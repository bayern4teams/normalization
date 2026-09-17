#!/usr/bin/env python3
"""Compare clone2 vs clone3 with deterministic sorting, byte-identical proof."""
import sys
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "normio" / "src"))

from normio.connectors import PostgresConnector, PostgresDestination

env: dict[str, str] = {}
for line in (ROOT / ".env.groundtruth").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

dsn2 = env["GT_DEST_DSN"]  # testdiffbot_clone2
dsn3 = env["GT_DEST_DSN"].replace("testdiffbot_clone2", "testdiffbot_clone3")

p2 = urlparse(dsn2)
p3 = urlparse(dsn3)

conn2 = PostgresConnector("clone2", dsn2)
conn3 = PostgresConnector("clone3", dsn3)

tables = [
    "company", "companycontact", "companyemployeecategory", "companyexperience",
    "companyfinancials", "companyindustry", "companyinvestmentround", "companyinvestor",
    "companyrelation", "companytechnographics", "industryclassification",
    "location", "person",
]

dest2 = PostgresDestination(p2.hostname or "localhost", p2.port or 5433, p2.username, p2.password)
dest3 = PostgresDestination(p3.hostname or "localhost", p3.port or 5433, p3.username, p3.password)

results: dict[str, dict] = {}
all_match = True

for table in tables:
    # Get column names and first column for ORDER BY
    with conn2._engine.connect() as c:
        cols_row = c.execute(
            __import__("sqlalchemy").text(
                f'SELECT column_name FROM information_schema.columns WHERE table_schema='
                f"'public' AND table_name='{table}' ORDER BY ordinal_position"
            )
        ).fetchone()
        # just get first column name for ordering
    first_col = None
    with conn2._engine.connect() as c:
        rows = c.execute(
            __import__("sqlalchemy").text(
                f'SELECT column_name FROM information_schema.columns WHERE table_schema='
                f"'public' AND table_name='{table}' ORDER BY ordinal_position LIMIT 1"
            )
        ).fetchall()
        if rows:
            first_col = rows[0][0]

    # Dump sorted data
    query = f'SELECT * FROM "{table}" ORDER BY "{first_col}"'
    
    rows2 = []
    with conn2._engine.connect() as c:
        result = c.execute(__import__("sqlalchemy").text(query))
        for row in result:
            rows2.append(str(row._mapping))
    
    rows3 = []
    with conn3._engine.connect() as c:
        result = c.execute(__import__("sqlalchemy").text(query))
        for row in result:
            rows3.append(str(row._mapping))
    
    import hashlib
    hash2 = hashlib.md5("\n".join(rows2).encode()).hexdigest()
    hash3 = hashlib.md5("\n".join(rows3).encode()).hexdigest()
    
    results[table] = {"hash2": hash2, "hash3": hash3}
    
    if hash2 == hash3:
        print(f"  MATCH  {table:30s} ({hash2[:16]}...)")
    else:
        all_match = False
        print(f"  MISMATCH {table:30s} clone2={hash2} clone3={hash3}")

print(f"\n{'='*60}")
print(f"Tables compared: {len(tables)}")
print(f"Identical: {sum(1 for r in results.values() if r['hash2'] == r['hash3'])}")
print(f"Different: {sum(1 for r in results.values() if r['hash2'] != r['hash3'])}")
if all_match:
    print("VERIFIED: byte-identical output (ground truth confirmed)")
else:
    print("WARNING: tables differ between clone2 and clone3")
print(f"{'='*60}")

# Save results
json.dump(results, open(ROOT / "ground_truth" / "clone_comparisons.json", "w"), indent=2)
print(f"\nSaved to ground_truth/clone_comparisons.json")

conn2.close()
conn3.close()
