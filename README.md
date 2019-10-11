# `vuespa`

A combined Python + Vue.js Single Page Application (SPA) framework.

Example usage (from `vuespa/__init__.py`):

1. Write Python API:


        class Client(vuespa.Client):
            async def vuespa_on_open(self):
                print("Client connected!")


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

