"""LOCAL_VERIFY D5: does the cast gate agree with the REAL destination columns?

Each value goes through `normio.storage_types.coerce` and, when the gate accepts it, through the
app's own destination writer (`bulk_insert`) into a real typed column; the stored value is read
back by direct SQL. Isolated `normbench` stack only (test credentials from the project fixtures).
"""

from __future__ import annotations

import json
import sys

import clickhouse_connect
import psycopg
from normio.connector import ColumnInfo
from normio.connectors.clickhouse_destination import ClickHouseDestination
from normio.connectors.postgres_destination import PostgresDestination
from normio.storage_types import coerce, sql_type

NINES = "9" * 29
VALUES = {
    "NUMERIC": [
        f"{NINES}.9999999994",  # fits Decimal(38,9) after rounding: gate accepts
        f"{NINES}.9999999995",  # carries into a 30th integer digit: gate rejects
        "1e999",
        "10000000000000000000000000000000000000000",  # 1e40
        "0.0000000005",  # half of ClickHouse's last digit: rounds or truncates?
        "0.00001",
        "1" + "0" * 131071,  # 131072 integer digits: Postgres maximum
        "1e131072",  # one digit more
        "1e-16383",
        "1e-16384",
    ],
    "MONEY": ["1e40", "0.00001", "0.00005", "12.34565", "99999999999999999999999999999999.99995"],
}
DB = "d5probe"


def main() -> None:
    out = []
    pg = PostgresDestination("localhost", 5535, "normalization", "normalization")
    ch = ClickHouseDestination("localhost", 8124, "writable_user", "writable_pass")
    with psycopg.connect(
        "postgresql://normalization:normalization@localhost:5535/postgres", autocommit=True
    ) as c:
        c.execute(f"DROP DATABASE IF EXISTS {DB}")
        c.execute(f"CREATE DATABASE {DB}")
    chc = clickhouse_connect.get_client(
        host="localhost", port=8124, username="writable_user", password="writable_pass"
    )
    chc.command(f"DROP DATABASE IF EXISTS {DB}")
    chc.command(f"CREATE DATABASE {DB}")
    for engine, dest in (("postgres", pg), ("clickhouse", ch)):
        for stype, values in VALUES.items():
            for i, raw in enumerate(values):
                table = f"t_{stype.lower()}_{i}"
                cols = [ColumnInfo("id", "INTEGER"), ColumnInfo("v", "TEXT")]
                key = {"primary_key": ["id"]} if engine == "postgres" else {"order_by": ["id"]}
                typed = {
                    "v": sql_type(stype, engine) or ""
                }  # what clone_executor passes (column_overrides)
                dest.create_table(
                    DB, table, cols, semantic_types={"v": stype}, column_overrides=typed, **key
                )
                cast, gate_error = coerce(stype, raw, engine)
                row = {
                    "engine": engine,
                    "type": stype,
                    "column": sql_type(stype, engine),
                    "input": raw if len(raw) < 60 else f"{raw[:12]}...({len(raw)} chars)",
                    "gate": "reject" if gate_error else "accept",
                }
                if gate_error is None:
                    try:
                        dest.bulk_insert(DB, table, [{"id": 1, "v": cast}], primary_key=["id"])
                        row["insert"] = "ok"
                    except Exception as exc:  # the D5 failure class: an INSERT abort
                        row["insert"] = f"ERROR {type(exc).__name__}: {str(exc)[:160]}"
                if engine == "postgres":
                    with psycopg.connect(
                        f"postgresql://normalization:normalization@localhost:5535/{DB}"
                    ) as c:
                        got = c.execute(f"SELECT v::text FROM {table}").fetchall()
                else:
                    got = chc.query(f"SELECT toString(v) FROM {DB}.{table}").result_rows
                stored = got[0][0] if got else None
                row["stored"] = (
                    stored if stored is None or len(stored) < 60 else f"({len(stored)} chars)"
                )
                out.append(row)
    json.dump(out, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
