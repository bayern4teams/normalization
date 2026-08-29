# ADR-016: Performance and Scale Architecture

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §102–§104 require the engine to process millions to billions of
values via vectorized/batch processing, streaming, chunking, caching,
deduplicated normalization calls, parser-object reuse, and safe
parallelism — while explicitly warning against database pushdown except
where semantics are provably safe, and against per-row Python overhead.

Three execution engine options were considered:

1. **Pandas + SQLAlchemy** — most familiar, but per-row Python-level
   iteration (even with `.apply()`) makes "millions to billions of values"
   unrealistic within reasonable latency/cost budgets; no zero-copy
   columnar interop with the normalizer layer.
2. **Spark / Ray distributed** — genuine horizontal scale, but introduces
   cluster operations, JVM/UDF serialization overhead for Python
   normalizers, and materially complicates the `env_id` reproducibility
   story (ADR-014) across a distributed, potentially heterogeneous
   cluster.
3. **Polars + DuckDB + Arrow/Parquet, single-node** — Polars' Rust/Arrow
   core supports multi-threaded columnar execution with dictionary-encoded
   strings; DuckDB provides fast SQL-style aggregation and is itself
   Arrow-native for reading/writing Parquet and connecting to ClickHouse.
   No cluster to operate; single-node scales to tens/hundreds of millions
   of rows before distribution would even be worth its operational cost.

## Decision

- **Polars + DuckDB + Arrow/Parquet**, single-node, chosen over Spark/Ray
  primarily because it keeps `env_id`-based reproducibility tractable (one
  process's dependency set, not a heterogeneous cluster's) and eliminates
  cluster-ops burden that is disproportionate to this project's actual
  scale requirements. Re-evaluated only if single-node throughput proves
  insufficient at Milestone 8's benchmark gate.
- **Distinct-value-first execution is the core performance strategy**, not
  a bolt-on cache: for any column being normalized, extract the **distinct
  value set** first (Polars `.unique()`), normalize only that set, then
  join results back to every row via Arrow dictionary encoding. Real
  columns are highly redundant (a 50M-row `city` column might hold 30k
  distinct values) — this typically reduces actual normalizer invocations
  by one to three orders of magnitude and makes even a network-hop
  normalizer (libpostal sidecar, ADR-005) practical at scale. This
  directly satisfies §102's "repeated values should be normalized once per
  profile/version" by construction.
- **Two-tier cache**: in-process LRU for hot repeated lookups within a
  single run, plus a DuckDB-backed persistent cache keyed on
  `(blake3(raw_value), profile_version, semantic_type, context_hash,
  env_id)` for cross-run reuse. Cache keys are hashes; raw values never
  appear in a key (§103's PII-in-cache-keys prohibition). The `env_id`
  component means any upstream library/dictionary change automatically
  invalidates stale entries rather than requiring manual cache clearing.
- **The distinct-value planner calls `normalize()` once per distinct
  value by default** (`DistinctValuePlanner._compute_serial`) — NOT a
  batch path. `Normalizer.normalize_batch(values: pa.Array, ctx) ->
  pa.StructArray` is a required part of the interface, but returns only
  4 of `NormalizedValue`'s fields and, confirmed during the 2026-08-29
  throughput/memory program's R&D pass, nothing in the real execution
  path has ever called it — this ADR previously claimed otherwise
  ("the distinct-value planner always calls the batch path"), which was
  never true. It remains implemented by all 20 normalizers and unused;
  removing it was out of scope for that program.
  **Phase 3 item 5 of that program** added a real, narrow batch path
  instead: an OPTIONAL `BatchCapableNormalizer.normalize_many(values,
  ctx) -> list[NormalizedValue]` Protocol (`normcore.interfaces`),
  checked by `Dispatcher.normalize_many` and used by
  `DistinctValuePlanner._compute_serial` whenever the resolved
  normalizer implements it — today, only `AddressNormalizer`, batching
  every distinct value needing a real parse into ONE libpostal HTTP
  call instead of one call per value (live-measured: ~58x faster on a
  200-value batch, byte-identical output vs. the per-value path). Every
  other semantic type still calls `normalize()` per distinct value,
  unchanged — this is deliberately narrow, not a general batch-by-default
  redesign: a CPU-bound normalizer has no equivalent win, since batching
  doesn't remove per-value dispatch overhead that's already amortized
  per-process, not per-call.
- **Database pushdown is restricted to provably safe operations only** —
  currently limited to exact-match sentinel/missing-value detection
  (§53–§54), which is semantically a lookup, not a parser-driven
  transformation. No parser-driven normalization (names, addresses, phones,
  dates) is ever pushed down to SQL.
- **Parser object reuse**: normalizer adapters that wrap stateful parser
  objects (ICU transliterators, `phonenumbers` metadata, `dateparser`
  settings objects) are constructed once per worker process and reused
  across the entire distinct-value batch, never reconstructed per value.

## Consequences

- Single-node Polars/DuckDB means the practical ceiling is bounded by one
  machine's cores/memory — acceptable for the stated scale target and
  explicitly re-evaluated (not silently deferred) at the M8 benchmark
  gate if real workloads exceed it.
- The distinct-value-first design means a normalizer's *implementation*
  correctness matters more than its raw per-call speed, since call volume
  is already reduced by orders of magnitude before any given normalizer
  sees a value — this shifts optimization priority toward correctness and
  cache-hit-ratio observability over micro-benchmarking individual
  normalizer calls.
- Benchmarks recorded at the M2 gate become the standing no-regression
  baseline for every subsequent gate (>10% throughput regression or >15%
  p95 latency regression fails the gate) — performance is tracked
  continuously, not audited only at M8.

## Revisit triggers

- M8 benchmarks show single-node throughput insufficient for a real
  target workload (stated scale: "millions/billions of values," per
  §102) — evaluate Ray/Dask as a thin distribution layer *over* the same
  Polars/DuckDB per-node logic, preserving `env_id` per node and
  aggregating, rather than adopting Spark's UDF model wholesale.
- Cache hit ratio in production consistently falls below a useful
  threshold — investigate whether the distinct-value assumption holds for
  the actual field in question (some fields, e.g. free-text notes, may
  have low natural redundancy and need a different strategy).
