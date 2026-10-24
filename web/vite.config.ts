import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", chunkSizeWarningLimit: 1200 },
  server: {
    // dev 模式代理到本地 SPICA 服务
    proxy: { "/api": "http://127.0.0.1:8666", "/ws": {
      target: "ws://127.0.0.1:8666", ws: true } },
  },
});
