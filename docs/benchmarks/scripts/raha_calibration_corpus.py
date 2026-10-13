"""Raha corpus for `normcli calibrate`: erroneous cells only (dirty != clean).

Unchanged cells are left out: their canonical truth is the engine's own answer on the same input, so
scoring them would be circular. Also left out: `beers.ounces` (the clean value drops the unit) and
cells equal to the truth as a number but not as a comparison key (`7.0` vs `7`), and cells where
either side is missing (no value claim to calibrate). All are reported in REPORT.md.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from normanalysis.gold import GoldCase, classify, default_engine

sys.path.insert(0, str(Path(__file__).parent))
from raha_accuracy import COLUMNS, MISSING, _refine

TRUTH = {"NORMALIZED": "PARSED", "PARSED": "PARSED", "UNCHANGED": "PARSED"}


def main(src_dir: str, out_path: str) -> None:
    lines, kept, skipped = [], 0, 0
    for dataset, (context, columns) in COLUMNS.items():
        for column, sem in columns.items():
            if column == "ounces":
                continue
            with (Path(src_dir) / f"{dataset}.{column}.csv").open(
                newline="", encoding="utf-8"
            ) as f:
                for row in csv.DictReader(f):
                    d, c = row["dirty"], row["clean"]
                    if d == c:
                        continue
                    t_status, t_value, _ = default_engine(
                        GoldCase(sem, context, c, "PARSED", "", (), "p")
                    )
                    truth = TRUTH.get(t_status, t_status)
                    if truth not in ("PARSED", "AMBIGUOUS"):
                        continue
                    t_value = MISSING if t_value is None else t_value
                    case = GoldCase(
                        sem,
                        context,
                        d,
                        truth,
                        t_value if truth == "PARSED" else None,
                        (),
                        f"raha:{dataset}.{column}",
                    )
                    status, value, _ = default_engine(case)
                    value = MISSING if value is None else value
                    refined = _refine(classify(case, status, value), sem, value, t_value)
                    if MISSING in (t_value, value) or refined == "equal-as-number":
                        skipped += 1  # no value claim to calibrate, or a format-only difference
                        continue
                    kept += 1
                    lines.append(
                        json.dumps(
                            case.__dict__ | {"candidates": []}, ensure_ascii=False, sort_keys=True
                        )
                    )
    Path(out_path).write_text("\n".join(lines) + "\n")
    print(f"kept {kept} erroneous cells, skipped {skipped} (missing on a side, or equal as number)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
