# Milestone M10 Verification Pack — Profile-Driven Config + DB Connectors Wired Into the Live API

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

M10 followed the already-approved M9-M12 follow-on plan's own scope for
this milestone: (1) profile-driven config actually affecting live
normalizer behavior (closing a gap disclosed since M2), and (2)
`normio`'s DB/file connectors wired into the live API (closing the
single biggest gap between "the engine works" and "it's part of a
pipeline"). Both deliverables were scoped up front via three explicit
design questions put to the user before implementation — see §1.1.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `NormalizationProfile.locale_policy`/field `locale_overrides`/`dictionary_refs`/`error_policy` actually threaded into the `NormalizationContext` a run's `Dispatcher.normalize()` call uses | ✅ Done |
| `normio` DB/file connectors (Postgres, MySQL, MongoDB, ClickHouse, file) reachable from `POST /normalization/runs` via a new `source` execution mode | ✅ Done — all 5 connector types |
| `GET /normalization/sources`, `GET /normalization/sources/{id}/tables` | ✅ Done |
| Gate G10 verification | ✅ Done |

### 1.1 Design decisions, confirmed with the user before implementation

Three real forks needed a decision before any route could be written;
all three were put to the user explicitly and confirmed:

1. **Execution model**: synchronous, row-capped (default 10,000 rows,
   max 100,000/request) — reusing today's `execute_run` path unchanged
   underneath, rather than waiting for M11's dedicated async/batch
   milestone. M11 can convert this same code path to async/chunked
   without discarding it.
2. **Credentials**: a server-side named source registry
   (`NORM_SOURCES_CONFIG_PATH`, a JSON file of `source_id -> connector
   spec`), never a client-supplied DSN in a request body — the same
   trust boundary `NORM_PG_DSN`/`NORM_SIDECAR_*` already draw.
3. **Connector scope**: all 5 connector types, not a subset — they
   already share one `SourceConnector` protocol, so the API-level code
   is identical either way; skipping some would only reduce test
   coverage, not implementation effort.

## 2. Layer 1 — Automated verification results

```
uv run ruff check .          -> All checks passed!
uv run ruff format --check . -> 192 files already formatted
uv run mypy packages         -> Success: no issues found in 83 source files
uv run mypy tests            -> Success: no issues found in 63 source files
uv run python -m normcli check-traceability
  -> PASSED — all 138 Source.txt sections present in the matrix
uv run pytest -m "unit or golden or property or contract" -q
  -> 828 passed, 12 skipped, 58 deselected
uv run pytest -m integration -q   (all 6 real services up: postgres,
  libpostal, demo-postgres, demo-mysql, demo-mongo, demo-clickhouse)
  -> 34 passed, 0 skipped, 0 failed
uv run pytest -m "unit or golden or property or contract or integration" -q
  -> 864 passed, 10 skipped, 24 deselected, 0 failed
```

New this milestone:
- `tests/unit/test_normcore_profile_and_run.py::TestBuildContext` (8
  tests) — `NormalizationProfile.build_context`'s locale-layering,
  dictionary_refs, and error_policy-resolution rules in isolation.
- `tests/golden/test_m10_corpus.py` (3 tests) — real behavior change
  through the live API: the genuinely ambiguous date `"03/04/2024"`
  resolves to `2024-03-04` (MDY) under a US-locale profile and
  `2024-04-03` (DMY) under a GB-locale profile, zero `DateNormalizer`
  code touched; field-level override winning over profile-wide policy;
  and the pre-M10 no-locale-policy fallback still holding (no
  regression).
- `tests/unit/test_sources.py` (14 tests) — `SourceRegistry` config
  parsing/error paths and real `read_column_values` round-trips through
  a local `FileConnector` (no docker needed).
- `tests/golden/test_m10_source_execution.py` (9 tests) — the `/sources`
  routes and `source`-mode run execution through the live API against a
  real local CSV, including the `values`/`source` mutual-exclusivity
  validator (422 on both-or-neither) and 404/400 error mapping for
  unknown source_id/table.
- `tests/integration/test_run_execution_from_source.py` (7 tests) — the
  same live-API execution path against all 4 real demo-* database
  containers (Postgres, MySQL, MongoDB, ClickHouse), each reading the
  same seeded 3-row `customers` table.

All prior-milestone suites unchanged and still fully passing.

## 3. Layer 2 — Live verification

### 3.1 Profile-driven config, live

Proven via `tests/golden/test_m10_corpus.py` against the real running
API (not a bare function call): the same ambiguous date string produces
different real `NormalizedValue.display` output purely from which
profile executed the run —

```
US-locale profile ("03/04/2024") -> display: "2024-03-04"  (MDY)
GB-locale profile ("03/04/2024") -> display: "2024-04-03"  (DMY)
```

with zero changes to `DateNormalizer` itself — the fix was entirely in
what context a run's execution actually builds.

### 3.2 DB-connector wiring, live — a real process, real containers, real data

Not simulated: started a real `uvicorn` process with
`NORM_SOURCES_CONFIG_PATH` pointed at a real JSON file registering
`demo_pg` against the real `demo-postgres` container (real
`readonly_user` credentials, the same ones
`tests/integration/test_readonly_connectors.py` uses), created a
profile through the live HTTP API, and executed a run with
`"source": {"source_id": "demo_pg", "table": "customers", "column":
"first_name"}` instead of pasted `values`:

```
POST /normalization/runs?profile_id=...&source_snapshot=live-source-snap
  -> 201, status COMPLETED, metrics.records_processed: 3
GET /normalization/runs/{id}/values
  -> real per-value results for "  John  ", "José", "JOHN" — the exact
     seeded rows in demo-postgres, whitespace preserved verbatim
```

The full integration suite was then run with all 6 real services
simultaneously healthy (`postgres`, `libpostal`, `demo-postgres`,
`demo-mysql`, `demo-mongo`, `demo-clickhouse`) — `34 passed, 0 skipped,
0 failed`, including the same source-execution path against MySQL,
MongoDB, and ClickHouse (`tests/integration/test_run_execution_from_source.py`).

## 4. Disclosed scope boundaries

1. **Synchronous only, row-capped.** A `source`-mode run reads at most
   `row_limit` rows (default 10,000, hard ceiling 100,000) inside one
   HTTP request/response cycle. There is no async/chunked/streaming
   execution path yet — a table larger than the cap is simply truncated
   to the cap, not paginated across multiple runs. This is the
   confirmed, deliberate scope boundary from §1.1's design decision; M11
   is expected to convert this same code path to async/chunked
   execution rather than replace it.
2. **Value coercion is `str(...)`, not type-aware.** A source column's
   real value (int, float, timestamp, ...) is stringified with Python's
   own `str()` before normalization, since `execute_run` normalizes
   `str | None` — the same contract pasted `values` already use. This is
   a reasonable default for a first wiring, not a type-system-aware
   ingestion layer; a caller wanting different coercion (e.g. locale-
   aware date formatting before stringification) has no hook for it yet.
3. **No lifespan cleanup for source connections.** `SourceRegistry`'s
   connectors are constructed eagerly at app startup and never
   explicitly closed on shutdown — matching every other resource this
   app already holds this way (`PostgresMetadataStore`, `SidecarStore`'s
   DuckDB connection); adding cleanup only for sources while every other
   resource lacks it would be inconsistent, not a real improvement, so
   it was left alone rather than half-fixed.
4. **Per-field pipeline STEP ORDERING remains not wired** (carried
   since M2, disclosed in every prior pack and in `RulesPage`'s own UI
   copy) — each normalizer's internal step sequence is still hardcoded
   Python logic, not data-driven from a profile's `NormalizationStep`
   list. What M10 actually wires (locale/dictionary/error-policy) is a
   different, narrower slice of "profile-driven config" than step
   reordering.
5. **Demo source containers are not part of the deployed `api`
   service's compose config.** `compose.yaml`'s `demo-*` services are
   explicitly commented "integration tests / spikes only"; the real
   `api` service was deliberately NOT wired to `NORM_SOURCES_CONFIG_PATH`
   by default, to keep that documented boundary between "real deployed
   stack" and "test/spike infrastructure" intact. A real deployment
   configures its own `sources.json` against real production sources.
6. **Mutation coverage (66% vs. the 75% gate)** remains explicitly
   deferred to M12, per the user's own standing instruction — untouched
   this milestone.

## Human Sign-off

milestone: M10
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |
