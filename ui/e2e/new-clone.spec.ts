import { expect, test } from "@playwright/test";
import { FIELD_SEMANTIC_TYPES } from "../src/api/types";
import { stubApi } from "./stub-api";

const CONNECTIONS = [
  { connection_id: "src", engine: "postgres", host: "db.internal", port: 5432, username: "reader", created_at: "2026-10-28T10:00:00Z" },
  { connection_id: "dst", engine: "postgres", host: "db.internal", port: 5432, username: "writer", created_at: "2026-10-28T10:00:00Z" },
];

test("new clone: origin, columns, then check answers; Start exists only on the last step", async ({ page }) => {
  const seen = await stubApi(page, {
    "GET /connections": () => ({ body: CONNECTIONS }),
    "POST /connections/src/databases": () => ({ body: ["orders"] }),
    "GET /connections/src/databases/orders/tables": () => ({ body: ["customers", "invoices"] }),
    "GET /connections/src/databases/orders/tables/customers/columns": () => ({
      body: [
        { name: "id", native_type: "integer" },
        { name: "joined", native_type: "text" },
      ],
    }),
    "POST /clone-jobs": () => ({ status: 201, body: { job_id: "job-1", status: "PENDING_DB_CREATE", create_database_sql: "" } }),
  });
  const start = page.getByRole("button", { name: "Start", exact: true });

  await page.goto("/#/new-clone");
  await expect(start).toHaveCount(0);
  await page.getByLabel("Origin connection (read only)").selectOption({ label: "postgres db.internal:5432 (reader)" });
  await page.getByLabel("Origin database").selectOption("orders");
  await page.getByLabel("Destination connection (can write)").selectOption({ label: "postgres db.internal:5432 (writer)" });
  await page.getByLabel("Destination database").fill("orders_clone");
  await page.getByRole("button", { name: "Next" }).click();

  // Step 2: every table is cloned; the semantic types are the API's enum, plus "Copy unchanged".
  await expect(start).toHaveCount(0);
  await expect(page.getByText("All 2 table(s) of")).toBeVisible();
  await page.getByRole("button", { name: "customers" }).click();
  const joined = page.getByLabel("Semantic type of customers.joined");
  await expect(joined.locator("option")).toHaveText(["Copy unchanged", ...FIELD_SEMANTIC_TYPES]);
  await joined.selectOption(FIELD_SEMANTIC_TYPES[0]);
  await page.getByRole("button", { name: "Next" }).click();

  // Step 3: the answers are listed, and only here is there a Start button.
  await expect(page.getByRole("heading", { name: "Check your answers" })).toBeVisible();
  await expect(page.getByText(`customers.joined: ${FIELD_SEMANTIC_TYPES[0]}`)).toBeVisible();
  await expect(page.getByText("orders_clone")).toBeVisible();
  await expect(page.getByText(/in.place/i)).toHaveCount(0);
  await expect(start).toHaveCount(1);
  expect(seen.some((r) => r.method() === "POST" && r.url().endsWith("/clone-jobs"))).toBe(false);

  await start.click();
  await expect(page).toHaveURL(/#\/jobs\/job-1$/);
  const post = seen.find((r) => r.method() === "POST" && r.url().endsWith("/clone-jobs"));
  expect(post?.postDataJSON()).toEqual({
    source_connection_id: "src",
    source_database: "orders",
    destination_connection_id: "dst",
    destination_database: "orders_clone",
    field_configs: { customers: { joined: FIELD_SEMANTIC_TYPES[0] } },
  });
});

test("new clone: Next stays disabled until origin, destination and a destination name are chosen", async ({ page }) => {
  await stubApi(page, { "GET /connections": () => ({ body: CONNECTIONS }) });
  await page.goto("/#/new-clone");
  await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
});

test("new clone: a table left unticked is not cloned, and Next needs at least one table", async ({ page }) => {
  const seen = await stubApi(page, {
    "GET /connections": () => ({ body: CONNECTIONS }),
    "POST /connections/src/databases": () => ({ body: ["orders"] }),
    "GET /connections/src/databases/orders/tables": () => ({ body: ["customers", "invoices", "notes"] }),
    "POST /clone-jobs": () => ({ status: 201, body: { job_id: "job-2", status: "PENDING_DB_CREATE", create_database_sql: "" } }),
  });
  await page.goto("/#/new-clone");
  await page.getByLabel("Origin connection (read only)").selectOption({ label: "postgres db.internal:5432 (reader)" });
  await page.getByLabel("Origin database").selectOption("orders");
  await page.getByLabel("Destination connection (can write)").selectOption({ label: "postgres db.internal:5432 (writer)" });
  await page.getByLabel("Destination database").fill("orders_clone");
  await page.getByRole("button", { name: "Next" }).click();

  for (const table of ["customers", "notes", "invoices"]) await page.getByLabel(`Clone table ${table}`).uncheck();
  await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
  await page.getByLabel("Clone table invoices").check();
  await expect(page.getByText("1 of 3 table(s) of")).toBeVisible();
  await expect(page.getByRole("button", { name: "customers" })).toHaveCount(0);
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByRole("row", { name: /Tables cloned/ })).toContainText("invoices");
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page).toHaveURL(/#\/jobs\/job-2$/);
  const post = seen.find((r) => r.method() === "POST" && r.url().endsWith("/clone-jobs"));
  expect(post?.postDataJSON().tables).toEqual(["invoices"]);
});
