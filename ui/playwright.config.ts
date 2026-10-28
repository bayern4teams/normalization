import { defineConfig, devices } from "@playwright/test";

// Real end-to-end suite (Source.txt Gate model, M7 §89-§121): drives a
// production build of the UI (`vite preview`, port 4173; the specs stub the API
// with page.route, so no CORS is involved, ADR-023)
// against a REAL running normapi server. CI (.github/workflows/gate.yml's
// `e2e` job) starts that server via `docker compose up -d --build` before
// invoking this suite; for local runs, start it yourself first (see
// README below) — this config does not start normapi itself, only the UI.
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
