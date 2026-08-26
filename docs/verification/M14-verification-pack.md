# Milestone M14 Verification Pack — Connector Catalog + Real Streaming

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

M14 is the first implementation milestone of the M13-M22 product-pipeline
program (`docs/plan/M13-M22-program-plan.md`), built under the user's
standing overnight authorization (see project memory, "Standing
authorization: unattended overnight execution of M14-M22"). Scope: pure
`normio` library work — catalog introspection and keyset-paginated
streaming reads — with no API/UI surface, so every claim below is
verifiable directly against real running databases without going through
`normapi` at all.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `normio/catalog.py` — `ColumnSpec`, `TableSpec` value objects | ✅ Done (`023b11d`) |
| `normio/capabilities.py` — `CatalogConnector`, `StreamingSourceConnector` protocols, kept separate from `SourceConnector` | ✅ Done (`023b11d`) |
| `ClickHouseConnector`: `list_databases`, public `list_columns`, `table_spec`, `sample_rows`, `sample_values`, `read_chunk` | ✅ Done (`023b11d`) |
| `ClickHouseConnector.read_table` rewritten onto `query_arrow_stream` (was `query_arrow`, which materializes the whole result first) | ✅ Done (`023b11d`) |
| Real primary-key-derived `source_row_key` (was positional `f"{table}:{offset+i}"`) for both `read_table` and `read_chunk`, ClickHouse and SQL connectors | ✅ Done (`023b11d`) |
| `SqlConnectorBase` (Postgres/MySQL): same catalog + `read_chunk` additions via SQLAlchemy `inspect` | ✅ Done (`023b11d`) |
| `normapi/store.py:142` crash-on-contact bug (`int(source_row_key)` sort) | ✅ Fixed — real `row_ordinal` int64 column added to the sidecar schema | 
| Gate G14 verification | ✅ Done, this pack |

## 2. Layer 1 — Automated verification results

Run fresh, in this session, against `main` at commit `023b11d`:

```
uv run ruff check .             -> All checks passed!
uv run ruff format --check .    -> all files formatted (after 2 auto-reformats during development)
uv run mypy packages            -> Success: no issues found in 86 source files
uv run mypy tests               -> Success: no issues found in 67 source files
uv run python -m normcli check-traceability
  -> PASSED - all 138 Source.txt sections present in the matrix
uv run pytest -m "unit or golden or property or contract" -q
  -> 967 passed, 12 skipped, 85 deselected, 1 warning in 316.33s
uv run python scripts/check_licenses.py
  -> License check passed: 140 packages inspected, 0 violations, 22 warnings
     (same pre-existing warning set as M12's pack; no new dependency added)
```

967 passed (up from M12's 963 baseline — the 4 new `test_catalog.py` unit
tests). 85 deselected (up from 61 — the 24 new parametrized integration
tests in `test_catalog_and_streaming.py`, `3 connectors × 8 test methods`,
correctly excluded from the non-integration marker set). The one warning
is the same pre-existing `httpx`/starlette deprecation notice M9-M12's
packs already disclose.

### 2.1 Integration suite — run live against real containers, not skipped

Unlike M9-M12 (which ran with `-m integration` deselected because the
demo containers weren't started), this milestone's own subject matter
*is* the connectors, so the full integration suite was run live:

```
docker compose up -d postgres demo-postgres demo-mysql demo-mongo demo-clickhouse
  -> all 5 containers healthy within ~20s

uv run pytest tests/integration -q -k "not postgres_store"
  -> 39 passed, 5 skipped, 17 deselected, 1 warning in 81.47s

uv run pytest tests/integration/test_postgres_store_integration.py -q
  -> 17 passed in 10.96s
```

`test_readonly_connectors.py` (the pre-existing read/write-enforcement
suite) passes unmodified — proof this milestone's changes didn't alter
existing read/write behavior, only added new capabilities.
`test_catalog_and_streaming.py` (new, 24 tests) is the M14-specific
coverage — see §3 below for what it actually proves.

## 3. Layer 2 — Live verification

### 3.1 Against the real target database (localhost:8190, origin1/origin2)

Every claim in `docs/verification/bench-baseline-m14.json` was captured by
running the real connector code against the real ClickHouse this whole
program exists to serve, not a demo container:

- **`list_databases()`** → `['default', 'origin1', 'origin2']`. This
  **differs from the program plan's own illustrative expectation**
  (`['origin1','origin2']`) — disclosed honestly rather than silently
  matched. `'default'` is a real ClickHouse database (`engine=Atomic`,
  confirmed live), currently empty in this deployment. `list_databases()`
  excludes only ClickHouse's three built-in system catalogs by name
  (`system`, `information_schema`, `INFORMATION_SCHEMA`); it deliberately
  does **not** special-case `'default'` out, since a real deployment could
  legitimately have user data in a database actually named `default`, and
  hardcoding that exclusion would silently hide it.
- **`table_spec("Experience")`** → `engine=ReplacingMergeTree`,
  `approx_rows=12,234,811`, `primary_key=('experienceID', 'companyID')` —
  matches the plan's expectation (columns match; the plan's example wrote
  them in the opposite order, which is not semantically significant for a
  set of key columns).
- **`table_spec("PersonContact")`** → `primary_key=('contactString',
  'personID')`, confirming (again, as in the original M13-M22 planning
  session) that `is_in_primary_key` correctly resolves the real key
  columns even though the table's `sorting_key` is the expression
  `personID, assumeNotNull(contactString)` — never parsed out of that
  expression string, read directly from `system.columns`.
- **Three sequential `read_chunk(Person, limit=1000)` calls**, keyset-paginated
  by `personID`: `1000, 1000, 1000` rows, **zero overlap between chunk
  boundaries** (proving no page re-fetches or gaps), `2999` distinct
  `personID`s across the three chunks. The `2999` (not naively-expected
  `3000`) is a **real, disclosed ClickHouse characteristic**, not a bug:
  `Person` currently has 3,797 `personID`s with un-merged duplicate rows
  pre-`ReplacingMergeTree`-merge (verified live via `SELECT personID,
  count() FROM Person GROUP BY personID HAVING count()>1` → 3,797 rows).
  Zero cross-chunk overlap is the correctness property `read_chunk` is
  actually responsible for; the duplicate landed within one chunk's raw
  fetch, which is exactly what an un-merged `ReplacingMergeTree` should
  do without `FINAL`. M19's destination writer already plans to reconcile
  this via `OPTIMIZE ... FINAL`.
- **`sample_values(Person, fullName, limit=5)`** → `0.139s`, proving
  `LIMIT` pushdown at the source (not a full-column fetch + client-side
  truncate) on a table with ~11.8M rows.
- **`read_table(Person, batch_size=50000)` streaming proof** — first batch
  (8,192 rows, ClickHouse's own network block size) arrived in `0.39s`;
  `303,104` rows read by `3.65s`. This is real evidence that
  `query_arrow_stream()` yields progressively rather than materializing
  the whole ~11.8M-row table before the first `RecordBatch` is available
  (the old `query_arrow()`-based implementation would have blocked on the
  full query completing first). Precise peak-RSS measurement via `psutil`
  was **not available** in this venv (`psutil` not installed) — disclosed
  honestly rather than fabricating a memory graph; the timing evidence is
  the substitute proof actually used.

Full captured data: `docs/verification/bench-baseline-m14.json`.

### 3.2 Against the demo containers (Postgres/MySQL/ClickHouse `customers` tables)

`test_catalog_and_streaming.py` parametrizes 8 test methods across all
three connector kinds (24 tests total), each against real containers
seeded by the pre-existing `tests/integration/fixtures/*-init/` scripts:

- `isinstance(connector, CatalogConnector)` and
  `isinstance(connector, StreamingSourceConnector)` — both `True` for all
  three connector classes (the `runtime_checkable` Protocols actually
  match the real implementations, not just type-check statically).
- `table_spec("customers").primary_key == ("id",)` on all three — the
  real declared primary key, for all three dialects.
- `read_chunk` keyset pagination with `limit=2` over the 3-row seeded
  table: page 1 returns 2 rows (`source_row_key` = the real `id` values
  `"1"`/`"2"`, not a positional index), page 2 returns the remaining 1 row
  with no overlap, page 3 (past the end) returns `None` — the caller's
  real stop condition.
- `read_chunk` and `table_spec` both reject an unknown column/table with
  `ValueError`, not a silent empty result or a raw driver exception.
- `read_table("customers")` now yields `source_row_key` values `{"1", "2",
  "3"}` — the real `id` column — where before this milestone it would
  have yielded `"customers:0"`, `"customers:1"`, `"customers:2"`.

## 4. Real gap found and fixed in this milestone's own scope: `store.py:142`

Disclosed in the M13-M22 program plan as a known, real, pre-existing risk
(top of its "Top 5 risks, ranked" list) rather than discovered fresh here,
but the fix itself happened in this milestone as planned:

`normapi/store.py`'s `_table_to_results` sorted a run's sidecar-hydrated
results via `rows.sort(key=lambda row: int(row["source_row_key"]))`. This
was safe only because the one caller that ever populated
`source_row_key` in production code (`_write_execution_to_sidecar`, the
pasted-values execution path) used a positional index string — connectors
were never actually wired into `execute_run()` before this program, so
the crash was latent, not live, going into M14. This milestone's own
connector changes (real, composite, non-numeric `source_row_key` values
like `"10000023481\x1flonnyr@gmail.com"`) would have turned that latent
risk into an immediate `ValueError` the moment M17 wires streamed
connector output into this same sidecar path.

Fixed now, ahead of that wiring, per the plan's explicit instruction to
land this fix "in this milestone, alongside the key change": a genuine
`row_ordinal` `int64` column was added to `_SIDECAR_SCHEMA`, populated
alongside (not instead of) `source_row_key`, and `_table_to_results` now
sorts by `row_ordinal` instead of parsing `source_row_key` as an int.
`source_row_key` itself is unchanged in shape or meaning — still a
string, still written on every row — only the sort key changed.

**Disclosed compatibility boundary:** this schema change is not
migration-compatible with sidecar Parquet parts written before commit
`023b11d` (a pre-existing run's sidecar data lacks the new `row_ordinal`
column and would raise `KeyError` on hydration). No migration is provided
in M14 — the plan explicitly schedules the Postgres/sidecar migration
runner for M15, not M14. This is a real, live risk only for **existing
production sidecar data**, which does not exist yet (nothing has been
deployed against real customer data at this stage of the program); local
dev/test sidecar directories created before this commit should be
cleared, not migrated.

## 5. Disclosed scope boundaries

1. **Mongo and file connectors were not touched.** The M13-M22 plan
   explicitly scopes M14's catalog/streaming work to ClickHouse, Postgres,
   MySQL — Mongo/file connectors remain `SourceConnector`-only (no
   `CatalogConnector`/`StreamingSourceConnector`), by design, not by
   oversight. A caller that capability-checks with `isinstance` before use
   (as the plan specifies) gets a clean `False`/501, never a crash.
2. **`since`/watermark filtering in `read_chunk` is implemented but not
   independently live-tested in this pack.** The parameter is exercised
   indirectly — every `read_chunk` call above passes `since=None`, the
   code path that skips the watermark clause entirely — but the
   `since is not None` branch (including its `ValueError` on a table
   without `created_at`) was not run against a real database in this
   session, only reasoned through against the code and the demo
   `customers` schema. Disclosed here rather than claimed as tested; real
   live verification of this branch is deferred to M20, which is also
   where a real caller first passes a real watermark value.
3. **`approx_rows` for Postgres/MySQL is genuinely best-effort.** Live
   verification against `demo-postgres` found `pg_class.reltuples = -1`
   (never analyzed) for the seeded `customers` table — `table_spec()`
   correctly returns `approx_rows=None` in that case rather than a
   misleading `-1` or a guessed value. MySQL's
   `information_schema.tables.table_rows` worked correctly (`3`) in the
   same live check.
4. **`TableSpec.engine` is always `None` for SQL connectors.** Postgres
   has no native "storage engine" concept and MySQL's is not consistently
   meaningful across dialects for this program's purposes; `engine` is
   populated only by `ClickHouseConnector.table_spec`, where it is real
   (`ReplacingMergeTree`, verified live). Documented as best-effort in
   `catalog.py`'s own docstring, not silently inconsistent.
5. **No API or UI surface.** Exactly as scoped — `normapi`/`ui` are
   untouched by this milestone. M16 is where these capabilities become
   reachable over HTTP.

## Human Sign-off

milestone: M14
verdict:
reviewer:
date:
env_id:
commit: 023b11d
conditions: []
notes: |
