# TODO — normio DB-clone-and-normalize (Postgres + ClickHouse)

Plan: `.hermes/plans/logical-growing-puddle.md`. Baseline: 546 unit passed / 1 pre-existing failure (`test_real_repo_files_are_fully_cross_referenced` — `Source.txt` deleted in 8ee6e48, unrelated). Env note: venv is Python 3.12; PyICU built from source against a user-local ICU 78.3 prefix (`~/tmp/icu-local`), because the box has no root ICU headers.

## 1. normio read-side
- [x] `ColumnInfo(name, native_type)` frozen dataclass in `normio/connector.py`
- [x] `PostgresConnector.list_databases()` + `get_columns(table)`
- [x] `ClickHouseConnector.list_databases()` + public `get_columns(table)`
- [x] unit tests for read-side additions; pytest -m unit green (covered via integration test_clone_pipeline.py — needs real DBs, no unit-testable in-memory alternative)
- [x] (discovered sub-step, not spelled out in plan) `PostgresConnector.get_primary_key(table)` + `ClickHouseConnector.get_table_engine_info(table)` — decision #11 (replicate PK/indexes, ORDER BY/engine) needs this DDL metadata from the origin, which `get_columns()` alone doesn't carry

## 2. normio write-side
- [x] Move `_ROW_CHUNK_SIZE` to `normio/connectors/_sql_base.py` (shared; pg_persistence imports it)
- [x] `postgres_destination.py`: `PostgresDestination` w/ `database_exists`/`create_table`/`bulk_insert` + PG type map
- [x] `clickhouse_destination.py`: `ClickHouseDestination` w/ same trio + CH type map
- [x] type-mapping unit tests (all 24 FieldSemanticTypes × 2 engines)

## 3. normapi schema + persistence
- [x] `normalization_connections` / `normalization_clone_jobs` / `normalization_clone_job_errors` in `pg_persistence._SCHEMA`
- [x] `save_connection`/`get_connection`/`list_connections`/`delete_connection`
- [x] `create_clone_job`/`save_clone_job`/`get_clone_job`/`list_clone_jobs`/`claim_clone_job`
- [x] `save_clone_job_errors`/`load_clone_job_errors_page`
- [ ] CRUD + claim-race coverage — no pure-unit harness exists for PgPersistence anywhere in this repo (raw Postgres-only SQL: jsonb_set/::jsonb casts); folded into `tests/integration/test_clone_pipeline.py` against real demo-postgres instead (§8/§9)

## 4. normapi routes + execution
- [x] `CloneJobStatus` in `normcore/enums.py`
- [x] `secrets.py` encrypt/decrypt (Fernet, `NORM_SECRET_KEY`) + round-trip unit test
- [x] connections CRUD + discovery routes (databases/tables/columns)
- [x] `POST /clone-jobs` (+ `CREATE DATABASE` text, PENDING_DB_CREATE)
- [x] `POST /clone-jobs/{id}/verify-database` (Phase 1 DDL)
- [x] `POST /clone-jobs/{id}/start` + `GET /clone-jobs/{id}` + `GET /clone-jobs/{id}/errors`
- [x] `clone_executor.py` Phase-2 loop — deviated from the plan's `normalize_column_to_arrow` suggestion in favor of `DistinctValuePlanner.distinct_value_results` directly (same call `InMemoryStore._normalize_deduped` already makes): `normalize_column_to_arrow`'s fixed `_JOIN_COLUMNS` drops `.errors`, which decision #9's full-detail error report needs verbatim — see clone_executor.py's module docstring
- [x] `dependencies.py` get_connections (reuses PgPersistence directly as the registry — no new wrapper class; see get_connections' docstring) + `app.state.connections`
- [x] `normapi/pyproject.toml`: +normio, +cryptography>=42,<44
- [x] route-level unit tests (validation, 404s, transitions) — `tests/unit/test_clone_routes.py`, fake PgPersistence via dependency override (no real DB)

## 5. UI
- [x] `api/client.ts` typed calls + `api/types.ts` types
- [x] `ConnectionsPage.tsx`
- [x] `CloneJobNewPage.tsx` (single page, local wizard state — no stepper, no separate per-step routes)
- [x] `CloneJobDetailPage.tsx` (polling + errors report, paginated)
- [x] `App.tsx` routes + `Nav.tsx` entries; `npm run build` passes (tsc -b && vite build, clean); `npm run lint` clean (pre-existing unrelated warning only)

## 6. Deferred docs (§7) — MySQL/Mongo/File, documentation only
- [x] write deferred section doc — `docs/adr/ADR-017-clone-normalize-engine-scope.md`

## 7. Integration tests
- [x] postgres-init: writable role w/ CREATEDB+DML; clickhouse users.xml: no-readonly user
- [x] `tests/integration/test_clone_pipeline.py`: PG→PG + CH→CH: DDL, population, bad-value fallback+error row, double-run no duplicates — 2/2 passing against real containers; 2 real bugs found and fixed by actually running it (semantic_type string-vs-enum identity check; ClickHouse Nullable-sorting-key hard error)

## 8. Verification (§9)
- [x] `pytest -m unit` green (558 passed / 1 pre-existing unrelated failure, same as baseline — zero regressions)
- [x] `docker compose up -d demo-postgres demo-clickhouse` + `pytest -m integration` green (13/13, incl. both clone_pipeline tests)
- [x] live docker-compose UI pass incl. hand-run CREATE DATABASE + psql row diffs + origin unchanged — found+fixed a real bug live (errors table never refetched after initial mount, so it stayed "No errors" through a real recorded error) and a real infra gotcha (saved connection host must be the docker-network service name, e.g. `demo-postgres`, not `localhost`, when the api runs in a container)
- [x] crash/resume re-run proof (`docker compose restart api` mid-run on a real 20,005-row job; destination rows == source exactly, 20000/20000, not doubled)
- [x] ponytail-review (2 real simplifications applied: unified bulk_insert signature, removed redundant single-raise-site exception class) + ponytail-debt (9 markers, 0 no-trigger) + ponytail-gain on final diff

## 9. CTO verification pass (independent re-run, post-handoff)
- [x] Independently reproduced: unit suite (558/1, matched), integration suite (2/2 clone_pipeline), live OpenAPI route check, a full live UI run (job → hand-run CREATE DATABASE → verify → start → COMPLETED), origin-untouched diff, PK replication, read-only-rejection, decision #3 (subset request ignored, full DB cloned), and the 20,005-row crash/resume proof (via the persisted job record) — all confirmed independently, not re-trusted from the report.
- [x] 2 real disclosure/precision issues found and fixed: (1) ponytail-debt count was ambiguous under a loose grep (9 tagged markers, but the module docstring separately repeated the `ponytail:` text for the threading.Thread marker) — docstring de-duplicated, now unambiguously 9 under any grep; (2) "a string-vs-enum identity check breaking Dispatcher.normalize" was imprecise — the check in `normcore/dispatch.py` is correct, pre-existing, untouched code; the actual bug was the caller (`clone_executor.py`) passing a raw string where the enum was required, fixed at the call site.
- [x] 1 misattribution corrected: `normcore/dispatch.py`/`pii.py`'s UTF-16-surrogate and `content_hash`-encoding fixes were reported as "undisclosed" — verified via `git diff`/`git diff --cached` that neither file has any edit from this feature's session; both were already staged (pre-existing M8 work) before this session's first edit.
- [x] `test_readonly_connectors.py`'s hardcoded ClickHouse port (and a second hardcoded MySQL host/port in its raw-driver write-rejection check) replaced with `TEST_*_HOST`/`TEST_*_PORT` env vars, same pattern as `test_clone_pipeline.py` — re-verified both ways: 13/13 from the host; 9/9 (+4 unrelated pre-existing skips, `test_address_normalizer_integration.py` hitting `localhost:8081` instead of the in-network `libpostal:8081` — a different file, out of this scope) from a throwaway container attached to `normalization_default` with `TEST_*_HOST` set to the compose service names.
- [x] Scratch data purged from the live metadata Postgres: `normalization_connections`/`normalization_clone_jobs`/`normalization_clone_job_errors` truncated, confirmed empty via the live API (`GET /connections` → `[]`).
- [ ] Commit (pending: container re-run finishing first, per the mandate — don't mark done on the strength of the first run alone).
