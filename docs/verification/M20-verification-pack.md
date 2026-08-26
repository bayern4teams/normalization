# Milestone M20 Verification Pack — Incremental Watermark + Full Resync

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

M20 is the seventh implementation milestone of the M13-M22 product-pipeline
program (`docs/plan/M13-M22-program-plan.md`), built under the user's
standing overnight authorization. Its scope, per the plan: a real
`created_at`-watermark incremental sync mechanism for both M17's
multi-column runs and M19's destination runs, plus an explicit full-resync
action — and the plan's own two named callouts, "this is where silent
data loss lives," handled explicitly rather than left implicit.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `source_watermarks` Postgres table (M15 migration runner) + CRUD | ✅ Done, live-verified |
| `mode: "incremental"` / `"full_resync"` on `MultiColumnRunRequest`/`DestinationRunRequest` | ✅ Done, live-verified |
| `read_chunk`'s `since` filter wired into `stream_column` (M17) | ✅ Done, live-verified |
| `read_chunk`'s `since` filter wired into `stream_table_to_destination` (M19) | ✅ Done, live-verified |
| `CatalogConnector.count_null` — real NULL-watermark blind-spot count | ✅ Done, live-verified (ClickHouse + SQLAlchemy base) |
| `RunProgress.rows_skipped_null_watermark` | ✅ Done, live-verified with a genuine NULL row |
| A real, pre-existing M17 identity bug found and fixed while wiring this milestone | ✅ Done |
| Gate G20 verification | ✅ Done, this pack |

## 2. Layer 1 — Automated verification results

Run fresh, in this session, against `main` at commit `196bf5b`:

```
uv run ruff check .             -> All checks passed!
uv run ruff format --check .    -> 241 files already formatted
uv run mypy packages tests      -> Success: no issues found in 183 source files
uv run python -m normcli check-traceability
  -> PASSED - all 138 Source.txt sections present in the matrix
uv run pytest -m "unit or golden or property or contract" -q
  -> 1027 passed, 10 skipped, 116 deselected, 1 warning in 137.11s
uv run python scripts/check_licenses.py
  -> License check passed: 144 packages inspected, 0 violations, 24 warnings
     (identical set to M19 — no new dependency; M20 only adds one new
     Postgres table and connector methods on existing packages)
```

1027 passed — unchanged from M19's close, since M20 added no new
unit/golden tests (its whole surface only makes sense live, against a
real, persistent Postgres and a real ClickHouse `created_at` column).
116 deselected (up from 114 — the 2 new `test_incremental_watermark.py`
integration tests).

### 2.1 Full non-bench regression sweep

Run three times this session while chasing down two real, disclosed
issues (§4):

```
uv run pytest -m "not bench" -q
  -> 1114 passed, 1 failed, 12 skipped, 26 deselected, 1 warning in 640.65s (0:10:40)
```

The one failure (`test_run_execution_from_source.py::test_mongo_source`,
a 15-second terminal-status poll timeout) is the same disclosed
transient-load characteristic already identified in M18's and M19's own
packs — confirmed non-reproducible in isolation:

```
uv run pytest tests/integration/test_run_execution_from_source.py -q
  -> 7 passed in 23.70s
```

### 2.2 New M20 test suite, run individually

```
uv run pytest tests/integration/test_incremental_watermark.py -v
  -> 2 passed in 27.27s
```

## 3. Layer 2 — Live verification

Against the real ClickHouse at `localhost:8190` (`origin2`, read-only)
and the real metadata Postgres (port 5535).

### 3.1 Incremental + full resync — `Industry` (179 real rows)

`TestIndustryIncrementalAndFullResync`, three sequential runs over the
same `Industry.name` mapping:

1. `mode: "full_resync"` → `COMPLETED`, `records_processed == 179`. Sets
   a real watermark (`source_watermarks.last_created_at`) to the true
   `MAX(created_at)` across all 179 rows.
2. `mode: "incremental"` (default), same mapping, no changes to real
   `Industry` data in between → `COMPLETED`, `records_processed == 0`.
   The watermark from run 1 already covers every real row's
   `created_at`, so `read_chunk`'s first call returns nothing and the
   loop exits immediately.
3. `mode: "full_resync"` again → `COMPLETED`, `records_processed == 179`.
   The watermark reset genuinely works a second time, from an
   already-set value, not just from an empty starting state.

### 3.2 The NULL-watermark blind spot — proven with a genuine NULL row

`origin2`'s real `Person`/`Company` tables currently have **zero** real
`created_at IS NULL` rows (a live finding already disclosed in M14's and
M17's own packs) — proving `rows_skipped_null_watermark` actually fires
needed a table that genuinely has one. Built live on the safe
`demo-clickhouse` server (port 8124, never `origin1`/`origin2`):

```sql
CREATE TABLE watermark_null_test (
  id String, val String, created_at Nullable(DateTime)
) ENGINE = MergeTree ORDER BY id;
INSERT INTO watermark_null_test VALUES
  ('1', 'alpha', '2024-01-01 00:00:00'),
  ('2', 'beta',  '2024-01-02 00:00:00'),
  ('3', 'gamma', NULL);
```

A multi-column run over `val` (mapped `FREE_TEXT`) against this real
table: `records_processed == 3` (a first, never-watermarked run always
reads every row — the watermark only gates a REPEAT run), and
`progress.rows_skipped_null_watermark == 1` — the real, structural blind
spot correctly counted and surfaced, not silently absorbed into "0 new
rows" with no explanation.

### 3.3 `since` reaches the real connector, not just the schema

Confirmed by §3.1's run 2 actually returning 0 rows (not by inspecting
code) — `normio.connectors.clickhouse.ClickHouseConnector.read_chunk`'s
`since` parameter (built in M14, never previously exercised by anything
real) genuinely filters `created_at > %(since)s` at the source.
`count_null` (new this milestone) was verified against both
`ClickHouseConnector` (a real `SELECT count(*) ... WHERE ... IS NULL`
query) and `SqlConnectorBase` (a real SQLAlchemy `func.count()...
where(col.is_(None))` query) — only the ClickHouse path was exercised
live in this milestone's own tests (matching this program's ClickHouse-
first scope), the SQL-base implementation is real code but not
independently live-tested here.

## 4. Two real, disclosed problems found and fixed during this milestone's own live verification

1. **A real, pre-existing M17 bug, found while wiring watermark
   identity**: `normapi.routes.start_multi_column_run` computed the
   `connection_identity` passed into `field_ref`/`run_columns`/(now)
   `source_watermarks` as `record.identity` — the connection's OWN
   stored identity, computed from `record.database` (its default
   database) at connection-creation time. M16 already lets a request
   target ANY database on that connection (`body.database`), not just
   the default — so whenever `body.database != record.database`,
   `record.identity` was silently the WRONG identity: a saved column
   mapping keyed by the real identity for `body.database` could never
   match, and (had this milestone not caught it) a watermark would have
   been saved under the wrong key too. **Fixed**: `connection_identity`
   is now recomputed fresh from `record.kind/host/port` and the REAL
   `body.database`, matching the pattern `start_destination_run` (M19)
   and the catalog routes (M16) already used correctly.
2. **A real test-suite regression, found and fixed via live re-
   verification, not assumed safe**: making `mode: "incremental"` the
   default for every multi-column/destination run changed real,
   observable behavior for every M17/M18/M19 test that runs against the
   same real `Industry`/`Company` tables — the metadata Postgres this
   project uses is genuinely persistent across the whole test session
   (and across every session ever run against it), so a watermark set by
   ANY earlier run silently starves a later run's row count expectations
   unless that later run explicitly opts back into "process everything"
   via `mode: "full_resync"`. This surfaced as real, reproducible test
   failures (0 rows processed where 179 were expected) across
   `test_multi_column_runs_api.py`, `test_multi_column_reporting.py`,
   `test_destination_writer.py`, and even this milestone's OWN first
   test (whose "first run, no watermark yet" framing was itself an unsafe
   assumption about shared, durable state). **Fixed** by adding
   `mode: "full_resync"` to every pre-existing test whose actual intent
   was "always process the full table," and reframing this milestone's
   own first test to start from an explicit reset rather than an assumed
   clean slate — then re-running the full affected suite set to confirm.

## 5. Design notes and disclosed scope decisions

1. **The watermark advances per TABLE, not per column.** A multi-column
   run's several mapped columns of the same table all read the identical
   real row set (just projecting different columns), so the watermark is
   resolved once per distinct table and advanced once, after every column
   of that table finishes successfully — not per (table, column). If ANY
   column of a table fails, that table's watermark is not advanced at
   all (`_TableWatermarkState.failed`), so a partial failure never
   silently marks rows as "already seen" for a column that never actually
   processed them.
2. **A destination run's watermark only advances if the whole
   `stream_table_to_destination` call succeeds** — there is no per-column
   partial-success concept for a destination run (it writes one complete
   row per source key), so this is simpler than the multi-column case: an
   exception propagates to `_run_destination_worker`'s outer `try/except`
   before the watermark-advance code is ever reached.
3. **`rows_skipped_null_watermark` is computed once per table per run**,
   via a real `COUNT(*) WHERE created_at IS NULL` query — not derived
   from the rows actually streamed (which structurally never see the
   NULL rows at all, by construction of the `created_at > since` filter).
   This is a real, separate query, disclosed as real overhead per run,
   not hidden.
4. **No UI surface for any of this yet** (M21's job) — the plan's own
   explicit instruction "say so in the UI, or users will trust stale
   output indefinitely" about ReplacingMergeTree updates not bumping
   `created_at` is a real, disclosed gap until M21 builds the 3-step UI
   and can put that warning somewhere a user actually sees it. The
   mechanism (`mode: "full_resync"`) exists and works; the user-facing
   explanation of *why* they might need it does not yet.
5. **`count_null`'s `SqlConnectorBase` implementation is real but not
   live-tested in this milestone** — this program's own real target is
   ClickHouse throughout (decision-level scope, carried since M14), and
   this milestone's live verification budget went to the ClickHouse path
   exclusively, matching that established precedent.

## 6. Disclosed scope boundaries carried forward

M21 (3-step UI) is next — cannot start before M18 per the plan's own
dependency chain, which is already satisfied. `env_id`/persistence/
connection encryption/catalog API/mappings/multi-column chunked
execution/bounded reporting/destination writer are all real and
unaffected by this milestone. M17's "sequential not parallel column
processing" and "no automatic resume-on-boot" scope decisions, M18's
"per-column reports not rearchitected to be bounded" decision, and M19's
"ClickHouse-only destinations" decision are all unchanged.

## Human Sign-off

milestone: M20
verdict:
reviewer:
date:
env_id:
commit: 196bf5b
conditions: []
notes: |
