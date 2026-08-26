"""Sidecar store — Parquet + DuckDB catalog, Source.txt §8, §105, §106;
design in docs/adr/ADR-013-normalization-storage.md.

Output is partitioned Parquet cataloged in a DuckDB table, never a write
back to the source system. This is the ONLY place in the codebase that
writes normalized data to disk.

M17 (docs/plan/M13-M22-program-plan.md) adds a real `column_name`
dimension: M9-M16's single-column execution smuggled the column in as
`table_name` (one run always normalized exactly one field, so it doubled
as the lookup key), which cannot express M17's real multi-column runs —
`(table, column)` pairs sharing a run_id are now genuinely distinct
partitions, not the same one reused. Partition paths become
`{source_id}/{table}/{column}/{run_id}/part-N.parquet` when `column` is
given; the legacy single-column shape
`{source_id}/{table}/{run_id}/part-N.parquet` (`column=""`) is preserved
byte-for-byte for the existing pasted-values execution path, so nothing
written before this milestone needs migrating.

M18: every `self._conn` (DuckDB) call is guarded by `self._lock`. A real
bug, found via live verification: a single `duckdb.Connection` is NOT
thread-safe for concurrent `execute()`/`fetchone()` calls from multiple
threads (verified directly — concurrent threads calling `execute()` on
one shared connection returned truncated/`None` rows, not an exception,
the worst kind of corruption). This was already a LATENT risk since M9
(this store has always been reachable from multiple concurrent
execution threads), but M17's worker pool is what made genuinely
concurrent multi-column runs sharing one `InMemoryStore`/`SidecarStore`
a routine occurrence rather than a rare one — the same category of "a
pool makes an existing race routine" risk the M17 pack already disclosed
for `run_id` double-starts, discovered here for real via a live M18 test
that runs two multi-column executions concurrently.
"""

from __future__ import annotations

import threading
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pa_parquet


class SidecarStore:
    def __init__(self, parquet_root: str | Path, duckdb_path: str | Path) -> None:
        self._parquet_root = Path(parquet_root)
        self._parquet_root.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(duckdb_path))
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS sidecar_catalog ("
                "  source_id VARCHAR,"
                "  table_name VARCHAR,"
                "  column_name VARCHAR NOT NULL DEFAULT '',"
                "  run_id VARCHAR,"
                "  part_path VARCHAR,"
                "  row_count BIGINT,"
                "  written_at TIMESTAMP DEFAULT current_timestamp,"
                "  PRIMARY KEY (source_id, table_name, column_name, run_id, part_path)"
                ")"
            )
            # `CREATE TABLE IF NOT EXISTS` above only creates the
            # up-to-date schema on a BRAND NEW catalog.duckdb file — an
            # existing one (from a deployment running M9-M16's code)
            # keeps its old 4-column schema forever unless something
            # actually alters it. Real, idempotent (verified live: a
            # second call is a no-op, not an error) — this is the actual
            # migration, not just a comment promising one.
            self._conn.execute(
                "ALTER TABLE sidecar_catalog ADD COLUMN IF NOT EXISTS "
                "column_name VARCHAR DEFAULT ''"
            )

    def write_batch(
        self,
        *,
        source_id: str,
        table: str,
        run_id: str,
        batch: pa.RecordBatch,
        part_index: int,
        column: str = "",
    ) -> Path:
        partition_dir = (
            self._parquet_root / source_id / table / column / run_id
            if column
            else self._parquet_root / source_id / table / run_id
        )
        partition_dir.mkdir(parents=True, exist_ok=True)
        part_path = partition_dir / f"part-{part_index:06d}.parquet"

        # Parquet writes to distinct files never conflict across threads
        # — only the shared DuckDB connection below needs the lock.
        pa_parquet.write_table(_as_table(batch), part_path)

        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sidecar_catalog "
                "(source_id, table_name, column_name, run_id, part_path, row_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [source_id, table, column, run_id, str(part_path), batch.num_rows],
            )
        return part_path

    def find_run_table(self, run_id: str) -> tuple[str, str] | None:
        """(source_id, table) for a given run_id, or None if nothing was
        ever written for it. Unchanged single-pair legacy contract for
        the pasted-values execution path (M9-M16), which only ever
        normalizes one column per run — for a real multi-column run, use
        `list_run_tables` instead, which doesn't collapse distinct
        columns into "whichever matched first"."""
        with self._lock:
            row = self._conn.execute(
                "SELECT source_id, table_name FROM sidecar_catalog WHERE run_id = ? LIMIT 1",
                [run_id],
            ).fetchone()
        return (row[0], row[1]) if row else None

    def list_run_tables(self, run_id: str) -> list[tuple[str, str, str]]:
        """Every (source_id, table, column) combination written for a
        run — the real lookup M17's multi-column runs need for restart
        recovery, since `find_run_table`'s "exactly one pair" contract
        can't represent more than one column sharing a run_id."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT source_id, table_name, column_name FROM sidecar_catalog "
                "WHERE run_id = ? ORDER BY table_name, column_name",
                [run_id],
            ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    def read_run(self, *, source_id: str, table: str, run_id: str, column: str = "") -> pa.Table:
        part_paths = self._part_paths(
            source_id=source_id, table=table, run_id=run_id, column=column
        )
        return pa_parquet.read_table(part_paths)

    def read_run_paginated(
        self,
        *,
        source_id: str,
        table: str,
        run_id: str,
        column: str = "",
        offset: int = 0,
        limit: int = 1000,
    ) -> pa.Table:
        """M18: a page of a run's real per-value results, pushed down to
        DuckDB (`read_parquet(...) OFFSET ... LIMIT ...`) rather than
        `read_run`'s "materialize everything, let the caller slice it" —
        the fix for `GET /runs/{id}/values` at real multi-million-row
        scale (the plan's own explicit callout: never `to_pylist()` on a
        12M-row table)."""
        part_paths = self._part_paths(
            source_id=source_id, table=table, run_id=run_id, column=column
        )
        with self._lock:
            # `.arrow()` returns a lazy `RecordBatchReader` in this
            # DuckDB version (verified live) — `.to_arrow_table()` is
            # what actually materializes the (small, LIMIT-bounded) page
            # into a real `pa.Table` the caller can call `.to_pylist()`
            # on.
            return self._conn.execute(
                "SELECT * FROM read_parquet(?) OFFSET ? LIMIT ?", [part_paths, offset, limit]
            ).to_arrow_table()

    def compute_column_stats(
        self,
        *,
        source_id: str,
        table: str,
        run_id: str,
        column: str = "",
        quality_sql_predicate: str | None = None,
    ) -> dict[str, int | None]:
        """M18: one bounded DuckDB aggregate query over a (table, column)
        run's real Parquet files — the replacement for `GET /overview`/
        `GET /quality` ever hydrating full per-value results (see
        `normanalysis.column_stats`'s module docstring). Returns raw
        scalar counts; the caller (`normapi.store`, which already depends
        on `normanalysis`) wraps them into a real `ColumnStats` model —
        kept as a plain dict here so `normio` doesn't gain a dependency on
        `normanalysis`.

        `quality_sql_predicate` is always one of the fixed SQL fragments
        in `normanalysis.quality.QUALITY_METRIC_DEFS` — never raw user
        input — interpolated directly into the query because DuckDB has
        no parameter-binding form for an arbitrary boolean expression."""
        part_paths = self._part_paths(
            source_id=source_id, table=table, run_id=run_id, column=column
        )
        with self._lock:
            base_row = self._conn.execute(
                "SELECT count(*), "
                "  sum(CASE WHEN normalization_status != 'UNCHANGED' THEN 1 ELSE 0 END), "
                "  sum(CASE WHEN normalization_status = 'AMBIGUOUS' THEN 1 ELSE 0 END), "
                "  sum(len(warnings)), sum(len(errors)) "
                "FROM read_parquet(?)",
                [part_paths],
            ).fetchone()
            # An aggregate query with no GROUP BY always returns exactly
            # one row, even over zero source rows (nulls/zeros, not an
            # empty result set) — `part_paths` is also already guaranteed
            # non-empty by `_part_paths`. `fetchone()`'s `Row | None`
            # return type is never actually `None` here; the assert
            # narrows it for mypy.
            assert base_row is not None
            rows_processed, rows_changed, rows_ambiguous, warnings_total, errors_total = base_row

            unique_row = self._conn.execute(
                "SELECT "
                "  count(DISTINCT CASE WHEN original IS NOT NULL AND original != '' "
                "    THEN original END), "
                "  count(DISTINCT CASE WHEN comparison IS NOT NULL AND comparison != '' "
                "    THEN comparison END) "
                "FROM read_parquet(?)",
                [part_paths],
            ).fetchone()
            assert unique_row is not None
            unique_before, unique_after = unique_row

            quality_issue_count: int | None = None
            if quality_sql_predicate is not None:
                quality_row = self._conn.execute(
                    f"SELECT count(*) FROM read_parquet(?) WHERE {quality_sql_predicate}",
                    [part_paths],
                ).fetchone()
                assert quality_row is not None
                (quality_issue_count,) = quality_row

        return {
            "rows_processed": rows_processed or 0,
            "rows_changed": rows_changed or 0,
            "rows_ambiguous": rows_ambiguous or 0,
            "warnings_total": warnings_total or 0,
            "errors_total": errors_total or 0,
            "unique_before": unique_before or 0,
            "unique_after": unique_after or 0,
            "quality_issue_count": quality_issue_count,
        }

    def _part_paths(
        self, *, source_id: str, table: str, run_id: str, column: str = ""
    ) -> list[str]:
        with self._lock:
            parts = self._conn.execute(
                "SELECT part_path FROM sidecar_catalog WHERE source_id = ? AND table_name = ? "
                "AND column_name = ? AND run_id = ? ORDER BY part_path",
                [source_id, table, column, run_id],
            ).fetchall()
        if not parts:
            msg = (
                f"No sidecar data for source_id={source_id!r} table={table!r} "
                f"column={column!r} run_id={run_id!r}"
            )
            raise FileNotFoundError(msg)
        return [row[0] for row in parts]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SidecarStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _as_table(batch: pa.RecordBatch) -> pa.Table:
    return pa.Table.from_batches([batch])
