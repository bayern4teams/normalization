import { expect, test, type Page } from "@playwright/test";

// Quality screen (U1, acceptance F9): one job's quality report as a live page. The job is in
// the URL, so a reload shows the same report; the page polls while the job runs. The API is
// intercepted with page.route, so no Docker or database is needed.

const RAW = "05/06/2021"; // planted in `disguised_missing`, where the API carries raw values (R23)
const POLL_MS = 2000; // the page's poll interval (lib/reviewJobs.ts); the clock is faked past it

const JOBS = ["job-run", "job-done"].map((id, n) => ({
  job_id: id,
  status: n === 0 ? "RUNNING" : "COMPLETED",
  source_connection_id: "src",
  source_database: "orders",
  destination_connection_id: "dst",
  destination_database: `${id}_clone`,
  tables: ["customers", "invoices"],
  field_configs: {},
  progress: { current_table: null, tables_completed: [], rows_done: 0, checkpoints: {} },
  error: null,
}));

const column = (values: number, statuses: Record<string, number>, extra: Record<string, unknown> = {}) => ({
  values,
  statuses,
  emptied: 5,
  checked_idempotent: 50,
  not_idempotent: 2,
  calibration: { below_threshold: 3 },
  disguised_missing: [{ value: RAW, count: 4, hint: null }],
  ...extra,
});
const CUSTOMERS = { joined: column(200, { NORMALIZED: 180, AMBIGUOUS: 15, INVALID: 5 }) };
const INVOICES = { total: column(100, { NORMALIZED: 100 }, { disguised_missing: [] }) };

type Quality = { job_id: string; status: string; tables: Record<string, Record<string, unknown>> };

async function open(page: Page, url: string, quality: (nth: number) => Quality | null) {
  const urls: string[] = [];
  let nth = 0;
  page.on("request", (r) => urls.push(r.url()));
  await page.route("**/normalization/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/normalization/, "");
    if (path === "/clone-jobs") return route.fulfill({ json: JOBS });
    if (/^\/clone-jobs\/[^/]+\/quality$/.test(path)) {
      const body = quality(nth++);
      return route.fulfill(body ? { json: body } : { status: 404, json: { detail: "No such clone job: nope" } });
    }
    return route.fulfill({ status: 404, json: { detail: `no stub for ${path}` } });
  });
  await page.clock.install();
  await page.goto(url);
  return {
    gets: () => nth,
    foreign: () => urls.filter((u) => new URL(u).origin !== new URL(page.url()).origin),
  };
}

test("choosing a job puts it in the URL and shows its report; a reload shows the same report", async ({ page }) => {
  const { foreign } = await open(page, "/#/quality", () => ({ job_id: "job-done", status: "COMPLETED", tables: { customers: CUSTOMERS, invoices: INVOICES } }));
  await expect(page.getByText("Choose a job to see")).toBeVisible();
  await page.getByRole("combobox", { name: "Job" }).click();
  await page.getByRole("option", { name: /job-done_clone/ }).click();
  await expect(page).toHaveURL(/#\/quality\?job=job-done$/);
  await expect(page.getByRole("heading", { name: "customers" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "customers" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "invoices" })).toBeVisible();
  expect(foreign()).toEqual([]);
});

test("a column row shows its counts, and a raw value planted in the payload never appears", async ({ page }) => {
  await open(page, "/#/quality?job=job-done", () => ({ job_id: "job-done", status: "COMPLETED", tables: { customers: CUSTOMERS } }));
  const row = page.getByRole("row", { name: /^joined/ });
  await expect(row).toBeVisible();
  const cells = row.getByRole("cell");
  await expect(cells.nth(1)).toHaveText("200"); // values
  await expect(cells.nth(2)).toContainText("NORMALIZED 180, AMBIGUOUS 15, INVALID 5");
  await expect(cells.nth(3)).toHaveText("5"); // emptied
  await expect(cells.nth(4)).toHaveText("2 of 50 checked");
  await expect(cells.nth(5)).toHaveText("3"); // below threshold
  await expect(cells.nth(6)).toHaveText("1"); // disguised-missing candidates: a count, not the value
  await expect(page.locator("body")).not.toContainText(RAW);
  await expect(page.getByLabel("Legend").getByText("AMBIGUOUS")).toBeVisible();
});

test("while the job runs the report updates by itself, and polling stops when it is done", async ({ page }) => {
  const { gets } = await open(page, "/#/quality?job=job-run", (n) =>
    n === 0
      ? { job_id: "job-run", status: "RUNNING", tables: { customers: CUSTOMERS } }
      : n === 1
        ? { job_id: "job-run", status: "RUNNING", tables: { customers: CUSTOMERS, invoices: INVOICES } }
        : { job_id: "job-run", status: "COMPLETED", tables: { customers: CUSTOMERS, invoices: INVOICES } },
  );
  await expect(page.getByRole("heading", { name: "customers" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "invoices" })).toHaveCount(0);
  await expect(page.getByText("Updating while the job runs.")).toBeVisible();
  await page.clock.fastForward(POLL_MS + 500);
  await expect(page.getByRole("heading", { name: "invoices" })).toBeVisible();
  await page.clock.fastForward(POLL_MS + 500);
  await expect(page.getByTestId("quality-state")).toHaveText("completed");
  const settled = gets();
  await page.clock.runFor(POLL_MS * 5);
  expect(gets()).toBe(settled);
});

test("a job with no finished table says when tables will appear", async ({ page }) => {
  await open(page, "/#/quality?job=job-run", () => ({ job_id: "job-run", status: "RUNNING", tables: {} }));
  await expect(page.getByText(/no table has finished yet/i)).toBeVisible();
});

test("an unknown job shows the API's message", async ({ page }) => {
  await open(page, "/#/quality?job=nope", () => null);
  await expect(page.getByText("No such clone job: nope")).toBeVisible();
});
