"""Example usage:

1. Write Python API:

    class Client(vuespa.Client):
        async def vuespa_on_open(self):
            print("Client connected!")


        async def shoe(self, arg1):
            return f'Got {arg1}'

    vuespa.VueSpa.run('vue.app', Client)

2. Create app via ``vue create vue.app``.

3. Edit ``vue.app/src/main.ts`` (if typescript) with:

    declare var VueSpaBackend:any;
    Vue.use(VueSpaBackend);

4. Edit ``vue.app/public/index.html`` with:

    <script src="<%= BASE_URL %>vuespa.js"></script>

5. Run the Python script!
"""

import aiohttp
import aiohttp.web as web
import asyncio
import async_timeout
import json
import logging
import traceback
import websockets

_log = logging.getLogger('vuespa')

class VueSpa:
    vue_port = 8080

    @property
    def host(self):
        return 'localhost'

    @property
    def port(self):
        return 8000

    def __init__(self, vue_path, client_class, development=True):
        self._vue_path = vue_path
        self._client_class = client_class
        self._development = development


    def run(self):
        loop = asyncio.get_event_loop()

        html_app = web.Application()
        html_app.router.add_get('/vuespa.js', self._handle_vuespa_js)
        html_app.router.add_get('/{path:.*}', self._handle_vue)
        html_server = web._run_app(html_app, host=self.host,
                port=self.port)

        ws_server = loop.run_until_complete(websockets.serve(
                self._handle_ws, self.host, self.port+1))

        if self._development:
            print("** for now, run 'npm run serve' to get vue running in "
                    "development mode.")

        try:
            loop.run_until_complete(html_server)
        finally:
            ws_server.close()
            html_server.close()


    async def _handle_vue(self, req):
        path = req.match_info['path']

        if not self._development:
            # Fetch from "dist" folder
            raise NotImplementedError("TODO")
            ext = path.rsplit('.', 1)
            ctype = 'text/plain'
            if len(ext) == 2:
                ext = ext[1]
                if ext == 'css':
                    ctype = 'text/css'
                elif ext == 'js':
                    ctype = 'text/javascript'
            return ctype, open(os.path.join('dist', *path.split('/')), 'rb').read()
        else:
            # Fetch from vue http server
            async with aiohttp.ClientSession() as session:
                with async_timeout.timeout(10):
                    async with session.get(f'http://{self.host}:{self.vue_port}/{path}') as response:
                        ctype = response.headers['Content-Type'].split(';', 1)[0]
                        return web.Response(body=await response.read(),
                                content_type=ctype)


    async def _handle_vuespa_js(self, req):
        ws_string = f'ws://{self.host}:{self.port+1}'
        body = """
            VueSpaBackend = {
                install: function(Vue) {
                    Object.defineProperty(Vue.prototype, '$vuespa', {
                        get: function get () {
                            return new VueSpaBackendWrapper(this);
                        }
                    });

                    var ws = VueSpaBackend._socket = new WebSocket('""" + ws_string + """');
                    ws.onmessage = VueSpaBackend._onmessage;
                },
                _socket: null,
                _onmessage: function(event) {
                    let msg = JSON.parse(event.data);
                    if (msg.type === 'resp') {
                        let p = VueSpaBackend._pending;
                        let callbacks = p.get(msg.id);
                        if (callbacks === undefined) {
                            console.error(`No callbacks for ${msg.id}?`);
                            return;
                        }

                        p.delete(msg.id);
                        if (msg.err !== undefined) {
                            callbacks[1](msg.err);
                        }
                        else {
                            callbacks[0](msg.r);
                        }
                    }
                    else {
                        console.error(`Invalid message: ${msg.type}`);
                    }
                },
                _pending: new Map(),
                _pendingNext: 0,
            };
            class VueSpaBackendWrapper {
                constructor(obj) {
                    this._obj = obj;
                }
                async call(meth, ...args) {
                    let id = VueSpaBackend._pendingNext++;
                    let p = new Promise((resolve, reject) => {
                        VueSpaBackend._pending.set(id, [resolve, reject]);
                        VueSpaBackend._socket.send(JSON.stringify({
                            type: 'call',
                            id, meth, args,
                        }));
                    });
                    return await p;
                }
                async update(prop, meth, ...args) {
                    this._obj[prop] = await this.call(meth, ...args);
                }
            }
        """
        return web.Response(body=body, content_type='text/javascript')


    async def _handle_ws(self, websocket, path):
        client = self._client_class(websocket)
        if hasattr(client, 'vuespa_on_open'):
            await client.vuespa_on_open()

        async for msg in websocket:
            try:
                msg = json.loads(msg)
                if msg['type'] == 'call':
                    call_id = msg['id']
                    meth = msg['meth']
                    args = msg['args']

                    try:
                        if meth.startswith('vuespa_'):
                            raise ValueError('Cannot remotely call vuespa_*')
                        _log.info(f'Calling {meth}(*{args})')
                        response = await getattr(client, meth)(*args)
                        await websocket.send(json.dumps({
                                'type': 'resp',
                                'id': call_id,
                                'r': response,
                        }))
                    except:
                        await websocket.send(json.dumps({
                                'type': 'resp',
                                'id': call_id,
                                'err': traceback.format_exc()
                        }))
                        raise
                else:
                    raise NotImplementedError(msg['type'])
            except:
                _log.exception(f'When handling {msg} from {websocket.remote_address}')

        if hasattr(client, 'vuespa_on_close'):
            await client.vuespa_on_close()



class Client:
    def __init__(self, socket):
        self._socket = socket

