"""LOCAL_VERIFY D4 on real tables: `SELECT value, count(*) GROUP BY value` -> detector.

Prints what the detector reports next to the column's most frequent values, so the report can
be compared with the GROUP BY by eye (the independent check). NULLs are not values.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import psycopg
from normanalysis.disguised_missing import detect_disguised_missing
from normcore.context import NormalizationContext

COLUMNS = [  # (database, table, column, semantic type, country)
    ("raha", "beers", "ibu", "NUMERIC", "US"),
    ("raha", "beers", "abv", "NUMERIC", "US"),
    ("raha", "hospital", "zip", "POSTCODE", "US"),
    ("raha", "hospital", "phone", "PHONE", "US"),
    ("raha", "hospital", "score", "NUMERIC", "US"),
    ("raha", "rayyan", "article_jcreated_at", "DATE", "US"),
    ("raha", "tax", "zip", "POSTCODE", "US"),
    ("ref_norway", "enheter", "hjemmeside", "URL", "NO"),
    ("ref_norway", "enheter", "epostadresse", "EMAIL", "NO"),
    ("ref_norway", "enheter", "telefon", "PHONE", "NO"),
    ("ref_norway", "enheter", "forretningsadresse.landkode", "COUNTRY", None),
    ("ref_gleif", "lei", "Entity.LegalAddress.Country", "COUNTRY", None),
    ("ref_france", "unite_legale", "dateCreationUniteLegale", "DATE", "FR"),
]


def main() -> None:
    out = []
    for db, table, column, sem, country in COLUMNS:
        with psycopg.connect(f"postgresql://source_admin:source_admin@localhost:5436/{db}") as c:
            rows = c.execute(
                f'SELECT "{column}", count(*) FROM "{table}" WHERE "{column}" IS NOT NULL '
                f"GROUP BY 1 ORDER BY 2 DESC"
            ).fetchall()
        counts = dict(rows)
        ctx = NormalizationContext(field_name=column, semantic_type=sem, country=country)
        t0 = time.perf_counter()
        found = detect_disguised_missing(counts, sem, ctx)
        entry = {
            "column": f"{db}.{table}.{column}",
            "type": sem,
            "country": country,
            "distinct": len(counts),
            "cells": sum(counts.values()),
            "seconds": round(time.perf_counter() - t0, 2),
            "reported": [[d.value, d.count, d.hint.value if d.hint else None] for d in found],
            "top_values": [[v, n] for v, n in rows[:15]],
        }
        out.append(entry)
        print(json.dumps(entry, ensure_ascii=False)[:900], flush=True)
    Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
