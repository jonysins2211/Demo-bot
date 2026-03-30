import sys
import os

# Ensure the workspace root is on the path so 'FileStream' package is found
# regardless of which directory Python is launched from (Koyeb, Heroku, Docker, etc.)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot import Bot
import pyrogram.utils

pyrogram.utils.MIN_CHANNEL_ID = -1009147483647

if __name__ == "__main__":
    Bot().run()
