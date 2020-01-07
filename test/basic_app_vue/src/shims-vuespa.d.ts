import Vue from 'vue';
declare module 'vue' {
  export default interface Vue {
    $vuespa: {
      call: (fn: string, ...args: any[]),
      update: (name: string, fn: string, ...args: any[]),
    };
  }
}
