# ruff: noqa: E501 - report lines read better unwrapped in a one-off script
"""PART1 D6.3: agreement between two people's labels (kappa_sample.py sheets).

Each answer is the chosen reading's text ("something else" plus the person's own text counts as
that text). Prints Cohen's kappa, Krippendorff's alpha (nominal), the share of values the two read
differently or marked "can't tell" (the corpus's ambiguity rate), and how that set compares with
what the engine refused.

    uv run python docs/benchmarks/scripts/kappa_score.py .tmp/labels
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

from normanalysis.gold import cohen_kappa, krippendorff_alpha


def _answers(path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            choices = dict(re.findall(r"(\d+)\) ([^|]+?)(?= \| \d+\)|$)", row["choices"]))
            pick = (row["your_answer"] or "").strip().rstrip(")")
            text = choices.get(pick, "").strip()
            if text == "something else":
                text = f"else: {(row['if_something_else'] or '').strip().casefold()}"
            out[int(row["id"])] = text or "(blank)"
    return out


def main(folder: str) -> None:
    d = Path(folder)
    a, b = _answers(d / "labels_person_A.csv"), _answers(d / "labels_person_B.csv")
    ids = sorted(set(a) & set(b))
    la, lb = [a[i] for i in ids], [b[i] for i in ids]
    key = {r["id"]: r for r in json.loads((d / "engine_key.json").read_text())}
    disputed = {i for i in ids if a[i] != b[i] or "can't tell" in (a[i], b[i])}
    refused = {
        i
        for i in ids
        if len(key[i]["readings"]) > 1 or "needing more context" in key[i]["readings"][0]
    }
    print(
        f"items {len(ids)}; Cohen's kappa {cohen_kappa(la, lb):.3f}; "
        f"Krippendorff's alpha {krippendorff_alpha([la, lb]):.3f}"
    )
    print(
        f"ambiguity rate (disagree or can't tell): {len(disputed)}/{len(ids)} = {len(disputed) / len(ids):.1%}"
    )
    print(
        f"engine refused {len(refused)}; of those disputed by people {len(refused & disputed)}; "
        f"engine answered but people disputed {len(disputed - refused)}"
    )
    for i in sorted(disputed - refused):
        print(
            f"  answered, disputed: #{i} {key[i]['type']} {key[i]['value']!r}: A={a[i]!r} B={b[i]!r}"
        )


if __name__ == "__main__":
    main(sys.argv[1])
