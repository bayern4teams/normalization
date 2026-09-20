# Wire `normio` into a DB-clone-and-normalize feature (Postgres + ClickHouse)

## Context

The app has always taken normalization input as inline JSON values via `POST /runs`. A whole `normio` package exists with real, tested, read-only Postgres/MySQL/Mongo/ClickHouse connectors — but it is **completely unwired**: no file outside `normio`'s own package/tests imports it (confirmed via codebase-memory-mcp: zero `IMPORTS` edges into `normio` from `normapi`/`normcli`), and `packages/normapi/pyproject.toml` doesn't even list `normio` as a dependency. The user wants to actually use it: point the app at a real origin database (strictly read-only, never modified), and have the app build a brand-new "clone" database next to it, schema-cloned then populated with normalized data, driven entirely from the UI, with no origin data ever at risk and no admin/create-database rights required by the app itself.

This was scoped through several rounds of explicit user decisions (recorded below as decisions, not options — do not re-litigate them). Scope for this plan: **Postgres and ClickHouse only** (both as origin and destination, always same engine). MySQL/Mongo/File are named at the end as deferred, suspended until the user approves continuing after Postgres+ClickHouse ship.

## Decisions already made (grounds for every design choice below)

1. **Discovery**: after host/port/username/password, the app queries the server itself for its list of databases (not a network port scan) → dropdown.
2. **Destination credentials**: a *second*, write-capable credential, same server (same host:port as origin) — the origin credential stays strictly read-only and is never reused for writes.
3. **Clone scope**: **every table** in the chosen origin database is cloned automatically. The per-column screen only decides, per column: semantic type (or passthrough/don't-normalize) — it never decides whether a table or column is included at all.
4. **Execution**: a background, pollable job (not a blocking request) — reuses this app's existing PENDING/RUNNING/COMPLETED run-status idiom.
5. **Two-phase**: Phase 1 creates the destination's tables completely empty (schema clone only). Phase 2, a separate background job, streams+normalizes+populates them.
6. **No admin rights for the app**: the app never issues `CREATE DATABASE`. It shows the user the exact command to run themselves, then verifies the database now exists before proceeding to create tables.
7. **Normalized columns replace in place** — no dual original+normalized columns in the clone.
8. **Failed normalizations**: keep the **original raw value** as fallback in the clone cell (never blank, never skip the row) — decided explicitly.
9. **Failure visibility**: a complete, well-organized, paginated error/warning report in the UI (explicit requirement: "completely give full detail report ... in perfect format and structure").
10. **Resumable**: a crashed/restarted job resumes rather than redoing a whole table, checkpointed via `source_row_key` (which `normio`'s connectors already stamp on every row for exactly this purpose).
11. **Clone constraints**: replicate primary keys/indexes (Postgres) and `ORDER BY`/table engine (ClickHouse) — not bare columns.
12. **Credentials at rest**: encrypted with an app-level key (env var), decrypted only in memory at connect-time. Nothing in this repo does encryption today (checked, zero hits) — `cryptography`'s `Fernet` is a justified new dependency, not scope creep.
13. **Saved connections are server-level** (host+port+username+password+engine) — the database is picked fresh each use, not baked into the saved connection. No per-user scoping (the app has no auth/session model anywhere — confirmed via codebase-memory-mcp).

## Layering decisions (ponytail: no speculative abstraction)

- **No new `DestinationConnector` Protocol.** Only one call site (the clone-job executor) ever touches destination writers, and it already knows the engine from the saved connection's `engine` field — a two-branch `if engine == "postgres" / else` is simpler than a Protocol with two implementations. `ponytail: add a Protocol only when a 3rd engine (MySQL) makes it a three-way branch.`
- **`SourceConnector` (read) and the new destination writers stay separate classes** — reusing the read connector for writes would need a second, differently-credentialed engine anyway, so sharing the class would be misleading, not lazy.
- **`list_databases()`/`get_columns()` go directly on `PostgresConnector`/`ClickHouseConnector`**, not added to the `SourceConnector` Protocol — `FileConnector`/`MongoConnector` are out of scope and would need dummy implementations if the Protocol grew these methods now.

## 1. `normio` — new read-side methods (extend existing classes)

- **`packages/normio/src/normio/connectors/postgres.py`**, `PostgresConnector`: add `list_databases()` (`SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname`) and `get_columns(table)` (`sa.inspect(self._engine).get_columns(table)` — same idiom `SqlConnectorBase.list_tables` already uses one line further).
- **`packages/normio/src/normio/connectors/clickhouse.py`**, `ClickHouseConnector`: add `list_databases()` (`SELECT name FROM system.databases ORDER BY name`, same shape as the existing `list_tables`, clickhouse.py:37-42) and a public `get_columns(table)` (`DESCRIBE TABLE`/`system.columns`) alongside the existing private `_list_columns` (44-49, which stays as-is — `read_table` still needs just the name set).
- New tiny `@dataclass(frozen=True) ColumnInfo(name, native_type)` return shape in `packages/normio/src/normio/connector.py`, next to `SourceConnector` — a data shape, not a behavior interface, no Protocol needed.

## 2. `normio` — new write-side classes

- **`packages/normio/src/normio/connectors/postgres_destination.py`** (new): `PostgresDestination(host, port, username, password)` — no `database` at construction (mirrors the server-level saved-connection shape). Same `postgresql+psycopg://` DSN convention as `PostgresConnector`/`pg_persistence.py`, but **no** `postgresql_readonly` execution option (this one writes). Methods: `database_exists(name)`, `create_table(database, table, columns, primary_key, indexes)`, `bulk_insert(database, table, rows)`.
- **`packages/normio/src/normio/connectors/clickhouse_destination.py`** (new): `ClickHouseDestination(host, port, username, password)`. Methods: `database_exists(name)`, `create_table(database, table, columns, order_by, engine="MergeTree")`, `bulk_insert(database, table, rows)` via `clickhouse_connect`'s native batch insert.
- `bulk_insert` on both **reuses `PgPersistence.save_execution`'s exact chunk loop** (`_ROW_CHUNK_SIZE = 2_000`, one `sa.text`/native-insert call per chunk, one transaction per chunk) — move `_ROW_CHUNK_SIZE` to `packages/normio/src/normio/connectors/_sql_base.py` as the one shared constant instead of redefining it, since it's now used by both packages. Chunk-commit boundaries double as checkpoint-commit boundaries for resumability (decision #10).
- Type mapping (`FieldSemanticType` → native destination column type) is a small fixed dict colocated with each `create_table` — 24 semantic types × 2 engines is a lookup table, not a reason to pull in a SQL-DDL-generation library. `ponytail: plain dict + string-built DDL, not a schema library — revisit only if a 3rd engine's type rules stop fitting a dict.`
- The `CREATE DATABASE ...;` text (decision #6) is a one-line f-string built in the route handler — not a method, not a class.

## 3. `normapi` — new Postgres schema (extend `pg_persistence.py`'s existing `_SCHEMA`, same convention)

```sql
CREATE TABLE IF NOT EXISTS normalization_connections (
    connection_id TEXT PRIMARY KEY,
    engine TEXT NOT NULL,              -- 'postgres' | 'clickhouse'
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT NOT NULL,
    encrypted_password TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS normalization_clone_jobs (
    job_id TEXT PRIMARY KEY,
    data TEXT NOT NULL   -- status, source/dest connection_id+database, per-table+per-column config,
                          -- progress counters (current table, last committed source_row_key per table) —
                          -- same single-JSONB-blob shape as normalization_runs.data
);
CREATE TABLE IF NOT EXISTS normalization_clone_job_errors (
    job_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    table_name TEXT NOT NULL,
    field TEXT NOT NULL,
    original TEXT,
    error TEXT NOT NULL,
    PRIMARY KEY (job_id, row_index, table_name, field)
);
```

`normalization_clone_jobs.data`'s single-JSONB-status-field shape means `claim_run_for_execution`'s exact conditional-`UPDATE`-with-`rowcount` pattern (`pg_persistence.py:351-373`) is directly copyable as `claim_clone_job(job_id)`:
```sql
UPDATE normalization_clone_jobs SET data = jsonb_set(data::jsonb,'{status}','"RUNNING"')::text
WHERE job_id = :jid AND (data::jsonb ->> 'status') = 'PENDING'
```
`normalization_clone_job_errors` mirrors `normalization_execution_rows`'s per-row shape and feeds a `get_run_errors`-shaped (`routes.py:385-414`) `NormalizationError` response.

Per-column config (semantic type or passthrough, per table) is **not** a new table — it's posted once as part of `POST /clone-jobs` and stored inside `normalization_clone_jobs.data`'s `field_configs` key. It's consumed exactly twice (Phase 1 DDL, Phase 2 normalization) by the job that owns it; re-running the same table later is a new job, not a "reuse my saved column config" feature nobody asked for. `ponytail: promote to its own table only if "reuse config across jobs" becomes a real requirement.`

New `PgPersistence` methods, placed next to their existing analogs: `save_connection`/`get_connection`/`list_connections`/`delete_connection` (mirror `save_profile`/`get_profile`/`list_profiles`); `create_clone_job`/`save_clone_job`/`get_clone_job`/`list_clone_jobs`/`claim_clone_job`; `save_clone_job_errors`/`load_clone_job_errors_page` (chunked insert + paginated read, mirroring `save_execution`/`load_execution_rows_page`).

## 4. `normapi` — routes, dispatch, background execution

**`packages/normapi/src/normapi/routes.py`** (same `Depends(get_store)`-style DI, same `HTTPException` conventions as every existing route):
- `POST /connections`, `GET /connections`, `DELETE /connections/{id}` — CRUD.
- `POST /connections/{id}/databases` (also accept ad-hoc inline host/port/user/pass for the not-yet-saved case) → `list_databases()`.
- `GET /connections/{id}/databases/{db}/tables` → `list_tables()`.
- `GET /connections/{id}/databases/{db}/tables/{table}/columns` → `get_columns()`, paginated limit/offset (same query-param names and capped page size as `GET /runs/{run_id}/values`).
- `POST /clone-jobs` — body: origin connection+database (all tables included per decision #3), destination connection, `field_configs` per table. Creates the job, returns the `CREATE DATABASE ...;` text + job id in a `PENDING_DB_CREATE` status. Add `CloneJobStatus` to `normcore/enums.py` next to the existing `RunStatus`, not an ad-hoc string.
- `POST /clone-jobs/{id}/verify-database` — calls `destination.database_exists(db)`; on success, runs `create_table` for every table (Phase 1) and advances status.
- `POST /clone-jobs/{id}/start` — claims the job (`claim_clone_job`) and starts Phase 2.
- `GET /clone-jobs/{id}` — status/progress poll target.
- `GET /clone-jobs/{id}/errors` — paginated, `NormalizationError`-shaped, same route shape as `get_run_errors`.

**Background execution**: no task-queue dependency exists in this codebase and none is justified for 2 engines / one deployment. `/start` kicks off Phase 2 on a daemon `threading.Thread`, same process, same `app.state`-held `dispatcher`/`cache`. `ponytail: threading.Thread, not Celery/RQ — a crashed process loses the in-flight thread, but the job resumes from its last committed chunk (checkpointed every chunk-commit), so correctness survives; only "auto-restart on crash" doesn't. Upgrade to a real task queue only if this needs to survive across multiple app replicas.`

**`packages/normapi/src/normapi/clone_executor.py`** (new, the Phase-2 loop):
1. Build origin `SourceConnector` and destination writer from decrypted saved-connection credentials (`secrets.py`, §5).
2. For every table in the job: `for batch in origin.read_table(table):` — stream, never materialize a whole table (same OOM-safety discipline as `save_execution`'s chunking).
3. For each configured (non-passthrough) column, call **`DistinctValuePlanner.normalize_column_to_arrow`** (`packages/normexec/src/normexec/planner.py:148-168`) directly on the Arrow batch — this is Arrow-native and avoids an unnecessary Polars round-trip (`read_table` already yields Arrow; a plain `normalize_column` would need a `pl.from_arrow` detour first). Same `Dispatcher`/cache `execute_run` already uses — no second normalization call path. Build the context with `error_policy=ErrorPolicy.RETURN_ORIGINAL` (`normcore/enums.py:62-69`) — that policy already makes `apply_error_policy` (`normcore/errors.py:55-78`) return the original value with an error marker on any normalizer failure. This *is* decision #8, with zero new fallback logic to write.
4. Passthrough columns copy through untouched (original native value, original native type).
5. `destination.bulk_insert(db, table, rows)` — chunked at `_ROW_CHUNK_SIZE`.
6. Any row/column with a recorded error gets buffered and flushed via `save_clone_job_errors` at the same chunk boundary as the bulk insert — checkpoint and error-flush share one transaction boundary.
7. After each chunk commits, update `normalization_clone_jobs.data`'s progress (rows done, current table, last committed `source_row_key`) via `save_clone_job`.
8. **Resume**: on `/start` for an already-`RUNNING`-but-orphaned job, re-stream the table from the start and skip rows whose `source_row_key` is ≤ the last committed checkpoint, until reaching it. `ponytail: re-stream-and-skip, not a WHERE source_row_key > :checkpoint pushdown (read_table has no per-row filter param today) — correct, but re-reads already-processed rows on resume. Add pushdown filtering to read_table if resumed jobs on very large tables become a real cost.`

**`packages/normapi/src/normapi/dependencies.py`** — add a `get_connection_registry`-style dependency, same `Annotated[X, Depends(get_x)]` shape as `get_store`, backed by `app.state.connections` set up in `create_app` the same way `app.state.store` already is.

**`packages/normapi/pyproject.toml`** — add `"normio"` to `dependencies` (currently listed as a workspace member at the *root* `pyproject.toml` only — confirmed via codebase-memory-mcp that `normapi`'s own dependency list doesn't include it yet, so nothing in `normapi` can import it until this is added) and `"cryptography>=42,<44"`.

## 5. Encryption helper (decision #12)

**`packages/normapi/src/normapi/secrets.py`** (new, ~10 lines): `encrypt(plaintext) -> str` / `decrypt(ciphertext) -> str` via `Fernet(os.environ["NORM_SECRET_KEY"].encode())`. Called only at write-time (`save_connection`) and read-time-of-use (building a connector/writer in `clone_executor.py`/the discovery routes) — never held decrypted anywhere else. `ponytail: one key from one env var, no rotation/versioning — add key-versioning only if rotation becomes a real requirement.`

## 6. UI

- **`ui/src/pages/ConnectionsPage.tsx`** (new) — list/create/delete saved connections; same local-`useState`-fields + `useMutation` idiom as `PreviewPage.tsx`.
- **`ui/src/pages/CloneJobNewPage.tsx`** + **`CloneJobDetailPage.tsx`** (new) — chained plain routes: connection → database → (all tables listed, paginated) → per-table column config → confirm/DDL → verify → start. No stepper component exists anywhere in this app and none is introduced — a few page routes with local state and `navigate()`, matching the codebase's existing idiom. Progress view: `useQuery({ queryKey: ["clone-job", id], queryFn, refetchInterval: 2000 })` — the one genuinely new UI idiom this feature needs (react-query's built-in polling option, not a new abstraction).
- **`ui/src/pages/CloneJobDetailPage.tsx`** errors section — same table + `QueryState` + pagination layout as `RunDetailPage.tsx`'s errors section, reading the new paginated errors route.
- **`ui/src/api/client.ts`** — add typed functions (`listConnections`, `createConnection`, `deleteConnection`, `listDatabases`, `listTables`, `listColumns`, `createCloneJob`, `verifyCloneJobDatabase`, `startCloneJob`, `getCloneJob`, `getCloneJobErrors`), each a thin wrapper through the existing `request<T>()` (client.ts:49-67) — no new fetch machinery.
- **`ui/src/api/types.ts`** — add `Connection`, `CloneJob`, `CloneJobStatus`, table/column listing interfaces, hand-synced to the new Pydantic models the same way `FieldSemanticType` already is (no codegen exists; don't introduce one here).
- **`ui/src/app/Nav.tsx`** — add `Connections` and `Clone` entries to `NAV_ITEMS`.
- **`ui/src/App.tsx`** — add flat `<Route>`s (`connections`, `clone`, `clone/:jobId`) inside the existing `<Layout />` route block, same pattern as every other route.

## 7. Deferred (write only, do not implement — suspended until Postgres+ClickHouse ship and the user approves continuing)

- **MySQL**: same `_sql_base.py` SQLAlchemy machinery for reads, but no session-level read-only guarantee exists for MySQL (`postgresql_readonly` is Postgres-specific) — would fall back to DB-grant-only enforcement; a MySQL destination writer needs its own DDL dialect (no `pg_database`-style catalog, no ORDER BY/engine like ClickHouse).
- **MongoDB**: schema-on-read means "replicate columns/types" (decision #11) doesn't map cleanly — would need a document-shape-inference step that doesn't exist anywhere in this codebase.
- **File**: `FileConnector` has no "server" (host+port+credentials) concept at all — "saved connection" and "database discovery" don't apply the same way; a file-based clone is really "pick a file, pick a destination," a different UX shape, not a small extension of this plan.

## 8. Test strategy

- **Unit** (`tests/unit/`, `@pytest.mark.unit`): `PgPersistence` new-table CRUD + `claim_clone_job` race behavior, mirroring existing persistence unit tests; `secrets.py` round-trip (`encrypt(x)` → `decrypt()` == `x`, wrong key fails) as the required `assert`-based self-check for this non-trivial logic; type-mapping dict coverage (every `FieldSemanticType` has both a Postgres and a ClickHouse native type).
- **Integration** (`tests/integration/`, `@pytest.mark.integration`): reuse `compose.yaml`'s existing `demo-postgres`/`demo-clickhouse` services and `tests/integration/fixtures/{postgres,clickhouse}-init/` verbatim for the **origin** side (same containers `test_readonly_connectors.py` already uses). Add one new writable role/user to each init fixture for the **destination** side (a `writable_user` Postgres role with `CREATEDB`+DML grants; a ClickHouse `users.xml` entry with no `readonly` profile restriction). New `tests/integration/test_clone_pipeline.py`: end-to-end against real demo-postgres→demo-postgres and demo-clickhouse→demo-clickhouse (a second database on the same demo container stands in for "second credential, same server"), asserting DDL correctness (types/PK/indexes or ORDER BY), correct row population, a deliberately-bad value landing with its original value plus a recorded error, and that calling the executor twice (simulating a crash+restart) doesn't duplicate rows.
- **Route-level** (`tests/unit/`, FastAPI `TestClient`, no real DB): request validation, 404s, and status transitions for the new routes, same style as existing run-lifecycle route tests.
- Run: `uv run pytest -m unit` for the fast pass; `docker compose up -d demo-postgres demo-clickhouse` then `uv run pytest -m integration` for the real-container pass — matches this project's existing two-tier verification split already encoded in `pyproject.toml`'s marker list.

## 9. Verification

1. `uv run pytest -m unit` — new tests green, zero regressions in the existing suite (this session's established baseline: 770 passed / 0 failed before touching anything, re-checked after).
2. `docker compose up -d demo-postgres demo-clickhouse` + `uv run pytest -m integration` — `test_clone_pipeline.py` proves Phase 1 DDL + Phase 2 population + error fallback + resume against real Postgres and real ClickHouse, not mocks.
3. Live pass via full `docker compose up` + the UI: create a saved connection to `demo-postgres`, discover databases/tables/columns, configure one column as `EMAIL` and leave the rest passthrough, submit a clone job, run the returned `CREATE DATABASE` command by hand (`docker compose exec demo-postgres psql ...`), click verify, start the job, poll progress to `COMPLETED`, open the errors report, and diff a few destination rows against the source directly via `psql`/`clickhouse-client` to confirm normalized-in-place values and untouched passthrough columns — and confirm the origin table is byte-for-byte unchanged.
4. Re-run step 3's job a second time after `docker compose restart api` mid-run, to demonstrate the `source_row_key` checkpoint resume actually resumes rather than duplicating rows (destination row count matches source exactly, not double).

### Critical files
- `packages/normio/src/normio/connectors/postgres.py`, `clickhouse.py`, `_sql_base.py` (extend)
- `packages/normio/src/normio/connectors/postgres_destination.py`, `clickhouse_destination.py` (new)
- `packages/normio/src/normio/connector.py` (add `ColumnInfo`)
- `packages/normapi/src/normapi/pg_persistence.py` (extend schema + methods)
- `packages/normapi/src/normapi/clone_executor.py` (new)
- `packages/normapi/src/normapi/secrets.py` (new)
- `packages/normapi/src/normapi/routes.py`, `dependencies.py`, `app.py` (extend)
- `packages/normapi/pyproject.toml` (add `normio`, `cryptography` deps)
- `packages/normcore/src/normcore/enums.py` (add `CloneJobStatus`)
- `packages/normexec/src/normexec/planner.py` (reuse `normalize_column_to_arrow`, no change expected)
- `ui/src/pages/ConnectionsPage.tsx`, `CloneJobNewPage.tsx`, `CloneJobDetailPage.tsx` (new); `ui/src/App.tsx`, `Nav.tsx`, `api/client.ts`, `api/types.ts` (extend)
- `tests/integration/fixtures/postgres-init/`, `clickhouse-init/users.xml` (add writable role/user)
- `tests/integration/test_clone_pipeline.py` (new)
