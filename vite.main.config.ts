import { defineConfig } from 'vite';
import path from 'path';
import pkg from './package.json' with { type: 'json' };

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
      external: ['electron', 'child_process', 'path', 'fs'],
    },
    minify: false,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'app'),
    },
  },
});
