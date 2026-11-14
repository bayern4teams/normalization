"""D33, live: a ClickHouse String column whose block holds both text and bytes
that are not UTF-8 (`clone_executor._restore_undecodable` keeps those bytes)
is written byte for byte. The driver's String writer took only `str` and
failed the whole insert on the first `bytes` value.

Point it at any ClickHouse with TEST_CLICKHOUSE_* (the compose stack by
default); it creates and drops its own database.
"""

from __future__ import annotations

import os
import uuid

import clickhouse_connect
import pytest
from normio.connector import ColumnInfo
from normio.connectors.clickhouse_destination import ClickHouseDestination
from normio.connectors.clickhouse_destination import quote_identifier as ch_q

pytestmark = pytest.mark.integration

CH_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.environ.get("TEST_CLICKHOUSE_PORT", "8124"))
_W = {
    "username": os.environ.get("TEST_CLICKHOUSE_USER", "writable_user"),
    "password": os.environ.get("TEST_CLICKHOUSE_PASSWORD", "writable_pass"),
}
_CAFE_LATIN1 = bytes.fromhex("636166e9")  # "café" in Latin-1, not valid UTF-8


def test_a_block_of_text_and_undecodable_bytes_is_written_byte_for_byte() -> None:
    ch = clickhouse_connect.get_client(host=CH_HOST, port=CH_PORT, **_W)
    db = f"norm_r4_{uuid.uuid4().hex[:8]}"
    ch.command(f"CREATE DATABASE {ch_q(db)}")
    try:
        dest = ClickHouseDestination(CH_HOST, CH_PORT, **_W)
        dest.create_table(
            db,
            "t",
            [
                ColumnInfo(name="id", native_type="Int64"),
                ColumnInfo(name="notes", native_type="Nullable(String)"),
            ],
            order_by=["id"],
        )
        dest.bulk_insert(
            db,
            "t",
            [
                {"id": 1, "notes": "plain"},
                {"id": 2, "notes": _CAFE_LATIN1},
                {"id": 3, "notes": None},
            ],
        )
        dest.close()
        rows = ch.query(f"SELECT id, hex(notes), isNull(notes) FROM {ch_q(db)}.t ORDER BY id")
        assert rows.result_rows == [
            (1, b"plain".hex().upper(), 0),
            (2, _CAFE_LATIN1.hex().upper(), 0),
            (3, None, 1),  # hex(NULL) is NULL
        ]
    finally:
        ch.command(f"DROP DATABASE IF EXISTS {ch_q(db)}")
