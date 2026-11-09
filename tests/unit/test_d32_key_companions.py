"""D32 (owner "b8b. a", C5 "a"): a configured key column keeps the source value;
its normalized value goes to `<col>_normalized`, so two keys can never collide."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pytest
from normapi.app import build_dispatcher
from normapi.clone_executor import CloneJobStateError, _normalize_table, plan_one_table
from normapi.pg_persistence import PgPersistence
from normexec.planner import DistinctValuePlanner
from normio.connector import ColumnInfo

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


class _Source:
    def __init__(self, *columns: ColumnInfo, key: tuple[str, ...] = ("email",)) -> None:
        self.columns, self.key = list(columns), list(key)

    def get_columns(self, table: str) -> list[ColumnInfo]:
        return self.columns

    def get_primary_key(self, table: str) -> list[str]:
        return self.key

    def read_table(self, *a: Any, **k: Any) -> Iterator[pa.RecordBatch]:
        yield pa.RecordBatch.from_pydict(
            {
                "email": ["a@B.com", "a@b.com"],
                "source_row_key": ["t:0", "t:1"],
            }
        )


_EMAIL = ColumnInfo(name="email", native_type="text")


class _Dest:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def bulk_insert(self, database: str, table: str, rows: list[Any], **kw: Any) -> None:
        self.rows.extend(rows)


def _job(**plan: Any) -> dict[str, Any]:
    return {
        "source_connection_id": "s",
        "source_identity": "postgres://s:5432/db",
        "destination_database": "d",
        "field_configs": {"t": {"email": "EMAIL"}},
        "destination_plan": {"t": {"typed_columns": {}, **plan}},
        "progress": {
            "checkpoints": {},
            "rows_done": 0,
            "current_table": None,
            "insert_block_rows": {"t": 100},
        },
    }


def test_both_keys_are_kept_and_the_companion_holds_the_normalized_value(tmp_path: Path) -> None:
    store = PgPersistence(f"sqlite:///{tmp_path}/m.db")
    store.ensure_schema()
    job = _job(key_normalized_columns={"email": "email_normalized"})
    dest = _Dest()
    _normalize_table(
        "t",
        job=job,
        job_id="j",
        source=_Source(_EMAIL),
        dest=dest,
        source_engine="postgres",
        persistence=store,
        planner=DistinctValuePlanner(build_dispatcher(env_id="e"), None),
        pool=None,
        progress=job["progress"],
        entity_countries={},
        adjudication=None,
    )
    assert [r["email"] for r in dest.rows] == ["a@B.com", "a@b.com"]
    assert [r["email_normalized"] for r in dest.rows] == ["a@b.com", "a@b.com"]


def test_the_plan_adds_the_companion_and_keeps_the_key_type() -> None:
    column = ColumnInfo(name="email", native_type="citext")
    plan = plan_one_table(_Source(column), "postgres", "t", _job())
    assert plan["extra_columns"] == {"email_normalized": "TEXT"}
    assert plan["key_normalized_columns"] == {"email": "email_normalized"}
    assert plan["ddl_semantic_types"] == {}


def test_an_unconfigured_key_gets_no_companion() -> None:
    job = _job()
    job["field_configs"] = {"t": {}}
    plan = plan_one_table(_Source(_EMAIL), "postgres", "t", job)
    assert plan["extra_columns"] == {}
    assert plan["key_normalized_columns"] == {}


def test_a_configured_column_outside_the_key_is_unchanged() -> None:
    plan = plan_one_table(_Source(_EMAIL, key=()), "postgres", "t", _job())
    assert plan["extra_columns"] == {}
    assert plan["ddl_semantic_types"] == {"email": "EMAIL"}


def test_a_source_column_with_a_companions_name_stops_the_job() -> None:
    clash = ColumnInfo(name="email_normalized", native_type="text")
    with pytest.raises(CloneJobStateError, match="email_normalized"):
        plan_one_table(_Source(_EMAIL, clash), "postgres", "t", _job())
