"""Run one clone job end to end through the real API (in-process) and record what it did.

Used for docs/benchmarks/REPORT.md. Credentials are the project's own test fixtures for the
isolated `normbench` docker stack (compose.yaml + .tmp/normbench.override.yaml); never point
this at a real database. Every number it records is re-checked by direct SQL in the report.

    uv run python docs/benchmarks/scripts/clone_bench.py --engine postgres --src-db pagila \
        --dst-db pagila_out --out .tmp/bench/pagila.json [--country US --locale en-US]
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import time
from pathlib import Path

import clickhouse_connect
import psycopg
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

APP_DSN = "postgresql://normalization:normalization@localhost:5535/normalization"
SOURCES = {
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
DESTINATIONS = {
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


def _create_database(engine: str, sql: str) -> None:
    dst = DESTINATIONS[engine]
    if engine == "postgres":
        with psycopg.connect(
            f"postgresql://{dst['username']}:{dst['password']}@{dst['host']}:{dst['port']}/postgres",
            autocommit=True,
        ) as conn:
            conn.execute(sql)
    else:
        clickhouse_connect.get_client(
            host=dst["host"], port=dst["port"], username=dst["username"], password=dst["password"]
        ).command(sql)


def main() -> None:  # noqa: PLR0915 - one linear benchmark script
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["postgres", "clickhouse"], required=True)
    ap.add_argument("--src-db", required=True)
    ap.add_argument("--src-port", type=int, help="override the source port (PG18 source: 5438)")
    ap.add_argument("--src-schema")
    ap.add_argument("--dst-db", required=True)
    ap.add_argument("--country")
    ap.add_argument("--locale")
    ap.add_argument("--field-configs", help="JSON file: {table: {column: SEMANTIC_TYPE|null}}")
    ap.add_argument("--no-autodetect", action="store_true")
    ap.add_argument(
        "--src-conn-id", help="reuse a saved source connection (verdicts are scoped to it)"
    )
    ap.add_argument("--dst-conn-id", help="reuse a saved destination connection")
    ap.add_argument(
        "--resume-job", help="start an existing job again (FAILED or killed) instead of a new one"
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    os.environ.setdefault("NORM_SECRET_KEY", Fernet.generate_key().decode())
    from normapi.app import create_app  # noqa: PLC0415 - after NORM_SECRET_KEY is set

    bench = Path(".tmp/bench")
    bench.mkdir(parents=True, exist_ok=True)
    client = TestClient(create_app(pg_dsn=APP_DSN, custom_dictionaries_dir=bench / "custom-dicts"))

    def call(method: str, path: str, **kw: object) -> dict:
        r = client.request(method, "/normalization" + path, **kw)
        if r.status_code >= 400:
            raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:2000]}")
        return r.json() if r.content else {}

    if args.resume_job:
        result: dict = {"args": vars(args), "stage": "phase2", "job_id": args.resume_job}
        t1 = time.perf_counter()
        call("POST", f"/clone-jobs/{args.resume_job}/start")
        while (job := call("GET", f"/clone-jobs/{args.resume_job}"))["status"] not in (
            "COMPLETED",
            "FAILED",
        ):
            time.sleep(1)
        result["phase2_s"] = round(time.perf_counter() - t1, 2)
        result.update(stage="done", status=job["status"], error=job.get("error"), job=job)
        result["peak_rss_mb_self"] = round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        )
        result["peak_rss_mb_children"] = round(
            resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
        )
        Path(args.out).write_text(json.dumps(result, indent=1, default=str))
        print(json.dumps({k: result.get(k) for k in ("job_id", "status", "error", "phase2_s")}))
        return

    source = {**SOURCES[args.engine], **({"port": args.src_port} if args.src_port else {})}
    src = (
        {"connection_id": args.src_conn_id}
        if args.src_conn_id
        else call("POST", "/connections", json={"engine": args.engine, **source})
    )
    dst = (
        {"connection_id": args.dst_conn_id}
        if args.dst_conn_id
        else call("POST", "/connections", json={"engine": args.engine, **DESTINATIONS[args.engine]})
    )
    body = {
        "source_connection_id": src["connection_id"],
        "source_database": args.src_db,
        "source_schema": args.src_schema,
        "destination_connection_id": dst["connection_id"],
        "destination_database": args.dst_db,
        "country": args.country,
        "locale": args.locale,
        "autodetect_field_types": not args.no_autodetect,
        "field_configs": json.loads(Path(args.field_configs).read_text())
        if args.field_configs
        else {},
    }
    result = {"args": vars(args), "stage": "create"}
    try:
        created = call("POST", "/clone-jobs", json=body)
        job_id = result["job_id"] = created["job_id"]
        _create_database(args.engine, created["create_database_sql"])
        result["plan"] = call("GET", f"/clone-jobs/{job_id}/plan")

        result["stage"] = "phase1"
        t0 = time.perf_counter()
        result["phase1"] = call("POST", f"/clone-jobs/{job_id}/verify-database")
        t1 = time.perf_counter()
        result["phase1_s"] = round(t1 - t0, 2)

        result["stage"] = "phase2"
        call("POST", f"/clone-jobs/{job_id}/start")
        while (job := call("GET", f"/clone-jobs/{job_id}"))["status"] not in (
            "COMPLETED",
            "FAILED",
        ):
            time.sleep(1)
        result["phase2_s"] = round(time.perf_counter() - t1, 2)
        result.update(stage="done", status=job["status"], error=job.get("error"), job=job)
        result["quality"] = call("GET", f"/clone-jobs/{job_id}/quality")
        # first page only; totals come from direct SQL on the metadata DB
        result["errors_first_page"] = call(
            "GET", f"/clone-jobs/{job_id}/errors", params={"limit": 100}
        )
        result["lineage"] = call("GET", f"/clone-jobs/{job_id}/lineage")
    except (Exception, SystemExit) as exc:  # a failing stage is a result, not a crash
        result["exception"] = f"{type(exc).__name__}: {str(exc)[:3000]}"
    result["peak_rss_mb_self"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    result["peak_rss_mb_children"] = round(
        resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    )
    Path(args.out).write_text(json.dumps(result, indent=1, default=str))
    keys = (
        "job_id",
        "stage",
        "status",
        "error",
        "exception",
        "phase1_s",
        "phase2_s",
        "peak_rss_mb_self",
        "peak_rss_mb_children",
    )
    print(json.dumps({k: result.get(k) for k in keys})[:1500])


if __name__ == "__main__":
    main()
