# Throughput/Memory Program — Phase 3 Verification Pack

Status: **Item 1 (process-pool parallelism) complete and live-verified.
Items 2–5 and the residual-risk items NOT started this pass — see §7.
Ready for your Layer 3 review and sign-off on what's here.**

Phase 3 of the throughput/memory program (`C:\Users\rezas\.claude\plans\humming-frolicking-shore.md`,
approved 2026-08-29) — "break the single-core ceiling." This pass
implements and live-verifies item 1 (process-pool parallelism for
distinct-value normalization, including its stated prerequisite —
`normalizers/script.py`'s lazy lingua fix — and the Phase-0-deferred
psutil worker-memory gate). Two real, load-bearing bugs were found and
fixed via live testing before this could be trusted, both documented
below. Items 2–5 (cardinality-aware cache policy, `NORM_CACHE_PATH`
revisit, the determinism proof against `normcli diff`, and the
deferred-but-recorded wins) are explicitly out of scope for this pass —
see §7.

## 1. Scope recap

| Item | Outcome | Status |
|---|---|---|
| Prerequisite: lazy `normalizers/script.py` language detector | Done, and revealed a far bigger memory cost than the plan estimated | ✅ Done, live-verified |
| Prerequisite: per-worker memory gate (Phase 0's deferred `psutil` sampler) | Built and run for real — clears the plan's own 600MB stop-and-reconsider gate | ✅ Done, live-verified |
| Container-aware CPU/memory quota detection (`normexec.resources`) | cgroup v2 → v1 → host fallback, generic (not ClickHouse-specific) | ✅ Done, unit-tested |
| Process-pool parallelism (`normexec.parallel`, `DistinctValueWorkerPool`) | Built, wired end-to-end into `normapi`, off by default | ✅ Done, live-verified |
| ADDRESS/SCRIPT permanent pool exclusion | Both guarded by tests, for two different real reasons | ✅ Done, tested |
| Runtime break-even calibration (no hardcoded threshold) | Built, and its FIRST design was wrong — found and fixed live (§5) | ✅ Done, live-verified after fix |
| Items 2–5 (cardinality-aware cache, `NORM_CACHE_PATH`, determinism proof, deferred wins) | Not attempted this pass | ⚠️ Deferred, see §7 |

## 2. Layer 1 — Automated verification results

```
uv run ruff check .                    -> All checks passed!
uv run mypy packages tests             -> Success: no issues found in 200 source files
uv run pytest -m "unit or golden or property or contract" -q
  -> see §6 below
```

## 3. Prerequisite — lazy `ScriptNormalizer` language detector, and a much bigger finding than expected

`packages/normalizers/src/normalizers/script.py`'s `_LANGUAGE_DETECTOR =
LanguageDetectorBuilder.from_all_languages().build()` ran at MODULE
scope — every process that imports `normalizers` paid it, whether or not
it ever normalizes a SCRIPT field. Made lazy + lock-guarded
(`_get_language_detector()`, double-checked locking so concurrent first
callers share one real build instead of racing into several), matching
the existing `text_ops._get_spoof_checker` precedent in this same
package. Zero output change — `test_normalize_output_unaffected_by_laziness`
and the golden/corpus suites confirm.

```
$ uv run pytest tests/unit/test_script_lazy_language_detector.py -v
...
6 passed
```

**The real finding**: the plan estimated this would be "the dominant
per-worker memory cost" and hoped it would move worker sizing from
"maybe 4" to "8 comfortably." Measured directly (real 4-process pool,
real spawn, real full 20-normalizer registry, this machine):

```
pid=904   import+registry_build=5950.5ms rss=151.9MB
pid=22444 import+registry_build=5966.1ms rss=152.0MB
pid=18548 import+registry_build=5947.4ms rss=151.3MB
pid=18928 import+registry_build=5993.9ms rss=151.7MB
TOTAL RSS across 4 workers: 606.9MB, avg 151.7MB/worker
```

Then, one worker that additionally normalizes a SINGLE SCRIPT value:

```
rss_before_script_normalize=151.5MB rss_after_script_normalize=1495.6MB delta=1344.2MB
```

**Building `lingua`'s detector costs 1.34 GB, not a modest tax.** A
worker that ever touches ONE SCRIPT value balloons ~10x and stays there
for the pool's entire lifetime (workers are long-lived, reused across
every chunk/column of a run). This is a materially bigger, previously
completely unmeasured cost than the plan's own text anticipated. The
consequence, disclosed and acted on here: **SCRIPT is permanently
excluded from the pool** (§4), for a different reason than ADDRESS's
existing exclusion — not a hypothetical, a real number that would
otherwise threaten the whole container's memory budget the plan already
flags as fragile.

## 4. Container-aware resource detection (`normexec.resources`)

Generic, non-negotiable per the plan: worker count/memory budget must be
read from the real environment, never `os.cpu_count()` directly (which
reports HOST cpus even inside a cgroup-quota-limited container) and never
tuned to this dev machine. `detect_cpu_quota()`/`detect_memory_limit_bytes()`
read cgroup v2 (`cpu.max`/`memory.max`), fall back to cgroup v1
(`cpu.cfs_quota_us`/`cpu.cfs_period_us`, `memory.limit_in_bytes`), fall
back again to the host's own reported limits (`os.cpu_count()`, `psutil`)
when no cgroup applies — the common case on this Windows dev machine,
which is exactly what its own test suite exercises (real temp files
standing in for real cgroup files, not mocked I/O).

```
$ uv run pytest tests/unit/test_resources.py -v
...
12 passed
```

## 5. Process-pool parallelism (`normexec.parallel`) — two real bugs found and fixed via live testing

`DistinctValueWorkerPool` owns one `ProcessPoolExecutor` (always `spawn`,
explicitly — never the platform default `fork`, since PyICU/DuckDB are
not documented fork-after-import-safe and the program's own IPC/RSS
numbers were taken under `spawn`), created once and reused across every
chunk/column of a run. `DistinctValuePlanner` gained an optional `pool`
parameter; `None` (the default) reproduces pre-Phase-3 behavior exactly.

**Bug 1 — real `BrokenProcessPool` crash, same root cause this project
has hit before.** First real pool test run crashed every worker with
`concurrent.futures.process.BrokenProcessPool`. Root cause: `import
normexec.parallel` in a fresh spawned process first initializes the
PARENT package `normexec/__init__.py`, which eagerly imports
`normexec.planner`, which imports `pyarrow` — all before anything in
that fresh process had imported `icu`. The exact PyICU/PyArrow
DLL-load-order segfault this codebase has hit and guarded against
several times before (`normcli/cli.py`, `normapi/main.py`,
`normalizers/__init__.py`), now hit inside a pool worker specifically
because spawn gives each worker a genuinely fresh, nothing-imported-yet
process. Fixed the same way every prior instance was fixed: `import icu`
as the literal first statement in `normexec/__init__.py`, matching
`normalizers/__init__.py`'s existing, explained precedent.

**Bug 2 — the calibration compared the wrong two things, and it
consistently rejected pooling for real data because of it.** The first
design measured a SINGLE-value round trip through the pool and compared
it against the per-value SERIAL duration. Live against real ClickHouse
`Company.name` data (97% distinct — exactly the kind of column the plan
says should benefit most):

```
direct in-process dispatcher.normalize(): 761.4us/call
single-value round trip through the (warm) pool: 3309.8us
```

A single value's round trip will always lose to in-process — of course
it does, it pays real IPC overhead for zero parallelism gain. But the
REAL call `normalize_batch()` makes splits N values across `workers`
CONCURRENT processes, which is a completely different question. Measured
directly:

```
POOL (warm, 4 workers, 2000 values):   0.764s (2616.6 rows/s)
SERIAL (2000 values):                  1.086s (1841.5 rows/s)
warm speedup: 1.42x
```

The first calibration design was answering "is one worker plus IPC worth
it" (always no) instead of "is `workers`-way concurrency worth it"
(often yes). Fixed: calibration now runs a REAL `pool.normalize_batch()`
call on a bounded sample (`min(len(values), 200 * workers)`, capped so a
large first chunk doesn't double its own cost calibrating) and compares
its real wall-clock time against the serial-equivalent cost for the same
sample size — the actual production code path, timed, not a synthetic
proxy for it.

**End-to-end live result, before vs. after the calibration fix, real
`origin2.Company` data, 40,000 rows / 39,793 distinct, 4 chunks of
10,000, 4 workers:**

```
BEFORE fix — pool decided False every time, net loss when forced on:
  SERIAL total:      27.086s  (1476.8 rows/s)
  POOLED(4) total:   28.758s  (1390.9 rows/s)   speedup: 0.94x

AFTER fix — pool correctly decides True after chunk 0's real calibration:
  SERIAL total:      26.636s  (1501.7 rows/s)
  POOLED(4) total:   19.783s  (2021.9 rows/s)   speedup: 1.35x
  (chunks 1-3 alone, decision already made: ~4.2-4.4s pooled vs ~6.5-6.8s serial per chunk)
```

**Correctness/determinism, unaffected by which path is taken** — verified
at two scales:

```
$ uv run pytest tests/unit/test_parallel_pool.py -v
14 passed
  (includes test_pool_normalize_batch_matches_serial_dispatcher_byte_identical,
   test_pool_normalize_batch_preserves_input_order,
   test_planner_with_pool_produces_identical_results_to_planner_without_pool,
   test_planner_never_pools_address_even_with_a_pool_configured,
   test_pool_excludes_address_and_script_permanently)
```

Live, 20,000 real `Company.name` values, serial vs. pooled: **0
mismatches / 20,000** (display, normalization_status, original all
compared).

Results are collected via `future.result()` in submission order, never
`as_completed` — cache-write order and downstream row-join behavior stay
identical to the serial path regardless of which real worker happens to
finish first.

## 6. Wired end-to-end into the live API — off by default

`normapi/registry.py` (new) extracts `create_app()`'s inline
20-normalizer registration into `build_normalizer_registry()` (mirroring
`normcli/registry.py`'s already-existing copy, and its own docstring's
anticipation of exactly this) plus `build_worker_dispatcher()` — a
MODULE-LEVEL, picklable factory `functools.partial`-bound in
`create_app()` and passed to the pool's `spawn`-based initializer (a
closure over `create_app()`'s locals would not be picklable).
`NORM_PARALLEL_WORKERS` (0/unset = off, negative = auto-derive from the
real cgroup CPU quota minus one core of headroom, positive = explicit
override) drives whether `app.state.parallel_pool` is `None` or a real
pool, threaded through `InMemoryStore` → `stream_column` →
`DistinctValuePlanner`. A `lifespan` context manager (not the deprecated
`on_event`) shuts the pool down gracefully on app shutdown.

```
$ uv run pytest tests/unit/test_app_parallel_pool_wiring.py -v
3 passed
  test_parallel_pool_is_none_by_default
  test_parallel_pool_disabled_when_env_var_unset
  test_parallel_pool_is_real_and_functional_when_explicitly_configured
    (real create_app(parallel_workers=1), real 20-normalizer registry
     built inside the worker, real pool.normalize_batch() call)
```

## 7. Full test-suite confirmation

```
$ uv run pytest -m "unit or golden or property or contract" -q
1129 passed, 12 skipped, 124 deselected, 1 warning in 465.27s (0:07:45)
```

Run fresh AFTER the calibration fix (§5's Bug 2), confirming it introduced
no regressions anywhere else — identical result to the checkpoint run
taken before that fix (also 1129 passed), since the fix only changes
which code path a performance decision routes through, never the
computed values themselves. Up from Phase 2's 1095 passed — the +34 is
this phase's own new test files (`test_script_lazy_language_detector.py`,
`test_resources.py`, `test_parallel_pool.py`,
`test_app_parallel_pool_wiring.py`). Zero failures, zero new skips.

## 8. Not yet done — explicitly out of scope for this pass

- **Item 2, cardinality-aware cache policy** — sample distinctness per
  column at run start, skip the persistent DuckDB tier above a threshold.
  Not started.
- **Item 3, `NORM_CACHE_PATH` revisit** — depends on item 2's policy
  existing first. Not started.
- **Item 4, the determinism proof** — a real `normcli run` ×2 +
  `normcli diff --require-identical` pass with the pool ENABLED, proving
  parallel execution is byte-identical to serial at the full-run level
  (not just the unit/live-column level already verified in §5). Needs
  `demo-postgres` up, which needs your go-ahead per standing instruction
  before starting any Docker container.
- **Item 5, deferred-but-recorded wins** — `AddressNormalizer` real HTTP
  batching, `ScriptNormalizer`'s 9,304 µs/value cost, and the
  `normalize_batch`/ADR-016 reality gap. Untouched, as the plan itself
  says not to attempt without a separate decision.
- **Residual risk: `PYTHONHASHSEED=0`** — not pinned in the API image/CI
  yet. Matters more now that pool workers are a real, if off-by-default,
  code path (`spawn` gives each worker a different `PYTHONHASHSEED`
  unless pinned).
- **Residual risk: workers returning serialized Arrow rows instead of
  `NormalizedValue` objects** — the plan's own suggested further
  optimization to raise the IPC ceiling (moving `json.dumps`/pydantic
  reconstruction into the worker). This pass's workers return full
  `NormalizedValue` objects — simpler, safer, and still delivered a real
  measured 1.35x — deliberately not attempted, to keep this pass's blast
  radius to the process-pool plumbing itself rather than also touching
  the cache/stream-write contract every downstream consumer relies on.
- **Documentation debt** (M17/M22 pack retractions, ADR-016 batch-API
  correction) — still deferred, as disclosed in Phases 1 and 2.

## Human Sign-off

**Verdict:**
**Reviewer:**
**Date:**
