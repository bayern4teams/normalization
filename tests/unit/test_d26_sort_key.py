"""D26: `system.tables.sorting_key` is parsed by its syntax, not split on commas.

The key strings are the ones ClickHouse 26.8.2.7 returned on the benchmark
machine, plus the spelled-out `tuple()`. Only the driver client is faked.
"""

from __future__ import annotations

from typing import Any

import pytest
from normio.connector import ColumnInfo
from normio.connectors.clickhouse import ClickHouseConnector
from normio.connectors.clickhouse_destination import ClickHouseDestination

from normapi import clone_executor

pytestmark = pytest.mark.unit


class _Sent(Exception):
    pass


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.result_rows = rows


class _Client:
    def __init__(self, key: str, columns: tuple[str, ...]) -> None:
        self.key, self.columns, self.sent = key, columns, ""

    def query(self, sql: str, parameters: Any = None) -> _Result:
        if "sorting_key" in sql:
            return _Result([("ReplacingMergeTree", self.key)])
        if "system.columns" in sql:
            return _Result([(c, "String") for c in self.columns])
        return _Result([("t",)])

    def query_arrow_stream(self, query: str) -> Any:
        self.sent = query
        raise _Sent


def _source(key: str, *columns: str) -> tuple[ClickHouseConnector, _Client]:
    source = ClickHouseConnector.__new__(ClickHouseConnector)
    client = _Client(key, columns)
    source._client, source._database = client, "db"
    return source, client


@pytest.mark.parametrize(
    ("key", "columns"),
    [
        ("id", ["id"]),
        ("(id)", ["id"]),
        ("a, b", ["a", "b"]),
        ("(a, b)", ["a", "b"]),
        ("`x,y`, b", ["x,y", "b"]),
        ("(`x,y`, b)", ["x,y", "b"]),
        ("`b\\`t`, a", ["b`t", "a"]),
        ("toDate(ts)", ["ts"]),
        ("(toDate(ts), id)", ["ts", "id"]),
        ("cityHash64(a, b), a", ["a", "b"]),
        ("replaceAll(a, ',', ')'), b", ["a", "b"]),
        ("", []),
        ("tuple()", []),
        # Reported by ClickHouse 26.4.2.10 on the owner's database machine.
        ("companyID", ["companyID"]),
        (
            "companyID, relatedCompanyID, relationType",
            ["companyID", "relatedCompanyID", "relationType"],
        ),
        (
            "database, `table`, event_date, event_time",
            ["database", "table", "event_date", "event_time"],
        ),
    ],
)
def test_the_key_columns_are_what_clickhouse_means(key: str, columns: list[str]) -> None:
    source, _ = _source(key, "id", "a", "b", "ts", "x,y", "b`t", "companyID")
    assert source.get_table_engine_info("t") == ("ReplacingMergeTree", columns)


@pytest.mark.parametrize(
    ("key", "order_by"),
    [
        ("(id)", " ORDER BY `id`"),
        ("(a, b)", " ORDER BY `a`, `b`"),
        ("(`x,y`, b)", " ORDER BY `x,y`, `b`"),
        ("toDate(ts)", " ORDER BY toDate(ts)"),
        ("(a) + (b)", " ORDER BY (a) + (b)"),
        ("", ""),
        ("database, `table`, event_date", " ORDER BY `database`, `table`, `event_date`"),
    ],
)
def test_the_read_orders_by_the_key_as_written(key: str, order_by: str) -> None:
    source, client = _source(key, "id", "a", "b", "ts", "x,y")
    with pytest.raises(_Sent):
        next(iter(source.read_table("t")))
    assert client.sent == f"SELECT * FROM `t`{order_by}"


@pytest.mark.parametrize("key", ["(a", "a)", "`a", "f('a"])
def test_a_key_that_cannot_be_parsed_stops_the_job(key: str) -> None:
    source, _ = _source(key, "a")
    with pytest.raises(ValueError, match="sorting_key"):
        source.get_table_engine_info("t")


def _job(**field_configs: str) -> dict[str, Any]:
    return {"field_configs": {"t": field_configs}}


def test_an_expression_key_on_a_retyped_column_fails_and_says_why() -> None:
    source, _ = _source("toDate(ts), id", "ts", "id")
    with pytest.raises(clone_executor.CloneJobStateError, match=r"toDate\(ts\).*'ts'|'ts'.*key"):
        clone_executor.plan_one_table(source, "clickhouse", "t", _job(ts="DATETIME"))


def test_an_expression_key_on_untouched_columns_is_copied_verbatim() -> None:
    source, _ = _source("toDate(ts), id", "ts", "id", "v")
    plan = clone_executor.plan_one_table(source, "clickhouse", "t", _job(v="EMAIL"))
    assert plan["key_columns"] == ["ts", "id"]
    assert plan["sort_key_sql"] == ["toDate(ts)", "`id`"]


def test_the_destination_ddl_replays_the_expression() -> None:
    sent: list[str] = []

    class _Dest:
        def command(self, sql: str) -> None:
            sent.append(sql)

    dest = ClickHouseDestination("h", 1, "u", "p")
    dest._clients["d"] = _Dest()
    cols = [ColumnInfo(name="ts", native_type="DateTime")]
    dest.create_table("d", "t", cols, order_by=["ts"], sort_key_sql=["toDate(ts)"])
    assert "ORDER BY (toDate(ts))" in sent[0]
    assert "`ts` DateTime" in sent[0]
