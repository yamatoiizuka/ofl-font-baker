declare module 'harfbuzzjs/hb.js' {
  function createHarfBuzz(config?: any): Promise<any>;
  export default createHarfBuzz;
}

declare module 'harfbuzzjs/hbjs.js' {
  function hbjs(wasmModule: any): any;
  export default hbjs;
}

declare module 'harfbuzzjs/hb.wasm?url' {
  const url: string;
  export default url;
}
