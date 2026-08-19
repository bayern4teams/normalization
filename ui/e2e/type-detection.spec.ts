import { expect, test } from "@playwright/test";

// Source.txt §61 (automatic field type detection) and §62/§84 (profile
// auto-suggestion) — added during the M7 follow-up self-audit, which
// found both were spec'd for M7 but never actually built. Real
// end-to-end coverage against the live API, matching the rest of this
// suite's discipline.
test("detect type from a field name and get a real profile suggestion", async ({ page }) => {
  await page.goto("/#/fields");

  await page.getByLabel("Field name").fill("mobile");
  await page.getByRole("button", { name: "Detect type" }).click();

  const firstRow = page.locator("tbody tr").first();
  await expect(firstRow).toContainText("PHONE");
  await expect(firstRow).toContainText("90%");

  await firstRow.getByRole("button", { name: "Suggest profile" }).click();
  await expect(page.getByText(/Recommended normalization for PHONE/)).toBeVisible();
  await expect(page.getByText(/libphonenumber/)).toBeVisible();
  await expect(page.getByText(/Country ambiguity/)).toBeVisible();
});
