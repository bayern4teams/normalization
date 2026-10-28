import { expect, test } from "@playwright/test";
import { stubApi, type Handlers } from "./stub-api";

const SAVED = [
  { connection_id: "c1", engine: "postgres", host: "db.internal", port: 5432, username: "reader", created_at: "2026-10-28T10:00:00Z" },
];

async function fillForm(page: import("@playwright/test").Page, host: string) {
  await page.getByLabel("Host").fill(host);
  await page.getByLabel("Username").fill("reader");
  await page.getByRole("textbox", { name: /^Password/ }).fill("not-a-real-password");
}

test("connections: Save stays disabled until Test connection passed for the values on screen", async ({ page }) => {
  const handlers: Handlers = {
    "GET /connections": () => ({ body: SAVED }),
    "POST /connections/adhoc/databases": () => ({ body: ["orders", "billing"] }),
    "POST /connections": () => ({ status: 201, body: SAVED[0] }),
  };
  const seen = await stubApi(page, handlers);
  await page.goto("/#/connections");
  await expect(page.getByRole("cell", { name: "db.internal" })).toBeVisible();

  await fillForm(page, "db.internal");
  const save = page.getByRole("button", { name: "Save", exact: true });
  await expect(save).toBeDisabled();

  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByText("Connection works. The server lists 2 database(s).")).toBeVisible();
  await expect(save).toBeEnabled();

  // Any edit invalidates the test: the tested values are no longer the ones on screen.
  await page.getByLabel("Username").fill("someone-else");
  await expect(save).toBeDisabled();

  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(save).toBeEnabled();
  await save.click();
  const post = seen.find((r) => r.method() === "POST" && r.url().endsWith("/normalization/connections"));
  expect(post?.postDataJSON()).toEqual({
    engine: "postgres",
    host: "db.internal",
    port: 5432,
    username: "someone-else",
    password: "not-a-real-password",
  });
});

test("connections: the API's refusal of a public host is shown next to the Host field", async ({ page }) => {
  const refusal = "address '8.8.8.8' is outside the allowed local network";
  await stubApi(page, {
    "GET /connections": () => ({ body: [] }),
    "POST /connections/adhoc/databases": () => ({ status: 422, body: { detail: refusal } }),
  });
  await page.goto("/#/connections");
  await fillForm(page, "8.8.8.8");
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByLabel("Host")).toHaveAccessibleDescription(new RegExp(refusal));
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  // Editing the host clears the message.
  await page.getByLabel("Host").fill("db.internal");
  await expect(page.getByText(refusal)).toHaveCount(0);
});

test("connections: a failure that is not about the host is shown as an alert, not at the field", async ({ page }) => {
  await stubApi(page, {
    "GET /connections": () => ({ body: [] }),
    "POST /connections/adhoc/databases": () => ({ status: 500, body: { detail: "password authentication failed" } }),
  });
  await page.goto("/#/connections");
  await fillForm(page, "db.internal");
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByRole("alert").getByText("password authentication failed")).toBeVisible();
  await expect(page.getByLabel("Host")).not.toHaveAttribute("aria-invalid", "true");
});
