#!/usr/bin/env python3
"""Phase F4: row/FK parity, no-data-loss, quality spot checks."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "normio" / "src"))

from normio.connectors import PostgresConnector
from urllib.parse import urlparse
import sqlalchemy as sa

env: dict[str, str] = {}
for line in (ROOT / ".env.groundtruth").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

origin = PostgresConnector("origin", env["GT_ORIGIN_DSN"])
dst = PostgresConnector("clone2", env["GT_DEST_DSN"])
origin_schema = env.get("GT_ORIGIN_SCHEMA", "diffbot")

tables = [
    "company", "companycontact", "companyemployeecategory", "companyexperience",
    "companyfinancials", "companyindustry", "companyinvestmentround", "companyinvestor",
    "companyrelation", "companytechnographics", "industryclassification",
    "location", "person",
]

results = {"row_parity": {}, "column_lists": {}, "quality_checks": {}}

EMPTY_STR = ''  # Python empty string — we'll use it as a bound parameter

# 1. Row parity
for t in tables:
    with origin._engine.connect() as c:
        on = c.execute(
            sa.text(f'SELECT count(*) FROM "{origin_schema}"."{t}"')
        ).scalar()
    with dst._engine.connect() as c:
        dn = c.execute(
            sa.text(f'SELECT count(*) FROM "{t}"')
        ).scalar()
    results["row_parity"][t] = {"origin": on, "dest": dn, "match": on == dn}

# 2. Column lists
for t in tables:
    with origin._engine.connect() as c:
        ocols = [r[0] for r in c.execute(
            sa.text(
                f"SELECT column_name FROM information_schema.columns WHERE "
                f"table_schema='diffbot' AND table_name='{t}' "
                f"ORDER BY ordinal_position"
            )
        ).fetchall()]
    with dst._engine.connect() as c:
        dcols = [r[0] for r in c.execute(
            sa.text(
                f"SELECT column_name FROM information_schema.columns WHERE "
                f"table_schema='public' AND table_name='{t}' "
                f"ORDER BY ordinal_position"
            )
        ).fetchall()]
    results["column_lists"][t] = {
        "origin_cols": len(ocols),
        "dest_cols": len(dcols),
        "match": ocols == dcols,
        "origin": ocols[:5],
        "dest": dcols[:5],
    }

# 3. Quality spot checks
# 3a. foundingdate all ISO-8601 or ledgered
with origin._engine.connect() as c:
    rows = c.execute(
        sa.text(
            f'SELECT count(*) FROM "{origin_schema}"."company" '
            f"WHERE foundingdate != '{EMPTY_STR}' "
            f"AND foundingdate !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'"
        )
    ).scalar()
results["quality_checks"]["foundingdate_iso"] = {
    "non_iso_count": rows,
    "explanation": f"Rows with non-ISO foundingdate after d-XX repair: {rows} "
                   f"(expected ~1,472 partial dates with XX placeholders)"
}

# 3b. website all scheme-qualified or ledgered
with origin._engine.connect() as c:
    bare = c.execute(
        sa.text(
            f'SELECT count(*) FROM "{origin_schema}"."company" '
            f"WHERE website != '{EMPTY_STR}' "
            f"AND website !~ '^https?://'"
        )
    ).scalar()
results["quality_checks"]["website_schemes"] = {
    "non_scheme_qualified": bare,
    "explanation": f"Non-scheme website URLs after pre-repair: {bare}"
}

# 3c. booleans in {true,false}
for col in ["ispublic", "isnonprofit", "isacquired", "isdissolved"]:
    with origin._engine.connect() as c:
        q = (
            f'SELECT count(*) FROM "{origin_schema}"."company" '
            f'WHERE "{col}" NOT IN ('
            f"'True', 'False') AND \"{col}\" != '{EMPTY_STR}'"
        )
        bad = c.execute(sa.text(q)).scalar()
    results["quality_checks"][f"boolean_{col}"] = {"non_bool_count": bad}

# 3d. person.name non-empty
with origin._engine.connect() as c:
    empty = c.execute(
        sa.text(
            f'SELECT count(*) FROM "{origin_schema}"."person" '
            f"WHERE name IS NULL OR name = '{EMPTY_STR}'"
        )
    ).scalar()
results["quality_checks"]["person_name_empty"] = {"count": empty}

# 3e. location.street empty
with origin._engine.connect() as c:
    no_street = c.execute(
        sa.text(
            f'SELECT count(*) FROM "{origin_schema}"."location" '
            f"WHERE street IS NULL OR street = '{EMPTY_STR}'"
        )
    ).scalar()
results["quality_checks"]["location_empty_streets"] = {"count": no_street}

# 3f. companytechnographics confidence = 1.0
with origin._engine.connect() as c:
    ct_bad = c.execute(
        sa.text(
            f'SELECT count(*) FROM "{origin_schema}"."companytechnographics" '
            f"WHERE confidence != '1.00'"
        )
    ).scalar()
results["quality_checks"]["ct_confidence"] = {"non_100": ct_bad}

# Summary
parities = results["row_parity"]
all_rows_match = all(v["match"] for v in parities.values())
total_origin = sum(v["origin"] for v in parities.values())
total_dest = sum(v["dest"] for v in parities.values())
col_matches = sum(1 for v in results["column_lists"].values() if v["match"])
total_cols_match = sum(1 for v in results["column_lists"].values() if v["origin_cols"] == v["dest_cols"])

print("=" * 60)
print("ROW PARITY")
print(f"  Total origin rows: {total_origin}")
print(f"  Total dest rows:   {total_dest}")
print(f"  All match: {all_rows_match}")
print()
print("COLUMN LISTS")
print(f"  {col_matches}/{total_cols_match} tables have identical column names")
for t, v in results["column_lists"].items():
    if not v["match"]:
        print(f"  MISMATCH: {t}: {v['origin_cols']} vs {v['dest_cols']} cols")
print()
print("QUALITY CHECKS")
for k, v in results["quality_checks"].items():
    print(f"  {k}: {v}")
print("=" * 60)

# Save
json.dump(results, open(ROOT / "ground_truth" / "verification_checks.json", "w"), indent=2)
print(f"\nSaved to ground_truth/verification_checks.json")

origin.close()
dst.close()
