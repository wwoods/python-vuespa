"""Example usage:

1. Write Python API:

    class Client(vuespa.Client):
        async def vuespa_on_open(self):
            print("Client connected")

        async def vuespa_on_close(self):
            print("Client disconnected")

        async def api_shoe(self, arg1):
            return f'Got {arg1}'

    vuespa.VueSpa.run('vue.app', Client)

2. Create app via ``vue create vue.app``.

3. Edit ``vue.app/src/main.ts`` (if typescript) with:

    declare var VueSpaBackend: any;
    Vue.use(VueSpaBackend);

4. Edit ``vue.app/public/index.html`` with:

    <script src="<%= BASE_URL %>vuespa.js"></script>

5. Run the Python script!
"""

import aiohttp
import aiohttp.web as web
import asyncio
import json
import logging
import os
import sys
import traceback
import webbrowser
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
        self._first_request = True


    def run(self):
        # Windows-compatible, with subprocess support:
        if sys.platform.startswith('win'):
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
        else:
            loop = asyncio.get_event_loop()

        html_app = web.Application()
        html_app.router.add_get('/vuespa.js', self._handle_vuespa_js)
        html_app.router.add_get('/{path:.*}', self._handle_vue)
        html_server = web._run_app(html_app, host=self.host,
                port=self.port)

        ws_server = loop.run_until_complete(websockets.serve(
                self._handle_ws, self.host, self.port+1))

        # Install node packages if no node_modules folder.
        if not os.path.lexists(os.path.join(self._vue_path, 'node_modules')):
            node_install = loop.run_until_complete(asyncio.create_subprocess_shell(
                'npm install', cwd=self._vue_path))
            loop.run_until_complete(node_install.communicate())

        promises = [html_server, ws_server]
        ui_proc = None
        if self._development:
            # Ensure node process is installed first.
            ui_proc = loop.run_until_complete(asyncio.create_subprocess_shell(
                "npx --no-install vue-cli-service serve --port 8080",
                cwd=self._vue_path))
            promises.append(ui_proc.communicate())
        elif not os.path.lexists(os.path.join(self._vue_path, 'dist')):
            # Build UI once, otherwise use cached version
            proc = loop.run_until_complete(asyncio.create_subprocess_shell(
                'npm run build', cwd=self._vue_path))
            loop.run_until_complete(proc.communicate())

        webbrowser.open(f'http://{self.host}:{self.port}')
        try:
            loop.run_until_complete(asyncio.wait(promises,
                    return_when=asyncio.FIRST_COMPLETED))
        finally:
            if ui_proc is not None:
                ui_proc.kill()
            ws_server.close()
            html_server.close()


    async def _handle_vue(self, req):
        path = req.match_info['path']

        if not self._development:
            # Fetch from "dist" folder
            if not path:
                path = 'index.html'
            ext = path.rsplit('.', 1)
            ctype = 'text/plain'
            if len(ext) == 2:
                ext = ext[1]
                if ext == 'css':
                    ctype = 'text/css'
                elif ext == 'js':
                    ctype = 'text/javascript'
                elif ext == 'html':
                    ctype = 'text/html'
            return web.Response(content_type=ctype,
                    body=open(os.path.join(self._vue_path, 'dist',
                        *path.split('/')), 'rb').read())
        elif (req.headers['connection'] == 'Upgrade'
                and req.headers['upgrade'] == 'websocket'
                and req.method == 'GET'):
            # Forward Vue's websocket?  Doesn't seem to actually hit this bit
            # of code.
            ws_response = web.WebSocketResponse()
            await ws_response.prepare(req)
            async with aiohttp.ClientSession().ws_connect(
                    f'ws://{self.host}:{self.vue_port}/{path}') as ws_client:
                async def ws_forward(ws_from, ws_to):
                    async for msg in ws_from:
                        mt = msg.type
                        md = msg.data
                        if mt == aiohttp.WSMsgType.TEXT:
                            await ws_to.send_str(md)
                        elif mt == aiohttp.WSMsgType.BINARY:
                            await ws_to.send_bytes(md)
                        elif mt == aiohttp.WSMsgType.PING:
                            await ws_to.ping()
                        elif mt == aiohttp.WSMsgType.PONG:
                            await ws_to.pong()
                        elif ws_to.closed:
                            await ws_to.close(code=ws_to.close_code,
                                    message=msg.extra)
                        else:
                            raise ValueError(f'Unknown ws message: {msg}')

                # keep forwarding websocket data until one side stops
                await asyncio.wait(
                        [
                            ws_forward(ws_response, ws_client),
                            ws_forward(ws_client, ws_response)],
                        return_when=asyncio.FIRST_COMPLETED)

            return ws_response
        else:
            # Fetch from vue http server
            async with aiohttp.ClientSession() as session:
                while True:
                    try:
                        async with session.get(
                                f'http://{self.host}:{self.vue_port}/{path}'
                                ) as response:
                            if self._first_request:
                                self._first_request = False

                            return web.Response(body=await response.read(),
                                    headers=response.headers.copy(),
                                    status=response.status)
                    except (aiohttp.client_exceptions.ClientConnectorError,
                            aiohttp.client_exceptions.ClientOSError):
                        if not self._first_request:
                            raise


    async def _handle_vuespa_js(self, req):
        ws_string = f'ws://{self.host}:{self.port+1}'
        body = """
            VueSpaBackend = {
                install: function(Vue) {
                    if (Object.hasOwnProperty(VueSpaBackend, 'installed')) {
                        return;
                    }
                    VueSpaBackend.installed = true;

                    Object.defineProperty(Vue.prototype, '$vuespa', {
                        get: function get () {
                            return new VueSpaBackendWrapper(this);
                        }
                    });

                    let ws;
                    function ws_retry() {
                        ws = VueSpaBackend._socket = new WebSocket('""" + ws_string + """');
                        ws.onopen = function(ev) {
                            console.log("WS open");
                        };
                        ws.onerror = function(ev) {
                            console.log("WS error... will close and retry");
                            ws.close();
                        };
                        ws.onmessage = VueSpaBackend._onmessage;
                        ws.onclose = function(ev) {
                            console.log("WS closed... will retry");
                            setTimeout(ws_retry, 3000);
                        };
                    }
                    ws_retry();
                },
                send: function(msg) {
                    if (VueSpaBackend._socket.readyState !== 1) {
                        setTimeout(function() { VueSpaBackend.send(msg); }, 300);
                        return;
                    }
                    VueSpaBackend._socket.send(msg);
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
                        VueSpaBackend.send(JSON.stringify({
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

                    api_meth = f'api_{meth}'

                    try:
                        _log.info(f'Calling {api_meth}(*{args})')
                        response = await getattr(client, api_meth)(*args)
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

