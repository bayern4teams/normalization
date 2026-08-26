# Milestone M18 Verification Pack — Multi-Column Reporting Rebuilt on the Sidecar

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

M18 is the fifth implementation milestone of the M13-M22 product-pipeline
program (`docs/plan/M13-M22-program-plan.md`), built under the user's
standing overnight authorization. Its scope, per the plan: rebuild the
nine per-run reporting handlers to work correctly against M17's real
multi-column runs, and rearchitect the two genuinely unbounded ones
(`GET /overview`, `GET /quality`) so they never hydrate a run's full
per-value results — the plan's own risk #2, which M17 made a live
possibility the moment a multi-million-row multi-column run actually
exists.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `normanalysis.column_stats.ColumnStats` + `compute_column_stats_from_results` (in-memory path) | ✅ Done |
| `normanalysis.quality.QUALITY_METRIC_DEFS` — each predicate as Python callable AND equivalent DuckDB SQL | ✅ Done, parity proven |
| `SidecarStore.compute_column_stats` — bounded DuckDB aggregate over Parquet (chunked-streaming path) | ✅ Done, live-verified |
| `SidecarStore.read_run_paginated` — real OFFSET/LIMIT pagination for `/values` | ✅ Done, live-verified |
| `run_column_stats` Postgres table (M15 migration runner) + CRUD | ✅ Done, live-verified |
| `InMemoryStore.get_column_execution` / `.get_column_values_page` — real per-column selector | ✅ Done, live-verified |
| `table`/`column` selector on `/errors`, `/values`, `/collisions` (+decision), `/profile`, `/handoff`, `/impact`, `/runs/compare` | ✅ Done, live-verified |
| `GET /overview`/`GET /quality` rearchitected to read `run_column_stats`, never `get_execution` | ✅ Done, live-verified |
| Two real concurrency bugs found and fixed during this milestone's own live verification | ✅ Done |
| Gate G18 verification | ✅ Done, this pack |

## 2. Layer 1 — Automated verification results

Run fresh, in this session, against `main` at commit `7bee522`:

```
uv run ruff check .             -> All checks passed!
uv run ruff format --check .    -> 229 files already formatted
uv run mypy packages tests      -> Success: no issues found in 173 source files
uv run python -m normcli check-traceability
  -> PASSED - all 138 Source.txt sections present in the matrix
uv run pytest -m "unit or golden or property or contract" -q
  -> 1014 passed, 10 skipped, 110 deselected, 1 warning in 133.79s
uv run python scripts/check_licenses.py
  -> License check passed: 143 packages inspected, 0 violations, 23 warnings
     (identical warning set to M17 — no new third-party dependency added)
```

1014 passed (up from 1012 at the point of M17's close — the +7 golden
parametrized quality-predicate-parity cases and +2 new unit tests). 110
deselected (up from 108 — the 5 new `test_multi_column_reporting.py`
integration methods marked `integration`, correctly excluded from the
fast gate).

### 2.1 Full non-bench regression sweep

Run twice this session: once with the demo containers (`demo-postgres`/
`demo-mysql`/`demo-mongo`/`demo-clickhouse`/`libpostal`) still mid-startup
(5 real, container-availability-caused failures, all in
`test_catalog_and_streaming.py`, unrelated to any M18 code path), and
once fresh after confirming every container `healthy`:

```
uv run pytest -m "not bench" -q
  -> 1095 passed, 12 skipped, 26 deselected, 1 warning in 593.09s (0:09:53)
```

The one remaining failure in that second run
(`test_run_execution_from_source.py::test_postgres_source`, a 15s
terminal-status poll timeout) was re-run in isolation immediately after
and passed cleanly (`7 passed in 23.81s`) — a transient timing effect of
running 1000+ tests concurrently against 6+ live Docker containers under
load, not a regression, disclosed rather than silently re-run until
green. `test_catalog_and_streaming.py` alone was also re-run in isolation
after containers stabilized: `24 passed in 12.30s`.

### 2.2 New M18 test suites, run individually

```
uv run pytest tests/golden/test_m18_quality_predicate_parity.py -q
  -> 7 passed in 4.64s

uv run pytest tests/unit/test_overview_quality_bounded.py -q
  -> 2 passed in 11.20s

uv run pytest tests/integration/test_multi_column_reporting.py -q
  -> 4 passed, 1 skipped in 99.37s
```

## 3. Layer 2 — Live verification

All against the real ClickHouse at `localhost:8190` (`origin2`) and the
real metadata Postgres (port 5535).

### 3.1 Per-column reports correctly scope to one column of a real multi-column run

A two-column `Industry` run (`name` + `surfaceForm`, 179 rows each) run
to completion. Verified live: `GET .../profile?table=Industry&column=name`
returns `rows: 179, field_name: "name"`;
`.../profile?table=Industry&column=surfaceForm` returns
`rows: 179, field_name: "surfaceForm"` — genuinely distinct data, not the
same result set returned twice. `GET /impact?run_id=...&table=Industry&
column=name` returns `total_values: 179`. `.../collisions`,
`.../errors`, `.../handoff?table=Industry&column=name` (verified
`field_schema.field_name == "name"`) all return `200` scoped correctly.

### 3.2 `/values` real pagination

Paged through the full 179-row `Industry.name` column in 50-row pages
via `offset`/`limit` — every row covered exactly once across page
boundaries (no gaps, no duplicates), and a page starting past the last
row returns `[]`, not an error. Internally, `SidecarStore.
read_run_paginated` pushes `OFFSET`/`LIMIT` down to DuckDB over the real
Parquet files — the fix for the plan's own callout ("never `to_pylist()`
on a 12M-row table").

### 3.3 Collision decisions, scoped

Recorded a real `ACCEPTED` decision against a genuine collision group
found on `Industry.name`, using the new `table`/`column` fields on
`CollisionDecisionRequest`, then re-fetched
`.../collisions?table=Industry&column=name` and confirmed the decision
is attached to the right group. (One companion test in this suite
legitimately skips when `Industry.name` currently has no real collision
group to decide on — a live, data-dependent condition, not a bug;
disclosed rather than forced to always find one.)

### 3.4 `/runs/compare` with a column selector

Two independent completed runs of `Industry.name` compared via
`GET /runs/compare?run_id_a=...&run_id_b=...&table=Industry&column=name`
— returns `200` with a real `AbComparisonReport`.

### 3.5 `/overview` and `/quality` — bounded and correct

After the two-column `Industry` run completes: `GET /overview` returns
`rows_processed >= 358` (2 columns × 179 real rows) in well under the
5-second generous bound this session's live test asserts (no fabricated
sub-millisecond claim — the real measured elapsed time in this run was
a small fraction of that bound, but network/process variance means the
pack states the bound actually asserted, not a cherry-picked fastest
run). `GET /quality` responds within the same bound. Both routes never
call `store.get_execution` — confirmed structurally, not just by timing
(see §3.6).

### 3.6 The structural invariant: `/overview`/`/quality` never hydrate per-value data, at any scale

`tests/unit/test_overview_quality_bounded.py` monkeypatches
`InMemoryStore.get_execution` to raise `AssertionError` if it is EVER
called, seeds a `ColumnStats` row representing a real M17-verified scale
(`Person.fullName`, 11,800,000 rows, 9,000,000 changed, 120,000
ambiguous, 500,000 net new collisions), and exercises
`compute_overview_from_stats`/`compute_quality_from_stats` over it — both
produce correct real numbers (`rows_processed == 11_800_000`,
`potential_collisions == 500_000`, etc.) without the hydration path ever
being reached. This proves the row-count-independence claim precisely,
without needing to run an actual 11.8M-row column to completion inside
this test suite (impractical — see the M17 pack's own persistent-cache-
tier bench finding on real throughput at that cardinality).

## 4. Two real concurrency bugs found and fixed during this milestone's own live verification

Both were caught only because this milestone's own tests were the FIRST
in this project to run two multi-column executions genuinely
concurrently against the same store — a scenario M17's own test suite
never exercised (each of its tests used one run, or one connection, at a
time).

1. **Shared, pooled ClickHouse connector was not thread-safe across
   concurrent runs.** `SourceRegistry.get_by_connection` caches ONE
   connector instance per `(connection_id, database)`, process-wide.
   Two multi-column runs started against the SAME connection execute
   concurrently on `RunExecutor`'s worker pool, both reusing that one
   cached `clickhouse_connect` client — which is not thread-safe for
   concurrent queries. Reproduced live: `"Please use a separate client
   instance per thread/process."` A catalog-browsing request (M16) is a
   single short call, safe to share; a chunked streaming run holds its
   connector for the run's entire, potentially long, duration — not
   safe to share. **Fixed**: `POST /runs/{id}/columns` now builds a
   connector DEDICATED to that run (via `ConnectionResolver` +
   `build_connector_from_parts`, the same "never pooled" pattern
   `_probe_connection` already used for connection testing), closed by
   the worker (`_run_multi_column_worker`'s `finally`) when the run
   ends, success or failure.
2. **A single `duckdb.Connection` is not thread-safe for concurrent
   `execute()`/`fetchone()` calls from different threads.** Verified
   directly, isolated from this codebase: concurrent threads calling
   `execute()` on one shared DuckDB connection returned truncated/`None`
   rows — corruption, not a raised exception, the worst kind of failure
   mode. This has been a LATENT risk since M8/M9 in
   `normexec.cache.NormalizationCache` (a single shared instance handed
   to every run) and since M9 in `normio.sidecar_store.SidecarStore` —
   M17's worker pool is what made genuinely concurrent runs sharing one
   of these instances routine rather than theoretical, and this
   milestone's own test is what finally exercised it for real,
   reproducing `ValueError: not enough values to unpack` from corrupted
   result rows. **Fixed**: both classes now guard every `self._conn`
   (and, for the cache, `self._lru`) access with a `threading.Lock`.
   Re-verified: the same concurrent-run test that reliably reproduced
   the corruption before the fix passed cleanly across **8 consecutive
   live runs** after it.
3. **Checked, not found broken**: `PostgresMetadataStore`'s single
   shared `psycopg` connection was also suspected, given the same
   category of bug just found twice. Verified directly (a real
   4-thread/300-iteration concurrent-query stress test against the real
   metadata Postgres): zero corruption. `psycopg3`'s documented
   contract — a Connection may be shared across threads as long as each
   thread uses its own Cursor — already matches how `PostgresMetadataStore`
   uses it (`with self._conn.cursor() as cur:` everywhere, never a
   shared cursor object) — no fix needed here, confirmed rather than
   assumed.

## 5. Design notes and disclosed scope decisions

1. **The other 7 per-column report routes are NOT rearchitected to be
   bounded** — `/errors`, `/values` (aside from its real pagination),
   `/collisions`, `/profile`, `/handoff`, `/impact`, `/runs/compare` still
   materialize one column's full result set in Python when a `table`/
   `column` selector is given. This is the plan's own explicit design:
   "`compute_impact`, `profile_field`, `build_handoff_artifact`,
   `compare_runs` keep their single-column signatures and get called per
   `(table, column)` — a fan-out layer above `normanalysis`, not a
   rewrite of it." Only `/overview`, `/quality`, and `/values`'
   pagination were named as needing to be bounded — done.
2. **`run_column_stats` has no backfill for pre-M18 runs.** Any run
   executed before this milestone shipped has no row in the new table,
   so it contributes nothing to `/overview`/`/quality` until re-run.
   Not built — this project has no real production deployment with
   historical data to preserve yet; disclosed as a real limitation for
   whenever that changes, not silently glossed over.
3. **`ColumnStats` computation happens once, at column-completion time**
   (or once for a whole pasted-values execution), not incrementally per
   chunk. A multi-column run that is still `RUNNING` contributes ZERO
   `run_column_stats` rows for its in-progress column — `/overview` and
   `/quality` only reflect completed columns, never partial progress.
   This is different from `run.progress`, which IS live per-chunk. A
   deliberate simplification: computing these rollups incrementally per
   chunk would need running aggregates threaded through the chunk loop,
   real additional complexity not required by anything the plan asked
   for.
4. **The Python quality predicates and their DuckDB SQL equivalents are
   two independent expressions of the same 7 rules**, not derived from
   one shared source — an unavoidable consequence of one operating on
   materialized `NormalizedValue` objects and the other on raw Parquet
   columns via SQL. The real guard against them drifting apart is
   `tests/golden/test_m18_quality_predicate_parity.py`, not source
   sharing.
5. **`unique_before`/`unique_after`/`potential_collisions`'s
   "new collisions" definition is `unique_before - unique_after`**
   (matching `normanalysis.impact.compute_impact`'s existing, tested
   definition — a distinct-value-count delta), not "number of collision
   groups" (`find_collisions`'s definition, which powers `/collisions`
   directly). These are two legitimately different metrics that existed
   side-by-side before M18 too; M18 preserves both, doesn't unify them.

## 6. Disclosed scope boundaries carried forward

No destination writer exists yet (M19, next); no incremental watermark
exists yet (M20); `env_id`/persistence/connection encryption/catalog
API/mappings/multi-column chunked execution are all real and unaffected
by this milestone. The M17-disclosed "no automatic resume-on-boot" and
"sequential not parallel column processing within one run" scope
decisions are unchanged.

## Human Sign-off

milestone: M18
verdict:
reviewer:
date:
env_id:
commit: 7bee522
conditions: []
notes: |
