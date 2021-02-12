# `vuespa`

A combined Python + Vue.js Single Page Application (SPA) framework.

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

History:
* 2021-02-11 - 0.3.7 release. If neither host nor port is specified, 'localhost' will be used as the host (resulting in a random port being selected).
* 2021-02-11 - 0.3.6 release. Default bind to IPv4 and IPv6, and documentation update. Some docker containers were having issues as docker now will not translate an IPv6 request to an IPv4 one.
* 2020-10-07 - 0.3.5 release. Support JSON body in XMLHttpRequest for GET/POST interactions, which is less confusing than encodeURIComponent with a query string.
* 2020-06-03 - 0.3.4 release. Better support for applications tunneled over a proxy.
* 2020-06-01 - 0.3.3 release. Larger websocket messages allowed to server by default.
* 2020-05-28 - 0.3.1 release. Fixes for websockets, mostly documentation, but also page load race condition.
* 2020-05-27 - 0.2.9 release. Websockets may now receive interactions via HTTP GET/POST requests, to allow child tabs from a Vuespa application to direct the parent tab. This is useful primarily for plugins, which execute code uncontrolled by the core application author, and might execute in an IFrame. Additionally, a `config_web_callback` method has been added which allows for registering arbitrary HTTP endpoints.
* 2020-04-02 - 0.2.8 release.  Production mode no longer runs 'npm install' if dist folder exists already.
* 2020-02-04 - 0.2.7 release.  Fixed an error from moving to aiohttp websocket.  Fixed vue serve hot reloading.
* 2020-01-06 - 0.2.6 release.  A few things:
  * Use IPv4 host by default, since e.g. Docker has issues with IPv6.
  * Only use one port (instead of one for HTTP and a separate port for websocket).  This is to make Docker usage easier.  Note that for development, the Vue development port will not be forwarded by default.
* 2019-12-18 - 0.2.5 release built.  Better documentation (shows $vuespa.call), and randomly select port unless otherwise specified.
* 2019-10-21 - 0.2.3 release.

