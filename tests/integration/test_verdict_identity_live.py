"""Live counterpart of tests/unit/test_verdict_identity.py (PART1 D1.5) against
real ClickHouse, with the queue on a real Postgres metadata database.

A ClickHouse table killed mid-run starts over on resume; its AMBIGUOUS values
were counted in the queue a second time. Locally, point the ports at an
isolated stack (TEST_PG_PORT etc.), never at a database you care about.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest
from normapi.pg_persistence import PgPersistence
from normio.connector import ColumnInfo
from normio.connectors.clickhouse_destination import ClickHouseDestination
from normio.connectors.clickhouse_destination import quote_identifier as ch_q
from tests.integration.test_followups_live import (
    _RUN,
    _W,
    BLOCK,
    CH_HOST,
    CH_PORT,
    ROWS,
    _pg_dsn,
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    ch,  # noqa: F401 - fixture
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    ch_db,  # noqa: F401 - fixture
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    pg_db,  # noqa: F401 - fixture
)

pytestmark = pytest.mark.integration

# The kill-and-resume child of test_followups_live, with the queue switched on.
_RUN_QUEUED = _RUN.replace(
    "adjudication=None,",
    "adjudication=Adjudication(store, SCAFFOLD_PROFILE),",
).replace(
    "import os, sys\n",
    "import os, sys\n"
    "from normapi.adjudication import Adjudication\n"
    "from normapi.scaffold_profile import SCAFFOLD_PROFILE\n",
)
_AMBIGUOUS = "03/04/2024"


# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
def test_a_restarted_clickhouse_table_is_counted_once(ch: Any, ch_db: str, pg_db: str) -> None:  # noqa: F811
    assert "adjudication=Adjudication(" in _RUN_QUEUED
    src = f"{ch_db}_src"
    ch.command(f"CREATE DATABASE {ch_q(src)}")
    try:
        # Three parts, no sorting key: the shape that cannot resume by offset.
        ch.command(f"CREATE TABLE {ch_q(src)}.t (id UInt64, amt String) ORDER BY tuple()")
        for part in range(3):
            ch.command(
                f"INSERT INTO {ch_q(src)}.t SELECT number, "
                f"if(number % 3 = 2, '{_AMBIGUOUS}', '2024-12-31') "
                f"FROM numbers({part * ROWS // 3}, {ROWS // 3})"
            )
        dest = ClickHouseDestination(CH_HOST, CH_PORT, **_W)
        dest.create_table(
            ch_db,
            "t",
            [
                ColumnInfo(name="id", native_type="UInt64"),
                ColumnInfo(name="amt", native_type="String"),
            ],
            order_by=["id"],
        )
        dest.close()
        meta = _pg_dsn(pg_db)
        store = PgPersistence(meta)
        store.ensure_schema()
        store.create_clone_job(
            "j",
            {
                "source_connection_id": "s",
                "source_identity": f"clickhouse://{CH_HOST}:{CH_PORT}/{src}",
                "destination_database": ch_db,
                "field_configs": {"t": {"amt": "DATE"}},
                "destination_plan": {"t": {"typed_columns": {}}},
                "progress": {
                    "checkpoints": {},
                    "rows_done": 0,
                    "current_table": None,
                    "insert_block_rows": {"t": BLOCK},
                },
                "country": None,
                "locale": None,
                "status": "FAILED",
            },
        )
        args = ["clickhouse", src, ch_db, meta, CH_HOST, str(CH_PORT)]
        killed = subprocess.run([sys.executable, "-c", _RUN_QUEUED, *args, "2"], check=False)
        assert killed.returncode == 137
        resumed = subprocess.run([sys.executable, "-c", _RUN_QUEUED, *args, "0"], check=False)
        assert resumed.returncode == 0

        (count,) = ch.query(
            f"SELECT countIf(amt = '{_AMBIGUOUS}') FROM {ch_q(ch_db)}.t"
        ).result_rows[0]
        assert count == ROWS // 3
        _, rows = store.list_queue(semantic_type="DATE", decided=None, limit=10, offset=0)
        assert [(r["original"], r["occurrences"]) for r in rows] == [(_AMBIGUOUS, ROWS // 3)]
    finally:
        ch.command(f"DROP DATABASE IF EXISTS {ch_q(src)}")
