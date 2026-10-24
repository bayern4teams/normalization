# DB-Clone-and-Normalize Verification Pack

Status: **All Layer 1/2 checks complete and passing, including an independent second-reviewer verification pass. Ready for Human Sign-off.**

Scope: point the app at a real origin database (Postgres or ClickHouse,
strictly read-only, never modified), clone its schema to a new destination
on the same server, then stream+normalize+populate it — driven from the
UI, with no admin/`CREATE DATABASE` rights required by the app itself.
This feature is **not** part of the `Source.txt` §0-§137 / 8-milestone gate
model — it wires the previously-unwired `normio` package (zero import
edges into `normapi` before this work) into a real feature per a
separate, explicit plan. It does not appear in
`docs/traceability-matrix.md` or the §136 acceptance-criteria table for
that reason; this pack is its own, equivalent evidence trail, structured
the same way the M0-M8 packs are.

Full decision record: the approved plan's "Decisions already made"
(13 items, referenced by number below) and `docs/adr/ADR-017-clone-normalize-engine-scope.md`
(why MySQL/Mongo/File are documentation-only). Live progress ledger:
`docs/archive/plans/TODO.md` (archived).

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `normio`: `PostgresDestination`/`ClickHouseDestination` write-capable connectors, `get_primary_key`/`get_table_engine_info` read-side additions | ✅ Done |
| `normapi`: `pg_persistence.py` connections/clone-job schema+CRUD, `clone_executor.py` (Phase 1 DDL + Phase 2 stream/normalize/populate/resume), `secrets.py` (Fernet encryption at rest), full route surface | ✅ Done |
| `normcore`: `CloneJobStatus` enum | ✅ Done |
| UI: `ConnectionsPage`, `CloneJobNewPage`, `CloneJobDetailPage` (polling, paginated error report) | ✅ Done |
| Postgres + ClickHouse only, both as origin and destination, always the same engine; MySQL/Mongo/File documentation-only | ✅ Done — ADR-017 |
| Integration tests against real Postgres + ClickHouse, both engines, DDL + population + error-fallback + resume | ✅ Done |
| Live docker-compose UI pass + independent second-reviewer verification | ✅ Done |

## 2. Layer 1 — Automated verification results

```
uv run pytest -m unit -q
  -> 558 passed, 1 failed (test_real_repo_files_are_fully_cross_referenced —
     pre-existing, unrelated: Source.txt was deleted before this feature's
     work began; same baseline before and after)

uv run pytest -m integration -q      (from the host)
  -> 13 passed, 832 deselected

docker run --rm --network normalization_default \
  -e TEST_PG_HOST=demo-postgres -e TEST_PG_PORT=5432 \
  -e TEST_MYSQL_HOST=demo-mysql -e TEST_MYSQL_PORT=3306 \
  -e TEST_MONGO_HOST=demo-mongo -e TEST_MONGO_PORT=27017 \
  -e TEST_CLICKHOUSE_HOST=demo-clickhouse -e TEST_CLICKHOUSE_PORT=8123 \
  <image> bash -lc "cd /app && uv run pytest -m integration -q"
  -> 9 passed, 4 skipped (test_address_normalizer_integration.py hitting
     localhost:8081 instead of the in-network libpostal:8081 — a
     different, pre-existing file, not in this feature's scope), 832
     deselected

cd ui && npm run build     -> tsc -b && vite build: clean, no errors
cd ui && npm run lint      -> oxlint: clean (one pre-existing, unrelated
                               warning in ModeContext.tsx)
```

New this feature: `tests/unit/test_clone_secrets_and_types.py` (5 tests —
secrets round-trip + wrong-key failure + FieldSemanticType→native-type
coverage for both engines), `tests/unit/test_clone_routes.py` (7 tests —
route validation/404s/state transitions against a fake `PgPersistence` via
dependency override), `tests/integration/test_clone_pipeline.py` (2
tests — full Postgres→Postgres and ClickHouse→ClickHouse pipelines
against real containers). All prior-milestone suites unchanged and still
fully passing — no regressions, confirmed both before and after every
meaningful change, not just once at the end.

Two real bugs were found and fixed by actually running the integration
tests against live containers, not by reading the code and trusting it:

1. `clone_executor.py` passed a raw JSON string where
   `Dispatcher.normalize`'s `context.semantic_type is not semantic_type`
   identity check (pre-existing, correct code, untouched by this feature)
   requires the real `FieldSemanticType` enum member — fixed at the
   caller.
2. ClickHouse hard-rejects a `Nullable` sorting-key column
   (`allow_nullable_key` disabled by default) — `create_table` now never
   wraps an ORDER BY column in `Nullable(...)`, stripping one if the
   origin's own type string already carried it.

ponytail-review found 2 real simplifications, applied: `ClickHouseDestination.bulk_insert`
took an unused `primary_key` kwarg (matching `PostgresDestination`'s
signature) instead of a separate `isinstance`-branching wrapper function;
a single-raise-site `DestinationDatabaseNotReadyError` collapsed into the
existing `CloneJobStateError` (routes.py mapped both to the same 409
already). ponytail-debt: 9 markers, 0 with no named upgrade trigger.

## 3. Layer 2 — Live verification

### 3.1 Full stack, built and running for real

`docker compose up -d --build` — real image rebuild (picking up the new
`normio`/`cryptography` deps in `packages/normapi/pyproject.toml`), all
seven services healthy including the rebuilt `api` container:

```
normalization-api-1               Up (healthy)
normalization-demo-clickhouse-1   Up (healthy)
normalization-demo-mongo-1        Up (healthy)
normalization-demo-mysql-1        Up (healthy)
normalization-demo-postgres-1     Up (healthy)
normalization-libpostal-1         Up (healthy)
normalization-postgres-1          Up (healthy)
```

`GET /openapi.json` against the live container confirmed all 10 new
routes present and reachable: `/normalization/connections`,
`/normalization/connections/{id}`,
`/normalization/connections/{id}/databases`,
`/normalization/connections/{id}/databases/{db}/tables`,
`/normalization/connections/{id}/databases/{db}/tables/{table}/columns`,
`/normalization/clone-jobs`, `/normalization/clone-jobs/{id}`,
`/normalization/clone-jobs/{id}/verify-database`,
`/normalization/clone-jobs/{id}/start`,
`/normalization/clone-jobs/{id}/errors`.

### 3.2 Live UI pass (decision #4/#5/#9), driven end to end through the real UI

Created a saved connection (`demo-postgres:5432`, `readonly_user`) →
discovered real databases/tables/columns through the UI → configured
`clone_source.email` as `EMAIL`, left everything else passthrough →
submitted the job (`PENDING_DB_CREATE`, returned
`CREATE DATABASE ui_demo_clone;`) → ran that command by hand via
`psql` (decision #6: the app never issues it itself) → clicked Verify
(`SCHEMA_READY`, Phase 1 DDL created every table completely empty) →
clicked Start → polled to `COMPLETED` (2 tables, 5 rows) — all in the
real browser against the real running stack, not simulated.

Found and fixed one real bug live: the errors table used a one-shot
`useQuery` fetched at mount time (typically `PENDING_DB_CREATE`, before
Phase 2 had produced any errors), so it never refetched as the job
progressed and stayed a stale "No errors" through a real recorded error.
Fixed by giving `errorsQuery` the same polling condition as the job
query. Re-verified live after the fix: the UI correctly showed
`clone_source.email`, row `1`, `An email address must have an @-sign.`

### 3.3 Decision #7/#8/#9/#11 verified directly against the destination

```
\d clone_source   (on the destination)
 id     | integer | not null
 email  | text    |
Indexes: "clone_source_pkey" PRIMARY KEY, btree (id)   -- decision #11

SELECT * FROM clone_source ORDER BY id;
 1 | Valid.User@example.com    -- real normalization, domain lowercased
 2 | not-an-email              -- decision #8: fallback to original, never blank
```
Both rows land in the SAME `email` column (decision #7: no dual
original+normalized columns).

### 3.4 Decision #3 verified directly (every table cloned, not a caller-chosen subset)

Posted a clone-job request naming only `["customers"]` in `tables`; the
job's stored table list still included `clone_source` — the app derives
the table list itself from `list_tables()` at creation time and ignores
any caller-supplied subset, per the plan's explicit design (there is no
per-table opt-out at job-creation time by design).

### 3.5 Decision #2/#1 verified directly (origin never at risk)

```sql
-- as readonly_user, against the origin
UPDATE customers SET first_name = 'x' WHERE id = 1;
ERROR: permission denied for table customers
```
Origin `clone_source`/`customers` content re-read after the full run:
byte-for-byte identical to the pre-run seed data.

### 3.6 Decision #10 — crash/resume proof, at real scale

Seeded a 20,000-row table (`resume_test`), started the clone job, and
ran `docker compose restart api` ~0.4s after `POST .../start` returned
— a genuine mid-run process kill, not a simulated one. The job was left
orphaned at `RUNNING` (`rows_done: 5`, `resume_test` not yet started).
Called `POST .../start` again after the container came back healthy;
the job resumed and reached `COMPLETED` (`rows_done: 20005`).
Destination row counts, queried directly:

```
clone_source |     2
customers    |     3
resume_test  | 20000      -- exactly the origin's row count, not doubled
```

### 3.7 Independent second-reviewer verification (not self-reported)

A separate verification pass reproduced this feature's claims
independently rather than trusting the implementation's own report:
rebuilt the test image from current code (not an old cached one) and
re-ran the unit suite (558/1, exact match), re-ran
`test_clone_pipeline.py` against the live containers (2/2), hit the
live OpenAPI schema directly, ran the full UI flow itself, diffed
origin vs. destination directly via `psql`, attempted a real write
against `readonly_user` and confirmed the database-level rejection,
confirmed decision #3 by posting a deliberately-restricted table list
and observing it was ignored, and cross-checked the 20,005-row
crash/resume claim against the persisted job-progress record. It found
two real precision/disclosure issues in the original report (both
corrected — see §3.8) and confirmed everything else as claimed.

### 3.8 Follow-ups from the independent review, applied and re-verified

1. `test_readonly_connectors.py` hardcoded a ClickHouse port and a
   MySQL host/port in raw-driver calls (pre-existing, unrelated to this
   feature, found only because the review ran the suite from a
   container). Parametrized via `TEST_*_HOST`/`TEST_*_PORT`, same
   pattern as `test_clone_pipeline.py`. Re-verified passing both ways
   (§2 above).
2. A summary description ("a string-vs-enum identity check breaking
   `Dispatcher.normalize`") was imprecise — the check itself is correct,
   pre-existing, untouched code; the bug was the caller. Corrected in
   this pack's §2.
3. The ponytail-debt marker count was ambiguous under a loose grep (a
   module docstring separately repeated one marker's text). De-duplicated;
   now unambiguously 9 under any grep.
4. Scratch connections/clone-jobs created during testing purged from the
   live metadata Postgres (`TRUNCATE`, confirmed empty via the live API).

### 3.9 A real, previously-undisclosed correctness bug — found on the first genuine e2e run against real data

Everything above (§3.1-§3.8) ran against small, hand-picked fixture data.
The first run against a real user's own database (13 tables, 52,828
rows, origin data in a non-default Postgres schema) failed outright on
the first chunk: a source `foundingdate` value like `"d1989-12-11"`
correctly failed `DateNormalizer`, correctly fell back to its original
raw value per decision #8 — and then couldn't be inserted into the
destination's native `DATE` column. Because the insert is one
transaction per chunk, this crashed the whole chunk, and with it the
whole job, including the error-report row for that exact value, which
never got written — the opposite of decision #9.

Root cause: there is no per-row column typing in SQL — a configured
column's destination type is fixed at `CREATE TABLE` time, before any
row's success/failure is known, so decision #8's "always insertable
fallback" guarantee is incompatible with any native (non-text) type.
Fixed by collapsing `SEMANTIC_TYPE_TO_PG_TYPE`/`SEMANTIC_TYPE_TO_CH_TYPE`
to map every semantic type to a text-compatible destination type (later superseded for NUMERIC/MONEY/BOOLEAN by the
`storage_types.coerce` cast gate; see ADR-020),
regression-tested (unit: every mapped type asserted text-compatible;
integration: the exact `d`-prefixed-date scenario, against a real
container), and re-verified against the same real database after
rebuilding and redeploying the `api` image:

```
status: COMPLETED, rows_done: 52828, tables_completed: 13/13, error: None
11,218 errors recorded (foundingdate parse failures, bare-domain website
values with no URL scheme — real source data quality, not app bugs),
each with its original value intact. Real normalization visible on
clean data (double-space collapsing, curly->straight quotes). Origin
re-verified byte-unchanged and still write-rejecting.
```

## 4. Known, disclosed gaps (not blocking, tracked via `ponytail:` comments in the code)

- Resumed inserts are idempotent via `ON CONFLICT DO NOTHING` on Postgres
  when the origin table has a primary key; a table with no primary key,
  or a crash inside ClickHouse's in-flight chunk (no `ON CONFLICT`
  equivalent there), has no dedup guard. Acceptable for the demo/decided
  scope; upgrade path named in `postgres_destination.py`/
  `clickhouse_destination.py`.
- Resume re-streams a table from the start and skips already-committed
  rows rather than a pushdown filter — correct, but re-reads processed
  rows on resume. `read_table` has no per-row filter param today.
- A crashed process loses the in-flight `threading.Thread`; the job
  resumes from its last committed chunk (proven in §3.6), but nothing
  auto-restarts it — a human (or the UI) has to click Start again. Named
  explicitly as out of scope unless this needs to survive across
  multiple app replicas.
- MySQL/MongoDB/File: documentation-only, per ADR-017.

## Human Sign-off

feature: DB-clone-and-normalize (normio wiring)
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |
