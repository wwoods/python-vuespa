<template>
  <div class="hello">
    <h1>{{ msg }}</h1>
    <h1>Vuespa delay on 10x0.2-second sleeps was: {{ vuespaDelayed }}</h1>
    <p> Vuespa says {{ vuespa }}; POST url is <a :href="vuespaUrl">{{ vuespaUrl }}</a> </p>
    <p>
      For a guide and recipes on how to configure / customize this project,<br>
      check out the
      <a href="https://cli.vuejs.org" target="_blank" rel="noopener">vue-cli documentation</a>.
    </p>
    <h3>Installed CLI Plugins</h3>
    <ul>
      <li><a href="https://github.com/vuejs/vue-cli/tree/dev/packages/%40vue/cli-plugin-typescript" target="_blank" rel="noopener">typescript</a></li>
    </ul>
    <h3>Essential Links</h3>
    <ul>
      <li><a href="https://vuejs.org" target="_blank" rel="noopener">Core Docs</a></li>
      <li><a href="https://forum.vuejs.org" target="_blank" rel="noopener">Forum</a></li>
      <li><a href="https://chat.vuejs.org" target="_blank" rel="noopener">Community Chat</a></li>
      <li><a href="https://twitter.com/vuejs" target="_blank" rel="noopener">Twitter</a></li>
      <li><a href="https://news.vuejs.org" target="_blank" rel="noopener">News</a></li>
    </ul>
    <h3>Ecosystem</h3>
    <ul>
      <li><a href="https://router.vuejs.org" target="_blank" rel="noopener">vue-router</a></li>
      <li><a href="https://vuex.vuejs.org" target="_blank" rel="noopener">vuex</a></li>
      <li><a href="https://github.com/vuejs/vue-devtools#vue-devtools" target="_blank" rel="noopener">vue-devtools</a></li>
      <li><a href="https://vue-loader.vuejs.org" target="_blank" rel="noopener">vue-loader</a></li>
      <li><a href="https://github.com/vuejs/awesome-vue" target="_blank" rel="noopener">awesome-vue</a></li>
    </ul>
  </div>
</template>

<script lang="ts">
import Vue from 'vue';

export default Vue.extend({
  name: 'HelloWorld',
  props: {
    msg: String,
  },
  data() {
    return {
      vuespa: 'waiting...',
      vuespaDelayed: 'waiting...',
      vuespaUrl: null as null | string,
    };
  },
  mounted() {
    this.$vuespa.update('vuespa', 'shoe', {some: 'data'});
    this.$vuespa.httpHandler(
        (v: string) => {this.vuespaUrl = v;},
        {showFile: (args: any) => {console.log(args);}},
    );

    (async () => {
      const before = Date.now();
      const promises = Array.from(Array(10).keys()).map(x => this.$vuespa.call('delay', 0.2));
      await Promise.all(promises);
      this.vuespaDelayed = `Took ${1e-3 * (Date.now() - before)} seconds`;
    })().then(console.log);
  }
});
</script>

<!-- Add "scoped" attribute to limit CSS to this component only -->
<style scoped>
h3 {
  margin: 40px 0 0;
}
ul {
  list-style-type: none;
  padding: 0;
}
li {
  display: inline-block;
  margin: 0 10px;
}
a {
  color: #42b983;
}
</style>
