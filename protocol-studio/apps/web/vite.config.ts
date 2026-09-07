import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API + auth to the FastAPI app so cookies are same-origin.
// In production the API serves `dist/` itself (PS_WEB_DIST), so no proxy is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8080",
      "/auth": "http://localhost:8080",
      "/healthz": "http://localhost:8080",
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
