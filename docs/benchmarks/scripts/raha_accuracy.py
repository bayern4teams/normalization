"""Tier A accuracy on the Raha/Baran datasets (dirty.csv vs clean.csv, aligned by row).

Canonical-truth method: the truth for a cell is the engine's own reading of the CLEAN value in the
same column context; the dirty value is scored against it with `normanalysis.gold.classify`. The
literal method (`normcli gold score` on dirty/clean CSVs) is run separately, as LOCAL_VERIFY says.

The column -> semantic type map below was fixed from the headers before any scoring (held-out:
it is never changed to move a number). Columns with no matching semantic type are not scored.
Writes per-column results, a JSONL corpus (for `normcli calibrate`) and dirty/clean CSVs.
"""

from __future__ import annotations

import csv
import decimal
import json
import sys
from collections import Counter
from pathlib import Path

from normanalysis.gold import GoldCase, classify, default_engine

ROOT = Path("data/benchmarks/A")
US = {"country": "US", "locale": "en-US"}
COLUMNS: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "hospital": (
        US,
        {
            "name": "COMPANY_NAME",
            "address_1": "ADDRESS",
            "zip": "POSTCODE",
            "phone": "PHONE",
            "emergency_service": "BOOLEAN",
            "score": "NUMERIC",
            "sample": "NUMERIC",
        },
    ),
    "beers": (
        US,
        {"ounces": "QUANTITY", "abv": "NUMERIC", "ibu": "NUMERIC", "brewery_name": "COMPANY_NAME"},
    ),
    "rayyan": (
        US,
        {
            "article_language": "LANGUAGE",
            "article_jcreated_at": "DATE",
            "article_jvolumn": "NUMERIC",
            "article_jissue": "NUMERIC",
        },
    ),
    "movies_1": (
        US,
        {
            "year": "DATE",
            "release_date": "DATE",
            "country": "COUNTRY",
            "duration": "QUANTITY",
            "rating_value": "NUMERIC",
            "rating_count": "NUMERIC",
        },
    ),
    "tax": (
        US,
        {
            "f_name": "GIVEN_NAME",
            "l_name": "FAMILY_NAME",
            "zip": "POSTCODE",
            "has_child": "BOOLEAN",
            "salary": "NUMERIC",
            "rate": "NUMERIC",
        },
    ),
    # flights: departure/arrival times of day; no TIME semantic type exists -> not scored
}
_TRUTH_STATUS = {"NORMALIZED": "PARSED", "PARSED": "PARSED", "UNCHANGED": "PARSED"}
MISSING = "<missing>"  # a clean answer with no value (a missing-value token), on both sides


def _refine(outcome: str, sem: str, value: str, truth: str) -> str:
    """Split two kinds out of `wrong-confident` (reported separately, never merged into
    `correct`): a deleted source value the engine leaves empty instead of inventing one, and a
    NUMERIC answer equal to the truth as a number (`7.0` vs `7`) but not as a comparison key."""
    if outcome != "wrong-confident":
        return outcome
    if value == MISSING:
        return "missing-in-source"
    if sem == "NUMERIC" and MISSING not in (value, truth):
        try:
            if decimal.Decimal(value) == decimal.Decimal(truth):
                return "equal-as-number"
        except decimal.InvalidOperation:
            pass
    return outcome


def _rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """Header and rows. Raha's clean.csv names its columns differently (HospitalName vs name)
    but keeps the same order, so dirty and clean are aligned by position."""
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results, corpus = [], []
    for dataset, (context, columns) in COLUMNS.items():
        header, dirty = _rows(ROOT / f"raha-{dataset}" / "dirty.csv")
        clean_header, clean = _rows(ROOT / f"raha-{dataset}" / "clean.csv")
        assert len(header) == len(clean_header), dataset
        assert len(dirty) == len(clean), dataset
        for column, sem in columns.items():
            counts: Counter[str] = Counter()
            err_counts: Counter[str] = Counter()
            truth_unreadable = 0
            examples: list[dict[str, str]] = []
            with (out / f"{dataset}.{column}.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["dirty", "clean"])
                for d_row, c_row in zip(dirty, clean, strict=True):
                    d, c = d_row[header.index(column)], c_row[header.index(column)]
                    w.writerow([d, c])
                    probe = GoldCase(sem, context, c, "PARSED", "", (), "probe")
                    t_status, t_value, _ = default_engine(probe)
                    t_value = MISSING if t_value is None else t_value
                    truth_status = _TRUTH_STATUS.get(t_status, t_status)
                    if truth_status not in ("PARSED", "AMBIGUOUS"):
                        truth_unreadable += 1  # the engine cannot read the clean value itself
                        continue
                    case = GoldCase(
                        sem,
                        context,
                        d,
                        truth_status,
                        t_value if truth_status == "PARSED" else None,
                        (),
                        f"raha:{dataset}.{column}",
                    )
                    status, value, _ = default_engine(case)
                    value = MISSING if value is None else value
                    outcome = _refine(classify(case, status, value), sem, value, t_value)
                    counts[outcome] += 1
                    if d != c:
                        err_counts[outcome] += 1
                        if outcome == "wrong-confident" and len(examples) < 5:
                            examples.append(
                                {"dirty": d, "clean": c, "got": str(value), "truth": str(t_value)}
                            )
                    corpus.append(case)
            results.append(
                {
                    "dataset": dataset,
                    "column": column,
                    "type": sem,
                    "cells": len(dirty),
                    "truth_unreadable": truth_unreadable,
                    "all": dict(counts),
                    "erroneous": dict(err_counts),
                    "wrong_confident_examples": examples,
                }
            )
            print(
                dataset,
                column,
                sem,
                dict(counts),
                "| erroneous:",
                dict(err_counts),
                "| truth unreadable:",
                truth_unreadable,
                flush=True,
            )
    (out / "raha_accuracy.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    (out / "raha_corpus.jsonl").write_text(
        "".join(
            json.dumps(
                c.__dict__ | {"candidates": list(c.candidates)}, ensure_ascii=False, sort_keys=True
            )
            + "\n"
            for c in corpus
        )
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".tmp/bench/raha")
