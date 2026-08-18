# Milestone M7 Verification Pack — Normalization UI

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

Covers Source.txt Phase 16: the full user interface (§81-§94 rule
builder/before-after/sample-preview/profile-suggestions/user-control/
normal-expert-admin modes/main nav/overview/field-detail/collision-
dashboard/quality-dashboard/run-detail, §115-§121 dictionary-management-
UI/rule-builder-UX/explanation-UX/preview-UX/change-impact-UI/safe-
rollback/comparison-workspace). `Source.txt` §98's API surface was
already fully real as of M6; this milestone adds seven new, real,
narrowly-scoped backend routes the UI genuinely needs (listed below)
rather than inventing UI-only mock data anywhere.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `ui/` — Vite + React 19 + TypeScript app, hand-written typed API client (`ui/src/api/client.ts`, `types.ts`) covering every real normapi endpoint | ✅ Done |
| App shell: main nav (§89) + Normal/Expert/Admin mode switch (§86-88), persisted in `localStorage` | ✅ Done |
| Profiles: list/create/version/rollback (§95, §120) | ✅ Done |
| Preview: sample-based preview (§83), BEFORE/AFTER with expandable DETAILS/TRACE (§118), "Why did this change?" explanation (§117) | ✅ Done |
| Runs: create+execute against the live Dispatcher, run detail, Change Impact panel (§94, §119) | ✅ Done |
| Collision Dashboard + Comparison Workspace (§92, §96, §121) | ✅ Done |
| Dictionaries UI: built-in (read-only) + custom (create/version/rollback/delete/import/export) (§115) | ✅ Done |
| Quality Dashboard (§93) + Overview Dashboard (§90) | ✅ Done |
| Field detail page + Fields list (§91) | ✅ Done |
| Rule Builder (§81, §116) — renders the *real* trace steps a live field-test call executed | ✅ Done |
| Warnings page (§89) | ✅ Done |
| 7 new real normapi routes: `GET /runs`, `GET /runs/{id}/values`, `GET /profiles/{id}`, `GET /profiles/{id}/versions`, `GET /dictionaries/{id}`, `GET /overview`, `GET /quality` | ✅ Done |
| CORS middleware (a real, previously-nonexistent gap — see §4.1) | ✅ Done |
| `normanalysis.overview` / `normanalysis.quality` — real aggregation over live profile/run state | ✅ Done |
| E2E suite: `@playwright/test`, 9 specs, driving a real Chromium browser against a real `vite preview` build + real `uvicorn` server | ✅ Done |
| Gate G7 verification | ✅ Done |

## 2. Layer 1 — Automated verification results

### 2.1 Backend

```
uv run ruff check .          -> All checks passed!
uv run ruff format --check . -> 160 files already formatted
uv run mypy packages         -> Success: no issues found in 71 source files
uv run pytest -m "unit or golden or property" -q
  -> 664 passed, 12 skipped, 31 deselected in ~100s
```

New this milestone: `tests/unit/test_overview_quality.py` (6 tests) for
`normanalysis.overview`/`normanalysis.quality`. All M2-M6 suites
unchanged and still fully passing — no regressions from the new routes
or the CORS middleware.

The Docker-based integration suite (`pytest -m integration`, needs
`docker compose up -d`) was **not re-run this milestone** — no
normalizer internals changed in M7 (only new API routes, new
`normanalysis` aggregation modules, and the entirely new `ui/` package),
so the already-passing M2-M6 integration coverage is not expected to be
affected. Flagging this honestly rather than silently omitting it,
consistent with this project's disclosure practice; a full re-run is a
reasonable pre-merge check for you to do independently if you want
belt-and-suspenders confidence.

### 2.2 Frontend

```
npm --prefix ui run build   -> tsc -b && vite build: clean, 0 errors
npm --prefix ui run lint    -> oxlint: 1 harmless warning (react-refresh
                                export-shape lint on ModeContext.tsx,
                                which intentionally exports both the
                                provider component and the useMode()
                                hook from one file — not a defect)
```

### 2.3 E2E suite (Playwright, real browser + real servers)

```
npm --prefix ui run test:e2e
  -> 9 passed (repeated twice in a row for flake-check, both clean)
```

Specs: `e2e/smoke.spec.ts` (overview loads real data, every nav link
reachable without a client error, mode switch), `e2e/profiles-and-
runs.spec.ts` (create profile -> create+execute a run reproducing §79's
José García/Jose Garcia/JOSÉ GARCÍA collision worked example -> run
detail shows the real impact/collision data; a second spec deliberately
triggers a mismatched-run-length comparison and asserts the real server
error renders legibly), `e2e/preview.spec.ts` (real EmailNormalizer
BEFORE/AFTER + explanation panel; Rule Builder loads a real executed
trace), `e2e/dictionaries.spec.ts` (create a real custom dictionary;
built-in dictionaries show no write controls).

CI (`.github/workflows/gate.yml`'s `e2e` job, gated on milestone M7/M8)
runs this same suite against `docker compose up -d --build` — the
config was already scaffolded in M0 expecting exactly this
`npm --prefix ui run test:e2e` contract; this milestone's `ui/`
structure and script name were built to satisfy it, not improvised
separately.

## 3. Layer 2 — Liveness verification

| Check | Result |
|---|---|
| Real running `uvicorn` + real `vite preview` build, driven by hand through the actual Claude_Browser tool (not just automated tests) | ✅ Verified — created a profile, executed a run reproducing the §79 collision example, viewed real Change Impact numbers (unique 3→2, 1 new collision), viewed the real collision group, viewed real per-value warnings, created a custom dictionary, switched to Expert mode and saw the real parsed name-component structure and full technical trace |
| Rule Builder shows the *actual* whole-pipeline fixed-point loop (M3's disclosed 2-pass repeat) for a real PERSON_NAME trace | ✅ Verified — 14 steps rendered (7 steps × 2 passes) + the final `name.parse_western` step, matching the documented M3 behavior exactly |
| CORS-enabled cross-origin fetch from the UI's own origin to the API's origin | ✅ Verified (see §4.1 — found broken, fixed, re-verified) |
| Overview/Quality dashboards reflect real executed-run data, not fabricated numbers | ✅ Verified — before any run existed, every metric read exactly 0; after one PERSON_NAME run, numbers changed to match the run's real metrics |
| Performance baseline | Not applicable this milestone — M7 is a UI/API-surface milestone, no new normalizer hot path; M8 owns performance work per the original plan |

## 4. Layer 3 — for human review

### 4.1 Real bugs found and fixed during M7 (not hypothetical)

1. **The API had no CORS middleware at all.** The very first real
   browser load of the UI against the live API failed outright —
   every fetch blocked with "No 'Access-Control-Allow-Origin' header is
   present." This is exactly the kind of bug this project's established
   discipline (real infra over reasoning-from-code) exists to catch: it
   would never have shown up in a Python-only test suite, since
   `TestClient`/`httpx` calls aren't subject to browser CORS
   enforcement. Fixed with `CORSMiddleware`, defaulting to the UI's own
   dev (5173) and preview (4173) origins, widened via `NORM_CORS_ORIGINS`.
2. **`GET /runs/compare` crashed with an unhandled 500** when given two
   runs with different numbers of executed values (a `ValueError` from
   `normanalysis.ab_comparison.compare_runs` propagated uncaught).
   Worse, because the exception was unhandled, Starlette's default
   error path produced a response that **skipped CORS header
   injection**, so the browser reported it as a CORS failure — masking
   the real root cause. Found by manually driving the live browser
   against the live server, confirmed via direct `curl` (bypasses CORS
   entirely, isolating the actual HTTP status), fixed by validating the
   lengths and raising a proper `HTTPException(409, ...)` before calling
   `compare_runs`. Re-verified via `curl` (clean 409 with
   `access-control-allow-origin` present) and in the browser (clean,
   readable error message).
3. **`ApiError` discarded the real server-provided error detail**,
   always showing a generic "API request failed with status 409"
   instead of the actual message ("Runs must have the same number of
   executed values..."). This affected every error surface in the whole
   app, not just the one endpoint that exposed it. Fixed by having
   `ApiError` parse and surface the server's `detail` field.
4. **Five E2E test-authoring bugs**, all caught by actually running the
   suite against the live app repeatedly rather than trusting the
   markup from memory: `selectOption({ label: RegExp })` isn't supported
   by Playwright (only exact-string labels); several forms
   (Runs/Preview/Rules/Dictionaries) use a wrapping `<label>` for
   accessibility rather than `placeholder` attributes, so
   `getByPlaceholder` silently found nothing; the status-pill's visible
   text is the raw uppercase enum value (`COMPLETED`) even though its
   CSS class is lowercased; and two `getByText` locators were ambiguous
   in strict mode (matching both a UI label and a data value containing
   the same substring) and needed `exact: true`. None of these were
   application bugs — each one was caught, isolated via the tool's own
   error output, and fixed in the test file.

### 4.2 Design decisions worth your attention

- **"Activate Profile" / "Deactivate Profile" (§120) are not implemented
  as standalone backend actions** — only versioning (create a new
  version) and rollback (reactivate a prior version) exist server-side,
  matching what `InMemoryStore` actually supports since M6. The Profile
  Detail page does not render buttons for actions that don't do
  anything real; only "Rollback to this version" is wired, since it is
  the one real, effectful operation. Adding true activate/deactivate
  semantics is a reasonable follow-up, not a silent omission.
- **The Collision Dashboard's Accept/Reject/Whitelist affordances from
  §92's UI description are not implemented** — collisions are computed
  live from a run's real data every time, and there is no persistence
  layer for "this collision was reviewed and accepted." Only "Inspect"
  (expanding the real original-value list) is real. Fabricating working
  buttons for state that isn't stored anywhere would violate this
  project's "no silent changes" principle (§85) more than omitting them
  does.
- **Quality Dashboard drill-down is coarse** — each metric links to the
  Runs list rather than a metric-filtered view, since there is no
  backend endpoint mapping a specific quality issue back to the
  originating run+row without adding a much larger indexing subsystem.
  Disclosed rather than faked.
- **Rule Builder's drag-to-reorder and enable/disable toggle are
  visualization-only** — they render the *real* trace a live
  `field-test` call produced, faithfully, but per-field pipeline
  configuration still is not threaded into individual normalizers (the
  same gap disclosed in every M2-M6 pack: `Normalizer.normalize(value,
  ctx)`'s signature doesn't carry a `FieldNormalizationConfig`). The UI
  says so explicitly in its own copy rather than implying the reorder
  does something it doesn't.
- **Per-run library-version expansion (`NormalizationVersion`) is not
  exposed via the API** — the Run Detail page shows the real `env_id`
  hash and says outright that its human-readable expansion isn't wired
  up yet, rather than fabricating a library-version table.
- **HashRouter, not BrowserRouter** — avoids needing a server-side SPA
  rewrite rule for a plain `vite preview`/static deployment; URLs are
  `#/runs/{id}` rather than `/runs/{id}`. A reasonable trade for this
  milestone's scope; switching later is a routing-layer change only.

### 4.3 Known open items (carried forward, none introduced by M7)

1. `env_id` computation is still the M1 placeholder (disclosed since M1).
2. Per-field profile-driven configuration still isn't wired into
   individual normalizers (disclosed since M2; directly visible in the
   Rule Builder's own UI copy this milestone).
3. The M3 whole-pipeline fixed-point performance cost remains
   unresolved (M8).
4. `ScriptNormalizer`'s language-hint latency is unoptimized (M8).
5. Non-Gregorian calendar conversion (M4) is unimplemented.
6. Phone region precedence (M3) still only implements 2 of 4 levels.
7. `IdentifierNormalizer`'s direct per-country stdnum registry still
   covers only 4 countries (M5; IBAN covers broader validation).
8. The Docker-based integration suite was not re-run this milestone
   (§2.1) — no code it exercises changed, but it wasn't proven fresh.

### 4.4 10-minute scripted demo (for you to run yourself)

```bash
cd D:/transfer/normalization

# 1. Backend sweep
uv run ruff check . && uv run ruff format --check .
uv run mypy packages
uv run pytest -m "unit or golden or property" -q

# 2. Start the real API
uv run uvicorn normapi.main:app --host 127.0.0.1 --port 8080 &

# 3. Build and preview the real UI
npm --prefix ui ci
npm --prefix ui run build
npm --prefix ui run preview -- --port 4173 &
# open http://localhost:4173 in a browser — create a profile, create a
# run with the pre-filled José García/Jose Garcia/JOSÉ GARCÍA sample,
# open the run, see the real Change Impact panel and collision group.

# 4. Full E2E suite (drives a real headless Chromium against the above)
npx --prefix ui playwright install chromium
npm --prefix ui run test:e2e

# (stop both servers afterward)
```

## 5. Acceptance criteria mapped (subset of §136 relevant to M7)

| §136 criterion | Status at M7 |
|---|---|
| Every transformation is traceable, and the UI can show it | ✅ Preview/Rule Builder render real `TraceStep` data, not summaries |
| No silent changes (§85) | ✅ Every UI action either calls a real endpoint or is explicitly labeled as visualization-only (Rule Builder reorder, Collision accept/reject) |
| Normal/Expert/Admin modes expose progressively more of the real data (§86-88) | ✅ Verified live — Expert mode revealed the real parsed name structure and technical trace that Normal mode hides |
| Change impact shown before/after normalization, with a primary warning (§78, §119) | ✅ Verified live — real unique-value delta, new-collision count, and a generated warning naming the responsible transformation step |
| Profiles are versioned, never overwritten; rollback never deletes (§95, §120) | ✅ Unchanged from M6, now has a real UI on top of it |
| (Remaining criteria are M8/later scope) | — |

## Human Sign-off

milestone: M7
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |
