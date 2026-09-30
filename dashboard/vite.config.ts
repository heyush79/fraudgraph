import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The config runs in Node; declared locally so the app's tsconfig does not
// need @types/node just for this one read.
declare const process: { env: Record<string, string | undefined> };

// Dev-only proxy: the dashboard is served from :5173 but the case service lives
// on :8082 and the analyst agent on :8010, so every backend path is proxied to
// keep the app same-origin (which is how it runs in production behind nginx).
const CASE_SERVICE = 'http://localhost:8082';
const AGENT = 'http://localhost:8010';
const http = { target: CASE_SERVICE, changeOrigin: true };

export default defineConfig({
  // '/' for nginx and dev; '/fraudgraph/' for the GitHub Pages replay build.
  // Replay files are fetched relative to it (import.meta.env.BASE_URL).
  base: process.env.VITE_BASE ?? '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/cases': http,
      '/stats': http,
      '/internal': http,
      // Plain WebSocket (not SockJS/STOMP) — needs ws: true to be tunnelled.
      '/ws': { target: CASE_SERVICE.replace(/^http/, 'ws'), ws: true, changeOrigin: true },
      // Same routing as nginx: /agent/* → the agent, prefix stripped.
      '^/agent(/|$)': {
        target: AGENT,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/agent/, '') || '/',
      },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
});
