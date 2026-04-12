import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
  build: {
    lib: {
      entry: path.resolve(__dirname, 'app/preload/index.ts'),
      formats: ['cjs'],
      fileName: () => 'index.js',
    },
    outDir: 'dist/preload',
    rollupOptions: {
      external: ['electron'],
    },
    minify: false,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'app'),
    },
  },
});
