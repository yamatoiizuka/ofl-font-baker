import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'path';
import pkg from './package.json' with { type: 'json' };

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [react(), tailwindcss()],
  root: path.resolve(__dirname, 'app/renderer'),
  base: './',
  build: {
    outDir: path.resolve(__dirname, 'dist/renderer'),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // Ensure wasm files are emitted as assets
        assetFileNames: 'assets/[name].[hash][extname]',
      },
    },
  },
  optimizeDeps: {
    exclude: ['harfbuzzjs'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'app'),
    },
  },
  server: {
    port: 5173,
  },
});
