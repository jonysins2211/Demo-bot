import re
import math
import time
import logging
import secrets
import mimetypes
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine

from FileStream.bot import multi_clients, work_loads
from FileStream.server.exceptions import FileNotFound, InvalidHash
from FileStream.utils.custom_dl import ByteStreamer
from FileStream.utils.render_template import render_page
from FileStream import StartTime, __version__
from helper_func import get_readable_time

# This is registered into the existing routes table from plugins/route.py
# so we use a separate RouteTableDef and merge it in plugins/__init__.py
stream_routes = web.RouteTableDef()

# Cache ByteStreamer instances per client to avoid re-creating sessions
_streamer_cache = {}

@stream_routes.get("/watch/{msg_id:\\d+}", allow_head=True)
async def watch_handler(request: web.Request):
    """
    Serve the HTML watch page for a file: /watch/{msg_id}?hash=...
    Opens in browser with Plyr player + external player buttons.
    """
    try:
        from config import CHANNEL_ID
        from bot import Bot
        msg_id = int(request.match_info["msg_id"])
        secure_hash = request.rel_url.query.get("hash", "")
        bot = Bot()
        html = await render_page(bot, CHANNEL_ID, msg_id, secure_hash)
        return web.Response(text=html, content_type="text/html")
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FileNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(e.with_traceback(None))
        raise web.HTTPInternalServerError(text=str(e))



@stream_routes.get("/stream/{msg_id:\\d+}", allow_head=True)
async def stream_handler(request: web.Request):
    """
    Stream endpoint: /stream/{msg_id}?hash={unique_id[:6]}
    Supports HTTP Range requests for seeking in video/audio players.
    """
    try:
        msg_id = int(request.match_info["msg_id"])
        secure_hash = request.rel_url.query.get("hash")
        return await _media_streamer(request, msg_id, secure_hash)
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message)
    except FileNotFound as e:
        raise web.HTTPNotFound(text=e.message)
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(e.with_traceback(None))
        raise web.HTTPInternalServerError(text=str(e))


@stream_routes.get("/stream_status", allow_head=True)
async def stream_status_handler(_):
    """Health / status endpoint for the streaming server."""
    from bot import Bot
    try:
        bot_username = "@" + (await Bot().get_me()).username
    except Exception:
        bot_username = "unknown"

    return web.json_response(
        {
            "server_status": "running",
            "uptime": get_readable_time(int(time.time() - StartTime)),
            "connected_clients": len(multi_clients),
            "client_loads": {
                f"client_{i + 1}": load
                for i, (_, load) in enumerate(
                    sorted(work_loads.items(), key=lambda x: x[1], reverse=True)
                )
            },
            "version": __version__,
        }
    )


async def _media_streamer(request: web.Request, msg_id: int, secure_hash: str):
    """Core streaming logic — resolves file, validates hash, streams bytes."""
    from config import CHANNEL_ID

    range_header = request.headers.get("Range", 0)

    # Pick the least-loaded client
    if multi_clients:
        index = min(work_loads, key=work_loads.get)
        client = multi_clients[index]
    else:
        # Fallback: use the single main Bot instance
        from bot import Bot
        index = 0
        client = Bot()
        if 0 not in work_loads:
            work_loads[0] = 0

    # Get or create a ByteStreamer for this client
    if client not in _streamer_cache:
        _streamer_cache[client] = ByteStreamer(client)
    tg_connect: ByteStreamer = _streamer_cache[client]

    file_id = await tg_connect.get_file_properties(CHANNEL_ID, msg_id)

    # Validate hash
    if secure_hash and file_id.unique_id[:6] != secure_hash:
        logging.debug(f"Hash mismatch for message {msg_id}")
        raise InvalidHash

    file_size = file_id.file_size

    # Parse Range header
    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = request.http_range.start or 0
        until_bytes = (request.http_range.stop or file_size) - 1

    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(
            status=416,
            body="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = 1024 * 1024  # 1 MB chunks
    until_bytes = min(until_bytes, file_size - 1)

    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1

    req_length = until_bytes - from_bytes + 1
    part_count = math.ceil(until_bytes / chunk_size) - math.floor(offset / chunk_size)

    body = tg_connect.yield_file(
        file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
    )

    # Resolve MIME type and filename
    mime_type = file_id.mime_type
    file_name = file_id.file_name
    disposition = "inline"  # inline so browsers/players open it directly

    if not mime_type:
        if file_name:
            mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        else:
            mime_type = "application/octet-stream"

    if not file_name:
        try:
            ext = mime_type.split("/")[1]
        except (IndexError, AttributeError):
            ext = "unknown"
        file_name = f"{secrets.token_hex(4)}.{ext}"

    # Use attachment for non-media types, or if ?download=1 is passed
    force_download = request.rel_url.query.get("download") == "1"
    if force_download or not any(mime_type.startswith(t) for t in ("video/", "audio/", "image/")):
        disposition = "attachment"

    return web.Response(
        status=206 if range_header else 200,
        body=body,
        headers={
            "Content-Type": mime_type,
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(req_length),
            "Content-Disposition": f'{disposition}; filename="{file_name}"',
            "Accept-Ranges": "bytes",
        },
    )
