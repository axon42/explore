import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 45000,
  use: {
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    baseURL: "http://127.0.0.1:5174",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "bash ../scripts/dev.sh",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: false,
    gracefulShutdown: { signal: "SIGTERM", timeout: 15000 },
    env: {
      FRONTEND_PORT: "5174",
      BACKEND_PORT: "8001",
      DATA_DIR: "./data/browser-tests",
      DEMO_ENABLED: "true",
      INGESTION_TOKEN: "",
      ANALYSIS_PROVIDER: "mock",
      GEMINI_API_KEY: "",
    },
    timeout: 60000,
  },
});
