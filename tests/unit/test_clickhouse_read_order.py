"""ClickHouse reads must be deterministically ordered.

`source_row_key` is assigned by arrival position and the clone executor's
resume skips every row whose offset is <= the last checkpoint, so an
unordered read makes resume silently produce a clone with both duplicates
and holes. Verified against a real 1.27M-row table: without ORDER BY, the
same query returned two disjoint row sets at offset 300000; with it,
6000/6000 source_row_key -> row mappings were identical across reads.

The integration suite cannot catch this — its tables are small enough to
be a single part read by a single thread, which is stable by accident.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest
from normio.connectors import ClickHouseConnector
from normio.connectors import clickhouse as ch_module


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.result_rows = rows


class _FakeClient:
    """Answers the metadata queries `read_table` makes, and records the
    data query it builds."""

    def __init__(self, sorting_key: str) -> None:
        self._sorting_key = sorting_key
        self.data_queries: list[str] = []

    def query(self, sql: str, parameters: dict[str, Any] | None = None) -> _FakeResult:
        if "system.tables" in sql and "sorting_key" in sql:
            return _FakeResult([("MergeTree", self._sorting_key)])
        if "system.tables" in sql:
            return _FakeResult([("Company",)])
        if "system.columns" in sql:
            return _FakeResult([("companyID",), ("companyName",)])
        raise AssertionError(sql)

    def query_arrow_stream(self, sql: str) -> Any:
        self.data_queries.append(sql)
        return _FakeStream()

    def close(self) -> None:
        pass


class _FakeStream:
    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def __iter__(self) -> Any:
        yield pa.RecordBatch.from_arrays(
            [pa.array(["a", "b"]), pa.array(["x", "y"])], names=["companyID", "companyName"]
        )


def _connector(monkeypatch: pytest.MonkeyPatch, sorting_key: str) -> tuple[Any, _FakeClient]:
    fake = _FakeClient(sorting_key)
    monkeypatch.setattr(ch_module.clickhouse_connect, "get_client", lambda **_kw: fake)
    conn = ClickHouseConnector("src", "host", port=8123, username="u", password="p", database="db")
    return conn, fake


def test_read_table_orders_by_the_tables_sorting_key(monkeypatch: pytest.MonkeyPatch) -> None:
    conn, fake = _connector(monkeypatch, "companyID")
    list(conn.read_table("Company", batch_size=10))
    assert fake.data_queries == ["SELECT * FROM `Company` ORDER BY `companyID`"]


def test_read_table_orders_by_every_sorting_key_column(monkeypatch: pytest.MonkeyPatch) -> None:
    conn, fake = _connector(monkeypatch, "companyID, companyName")
    list(conn.read_table("Company", batch_size=10))
    assert fake.data_queries == ["SELECT * FROM `Company` ORDER BY `companyID`, `companyName`"]


def test_read_table_omits_order_by_when_the_table_has_no_sorting_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ENGINE = ... ORDER BY tuple() reports an empty sorting_key. There is
    # no deterministic order to ask for, so emit none rather than invalid
    # SQL — such a table simply cannot support positional resume.
    conn, fake = _connector(monkeypatch, "")
    list(conn.read_table("Company", batch_size=10))
    assert fake.data_queries == ["SELECT * FROM `Company`"]


def test_row_keys_are_contiguous_and_table_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    conn, _ = _connector(monkeypatch, "companyID")
    keys = [
        k
        for batch in conn.read_table("Company", batch_size=10)
        for k in batch.column("source_row_key").to_pylist()
    ]
    assert keys == ["Company:0", "Company:1"]
