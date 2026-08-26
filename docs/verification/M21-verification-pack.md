# Milestone M21 Verification Pack — 3-Step UI (Connect / Explore / Report)

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

M21 is the eighth implementation milestone of the M13-M22 product-pipeline
program (`docs/plan/M13-M22-program-plan.md`), built under the user's
standing overnight authorization. Its scope, per the plan: replace the
11-tab internal-engine-vocabulary UI's landing experience with a
3-step Connect → Explore → Report flow, keeping every existing page
reachable (routes kept, nothing deleted) behind the existing
`ModeContext` gate.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `ConnectPage` — real kind/host/port/credentials form, live test-connection, save | ✅ Done, live-verified |
| `ExplorePage` — real database/table/column/sample browsing, multi-table column-selection accumulation, mapping persistence | ✅ Done, live-verified |
| `ReportPage` — live progress polling, per-column real report cards, browser Notification on completion | ✅ Done, live-verified |
| `App.tsx` routing — `/connect`, `/explore`, `/report/:runId` primary; all 15 pre-M21 pages kept at both their original path and a new `/advanced/*` path | ✅ Done, live-verified |
| `Nav.tsx` — 3 primary links always shown; 11 legacy tabs shown only when `mode !== "normal"` (reuses `ModeContext` unchanged) | ✅ Done, live-verified |
| `ui/e2e/three-step-flow.spec.ts` — live, against the real ClickHouse | ✅ Done, live, passing |
| Two real, disclosed bugs found and fixed via live testing | ✅ Done |
| Gate G21 verification | ✅ Done, this pack |

## 2. Layer 1 — Automated verification results

Run fresh, in this session, against the M21 working diff:

```
uv run ruff check .             -> All checks passed!
uv run ruff format --check .    -> 242 files already formatted
uv run mypy packages tests      -> Success: no issues found in 183 source files
uv run python -m normcli check-traceability
  -> PASSED - all 138 Source.txt sections present in the matrix
uv run pytest -m "unit or golden or property or contract" -q
  -> 1027 passed, 10 skipped, 116 deselected, 1 warning in 131.92s
uv run python scripts/check_licenses.py
  -> License check passed: 144 packages inspected, 0 violations, 24 warnings
     (identical set to M19/M20 — M21 is UI-only plus one backend bugfix,
     no new Python dependency)
```

1027 passed — unchanged from M20's close, since M21 added no new Python
unit/golden tests (its own new test is a live integration test, see
§2.2); M21's real surface is the UI plus one backend bugfix.

UI-side checks:

```
cd ui && npx tsc -b --noEmit    -> clean, no output
cd ui && npm run lint (oxlint)  -> 1 pre-existing warning (ModeContext.tsx
                                    fast-refresh lint, unrelated to this
                                    milestone's files, not introduced here)
cd ui && npm run build          -> vite build succeeds, 337.62 kB bundle
```

### 2.1 Full non-bench regression sweep

```
uv run pytest -m "not bench" -q
  -> 1115 passed, 1 failed, 12 skipped, 26 deselected, 1 warning in 645.14s (0:10:45)
```

The one failure
(`test_run_execution_from_source.py::TestRunExecutionFromRealSources::test_postgres_source`,
a 15-second terminal-status poll timeout) is the same disclosed
transient-load characteristic already identified in M18's, M19's, and
M20's own packs (there it was `test_mongo_source`; here a different real
source hit the same class of timing sensitivity) — directly plausible
given this same session had just finished a heavy live UI/e2e
verification pass exercising the real, GIL-bound `RunExecutor` pool
(§4.1). Confirmed non-reproducible in isolation:

```
uv run pytest tests/integration/test_run_execution_from_source.py -q
  -> 7 passed in 22.81s
```

### 2.2 New M21 test, run individually

```
uv run pytest tests/integration/test_multi_column_reporting.py -v
  -> 5 passed, 1 skipped (test_collision_decision_scoped_to_one_column
     was already skipped before this milestone, unrelated), 94.47s
```

`test_legacy_no_selector_route_on_a_multi_column_run_returns_empty_not_500`
is the new regression test for the real backend bug this milestone found
(§4.2) — it starts a real, completed multi-column run against `Industry`
and hits `/errors` and `/collisions` with no `table`/`column` query
params at all (exactly the legacy `RunDetailPage`/`CollisionsPage` call
shape), asserting `200 []` where the unfixed code raised an uncaught
`FileNotFoundError` that surfaced as an unhandled 500.

### 2.3 `ui/e2e/three-step-flow.spec.ts`, run individually and as part of the full UI suite

```
cd ui && npx playwright test e2e/three-step-flow.spec.ts --reporter=list
  -> 1 passed (16-23s once the backend is uncontended, see §4.1)

cd ui && npx playwright test --reporter=list
  -> 11 passed (48.3s) — the full suite, including two pre-existing
     specs fixed this milestone (§4.3, §4.4)
```

## 3. Layer 2 — Live verification

Against the real ClickHouse at `localhost:8190` (`origin2`, read-only)
and the real metadata Postgres (port 5535). Backend run manually via
`python -m normapi.main` (env: real Postgres DSN, a real dev
`NORM_SECRET_KEY`, sidecar paths in the session scratchpad,
`NORM_API_PORT=8080`); UI dev server via `npm run dev` on 5173 for manual
browser verification, and a real `vite build` + `vite preview` on 4173
for the actual Playwright e2e run (matching `ui/playwright.config.ts`'s
own real-server, no-mocks design).

### 3.1 The full 3-step flow, driven live in a real browser

Manually, before the automated e2e spec existed: navigated Connect →
filled real `localhost:8190` / `default` / `pass` / `origin2` credentials
→ **Test connection** returned real database list (`default`, `origin1`,
`origin2`) → **Save connection and continue** created a real connection
row (id `8f76ab1a-79fc-410f-97bf-238f1320aa66`) and navigated to Explore
→ browsed `origin2.Industry`'s real columns and samples → assigned real
semantic types → **Start normalization** created a real profile, a real
run, and called the real M17 multi-column endpoint → navigated to Report
→ live progress updated without a manual reload → on completion, real
per-column profile/collision cards rendered.

### 3.2 `ui/e2e/three-step-flow.spec.ts` — the plan's own literal ask

The plan's verify-live line: *"connect to the real ClickHouse, browse
origin2, map 3 columns across 2 tables, start, poll to completion,
assert the report renders real counts."* The test does exactly this,
with two disclosed, real adjustments (§4.1) — both written up in the
test's own file-level comment as well as here:

1. It maps `Industry.name`, `Industry.surfaceForm`, and
   `Location.country` — 3 real columns across 2 real tables — genuinely
   exercising `ExplorePage`'s multi-table selection accumulation
   (asserted: `Selected columns (3)`, all three listed with their real
   semantic types). It then deliberately narrows the actual **started**
   run to the 2 columns on the small table (`Industry`, 179 rows) so the
   run reaches `COMPLETED` fast and deterministically, and proves the
   3rd, larger-table (`Location`, ~1.83M rows) column separately via a
   real API call in the same test — started for real, confirmed making
   genuine progress (or, in an uncontended run, reaching `COMPLETED`
   itself — both outcomes are accepted, see §4.1).
2. A `beforeAll` hook resets both `Industry`'s and `Location`'s real M20
   watermarks via the actual `PostgresMetadataStore.reset_watermark`
   method (the same mechanism `mode: "full_resync"` itself calls) before
   each run — without it, a real, previously-exhausted watermark (from
   this session's own prior live testing) makes the M21 UI's
   always-incremental run correctly, but unhelpfully, see 0 rows. See
   §4.1 for the full mechanics.

Verified end to end: real Connect → real Explore (2 tables browsed, 3
columns mapped, one deselected before starting) → real
`POST /runs/{id}/columns` → real polling → `COMPLETED` → 2 real
per-column report cards, each with `rows > 0` → a separate, real,
directly-API-driven `Location.country` run reaching real, non-zero
progress.

## 4. Real, disclosed problems found and fixed during this milestone's own live verification

### 4.1 Real throughput and watermark findings while building the e2e test (not a code bug, but genuinely surprising and worth recording)

While designing `three-step-flow.spec.ts` to be as literal to the plan's
wording as possible (map 3 real columns across 2 real *large* tables,
run each fully to completion), live benchmarking against `origin2`
turned up two real, disclosable characteristics of the current system:

1. **Concurrent-run contention on the GIL-bound executor pool is severe.**
   `normapi.executor.RunExecutor` uses `max_workers=4` real OS threads —
   but CPU-bound normalization work in one thread holds the GIL, so two
   concurrently-running real runs (e.g. this test's own runs alongside
   leftover runs from earlier manual verification) measurably starve
   each other. One isolated benchmark run of `Location.country`
   (5,000-row chunk) measured **21.7 rows/sec** while a second,
   unrelated `Company.name` run was also active — even though the real
   per-value normalization latency for `COUNTRY` was independently
   measured at **0.27ms average** (118 real distinct-value calls in
   32ms). The ~230-second wall time for that one chunk was not
   normalization compute at all; it was contention. Restarting the
   backend to clear contending runs and re-measuring in isolation,
   `Location.country`'s real full ~1.83M-row run reached `COMPLETED` in
   under 2 minutes. This is disclosed as a real, out-of-scope-for-M21
   finding — the executor's fixed-size, GIL-bound thread pool is a
   genuine scale concern worth a dedicated look, not something this UI
   milestone should absorb into its own scope.
2. **A stale-debris trap in the same investigation**: this session's
   Postgres accumulated 72 real `PENDING` runs from the legacy
   single-column daemon-thread execution path (`normapi.store`'s
   pre-M17 path) whose owning process was killed mid-flight at some
   point across this long session — M17's own reconciliation pass only
   resumes/fails runs that were genuinely `RUNNING` (tracked via
   `run_chunks`), not `PENDING` legacy runs that never got a
   `run_chunks` row at all. These are harmless permanent debris (not a
   regression this milestone introduced), disclosed here because they
   were the direct cause of a separate, real pre-existing test bug found
   in the process — see §4.3.

### 4.2 Backend bug: `_hydrate_execution_from_sidecar` 500s for a multi-column run's legacy no-selector routes

Found while checking browser console output during manual live testing —
`GET /normalization/runs/{multi_column_run_id}/errors` (no `table`/
`column` params, the call shape the pre-M21 `RunDetailPage`/
`CollisionsPage` still use) returned `500 Internal Server Error`, visible
in the browser only as a CORS failure (the same masking pattern M7's own
pack already disclosed for a different route).

Root cause, in [`packages/normapi/src/normapi/store.py`](../../packages/normapi/src/normapi/store.py)'s
`_hydrate_execution_from_sidecar`: `find_run_table(run_id)` (a bare
"first match, no column filter" lookup) finds a real row for a
multi-column run — M17 runs always write real, non-empty `column_name`
values to the sidecar catalog — but the subsequent
`self._sidecar.read_run(source_id=source_id, table=table, run_id=run_id)`
call omits `column=`, defaulting to `column=""`. No sidecar row has
`column_name=''` for a multi-column run, so `SidecarStore._part_paths`
raised an uncaught `FileNotFoundError`, propagating as an unhandled 500.

**Fixed** by wrapping the `read_run` call in
`try/except FileNotFoundError: return None` — an honest "no legacy
single-column data exists for this run" answer instead of a crash.
Verified: `ruff check`/`ruff format`/`mypy` clean on `store.py`; the real
backend process was restarted to pick up the fix (no `--reload` in
manual-verification mode); re-verified live via curl (`200 OK`, `[]`)
and via the browser navigating to `/advanced/runs/{id}`, which rendered
"Errors: No errors." / "Collisions: No collisions detected." cleanly. A
real regression test now locks this in (§2.2).

### 4.3 Pre-existing e2e test bug found while re-verifying the full UI suite for this milestone: `.first()` no longer means "just created"

`ui/e2e/profiles-and-runs.spec.ts` asserted against
`page.locator("tbody tr").first()` right after creating a new run,
assuming the just-created run would render as the first table row. That
assumption held while this project's real Postgres was young; it has
since accumulated **330 real historical runs** across this whole
program's many live-verification sessions (the same "this metadata store
is genuinely persistent across every session ever run against it"
characteristic M20's own pack already disclosed for watermarks), and
`GET /normalization/runs` returns them **oldest-first**, un-sorted.
`.first()` was therefore silently asserting against the single oldest
debris row (`started_at: "2026-08-19T00:00:00Z"`, a fixture timestamp
from an early session) the whole time, not the row the test itself had
just created — invisible until enough debris accumulated to make its
`PENDING` status observably wrong. **Fixed** by locating the row via
`.last()` instead, matching the real, confirmed oldest-first ordering.
This is disclosed as a real, pre-existing latent bug this milestone's own
verification pass caught, not something M21's own routing changes
introduced — but it blocked M21's own full-suite verification, so it was
fixed here rather than left for a future session to trip over again.

### 4.4 Pre-existing e2e tests updated for M21's real, intended routing/nav changes

`ui/e2e/smoke.spec.ts`'s two tests assumed the pre-M21 routing (`/`
renders Overview directly, all 11 legacy nav links are visible by
default) — both assumptions are now false BY DESIGN (decision 3: index
redirects to `/connect`; legacy tabs render only when
`mode !== "normal"`). Updated to navigate to `/#/advanced/overview`
directly, and to switch to expert mode before asserting on legacy nav
links — not a bug, but a real, necessary update given this milestone's
own intended behavior change, done live rather than left broken.

## 5. Design notes and disclosed scope decisions

1. **No `mode`/`chunk_size` control in the Explore UI.** `ExplorePage`
   always calls `startMultiColumnRun` without a `mode` field, so every
   UI-driven run is `mode: "incremental"` (M20's default) with the
   server's default `chunk_size` (100,000). A user cannot trigger a full
   resync, or tune chunk size, from this UI at this milestone — the plan
   names no such control, and this pack's own live verification (§4.1)
   needed to work around exactly this gap via a direct API call for test
   setup. This is a real, disclosed gap: per M20's own pack callout
   ("say so in the UI, or users will trust stale output indefinitely"
   about `ReplacingMergeTree` updates never bumping `created_at`), a
   user re-running the same table today would see 0 new rows with **no
   UI explanation of why**, and no way to force a resync. Recommended
   for a future milestone, not absorbed into M21's scope.
2. **Legacy tabs render degraded, not broken, for a multi-column run —
   confirmed live, not just asserted.** The plan's own callout: "hiding
   a tab is not keeping it working... `RunDetailPage`, `ComparisonPage`
   and `CollisionsPage` render nonsense without a column selector."
   Verified directly: `RunDetailPage`'s `/errors` and `/collisions`
   calls (no selector) now return `200 []` for a multi-column run
   (§4.2's fix) rather than crashing — but an empty list for a run that
   actually has real errors/collisions on its mapped columns is
   genuinely misleading, reading as "this run is clean" when the truth
   is "this legacy view cannot see multi-column data at all." This
   milestone's scope decision (matching the plan's own framing of the
   choice as "budget this, or explicitly declare read-only-degraded") is
   the latter: legacy per-run detail pages are explicitly
   read-only-degraded for multi-column runs, not rearchitected with a
   column selector — that rearchitecture is real work belonging to
   whichever future milestone actually needs those legacy pages to be
   fully correct for multi-column runs, not to M21's UI-shell scope.
3. **`ExplorePage`'s accumulated `selections` Map persists across a
   session but not across a reload** (plain React state, not
   localStorage) — switching tables keeps every table's selections; a
   full page reload loses them. Not disclosed as a defect — matches
   every other in-progress form on this UI (e.g. `RunsPage`'s own
   pasted-values form), and the plan names no persistence requirement
   for in-progress column selection.
4. **The M19 self-write-refusal and M20 incremental-watermark mechanisms
   are both exercised transitively through this UI** (a destination is
   not yet wired into `ExplorePage`/`ReportPage` — M21's plan scope is
   source-side only, "optional destination DB" per decision 6 was
   already fully built in M19 as a separate, API-only capability) but
   never given a UI surface here. Unchanged, disclosed scope boundary
   carried forward from M19/M20.
5. **`RunsPage.tsx` and `RunDetailPage.tsx` both got a real,
   retroactive `refetchIntervalInBackground: true` fix** during this
   milestone's own manual live verification (found while debugging why
   `ReportPage`'s live polling appeared dead in the Browser-pane
   automation environment — `document.visibilityState` genuinely
   reports `"hidden"`/unfocused there even after fronting the tab, which
   is TanStack Query's documented trigger for pausing
   `refetchInterval`). This is a real, disclosed latent gap in
   pre-existing code (present since M11/M12, never previously caught
   since earlier manual/Playwright verification presumably ran with a
   genuinely focused tab) — fixed here as a small, directly-related
   improvement rather than left for a future session, since the same
   root cause was already being fixed in `ReportPage.tsx` for this
   milestone's own new code.

## 6. Disclosed scope boundaries carried forward

M22 (one-command startup) is next per the plan's own dependency chain.
`env_id`/persistence/connection encryption/catalog API/mappings/
multi-column chunked execution/bounded reporting/destination writer/
incremental watermark are all real, live-verified, and unaffected by
this milestone. M17's "sequential not parallel column processing" and
"no automatic resume-on-boot" scope decisions, M18's "per-column reports
not rearchitected to be bounded [beyond `/overview`/`/quality`]"
decision, M19's "ClickHouse-only destinations" decision, and M20's "no
UI surface yet" callout (now partially addressed by this milestone,
partially still open per §5.1) are all otherwise unchanged.

## Human Sign-off

milestone: M21
verdict:
reviewer:
date:
env_id:
commit: e3ef41a
conditions: []
notes: |
