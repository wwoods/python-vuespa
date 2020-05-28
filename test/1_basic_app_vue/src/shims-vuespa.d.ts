import Vue from 'vue';
declare module 'vue' {
  export default interface Vue {
    $vuespa: {
      call: (fn: string, ...args: any[]) => Promise<any>,
      httpHandler: (cb: {(url: string): void}, fns: {[name: string]: {(args: any): void}}) => {(): void},
      update: (name: string, fn: string, ...args: any[]) => Promise<void>,
    };
  }
}
