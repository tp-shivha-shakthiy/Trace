import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the SPA runs on its own Vite server (default :5173) and
// proxies API/auth calls to the local FastAPI server (default :8000).
// In production the built assets are served by FastAPI itself (same origin),
// so every request target is relative and needs no explicit base URL.
//
// changeOrigin must stay false: the backend builds the GitHub OAuth
// redirect/callback URIs from the incoming Host header. If the proxy rewrote
// it to :8000, the browser would be sent to GitHub with the wrong callback
// URI and bounced back to a port where the OAuth state cookie never exists.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: false },
      "/auth": { target: "http://localhost:8000", changeOrigin: false },
      "/health": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});