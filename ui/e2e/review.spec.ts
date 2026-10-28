import { expect, test, type Page, type Request } from "@playwright/test";
import { actionForKey, type KeyEventLike } from "../src/lib/reviewKeys";
import { initialQueue, queueReducer, type QueueState } from "../src/lib/reviewQueue";
import { extractReadings } from "../src/lib/reviewReadings";

// Review screen (U1; report "No pre-selected reading", "Speed"; acceptance F2-F7). The API is
// intercepted with page.route, so no Docker or database is needed. Every expected value is
// computed here from the calendar or comes from the report, never from running the page.

const HOLD_MS = 5000; // the page's undo window (reviewQueue.ts UNDO_WINDOW_MS); the clock is faked past it
const iso = (y: number, m: number, d: number) => new Date(Date.UTC(y, m - 1, d)).toISOString().slice(0, 10);

// A dd/mm/yyyy date with both parts <= 12 has two readings (the normalizer's DMY and MDY).
function dateEntry(first: number, second: number, year: number, occurrences: number) {
  const p = (n: number) => String(n).padStart(2, "0");
  return {
    key: `k-${first}-${second}-${year}`,
    semantic_type: "DATE",
    original: `${p(first)}/${p(second)}/${year}`,
    context: { field_name: "joined", semantic_type: "DATE" },
    detail: {
      structured: {
        candidates: [
          { interpretation: "DMY", day: p(first), month: p(second), year: String(year) },
          { interpretation: "MDY", day: p(second), month: p(first), year: String(year) },
        ],
        assumption: null,
      },
      warnings: [],
      errors: [],
    },
    occurrences,
    decided: false,
  };
}
const A = dateEntry(5, 6, 2021, 9);
const B = dateEntry(7, 8, 2022, 5);
const C = dateEntry(9, 10, 2023, 3);
const dmy = (e: typeof A) => iso(Number(e.original.slice(6)), Number(e.original.slice(3, 5)), Number(e.original.slice(0, 2)));
const mdy = (e: typeof A) => iso(Number(e.original.slice(6)), Number(e.original.slice(0, 2)), Number(e.original.slice(3, 5)));

const position = (page: Page) => page.getByTestId("position");
const raw = (page: Page) => page.getByTestId("raw-value");

interface Setup {
  entries?: unknown[];
  verdict?: (request: Request) => Promise<{ status: number; body: unknown }>;
}

async function open(page: Page, setup: Setup = {}) {
  const lists: Request[] = [];
  const verdicts: Request[] = [];
  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));
  await page.route("**/normalization/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/normalization/, "");
    if (request.method() === "GET" && path === "/adjudication/review") {
      lists.push(request);
      return route.fulfill({ json: setup.entries ?? [B, C, A] }); // deliberately not in occurrence order
    }
    if (request.method() === "POST" && /^\/adjudication\/queue\/.+\/verdicts$/.test(path)) {
      verdicts.push(request);
      const answer = setup.verdict ? await setup.verdict(request) : { status: 201, body: {} };
      return route.fulfill({ status: answer.status, json: answer.body });
    }
    return route.fulfill({ status: 404, json: { detail: `no stub for ${request.method()} ${path}` } });
  });
  await page.clock.install();
  await page.goto("/#/review");
  // Keys pressed before the list has loaded would be lost, so wait for the first value.
  if (setup.entries === undefined || setup.entries.length > 0) await expect(raw(page)).toBeVisible();
  // Offline rule: nothing may be requested from an origin other than the page's own.
  const foreign = () => urls.filter((u) => new URL(u).origin !== new URL(page.url()).origin);
  return { lists, verdicts, foreign };
}


// ----------------------------------------------------------------------------- key handler, pure
const key = (k: string, extra: Partial<KeyEventLike> = {}): KeyEventLike => ({
  key: k,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  repeat: false,
  ...extra,
});

test.describe("key handler (pure function)", () => {
  test("each key maps to its action, and the four action keys are distinct", () => {
    for (let n = 1; n <= 9; n++) expect(actionForKey(key(String(n)), 9)).toEqual({ type: "pick", index: n - 1 });
    expect(actionForKey(key("o"), 2)).toEqual({ type: "other" });
    expect(actionForKey(key("k"), 2)).toEqual({ type: "keep" });
    expect(actionForKey(key("u"), 2)).toEqual({ type: "undo" });
    const names = ["1", "o", "k", "u"].map((k) => JSON.stringify(actionForKey(key(k), 2)));
    expect(new Set(names).size).toBe(4);
  });

  test("a number beyond the readings, 0, and any other key do nothing", () => {
    expect(actionForKey(key("3"), 2)).toBeNull();
    expect(actionForKey(key("0"), 9)).toBeNull();
    for (const k of ["Enter", " ", "a", "Escape", "ArrowRight", "y"]) expect(actionForKey(key(k), 2)).toBeNull();
  });

  test("no key works with a modifier, while held down, or in a text box", () => {
    for (const mod of ["ctrlKey", "metaKey", "altKey", "shiftKey"] as const) {
      for (const k of ["1", "o", "k", "u"]) expect(actionForKey(key(k, { [mod]: true }), 2)).toBeNull();
    }
    expect(actionForKey(key("1", { repeat: true }), 2)).toBeNull();
    expect(actionForKey(key("k", { isComposing: true }), 2)).toBeNull();
    for (const tagName of ["INPUT", "TEXTAREA", "SELECT", "input"]) expect(actionForKey(key("1"), 2, { tagName })).toBeNull();
    expect(actionForKey(key("k"), 2, { tagName: "DIV", isContentEditable: true })).toBeNull();
    expect(actionForKey(key("k"), 2, { tagName: "BUTTON" })).toEqual({ type: "keep" });
  });
});

// ----------------------------------------------------------------------------- readings, pure
test.describe("candidate readings", () => {
  test("date readings become ISO values computed from the calendar; a two-digit year is not sent", () => {
    const readings = extractReadings(A.detail);
    expect(readings.map((r) => r.value)).toEqual([dmy(A), mdy(A)]);
    expect(readings.map((r) => r.tag)).toEqual(["DMY", "MDY"]);
    const short = extractReadings({ structured: { candidates: [{ interpretation: "DMY", day: "05", month: "06", year: "21" }] } });
    expect(short[0].value).toBeNull();
    expect(short[0].note).not.toBe("");
  });

  test("strings are their own value, names use Family, Given, unknown shapes are shown as JSON and not sent", () => {
    expect(extractReadings({ structured: { candidates: ["USD", "CAD"] } }).map((r) => r.value)).toEqual(["USD", "CAD"]);
    const name = extractReadings({ structured: { candidates: [{ given_name: "Ana", family_name: "Lee" }] } });
    expect(name[0].value).toBe("Lee, Ana");
    const odd = extractReadings({ structured: { candidates: [{ foo: 1 }] } });
    expect(odd[0]).toMatchObject({ shown: '{"foo":1}', value: null });
    expect(extractReadings({ structured: {} })).toEqual([]);
    expect(extractReadings(null)).toEqual([]);
  });
});

// ----------------------------------------------------------------------------- queue, pure
test.describe("queue state (pure reducer)", () => {
  const run = (s: QueueState, ...actions: Parameters<typeof queueReducer>[1][]) => actions.reduce(queueReducer, s);
  const start = () => initialQueue(["a", "b", "c"]);
  const decide = { type: "decide", value: "v", rationale: "r" } as const;

  test("deciding and keeping both advance; keeping stores nothing and the item stays unsent", () => {
    const s = run(start(), decide, { type: "skip" });
    expect(s.cursor).toBe(2);
    expect(s.items.map((i) => i.status)).toEqual(["held", "skipped", "pending"]);
  });

  test("undo returns to the value and clears the held decision", () => {
    const s = run(start(), decide, { type: "undo" });
    expect(s.cursor).toBe(0);
    expect(s.items[0]).toMatchObject({ status: "pending", value: undefined });
  });

  test("undo of a saved decision is refused with a notice and changes nothing else", () => {
    const s = run(start(), decide, { type: "sending", key: "a" }, { type: "saved", key: "a" }, { type: "undo" });
    expect(s.items[0].status).toBe("saved");
    expect(s.cursor).toBe(1);
    expect(s.notice).toMatch(/already saved/i);
  });

  test("a failed send makes the item pending again with the API's text", () => {
    const s = run(start(), decide, { type: "sending", key: "a" }, { type: "failed", key: "a", message: "nope" });
    expect(s.items[0]).toMatchObject({ status: "pending", error: "nope" });
  });
});

// ----------------------------------------------------------------------------- the screen
test("shows the most frequent value first with its count, all readings, and n of N; nothing is pre-selected", async ({ page }) => {
  await open(page);
  await expect(raw(page)).toHaveText(A.original);
  await expect(position(page)).toHaveText("1 of 3");
  await expect(page.getByTestId("occurrences")).toHaveText("9 occurrences");
  const readings = page.getByRole("group", { name: "Candidate readings" }).getByRole("button");
  await expect(readings).toHaveCount(2);
  await expect(readings.nth(0)).toContainText(dmy(A));
  await expect(readings.nth(1)).toContainText(mdy(A));
  // No pre-selected reading: no pressed/checked/selected/active state anywhere on the card.
  await expect(page.locator('[aria-pressed="true"], [aria-checked="true"], [aria-selected="true"], [data-active], [data-checked], [data-selected]')).toHaveCount(0);
  await expect(page.locator("input:checked, option:checked")).toHaveCount(0);
});

test("order is by occurrences, 9 then 5 then 3, and the list is requested once", async ({ page }) => {
  const { lists } = await open(page);
  await expect(page.getByTestId("occurrences")).toHaveText("9 occurrences");
  await page.keyboard.press("k");
  await expect(page.getByTestId("occurrences")).toHaveText("5 occurrences");
  await expect(position(page)).toHaveText("2 of 3");
  await page.keyboard.press("k");
  await expect(page.getByTestId("occurrences")).toHaveText("3 occurrences");
  await page.keyboard.press("k");
  await expect(page.getByTestId("review-done")).toBeVisible();
  expect(lists).toHaveLength(1);
});

test("Enter, Space and an accept key before choosing send nothing", async ({ page }) => {
  const { verdicts } = await open(page);
  await expect(raw(page)).toBeVisible();
  for (const k of ["Enter", " ", "a", "y"]) await page.keyboard.press(k);
  await page.clock.fastForward(HOLD_MS * 2);
  expect(verdicts).toHaveLength(0);
  await expect(position(page)).toHaveText("1 of 3");
});

test("every action has a visible button with its key shown and aria-keyshortcuts", async ({ page }) => {
  await open(page);
  const expected: [string, string][] = [["Other value", "o"], ["Keep ambiguous", "k"], ["Undo", "u"]];
  for (const [name, k] of expected) {
    const button = page.getByRole("button", { name: new RegExp(name) });
    await expect(button).toBeVisible();
    await expect(button).toHaveAttribute("aria-keyshortcuts", k);
    await expect(button).toContainText(k);
  }
  const readings = page.getByRole("group", { name: "Candidate readings" }).getByRole("button");
  for (const n of [0, 1]) await expect(readings.nth(n)).toHaveAttribute("aria-keyshortcuts", String(n + 1));
});

for (const how of ["key", "button"] as const) {
  test(`picking reading 2 by ${how} sends the verdict after the undo window`, async ({ page }) => {
    const { verdicts } = await open(page);
    await expect(raw(page)).toHaveText(A.original);
    if (how === "key") await page.keyboard.press("2");
    else await page.getByRole("group", { name: "Candidate readings" }).getByRole("button").nth(1).click();
    await expect(raw(page)).toHaveText(B.original); // advanced at once
    expect(verdicts).toHaveLength(0); // still held back
    await page.clock.fastForward(HOLD_MS + 1000);
    await expect.poll(() => verdicts.length).toBe(1);
    expect(verdicts[0].url()).toContain(`/adjudication/queue/${A.key}/verdicts`);
    const body = verdicts[0].postDataJSON();
    expect(body).toEqual({ decided_value: mdy(A), decided_by: "human:reviewer", rationale: expect.stringMatching(/\S/) });
    expect(body.rationale).not.toContain(A.original); // the rationale must not echo the raw value
  });
}

test("o opens a text field; keys are ignored while typing; Enter sends the typed text", async ({ page }) => {
  const { verdicts } = await open(page);
  await expect(raw(page)).toHaveText(A.original);
  await page.keyboard.press("o");
  const field = page.getByLabel("Other value");
  await expect(field).toBeFocused();
  await expect(field).toHaveValue(""); // the "o" itself was not typed
  const typed = "2021-06-05 k1u";
  await page.keyboard.type(typed);
  await expect(field).toHaveValue(typed);
  await expect(position(page)).toHaveText("1 of 3"); // k, 1 and u did nothing
  await page.keyboard.press("Enter");
  await expect(raw(page)).toHaveText(B.original);
  await page.clock.fastForward(HOLD_MS + 1000);
  await expect.poll(() => verdicts.length).toBe(1);
  expect(verdicts[0].postDataJSON().decided_value).toBe(typed);
});

test("Escape closes the text field without deciding", async ({ page }) => {
  const { verdicts } = await open(page);
  await page.keyboard.press("o");
  await page.keyboard.press("Escape");
  await expect(page.getByLabel("Other value")).toHaveCount(0);
  await page.clock.fastForward(HOLD_MS * 2);
  expect(verdicts).toHaveLength(0);
});

test("k keeps the value ambiguous: nothing is sent, and it can be reviewed again", async ({ page }) => {
  const { verdicts } = await open(page);
  await page.keyboard.press("k");
  await expect(raw(page)).toHaveText(B.original);
  await page.keyboard.press("k");
  await page.keyboard.press("k");
  await expect(page.getByTestId("review-done")).toBeVisible();
  await page.clock.fastForward(HOLD_MS * 2);
  expect(verdicts).toHaveLength(0);
  await page.getByRole("button", { name: /review the open values again/i }).click();
  await expect(raw(page)).toHaveText(A.original);
  await expect(position(page)).toHaveText("1 of 3");
});

test("u inside the window cancels the decision and returns to the value; nothing is sent", async ({ page }) => {
  const { verdicts } = await open(page);
  await expect(raw(page)).toHaveText(A.original);
  await page.keyboard.press("1");
  await expect(raw(page)).toHaveText(B.original);
  await page.keyboard.press("u");
  await expect(raw(page)).toHaveText(A.original);
  await expect(position(page)).toHaveText("1 of 3");
  await page.clock.fastForward(HOLD_MS * 2);
  expect(verdicts).toHaveLength(0);
});

test("u after the decision was sent says it is saved", async ({ page }) => {
  const { verdicts } = await open(page);
  await page.keyboard.press("1");
  await page.clock.fastForward(HOLD_MS + 1000);
  await expect.poll(() => verdicts.length).toBe(1);
  await expect(page.getByText(/1 saved/)).toBeVisible();
  await page.keyboard.press("u");
  await expect(page.getByText(/already saved/i)).toBeVisible();
  await expect(raw(page)).toHaveText(B.original);
});

test("the next value is on screen within 0.1 s of the key, and without waiting for the network", async ({ page }) => {
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => (release = resolve));
  const { verdicts } = await open(page, { verdict: async () => (await gate, { status: 201, body: {} }) });
  await expect(raw(page)).toHaveText(A.original);
  // NN/g: 0.1 s is the limit for a response to feel instant (report U1 "Speed").
  const elapsed = await page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        const target = document.querySelector('[data-testid="raw-value"]') as HTMLElement;
        const start = performance.now();
        new MutationObserver((_, observer) => {
          observer.disconnect();
          resolve(performance.now() - start);
        }).observe(document.body, { childList: true, subtree: true, characterData: true });
        target.dispatchEvent(new KeyboardEvent("keydown", { key: "k", bubbles: true }));
      }),
  );
  expect(elapsed).toBeLessThan(100);
  await page.keyboard.press("2");
  await expect(position(page)).toHaveText("3 of 3");
  await page.clock.fastForward(HOLD_MS + 1000);
  await expect.poll(() => verdicts.length).toBe(1);
  // The POST is still unanswered and the screen has already moved on.
  await expect(position(page)).toHaveText("3 of 3");
  release?.();
  await expect(page.getByText(/1 saved/)).toBeVisible();
});

test("the API's 422 text is shown and the value can be reopened", async ({ page }) => {
  const message = "decided value normalizes to AMBIGUOUS with display set, not to a clean value; nothing stored";
  await open(page, { verdict: async () => ({ status: 422, body: { detail: message } }) });
  await page.keyboard.press("1");
  await page.clock.fastForward(HOLD_MS + 1000);
  await expect(page.getByText(message).first()).toBeVisible();
  await page.getByRole("button", { name: "Go back to it" }).click();
  await expect(raw(page)).toHaveText(A.original);
  await expect(position(page)).toHaveText("1 of 3");
});

test("leaving the screen sends a decision that is still held back", async ({ page }) => {
  const { verdicts } = await open(page);
  await expect(raw(page)).toHaveText(A.original);
  await page.keyboard.press("1");
  await expect(raw(page)).toHaveText(B.original);
  expect(verdicts).toHaveLength(0);
  await page.evaluate(() => (window.location.hash = "#/does-not-exist"));
  await expect.poll(() => verdicts.length).toBe(1);
  expect(verdicts[0].postDataJSON().decided_value).toBe(dmy(A));
});

test("an empty list says so, and no request goes to another origin", async ({ page }) => {
  const { foreign } = await open(page, { entries: [] });
  await expect(page.getByText(/nothing to review/i)).toBeVisible();
  expect(foreign()).toEqual([]);
});

test("an entry whose detail has no known reading shows the detail and can only be decided with o or kept", async ({ page }) => {
  await open(page, { entries: [{ ...A, detail: { structured: { shape: "new" } } }] });
  await expect(page.getByText(/no candidate readings/i)).toBeVisible();
  await expect(page.getByText('"shape": "new"')).toBeVisible();
  await expect(page.getByRole("group", { name: "Candidate readings" }).getByRole("button")).toHaveCount(0);
});
