import { expect, test } from "@playwright/test";
import { stubApi } from "./stub-api";

const SCREENS = ["Connections", "New clone", "Jobs", "Review", "Quality"];

test.beforeEach(async ({ page }) => {
  await stubApi(page, {
    "GET /connections": () => ({ body: [] }),
    "GET /quality": () => ({ body: { metrics: [] } }),
  });
});

test("navigation shows exactly the five screens: Connections, New clone, Jobs, Review, Quality", async ({ page }) => {
  await page.goto("/");
  const links = page.getByRole("navigation", { name: "Main" }).getByRole("link");
  await expect(links).toHaveText(SCREENS);
  await expect(page).toHaveURL(/#\/connections$/);
});

test("each navigation entry changes the address to its own screen", async ({ page }) => {
  await page.goto("/");
  const addresses = ["connections", "new-clone", "jobs", "review", "quality"];
  for (const [i, label] of SCREENS.entries()) {
    await page.getByRole("link", { name: label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`#/${addresses[i]}$`));
  }
});

test("an address that is not one of the five screens shows page not found", async ({ page }) => {
  await page.goto("/#/no-such-screen");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
});

test("English only, no UI mode choice, no login and no dark-mode toggle", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("radiogroup")).toHaveCount(0);
  await expect(page.getByText(/log ?in|sign ?in/i)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /dark|theme|language/i })).toHaveCount(0);
});

test("offline: no request leaves the page's own origin on any screen", async ({ page, baseURL }) => {
  const foreign: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).origin !== new URL(baseURL as string).origin) foreign.push(request.url());
  });
  for (const address of ["connections", "new-clone", "jobs", "review", "quality"]) {
    await page.goto(`/#/${address}`);
    await page.waitForLoadState("networkidle");
  }
  expect(foreign).toEqual([]);
});
