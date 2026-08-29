"""The M17 chunk loop (docs/plan/M13-M22-program-plan.md) — normalizes
one `(table, column)` at a time from a `StreamingSourceConnector`, chunk
by chunk, real streaming (keyset-paginated, no `OFFSET`) rather than
sample-capped, resumable via a caller-supplied progress callback.

Deliberately decoupled from any persistence mechanism: `normexec` has no
Postgres dependency, so resumability is a plain callback
(`on_chunk_committed`) — the caller (`normapi.executor`, M17) is the one
that actually persists `ChunkProgress` to a real `run_chunks` table and
passes the last committed key back in as `resume_after_key` on restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pyarrow as pa
from normcore.contract import NORMALIZED_VALUE_ARROW_SCHEMA, normalized_value_to_arrow_row
from normio.capabilities import CardinalitySamplingConnector

from normcore import ColumnCachePolicy, NormalizationStatus
from normexec.cache_policy import decide_cache_policy
from normexec.planner import DistinctValuePlanner

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from normio.capabilities import StreamingSourceConnector

    from normanalysis import RunRecorder
    from normcore import (
        Dispatcher,
        FieldSemanticType,
        NormalizationContext,
        NormalizationProfile,
        NormalizedValue,
    )
    from normexec.cache import NormalizationCache
    from normexec.parallel import DistinctValueWorkerPool
    from normexec.sinks import RunSink

_CHUNK_SIDECAR_SCHEMA = pa.schema(
    [pa.field("source_row_key", pa.large_string()), *NORMALIZED_VALUE_ARROW_SCHEMA]
)


@dataclass(frozen=True, slots=True)
class ChunkProgress:
    run_id: str
    table: str
    column: str
    chunk_index: int
    last_key: tuple[object, ...]
    rows_processed: int
    # M20: the max real `created_at` value seen in this chunk, when
    # `track_created_at=True` — `None` when watermark tracking wasn't
    # requested, or the table has no `created_at` column. The caller
    # (normapi.store) accumulates this across chunks/columns to know how
    # far an incremental watermark may safely advance once the run
    # completes.
    last_created_at: object | None = None


def stream_column(
    connector: StreamingSourceConnector,
    *,
    run_id: str,
    table: str,
    column: str,
    key_columns: Sequence[str],
    semantic_type: FieldSemanticType,
    context: NormalizationContext,
    profile: NormalizationProfile,
    dispatcher: Dispatcher,
    cache: NormalizationCache | None,
    recorder: RunRecorder,
    sink: RunSink,
    chunk_size: int = 100_000,
    resume_after_key: tuple[object, ...] | None = None,
    since: object | None = None,
    track_created_at: bool = False,
    on_chunk_committed: Callable[[ChunkProgress], None] | None = None,
    pool: DistinctValueWorkerPool | None = None,
) -> int:
    """Streams `table.column`, chunk by chunk, until `read_chunk` reports
    exhaustion (`None`). Each chunk: dedupe + normalize via
    `DistinctValuePlanner.normalize_values` (the same shared entry point
    the pasted-values path uses, M17's refactor — real cache-aware
    dedup, not sample-capped or reinvented), write through `sink`, then
    report `ChunkProgress` — a caller persisting that progress durably is
    what makes `resume_after_key` on a later call actually resumable.

    `since` (M20): real `created_at > since` keyset filtering, pushed
    down by the connector — an incremental run's watermark.
    `track_created_at` (M20): when `True`, also fetches `created_at` per
    row and reports each chunk's max value via `ChunkProgress.
    last_created_at` — what the caller advances a watermark to, only
    after this chunk's write is confirmed committed.

    `pool` (Phase 3, 2026-08-29 throughput/memory program): an already-
    started `DistinctValueWorkerPool` this column's planner MAY use for
    expensive, pool-eligible semantic types — `None` (the default)
    reproduces this function's pre-Phase-3 behavior exactly, fully
    serial. Never constructed here: owned and shut down by whatever
    process-wide caller created it (see `normapi.app.create_app`), since
    the whole point of the pool is amortizing its worker-startup cost
    across every column/chunk of a run, not paying it per `stream_column`
    call.

    Returns the total row count processed across every chunk.
    """
    planner = DistinctValuePlanner(dispatcher, cache, pool=pool)
    after_key = resume_after_key
    chunk_index = 0
    rows_processed = 0

    # Phase 3 item 2 (cardinality-aware cache policy): decided once, up
    # front, when the connector can supply a cheap real estimate; `None`
    # (undecided) otherwise, in which case the first chunk always uses
    # the cache (this run's pre-Phase-3 default) and doubles as the
    # generic fallback's sample — see the non-negotiable "connector
    # capability with a generic fallback" rule in the throughput/memory
    # program's plan. Never computed at all when no cache was configured
    # for this run — there is no policy to decide.
    cache_policy: ColumnCachePolicy | None = None
    if cache is not None and isinstance(connector, CardinalitySamplingConnector):
        cache_policy = decide_cache_policy(
            table=table,
            column=column,
            distinct_ratio=connector.estimate_distinct_ratio(table, column),
            source="connector_estimate",
        )
        recorder.record_cache_policy(cache_policy)
    fetch_columns = (
        [column, *key_columns, "created_at"]
        if track_created_at
        else [
            column,
            *key_columns,
        ]
    )

    while True:
        batch = connector.read_chunk(
            table,
            key_columns=key_columns,
            columns=fetch_columns,
            after_key=after_key,
            limit=chunk_size,
            since=since,
        )
        if batch is None:
            break

        column_values: list[str | None] = batch.column(column).to_pylist()
        key_arrays = [batch.column(name) for name in key_columns]
        last_created_at = None
        if track_created_at:
            real_values = [v for v in batch.column("created_at").to_pylist() if v is not None]
            if real_values:
                last_created_at = max(real_values)

        results = planner.normalize_values(
            column_values,
            semantic_type,
            context,
            profile,
            on_computed=recorder.record_computation,
            on_cache_stat=lambda hit: recorder.record_cache(hit=hit),
            use_cache=cache_policy is None or cache_policy.use_cache,
        )

        if cache is not None and cache_policy is None:
            # Generic fallback (no connector capability): estimate from
            # the real data this chunk already fetched — zero extra I/O.
            # This chunk itself always ran with the cache (the `True`
            # default just above, since `cache_policy` was still `None`);
            # only chunk 2 onward is affected by what gets decided here.
            # A chunk with no non-null values at all leaves `cache_policy`
            # `None` so the NEXT chunk gets a real chance to sample,
            # rather than locking in an "unavailable" verdict from a
            # chunk that had nothing to measure.
            non_null = [v for v in column_values if v is not None]
            if non_null:
                cache_policy = decide_cache_policy(
                    table=table,
                    column=column,
                    distinct_ratio=len(set(non_null)) / len(non_null),
                    source="first_chunk_sample",
                )
                recorder.record_cache_policy(cache_policy)

        for result in results:
            changed = result.normalization_status is not NormalizationStatus.UNCHANGED
            recorder.record_value(changed=changed, status=result.normalization_status)
            for _ in result.warnings:
                recorder.record_warning()
            if result.errors:
                recorder.record_error()
        recorder.record_field()

        out_batch = _results_to_batch(batch, results)
        sink.write_chunk(
            run_id=run_id, table=table, column=column, chunk_index=chunk_index, batch=out_batch
        )

        last_key = tuple(key_array[-1].as_py() for key_array in key_arrays)
        rows_processed += batch.num_rows
        if on_chunk_committed is not None:
            on_chunk_committed(
                ChunkProgress(
                    run_id=run_id,
                    table=table,
                    column=column,
                    chunk_index=chunk_index,
                    last_key=last_key,
                    rows_processed=rows_processed,
                    last_created_at=last_created_at,
                )
            )

        after_key = last_key
        chunk_index += 1

    sink.finish(run_id=run_id, table=table, column=column)
    return rows_processed


def _results_to_batch(
    source_batch: pa.RecordBatch, results: list[NormalizedValue]
) -> pa.RecordBatch:
    """Builds the Arrow batch `sink.write_chunk` receives — every
    result's flat fields plus the source's real `source_row_key`
    (already computed by the connector from real primary-key values, per
    M14 — never a positional index).

    Phase 2 (2026-08-29 throughput program): duplicate rows in `results`
    share the SAME `NormalizedValue` object by reference —
    `DistinctValuePlanner.normalize_values` resolves every row back from
    its distinct-value dedup, not a fresh object per row — so calling
    `normalized_value_to_arrow_row` once per ROW repeated the same
    (measured ~100% trace-JSON-serialization) work for every duplicate.
    Memoized on `id(result)`: safe because `results` holds a live
    reference to every object for this whole function call, so no id can
    be reused by the garbage collector mid-build. Byte-identical output —
    this only skips redundant recomputation of a value already computed
    for an object appearing earlier in the same list.
    """
    source_keys = source_batch.column("source_row_key").to_pylist()
    row_cache: dict[int, dict[str, Any]] = {}
    rows = []
    for result in results:
        cache_key = id(result)
        row = row_cache.get(cache_key)
        if row is None:
            row = normalized_value_to_arrow_row(result)
            row_cache[cache_key] = row
        rows.append(row)
    arrays = [
        pa.array(
            [
                source_keys[i] if field.name == "source_row_key" else rows[i][field.name]
                for i in range(len(rows))
            ],
            type=field.type,
        )
        for field in _CHUNK_SIDECAR_SCHEMA
    ]
    return pa.RecordBatch.from_arrays(arrays, schema=_CHUNK_SIDECAR_SCHEMA)
