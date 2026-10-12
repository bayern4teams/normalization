"""F-PG-COLNAME reproducer: which column names the destination writers accept.

Each name goes through the app's own `create_table` + `bulk_insert` (the calls a clone makes) on
the isolated `normbench` stack. Prints ok or the first error line per writer and name.
"""

from __future__ import annotations

import clickhouse_connect
import psycopg
from normio.connector import ColumnInfo
from normio.connectors.clickhouse_destination import ClickHouseDestination
from normio.connectors.postgres_destination import PostgresDestination

NAMES = ["a.b", "first name", "x-y", "çity", 'q"uote', "b`tick", "a:b", "%(x)s", "ok_col"]
DB = "colname_out"


def _try(fn: object) -> str:
    try:
        fn()  # type: ignore[operator]
    except Exception as exc:  # the result is the error text
        return f"ERROR {type(exc).__name__}: {str(exc).splitlines()[0][:90]}"
    return "ok"


def main() -> None:
    with psycopg.connect(
        "postgresql://normalization:normalization@localhost:5535/postgres", autocommit=True
    ) as c:
        c.execute(f"DROP DATABASE IF EXISTS {DB}")
        c.execute(f"CREATE DATABASE {DB}")
    ch = clickhouse_connect.get_client(
        host="localhost", port=8124, username="writable_user", password="writable_pass"
    )
    ch.command(f"DROP DATABASE IF EXISTS {DB}")
    ch.command(f"CREATE DATABASE {DB}")
    pg = PostgresDestination("localhost", 5535, "normalization", "normalization")
    chd = ClickHouseDestination("localhost", 8124, "writable_user", "writable_pass")
    for i, name in enumerate(NAMES):
        cols = [ColumnInfo("id", "INTEGER"), ColumnInfo(name, "TEXT")]
        row = [{"id": 1, name: "v"}]
        t = f"t{i}"
        print(
            repr(name).ljust(12),
            "| PG ddl",
            _try(lambda t=t, cols=cols: pg.create_table(DB, t, cols, primary_key=["id"])),
            "| PG insert",
            _try(lambda t=t, row=row: pg.bulk_insert(DB, t, row, primary_key=["id"])),
            "| CH ddl",
            _try(lambda t=t, cols=cols: chd.create_table(DB, t, cols, order_by=["id"])),
            "| CH insert",
            _try(lambda t=t, row=row: chd.bulk_insert(DB, t, row)),
        )


if __name__ == "__main__":
    main()
