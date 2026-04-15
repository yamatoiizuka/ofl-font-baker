import { defineConfig } from 'vite';
import path from 'path';
import { builtinModules } from 'module';
import pkg from './package.json' with { type: 'json' };

// Keep Node built-ins and runtime-resolved npm deps out of the bundle.
// Vite/Rollup otherwise stubs `require('events')` etc. with a browser shim,
// which breaks `class extends EventEmitter` inside electron-updater and its
// transitive deps. These packages are shipped inside the asar via
// electron-builder, so they resolve at runtime.
const nodeBuiltins = [
  ...builtinModules,
  ...builtinModules.map((m) => `node:${m}`),
];

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  build: {
    lib: {
      entry: path.resolve(__dirname, 'app/main/index.ts'),
      formats: ['cjs'],
      fileName: () => 'index.js',
    },
    outDir: 'dist/main',
    rollupOptions: {
      external: ['electron', 'electron-updater', ...nodeBuiltins],
    },
    minify: false,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'app'),
    },
  },
});
