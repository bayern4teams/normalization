#!/usr/bin/env python3
"""Origin fingerprint: per-table count for Phase F verification."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "normio" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "normcore" / "src"))

from normio.connectors import PostgresConnector

# Load env from .env.groundtruth
env: dict[str, str] = {}
for line in (ROOT / ".env.groundtruth").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

conn = PostgresConnector("fingerprint", env["GT_ORIGIN_DSN"])
origin_schema = env.get("GT_ORIGIN_SCHEMA", "diffbot")
tables = [
    "company", "companycontact", "companyemployeecategory", "companyexperience",
    "companyfinancials", "companyindustry", "companyinvestmentround", "companyinvestor",
    "companyrelation", "companytechnographics", "industryclassification",
    "location", "person",
]

fp: dict[str, int] = {}
for t in tables:
    with conn._engine.connect() as c:
        n = int(
            c.execute(
                __import__("sqlalchemy").text(
                    f'SELECT count(*) FROM "{origin_schema}"."{t}"'
                )
            ).scalar()
        )
    fp[t] = n
conn.close()

out = ROOT / "ground_truth" / "origin_fingerprint_before.json"
out.write_text(json.dumps(fp, indent=2))
print(json.dumps(fp, indent=2))
print(f"Wrote {len(fp)} fingerprints. Total rows: {sum(fp.values())}")
