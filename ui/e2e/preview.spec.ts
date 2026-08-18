import { expect, test } from "@playwright/test";

// Source.txt §83/§118/§117 — sample preview, BEFORE/AFTER, explanation.
test("preview runs real values through the live dispatcher and explains the result", async ({
  page,
}) => {
  await page.goto("/#/preview");
  await page.getByLabel("Field name").fill("email_field");
  await page.getByLabel("Semantic type").selectOption("EMAIL");
  await page.getByLabel("Values (one per line)").fill("  User@Example.com  \nnot-an-email");
  await page.getByRole("button", { name: /Run preview/ }).click();

  const rows = page.locator("tbody tr");
  // Real EmailNormalizer behavior (verified against the live server):
  // domain is lowercased, local part case is preserved in `display`.
  await expect(rows.first()).toContainText("User@example.com");
  await expect(page.locator(".status-pill", { hasText: "INVALID" })).toBeVisible();

  await page.getByRole("button", { name: "Details" }).first().click();
  await expect(page.locator(".explanation-panel__plain").first()).toBeVisible();
});

test("rule builder loads the real executed trace for a value", async ({ page }) => {
  await page.goto("/#/rules");
  await page.getByRole("button", { name: "Load pipeline" }).click();
  await expect(page.locator(".pipeline-list")).toBeVisible();
  await expect(page.locator(".pipeline-step").first()).toBeVisible();
});
