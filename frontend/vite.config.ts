import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const backend = process.env.AGENTDASH_BACKEND ?? "http://localhost:8080";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api/ws": { target: backend.replace(/^http/, "ws"), ws: true },
      "/api": backend,
    },
  },
  build: { chunkSizeWarningLimit: 1500 },
  test: { environment: "node" },
});
