# ruff: noqa: E501 - SQL and report lines read better unwrapped in a one-off live check
"""PART1 D8-D12 live: real values through a real clone (normbench), checked by direct SQL.

Builds one source table on the normbench Postgres from real public values (Brreg organisation
numbers and websites, Raha hospital phones), clones it through the API in-process (as
clone_bench.py), and reads the destination and the metadata database:
  D8  the same numbers as TAX_ID (country NO) and as CODE: a corrupted check digit is INVALID
      (an error row) as TAX_ID, never as CODE;
  D9  each URL's registrable domain, from the engine's structured view (a clone persists no
      structured view), against the Public Suffix List computed independently;
  D10 phones with an extension: the code companion is the RFC 3966 URI carrying it, and the
      region companion is libphonenumber's region;
  D11 multi-script names: Double Metaphone / Beider-Morse keys present, no Soundex on non-Latin;
  D12 a verdict whose decided value now normalizes differently is applied as NEEDS_REVIEW.

    uv run python docs/benchmarks/scripts/d8_d12_live.py --out $BENCH_DIR/work/d812/live.json
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid

import phonenumbers
import psycopg
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from publicsuffixlist import PublicSuffixList

APP_DSN = "postgresql://normalization:normalization@localhost:5535/normalization"
SRC = {"host": "localhost", "port": 5436, "username": "readonly_user", "password": "readonly_pass"}
DST = {"host": "localhost", "port": 5535, "username": "normalization", "password": "normalization"}


def _pg(port: int, user: str, pw: str, db: str) -> psycopg.Connection:
    return psycopg.connect(f"postgresql://{user}:{pw}@localhost:{port}/{db}", autocommit=True)


def _real_values() -> dict[str, list[str]]:
    with _pg(5436, "readonly_user", "readonly_pass", "ref_norway") as c:
        orgnr = [r[0] for r in c.execute('SELECT "organisasjonsnummer" FROM enheter LIMIT 200')]
        urls = [
            r[0]
            for r in c.execute(
                'SELECT DISTINCT "hjemmeside" FROM enheter WHERE "hjemmeside" LIKE \'%%.%%\' LIMIT 200'
            )
        ]
    with _pg(5436, "readonly_user", "readonly_pass", "raha") as c:
        phones = [r[0] for r in c.execute("SELECT DISTINCT phone FROM hospital LIMIT 50")]
    return {"orgnr": orgnr, "urls": urls, "phones": phones}


def main() -> None:  # noqa: PLR0915 - one linear live check
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.environ.setdefault("NORM_SECRET_KEY", Fernet.generate_key().decode())
    from normapi.app import build_dispatcher, create_app  # noqa: PLC0415
    from normapi.scaffold_profile import SCAFFOLD_PROFILE  # noqa: PLC0415
    from normcore.context import NormalizationContext  # noqa: PLC0415
    from normcore.enums import FieldSemanticType as T  # noqa: PLC0415

    real = _real_values()
    corrupted = [n[:-1] + str((int(n[-1]) + 1) % 10) for n in real["orgnr"][:5]]
    with_ext = [
        f"+1 {p[:3]} {p[3:6]} {p[6:10]} ext. 12" for p in real["phones"][:10] if p.isdigit()
    ]
    names = ["Мухаммед", "Muhammad", "محمد", "Jean-Pierre", "Zhang", "O'Boyle"]
    tids, phones = real["orgnr"] + corrupted, real["phones"] + with_ext
    rows = [
        (
            i,
            tids[i] if i < len(tids) else None,
            tids[i] if i < len(tids) else None,
            phones[i] if i < len(phones) else None,
            names[i % len(names)],
            "03/04/2024",
        )
        for i in range(max(len(tids), len(phones)))
    ]
    tag = uuid.uuid4().hex[:8]
    src = f"d812_src_{tag}"
    with _pg(5436, "source_admin", "source_admin", "postgres") as c:
        c.execute(f'CREATE DATABASE "{src}"')
    with _pg(5436, "source_admin", "source_admin", src) as c:
        c.execute(
            "CREATE TABLE t (id int PRIMARY KEY, tid text, code text, phone text, name text, d text)"
        )
        c.cursor().executemany("INSERT INTO t VALUES (%s, %s, %s, %s, %s, %s)", rows)
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
    fc = {
        "t": {"tid": "TAX_ID", "code": "CODE", "phone": "PHONE", "name": "PERSON_NAME", "d": "DATE"}
    }

    def clone(n: int, country: str | None = "NO") -> dict:
        created = call(
            "POST",
            "/clone-jobs",
            json={
                "source_connection_id": src_conn,
                "source_database": src,
                "destination_connection_id": dst_conn,
                "destination_database": f"d812_out{n}_{tag}",
                "country": country,
                "autodetect_field_types": False,
                "field_configs": fc,
            },
        )
        with _pg(5535, "normalization", "normalization", "postgres") as c:
            c.execute(created["create_database_sql"])
        call("POST", f"/clone-jobs/{created['job_id']}/verify-database")
        call("POST", f"/clone-jobs/{created['job_id']}/start")
        while (job := call("GET", f"/clone-jobs/{created['job_id']}"))["status"] not in (
            "COMPLETED",
            "FAILED",
        ):
            time.sleep(1)
        return job

    def meta(sql: str, params: tuple = ()) -> list[tuple]:
        with _pg(5535, "normalization", "normalization", "normalization") as c:
            return c.execute(sql, params).fetchall()

    out: dict = {"source_db": src}
    job1 = clone(1)
    out["job1"] = {"status": job1["status"], "error": job1.get("error")}
    errors = meta(
        "SELECT field, original, error FROM normalization_clone_job_errors WHERE job_id = %s",
        (job1["job_id"],),
    )
    out["D8"] = {
        "tid_error_rows": sum(f == "tid" for f, _, _ in errors),
        "tid_error_originals": sorted(o for f, o, _ in errors if f == "tid"),
        "corrupted": sorted(corrupted),
        "code_error_rows": sum(f == "code" for f, _, _ in errors),
    }
    with _pg(5535, "normalization", "normalization", f"d812_out1_{tag}") as c:
        phone_rows = c.execute(
            "SELECT phone, phone_code, phone_region FROM t WHERE phone IS NOT NULL ORDER BY id"
        ).fetchall()
    ext = [r for r in phone_rows if r[1] and ";ext=" in r[1]]
    out["D10"] = {
        "rows": len(phone_rows),
        "with_extension_in_code": len(ext),
        "planted_extensions": len(with_ext),
        "examples": ext[:3],
        "region_matches_libphonenumber": sum(
            r[2]
            == phonenumbers.region_code_for_number(
                phonenumbers.parse(r[1].removeprefix("tel:").split(";")[0])
            )
            for r in phone_rows
            if r[1] and r[1].startswith(("+", "tel:+"))
        ),
        "region_checked": sum(1 for r in phone_rows if r[1] and r[1].startswith(("+", "tel:+"))),
    }

    # D9 and D11: the engine's structured view on the same real values (not persisted by a clone).
    d = build_dispatcher(env_id="d812")
    psl = PublicSuffixList(accept_unknown=False)

    def norm(t: T, v: str) -> object:
        return d.normalize(
            v, t, NormalizationContext(field_name="f", semantic_type=t), SCAFFOLD_PROFILE
        )

    agree = disagree = 0
    for url in real["urls"]:
        r = norm(T.URL, url)
        host = r.structured.get("host")
        if host:
            if r.structured.get("registrable_domain") == psl.privatesuffix(host):
                agree += 1
            else:
                disagree += 1
    out["D9"] = {
        "urls": len(real["urls"]),
        "registrable_domain_agrees_with_psl": agree,
        "disagrees": disagree,
    }
    out["D11"] = {
        n: {
            k: v
            for k, v in norm(T.FAMILY_NAME, n).structured.items()
            if "phonetic" in k or k in ("script",)
        }
        for n in names
    }

    # D12: a verdict whose decided value now normalizes differently. No country, so the
    # day/month order of 03/04/2024 is unstated and the value is queued.
    job_q = clone(2, country=None)
    (key,) = [
        k
        for (k,) in meta(
            "SELECT key FROM normalization_adjudication_queue WHERE last_job_id = %s AND original = %s",
            (job_q["job_id"], "03/04/2024"),
        )
    ]
    call(
        "POST",
        f"/adjudication/queue/{key}/verdicts",
        json={
            "decided_value": "2024-04-03",
            "decided_by": "human:d812-live",
            "rationale": "D12 live",
        },
    )
    with _pg(5535, "normalization", "normalization", "normalization") as c:
        # As if the date normalizer had changed since the decision: the stored display differs.
        c.execute(
            "UPDATE normalization_adjudication_verdicts SET decided_display = 'as decided earlier' WHERE key = %s",
            (key,),
        )
    job2 = clone(3, country=None)
    out["D12"] = {
        "status": job2["status"],
        "d_statuses": job2.get("quality", {}).get("t", {}).get("d", {}).get("statuses"),
        "cells": sorted(
            {
                r[0]
                for r in _pg(5535, "normalization", "normalization", f"d812_out3_{tag}")
                .execute("SELECT d FROM t")
                .fetchall()
            }
        ),
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1, default=str, ensure_ascii=False)
    print(json.dumps(out, default=str, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()
