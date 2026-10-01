import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the Vite server proxies /api (HTTP and WebSocket) to the FastAPI service,
// so the browser always talks to one origin, exactly like production behind Caddy.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.SIQE_API_URL ?? "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
    // Served from the user's own machine, so a ~190 kB gzipped entry is fine; revisit when
    // the heavy workspaces (Studio, Forge) land and get route-level code splitting.
    chunkSizeWarningLimit: 800,
  },
});
