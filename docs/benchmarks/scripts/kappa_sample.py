"""PART1 D6.3: a labelling sheet for the corpus's own ambiguity rate (Cohen's kappa /
Krippendorff's alpha between two people who label independently).

Draws real values from the public benchmark data on the normbench stack: half that the engine
refuses (AMBIGUOUS), half that it answers, across dates, money, phones, country codes, URLs and
person names. Each row lists the readings to choose from: the engine's own candidates (or its
answer), plus "can't tell", "missing" and "something else". Seeded, so both people get the same
sheet. The values are dataset values: the sheet stays under $BENCH_DIR/work/, never committed.

    uv run python docs/benchmarks/scripts/kappa_sample.py --out-dir $BENCH_DIR/work/labels --n 60
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

import psycopg
from normapi.app import build_dispatcher
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType as T
from normcore.enums import NormalizationStatus as S

CANT_TELL, MISSING, OTHER = "can't tell", "missing (no value)", "something else"
POOLS = [  # (database, SQL, semantic type, context)
    ("raha", "SELECT DISTINCT article_jcreated_at FROM rayyan", T.DATE, {}),
    ("raha", "SELECT DISTINCT release_date FROM movies_1", T.DATE, {}),
    ("raha", "SELECT DISTINCT salary FROM tax", T.MONEY, {}),
    ("raha", "SELECT DISTINCT phone FROM hospital", T.PHONE, {}),
    ("ref_norway", 'SELECT DISTINCT "forretningsadresse.landkode" FROM enheter', T.COUNTRY, {}),
    ("ref_norway", 'SELECT DISTINCT "hjemmeside" FROM enheter LIMIT 3000', T.URL, {}),
    ("raha", "SELECT DISTINCT f_name || ' ' || l_name FROM tax LIMIT 3000", T.PERSON_NAME, {}),
]


def _readings(r: object, semantic_type: T) -> list[str]:
    s = r.structured or {}
    if r.normalization_status is S.AMBIGUOUS:
        cands = s.get("candidates") or []
        out = []
        for c in cands:
            if isinstance(c, dict):
                out.append(
                    c.get("url")
                    or c.get("display")
                    or ", ".join(f"{k}={v}" for k, v in c.items() if k != "interpretation")
                    or c.get("interpretation", "")
                )
            else:
                out.append(str(c))
        if not out:
            out = [f"a {semantic_type.value} needing more context"]
        return out
    return [str(r.display)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    d = build_dispatcher(env_id="kappa")
    refused, answered = [], []
    for db, sql, t, ctx in POOLS:
        with psycopg.connect(f"postgresql://readonly_user:readonly_pass@localhost:5436/{db}") as c:
            values = sorted({str(v) for (v,) in c.execute(sql) if v not in (None, "")})
        rng.shuffle(values)
        for v in values[:400]:
            context = NormalizationContext(field_name="f", semantic_type=t, **ctx)
            r = d.normalize(v, t, context, SCAFFOLD_PROFILE)
            if r.original_kind is not None:
                continue
            row = {
                "type": t.value,
                "context": json.dumps(ctx),
                "value": v,
                "readings": _readings(r, t),
            }
            (refused if r.normalization_status is S.AMBIGUOUS else answered).append(row)
    per = args.n // 2

    # spread each half over the types
    def pick(rows: list[dict], k: int) -> list[dict]:
        by_type: dict[str, list[dict]] = {}
        for row in rows:
            by_type.setdefault(row["type"], []).append(row)
        out: list[dict] = []
        while len(out) < k and any(by_type.values()):
            for t in sorted(by_type):
                if by_type[t] and len(out) < k:
                    out.append(by_type[t].pop(0))
        return out

    sheet = pick(refused, per) + pick(answered, args.n - per)
    rng.shuffle(sheet)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for person in ("A", "B"):
        with (out_dir / f"labels_person_{person}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(
                ["id", "type", "context", "value", "choices", "your_answer", "if_something_else"]
            )
            for i, row in enumerate(sheet, 1):
                choices = [*row["readings"], CANT_TELL, MISSING, OTHER]
                numbered = " | ".join(f"{n}) {c}" for n, c in enumerate(choices, 1))
                w.writerow([i, row["type"], row["context"], row["value"], numbered, "", ""])
    key = [{"id": i, **row} for i, row in enumerate(sheet, 1)]
    (out_dir / "engine_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1))
    print(
        f"{len(sheet)} rows: {sum(1 for r in sheet if r in refused)} refused by the engine, "
        f"{sum(1 for r in sheet if r in answered)} answered -> {out_dir}"
    )


if __name__ == "__main__":
    main()
