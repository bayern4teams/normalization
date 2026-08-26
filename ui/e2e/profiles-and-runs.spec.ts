import { expect, test } from "@playwright/test";

// Exercises the real create-profile -> create-and-execute-run -> run-detail
// flow end to end against a live normapi server (no mocks). Uses a
// timestamp-suffixed profile name so this is safe to re-run against a
// server whose in-memory store already has state from prior runs.
//
// M21 moved these legacy pages' nav links behind expert mode (decision 3)
// — this suite navigates directly to their real, still-live `/advanced/*`
// routes ("routes kept, nothing deleted") rather than depending on nav
// link visibility, which is no longer the default.
//
// Also fixed here, found while re-verifying this suite for M21: `GET
// /runs` returns oldest-first, and this project's real Postgres
// (persistent across every session ever run against it, same as M20's
// own disclosed watermark finding) has accumulated hundreds of historical
// runs. `.locator("tbody tr").first()` therefore stopped meaning "the run
// just created" a while ago and was silently asserting against the
// single oldest debris row instead — `.last()` is what "just created"
// actually means against an oldest-first, ever-growing list.
test("create profile, execute a run with a real collision, see it on run detail", async ({
  page,
}) => {
  const profileName = `e2e-profile-${Date.now()}`;

  await page.goto("/#/profiles");
  await page.getByPlaceholder("Profile name").fill(profileName);
  await page.getByPlaceholder("Created by").fill("playwright-e2e");
  await page.getByRole("button", { name: "Create profile" }).click();
  await expect(page.getByRole("link", { name: profileName })).toBeVisible();

  await page.goto("/#/advanced/runs");
  await page
    .locator("select")
    .first()
    .selectOption({ label: `${profileName} (v1)` });
  // Textareas are pre-filled with the José García/Jose Garcia/JOSÉ GARCÍA
  // collision worked example (Source.txt §79) — a real, deliberate
  // collision the assertions below verify was actually detected.
  await page.getByRole("button", { name: /Create \+ execute run/ }).click();

  const runRow = page.locator("tbody tr").last();
  await expect(runRow).toContainText("COMPLETED", { timeout: 15_000 });
  await expect(runRow).toContainText("3"); // rows processed

  await runRow.getByRole("link").click();
  await expect(page.getByRole("heading", { name: "Run detail" })).toBeVisible();
  await expect(page.getByText("Change impact")).toBeVisible();
  await expect(page.getByText("New collisions", { exact: true })).toBeVisible();
  await expect(page.getByText("josé garcía", { exact: true })).toBeVisible();
});

test("mismatched-length run comparison surfaces a real, readable server error", async ({
  page,
}) => {
  const profileName = `e2e-compare-${Date.now()}`;

  await page.goto("/#/profiles");
  await page.getByPlaceholder("Profile name").fill(profileName);
  await page.getByPlaceholder("Created by").fill("playwright-e2e");
  await page.getByRole("button", { name: "Create profile" }).click();

  await page.goto("/#/advanced/runs");
  const profileSelect = page.locator("select").first();

  // Run A: the default 3-value sample.
  await profileSelect.selectOption({ label: `${profileName} (v1)` });
  await page.getByRole("button", { name: /Create \+ execute run/ }).click();
  await expect(page.locator("tbody tr").last()).toContainText("COMPLETED", { timeout: 15_000 });

  // Run B: a deliberately different-length sample.
  await profileSelect.selectOption({ label: `${profileName} (v1)` });
  await page.getByLabel("Values (one per line)").fill("Alpha\nBeta\nGamma\nDelta");
  await page.getByRole("button", { name: /Create \+ execute run/ }).click();
  await expect(page.locator("tbody tr").last()).toContainText("COMPLETED", { timeout: 15_000 });

  await page.goto("/#/advanced/compare");
  const selects = page.locator("select");
  const runIds = await page.evaluate(async () => {
    const base = "http://localhost:8080/normalization/runs";
    const resp = await fetch(base);
    const runs = (await resp.json()) as { id: string }[];
    return runs.slice(-2).map((r: { id: string }) => r.id);
  });
  await selects.nth(0).selectOption(runIds[0]);
  await selects.nth(1).selectOption(runIds[1]);

  await expect(page.getByText(/Request failed:/)).toBeVisible();
  await expect(page.getByText(/same number of executed values/)).toBeVisible();
});
