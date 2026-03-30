#(©)Codexbotz
#@iryme





from aiohttp import web
from .route import routes
from FileStream.server import stream_routes


async def web_server():
    web_app = web.Application(client_max_size=30000000)
    web_app.add_routes(routes)
    web_app.add_routes(stream_routes)  # File streaming endpoints
    return web_app
