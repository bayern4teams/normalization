# Throughput/Memory Program — Follow-up Recommendations Verification Pack

**Parent commit:** `aa4af50` (Phase 3 items 2-5)
**Scope:** implementation of the "9 recommendations" the previous session
handed the user as prioritized next steps after Phase 3 items 2-5 landed.
This pack covers the 5 items completed and live-verified this session;
the remaining 4 (real full-scale 11.8M-row run, CI `determinism-replay`
verification via a real push, the `NORM_PARALLEL_WORKERS` production
default decision, and `ScriptNormalizer`'s language/accuracy tradeoff)
require either a real push to a shared branch, an hours-long run against
production-adjacent infrastructure, or product input this session cannot
supply alone — deferred to a separate, explicit decision per this
project's standing rule on sensitive/consequential actions, not silently
skipped.

## 1. What this pack covers (and doesn't)

| # | Recommendation | Done here? |
|---|---|---|
| 1 | `api` service `mem_limit` in `compose.yaml` | Yes |
| 2 | Real full-scale end-to-end run (`Person.fullName`, 11.8M rows) | No — deferred, see §7 |
| 3 | `PYTHONHASHSEED=0` pinning | Yes |
| 4 | CI `determinism-replay` job verification in real GitHub Actions | No — deferred, see §7 |
| 5 | `NORM_PARALLEL_WORKERS` production default decision | No — deferred, see §7 |
| 6 | Native cardinality sampling for Postgres/MySQL | Yes |
| 7 | Remove dead `normalize_batch(pa.Array)` from 19 normalizers | Yes |
| 8 | Documentation debt (`normalization-performance.md`, stale M17 citation) | Yes |
| 9 | `ScriptNormalizer` accuracy/speed tradeoff | No — needs product input, see §7 |

## 2. Item 1 — `api` service memory limit

`compose.yaml`'s `api` service had no `mem_limit` at all while
`NORM_PARALLEL_WORKERS` could spawn a real `ProcessPoolExecutor` fleet —
flagged as a real risk since the original plan (an over-sized worker
count degrades the whole Docker VM instead of failing as a legible
container OOM), and more urgent now that Phase 3's pool is live.

Added `mem_limit: 4g`, sized per the plan's own budget arithmetic: WSL2
VM ~7.8 GB total, minus `libpostal`'s existing `3g`, minus Postgres,
leaves ~4 GB for the api service and its workers. Also corrected the
adjacent `NORM_CACHE_PATH` comment, which cited the M17 pack's retracted
"net loss" finding as its justification — see `compose.yaml`'s new
comment for the corrected reasoning (the operational default stays
`:memory:`, but now for the real, current reason: the cardinality policy
already avoids wasted within-run writes, and a persistent cross-run file
needs a cache-invalidation story this program didn't design, not because
the persistent tier is slow — it measured ~10,286 values/sec post-fix).

## 3. Item 3 — `PYTHONHASHSEED=0` pinning

Pinned in two places, since they're independent code paths:

- `packages/normapi/Dockerfile`: `ENV PYTHONHASHSEED=0` in the runtime
  stage — covers any real deployment where the containerized API spawns
  `DistinctValueWorkerPool` workers via `spawn`.
- `.github/workflows/gate.yml`'s `determinism-replay` job: `normcli run`
  there executes directly on the GitHub Actions runner via `uv run`, not
  inside the built container, so the Dockerfile's `ENV` never reaches it
  — needs its own pin.

This closes a residual risk the plan itself flagged: `spawn` gives each
worker process its own randomized hash seed unless pinned in the
environment before any interpreter starts, so a latent hash-order
dependency in some normalizer (e.g. iterating a `set`) could surface only
under multiple worker processes and never under serial execution or the
existing single-process test suite.

## 4. Item 6 — Native cardinality sampling for Postgres/MySQL

Prior session's cardinality-aware cache policy (Phase 3 item 2) only had
a real `CardinalitySamplingConnector.estimate_distinct_ratio` on
`ClickHouseConnector` (`uniqExact`); Postgres and MySQL relied entirely
on the generic first-chunk-sample fallback. Added a dialect-generic
implementation to `normio/connectors/_sql_base.py`'s shared
`SqlConnectorBase` (used by both `PostgresConnector` and
`MySQLConnector`) — `COUNT(*)` / `COUNT(DISTINCT column)` is standard SQL
via SQLAlchemy Core, so unlike `list_databases`/`_approx_row_count`
elsewhere in that file, this needed **no** dialect branching, matching
the program's own non-negotiable "nothing may be specific to this
database" rule.

**Live verification** — started the previously-unused
`demo-postgres`/`demo-mysql`/`demo-clickhouse` containers
(`COMPOSE_PROFILES=integration docker compose up -d demo-postgres
demo-mysql demo-clickhouse`), waited for all three healthchecks, and ran
a new parametrized test class,
`TestCardinalitySamplingAcrossConnectors`, against all three real
connector kinds in `tests/integration/test_catalog_and_streaming.py`:

```
$ uv run pytest tests/integration/test_catalog_and_streaming.py -m integration -q
.....................................                                    [100%]
37 passed in 14.85s
```

Covers: `isinstance(connector, CardinalitySamplingConnector)` is now true
for all three kinds (previously only ClickHouse); a real all-distinct
column returns ratio `1.0`; a column with a real NULL row excludes it
from both numerator and denominator correctly; an unknown column raises
`ValueError` with the same message shape as the ClickHouse
implementation.

## 5. Item 7 — Dead `normalize_batch` removal

Confirmed (again, independently of the prior session's finding) that
`normalize_batch(values: pa.Array, ctx) -> pa.StructArray` — required by
the `Normalizer` Protocol and implemented identically by all 19
normalizers (`results = [self.normalize(v, ctx) for v in
values.to_pylist()]` then repacked into a 4-field `pa.StructArray`) — was
never called by anything in the real execution path.
`DistinctValueWorkerPool.normalize_batch` (`normexec/parallel.py`) is a
separate, coincidentally-same-named method that calls
`dispatcher.normalize()` per value inside each worker process, not
`Normalizer.normalize_batch`; confirmed by reading its body before
removing anything.

Removed:
- The method requirement from `Normalizer` (`normcore/interfaces.py`),
  with a docstring note explaining the removal and pointing to the real
  batch path (`BatchCapableNormalizer.normalize_many`).
- All 19 implementations, via a scripted regex removal (verified against
  every file's exact body first — all 19 were textually identical modulo
  two files' internal variable names) plus the now-unused `import
  pyarrow as pa` line each file only needed for that method's type hints.
- The corresponding `TestBatch`/`TestBatchAndInverse` test classes/methods
  in 8 test files (kept `TestInverse` where a class had both an inverse
  test and a batch test), 3 dead stub `normalize_batch` methods on test
  doubles in `test_dispatch.py`/`test_run_execution.py`, and fixed 2
  stale comments that cited `normalize_batch` as the reason a `pyarrow`
  import-order guard exists (`test_trace_duration_guard.py`,
  `test_run_execution.py`) — the guard itself is still needed (other
  modules transitively import pyarrow), only the specific example was
  stale.
- Corrected `docs/normalization-architecture.md`'s §5 `Normalizer`
  Protocol code block, which still showed `normalize_batch` as part of
  the live interface.

**Verification:**

```
$ uv run ruff check packages/normalizers packages/normcore <touched test files>
All checks passed!

$ uv run mypy packages/normalizers packages/normcore
Success: no issues found in 36 source files

$ uv run pytest <11 touched unit test files> -m unit -q
313 passed, 1 warning in 63.02s
```

Full-suite confirmation after all 5 completed items combined (§6).

## 6. Item 8 — Documentation debt

- **`docs/normalization-performance.md` created.** Referenced from
  `docs/normalization-architecture.md` since M8 as "(populated in M8)"
  but never written. Summarizes the whole throughput/memory program
  (Phases 0-3) with links to every real pack, so a future reader has one
  entry point instead of needing to know the program existed.
- **`docs/verification/M17-verification-pack.md`'s stale §5.3 citation
  fixed.** The pack cited §5.3 (the double-start race note) as the reason
  `chunk_size` was tuned 50,000 → 3,000; §5.3 is unrelated. Added a
  correction blockquote (not a silent edit) giving the most likely real
  reason found by this program — the Phase 1 O(n²) `cache.py` defect,
  which only manifests at scale with many cache misses, exactly the shape
  of the original hang this program was triggered by — while being
  explicit that this is a plausible reconstruction, not a re-derivation
  of a decision whose original reasoning was never recorded.
- **`docs/normalization-architecture.md`'s stale doc-index annotation
  fixed** ("(populated in M8)" → the real date/reason).

## 7. Deliberately not done this session, and why

- **Item 2 (real `Person.fullName`, 11.8M-row, full-registry end-to-end
  run):** genuinely the biggest gap between "verified" and "claimed" in
  this whole program, but a real run at that scale is estimated at
  ~75 minutes (Phase 3's own projection table) against production-adjacent
  ClickHouse — a resource/time commitment, not a quick check. Deferred to
  an explicit go-ahead rather than started unilaterally.
- **Item 4 (verifying `gate.yml`'s `determinism-replay` job actually runs
  green in real GitHub Actions):** requires pushing to a branch that
  triggers CI — pushing code is a shared-state action this project's
  standing rules require confirming first, not something to do as a side
  effect of a recommendations pass.
- **Item 5 (`NORM_PARALLEL_WORKERS` production default):** a real
  resource-usage tradeoff for whoever runs this in production, not an
  engineering decision to make unilaterally. Recorded as still open in
  `docs/normalization-performance.md`'s §10 and left off by default,
  unchanged.
- **Item 9 (`ScriptNormalizer` accuracy/speed):** every available lever
  (lingua's low-accuracy mode, restricting `from_all_languages()` to an
  expected subset) changes real classification *output* for ambiguous
  text — this needs a product decision on expected languages before any
  code changes, which this session cannot supply on its own.

## 8. Full-suite confirmation

```
$ uv run ruff check .
All checks passed!

$ uv run mypy packages
Success: no issues found in 109 source files

$ uv run pytest -m "unit or golden or property or contract" -q
1154 passed, 10 skipped, 138 deselected, 1 warning in 254.75s (0:04:14)
```

(1154 vs. the prior session's 1162 checkpoint: -8, matching the 8 removed
`normalize_batch`-specific test methods from item 7; no new failures.)

## Human Sign-off

milestone: throughput-memory-program-followup-recommendations
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |
