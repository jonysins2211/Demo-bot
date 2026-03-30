import math
import asyncio
import logging
from typing import Dict, Union
from pyrogram import Client, utils, raw
from pyrogram.session import Session, Auth
from pyrogram.errors import AuthBytesInvalid
from pyrogram.file_id import FileId, FileType, ThumbnailSource
from FileStream.server.exceptions import FileNotFound
from FileStream.utils.file_properties import get_file_ids
from FileStream.bot import work_loads


class ByteStreamer:
    def __init__(self, client: Client):
        """
        Holds a per-client cache and streams Telegram media bytes via raw API.
        Adapted from https://github.com/eyaadh/megadlbot_oss
        """
        self.clean_timer = 30 * 60  # 30 minutes
        self.client: Client = client
        self.cached_file_ids: Dict[int, FileId] = {}
        asyncio.create_task(self.clean_cache())

    async def get_file_properties(self, channel_id: int, msg_id: int) -> FileId:
        """Return cached FileId or generate and cache it."""
        cache_key = msg_id
        if cache_key not in self.cached_file_ids:
            await self.generate_file_properties(channel_id, msg_id)
            logging.debug(f"Cached file properties for message {msg_id}")
        return self.cached_file_ids[cache_key]

    async def generate_file_properties(self, channel_id: int, msg_id: int) -> FileId:
        """Fetch file properties from Telegram and cache them."""
        file_id = await get_file_ids(self.client, channel_id, msg_id)
        if not file_id:
            logging.debug(f"Message {msg_id} not found in channel {channel_id}")
            raise FileNotFound
        self.cached_file_ids[msg_id] = file_id
        logging.debug(f"Cached media message {msg_id}")
        return self.cached_file_ids[msg_id]

    async def generate_media_session(self, client: Client, file_id: FileId) -> Session:
        """Create or reuse a media session for the DC that holds the file."""
        media_session = client.media_sessions.get(file_id.dc_id, None)

        if media_session is None:
            if file_id.dc_id != await client.storage.dc_id():
                media_session = Session(
                    client,
                    file_id.dc_id,
                    await Auth(
                        client, file_id.dc_id, await client.storage.test_mode()
                    ).create(),
                    await client.storage.test_mode(),
                    is_media=True,
                )
                await media_session.start()

                for _ in range(6):
                    exported_auth = await client.invoke(
                        raw.functions.auth.ExportAuthorization(dc_id=file_id.dc_id)
                    )
                    try:
                        await media_session.send(
                            raw.functions.auth.ImportAuthorization(
                                id=exported_auth.id, bytes=exported_auth.bytes
                            )
                        )
                        break
                    except AuthBytesInvalid:
                        logging.debug(f"Invalid auth bytes for DC {file_id.dc_id}")
                        continue
                else:
                    await media_session.stop()
                    raise AuthBytesInvalid
            else:
                media_session = Session(
                    client,
                    file_id.dc_id,
                    await client.storage.auth_key(),
                    await client.storage.test_mode(),
                    is_media=True,
                )
                await media_session.start()

            logging.debug(f"Created media session for DC {file_id.dc_id}")
            client.media_sessions[file_id.dc_id] = media_session
        else:
            logging.debug(f"Reusing cached media session for DC {file_id.dc_id}")

        return media_session

    @staticmethod
    async def get_location(
        file_id: FileId,
    ) -> Union[
        raw.types.InputPhotoFileLocation,
        raw.types.InputDocumentFileLocation,
        raw.types.InputPeerPhotoFileLocation,
    ]:
        """Resolve the Telegram file location object from a FileId."""
        file_type = file_id.file_type

        if file_type == FileType.CHAT_PHOTO:
            if file_id.chat_id > 0:
                peer = raw.types.InputPeerUser(
                    user_id=file_id.chat_id, access_hash=file_id.chat_access_hash
                )
            else:
                if file_id.chat_access_hash == 0:
                    peer = raw.types.InputPeerChat(chat_id=-file_id.chat_id)
                else:
                    peer = raw.types.InputPeerChannel(
                        channel_id=utils.get_channel_id(file_id.chat_id),
                        access_hash=file_id.chat_access_hash,
                    )
            location = raw.types.InputPeerPhotoFileLocation(
                peer=peer,
                volume_id=file_id.volume_id,
                local_id=file_id.local_id,
                big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG,
            )
        elif file_type == FileType.PHOTO:
            location = raw.types.InputPhotoFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size,
            )
        else:
            location = raw.types.InputDocumentFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size,
            )
        return location

    async def yield_file(
        self,
        file_id: FileId,
        index: int,
        offset: int,
        first_part_cut: int,
        last_part_cut: int,
        part_count: int,
        chunk_size: int,
    ) -> Union[bytes, None]:
        """
        Async generator that yields the requested byte range of a Telegram file.
        Handles partial content (Range requests) correctly.
        """
        client = self.client
        work_loads[index] += 1
        logging.debug(f"Streaming file with client index {index}")
        media_session = await self.generate_media_session(client, file_id)

        current_part = 1
        location = await self.get_location(file_id)

        try:
            r = await media_session.send(
                raw.functions.upload.GetFile(
                    location=location, offset=offset, limit=chunk_size
                ),
            )
            if isinstance(r, raw.types.upload.File):
                while True:
                    chunk = r.bytes
                    if not chunk:
                        break
                    elif part_count == 1:
                        yield chunk[first_part_cut:last_part_cut]
                    elif current_part == 1:
                        yield chunk[first_part_cut:]
                    elif current_part == part_count:
                        yield chunk[:last_part_cut]
                    else:
                        yield chunk

                    current_part += 1
                    offset += chunk_size

                    if current_part > part_count:
                        break

                    r = await media_session.send(
                        raw.functions.upload.GetFile(
                            location=location, offset=offset, limit=chunk_size
                        ),
                    )
        except (TimeoutError, AttributeError):
            pass
        finally:
            logging.debug(f"Finished streaming after {current_part} parts.")
            work_loads[index] -= 1

    async def clean_cache(self) -> None:
        """Periodically clear file ID cache to free memory."""
        while True:
            await asyncio.sleep(self.clean_timer)
            self.cached_file_ids.clear()
            logging.debug("File ID cache cleared.")
