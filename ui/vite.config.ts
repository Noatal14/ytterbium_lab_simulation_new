import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
        configure(proxy) {
          // The browser talks only to Vite. Present the proxy's actual
          // loopback origin to the API so its strict same-origin/CSRF check
          // remains enabled in development.
          proxy.on("proxyReq", (request) => {
            request.setHeader("Origin", "http://127.0.0.1:8765");
          });
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
