"""A configured text column holding bytes that are not UTF-8 keeps them unchanged
and says why in an error row (`clone_executor._restore_undecodable`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pytest
from normapi.app import build_dispatcher
from normapi.clone_executor import _normalize_table
from normapi.pg_persistence import PgPersistence
from normexec.planner import DistinctValuePlanner

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit

_CAFE_LATIN1 = bytes.fromhex("636166e9")  # "café" in Latin-1, not valid UTF-8


class _Source:
    def get_columns(self, table: str) -> list[Any]:
        return []

    def get_primary_key(self, table: str) -> list[str]:
        return []

    def read_table(self, *a: Any, **k: Any) -> Iterator[pa.RecordBatch]:
        yield pa.RecordBatch.from_pydict(
            {
                "notes": pa.array([_CAFE_LATIN1, b"plain"], type=pa.binary()),
                "source_row_key": ["t:0", "t:1"],
            }
        )


class _Dest:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def bulk_insert(self, database: str, table: str, rows: list[Any], **kw: Any) -> None:
        self.rows.extend(rows)


def test_undecodable_bytes_are_kept_and_reported(tmp_path: Path) -> None:
    store = PgPersistence(f"sqlite:///{tmp_path}/m.db")
    store.ensure_schema()
    job = {
        "source_connection_id": "s",
        "source_identity": "postgres://s:5432/db",
        "destination_database": "d",
        "field_configs": {"t": {"notes": "FREE_TEXT"}},
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
        source_engine="postgres",
        persistence=store,
        planner=DistinctValuePlanner(build_dispatcher(env_id="e"), None),
        pool=None,
        progress=job["progress"],
        entity_countries={},
        adjudication=None,
    )
    assert dest.rows[0]["notes"] == _CAFE_LATIN1
    assert dest.rows[1]["notes"] == "plain"
    errors = store.load_clone_job_errors_page("j", limit=10, offset=0)
    assert [(e["row_index"], e["field"], e["original"], e["error"]) for e in errors] == [
        (0, "notes", "caf\\xe9", "value is not valid UTF-8; kept unchanged")
    ]
