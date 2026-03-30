import os
import jinja2
from config import BASE_URL
from FileStream.utils.file_properties import get_file_ids
from FileStream.server.exceptions import InvalidHash


def _humanbytes(size: int) -> str:
    """Convert bytes to human-readable string."""
    if not size:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


async def render_page(bot, channel_id: int, msg_id: int, secure_hash: str) -> str:
    """
    Render the watch.html template for a given Telegram message.
    Returns the rendered HTML string.
    Raises InvalidHash if the hash doesn't match.
    """
    file_data = await get_file_ids(bot, channel_id, msg_id)

    if file_data.unique_id[:6] != secure_hash:
        raise InvalidHash

    base = BASE_URL.rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"

    file_url = f"{base}/stream/{msg_id}?hash={secure_hash}"

    mime_type = file_data.mime_type or "application/octet-stream"
    media_type = mime_type.split("/")[0]   # "video", "audio", "image", etc.

    template_path = os.path.join(
        os.path.dirname(__file__), "..", "template", "watch.html"
    )
    with open(template_path, encoding="utf-8") as f:
        template = jinja2.Template(f.read())

    # Try to get bot username for footer link
    try:
        bot_username = bot.username or ""
    except Exception:
        bot_username = ""

    return template.render(
        file_name=file_data.file_name or f"file_{msg_id}",
        file_url=file_url,
        file_size=_humanbytes(file_data.file_size),
        mime_type=mime_type,
        media_type=media_type,
        bot_username=bot_username,
    )
