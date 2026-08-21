# Milestone M11 Verification Pack — Async Execution, Collision Workflow, Lightweight Auth

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

M11 followed the already-approved M9-M12 follow-on plan's own scope for
this milestone: async/batch job execution, the collision workflow
(§92's Accept/Reject/Whitelist actions), and lightweight auth. Two of
these three are pragmatic engineering additions layered onto the plan in
an earlier session, not literal Source.txt requirements — confirmed by
grepping the spec for `async`/`queue`/`job`/`authentic`/`authoriz`/
`role-based`/`RBAC` before starting: zero matches, and §123 Security is
specifically about PII masking, not access control. The collision
workflow, by contrast, IS a real, explicit §92 requirement ("Accept
rule / Reject rule / Inspect / Whitelist collision / Change
configuration") that had only ever had "Inspect" built, disclosed as a
gap since M7.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| Run execution genuinely asynchronous — `POST /runs` returns immediately, `RunStatus.RUNNING`/`FAILED` actually reachable and observable | ✅ Done |
| Real collision workflow (§92) — persisted Accept/Reject/Whitelist decisions | ✅ Done — backend only, UI deferred to M12 (see §4) |
| Lightweight API-key auth on mutating routes | ✅ Done |
| Gate G11 verification | ✅ Done |

### 1.1 Design decisions

**Async execution** — Source.txt §70's `NormalizationRun.status` already
modeled `RUNNING`/`FAILED` as real lifecycle states, and §98's own route
list already has `POST /normalization/runs` + `GET /normalization/runs/{id}`
with no separate job endpoint — the run-record-with-pollable-status was
always the intended mechanism; M6-M10's `execute_run()` just always
finished synchronously within the same request, so those states were
never actually observable. `InMemoryStore.start_run_execution()` is a
thin background-thread wrapper: `execute_run()` itself is untouched and
remains the synchronous, directly-testable primitive every prior test
already used.

**A real bug was caught, not shipped**, during implementation: an
initial version of `start_run_execution` marked the run `RUNNING` itself
before spawning the background thread, racing with `RunRecorder`'s own
PENDING-only construction guard (`RunRecorder.__init__` raises if handed
anything but a `PENDING` run — it owns that exact transition via its own
`.start()` method). Reproduced directly (not inferred) via a small
repro script, then fixed by having `start_run_execution` NOT also set
`RUNNING` — it now returns the still-`PENDING` run, and the recorder
inside the background thread owns the transition exclusively.

**Collision workflow** — no separate mechanism distinguishes
"accept/reject A RULE" from "accept/reject THIS COLLISION" in this
codebase (there's no rule-proposal engine to make those meaningfully
different actions), so `CollisionDecisionType` (ACCEPTED/REJECTED/
WHITELISTED) covers both real spec bullets with one enum. Decisions are
Postgres-persisted (ADR-013 already explicitly names collisions as
Postgres-backed metadata), keyed by `(run_id, normalized_value)` since
that pair already is a collision group's real identity.

**Auth** — one shared secret (`NORM_API_KEY`), gating only
POST/PUT/PATCH/DELETE, applied once at the `APIRouter` level (not
per-route) so a future mutating route is protected by construction.
Unset (default) disables auth entirely, matching every other optional-
integration env var (`NORM_PG_DSN`, `NORM_SIDECAR_*`,
`NORM_SOURCES_CONFIG_PATH`) — no user-management/RBAC system, which was
never specified and would be scope well beyond "lightweight."

## 2. Layer 1 — Automated verification results

```
uv run ruff check .          -> All checks passed!
uv run ruff format --check . -> 196 files already formatted
uv run mypy packages         -> Success: no issues found in 84 source files
uv run mypy tests            -> Success: no issues found (147+ source files across runs)
uv run python -m normcli check-traceability
  -> PASSED — all 138 Source.txt sections present in the matrix
uv run pytest -m "unit or golden or property or contract or integration" -q
  -> 886 passed, 10 skipped, 24 deselected, 0 failed
```

New this milestone (58 new tests across the three deliverables):
- `tests/unit/test_run_execution.py::TestStartRunExecution` (4 tests) —
  non-blocking return, real completion via polling, `resolve_values`
  failure -> `FAILED` with `failure_reason`, double-start on a terminal
  run still raises synchronously.
- Every existing golden/integration test that `POST`s to `/runs` and
  previously checked results immediately was updated to poll
  `GET /runs/{id}` for a terminal status first (`test_m6_corpus.py`,
  `test_m10_corpus.py`, `test_m10_source_execution.py`,
  `test_run_execution_from_source.py`) — the real, disclosed behavior
  change this milestone makes, not incidental churn.
- `tests/golden/test_m11_collision_workflow.py` (7 tests) — all three
  decision types, re-deciding overwrites the prior decision, a
  fabricated `normalized_value` is 404, an unknown run is 404.
- `tests/integration/test_postgres_store_integration.py` (+3 tests) —
  direct `PostgresMetadataStore` round-trip/upsert, decisions spanning
  multiple runs, and the real restart-simulation (second independent
  `InMemoryStore` sees what the first recorded).
- `tests/unit/test_auth.py` (8 tests) — disabled-by-default, 401 on
  missing/wrong/malformed key, success with the correct key, GET always
  open even with a key configured, `/health` always open.

## 3. Layer 2 — Live verification

### 3.1 Async execution, live

A real browser session against a real running API (not just
`TestClient`): submitted a run via the live Runs page, captured the
page mid-flight showing `pending`, and confirmed — **without a manual
reload** — the page's own polling (`refetchInterval`, added to
`RunsPage`/`RunDetailPage` specifically because the async change would
otherwise leave the page stuck showing a stale status) caught the real
transition to `completed` with real metrics. The backend was confirmed
independently via `curl` to show the same real `COMPLETED` run with
`records_processed: 3` and real per-value results.

Separately, the full integration suite was run against all 4 real DB
connector types with async execution live: `postgres`, `mysql`,
`mongo`, `clickhouse` demo containers all completed real source-mode
runs through the async path — 7/7 passed.

### 3.2 Collision workflow, live

`tests/integration/test_postgres_store_integration.py`'s new
restart-simulation test: a real `PassthroughNormalizer` run producing a
genuine collision (`"a"`/`"A"` casefold to the same comparison value),
a decision recorded against a real Postgres-backed `InMemoryStore`, then
recovered by a SECOND, independent `InMemoryStore` instance — the same
rigor M9's persistence tests established, applied to this new state.

### 3.3 Auth, live — a real process, real curl requests

Not simulated: started a real `uvicorn` process with `NORM_API_KEY` set,
then via `curl` against that real running process:

```
GET  /normalization/profiles            (no key)              -> 200
POST /normalization/profiles            (no key)               -> 401
POST /normalization/profiles            (wrong key)             -> 401
POST /normalization/profiles            (correct Bearer key)    -> 201
```

## 4. Disclosed scope boundaries

1. **Collision workflow and DB-connector UI wiring both stay backend-
   only**, consistent with the already-established M10 precedent
   (`CollisionsPage.tsx`'s own comment already disclosed
   Accept/Reject/Whitelist as needing "a persistence layer this
   milestone doesn't add" — that layer now exists, but wiring the
   buttons themselves is M12's "UI catch-up" job, not silently skipped).
2. **Async execution is still single-process, single-thread-per-run**,
   not a real distributed job queue (no Celery/Redis/etc. introduced) —
   a background Python thread per run, consistent with M9's own audit
   finding that this store's concurrency model is "Starlette's sync-
   route thread pool + a shared mutable dict," not something requiring
   new infrastructure to reason about safely for this scope.
3. **A known, pre-existing double-start race is NOT newly introduced
   nor newly fixed**: two genuinely concurrent `start_run_execution`
   calls for the same `run_id` could both pass the `is_terminal()`
   check and both spawn a worker thread before either one's `execute_run`
   call transitions the run past `PENDING`. This exact race already
   existed in the synchronous world (concurrent HTTP requests hitting
   the same not-yet-terminal run) — M11 doesn't make it more or less
   likely, just easier to describe. Left as a disclosed, pre-existing
   boundary rather than solved incidentally as part of this milestone.
4. **Auth has no key rotation, expiry, or per-caller identity** — one
   shared secret, valid or not. A caller's identity for `decided_by`/
   `created_by` fields throughout this API is still self-reported in
   the request body, not derived from the auth credential — consistent
   with "lightweight," not a real identity system.
5. **Mutation coverage (66% vs. the 75% gate)** remains explicitly
   deferred to M12, per the user's own standing instruction — untouched
   this milestone.

## Human Sign-off

milestone: M11
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |
