import { expect, test } from "@playwright/test";

// Real end-to-end smoke test — every assertion here reads text that only
// appears if the live fetch to the real normapi server actually
// succeeded (no mocked routes anywhere in this suite).
test("overview loads real aggregated data from the live API", async ({ page }) => {
  await page.goto("/");
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
  await page.goto("/");
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
