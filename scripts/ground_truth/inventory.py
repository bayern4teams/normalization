#!/usr/bin/env python3
"""Phase A — full inventory of the origin database (read-only).

Writes ground_truth/inventory.json covering:
  - every table: columns + native types + PK + row count
  - per text column: null/empty/distinct counts, min/max length, 25 samples
  - FK census: referent-existence counts for common key columns
  - special lookups: distinct contacttype / relationtype / types / sourcecategory
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "normio" / "src"))

from normio.connectors import PostgresConnector  # noqa: E402

DSN = os.environ["GT_ORIGIN_DSN"]
SCHEMA = os.environ.get("GT_ORIGIN_SCHEMA", "diffbot")
OUT = ROOT / "ground_truth" / "inventory.json"

TABLES = [
    "company", "companycontact", "companyemployeecategory", "companyexperience",
    "companyfinancials", "companyindustry", "companyinvestmentround",
    "companyinvestor", "companyrelation", "companytechnographics",
    "industryclassification", "location", "person",
]

SAMPLE_LIMIT = 25


def main() -> int:
    conn = PostgresConnector("inventory", DSN)
    engine = conn._engine  # read engine for raw SQL
    inventory: dict[str, object] = {
        "schema": SCHEMA,
        "tables": {},
        "fk_census": {},
        "lookups": {},
    }
    total_rows = 0

    def q(text: str, **params):
        with engine.connect() as c:
            return c.execute(sa.text(text), params).all()

    for table in TABLES:
        tinfo: dict[str, object] = {}
        # columns + native types + PK
        insp = sa.inspect(engine)
        cols = insp.get_columns(table, schema=SCHEMA)
        pk = insp.get_pk_constraint(table, schema=SCHEMA)
        pk_cols = list(pk.get("constrained_columns") or [])
        col_infos = [
            {"name": c["name"], "native_type": str(c["type"]), "nullable": c.get("nullable")}
            for c in cols
        ]
        tinfo["columns"] = col_infos
        tinfo["primary_key"] = pk_cols
        # row count
        n = q(f'SELECT count(*) FROM "{SCHEMA}"."{table}"')[0][0]
        total_rows += n
        tinfo["row_count"] = n
        # per-column profiling for text-ish columns
        col_profiles: dict[str, object] = {}
        for c in cols:
            col = c["name"]
            native = str(c["type"])
            prof: dict[str, object] = {"native_type": native}
            # null / empty / distinct / minmax len / samples
            is_textish = any(
                t in native.lower() for t in ("char", "text") 
            ) or "int" in native.lower() or "numeric" in native.lower() or "bool" in native.lower()
            empty_expr = f'count(*) FILTER (WHERE CAST("{col}" AS text) = \'\')'
            probe_expr = f'count(*) FILTER (WHERE CAST("{col}" AS text) = \'\')'
            rows = q(
                f'SELECT count(*) FILTER (WHERE "{col}" IS NULL), '
                f'{probe_expr}, '
                f'count(DISTINCT "{col}"), '
                f'min(length(CAST("{col}" AS text))), '
                f'max(length(CAST("{col}" AS text))) '
                f'FROM "{SCHEMA}"."{table}"'
            )[0]
            prof["null_count"] = rows[0]
            prof["empty_count"] = rows[1]
            prof["distinct_count"] = rows[2]
            prof["min_len"] = rows[3]
            prof["max_len"] = rows[4]
            if rows[0] + rows[1] < n:  # has non-null non-empty values
                samples = q(
                    f'SELECT DISTINCT CAST("{col}" AS text) FROM "{SCHEMA}"."{table}" '
                    f'WHERE "{col}" IS NOT NULL AND CAST("{col}" AS text) <> \'\' '
                    f'ORDER BY 1 LIMIT {SAMPLE_LIMIT}'
                )
                prof["samples"] = [str(r[0]) for r in samples]
            else:
                prof["samples"] = []
            col_profiles[col] = prof
        tinfo["column_profiles"] = col_profiles
        inventory["tables"][table] = tinfo

    inventory["total_rows"] = total_rows

    # FK census: referent existence for key columns
    fk_query = """
        SELECT
          tc.table_name AS fk_table,
          kcu.column_name AS fk_column,
          ccu.table_name AS ref_table,
          ccu.column_name AS ref_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
          AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
          AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = :schema
        ORDER BY 1,2
    """
    fk_rels = q(fk_query, schema=SCHEMA)
    census: dict[str, object] = {}
    for ft, fc, rt, rc in fk_rels:
        miss = q(
            f'SELECT count(*) FROM "{SCHEMA}"."{ft}" f '
            f'LEFT JOIN "{SCHEMA}"."{rt}" r ON f."{fc}" = r."{rc}" '
            f'WHERE f."{fc}" IS NOT NULL AND r."{rc}" IS NULL'
        )[0][0]
        census[f"{ft}.{fc} -> {rt}.{rc}"] = {"dangling": miss}
    inventory["fk_census"] = census

    # special lookups
    for tbl, col in [
        ("companycontact", "contacttype"),
        ("companyrelation", "relationtype"),
        ("company", "types"),
        ("company", "sourcecategory"),
        ("companytechnographics", "technologytype"),
        ("companytechnographics", "categories"),
        ("person", "types"),
    ]:
        distinct = q(f'SELECT DISTINCT "{col}" FROM "{SCHEMA}"."{tbl}" ORDER BY 1')
        inventory["lookups"].setdefault(tbl, {})[col] = [str(r[0]) for r in distinct if r[0] is not None]

    OUT.write_text(json.dumps(inventory, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"Tables: {len(inventory['tables'])}  Total rows: {total_rows}")
    print("FK relationships:", len(census))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
