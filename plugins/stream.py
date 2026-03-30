from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot import Bot
from config import BASE_URL, CHANNEL_ID, STREAM_MODE
from FileStream.utils.file_properties import get_file_ids, get_media_from_message, get_hash


@Bot.on_callback_query(filters.regex(r"^generate_stream_link:(\d+)$"))
async def generate_stream_link_callback(client: Client, query: CallbackQuery):
    """
    Triggered when user clicks '🚀 Fast Download / Watch Online 🖥️'.
    Generates stream, watch, and download links on demand and sends them.
    """
    if not STREAM_MODE:
        await query.answer("Stream mode is currently disabled.", show_alert=True)
        return

    await query.answer("⏳ Generating links...")

    try:
        msg_id = int(query.matches[0].group(1))

        # Fetch file properties from the DB channel
        file_data = await get_file_ids(client, CHANNEL_ID, msg_id)
        file_hash = file_data.unique_id[:6]

        base = BASE_URL.rstrip("/")
        if not base.startswith("http"):
            base = f"https://{base}"

        stream_url   = f"{base}/stream/{msg_id}?hash={file_hash}"
        watch_url    = f"{base}/watch/{msg_id}?hash={file_hash}"
        download_url = f"{base}/stream/{msg_id}?hash={file_hash}&download=1"

        file_name = file_data.file_name or f"file_{msg_id}"

        await query.message.edit_text(
            text=(
                f"**🗂 ғɪʟᴇ:** `{file_name}`\n\n"
                f"**•• ʏᴏᴜʀ ʟɪɴᴋs ᴀʀᴇ ʀᴇᴀᴅʏ 👇**"
            ),
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎬 Watch Online", url=watch_url),
                ],
                [
                    InlineKeyboardButton("▶️ Stream", url=stream_url),
                    InlineKeyboardButton("⬇️ Download", url=download_url),
                ],
            ])
        )

    except Exception as e:
        print(f"[generate_stream_link] Error: {e}")
        await query.answer("❌ Failed to generate links. Try again.", show_alert=True)
