"""The M19 full-row destination-writing chunk loop
(docs/plan/M13-M22-program-plan.md) — reads a table's REAL, COMPLETE rows
(every source column, not just one), normalizes the columns the run's
mapping designates, copies every other column through unchanged, and
writes one complete destination row per source row.

This is deliberately a SEPARATE function from `normexec.stream.
stream_column`, not a reuse of it, and `normsink.DestinationConnector`'s
`insert_batch` is a genuinely different shape from M17's `RunSink.
write_chunk` (a real, disclosed deviation from the M13-M22 plan's own
"implementing M17's RunSink" wording — see the M19 verification pack).
`stream_column` processes ONE column's distinct values, deduped across
the whole chunk, entirely decoupled from any other column; a destination
write needs a COMPLETE row per source key in one INSERT (ClickHouse
`ReplacingMergeTree` replaces the whole row for a repeated key, it does
not merge columns across separate inserts for the same key — writing a
row's mapped and unmapped columns via two separate partial inserts would
make the second one silently wipe out the first's data). Reusing
`stream_column`'s per-column model for a full-row destination write is
not just an inconvenient interface mismatch, it would be incorrect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pyarrow as pa
from normcore.enums import NormalizationStatus
from normsink.typed_values import extract_date, extract_numeric

from normexec.planner import DistinctValuePlanner
from normexec.stream import ChunkProgress

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from normio.capabilities import StreamingSourceConnector
    from normio.catalog import ColumnSpec
    from normsink.destination import DestinationConnector

    from normanalysis import RunRecorder
    from normcore import Dispatcher, FieldSemanticType, NormalizationProfile, NormalizedValue
    from normexec.cache import NormalizationCache

_SIDE_TABLE_SCHEMA_FIELDS = (
    "table_name",
    "source_row_key",
    "column_name",
    "severity",
    "code",
    "message",
    "lossiness",
    "normalization_status",
    "run_id",
)

_SUCCESSFUL_STATUSES = frozenset(
    {
        NormalizationStatus.NORMALIZED,
        NormalizationStatus.REPAIRED,
        NormalizationStatus.PARSED,
        NormalizationStatus.UNCHANGED,
    }
)


def stream_table_to_destination(
    connector: StreamingSourceConnector,
    *,
    run_id: str,
    table: str,
    key_columns: Sequence[str],
    source_columns: Sequence[ColumnSpec],
    column_semantic_types: Mapping[str, FieldSemanticType],
    field_ref_prefix: str,
    profile: NormalizationProfile,
    dispatcher: Dispatcher,
    cache: NormalizationCache | None,
    recorder: RunRecorder,
    destination: DestinationConnector,
    destination_table: str,
    chunk_size: int = 100_000,
    resume_after_key: tuple[object, ...] | None = None,
    since: object | None = None,
    track_created_at: bool = False,
    on_chunk_committed: Callable[[ChunkProgress], None] | None = None,
) -> int:
    """Streams `table`'s complete real rows, chunk by chunk, writing a
    complete mirrored row (mapped columns normalized/typed, unmapped
    columns copied verbatim) plus any real normalization-issue rows per
    chunk. `column_semantic_types` maps a SUBSET of `source_columns`'
    names to the semantic type mapped for them — every other real source
    column is copied through unchanged, never dropped, keeping the
    destination table exactly as wide as the source (decision 7).

    `since`/`track_created_at` (M20): the same real incremental-watermark
    support `normexec.stream.stream_column` has — `columns=None` already
    fetches every real source column, so `created_at` (when the table has
    one) is already present in each chunk without any extra column
    request; this just tracks its max value per chunk.

    Returns the total row count processed across every chunk.
    """
    planner = DistinctValuePlanner(dispatcher, cache)
    after_key = resume_after_key
    chunk_index = 0
    rows_processed = 0
    all_column_names = [c.name for c in source_columns]

    while True:
        batch = connector.read_chunk(
            table,
            key_columns=key_columns,
            columns=None,  # every real source column, not just the mapped ones
            after_key=after_key,
            limit=chunk_size,
            since=since,
        )
        if batch is None:
            break

        last_created_at = None
        if track_created_at and "created_at" in batch.schema.names:
            real_values = [v for v in batch.column("created_at").to_pylist() if v is not None]
            if real_values:
                last_created_at = max(real_values)

        normalized_by_column: dict[str, list[NormalizedValue]] = {}
        for column, semantic_type in column_semantic_types.items():
            values: list[str | None] = batch.column(column).to_pylist()
            ctx = profile.build_context(
                f"{field_ref_prefix}{column}", semantic_type, error_policy=None
            )
            results = planner.normalize_values(
                values,
                semantic_type,
                ctx,
                profile,
                on_computed=recorder.record_computation,
                on_cache_stat=lambda hit: recorder.record_cache(hit=hit),
            )
            for result in results:
                changed = result.normalization_status is not NormalizationStatus.UNCHANGED
                recorder.record_value(changed=changed, status=result.normalization_status)
                for _ in result.warnings:
                    recorder.record_warning()
                if result.errors:
                    recorder.record_error()
            normalized_by_column[column] = results
        recorder.record_field()

        source_row_keys: list[str] = batch.column("source_row_key").to_pylist()
        dest_batch = _build_destination_batch(
            batch,
            all_column_names=all_column_names,
            column_semantic_types=column_semantic_types,
            normalized_by_column=normalized_by_column,
        )
        destination.insert_batch(destination_table, dest_batch)

        issues_batch = _build_issues_batch(
            table=table,
            run_id=run_id,
            source_row_keys=source_row_keys,
            column_semantic_types=column_semantic_types,
            normalized_by_column=normalized_by_column,
        )
        if issues_batch is not None:
            destination.insert_side_table_batch(destination_table, issues_batch)

        key_arrays = [batch.column(name) for name in key_columns]
        last_key = tuple(key_array[-1].as_py() for key_array in key_arrays)
        rows_processed += batch.num_rows
        if on_chunk_committed is not None:
            on_chunk_committed(
                ChunkProgress(
                    run_id=run_id,
                    table=table,
                    column="",
                    chunk_index=chunk_index,
                    last_key=last_key,
                    rows_processed=rows_processed,
                    last_created_at=last_created_at,
                )
            )

        after_key = last_key
        chunk_index += 1

    return rows_processed


def _build_destination_batch(
    source_batch: pa.RecordBatch,
    *,
    all_column_names: list[str],
    column_semantic_types: Mapping[str, FieldSemanticType],
    normalized_by_column: dict[str, list[NormalizedValue]],
) -> pa.RecordBatch:
    arrays = []
    fields = []
    for name in all_column_names:
        semantic_type = column_semantic_types.get(name)
        if semantic_type is None:
            # Unmapped — copied straight through, unchanged, same Arrow
            # array the source connector already produced for it.
            arrays.append(source_batch.column(name))
            fields.append(source_batch.schema.field(name))
            continue

        results = normalized_by_column[name]
        arr_type: pa.DataType
        typed_values: list[object]
        if semantic_type.value == "NUMERIC":
            typed_values = [extract_numeric(r) for r in results]
            arr_type = pa.decimal128(38, 9)
        elif semantic_type.value == "DATE":
            typed_values = [extract_date(r) for r in results]
            arr_type = pa.date32()
        else:
            typed_values = [r.display for r in results]
            arr_type = pa.large_string()
        arrays.append(pa.array(typed_values, type=arr_type))
        fields.append(pa.field(name, arr_type))

    return pa.RecordBatch.from_arrays(arrays, schema=pa.schema(fields))


def _build_issues_batch(
    *,
    table: str,
    run_id: str,
    source_row_keys: list[str],
    column_semantic_types: Mapping[str, FieldSemanticType],
    normalized_by_column: dict[str, list[NormalizedValue]],
) -> pa.RecordBatch | None:
    """One row per real normalization issue: every warning, every error,
    and — for a typed NUMERIC/DATE column whose destination value ends up
    NULL for any reason (a non-successful status like AMBIGUOUS with no
    warning/error of its own, e.g. `NumericNormalizer`'s ambiguous-locale
    case, or a real parse-back failure where `normalization_status`
    looked like success but `display` did not parse as the target type)
    — a real explanatory row, so a silently-NULLed typed destination
    value is never left with NO trace of why."""
    rows: list[tuple[str, ...]] = []
    for column, semantic_type in column_semantic_types.items():
        results = normalized_by_column[column]
        is_typed = semantic_type.value in ("NUMERIC", "DATE")
        for row_key, result in zip(source_row_keys, results, strict=True):
            issue_ctx = _IssueContext(table=table, column=column, run_id=run_id)
            had_warning_or_error = False
            for warning in result.warnings:
                had_warning_or_error = True
                rows.append(
                    _issue_row(
                        issue_ctx,
                        row_key,
                        result,
                        severity="warning",
                        code="NORMALIZER_WARNING",
                        message=warning,
                    )
                )
            for error in result.errors:
                had_warning_or_error = True
                rows.append(
                    _issue_row(
                        issue_ctx,
                        row_key,
                        result,
                        severity="error",
                        code="NORMALIZER_ERROR",
                        message=error,
                    )
                )
            if not is_typed or had_warning_or_error or not result.original:
                continue
            kind = "numeric" if semantic_type.value == "NUMERIC" else "date"
            extracted = extract_numeric(result) if kind == "numeric" else extract_date(result)
            if extracted is None:
                rows.append(_typed_parse_issue_row(issue_ctx, row_key, result, kind))

    if not rows:
        return None

    arrays = [
        pa.array([row[i] for row in rows], type=pa.large_string())
        for i in range(len(_SIDE_TABLE_SCHEMA_FIELDS))
    ]
    schema = pa.schema([pa.field(name, pa.large_string()) for name in _SIDE_TABLE_SCHEMA_FIELDS])
    return pa.RecordBatch.from_arrays(arrays, schema=schema)


class _IssueContext(NamedTuple):
    table: str
    column: str
    run_id: str


def _issue_row(
    ctx: _IssueContext,
    row_key: str,
    result: NormalizedValue,
    *,
    severity: str,
    code: str,
    message: str,
) -> tuple[str, ...]:
    return (
        ctx.table,
        row_key,
        ctx.column,
        severity,
        code,
        message,
        result.lossiness.value,
        result.normalization_status.value,
        ctx.run_id,
    )


def _typed_parse_issue_row(
    ctx: _IssueContext,
    row_key: str,
    result: NormalizedValue,
    kind: str,
) -> tuple[str, ...]:
    """Reached whenever a typed (NUMERIC/DATE) destination column ends up
    NULL for a row that had a real original value and no warning/error
    row of its own (the caller already filters those out to avoid a
    duplicate) — covers both a genuine parse-back failure (status looked
    successful but `display` did not parse as the target type) and a
    non-successful status with nothing else explaining the NULL (e.g.
    `NumericNormalizer`'s AMBIGUOUS-locale case, which sets a flag but no
    warning/error of its own)."""
    if result.normalization_status in _SUCCESSFUL_STATUSES:
        message = (
            f"display={result.display!r} did not parse as a real {kind} value; "
            "destination column written NULL"
        )
    else:
        message = (
            f"normalization_status={result.normalization_status.value} — no {kind} value "
            "written; destination column written NULL"
        )
    return _issue_row(
        ctx, row_key, result, severity="warning", code="TYPED_COLUMN_PARSE_FAILED", message=message
    )
