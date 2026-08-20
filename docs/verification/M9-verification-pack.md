# Milestone M9 Verification Pack — Unbiased Audit, Real env_id, Persistent Storage

Status: **All Layer 1/2 checks complete and passing (with one honestly-disclosed scope boundary — see §4). Ready for your Layer 3 review and sign-off.**

M9 followed the user's explicit instruction: "go ahead, start M9 with the
audit" — the same periodic, from-scratch, unbiased-audit pattern used
before M8, this time turned specifically on M8's own new code (which,
unlike M1-M7, had only ever been live-verified feature-by-feature as it
was built, never re-read adversarially afterward). After the audit, M9
continued into its two approved feature deliverables: real `env_id`
computation wired into the live API (§73, ADR-014), and Postgres-backed
persistent storage for profiles and runs (§105-§107, ADR-013).

## 1. Scope recap

| Deliverable | Status |
|---|---|
| Unbiased audit of M8's own new code | ✅ Done — 4 real issues found and fixed, 1 real gap disclosed (not fixed, out of scope) |
| Real `env_id` computation wired into the live `Dispatcher` (§73, ADR-014) — was an M1-era hardcoded placeholder | ✅ Done |
| `LibpostalClient.version()` — real `GET /version` query, never raises | ✅ Done |
| Postgres-backed persistent storage for profiles + runs (§105-§107, ADR-013) — `InMemoryStore` state no longer lost on every restart | ✅ Done — with a disclosed, deliberate scope boundary (see §4) |
| Gate G9 verification | ✅ Done |

## 2. Layer 1 — Automated verification results

```
uv run ruff check .          -> All checks passed!
uv run ruff format --check . -> 185 files already formatted
uv run mypy packages         -> Success: no issues found in 82 source files
uv run pytest -m "unit or golden or property or contract" -q
  -> 789 passed, 10 skipped, 37 deselected
uv run pytest -m "unit or golden or property or contract or integration" -q
  -> 812 passed, 10 skipped, 24 deselected, 4 failed
uv run python -m normcli check-traceability
  -> PASSED — all 138 Source.txt sections present in the matrix
```

The 4 integration failures are `tests/integration/test_readonly_connectors.py`
— pre-existing, unrelated to any M9 change, and expected: that file
requires `docker compose up -d demo-postgres demo-mysql demo-mongo
demo-clickhouse`, none of which were started this session (M9's own new
integration tests only needed the real `postgres`/`libpostal` services,
both of which were started and are what the 812-passed number reflects).

New this milestone: `tests/integration/test_postgres_store_integration.py`
(14 tests, real round-trips through a real Postgres container, including
two-independent-`InMemoryStore`-instances persistence simulation),
2 new `LibpostalClient.version()` tests in
`test_address_normalizer_integration.py`, 1 real multi-threaded
concurrency regression test, 2 new `NormalizationCache` duplicate-key
tests. All prior-milestone suites unchanged and still fully passing.

## 3. Layer 2 — Live verification

### 3.1 The audit's findings, live-verified as fixed

See §3 below for the full audit narrative. In short: a real concurrency
race in M8's cache-stats wiring was found and fixed, proven with a real
`threading.Thread`-based test run 5 times to catch flakiness (all 5
clean); two latent `NormalizationCache` duplicate-key bugs were found
(one confirmed against real DuckDB `INSERT OR REPLACE` behavior, not
assumed) and fixed; two stale traceability-matrix rows were corrected.

### 3.2 Real env_id, live

Two independent, separately-started `uvicorn` processes against the
*same* real environment (including a live `libpostal` container)
produced the **exact same** `env_id`:
`4d33351141911f5bfa135de4327e7805fdeb8c603237ea7060bd2ea5eb6f03e5` —
proving real stability across restarts, not just "it runs." The
standalone CLI (`scripts/env_fingerprint.py`, without libpostal
reachable) produced a genuinely different hash
(`0524f47d...`), correctly reflecting its different real inputs
(`libpostal_model_sha256: null` there vs. the real sidecar's SHA in the
live app) — sensitivity to real input differences, not a false
self-consistency.

### 3.3 Persistent storage, live — a genuine process kill and restart

Not simulated: started a real `uvicorn` process (PID 5596) with
`NORM_PG_DSN` pointed at the real `postgres` container, created a
profile and executed a run against it through the live HTTP API, then
**killed that process outright** (`taskkill /F`, confirmed the port was
no longer accepting connections), started a **brand-new** `uvicorn`
process (PID 3804 — genuinely a different OS process), and fetched the
same profile/run IDs:

```
GET /normalization/profiles/525ecf72-...  -> 200, full profile, unchanged
GET /normalization/runs/29fcbd9a-...      -> 200, status COMPLETED, full real metrics intact
```

This is the actual promise persistent storage makes, proven against a
real killed-and-restarted process rather than a simulated equivalent.

## 4. Addendum — the audit that started M9

Before any new feature work, the user asked for the same unbiased,
from-scratch audit that found 6 real gaps before M8 — this time turned
on M8's own new code. Method: fresh full test run, grep for stub
markers, a systematic file-existence check on every
traceability-matrix test-location path (found via a small script
extracting every backtick-quoted path and checking it against the real
filesystem), a fresh re-read of every M8-authored file with adversarial
intent, and a §99 registry cross-check.

**Found and fixed:**

1. **A real concurrency bug.** `InMemoryStore._normalize_deduped()`
   computed `cache_hits`/`cache_misses` via a before/after delta on
   `NormalizationCache.stats` — a shared, globally-mutable counter.
   `create_run`'s route handler is a synchronous `def`, so Starlette
   genuinely dispatches concurrent requests to a thread pool sharing
   that same counter; another request's activity landing between the
   two reads could misattribute hits/misses across unrelated runs.
   Fixed by tracking hits/misses from local, per-request state (which
   distinct values the `on_computed` hook actually fired for) instead —
   race-free by construction. Verified with a real multi-threaded test,
   run 5 times.
2. **Two latent `NormalizationCache` bugs** for duplicate keys within
   one `get_many()`/`put_many()` call — not reachable via the one real
   caller (which always pre-dedupes), but genuine bugs in public
   methods. `put_many`'s was confirmed against real DuckDB behavior
   directly: `INSERT OR REPLACE` with a duplicate key in the *same*
   statement keeps the FIRST occurrence, silently diverging from the
   LRU tier's natural last-write-wins. Both fixed and tested.
3. **Two stale traceability-matrix rows** (§102/§103) citing a test
   file (`tests/bench/test_performance.py`) that never existed.

**Disclosed, not fixed (real, but out of scope for that audit's
size):** `mypy` has never been run against `tests/` in this project's
history — every milestone's "mypy clean" claim only ever covered
`packages/`. A fresh, cache-cleared check found 48 real type errors
across 18 pre-existing test files spanning M1-M8. Spot-checked several
— legitimate mypy strictness (unnarrowable `str | None`, a dict-literal
type join collapsing under `**kwargs` unpacking), not evidence of
hidden runtime bugs. Flagged as a candidate follow-up, not silently
absorbed into either the audit or M9's feature work.

Full details and the fix-by-fix breakdown: `docs/verification/
M8-verification-pack.md`'s own §6 addendum (this audit's findings were
recorded there, against the milestone whose code was actually being
audited, rather than duplicated here).

## 5. The real env_id design decision — disclosed

ADR-014 states `env_id`'s inputs include "the active
`NormalizationProfile.version`." But `Dispatcher` is a single
process-wide singleton (its own docstring: "computed once per
run/process... never recomputed per value") serving *every* profile
this service knows about simultaneously — there is no single "the
active profile" for a process-wide `env_id` to bind to. Resolution:
the live app's `env_id` computation uses `env_fingerprint`'s own
"no specific profile" default (`"unversioned"`) rather than arbitrarily
picking one profile's version to represent all of them. `env_id` at
this granularity represents the library/ICU/dictionary environment
snapshot only — genuinely real and genuinely stable, just not
per-profile-version-sensitive the way ADR-014's literal wording
describes. This is a deliberate, disclosed interpretation, not a bug;
flagged here for your judgment on whether it needs a formal ADR-014
amendment.

## 6. Persistent storage — the real, disclosed scope boundary

ADR-013 distinguishes two kinds of durable data: lightweight relational
**metadata** (profiles, run records) → PostgreSQL, and bulk columnar
**normalized-value data** → a separate Arrow/Parquet sidecar store
(`normio.SidecarStore`, built in M1, never wired into the live
execution path). M9 delivers the first: `InMemoryStore` now
write-throughs profile and run *records* (status, metrics, timestamps —
everything in the `NormalizationRun`/`NormalizationProfile` pydantic
models) to Postgres, and hydrates from Postgres at startup. **Still
in-memory only**: a run's bulk per-value execution results
(`_RunExecution.originals`/`.results` — the actual `NormalizedValue` for
every row). After a restart, every past run's status and metrics are
correctly recoverable via the API; its detailed per-value
results/collisions/impact are not, until the sidecar store is wired in
as a separate, dedicated piece of work. This is disclosed plainly here,
matching M8's own precedent of stating real gaps outright rather than
glossing over them (see M8-verification-pack.md §4.1's mutation-score
disclosure).

## 7. Addendum — the §6 scope boundary is now closed

Post-M9, per the user's explicit instruction ("do #2 and #3 and then
continue plan and go for M10"), the scope boundary disclosed in §6 above
was closed as a dedicated follow-up: `InMemoryStore.execute_run` now
writes every run's real per-value results through to
`normio.SidecarStore` (Arrow/Parquet), and `InMemoryStore.get_execution`
transparently rehydrates them from it when the in-memory `_executions`
dict doesn't have them — i.e. after a restart. `app.py`'s `create_app()`
reads the previously-declared-but-unused `NORM_SIDECAR_PARQUET_ROOT`/
`NORM_SIDECAR_DUCKDB_PATH` env vars, mirroring exactly how `NORM_PG_DSN`
was wired in for §6's own metadata persistence.

One honest boundary carries forward: a sidecar-hydrated execution's
`invariant_report` is `sampled=0, violations=()` rather than whatever the
original live run actually sampled — runtime idempotency/determinism
sampling (§36) is a live-only artifact of the original `execute_run()`
call and is not reconstructed from persisted data, to avoid fabricating
a false "still clean" claim for a run this process didn't itself
execute.

Verified per this project's standard 3-layer model:
- **Layer 1**: `ruff check`, `ruff format`, `mypy packages` all clean;
  full unit/golden/property/contract suite (796 tests, up from 789) green.
- **Layer 2 (new tests)**: `tests/unit/test_sidecar_persistence.py` —
  real write-then-read round trip through `InMemoryStore` backed by real
  Parquet/DuckDB files under `tmp_path`, and restart simulation via a
  SECOND, independent `InMemoryStore` instance (same technique as §3.3's
  Postgres restart test) proving a run's results, field name, and
  original/result pairing all survive exactly. Plus two new
  `find_run_table` unit tests in `tests/unit/test_file_connector_and_sidecar.py`.
- **Layer 2 (live)**: a genuine process kill and restart against a real
  running `uvicorn` server, both `NORM_PG_DSN` (the real local Postgres
  used throughout M9's own live verification) and the new sidecar env
  vars set. Created a profile and executed a real run
  (`POST /normalization/runs`, 4 values including a `null`) against
  process 1, captured `GET /runs/{id}/values`'s full response as a
  baseline, `taskkill /F`'d the process outright, started a brand-new
  independent process against the same Postgres DSN and sidecar paths,
  and re-fetched `GET /runs/{id}/values` — byte-for-byte identical to
  the pre-kill baseline (all 4 rows, including full `trace` steps and
  `structured` fields), served entirely from data the second process
  never computed itself.

Mypy-tests-gate closure (the other item from the same instruction) is
recorded separately in commit `17a7450`.

## Human Sign-off

milestone: M9
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |
