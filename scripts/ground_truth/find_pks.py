#!/usr/bin/env python3
"""Find actual PK values for ledgered rows in both origin and clone2."""
import os, sys, json
from pathlib import Path

ROOT = Path(__file__).resolve()
for p in (ROOT.parent.parent / "packages" / "normio" / "src",
          ROOT.parent.parent / "packages" / "normcore" / "src"):
    if p.exists():
        sys.path.insert(0, str(p))

from normio.connectors import PostgresConnector

env = {}
for line in (ROOT.parent.parent / ".env.groundtruth").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

origin = PostgresConnector("origin", env["GT_ORIGIN_DSN"])
dst = PostgresConnector("clone2", env["GT_DEST_DSN"])

# The two original values from the ledger
val1 = "+1646828766616198095707003994"
val2 = "hello@bdnaerospace.com?__xts"

# Origin PK lookup
q1 = f"SELECT contactid FROM diffbot.companycontact WHERE contactstring = '{val1}'"
q2 = f"SELECT contactid FROM diffbot.companycontact WHERE contactstring = '{val2}'"

with origin._engine.connect() as c:
    r1 = c.execute(__import__("sqlalchemy").text(q1)).fetchone()
    r2 = c.execute(__import__("sqlalchemy").text(q2)).fetchone()

with dst._engine.connect() as c:
    r1_dst = c.execute(__import__("sqlalchemy").text(q1)).fetchone()
    r2_dst = c.execute(__import__("sqlalchemy").text(q2)).fetchone()

print(f"Value 1: {val1}")
print(f"  Origin contactid: {r1[0] if r1 else 'NOT FOUND'}")
print(f"  Clone2 contactid: {r1_dst[0] if r1_dst else 'NOT FOUND'}")
print(f"Value 2: {val2}")
print(f"  Origin contactid: {r2[0] if r2 else 'NOT FOUND'}")
print(f"  Clone2 contactid: {r2_dst[0] if r2_dst else 'NOT FOUND'}")

# Current ledger row_index values
print(f"\nCurrent ledger row_index values: 763, 3324")
print(f"Actual PK (contactid) values: {r1[0] if r1 else 'N/A'}, {r2[0] if r2 else 'N/A'}")

origin.close()
dst.close()
