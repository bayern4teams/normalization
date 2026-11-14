"""D33: an UNCONFIGURED text column holding bytes that are not UTF-8 keeps them
unchanged and says why in an error row, as a configured one does
(`test_clone_undecodable_bytes.py`). A column the source types as binary is
not text, so its bytes are never reported."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pytest
from normapi.app import build_dispatcher
from normapi.clone_executor import _normalize_table
from normapi.pg_persistence import PgPersistence
from normexec.planner import DistinctValuePlanner
from normio.connector import ColumnInfo

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit

_CAFE_LATIN1 = bytes.fromhex("636166e9")  # "café" in Latin-1, not valid UTF-8


class _Source:
    def get_columns(self, table: str) -> list[ColumnInfo]:
        return [
            ColumnInfo(name="notes", native_type="Nullable(String)"),
            ColumnInfo(name="blob", native_type="bytea"),
        ]

    def get_primary_key(self, table: str) -> list[str]:
        return []

    def read_table(self, *a: Any, **k: Any) -> Iterator[pa.RecordBatch]:
        yield pa.RecordBatch.from_pydict(
            {
                "notes": pa.array([_CAFE_LATIN1, b"plain"], type=pa.binary()),
                "blob": pa.array([_CAFE_LATIN1, _CAFE_LATIN1], type=pa.binary()),
                "source_row_key": ["t:0", "t:1"],
            }
        )


class _Dest:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def bulk_insert(self, database: str, table: str, rows: list[Any], **kw: Any) -> None:
        self.rows.extend(rows)


def test_unconfigured_text_column_reports_undecodable_bytes(tmp_path: Path) -> None:
    store = PgPersistence(f"sqlite:///{tmp_path}/m.db")
    store.ensure_schema()
    job = {
        "source_connection_id": "s",
        "source_identity": "clickhouse://s:9000/db",
        "destination_database": "d",
        "field_configs": {"t": {}},
        "destination_plan": {"t": {"typed_columns": {}}},
        "progress": {
            "checkpoints": {},
            "rows_done": 0,
            "current_table": None,
            "insert_block_rows": {"t": 100},
        },
    }
    dest = _Dest()
    _normalize_table(
        "t",
        job=job,
        job_id="j",
        source=_Source(),
        dest=dest,
        source_engine="clickhouse",
        persistence=store,
        planner=DistinctValuePlanner(build_dispatcher(env_id="e"), None),
        pool=None,
        progress=job["progress"],
        entity_countries={},
        adjudication=None,
        source_types={c.name: c.native_type for c in _Source().get_columns("t")},
    )
    errors = store.load_clone_job_errors_page("j", limit=10, offset=0)
    assert [(e["row_index"], e["field"], e["original"], e["error"]) for e in errors] == [
        (0, "notes", "caf\\xe9", "value is not valid UTF-8; kept unchanged")
    ]
    assert dest.rows[0]["notes"] == _CAFE_LATIN1
    assert dest.rows[1]["notes"] == "plain"  # the block arrived as binary; valid bytes read as text
    assert [r["blob"] for r in dest.rows] == [_CAFE_LATIN1, _CAFE_LATIN1]
