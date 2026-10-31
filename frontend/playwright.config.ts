import { defineConfig } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI,
  use: {
    baseURL,
  },
  webServer: {
    command: "bun run start",
    url: baseURL,
    reuseExistingServer: true,
  },
});
