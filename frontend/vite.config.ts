import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, "..", ""), ...process.env };
  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: "127.0.0.1",
      port: Number(env.FRONTEND_PORT || 5173),
      strictPort: true,
      proxy: {
        "/api": {
          target: `http://127.0.0.1:${env.BACKEND_PORT || 8000}`,
          ws: true,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
        },
      },
    },
  };
});
