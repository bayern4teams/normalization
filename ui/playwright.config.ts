import { defineConfig, devices } from "@playwright/test";

// Browser suite (Source.txt Gate model, M7 §89-§121): drives a production build
// of the UI (`vite preview`, port 4173). Every spec stubs the API with
// page.route (`e2e/stub-api.ts`), so no normapi server is needed (ADR-023).
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:4173",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview -- --port 4173 --strictPort",
    url: "http://localhost:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
