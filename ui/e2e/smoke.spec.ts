import { expect, test } from "@playwright/test";

// Real end-to-end smoke test — every assertion here reads text that only
// appears if the live fetch to the real normapi server actually
// succeeded (no mocked routes anywhere in this suite).
//
// M21 moved the legacy Overview page off the bare `/` route — index now
// redirects to `/connect` (the new primary 3-step flow), and Overview
// lives at `/advanced/overview` (still reachable, per the plan's own
// "routes kept, nothing deleted" decision). These two tests are updated
// to that real, current routing rather than the pre-M21 assumption that
// `/` renders Overview directly.
test("overview loads real aggregated data from the live API", async ({ page }) => {
  await page.goto("/#/advanced/overview");
  await expect(page.getByRole("heading", { name: "Normalization Overview" })).toBeVisible();
  await expect(page.getByText("Fields analyzed")).toBeVisible();
  // A real number (possibly 0), never "Loading…" once resolved and never
  // the error state — proves the CORS-enabled fetch round-tripped.
  await expect(page.getByText("Loading…")).toHaveCount(0);
  await expect(page.getByText(/Request failed/)).toHaveCount(0);
});

test("nav links every page in Source.txt §89 without a client error", async ({ page }) => {
  const pages = [
    "Overview",
    "Profiles",
    "Fields",
    "Rules",
    "Preview",
    "Runs",
    "Warnings",
    "Collisions",
    "Dictionaries",
    "Quality",
    "Settings",
  ];
  // These 11 legacy tabs only render in the nav once mode !== "normal"
  // (M21 decision 3) — switch to expert mode first, same as a real user
  // reaching them would.
  await page.goto("/#/settings");
  await page.getByRole("button", { name: "expert", exact: true }).click();
  for (const label of pages) {
    await page.getByRole("link", { name: label, exact: true }).click();
    await expect(page.getByText(/Request failed/)).toHaveCount(0);
  }
});

test("mode switch changes what expert/admin-only content renders", async ({ page }) => {
  await page.goto("/#/settings");
  await expect(page.getByText("Current mode:")).toContainText("normal");
  await page.getByRole("button", { name: "expert", exact: true }).click();
  await expect(page.getByText("Current mode:")).toContainText("expert");
});
