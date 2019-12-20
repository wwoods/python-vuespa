# `vuespa`

A combined Python + Vue.js Single Page Application (SPA) framework.

Example usage (from `vuespa/__init__.py`):

1. Write Python API:


        class Client(vuespa.Client):
            async def vuespa_on_open(self):
                print("Client connected!")


            async def api_shoe(self, arg1):
                return f'Got {arg1}'

        vuespa.VueSpa('vue.app', Client).run()

   Optionally, may specify `vuespa.VueSpa('vue.app', Client, port=8080).run()` to run on ports 8080, 8081, and 8082.

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

History:
* 2019-12-18 - 0.2.5 release built.  Better documentation (shows $vuespa.call), and randomly select port unless otherwise specified.
* 2019-10-21 - 0.2.3 release.

