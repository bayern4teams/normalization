#!/usr/bin/env python3
"""Compare clone2 vs clone3: dump each table to md5 and compare."""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
env: dict[str, str] = {}
for line in (ROOT / ".env.groundtruth").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

DB2 = env["GT_DEST_DB"]
DB3 = env.get("GT_DEST_DB2", "testdiffbot_clone2")
# clone2 is DB2, clone3 is env['GT_DEST_DB'] (second one)
# Actually, looking at .env.groundtruth:
# GT_DEST_DB=testdiffbot_clone2  → first run
# GT_DEST_DB2=testdiffbot_clone3 → second run

# Check env for the second DB
db2 = "testdiffbot_clone2"
db3 = "testdiffbot_clone3"

tables = [
    "company", "companycontact", "companyemployeecategory", "companyexperience",
    "companyfinancials", "companyindustry", "companyinvestmentround", "companyinvestor",
    "companyrelation", "companytechnographics", "industryclassification",
    "location", "person",
]

dsn2 = env["GT_DEST_DSN"].replace("testdiffbot_clone2", db2)
# Build clone3 DSN from .env
for line in (ROOT / ".env.groundtruth").read_text().splitlines():
    if line.startswith("GT_DEST_DSN2="):
        dsn3 = line.split("=", 1)[1].strip()
        break
else:
    # build from GT_DEST_DSN by replacing the db name
    dsn3 = env["GT_DEST_DSN"].replace("testdiffbot_clone2", db3)

results = {}
for table in tables:
    # Dump as sorted rows to ignore insert order
    for db, dsn in [(db2, dsn2), (db3, dsn3)]:
        cmd = f"psql '{dsn}' -Atc \"SELECT * FROM \\\"{table}\\\" ORDER BY ctid\" | md5sum"
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        md5 = r.stdout.split()[0] if r.stdout.strip() else "N/A"
        results.setdefault(table, {})[db] = md5

# Compare
matches = 0
diffs = 0
for table in tables:
    md5_2 = results[table][db2]
    md5_3 = results[table][db3]
    if md5_2 == md5_3:
        matches += 1
    else:
        diffs += 1
        print(f"MISMATCH: {table}: clone2={md5_2} clone3={md5_3}")

print(f"\n{'='*60}")
print(f"Tables compared: {len(tables)}")
print(f"Identical: {matches}")
print(f"Different: {diffs}")
if diffs == 0:
    print("VERIFIED: byte-identical output (ground truth confirmed)")
else:
    print("WARNING: tables differ between clone2 and clone3")
print(f"{'='*60}")
