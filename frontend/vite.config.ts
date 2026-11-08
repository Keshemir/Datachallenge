import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    fs: {
      strict: true,
      allow: [fileURLToPath(new URL('.', import.meta.url))],
      deny: ['.env', '.env.*', '**/.secrets/**', '**/data/**', '**/tmp/**', '**/.git/**'],
    },
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
});
