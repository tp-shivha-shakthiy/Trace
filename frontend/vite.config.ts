import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the SPA runs on its own Vite server (default :5173) and
// proxies API/auth calls to the local FastAPI server (default :8000).
// In production the built assets are served by FastAPI itself (same origin),
// so every request target is relative and needs no explicit base URL.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});