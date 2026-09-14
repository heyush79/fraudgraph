import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev-only proxy: the dashboard is served from :5173 but the case-service lives
// on :8082, so every backend path is proxied to keep the app same-origin (which
// is how it runs in production behind nginx).
const CASE_SERVICE = 'http://localhost:8082';
const http = { target: CASE_SERVICE, changeOrigin: true };

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/cases': http,
      '/stats': http,
      '/internal': http,
      // Plain WebSocket (not SockJS/STOMP) — needs ws: true to be tunnelled.
      '/ws': { target: CASE_SERVICE.replace(/^http/, 'ws'), ws: true, changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
});
