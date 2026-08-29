# Throughput/Memory Program — Phase 2 Verification Pack

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

Phase 2 of the throughput/memory program (`C:\Users\rezas\.claude\plans\humming-frolicking-shore.md`,
approved 2026-08-29) — "stop doing per-row what is per-distinct-value."
Three of the plan's four items landed as designed; the fourth was
investigated against real infrastructure and found not to apply at
realistic scale — documented below rather than implemented as a no-op,
consistent with this project's verification-rigor discipline.

## 1. Scope recap

| Item | Outcome | Status |
|---|---|---|
| `stream.py` per-row Arrow serialization | Memoized `normalized_value_to_arrow_row` on `id(result)` | ✅ Done, live-verified |
| `dispatch.py` double `NormalizedValue` construction | Stamp fields directly on the existing object instead of `model_copy` | ✅ Done, live-verified (~3.6x on the isolated step; safer than the plan's literal suggestion) |
| ClickHouse per-chunk metadata round trips | Cache `list_tables()`/`list_columns()` per connector instance | ✅ Done |
| `combine_chunks()` skip when single-chunk | **Investigated, not implemented** — real `query_arrow()` at the actual 100k-row chunk size returns 14 chunks, not 1; the plan's premise does not hold | ⚠️ Deviation, documented in §5 |

## 2. Layer 1 — Automated verification results

```
uv run ruff check .                    -> All checks passed!
uv run mypy packages tests             -> Success: no issues found in 193 source files
uv run pytest -m "unit or golden or property or contract" -q
  -> (see §6 below — full-suite confirmation, all Phase 2 changes combined)
```

## 3. `stream.py` per-row memoization — live verification

`packages/normexec/src/normexec/stream.py`'s `_results_to_batch` called
`normalized_value_to_arrow_row` once per ROW, even though duplicate rows
share the SAME `NormalizedValue` object by reference —
`DistinctValuePlanner.normalize_values` (`planner.py:174`) resolves
every row back from its distinct-value dedup, confirmed by direct
reading of that code. Memoized on `id(result)`, safe because `results`
(the function's own parameter) holds a live reference to every object
for the whole call, so no id can be reused mid-build.

New test file `tests/unit/test_stream_batch_memoization.py` (3 tests,
all passing): proves the memoization actually skips redundant
recomputation (monkeypatched call counter: 5 rows, 2 distinct objects,
exactly 2 real calls), proves output is byte-identical to serializing
every row fresh, and proves two distinct objects with equal content are
never conflated (memoized on identity, not value equality).

Live verification: `tests/integration/test_stream_column.py` (3 tests,
all passing, live against the real `origin2` ClickHouse at
`localhost:8190`) exercises `_results_to_batch` through the real
`stream_column` chunk loop, `chunk_size=50` forcing multiple chunks —
this is the code path the fix targets, run for real, not simulated.

```
$ uv run pytest tests/unit/test_stream_batch_memoization.py -q
...
3 passed in 1.22s
$ uv run pytest tests/integration/test_stream_column.py -m integration -q
...
3 passed in 14.89s
```

## 4. `dispatch.py` double-construction fix — live verification

The plan's literal suggestion ("have normalizers receive
profile_version/env_id... so only one model is built") would require
changing the `Normalizer` Protocol and every one of its 20
implementations' every `NormalizedValue` construction call site (boolean.py
alone has at least 2) — a wide blast radius for a measured 3.81 µs/value
win, the smallest of any defect in this program.

**Chose a narrower fix with the same effect and far less risk**: found
that `NormalizedValue` (unlike most domain models in this codebase) is
NOT `frozen=True` — confirmed by grepping `models.py` for
`model_config` (no match). `packages/normcore/src/normcore/dispatch.py`'s
`Dispatcher.normalize()` now stamps `profile_version`/`env_id` directly
onto the already-constructed object (`result.profile_version = ...`)
instead of `result.model_copy(update={...})`, which built a second
object. The `context_hash` mismatch assertion (a real correctness check,
per the plan) is unchanged. Only `dispatch.py` changed — zero changes to
the `Normalizer` Protocol or any of the 20 normalizer files.

`tests/unit/test_dispatch.py` (10 tests, all passing, unchanged) —
proves this is observably identical to the old `model_copy` behavior.

Real measurement, isolating exactly what changed (the dispatcher's own
post-processing step, given an already-constructed object):

```
$ uv run python -c "..."
OLD (model_copy, second object built): 3.404 us/call
NEW (direct stamp, same object): 0.949 us/call
speedup: 3.59x
```

Also confirmed the returned object is still safely usable by every other
caller exactly as before (this is a targeted, single-call-site change,
not a change to `NormalizedValue`'s general mutability posture, which
was already unrestricted before this phase).

## 5. ClickHouse metadata caching — done; `combine_chunks()` skip — investigated, not implemented

**Metadata caching** (`packages/normio/src/normio/connectors/clickhouse.py`):
`read_chunk` validated its `table`/`columns` arguments against
`list_tables()`/`list_columns()` on every chunk — up to 2 real
`system.tables`/`system.columns` round trips per chunk, for schema that
cannot change mid-run (a connector instance is per-run). Cached per
instance (`self._table_names_cache`, `self._columns_cache`), invalidated
never, matching `postcode_validation.py`'s Phase 1 pattern.
`list_tables()` returns a fresh list copy each call (preserving the
pre-existing "callers may mutate their own copy" contract);
`list_columns()` returns the cached tuple directly (`ColumnSpec` is a
frozen dataclass, safe to share).

```
uv run ruff check packages/normio/src/normio/connectors/clickhouse.py  -> All checks passed!
uv run mypy packages/normio                                            -> Success: no issues found in 12 source files
```

Live verification came from `tests/integration/test_stream_column.py`
(§3 above) — its `chunk_size=50` test issues many `read_chunk` calls
against the same connector instance, exercising this exact caching path
across chunks, and passed.

`tests/integration/test_catalog_and_streaming.py` (the test file that
most directly targets `ClickHouseConnector`'s catalog methods, including
a dedicated concurrency regression test) was attempted but requires the
`demo-clickhouse`/`demo-postgres`/`demo-mysql` containers (port 8124 for
ClickHouse specifically) — not brought up this phase. All 23 failures
are `WinError 10061` / connection-refused on those specific ports, with
zero evidence of a logic error in the caching change itself; this is an
infrastructure-availability gap in this phase's verification, not a
defect, and is recorded honestly rather than glossed over.

**`combine_chunks()` skip — investigated against real data, not
implemented.** The plan's premise: "`combine_chunks()` copies the entire
batch; skip when the table already has a single chunk." Tested directly
against the real, already-running ClickHouse (`origin2`, `localhost:8190`,
the same instance `test_stream_column.py` uses):

```
$ uv run python -c "..."
limit=1000: num_rows=1000, num_chunks(col0)=1
limit=100000: num_rows=100000, num_chunks(col0)=14
combine_chunks on REAL query_arrow result (100k rows): 31823.79 us/call
skip-if-single-chunk on REAL query_arrow result: 30358.21 us/call
```

At `stream_column`'s actual default `chunk_size=100_000`,
`clickhouse_connect`'s `query_arrow()` returns **14 chunks, not 1** — so
`combine_chunks()` is doing real, necessary work (31.8ms) to produce one
combined batch, not wasted work on an already-single-chunk table. A
"skip when single-chunk" guard would never trigger at this realistic
scale (confirmed: both measurements above still pay the real
`combine_chunks()` cost, ~31-32ms either way) and would be pure added
code complexity for zero measured benefit. Separately confirmed pyarrow
itself already short-circuits `combine_chunks()` into a near-no-op
(2.19 µs) when a table genuinely is already single-chunked, so even the
degenerate small-chunk case this guard would help is a case pyarrow
already handles efficiently on its own.

This is a real, if secondary, finding worth flagging forward: 31.8ms of
real `combine_chunks()` cost per 100k-row chunk is a genuine cost this
program has now quantified for the first time, but the actual fix (if
one is wanted) is architectural — teaching `read_chunk`'s downstream
Arrow consumers to work with the natively multi-chunk result instead of
requiring one combined batch — not something this phase's scope covers,
and a materially different, larger change than what the plan described.

## 6. Full test-suite confirmation (Phase 2 changes combined)

```
$ uv run pytest -m "unit or golden or property or contract" -q
1095 passed, 12 skipped, 124 deselected, 1 warning in 292.39s (0:04:52)
```

Run fresh with all three landed Phase 2 changes present (`stream.py`,
`dispatch.py`, and `clickhouse.py`'s metadata caching). Identical result
to the intermediate run taken right after `stream.py`/`dispatch.py`
alone (1095 passed, 292.39s vs. 290.93s) — confirms the `clickhouse.py`
change, which has no unit-level test surface (no `tests/unit` or
`tests/contract` file references `ClickHouseConnector`), introduces no
regression anywhere else in the suite. Up from Phase 1's 1092 passed —
the +3 is exactly this phase's new `test_stream_batch_memoization.py`
tests. Zero failures, zero new skips.

## 7. Not yet done (explicitly out of Phase 2's scope)

- Phase 3 (process-pool parallelism, cardinality-aware cache policy,
  `NORM_CACHE_PATH` revisit, determinism proof) — next, and explicitly
  gated in the plan on Phase 0's `psutil` memory measurements and the
  `normalizers/script.py:36` lazy-lingua prerequisite landing first.
- Live verification of the ClickHouse catalog-method caching against
  `test_catalog_and_streaming.py` specifically (needs the `demo-clickhouse`
  container — see §5).
- The `combine_chunks()` architectural fix this phase's investigation
  surfaced (teaching downstream consumers to accept multi-chunk Arrow
  tables) — a materially different, larger change than originally
  planned; not scoped into this program without a separate decision.

## Human Sign-off

**Verdict:**
**Reviewer:**
**Date:**
