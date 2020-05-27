import Vue from 'vue'
import App from './App.vue'

declare var VueSpaBackend: any;
Vue.use(VueSpaBackend);

Vue.config.productionTip = false

new Vue({
  render: h => h(App),
}).$mount('#app')
