import { expect, test, type Page, type Request } from "@playwright/test";

// Jobs screen (U1, acceptance F9): a list filterable by state and one job's detail with
// progress and errors; both survive a reload because their state is in the URL. The API is
// intercepted with page.route, so no Docker or database is needed.

const RAW = "05/06/2021"; // planted where a leak would put it; the Jobs screen must never show it
const POLL_MS = 2000; // the page's poll interval (lib/reviewJobs.ts); the clock is faked past it
const ERRORS_PER_PAGE = 50; // the page's page size
const TOTAL_ERRORS = 120;

function job(id: string, status: string, over: Record<string, unknown> = {}) {
  return {
    job_id: id,
    status,
    source_connection_id: "src",
    source_database: "orders",
    destination_connection_id: "dst",
    destination_database: `${id}_clone`,
    tables: ["customers", "invoices", "lines"],
    field_configs: {},
    progress: { current_table: null, tables_completed: [], rows_done: 0, checkpoints: {} },
    error: null,
    stale: false,
    ...over,
  };
}
const RUNNING = job("job-run", "RUNNING", {
  progress: { current_table: "invoices", tables_completed: ["customers"], rows_done: 120, checkpoints: {} },
});
const DONE = job("job-done", "COMPLETED", {
  progress: { current_table: null, tables_completed: ["customers", "invoices", "lines"], rows_done: 900, checkpoints: {} },
});
const FAILED = job("job-fail", "FAILED", { error: "destination refused the connection" });
const ALL = [RUNNING, DONE, FAILED];

interface Setup {
  jobs?: ReturnType<typeof job>[];
  /** Called for each GET of one job; lets a test change the answer over time. */
  detail?: (id: string, nth: number) => ReturnType<typeof job>;
}

async function open(page: Page, url: string, setup: Setup = {}) {
  const requests: Request[] = [];
  const urls: string[] = [];
  const details = new Map<string, number>();
  page.on("request", (r) => urls.push(r.url()));
  await page.route("**/normalization/**", async (route) => {
    const request = route.request();
    requests.push(request);
    const { pathname, searchParams } = new URL(request.url());
    const path = pathname.replace(/^\/normalization/, "");
    const jobs = setup.jobs ?? ALL;
    if (request.method() === "GET" && path === "/clone-jobs") return route.fulfill({ json: jobs });
    const errors = path.match(/^\/clone-jobs\/([^/]+)\/errors$/);
    if (request.method() === "GET" && errors) {
      const offset = Number(searchParams.get("offset"));
      const count = Math.max(0, Math.min(Number(searchParams.get("limit")), TOTAL_ERRORS - offset));
      const rows = Array.from({ length: count }, (_, i) => ({
        field: "customers.joined",
        record_ref: String(offset + i),
        operation: "clone-normalize",
        error: `row ${offset + i} could not be normalized`,
        severity: "error",
        safe_preview: "dd/dd/dddd",
        original: RAW,
      }));
      return route.fulfill({ json: rows, headers: { "X-Total-Count": String(TOTAL_ERRORS) } });
    }
    const one = path.match(/^\/clone-jobs\/([^/]+)$/);
    if (request.method() === "GET" && one) {
      const nth = details.get(one[1]) ?? 0;
      details.set(one[1], nth + 1);
      const found = setup.detail ? setup.detail(one[1], nth) : jobs.find((j) => j.job_id === one[1]);
      return route.fulfill(found ? { json: found } : { status: 404, json: { detail: `No such clone job: ${one[1]}` } });
    }
    if (request.method() === "POST") return route.fulfill({ json: job("any", "RUNNING") });
    return route.fulfill({ status: 404, json: { detail: `no stub for ${request.method()} ${path}` } });
  });
  await page.clock.install();
  await page.goto(url);
  return { requests, foreign: () => urls.filter((u) => new URL(u).origin !== new URL(page.url()).origin) };
}

test("list shows every job and one button per state present, with counts", async ({ page }) => {
  const { foreign } = await open(page, "/#/jobs");
  await expect(page.getByRole("link", { name: "job-run" })).toBeVisible();
  await expect(page.getByRole("link", { name: "job-done" })).toBeVisible();
  await expect(page.getByRole("link", { name: "job-fail" })).toBeVisible();
  const filters = page.getByRole("group", { name: "Filter by state" }).getByRole("button");
  await expect(filters).toHaveText(["All (3)", "running (1)", "completed (1)", "failed (1)"]);
  expect(foreign()).toEqual([]);
});

test("filtering by state keeps the state in the URL and survives a reload", async ({ page }) => {
  await open(page, "/#/jobs");
  await page.getByRole("button", { name: "failed (1)" }).click();
  await expect(page).toHaveURL(/#\/jobs\?state=FAILED$/);
  await expect(page.getByRole("link", { name: "job-fail" })).toBeVisible();
  await expect(page.getByRole("link", { name: "job-run" })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("link", { name: "job-fail" })).toBeVisible();
  await expect(page.getByRole("link", { name: "job-run" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "failed (1)" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: /^All/ }).click();
  await expect(page.getByRole("link", { name: "job-run" })).toBeVisible();
});

test("an empty list says so", async ({ page }) => {
  await open(page, "/#/jobs", { jobs: [] });
  await expect(page.getByText(/no clone jobs yet/i)).toBeVisible();
});

test("detail shows state, progress and the job's error; the planted raw value never appears", async ({ page }) => {
  await open(page, "/#/jobs/job-fail");
  await expect(page.getByTestId("job-state")).toHaveText("failed");
  await expect(page.getByText("destination refused the connection")).toBeVisible();
  await expect(page.getByTestId("progress-text")).toHaveText("0 of 3 tables done, 0 rows");
  await expect(page.getByText("Errors (120)")).toBeVisible();
  await expect(page.getByText("dd/dd/dddd").first()).toBeVisible();
  await expect(page.getByText(RAW)).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(RAW);
});

test("a running job is polled and its progress updates; a finished job is not polled", async ({ page }) => {
  const { requests } = await open(page, "/#/jobs/job-run", {
    detail: (id, nth) =>
      nth === 0
        ? RUNNING
        : nth === 1
          ? { ...RUNNING, progress: { ...RUNNING.progress, rows_done: 480 } }
          : { ...DONE, job_id: id },
  });
  const progress = page.getByTestId("progress-text");
  await expect(progress).toHaveText("1 of 3 tables done, 120 rows, now invoices");
  await page.clock.fastForward(POLL_MS + 500);
  await expect(progress).toHaveText("1 of 3 tables done, 480 rows, now invoices");
  await page.clock.fastForward(POLL_MS + 500);
  await expect(page.getByTestId("job-state")).toHaveText("completed");
  const jobGets = () => requests.filter((r) => r.method() === "GET" && /\/clone-jobs\/job-run$/.test(r.url())).length;
  const settled = jobGets();
  await page.clock.runFor(POLL_MS * 5);
  expect(jobGets()).toBe(settled);
});

test("errors are paged 50 at a time with the job-wide total, and the page survives a reload", async ({ page }) => {
  const { requests } = await open(page, "/#/jobs/job-done");
  const lastPage = Math.ceil(TOTAL_ERRORS / ERRORS_PER_PAGE); // 3
  await expect(page.getByText(`Page 1 of ${lastPage}`)).toBeVisible();
  await expect(page.getByRole("button", { name: "Previous" })).toBeDisabled();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page).toHaveURL(/#\/jobs\/job-done\?page=1$/);
  await expect(page.getByText("row 50 could not be normalized")).toBeVisible();
  const second = requests.find((r) => r.url().includes("/errors") && r.url().includes("offset=50"));
  expect(second).toBeDefined();
  expect(new URL(second!.url()).searchParams.get("limit")).toBe(String(ERRORS_PER_PAGE));
  await page.reload();
  await expect(page.getByText(`Page 2 of ${lastPage}`)).toBeVisible();
  await expect(page.getByText("row 50 could not be normalized")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText(`Page 3 of ${lastPage}`)).toBeVisible();
  await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
});

test("the steps a new job needs are offered only in their state", async ({ page }) => {
  const pending = job("job-new", "PENDING_DB_CREATE");
  const { requests } = await open(page, "/#/jobs/job-new", { jobs: [pending] });
  await expect(page.getByRole("button", { name: "Start clone" })).toHaveCount(0);
  await page.getByRole("button", { name: "Verify database" }).click();
  await expect.poll(() => requests.some((r) => r.method() === "POST" && r.url().endsWith("/clone-jobs/job-new/verify-database"))).toBe(true);
});

test("an unknown job shows the API's message", async ({ page }) => {
  await open(page, "/#/jobs/nope", { jobs: [] });
  await expect(page.getByText("No such clone job: nope")).toBeVisible();
});
