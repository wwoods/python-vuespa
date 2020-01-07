
import vuespa

class Client(vuespa.Client):
    async def vuespa_on_open(self):
        print("Client connected!")
    async def api_shoe(self, arg1):
        return f'Got {arg1}'

vuespa.VueSpa('basic_app_vue', Client).run()

