# Throughput/Memory Program — Phase 0 Verification Pack

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

Phase 0 of the throughput/memory program (`C:\Users\rezas\.claude\plans\humming-frolicking-shore.md`,
approved 2026-08-29) — the "make performance measurable before optimizing
anything" phase. Its own rationale: neither of `gate.yml`'s performance
gates (`normcli bench-compare`, `normcli run`/`normcli diff --require-identical`)
had ever actually run, since neither command existed in `normcli/cli.py`
before this phase. Optimization work in later phases would otherwise be
entirely unguarded.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `normcli bench-compare` — throughput/p95 regression gate against a baseline | ✅ Done, live-verified (pass + fail cases) |
| `normcli run` / `normcli diff --require-identical` — the ADR-014 byte-identical determinism gate | ✅ Done, live-verified against real demo-postgres (pass + fail cases) |
| `TraceStep.duration_us` determinism guard | ✅ Done, live-verified across 23 semantic types |
| Real-scale benchmarks (617/100k and 97k/100k distinct shapes) | ✅ Done, live-verified — the 97k case reproduces the O(n²) defect live |
| `psutil` dev dependency | ✅ Added, importable |
| Committed `tests/bench/baseline.json` | ✅ Done, generated on this machine, self-compares PASSED |

## 2. Layer 1 — Automated verification results

Run fresh, in this session, against the Phase 0 working diff:

```
uv run ruff check .                    -> All checks passed!
uv run mypy packages tests             -> Success: no issues found in 191 source files
uv run pytest -m "unit or golden or property or contract" -q
  -> (see §3 below — full-suite confirmation)
```

## 3. `normcli bench-compare` — live verification

Implementation: `packages/normcli/src/normcli/bench_compare.py`. Compares
two `pytest-benchmark --benchmark-json` files by `fullname`; throughput
regression from `stats.ops`, p95 regression computed from `stats.data`
(nearest-rank percentile over real per-round timings, not `stats.mean`).
New-in-current and only-in-baseline benchmarks are reported, never fail
the gate.

Unit tests: `tests/unit/test_normcli.py::TestBenchCompare`,
`::TestRunBenchCompareExitCodes` — 16 tests, all passing (see §6).

Live CLI smoke test, run against this repo's own real benchmark output
(not synthetic fixtures):

```
$ uv run python -m normcli bench-compare --current bench_sample.json --baseline bench_baseline_copy.json \
    --max-throughput-regression 0.10 --max-p95-regression 0.15
bench-compare: OK test_bench_execute_run_10000_rows_100_distinct_no_cache — throughput 30.1 -> 30.1 ops/s (+0.0%, limit 10%), p95 41.474ms -> 41.474ms (+0.0%, limit 15%)
... (4/4 benchmarks)
bench-compare: PASSED — 4/4 benchmarks within regression limits
exit=0
```

Deliberately regressed one benchmark 2x slower (50% throughput drop, 2x
p95) and re-ran:

```
bench-compare: REGRESSION test_bench_execute_run_10000_rows_100_distinct_no_cache — throughput 30.1 -> 15.0 ops/s (+50.0%, limit 10%), p95 41.474ms -> 82.947ms (+100.0%, limit 15%)
... (3/4 OK)
bench-compare: FAILED — 3/4 benchmarks within regression limits
exit=1
```

Both the pass and fail paths are proven against real command output, not
just unit-test assertions.

## 4. `normcli run` / `normcli diff --require-identical` — live verification

Implementation: `packages/normcli/src/normcli/run_cmd.py` (executes a
profile against a source via `normexec.stream.stream_column` directly —
no FastAPI/HTTP/DB-registry involvement, confirmed feasible by dedicated
research before implementation), `packages/normcli/src/normcli/diff_cmd.py`
(compares decoded Parquet row content + `run_report.json`, excluding the
inherently time-varying fields by name: `id`, `started_at`, `finished_at`,
and every `metrics.*_latency_ms`/`duration_seconds`/`rows_per_second`),
`packages/normcli/src/normcli/demo_fixture.py` (defines the "demo"
profile / "demo_pg" source `gate.yml` has always assumed existed but
never did), `packages/normcli/src/normcli/registry.py` (the real
20-normalizer registry + env_id computation, mirroring `normapi.app`
without pulling in FastAPI).

A real DLL-load-order segfault was found and fixed during implementation:
`diff_cmd.py` imported `pyarrow.parquet` without importing `icu` first,
and `cli.py` imported it before `run_cmd.py` (which did have the guard)
— `python -m normcli --help` segfaulted (exit 139) until fixed. Now
guarded in every module that imports pyarrow directly.

Live verification against a real `demo-postgres` container
(`COMPOSE_PROFILES=integration docker compose up -d demo-postgres`,
started and stopped for this verification only, per user confirmation):

```
$ uv run python -m normcli run --profile demo --source demo_pg --out run1
run: COMPLETED — 9 rows written to .../run1
$ uv run python -m normcli run --profile demo --source demo_pg --out run2
run: COMPLETED — 9 rows written to .../run2
$ uv run python -m normcli diff run1 run2 --require-identical
diff: IDENTICAL
exit=0
```

Two genuinely independent `run_normalization()` calls (separate output
directories, separate default run_id per call — `diff` deliberately does
not require the two runs to share a run_id) against the real seeded
`customers` table (3 rows x 3 profiled columns = 9) produced
content-identical output.

Negative case — mutated one real output row's `display` field after a
real run, confirmed `diff` catches it:

```
$ uv run python -m normcli diff run1 run2 --require-identical
diff: MISMATCH demo_pg.customers.first_name: row '1' differs
diff: DIFFERENT
exit=1
```

And confirmed `--require-identical` is what gates the exit code (report
without it stays exit 0 even with a real difference present):

```
$ uv run python -m normcli diff run1 run2
diff: MISMATCH demo_pg.customers.first_name: row '1' differs
diff: DIFFERENT
exit=0
```

`tests/integration/test_normcli_run_diff.py` (4 tests, all passing, run
live against the same container) makes this repeatable: two direct
`run_normalization()` calls proving content-identical output, a real
mutation-detection test, a real bad-column failure-path test (asserts
both the raised exception and the `run_report.json`'s recorded
`failure_reason`), and a full subprocess-based run of the exact
`gate.yml` scenario (`normcli run` x2 + `normcli diff --require-identical`
as three separate OS processes, not warm in-process calls — the stronger
claim ADR-014 actually makes).

```
$ uv run pytest tests/integration/test_normcli_run_diff.py -m integration -q
....
4 passed in 65.89s
```

## 5. `TraceStep.duration_us` determinism guard

`tests/unit/test_trace_duration_guard.py` — builds the real 20-normalizer
registry (via the new `normcli.registry.build_normalizer_registry`, no
live libpostal needed since ADDRESS is excluded — same exclusion `M4`'s
golden corpus already requires) and normalizes one representative sample
value per semantic type (23 of 24 — `ADDRESS` excluded and covered
separately by `tests/golden/test_m4_corpus.py`), asserting every
resulting `TraceStep.duration_us is None`.

```
$ uv run pytest tests/unit/test_trace_duration_guard.py -q
........................
24 passed in 40.64s
```

## 6. Real-scale cardinality benchmarks — live measurement

`tests/bench/test_real_scale_cardinality_benchmark.py` — the shapes the
plan's own cardinality table names, at a CI-runnable row count (existing
benchmarks only ever exercised 100 distinct / 10,000 rows, a ratio that
cannot reveal any of the plan's four algorithmic defects).

Low cardinality (Location.country's real 0.03%-distinct ratio, scaled to
100k rows) — confirms the cheap path stays cheap:

```
$ uv run pytest tests/bench/test_real_scale_cardinality_benchmark.py::test_real_scale_low_cardinality_617_distinct_100k_rows -m bench -q -s
[real-scale-bench] low-cardinality: 617 distinct / 100000 rows — cold=0.31s (321204 rows/s), warm=0.19s (534634 rows/s)
1 passed in 7.72s
```

High cardinality (Company.name's real 97.1%-distinct ratio, scaled to
100k rows) — **live, first-hand reproduction of the O(n²) defect this
whole program exists to fix**, not just a citation of the earlier
extrapolation:

```
$ uv run pytest tests/bench/test_real_scale_cardinality_benchmark.py::test_real_scale_high_cardinality_97k_distinct_100k_rows -m bench -q -s
[real-scale-bench] high-cardinality: 97000 distinct / 100000 rows — cold=113.43s (882 rows/s), warm=27.63s (3619 rows/s)
1 passed in 148.17s
```

113.43s for a single 100k-row chunk at this cardinality, vs. 0.31s at
617-distinct — a ~366x difference in wall time for an 11.5x increase in
distinct-value count, consistent with `packages/normexec/src/normexec/cache.py:218`'s
O(n²) list-membership scan (not yet fixed — that is Phase 1's job; this
number is the real "before"). The measured cold time is lower than the
plan's naive n=97,000 extrapolation (~169s) because the in-process LRU
tier (50,000-entry capacity) absorbs roughly half the misses before the
DuckDB tier's O(n²) scan ever runs — a real, useful correction to the
plan's own estimate, found by actually running it rather than trusting
the extrapolation.

Both benchmarks use manual `time.perf_counter()` timing (not
`pytest-benchmark`'s `benchmark()` fixture), matching
`test_persistent_cache_benchmark.py`'s established precedent — multi-round
calibration would silently convert "cold" into "mostly warm" after round
1 at this row count, understating the real defect.

## 7. `tests/bench/baseline.json` — committed, self-verified

Generated fresh on this machine from all 6 fixture-based benchmark files
(`test_execution_caching_benchmark.py`, `test_generic_text_benchmark.py`,
`test_identity_normalizers_benchmark.py`, `test_m4_normalizers_benchmark.py`,
`test_m5_normalizers_benchmark.py`, `test_m6_analysis_benchmark.py` — 24
benchmarks total). `test_persistent_cache_benchmark.py` and the new
real-scale benchmarks above deliberately don't use the `benchmark`
fixture (see §6), so they don't appear in this file — consistent with
existing precedent, not an oversight.

```
$ uv run pytest tests/bench/test_execution_caching_benchmark.py tests/bench/test_generic_text_benchmark.py \
    tests/bench/test_identity_normalizers_benchmark.py tests/bench/test_m4_normalizers_benchmark.py \
    tests/bench/test_m5_normalizers_benchmark.py tests/bench/test_m6_analysis_benchmark.py \
    -m bench --benchmark-json=tests/bench/baseline.json -q
24 passed in 42.63s

$ uv run python -m normcli bench-compare --current tests/bench/baseline.json --baseline tests/bench/baseline.json \
    --max-throughput-regression 0.10 --max-p95-regression 0.15
bench-compare: PASSED — 24/24 benchmarks within regression limits
```

`release.yml` previously only ever wrote this file as a release
artifact, never back into the repo — this is the first time it has
existed as a committed file, closing the gap `gate.yml`'s `benchmarks`
job has silently depended on since it was written.

## 8. `psutil` dependency

Added to `[project.optional-dependencies].dev` in `pyproject.toml`,
`uv sync --all-extras` confirmed installable (`psutil==6.1.1` resolved,
`7.1.3` importable in this venv). No RSS sampler wired into a benchmark
yet — that is Phase 3's own prerequisite (measuring per-worker process
memory before sizing a process pool), not needed by anything in Phase 0
itself.

## 9. Full test-suite confirmation

```
$ uv run pytest -m "unit or golden or property or contract" -q
1083 passed, 12 skipped, 124 deselected, 1 warning in 298.98s (0:04:58)
```

No regressions from Phase 0's changes. The 12 skips and 1 warning
(`starlette.testclient`/`httpx` deprecation notice) are pre-existing and
unrelated to this phase.

## 10. Not yet done (explicitly out of Phase 0's scope)

- Phase 1's four algorithmic defect fixes (`cache.py`'s O(n²), `context_hash`
  memoization, `postcode_validation.py`'s `lru_cache`, `run_recorder.py`'s
  double-snapshot + unbounded latency list) — next.
- Documentation debt corrections (the retracted M17 cache finding still
  stated as fact in `M17-verification-pack.md`/`M22-verification-pack.md`)
  — deferred to land alongside Phase 1's real before/after numbers for
  that same cache, rather than corrected twice.
- A general profile-file-loading mechanism — `normcli run` only resolves
  the literal names `"demo"`/`"demo_pg"` today (see `demo_fixture.py`'s
  own docstring); this was explicitly out of scope for a gate command
  that only ever needs to run `gate.yml`'s one named scenario.

## Human Sign-off

**Verdict:**
**Reviewer:**
**Date:**
