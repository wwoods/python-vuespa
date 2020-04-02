"""Example usage:

1. Write Python API:


        class Client(vuespa.Client):
            async def vuespa_on_open(self):
                print("Client connected!")


            async def api_shoe(self, arg1):
                return f'Got {arg1}'

        vuespa.VueSpa('vue.app', Client).run()

   Optionally, may specify `vuespa.VueSpa('vue.app', Client, port=8080).run()` to run on ports 8080 (webserver and websocket) and 8081 (Vue dev server).

2. Create app via ``vue create vue.app``.

3. Edit ``vue.app/src/main.ts`` (if typescript) with:

        declare var VueSpaBackend: any;
        Vue.use(VueSpaBackend);

4. Edit ``vue.app/public/index.html`` with:

        <script src="<%= BASE_URL %>vuespa.js"></script>

5. Create ``vue.app/src/shims-vuespa.d.ts``, to silence Typescript errors, with:

        import Vue from 'vue';
        declare module 'vue' {
          export default interface Vue {
            $vuespa: {
              call: (fn: string, ...args: any[]),
              update: (name: string, fn: string, ...args: any[]),
            };
          }
        }

6. Add calls to the server as:

    await this.$vuespa.call('shoe', 32)

7. Run the Python script!  This will build the Vue application, run a Python web server on a random port, and point your web browser at the deployment.

As a shortcut in e.g. template callbacks, can use `$vuespa.update('propName', 'shoe', 32)` to place the call to `api_shoe` and then set the resulting value in `propName`.
"""

import aiohttp
import aiohttp.web as web
import asyncio
import json
import logging
import os
import re
import sys
import traceback
import webbrowser

_log = logging.getLogger('vuespa')

class VueSpa:
    @property
    def host(self):
        return self._host

    @property
    def port(self):
        return self._port

    @property
    def port_vue(self):
        return self._port_vue

    def __init__(self, vue_path, client_class, host=None, port=None,
            development=True):
        self._vue_path = vue_path
        self._client_class = client_class
        self._development = development
        self._first_request = True
        self._host = host
        if self._host is None and development:
            # In e.g. Docker, 'localhost' would sometimes resolve to an IPV6
            # address which is unsupported by some modules.  Better to clarify
            # IPV4 support by using the localhost address directly.
            self._host = '127.0.0.1'
        self._port = port
        self._port_vue = None


    def run(self):
        # Windows-compatible, with subprocess support:
        if sys.platform.startswith('win'):
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
        else:
            loop = asyncio.get_event_loop()

        html_app = web.Application()
        html_app.router.add_get('/vuespa.js', self._handle_vuespa_js)
        html_app.router.add_get('/vuespa.ws', self._handle_vuespa_ws)
        html_app.router.add_get('/{path:.*}', self._handle_vue)
        html_app.router.add_post('/{path:.*}', self._handle_vue)

        # Run the application on a randomly selected port (or specified port)
        if self._port is not None:
            self._port_vue = self._port + 1
        html_server_handler = html_app.make_handler()
        html_server = loop.run_until_complete(
                loop.create_server(html_server_handler, self.host, self._port))
        self._port = html_server.sockets[0].getsockname()[1]

        dist_exists = os.path.lexists(os.path.join(self._vue_path, 'dist'))
        needs_npm_mod = self._development or not dist_exists

        # Install node packages if no node_modules folder.
        if (
                needs_npm_mod
                and not os.path.lexists(os.path.join(
                    self._vue_path, 'node_modules'))):
            node_install = loop.run_until_complete(asyncio.create_subprocess_shell(
                'npm install', cwd=self._vue_path))
            loop.run_until_complete(node_install.communicate())

        promises = []
        ui_proc = None
        if self._development:
            # Ensure node process is installed first.

            # BUT FIRST, work around excessive websocket closing.
            # See https://github.com/vuejs-templates/webpack/issues/1205
            vue_config_path = os.path.join(self._vue_path, 'vue.config.js')
            with open(vue_config_path) as f:
                js_src = f.read()
            js_pat = r'(module\.exports *= *)(.*)'
            m = re.search(js_pat, js_src, flags=re.M | re.DOTALL)
            if m is not None:
                try:
                    j = json.loads(m.group(2))
                except:
                    raise ValueError(f"Looks like {vue_config_path} has invalid JSON: {m.group(2)}")
                if not j.get('devServer', {}).get('disableHostCheck', False):
                    j.setdefault('devServer', {})
                    j['devServer']['disableHostCheck'] = True
                    with open(vue_config_path, 'w') as f:
                        f.write(re.sub(js_pat,
                            lambda m: m.group(1) + json.dumps(j, indent=2),
                            js_src,
                            flags=re.M | re.DOTALL))

            ui_proc = loop.run_until_complete(asyncio.create_subprocess_shell(
                f"FORCE_COLOR=1 npx --no-install vue-cli-service serve",
                stdout=asyncio.subprocess.PIPE,
                # Leave stderr connected
                cwd=self._vue_path))

            # We need to get the port first, so read lines from stdout until we
            # find that information.  Then, communicate.
            async def streamer(stream_in, stream_out, re_stop=None):
                """Returns `None` on process exit, or a regex Match object.
                """
                while True:
                    line = await stream_in.readline()
                    if not line:
                        break
                    line = line.decode()
                    stream_out.write(line)
                    if re_stop is not None:
                        m = re.search(re_stop, line)
                        if m is not None:
                            return m
            m = loop.run_until_complete(streamer(ui_proc.stdout,
                sys.stdout,
                # Note that regex looks weird because we must strip color code
                re_stop=re.compile('- Local: .*?http://[^:]+:\x1b\\[[^m]*m(?P<port>\d+)')))
            self._port_vue = int(m.group('port'))
            promises.append(streamer(ui_proc.stdout, sys.stdout))
            promises.append(ui_proc.wait())
        elif not dist_exists:
            # Build UI once, otherwise use cached version
            proc = loop.run_until_complete(asyncio.create_subprocess_shell(
                'npm run build', cwd=self._vue_path))
            loop.run_until_complete(proc.communicate())

        webbrowser.open(f'http://{self.host}:{self.port}')
        try:
            # Terminate either when a child process terminates OR when a
            # KeyboardInterrupt is sent.
            if promises:
                loop.run_until_complete(asyncio.wait(promises,
                        return_when=asyncio.FIRST_COMPLETED))
            else:
                # Nothing will terminate early.
                loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if ui_proc is not None:
                ui_proc.kill()
            html_server.close()
            loop.run_until_complete(html_server.wait_closed())


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
        elif 'Upgrade' in req.headers:
            # Forward Vue's websocket.
            async with aiohttp.ClientSession() as session:
                ws_response = web.WebSocketResponse()
                await ws_response.prepare(req)

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

                async with session.ws_connect(
                        f'ws://{self.host}:{self.port_vue}/{path}'
                        ) as ws_client:
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
                        async with session.request(
                                req.method,
                                f'http://{self.host}:{self.port_vue}/{path}',
                                headers=req.headers,
                                params=req.rel_url.query,
                                data = await req.read(),
                                ) as response:
                            if self._first_request:
                                self._first_request = False

                            body = await response.read()
                            headers = response.headers.copy()
                            if 'Transfer-Encoding' in headers:
                                del headers['Transfer-Encoding']
                                headers['Content-Length'] = str(len(body))
                            return web.Response(body=body,
                                    headers=headers,
                                    status=response.status)
                    except (aiohttp.client_exceptions.ClientConnectorError,
                            aiohttp.client_exceptions.ClientOSError):
                        if not self._first_request:
                            raise


    async def _handle_vuespa_js(self, req):
        ws_string = f'ws://{self.host}:{self.port}/vuespa.ws'
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


    async def _handle_vuespa_ws(self, req):
        websocket = web.WebSocketResponse()
        await websocket.prepare(req)

        client = self._client_class(websocket)
        if hasattr(client, 'vuespa_on_open'):
            await client.vuespa_on_open()

        async for msg in websocket:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    msg = json.loads(msg.data)
                    if msg['type'] == 'call':
                        call_id = msg['id']
                        meth = msg['meth']
                        args = msg['args']

                        api_meth = f'api_{meth}'

                        try:
                            _log.info(f'Calling {api_meth}(*{args})')
                            response = await getattr(client, api_meth)(*args)
                            await websocket.send_str(json.dumps({
                                    'type': 'resp',
                                    'id': call_id,
                                    'r': response,
                            }))
                        except:
                            await websocket.send_str(json.dumps({
                                    'type': 'resp',
                                    'id': call_id,
                                    'err': traceback.format_exc()
                            }))
                            raise
                    else:
                        raise NotImplementedError(msg['type'])
                except:
                    _log.exception(f'When handling {msg} from {req.remote}')
            else:
                _log.error(f'Cannot handle {msg} from {req.remote}')

        if hasattr(client, 'vuespa_on_close'):
            await client.vuespa_on_close()
        return websocket



class Client:
    def __init__(self, socket):
        self._socket = socket

