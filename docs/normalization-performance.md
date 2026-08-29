# Normalization performance

Referenced from `normalization-architecture.md` since M8 as "(populated in
M8)" but never written until the throughput/memory program (2026-08-29) —
that program's findings are this document's natural content, so it starts
here rather than at M8's original, narrower scope.

This is a summary and index, not the source of truth. Every number below
was measured against real infrastructure and is recorded in full, with
real command output, in the verification packs linked from each section.
When this document and a pack disagree, the pack wins — update this
document to match, not the other way around.

## 1. Why this exists

M0–M22 built a correct, three-step normalization product. It had never
been profiled against its real workload until a live run against
`origin2.Company` (1.27M rows, 97% distinct) appeared to hang
indefinitely. That hang, and three other algorithmic defects hiding
behind it, are documented in
`docs/verification/perf-program-phase-0-verification-pack.md` and
`docs/verification/perf-program-phase-1-verification-pack.md`, and the
plan that drove the whole program:
`C:\Users\rezas\.claude\plans\humming-frolicking-shore.md` (local to the
machine this program ran on, not checked into the repo).

## 2. What changed, by phase

| Phase | What | Pack |
|---|---|---|
| 0 | Measurability infra: `bench-compare`, `normcli run`/`diff --require-identical`, `psutil` RSS sampling, real-scale benchmarks | `docs/verification/perf-program-phase-0-verification-pack.md` |
| 1 | Four algorithmic defects fixed (O(n²) cache scan, redundant `context_hash` recompute, uncached `i18naddress` disk reads, double `snapshot()` + unbounded latency list) | `docs/verification/perf-program-phase-1-verification-pack.md` |
| 2 | Per-row work moved to per-distinct-value (Arrow row memoization, single `NormalizedValue` construction, connector round-trip caching) | `docs/verification/perf-program-phase-2-verification-pack.md` |
| 3.1 | Process-pool parallelism for distinct-value normalization, gated by measured per-value cost | `docs/verification/perf-program-phase-3-verification-pack.md` |
| 3.2–3.5 | Cardinality-aware cache policy, `NORM_CACHE_PATH` re-measurement, determinism proof for the pool, `AddressNormalizer` HTTP batching | `docs/verification/perf-program-phase-3-items-2-5-verification-pack.md` |

`docs/traceability-matrix.md`'s "Throughput/Memory Program" section carries
the same links plus per-item source/test-location detail.

## 3. The four algorithmic defects (Phase 1)

Measured on real ClickHouse data (`origin2`), not synthetic:

1. **`normexec/cache.py`'s `get_many`** tracked pending DuckDB lookup keys
   in a `list` and checked membership with `in` — O(n²). Measured
   quadratic: n=20,000 → 4.7s, n=50,000 → 44.9s. This is what made
   `Company.name` (97% distinct, i.e. mostly cache misses) appear to
   hang. Fixed with a `set` alongside the list; same insertion-order and
   per-occurrence stats semantics preserved exactly.
2. **`normcore/context.py`'s `context_hash`** was a plain `@property` on
   a frozen model, recomputed (model_dump + json.dumps + blake3) on every
   access — ~19.3 µs/access, hit ~3x per value. Memoized via a pydantic
   `PrivateAttr`.
3. **`normalizers/postcode_validation.py`** re-read and re-parsed
   `i18naddress` country JSON from disk on every call — 768.9 µs/call.
   Wrapped in `functools.lru_cache`: 0.186 µs — a 4,127x difference.
4. **`normapi/store.py`** called `RunRecorder.snapshot()` twice per
   chunk, each sorting the run's entire accumulated latency list — and
   that list was itself unbounded (290 MB at `Person.fullName` scale).
   Fixed: one `snapshot()` per chunk, plus a fixed-size reservoir sample
   for latencies (the one intentional behavior change in Phase 1 —
   percentile *values* shift slightly; percentile *fields* were already
   excluded from the ADR-014 determinism comparison as wall-clock noise).

## 4. Per-distinct-value, not per-row (Phase 2)

Duplicate rows share the same `NormalizedValue` object by reference
(`DistinctValuePlanner`). Row serialization was memoized on `id(result)`,
turning trace-serialization cost (the dominant per-row cost — 66 µs
`model_dump` + 111 µs `json.dumps`, up to 266.7 µs/row for a 15-step
trace) into a per-*distinct-value* cost. A column's real dedup factor
(measured 1.03x–2,972x across `origin2`'s real columns) is realized for
free as a result.

## 5. Process-pool parallelism (Phase 3.1)

Threads were measured useless for this workload — 4 threads on real
normalization is a 0.90x "speedup" (Python's GIL, pure-CPU work). A
`ProcessPoolExecutor`-backed `DistinctValueWorkerPool`
(`normexec/parallel.py`) parallelizes the distinct-value normalize loop,
gated by measured per-value cost (break-even ~200 µs) so cheap semantic
types (COUNTRY, DATE, BOOLEAN, CURRENCY) are never routed through it —
IPC round-trip cost (measured 198.4 µs/value) would make them slower, not
faster. `ADDRESS` is permanently excluded (network-bound work, and the
libpostal sidecar's single sync worker gains nothing from more client
concurrency — see the pack for the full argument).

Off by default (`NORM_PARALLEL_WORKERS=0`); enabling it derives worker
count from the container's real cgroup CPU quota, never
`os.cpu_count()` (which reports host CPUs even inside a limited
container).

## 6. Cardinality-aware caching (Phase 3.2–3.3)

Distinctness is sampled per column at run start — via a connector's
`CardinalitySamplingConnector.estimate_distinct_ratio` when it implements
one (ClickHouse: `uniqExact`; Postgres/MySQL: standard `COUNT(DISTINCT
...)` on `normio/connectors/_sql_base.py`'s shared `SqlConnectorBase`,
added as part of this document's own doc-debt cleanup), or from the
column's real first chunk when it doesn't (the generic fallback every
connector kind gets for free). Below `CACHE_SKIP_DISTINCT_RATIO_THRESHOLD`
(0.5), the full two-tier cache is used; above it, cache writes are
skipped entirely — verified live: `Company.name` (97% distinct) makes
zero cache writes, `Location.country` (0.03% distinct) hits the full
617-miss/14,732-hit split predicted by its real cardinality. The decision
is recorded per column in the run report (`ColumnCachePolicy`), never
silent.

`NORM_CACHE_PATH`'s persistent DuckDB tier was re-measured after fixing a
separate DuckDB literal-embedding/binder bug (predates this program;
see `docs/verification/M22-verification-pack.md` for the bug itself, and
`docs/verification/perf-program-phase-3-items-2-5-verification-pack.md`
for the re-measurement) at ~10,286 values/sec — the M17/M22 packs' "net
loss" conclusion, based on a bugged ~80 values/sec, is marked RETRACTED
in place in both packs. The
operational default (`compose.yaml`) still ships `:memory:`: the
cardinality policy already avoids wasted writes at the within-run tier
regardless of this setting, and enabling a real cross-run file adds a
stateful volume and cache-invalidation story this program deliberately
did not design.

## 7. Determinism under parallelism (Phase 3.4)

`normcli diff --require-identical` between a serial run and a
`--parallel-workers 4` run over the same real ~3,940-row Postgres dataset
returned `IDENTICAL` (exit 0) — proven, not just architecturally argued.
Workers return already-ordered results (rejoined by input position, never
`as_completed` order), so cache-write order and downstream row-join
behavior match serial execution exactly.

## 8. AddressNormalizer batching (Phase 3.5)

The libpostal sidecar's `/parse` endpoint already accepted a list; only
one address per HTTP call was ever sent. `LibpostalClient.parse_batch`
and `AddressNormalizer.normalize_many` (an opt-in
`BatchCapableNormalizer`, distinct from the removed `Normalizer.
normalize_batch` — see §9) send the whole batch in one round trip.
Measured against the real sidecar: per-value ~51,524 µs/value vs. batched
~881.6 µs/value — ~58x, 0 mismatches across 200 real addresses.

## 9. A correction: `normalize_batch` never existed as a real batch path

`ADR-016-performance-architecture.md` originally claimed batch APIs were
mandatory on every `Normalizer` and that "the planner always calls the
batch path." Neither was true: every normalizer implemented
`normalize_batch(values: pa.Array, ctx) -> pa.StructArray`, but
`DistinctValuePlanner` has always called `normalize()` once per distinct
value — confirmed during this program's R&D, and the ADR has since been
corrected. The dead method (and the now-unused `pyarrow` imports it
required) was removed from the `Normalizer` Protocol and all 19
normalizers as part of this document's own doc-debt pass. The real,
narrow, opt-in batch path is `BatchCapableNormalizer.normalize_many`
(§8), used today only by `AddressNormalizer`.

## 10. Known-open items

- Per-worker memory under the process pool has been measured at small
  scale, not at the full `Person.fullName` (11.8M-row) scale with the
  complete 20-normalizer registry loaded.
- `PYTHONHASHSEED=0` is now pinned in `packages/normapi/Dockerfile` and
  `.github/workflows/gate.yml`'s `determinism-replay` job — a residual
  risk closed, not a new open item, but recorded here since the plan
  originally flagged it as open.
- `ScriptNormalizer`'s per-value cost is addressed in §11 below via
  per-column language calibration, landed 2026-08-29 after the product
  answer to "what languages does this data contain" turned out to be
  "it varies by source, and some sources are genuinely unknown" — see
  §11 for why that made per-project configuration the wrong shape.

## 11. `ScriptNormalizer`: per-column language calibration

The available speedup levers for `_detect_language_hint`'s ~25,500
µs/value all-75-languages `lingua` detector change its real classification
output on ambiguous text — restricting the candidate language set can
change which language a value scores as. A blanket, hardcoded
per-project language list was rejected: real sources here range from
single-language to genuinely global (`origin1`), sometimes within the
same database, and "what languages will this data contain" is not
something a user can reliably answer in advance for a general-purpose
engine.

Instead, `normalizers/script.py` calibrates per column, from the
column's own data, at run time:

- The first 500 values normalized for a given `context_hash` (a stable
  per-column key — field/table/source/profile, already computed for
  every value) run the full 75-language detector, as before, while
  tallying which language won each call.
- Once 500 samples are in, the top languages by tally count (capped at
  12) are frozen into a small restricted detector, cached and reused for
  the rest of the column.
- Below a confidence threshold, a restricted-detector result falls back
  to the full detector for that one value — real output correctness is
  preserved; only speed is traded, and only where the column's own data
  showed enough concentration to justify it.
- A calibrated set is required to have >= 2 languages: `lingua` gives a
  degenerate 0.0/1.0 confidence with exactly one candidate language
  (confirmed empirically against real single-language input), which
  would make the fallback check meaningless. A column whose 500-sample
  tally never reaches 2 distinct languages stays on the full detector.

Measured (this machine): a 1-language restricted detector runs at ~137
µs/value (186x faster than full); a real 15-language set drawn from
actual `origin2.Person.fullName` samples ran at ~10,700 µs/value (2.4x
faster) — `fullName` is the program's own worked example of a
genuinely high-diversity column (76.8% distinct, real global names), so
a modest win there and a large one on more concentrated columns is the
expected, intentional shape of this feature, not a shortfall.

This is a deliberate accuracy/speed *tradeoff*, unlike the byte-identical
Phase 1 fixes — flagged explicitly in `script.py`'s own module comment,
including the one confirmed residual risk: the confidence-based fallback
is relative to the candidate pool, so a calibrated set sitting right at
the 2-language floor gives a weaker safety signal than the larger sets
real noisy per-value data typically produces (500 real `fullName`
samples alone produced 47 distinct guessed languages). Determinism is
unaffected either way: calibration is itself deterministic (same
profile+source+chunk order -> same calibrated set every run), it only
trades off against how a hypothetical uncalibrated full-detector run
would have scored the same value.
