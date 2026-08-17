"""Sidecar store — Parquet + DuckDB catalog, Source.txt §8, §105, §106;
design in docs/adr/ADR-013-normalization-storage.md.

Output is partitioned Parquet (`{source_id}/{table}/{run_id}/part-N.parquet`)
cataloged in a DuckDB table, never a write back to the source system. This
is the ONLY place in the codebase that writes normalized data to disk.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pa_parquet


class SidecarStore:
    def __init__(self, parquet_root: str | Path, duckdb_path: str | Path) -> None:
        self._parquet_root = Path(parquet_root)
        self._parquet_root.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(duckdb_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sidecar_catalog ("
            "  source_id VARCHAR,"
            "  table_name VARCHAR,"
            "  run_id VARCHAR,"
            "  part_path VARCHAR,"
            "  row_count BIGINT,"
            "  written_at TIMESTAMP DEFAULT current_timestamp,"
            "  PRIMARY KEY (source_id, table_name, run_id, part_path)"
            ")"
        )

    def write_batch(
        self,
        *,
        source_id: str,
        table: str,
        run_id: str,
        batch: pa.RecordBatch,
        part_index: int,
    ) -> Path:
        partition_dir = self._parquet_root / source_id / table / run_id
        partition_dir.mkdir(parents=True, exist_ok=True)
        part_path = partition_dir / f"part-{part_index:06d}.parquet"

        pa_parquet.write_table(_as_table(batch), part_path)

        self._conn.execute(
            "INSERT OR REPLACE INTO sidecar_catalog "
            "(source_id, table_name, run_id, part_path, row_count) VALUES (?, ?, ?, ?, ?)",
            [source_id, table, run_id, str(part_path), batch.num_rows],
        )
        return part_path

    def read_run(self, *, source_id: str, table: str, run_id: str) -> pa.Table:
        parts = self._conn.execute(
            "SELECT part_path FROM sidecar_catalog "
            "WHERE source_id = ? AND table_name = ? AND run_id = ? ORDER BY part_path",
            [source_id, table, run_id],
        ).fetchall()
        if not parts:
            msg = f"No sidecar data for source_id={source_id!r} table={table!r} run_id={run_id!r}"
            raise FileNotFoundError(msg)
        return pa_parquet.read_table([row[0] for row in parts])

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SidecarStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _as_table(batch: pa.RecordBatch) -> pa.Table:
    return pa.Table.from_batches([batch])
