"""PART1 D1.3 live: a verdict survives deleting and re-adding the source connection.

Through the real API (in-process, as clone_bench.py) against the isolated normbench
stack, per engine:
  1. a source table holding the ambiguous date `03/04/2024` five times and one clean date;
  2. job 1 on connection A: the value is queued once with occurrences 5;
  3. a verdict through the API; connection A deleted; the same server saved again (B);
  4. job 2 on B: the destination cell is the decided date, the queue did not grow.
Every check is direct SQL on the source, the destination and the metadata database; the
job's own status is printed but decides nothing.

    uv run python docs/benchmarks/scripts/d1_identity_roundtrip.py --engine postgres
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid

import clickhouse_connect
import psycopg
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

APP_DSN = "postgresql://normalization:normalization@localhost:5535/normalization"
SOURCE = {
    "postgres": {
        "host": "localhost",
        "port": 5436,
        "username": "readonly_user",
        "password": "readonly_pass",
    },
    "clickhouse": {
        "host": "localhost",
        "port": 8124,
        "username": "readonly_user",
        "password": "readonly_pass",
    },
}
DEST = {
    "postgres": {
        "host": "localhost",
        "port": 5535,
        "username": "normalization",
        "password": "normalization",
    },
    "clickhouse": {
        "host": "localhost",
        "port": 8124,
        "username": "writable_user",
        "password": "writable_pass",
    },
}
AMBIGUOUS, DECIDED, CLEAN = "03/04/2024", "2024-04-03", "2024-12-31"
ROWS = [(i, AMBIGUOUS) for i in range(5)] + [(5, CLEAN)]


def _pg(port: int, user: str, password: str, db: str) -> psycopg.Connection:
    return psycopg.connect(f"postgresql://{user}:{password}@localhost:{port}/{db}", autocommit=True)


def _ch() -> object:
    return clickhouse_connect.get_client(
        host="localhost", port=8124, username="writable_user", password="writable_pass"
    )


def make_source(engine: str, db: str) -> None:
    if engine == "postgres":
        with _pg(5436, "source_admin", "source_admin", "postgres") as c:
            c.execute(f'CREATE DATABASE "{db}"')
        with _pg(5436, "source_admin", "source_admin", db) as c:
            c.execute("CREATE TABLE t (id int PRIMARY KEY, d text)")
            c.cursor().executemany("INSERT INTO t VALUES (%s, %s)", ROWS)
            c.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user")
    else:
        ch = _ch()
        ch.command(f"CREATE DATABASE `{db}`")
        ch.command(f"CREATE TABLE `{db}`.t (id Int32, d String) ENGINE = MergeTree ORDER BY id")
        ch.insert(f"`{db}`.t", [list(r) for r in ROWS], column_names=["id", "d"])


def dest_cells(engine: str, db: str) -> dict[int, str | None]:
    if engine == "postgres":
        with _pg(5535, "normalization", "normalization", db) as c:
            return dict(c.execute("SELECT id, d FROM t ORDER BY id").fetchall())
    return dict(_ch().query(f"SELECT id, d FROM `{db}`.t ORDER BY id").result_rows)


def meta(sql: str, params: dict | None = None) -> list[tuple]:
    with _pg(5535, "normalization", "normalization", "normalization") as c:
        return c.execute(sql, params or {}).fetchall()


def main() -> None:  # noqa: PLR0915 - one linear live check
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["postgres", "clickhouse"], required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    engine = args.engine
    os.environ.setdefault("NORM_SECRET_KEY", Fernet.generate_key().decode())
    from normapi.app import create_app  # noqa: PLC0415 - after NORM_SECRET_KEY is set

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

    tag = uuid.uuid4().hex[:8]
    src_db = f"d1id_src_{tag}"
    make_source(engine, src_db)
    dst = call("POST", "/connections", json={"engine": engine, **DEST[engine]})

    def clone(conn_id: str, dst_db: str) -> dict:
        body = {
            "source_connection_id": conn_id,
            "source_database": src_db,
            "destination_connection_id": dst["connection_id"],
            "destination_database": dst_db,
            "autodetect_field_types": False,
            "field_configs": {"t": {"d": "DATE"}},
        }
        created = call("POST", "/clone-jobs", json=body)
        sql = created["create_database_sql"]
        if engine == "postgres":
            with _pg(5535, "normalization", "normalization", "postgres") as c:
                c.execute(sql)
        else:
            _ch().command(sql)
        call("POST", f"/clone-jobs/{created['job_id']}/verify-database")
        call("POST", f"/clone-jobs/{created['job_id']}/start")
        while (job := call("GET", f"/clone-jobs/{created['job_id']}"))["status"] not in (
            "COMPLETED",
            "FAILED",
        ):
            time.sleep(1)
        return job

    out: dict = {"engine": engine, "source_db": src_db}
    conn_a = call("POST", "/connections", json={"engine": engine, **SOURCE[engine]})[
        "connection_id"
    ]
    job1 = clone(conn_a, f"d1id_out1_{tag}")
    out["job1"] = {
        "id": job1["job_id"],
        "status": job1["status"],
        "identity": job1.get("source_identity"),
    }
    out["job1_cells"] = dest_cells(engine, f"d1id_out1_{tag}")
    rows = meta(
        "SELECT key, occurrences, context FROM normalization_adjudication_queue "
        "WHERE last_job_id = %(j)s AND original = %(v)s",
        {"j": job1["job_id"], "v": AMBIGUOUS},
    )
    out["queue_after_job1"] = [(k, n, json.loads(ctx)["source"]) for k, n, ctx in rows]
    key = rows[0][0]
    call(
        "POST",
        f"/adjudication/queue/{key}/verdicts",
        json={
            "decided_value": DECIDED,
            "decided_by": "human:d1-live",
            "rationale": "D1.3 live check",
        },
    )
    call("DELETE", f"/connections/{conn_a}")
    conn_b = call("POST", "/connections", json={"engine": engine, **SOURCE[engine]})[
        "connection_id"
    ]
    out["connections"] = {"a": conn_a, "b": conn_b}
    job2 = clone(conn_b, f"d1id_out2_{tag}")
    out["job2"] = {
        "id": job2["job_id"],
        "status": job2["status"],
        "identity": job2.get("source_identity"),
    }
    out["job2_cells"] = dest_cells(engine, f"d1id_out2_{tag}")
    out["queue_rows_for_value"] = meta(
        "SELECT key, occurrences, last_job_id FROM normalization_adjudication_queue "
        "WHERE original = %(v)s AND context::jsonb->>'source' = %(s)s",
        {"v": AMBIGUOUS, "s": job2.get("source_identity")},
    )
    out["error_rows_job2"] = meta(
        "SELECT count(*) FROM normalization_clone_job_errors WHERE job_id = %(j)s",
        {"j": job2["job_id"]},
    )[0][0]
    cells = out["job2_cells"]
    out["pass"] = (
        conn_a != conn_b
        and all(cells[i] == DECIDED for i in range(5))
        and cells[5] == CLEAN
        and len(out["queue_rows_for_value"]) == 1
        and out["queue_rows_for_value"][0][1] == 5
    )
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(
        json.dumps(
            {
                k: out[k]
                for k in ("engine", "job1", "job2", "job2_cells", "queue_rows_for_value", "pass")
            },
            default=str,
        )
    )


if __name__ == "__main__":
    main()
