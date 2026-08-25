# M13–M22 Program Plan: Product-Grade Normalization Pipeline

## Status

Approved by the user 2026-08-26. **Not yet implemented** — this document
records the plan itself; implementation proceeds milestone by milestone,
each closing with its own real, live-verified
`docs/verification/M{n}-verification-pack.md`, matching this project's
standing discipline. Do not read any milestone below as done until its own
pack says so.

## Context

M0–M12 (`docs/plan/M1-M12-retrospective-plan.md`) built a genuinely capable
normalization engine — 20+ normalizers, profile versioning, dictionaries,
collision analysis, A/B comparison, OTel observability, and real
mutation-tested coverage. But it is not usable as a product:

- The UI exposes 11 tabs of internal engine vocabulary (Profiles, Rules,
  Fields, Dictionaries, Collisions…). A user cannot connect a database and
  clean it without already understanding the engine's internals.
- Connections are a hand-edited JSON file read once at process start. There
  is no write endpoint, no connection test, no way to list databases.
- A run normalizes **one column**, materialized entirely in memory, capped
  at 100k rows, in a raw daemon thread with no progress and no resume.
- Normalized output goes nowhere — there is no destination, only report
  endpoints.

The real target is a live ClickHouse the user already runs at
`localhost:8190`: `origin2` holds **11.8M Person rows, 12.2M Experience
rows, 1.27M Company rows** across 7 tables, every one `ReplacingMergeTree`
with a real primary key and a `created_at` column. This scale is why the
program cannot simply extend the existing single-column, whole-table-in-
memory execution path — verified directly against that live server during
planning (see the risk table below).

**Intended outcome:** a 3-step product — *Connect → Map → Report* — that
ingests a real multi-million-row database, normalizes many columns in one
run, optionally mirrors clean data into a destination database, remembers
its configuration, and processes only new data on subsequent runs.

## Fixed decisions

Agreed with the user during planning (`AskUserQuestion` rounds, 2026-08-26).
Not open for re-litigation without a new conversation with the user.

| # | Decision |
|---|---|
| 1 | Real chunked/streaming execution now — not sample-capped |
| 2 | Credentials encrypted at rest in Postgres via `NORM_SECRET_KEY`; never returned by any GET |
| 3 | The 11 legacy tabs are hidden behind the existing `ModeContext`, not deleted |
| 4 | Column mappings keyed by `host+port+database` identity, never by user alias |
| 5 | One run holds many columns — extend the core run model |
| 6 | Optional destination DB; app creates DB+tables if absent; source never written to |
| 7 | Destination mirrors table/column names + order; mapped NUMERIC/DATE get real typed columns; unmapped copied verbatim; same engine only |
| 8 | Quality/warnings/lossiness go to a separate side table, not extra columns |
| 9 | Incremental by `created_at` watermark + explicit full resync action |
| 10 | Retroactive M1–M12 plan doc, live-verified packs for M12 + all new milestones, one-command startup, source write endpoints |

## Dependency chain

```
M13 docs ─(discipline gate)

M14 catalog + streaming ─→ M15 connections + crypto ─→ M16 catalog API + mappings
                                                             │
                                                             ▼
                                                    M17 multi-column chunked runs
                                                             │
                              ┌──────────────────────────────┼──────────────────┐
                              ▼                              ▼                  ▼
                        M18 reporting              M19 destination        M20 watermark
                              │                              │                  │
                              └──────────────┬───────────────┴──────────────────┘
                                             ▼
                                      M21 3-step UI ─→ M22 one-command startup
```

**The 3-step UI cannot be built before M18.** Tabs 1–2 are reachable after
M16; "one button starts normalization" needs M17; "full report" needs M18.
Do not start M21 early.

---

## M13 — Ledger catch-up (docs only, this milestone)

- `docs/plan/M1-M12-retrospective-plan.md` — reconstructed from git log +
  the 12 packs.
- `docs/plan/M13-M22-program-plan.md` — this document.
- `docs/verification/M12-verification-pack.md` — the missing pack, with
  real Layer 1 evidence (ruff/mypy/pytest/license/traceability, all
  actually executed, not narrated).
- `docs/traceability-matrix.md` — add M13–M22 rows, marked planned/not yet
  implemented; refresh the stale "Last updated: M7 follow-up" header.
- `docs/adr/ADR-017-connection-credentials.md` — stub; filled in M15.
- `scripts/check_signoff.py` — real bug fixed: `MILESTONE_ORDER` stopped at
  M8, so `--milestone M9` (and M10/M11/M12) would fail argparse's `choices`
  validation outright. Extended through M22.

**Explicitly not done in M13, by design:** the blank `## Human Sign-off`
blocks on M0–M11's packs are left blank. Every pack in this project's
history has left that block for the user to fill in; fabricating a verdict,
reviewer, or date on the user's behalf would misrepresent that a human
review happened when it didn't. M13 prepares evidence for review — it does
not perform the review.

---

## M14 — Connector catalog + real streaming (`normio` only)

Pure library work, no API/UI surface, fully verifiable against the live
ClickHouse.

**Create**
- `packages/normio/src/normio/catalog.py` — `ColumnSpec`, `TableSpec`
  (engine, sorting_key, primary_key, approx_rows, created_at nullability).
- `packages/normio/src/normio/capabilities.py` — two new protocols,
  deliberately separate from `SourceConnector`
  (`packages/normio/src/normio/connector.py:1-14` — its "no write
  vocabulary at all" argument is load-bearing in ADR-013 and three
  verification packs, so it is not extended): `CatalogConnector`
  (`list_databases`, `list_columns`, `table_spec`, `sample_rows`,
  `sample_values`) and `StreamingSourceConnector`
  (`read_chunk(table, columns, *, key_columns, after_key, limit, since)`).
  Capability-check with `isinstance` at the registry; return 501 for
  connectors lacking the capability.

**Change**
- `connectors/clickhouse.py` — promote the private `_list_columns`
  (currently line 44) to a typed public `list_columns`; add
  `list_databases()` from `system.databases`; `table_spec()` from
  `system.tables`. Derive key columns from `system.columns.
  is_in_primary_key`, not by parsing `sorting_key` — verified live:
  `PersonContact`'s sorting key is the expression `personID,
  assumeNotNull(contactString)`, but `is_in_primary_key` cleanly returns
  `personID` + `contactString` without any expression parsing. Add
  `read_chunk()` with keyset pagination and `LIMIT` pushdown. Rewrite
  `read_table` to use `query_arrow_stream` — it currently calls
  `query_arrow()`, which materializes the **entire** table before yielding
  the first batch (confirmed against the installed `clickhouse_connect`
  0.15.1, which has `query_arrow_stream` available and unused).
- `connectors/_sql_base.py` — same via SQLAlchemy `inspect`
  (`get_schema_names`, `get_columns`, `get_pk_constraint`).
- Replace the positional `source_row_key`
  (`clickhouse.py:83`, `f"{table}:{row_offset+i}"`) with a value derived
  from real key columns.
- **`packages/normapi/src/normapi/store.py:142`** —
  `rows.sort(key=lambda row: int(row["source_row_key"]))`. Verified
  present in the current codebase. This hard-crashes the instant the key
  stops being numeric, so it must land in this milestone, alongside the
  key change, not after. Persist an explicit `row_ordinal` column in the
  sidecar instead.

**Reuse unchanged:** `SidecarStore`, `DistinctValuePlanner`,
`NormalizationCache`.

**Verify live (against `localhost:8190`, databases `origin1`/`origin2`):**
`list_databases()` → `["origin1","origin2"]`; `table_spec("Experience")` →
ReplacingMergeTree, ≈12,234,811 rows, key `(companyID, experienceID)`;
three sequential `read_chunk(Person, limit=1000)` → 3000 **distinct**
personIDs with flat peak RSS; `sample_values` under 1s (proves LIMIT
pushdown, not client-side truncation). Record in
`docs/verification/bench-baseline-m14.json`, matching the existing
`bench-baseline-m2.json` .. `m6.json` convention.

---

## M15 — Connection registry with encrypted credentials

**Create**
- `normapi/secrets.py` — AES-GCM from `NORM_SECRET_KEY`; require a real
  32-byte key; refuse to boot if connection rows exist and the key is
  absent.
- `normapi/connections.py` — `ConnectionRecord`, server-side default-port
  table (clickhouse 8123, postgres 5432, mysql 3306, mongo 27017), and
  `connection_identity(kind, host, port, database)` as a blake3 hex (blake3
  is already a dependency via `normexec.cache`).
- `normapi/migrations.py` — a small versioned migration runner +
  `schema_migrations` table. This milestone pays the migrations debt: six
  new tables land across M15–M20 and the DuckDB sidecar catalog gains a
  column in M17, and `CREATE TABLE IF NOT EXISTS`
  (`postgres_store.py:53`, `sidecar_store.py:24`, `cache.py:103`) cannot
  express any of that on an existing deployment. Not Alembic — a small
  hand-rolled runner matches this project's existing "no framework beyond
  what's needed" pattern.

**Change**
- `normapi/sources.py` — hybrid: file-configured sources stay eager (every
  existing test's behavior preserved); DB-configured connections build
  lazily into a bounded pool keyed by `(connection_id, database)`, with
  `refresh()` so a newly-POSTed connection works without a restart.
  Rewrite the module docstring — its current "DSNs are never accepted from
  a request body, deliberately" claim becomes false with this milestone,
  and this repo's culture is disclosed boundaries, not silent
  contradictions (see ADR-017).
- `normapi/routes.py` — `POST /connections`, `POST /connections/test`,
  `GET /connections`, `PATCH /connections/{id}`, `DELETE
  /connections/{id}`, `GET /connection-kinds`. Leave the existing
  `GET /sources` untouched for back-compat.
- `normapi/schemas.py` — `ConnectionCreateRequest` with
  `password: SecretStr`; `ConnectionResponse` with no password field at
  all (absent, not `None`, so `model_dump` cannot leak it).
- `normapi/app.py` — `NORM_SECRET_KEY` wiring beside the existing
  optional-env block.

**Verify live:** POST `{clickhouse, localhost, 8190, default, pass,
origin2}` → 201; `GET /connections` contains no password anywhere in the
response body; the Postgres row shows ciphertext, not plaintext; restart
the API → connection still resolves; wrong password → structured 400 with
no credential echoed anywhere (response, logs, or spans).

**Must fix in this milestone, not later:** `POST /connections/test` carries
a plaintext password in a request body, and M12 wired real OTel spans into
the live app. Add explicit span-attribute and access-log scrubbing for this
route — overriding ADR-013's old policy without neutralizing the harm it
named would be the worst of both worlds.

---

## M16 — Catalog API + connection-keyed mappings + the semantic-type bug

**Create**
- `normapi/mappings.py` + `column_mappings` table, PK
  `(connection_identity, database, table_name, column_name)` →
  `semantic_type, semantic_source, enabled, updated_at, updated_by`. Keyed
  by identity, never alias (decision 4).

**Change**
- `normapi/routes.py` — `GET /connections/{id}/databases`,
  `/databases/{db}/tables`, `/databases/{db}/tables/{t}/columns`, and a
  **batched** `GET /databases/{db}/tables/{t}/samples?n=5` returning
  samples for all columns in one response. One request per column would
  fire ~14 requests just to render `Company` — design the batch endpoint
  now, not in M21.
- **The bug fix.** Today `execution.semantic_type` from the request body
  wins unconditionally over any matched `FieldNormalizationConfig.
  semantic_type` — the profile's own saved type is never read at run time.
  Resolve from `profile.config_for(field_ref)` with the request body as
  override only. Also pass a real `field_ref`
  (`{identity}.{database}.{table}.{column}`) into `build_context` instead
  of a bare column name — `error_policy`, `locale_overrides`, and
  `dictionary_refs` are all silently unapplied today because of this same
  line. One line, three bugs, fixed together with a regression test.

**Architectural decision:** the mappings table and `FieldNormalizationConfig`
inside a versioned profile become two sources of truth. Resolution: the
mappings table is the UI-facing editable surface; at run start, a profile
version is materialized from the mappings. Profiles are not bypassed —
`run.profile_version` is load-bearing for cache keys, A/B compare, and the
§134 handoff artifact.

**Verify live:** map `Person.fullName→PERSON_NAME`,
`Company.name→COMPANY_NAME`, `Location.country→COUNTRY`,
`Location.zip→POSTCODE`; delete the connection; re-add under a **different
alias** with the same host/port/db → the mappings reappear. Plus a golden
test locking the `error_policy` regression fix.

---

## M17 — Multi-column, chunked, resumable runs

Largest blast radius of the program. Budget accordingly.

**Change `normcore/run.py`** — add `RunColumnSpec(table, column,
semantic_type)`, `columns: tuple[RunColumnSpec, ...]`, and
`RunProgress(total_rows_estimate, rows_done, chunks_done, current_table,
current_column)`. Keep `metrics` as the roll-up so every existing consumer
keeps working unmodified.

**Create**
- `normexec/stream.py` — per `(table, column)`, per chunk: dedupe →
  `DistinctValuePlanner.distinct_value_results` (reuse unchanged) →
  `RunRecorder.record_*` (reuse unchanged) → `sink.write_chunk(...)` →
  persist `(run_id, table, column, chunk_index, last_key)` for
  resumability.
- `normexec/sinks.py` — `RunSink` Protocol (`write_chunk`, `finish`).
  `SidecarRunSink` here; `DestinationRunSink` in M19 — this seam is what
  keeps M19 from reopening the loop.
- `normapi/executor.py` — bounded worker pool (`queue.Queue` + N threads)
  replacing the raw `threading.Thread(daemon=True)` in `store.py`. Plus a
  startup reconciliation pass: any run left RUNNING in Postgres at boot is
  resumed from `run_chunks` or marked FAILED with
  `failure_reason="process restarted"` — the real fix for "stuck RUNNING
  forever."
- Tables `run_columns`, `run_chunks` via M15's migration runner.

**Change**
- `normapi/store.py` — add a `threading.Lock` around `_runs`/`_executions`
  (currently unguarded dicts mutated from daemon threads). Keep the
  existing list-based `execute_run` alive for pasted-values mode so the
  current test suite needs no rewrite.
- `normio/sidecar_store.py` — add a real `column_name` dimension. Column is
  currently smuggled in as `table` (`store.py:562`, `table=field_name`) and
  `find_run_table` returns exactly one pair. Needs `list_run_tables`, path
  `{source_id}/{table}/{column}/{run_id}/part-N.parquet`, and an explicit
  `ALTER TABLE ... ADD COLUMN` in `__init__` — `CREATE TABLE IF NOT
  EXISTS` will not touch an existing catalog file.
- `app.py` + `compose.yaml` — `NORM_CACHE_PATH` defaults to `:memory:` and
  compose doesn't set it, so the persistent cache tier is effectively dead
  today. Turn it on — this is the cross-run dedup speedup, already built,
  currently unused.

**Reuse verbatim:** `DistinctValuePlanner.distinct_value_results` with its
`on_computed` hook, `RunRecorder` (including `snapshot()`, which already
exists specifically for mid-run progress reporting), `NormalizationCache.
get_many/put_many`, `SidecarStore.write_batch`.

**Verify live:** one run over `Person.firstName + Person.lastName +
Company.name`; `GET /runs/{id}` shows monotonically increasing `rows_done`
while RUNNING; kill the API process mid-run, restart it, confirm the run
resumes from `last_key` and finishes with `rows_done` equal to the source
count; memory stays flat throughout.

**Risks:** persistent cache tier at ~8M distinct `Person.fullName` values
may be a net *loss* — bench honestly, consider a per-column cardinality
threshold, disclose in the pack if it doesn't pay. Two workers racing one
`run_id` — the M11 pack already discloses a double-start race; with a pool
it becomes routine, not rare — fix with the lock plus a DB-level unique
claim, then drop the disclosure.

---

## M18 — Multi-column reporting rebuilt on the sidecar

Nine handlers take a `?table=&column=` selector plus a per-run rollup:
errors, values, collisions, profile, handoff, impact, overview, quality,
compare.

**Two must be re-architected, not parameterized:**
- `GET /overview` and `GET /quality` are unbounded **today** — they loop
  every run, hydrate full Parquet result sets, and `compute_overview` then
  calls `compute_impact` over all of it. At multi-million-row scale they
  OOM the API. Rewrite to read a new `run_column_stats` table (rows,
  changed, warnings, errors, status histogram, collision count) written at
  chunk-commit time in M17. They must never touch per-value data again.
- `GET /runs/{id}/values` becomes paginated (`?offset=&limit=`) pushed down
  to DuckDB over Parquet — never `to_pylist()` on a 12M-row table.
- Collisions computed in DuckDB (`GROUP BY comparison HAVING
  count(DISTINCT original) > 1`) over the sidecar rather than Python dicts.
  Keep `find_collisions` for the pasted-values path.

**Reuse:** `compute_impact`, `profile_field`, `build_handoff_artifact`,
`compare_runs` keep their single-column signatures and get called per
`(table, column)` — a fan-out layer above `normanalysis`, not a rewrite of
it.

**Verify live:** a completed 3-column run returns per-column reports plus a
run rollup; `GET /overview` returns in under 500ms with a multi-million-row
run in the store — demonstrate the before/after, since the current
implementation would hang or OOM on the same data.

---

## M19 — Destination writer (new package `packages/normsink/`)

**Create**
- `normsink/destination.py` — `DestinationConnector` Protocol *with* write
  vocabulary (`ensure_database`, `ensure_table`, `insert_batch`,
  `ensure_side_table`, `close`), physically separate from `normio` so
  ADR-013's "sources have no write vocabulary" stays literally true
  (decision 6).
- `normsink/clickhouse.py` — DDL mirroring: source column names and order
  preserved; unmapped columns get the source's exact `system.columns.type`
  string copied verbatim; mapped NUMERIC → `Nullable(Decimal(38,9))`,
  mapped DATE/DATETIME → `Nullable(Date)`/`Nullable(DateTime64(3))`.
  Engine `ReplacingMergeTree` with the same ORDER BY as the source's
  `sorting_key` — this is what makes re-inserts idempotent by
  construction, not by application logic.
- Side table `{table}__normalization_issues`, `ORDER BY (table_name,
  source_row_key, column_name)`, carrying `severity, code, message,
  lossiness, normalization_status, run_id`. Mirrored tables stay exactly
  as wide as the source (decision 8).
- `DestinationRunSink` implementing M17's `RunSink`.
- Self-write refusal: compare destination vs. source `connection_identity`
  → 409. Also block same `host+port` regardless of database, unless the
  request explicitly sets `i_understand_same_server: true` — blocking only
  exact database equality still permits writing into `origin1` on the same
  server as `origin2`, which is the realistic accident.

**Two decisions to make before this milestone starts, not during:**
1. `NormalizedValue` has no typed numeric/temporal field — it's all
   `str | None` plus a free-form `structured: dict[str, Any]`. Extract
   NUMERIC/DATE values from `structured` via an explicit, tested
   per-semantic-type contract (which key, what happens on parse failure)
   rather than adding new typed fields to `NormalizedValue` itself, which
   would ripple into the §107 JSON Schema, the Arrow sidecar schema, and
   every cached `value_json` row.
2. "Byte-identical verbatim" is not achievable via Arrow `large_string` for
   ClickHouse `String` columns, which are byte arrays with no UTF-8
   guarantee. Read `String` columns as `large_binary` for the copy path;
   the claim is "value-identical for valid UTF-8, with a disclosed lossy
   path otherwise," not literally byte-identical in all cases.

**Verify live:** `Location` (1.83M rows) mapped `city→FREE_TEXT`,
`country→COUNTRY`, `zip→POSTCODE` into a real destination database;
`count()` matches source; re-run the same run → count unchanged after
`OPTIMIZE ... FINAL` (proves ReplacingMergeTree idempotency); destination
pointed at the source database → 409.

---

## M20 — Incremental watermark + full resync

`source_watermarks` table: `(connection_identity, database, table_name)` →
`last_created_at, last_run_id, updated_at`. Advance only to the MAX
`created_at` actually committed, and only after a successful chunk commit.

`read_chunk`'s predicate layers `created_at > {watermark}` on top of keyset
pagination. Add `POST /runs` with `mode: "full_resync"`, resetting the
watermark for that `(connection, table)`.

**Two callouts — this is where silent data loss lives:**
1. `Company.created_at` is typed `Nullable(DateTime)`. Verified live: it
   currently holds **0** NULL rows, so this is a latent trap rather than a
   live bug today — but the column type permits NULLs, and any future NULL
   row would become invisible to `created_at > watermark` forever unless
   handled explicitly. Exclude NULLs and surface a
   `rows_skipped_null_watermark` counter in the report rather than leaving
   this implicit.
2. ReplacingMergeTree row *updates* do not bump `created_at`. An updated
   row will never be re-normalized by a `created_at` watermark —
   incremental here means "new rows," not "changed rows." Full resync is
   the only correct answer for updates, and this distinction must be
   visible in the UI, or users will trust stale normalized output
   indefinitely.

**Verify live:** run `Industry` (179 rows) → watermark set; re-run → 0 new
rows; full resync → 179 again. Then a `Company` run proving the NULL-skip
counter fires (using a deliberately inserted NULL-`created_at` test row,
since the real table currently has none).

---

## M21 — 3-step UI, legacy tabs behind ModeContext

**Create** `ui/src/pages/ConnectPage.tsx`, `ExplorePage.tsx`,
`ReportPage.tsx`.

- **Connect:** DB-kind dropdown → default port auto-filled from
  `GET /connection-kinds` → host/user/password → Test → list databases →
  pick one.
- **Explore:** tables → columns with ~5 sample values each (one batched
  samples request per table) → assign semantic type per column → one
  button starts the run.
- **Report:** per-column results, quality metrics, collisions, charts;
  browser `Notification` on completion.

**Change**
- `ui/src/App.tsx` — `/connect`, `/explore`, `/report/:runId` become the
  primary flow; the 15 existing pages move under `/advanced/*`. Routes
  kept, nothing deleted.
- `ui/src/app/Nav.tsx` — render the 3 steps always; render the 11 legacy
  tabs only when `mode !== "normal"`. Reuse `useMode()` from
  `ui/src/app/ModeContext.tsx` completely unchanged — it already has three
  modes and already persists to localStorage (decision 3, zero new
  machinery).
- `ui/src/api/client.ts` — add connection/catalog/mapping/progress
  functions; the existing `request<T>` wrapper and `authStore.ts` already
  handle the API key.

**Reuse:** `QueryState.tsx` for every loading/error/empty state;
`ExplanationPanel.tsx`, `TraceView.tsx`, `lib/explain.ts` in the report
drill-down. Progress via TanStack Query `refetchInterval` while the run is
non-terminal — no WebSockets/SSE; polling is what M11's pack already
documents and verifies.

**Verify live:** a Playwright spec connecting to the real ClickHouse,
browsing `origin2`, mapping 3 columns across 2 tables, starting a run,
polling to completion, and asserting the report renders real counts.

**Callout:** hiding a tab is not the same as keeping it working. Once runs
are multi-column, `RunDetailPage`, `ComparisonPage`, and `CollisionsPage`
render nonsense without a column selector — budget that here, or
explicitly declare the legacy tabs read-only-degraded in the pack.

---

## M22 — One-command startup

**Create** `ui/Dockerfile` (node build → nginx) and `ui/nginx.conf`
proxying `/normalization` and `/health` to the `api` service.

**Change** `compose.yaml` — add the `ui` service; add
`NORM_SOURCES_CONFIG_PATH`, `NORM_CACHE_PATH`, `NORM_SECRET_KEY` to the
`api` env block (none are currently set).

**Callouts:**
- A local `sources.json` pointed at `localhost` will resolve wrong from
  inside a container — needs `host.docker.internal` on Docker Desktop, or
  a compose network name. Document this rather than let it silently fail
  on first `docker compose up`.
- Behind nginx the UI's API base must become relative; the CORS middleware
  stays for `npm run dev` only.

**Verify:** `docker compose up -d` from a clean clone → full 3-step flow
against a real database, no manual setup beyond a `.env` file.

---

## Explicitly out of scope

- No Celery/Redis/Airflow — a worker pool plus Postgres-persisted chunk
  state is sufficient, matching this repo's existing "Starlette's sync
  thread pool + a shared store" posture.
- No RBAC or user accounts — auth stays M11's single shared
  `NORM_API_KEY`.
- No cross-engine destination — enforce with a 409, not a type-translation
  matrix.
- No WebSockets/SSE — poll, matching M11's already-verified pattern.
- No deletion of the 11 legacy tabs; no rewrite of legacy pages beyond a
  column selector where genuinely needed.
- No Mongo/file catalog parity for M14–M16 — ClickHouse fully, Postgres/
  MySQL for catalog, explicit 501 for the rest until asked for.
- No destination schema evolution — if the source gains a column later,
  fail loudly, never auto-`ALTER`.
- No re-normalization of already-written destination rows when a mapping
  changes — that is a full resync, by definition.
- No LLM type detection — `type_detection.py` stays deterministic and
  suggest-only, per §85's existing no-silent-changes rule.

## Where the existing architecture resists this program

| Resistance | Location | Why it hurts |
|---|---|---|
| `SourceConnector` has no catalog/streaming vocabulary by design | `normio/connector.py:1-14` | Adding methods undermines the read-only argument ADR-013 and three packs rest on → separate protocols in M14 |
| `SourceRegistry` eager, immutable, docstring forbids request-body credentials | `normapi/sources.py:1-15` | Decision 2 overturns a deliberate, documented trust boundary → needs ADR-017 + real log/span scrubbing, not a quiet edit |
| Run model single-column, frozen, one aggregate `metrics` | `normcore/run.py` | Decision 5 touches ~9 route handlers and 6 `normanalysis` entry points |
| Analysis functions take `Sequence[NormalizedValue]` | `overview.py`, `quality.py`, `impact.py` | All assume full materialization; at 12M rows they cannot simply be parameterized |
| Sidecar catalog has no `column` dimension | `sidecar_store.py` | DuckDB `CREATE TABLE IF NOT EXISTS` will not add it to an existing file |
| No migrations anywhere | `postgres_store.py`, `sidecar_store.py`, `cache.py` | Six new tables + one schema change across this program |
| `NormalizedValue` has no typed numeric/temporal field | `normcore/models.py` | Decision 7's typed destination columns have no source of truth without M19's explicit extraction contract |

## Top 5 risks, ranked

1. `store.py`'s `int(row["source_row_key"])` sort — verified present in the
   current code; guaranteed crash the moment keys stop being numeric. Must
   land in M14 with the key change, not after.
2. `GET /overview` / `GET /quality` OOM on the first real multi-million-row
   run — they are unbounded today, so this fires the moment M17 ships if
   M18 lags behind it.
3. Typed NUMERIC/DATE destination columns have no contract today — decide
   the extraction approach before M19 starts, not during.
4. Watermark misses in-place row updates, permanently and silently. Full
   resync is the only correct answer; it must be visible in the UI, not
   just documented in a pack.
5. Persistent cache tier at ~8M distinct values may be a net loss — bench
   honestly in M17 and be willing to disable it per-column.

## Verification discipline

Every milestone follows the existing repo pattern: a real
`docs/verification/M{n}-verification-pack.md` with real command output, run
against the live ClickHouse at `localhost:8190` (`origin1`/`origin2`), plus
a `docs/traceability-matrix.md` update. No milestone closes on synthetic
data alone — this program is the first time the engine meets a genuinely
large real dataset, and that is the point of building it this way.
