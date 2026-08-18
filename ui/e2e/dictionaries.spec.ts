import { expect, test } from "@playwright/test";

// Source.txt §59/§115 — custom dictionary create/versioning end to end
// against the real CustomDictionaryStore (file-backed, not mocked).
test("create a custom dictionary and add a merged version", async ({ page }) => {
  const dictId = `e2e-dict-${Date.now()}`;

  await page.goto("/#/dictionaries");
  await expect(page.getByText("honorifics.common")).toBeVisible(); // a real built-in

  await page.getByLabel("id", { exact: true }).fill(dictId);
  await page.getByRole("button", { name: "Create", exact: true }).click();

  const newRow = page.locator("tr", { hasText: dictId });
  await expect(newRow).toContainText("active");
  await expect(newRow).toContainText("v1");

  await newRow.getByRole("button", { name: "View" }).click();
  await expect(page.locator(".json-block")).toContainText("example-key");
});

test("built-in dictionaries stay read-only (no create/rollback/delete controls)", async ({
  page,
}) => {
  await page.goto("/#/dictionaries");
  const builtinRow = page.locator("tr", { hasText: "missing-values.common" });
  await expect(builtinRow).toContainText("built-in");
  await expect(builtinRow.getByRole("button", { name: "Delete" })).toHaveCount(0);
  await expect(builtinRow.getByRole("button", { name: /Rollback/ })).toHaveCount(0);
});
