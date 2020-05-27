
import aiohttp.web as web
import vuespa

class Client(vuespa.Client):
    async def vuespa_on_open(self):
        print("Client connected!")
    async def api_shoe(self, arg1):
        return f'Got {arg1}'

async def handle_hello(req):
    return web.Response(body='Hello, world')
def config_web(app):
    app.router.add_get('/hello', handle_hello)
vuespa.VueSpa('1_basic_app_vue', Client, config_web_callback=config_web).run()

