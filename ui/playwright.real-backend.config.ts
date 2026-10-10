import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./integration",
  fullyParallel: false,
  workers: 1,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:5173",
  },
  webServer: [
    {
      command: "python3 integration/real_backend_server.py",
      url: "http://127.0.0.1:8765/api/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "node ./node_modules/vite/bin/vite.js --host 127.0.0.1",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
