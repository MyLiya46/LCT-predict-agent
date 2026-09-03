import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        // 浏览器打开二级页 /api 时走 SPA，其余 /api/* 仍代理到 FastAPI
        bypass(req) {
          const url = (req.url || "").split("?")[0];
          if (req.method === "GET" && (url === "/api" || url === "/api/")) {
            return "/index.html";
          }
          return undefined;
        },
      },
    },
  },
});
