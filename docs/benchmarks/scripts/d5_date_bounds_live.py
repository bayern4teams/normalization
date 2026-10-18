"""PART1 D5.3 live: DATE keeps its TEXT value and gains typed <col>__from / <col>__to.

Creates a small source table on the isolated normbench stack, clones it through the real
API (clone_bench.py), then reads the destination with direct SQL: the column types from the
catalogue and every row's (value, from, to).

    uv run python docs/benchmarks/scripts/d5_date_bounds_live.py --engine postgres --out x.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid

import clickhouse_connect
import psycopg

ROWS = [
    (0, "1990"),  # a year: the whole year
    (1, "1990-03"),  # a month
    (2, "2024-02-29"),  # a full date: itself twice
    (3, "199X"),  # EDTF decade: 1990-01-01..1999-12-31
    (4, "03/04/2024"),  # AMBIGUOUS without a locale: no bounds
    (5, "not a date"),  # INVALID: no bounds
    (6, "1850-06-01"),  # outside ClickHouse Date32: NULL + error row there, a date on Postgres
]


def _pg(port: int, user: str, pw: str, db: str) -> psycopg.Connection:
    return psycopg.connect(f"postgresql://{user}:{pw}@localhost:{port}/{db}", autocommit=True)


def _ch() -> object:
    return clickhouse_connect.get_client(
        host="localhost", port=8124, username="writable_user", password="writable_pass"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["postgres", "clickhouse"], required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    tag = uuid.uuid4().hex[:8]
    src, dst = f"d5b_src_{tag}", f"d5b_out_{tag}"
    if args.engine == "postgres":
        with _pg(5436, "source_admin", "source_admin", "postgres") as c:
            c.execute(f'CREATE DATABASE "{src}"')
        with _pg(5436, "source_admin", "source_admin", src) as c:
            c.execute("CREATE TABLE t (id int PRIMARY KEY, d text)")
            c.cursor().executemany("INSERT INTO t VALUES (%s, %s)", ROWS)
            c.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user")
    else:
        ch = _ch()
        ch.command(f"CREATE DATABASE `{src}`")
        ch.command(f"CREATE TABLE `{src}`.t (id Int32, d String) ENGINE = MergeTree ORDER BY id")
        ch.insert(f"`{src}`.t", [list(r) for r in ROWS], column_names=["id", "d"])
    fc = f".tmp/d5b_{tag}.json"
    with open(fc, "w") as fh:
        json.dump({"t": {"d": "DATE"}}, fh)
    bench = f".tmp/d5b_{tag}_bench.json"
    subprocess.run(
        [sys.executable, "docs/benchmarks/scripts/clone_bench.py", "--engine", args.engine,
         "--src-db", src, "--dst-db", dst, "--no-autodetect", "--field-configs", fc,
         "--out", bench],
        check=True,
    )  # fmt: skip
    job = json.load(open(bench))  # noqa: SIM115 - a script
    if args.engine == "postgres":
        with _pg(5535, "normalization", "normalization", dst) as c:
            types = c.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 't' ORDER BY ordinal_position"
            ).fetchall()
            rows = c.execute("SELECT id, d, d__from, d__to FROM t ORDER BY id").fetchall()
    else:
        ch = _ch()
        types = ch.query(
            f"SELECT name, type FROM system.columns WHERE database = '{dst}' AND table = 't'"
        ).result_rows
        rows = ch.query(f"SELECT id, d, d__from, d__to FROM `{dst}`.t ORDER BY id").result_rows
    with _pg(5535, "normalization", "normalization", "normalization") as c:
        errors = c.execute(
            "SELECT row_index, field, error FROM normalization_clone_job_errors "
            "WHERE job_id = %s ORDER BY row_index",
            (job["job_id"],),
        ).fetchall()
    out = {
        "engine": args.engine,
        "status": job.get("status"),
        "types": types,
        "rows": rows,
        "errors": errors,
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
