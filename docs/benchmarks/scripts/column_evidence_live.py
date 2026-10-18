# ruff: noqa: E501 - SQL and report lines read better unwrapped in a one-off live check
"""ADR-008 amendment 2026-10-17 live: a column's own values state its day/month order.

Copies one real column (Raha `rayyan.article_jcreated_at`, or `--table`/`--column`) into a fresh
source database on the normbench stack, clones it through the API in-process with the column
as DATE (or NUMERIC, `--type`) and no country, and reads the destination and the metadata database by direct SQL:
how many cells kept their original (refused), the job's evidence, the queue rows, and for every
resolved cell that it is exactly the reading in the proven order. Run it on two checkouts to
compare (before / after).

    uv run python docs/benchmarks/scripts/column_evidence_live.py --out $BENCH_DIR/work/colev/after.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import uuid
from decimal import Decimal

import psycopg
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

APP_DSN = "postgresql://normalization:normalization@localhost:5535/normalization"
SRC = {"host": "localhost", "port": 5436, "username": "readonly_user", "password": "readonly_pass"}
DST = {"host": "localhost", "port": 5535, "username": "normalization", "password": "normalization"}
SINGLE_GROUP = re.compile(r"^[-+]?\d{1,3}[.,]\d{3}$")
DMY = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$")


def _pg(port: int, user: str, pw: str, db: str) -> psycopg.Connection:
    return psycopg.connect(f"postgresql://{user}:{pw}@localhost:{port}/{db}", autocommit=True)


def main() -> None:  # noqa: PLR0915 - one linear live check
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--db", default="raha")
    ap.add_argument("--table", default="rayyan")
    ap.add_argument("--column", default="article_jcreated_at")
    ap.add_argument("--type", default="DATE", choices=["DATE", "NUMERIC"])
    args = ap.parse_args()
    os.environ.setdefault("NORM_SECRET_KEY", Fernet.generate_key().decode())
    from normapi.app import create_app  # noqa: PLC0415

    with _pg(5436, "readonly_user", "readonly_pass", args.db) as c:
        values = [r[0] for r in c.execute(f'SELECT "{args.column}" FROM "{args.table}"')]
    tag = uuid.uuid4().hex[:8]
    src = f"colev_src_{tag}"
    with _pg(5436, "source_admin", "source_admin", "postgres") as c:
        c.execute(f'CREATE DATABASE "{src}"')
    with _pg(5436, "source_admin", "source_admin", src) as c:
        c.execute("CREATE TABLE t (id int PRIMARY KEY, d text)")
        c.cursor().executemany("INSERT INTO t VALUES (%s, %s)", list(enumerate(values)))
        c.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user")

    client = TestClient(
        create_app(
            pg_dsn=APP_DSN, custom_dictionaries_dir=os.environ["BENCH_DIR"] + "/work/custom-dicts"
        )
    )

    def call(method: str, path: str, **kw: object) -> dict:
        r = client.request(method, "/normalization" + path, **kw)
        if r.status_code >= 400:
            raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:2000]}")
        return r.json() if r.content else {}

    src_conn = call("POST", "/connections", json={"engine": "postgres", **SRC})["connection_id"]
    dst_conn = call("POST", "/connections", json={"engine": "postgres", **DST})["connection_id"]
    out_db = f"colev_out_{tag}"
    created = call(
        "POST",
        "/clone-jobs",
        json={
            "source_connection_id": src_conn,
            "source_database": src,
            "destination_connection_id": dst_conn,
            "destination_database": out_db,
            "autodetect_field_types": False,
            # text destination, so a refused value keeps its original in the cell
            "typed_destination_columns": False,
            "field_configs": {"t": {"d": args.type}},
        },
    )
    job_id = created["job_id"]
    with _pg(5535, "normalization", "normalization", "postgres") as c:
        c.execute(created["create_database_sql"])
    call("POST", f"/clone-jobs/{job_id}/verify-database")
    call("POST", f"/clone-jobs/{job_id}/start")
    while (job := call("GET", f"/clone-jobs/{job_id}"))["status"] not in ("COMPLETED", "FAILED"):
        time.sleep(1)

    with _pg(5535, "normalization", "normalization", out_db) as c:
        written = dict(c.execute("SELECT id, d FROM t").fetchall())
    with _pg(5535, "normalization", "normalization", "normalization") as c:
        queued = c.execute(
            "SELECT count(*), coalesce(sum(occurrences), 0) FROM normalization_adjudication_queue WHERE last_job_id = %s",
            (job_id,),
        ).fetchone()
        stored = c.execute(
            "SELECT data FROM normalization_clone_jobs WHERE job_id = %s", (job_id,)
        ).fetchone()
    evidence = json.loads(stored[0]).get("column_evidence", {}).get("t", {}).get("d")
    order = (evidence or {}).get("order") or (evidence or {}).get("mark")

    if args.type == "NUMERIC":
        ambiguous = {i: v for i, v in enumerate(values) if v and SINGLE_GROUP.match(v.strip())}

        def reads_in_order(v: str, w: str) -> bool:
            grouping = "," if order == "." else "."
            body = v.strip().replace(grouping, "").replace(str(order), ".")
            return Decimal(w) == Decimal(body)
    else:
        ambiguous = {
            i: v
            for i, v in enumerate(values)
            if v
            and (m := DMY.match(v.strip()))
            and m[1] != m[2]
            and int(m[1]) <= 12
            and int(m[2]) <= 12
        }

        def reads_in_order(v: str, w: str) -> bool:
            first, second, year = DMY.match(v.strip()).groups()  # type: ignore[union-attr]
            day, month = (first, second) if order == "DMY" else (second, first)
            tail = f"-{int(month):02d}-{int(day):02d}"
            return w.endswith(f"{int(year):04d}{tail}" if len(year) == 4 else tail)

    refused = sum(written[i] == v for i, v in ambiguous.items())
    resolved = {i: written[i] for i, v in ambiguous.items() if written[i] != v}
    wrong = [
        (values[i], w)
        for i, w in resolved.items()
        if not (order and w is not None and reads_in_order(values[i], w))
    ]
    out = {
        "job": job_id,
        "status": job["status"],
        "rows_source": len(values),
        "rows_destination": len(written),
        "evidence": evidence,
        "ambiguous_cells": len(ambiguous),
        "ambiguous_distinct": len(set(ambiguous.values())),
        "refused_cells": refused,
        "resolved_cells": len(resolved),
        "resolved_not_in_proven_order": wrong[:10],
        "queue_rows": queued[0],
        "queue_occurrences": queued[1],
        "statuses": job.get("quality", {}).get("t", {}).get("d", {}).get("statuses"),
        "examples": sorted({(values[i], w) for i, w in resolved.items()})[:8],
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
