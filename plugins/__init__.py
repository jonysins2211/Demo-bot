#(©)Codexbotz
#@iryme

import sys
import os

# Add the project root to sys.path so FileStream package is always resolvable
# This must happen here because plugins/__init__.py is imported before main.py
# finishes executing (Koyeb/Docker run from /workspace)
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from aiohttp import web
from .route import routes
from FileStream.server import stream_routes


async def web_server():
    web_app = web.Application(client_max_size=30000000)
    web_app.add_routes(routes)
    web_app.add_routes(stream_routes)  # File streaming endpoints
    return web_app
