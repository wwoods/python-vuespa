"""A combined Python + Vue.js Single Page Application (SPA) framework.

Example usage (from `vuespa/__init__.py`):

1. Write Python API:


        class Client(vuespa.Client):
            async def vuespa_on_open(self):
                print("Client connected!")

            # vuespa_on_close exists, too

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
              // Call a remote method, and return the result
              call: (fn: string, ...args: any[]) => Promise<any>,
              /** Set up a handler for HTTP endpoints. First argument is a function
                called whenever the websocket's identity changes. The second argument is
                a list of available handlers, each of which take one argument, which holds
                the query parameters given to the HTTP request.

                Returns: a function which, when called, unbinds the handler. Often,
                this belongs in Vue's ``beforeDestroy`` callback.
                */
              httpHandler: (cb: {(url: string): void}, fns: {[name: string]: {(args: any): void}}) => {(): void},
              // Call a remote method, and update `name` on this local Vue instance.
              update: (name: string, fn: string, ...args: any[]) => Promise<void>,
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
import random
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
            development=True, config_web_callback=None, max_msg_size=1024**3):
        """
        Args:
            vue_path: File system path to Vue application.
            client_class: Class (derived from `Client`) to instantiate per
                websocket connection.
            host: Host address to bind to.
            port: Port to listen on.
            development: True for Vue's development server; False to use the
                dist folder.
            config_web_callback: Callback which gets a `web.Application` object,
                to which additional routes may be added. Useful for bolting on
                plugins, often via IFrames which may communicate back with
                the main tab over ``$vuespa.httpHandler``. The benefits of this
                approach are that each plugin may be developed in any language
                or framework, and do not need knowledge of the hosting page.
                For ad hoc applications, this is occasionally useful.

                Note that an alternative for simple pages is to load the page's
                source code directly into the IFrame, with something like:

                      // CRUCIAL: blob does weird UTF-16 conversion.
                      // See https://blog.logrocket.com/binary-data-in-the-browser-untangling-an-encoding-mess-with-javascript-typed-arrays-119673c0f1fe/
                      // string must be in UTF-8
                      const u8 = new Uint8Array(newVal.length);
                      for (let i = 0, m = newVal.length; i < m; i++) {
                        u8[i] = newVal.charCodeAt(i);
                      }
                      (this.$refs.pluginIframe as any).src = URL.createObjectURL(new Blob([u8]));
            max_msg_size: Maximum websocket message size that the server should
                accept. Defaults to 1GB.
        """
        self._vue_path = vue_path
        self._client_class = client_class
        self._development = development
        self._config_web_callback = config_web_callback
        self._first_request = True
        self._host = host
        if self._host is None and development:
            # In e.g. Docker, 'localhost' would sometimes resolve to an IPV6
            # address which is unsupported by some modules.  Better to clarify
            # IPV4 support by using the localhost address directly.
            self._host = '127.0.0.1'
        self._port = port
        self._port_vue = None
        self._websocket_clients = {}
        self._max_msg_size = max_msg_size


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

        # Now, allow the websocket to receive messages via HTTP requests.
        # We want a new tab to be able to call '/api/blahws123/select?q=0096.pdf'
        # and have this websocket select the right tab.
        html_app.router.add_get('/vuespa.ws.http/{id}/{fn}',
                self._handle_vuespa_ws_http)
        html_app.router.add_post('/vuespa.ws.http/{id}/{fn}',
                self._handle_vuespa_ws_http)
        lame_response = lambda req: web.Response(content_type='text/plain',
                body='Add /fn?arg=8 to URL to call `fn` with `{arg: 8}`')
        html_app.router.add_get('/vuespa.ws.http/{id}', lame_response)
        html_app.router.add_post('/vuespa.ws.http/{id}', lame_response)

        if self._config_web_callback is not None:
            self._config_web_callback(html_app)

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
            if os.path.lexists(vue_config_path):
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
                ws_response = web.WebSocketResponse(
                        max_msg_size=self._max_msg_size)
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
                            VueSpaBackend.send(JSON.stringify({
                                type: 'clientIdRequest',
                                idOld: VueSpaBackend._clientId,
                            }));
                        };
                        ws.onerror = function(ev) {
                            console.log("WS error... will close and retry");
                            ws.close();
                        };
                        ws.onmessage = VueSpaBackend._onmessage;
                        ws.onclose = function(ev) {
                            // QoL for user on system suspend/resume, internet
                            // disconnect/reconnect... Don't actually wipe the
                            // clientId. Just set a flag that we're
                            // disconnected, and keep the same internal
                            // clientId. This keeps old tabs working, and as
                            // the websockets are relatively stateless,
                            // shouldn't have a problem picking back up.
                            VueSpaBackend._setClientId(VueSpaBackend._clientId,
                                    false);
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
                _getClientApiUrl: function() {
                    return new URL('vuespa.ws.http/' + VueSpaBackend._clientId,
                            window.location).href;
                },
                _setClientId: function(clientId, clientConnected) {
                    VueSpaBackend._clientId = clientId;
                    VueSpaBackend._clientConntected = clientConnected;

                    let value = this._getClientApiUrl();
                    if (!clientConnected) value = null;
                    for (const h of VueSpaBackend._httpHandlers) {
                        h[0](value);
                    }
                },
                _clientConnected: false,
                _clientId: null,
                _httpHandlers: [],
                _socket: null,
                _onmessage: function(event) {
                    let msg = JSON.parse(event.data);
                    if (msg.type === 'clientId') {
                        VueSpaBackend._setClientId(msg.id, true);
                    }
                    else if (msg.type === 'resp') {
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
                    else if (msg.type === 'http') {
                        let unhandled = true, error = null, result;
                        try {
                            for (const h of VueSpaBackend._httpHandlers) {
                                const hh = h[1];
                                if (!hh.hasOwnProperty(msg.fn)) {
                                    continue;
                                }

                                unhandled = false;
                                result = hh[msg.fn](msg.args);
                            }
                        }
                        catch (e) {
                            error = e;
                            console.error(e);
                        }
                        if (unhandled || error) {
                            if (unhandled) {
                                console.error(`No http callback for ${msg.fn}?`);
                                if (!error) {
                                    error = 'No http callback found.';
                                }
                            }
                            VueSpaBackend.send(JSON.stringify({
                                type: 'httpResp',
                                id: msg.id,
                                err: error,
                                result: null,
                            }));
                        }
                        else {
                            VueSpaBackend.send(JSON.stringify({
                                type: 'httpResp',
                                id: msg.id,
                                err: null,
                                result: result || null,
                            }));
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

                /** Creates a listener for handling HTTP requests.
                  */
                httpHandler(newIdCallback, methodsArray) {
                    const config = [newIdCallback, methodsArray];
                    VueSpaBackend._httpHandlers.push(config);
                    if (VueSpaBackend._clientId !== null)
                        config[0](VueSpaBackend._getClientApiUrl());
                    return () => {
                        VueSpaBackend._httpHandlers = VueSpaBackend._httpHandlers.filter(
                                (x) => x !== config);
                    };
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
        client_id = None
        try:
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
                        elif msg['type'] == 'clientIdRequest':
                            # Synchronization note: this would require a lock
                            # for threading; asyncio doesn't require a lock
                            # where there's no `await`.
                            maybe_client_id = msg['idOld']
                            while True:
                                if (maybe_client_id is not None
                                        and self._websocket_clients.get(maybe_client_id)
                                            is None):
                                    break
                                maybe_client_id = f'{random.getrandbits(128):032x}'
                            client_id = maybe_client_id
                            self._websocket_clients[client_id] = client

                            await websocket.send_str(json.dumps({
                                    'type': 'clientId',
                                    'id': client_id,
                            }))
                        elif msg['type'] == 'httpResp':
                            http_resp = client._socket_http_reqs[msg['id']]
                            http_resp['err'] = msg['err']
                            http_resp['result'] = msg['result']
                            http_resp['event'].set()
                        else:
                            raise NotImplementedError(msg['type'])
                    except:
                        _log.exception(f'When handling {msg} from {req.remote}')
                else:
                    _log.error(f'Cannot handle {msg} from {req.remote}')

            if hasattr(client, 'vuespa_on_close'):
                await client.vuespa_on_close()
        finally:
            if client_id is not None:
                del self._websocket_clients[client_id]
        return websocket


    async def _handle_vuespa_ws_http(self, req):
        ws_id = req.match_info['id']
        fn_id = req.match_info['fn']
        ws_client = self._websocket_clients.get(ws_id)
        if ws_client is None:
            raise web.HTTPNotFound()

        # Synchronization note: if threaded, this would need a lock. However,
        # asyncio doesn't need a lock for code which does not include "await".
        web_id = ws_client._socket_http_next
        ws_client._socket_http_next += 1
        ws_client._socket_http_reqs[web_id] = socket_req = {
                'event': asyncio.Event(),
                'result': None,
                'err': None,
        }
        try:
            args = dict(await req.post())
            args.update(req.query)
            await ws_client._socket.send_str(json.dumps({
                'type': 'http',
                'fn': fn_id,
                'id': web_id,
                'args': args,
            }))
            await socket_req['event'].wait()
        finally:
            del ws_client._socket_http_reqs[web_id]

        if socket_req['err'] is not None:
            raise web.HTTPServerError(body=socket_req['err'])

        return web.Response(body=socket_req['result'],
                content_type='application/json')



class Client:
    def __init__(self, socket):
        self._socket = socket
        self._socket_http_next = 0
        self._socket_http_reqs = {}

