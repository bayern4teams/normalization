"""FileConnector — CSV, Parquet, and Excel sources (Source.txt §105).

Files are inherently read-only from this connector's perspective (it never
opens a file for writing), but the "read-only credentials" concern that
matters for database connectors doesn't apply the same way here — the
enforcement is simply that this class has no write method, per the
SourceConnector protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import openpyxl
import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pa_parquet

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

_SUPPORTED_SUFFIXES = {".csv", ".parquet", ".xlsx"}


class FileConnector:
    """`base_dir` scopes every readable file — `read_table` takes a
    filename (with extension) relative to it, never an absolute or
    parent-escaping path, so a connector configured against one directory
    cannot read arbitrary filesystem locations.
    """

    def __init__(self, source_id: str, base_dir: str | Path) -> None:
        self.source_id = source_id
        self._base_dir = Path(base_dir).resolve()

    def list_tables(self) -> Sequence[str]:
        return sorted(
            p.name
            for p in self._base_dir.iterdir()
            if p.is_file() and p.suffix.lower() in _SUPPORTED_SUFFIXES
        )

    def _resolve(self, table: str) -> Path:
        path = (self._base_dir / table).resolve()
        if self._base_dir not in path.parents and path != self._base_dir:
            msg = f"Refusing to read outside base_dir: {table!r}"
            raise ValueError(msg)
        if not path.exists():
            msg = f"File not found: {path}"
            raise FileNotFoundError(msg)
        return path

    def read_table(
        self,
        table: str,
        *,
        columns: Sequence[str] | None = None,
        batch_size: int = 100_000,
    ) -> Iterator[pa.RecordBatch]:
        path = self._resolve(table)
        suffix = path.suffix.lower()

        if suffix == ".parquet":
            yield from self._read_parquet(path, columns, batch_size)
        elif suffix == ".csv":
            yield from self._read_csv(path, columns, batch_size)
        elif suffix == ".xlsx":
            yield from self._read_excel(path, columns, batch_size)
        else:
            msg = f"Unsupported file type: {suffix}"
            raise ValueError(msg)

    def _read_parquet(
        self, path: Path, columns: Sequence[str] | None, batch_size: int
    ) -> Iterator[pa.RecordBatch]:
        parquet_file = pa_parquet.ParquetFile(path)
        row_offset = 0
        for batch in parquet_file.iter_batches(batch_size=batch_size, columns=columns):
            yield _with_row_key(batch, row_offset, path.stem)
            row_offset += batch.num_rows

    def _read_csv(
        self, path: Path, columns: Sequence[str] | None, batch_size: int
    ) -> Iterator[pa.RecordBatch]:
        convert_options = pa_csv.ConvertOptions(include_columns=columns) if columns else None
        reader = pa_csv.open_csv(
            path,
            read_options=pa_csv.ReadOptions(block_size=batch_size * 128),
            convert_options=convert_options,
        )
        row_offset = 0
        for batch in reader:
            yield _with_row_key(batch, row_offset, path.stem)
            row_offset += batch.num_rows

    def _read_excel(
        self, path: Path, columns: Sequence[str] | None, batch_size: int
    ) -> Iterator[pa.RecordBatch]:
        # openpyxl has no native Arrow batching API — read fully, then
        # rebatch. Excel sources are not expected to reach the row counts
        # CSV/Parquet do; this is an accepted trade-off for M1.
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        rows_iter = sheet.iter_rows(values_only=True)
        header = list(next(rows_iter))
        col_indices = [header.index(c) for c in columns] if columns else list(range(len(header)))
        selected_header = [header[i] for i in col_indices]

        rows_buffer: list[tuple[object, ...]] = []
        row_offset = 0
        for row in rows_iter:
            rows_buffer.append(tuple(row[i] for i in col_indices))
            if len(rows_buffer) >= batch_size:
                yield _rows_to_batch(rows_buffer, selected_header, row_offset, path.stem)
                row_offset += len(rows_buffer)
                rows_buffer = []
        if rows_buffer:
            yield _rows_to_batch(rows_buffer, selected_header, row_offset, path.stem)
        workbook.close()

    def close(self) -> None:
        """No persistent connection to release — files are opened and
        closed per read_table() call. Present to satisfy SourceConnector.
        """


def _with_row_key(batch: pa.RecordBatch, row_offset: int, table_name: str) -> pa.RecordBatch:
    keys = pa.array(
        [f"{table_name}:{row_offset + i}" for i in range(batch.num_rows)], type=pa.large_string()
    )
    return batch.append_column("source_row_key", keys)


def _rows_to_batch(
    rows: list[tuple[object, ...]], header: list[str], row_offset: int, table_name: str
) -> pa.RecordBatch:
    columns_data: list[list[object]] = [[] for _ in header]
    for row in rows:
        for i, value in enumerate(row):
            columns_data[i].append(value)
    arrays = [pa.array(col) for col in columns_data]
    keys = pa.array(
        [f"{table_name}:{row_offset + i}" for i in range(len(rows))], type=pa.large_string()
    )
    return pa.RecordBatch.from_arrays([*arrays, keys], names=[*header, "source_row_key"])
