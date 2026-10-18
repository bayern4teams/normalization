"""DeepMatcher labelled pairs: do comparison keys agree on matches and differ on non-matches?

For each (dataset, column, semantic type): over all labelled pairs (train+valid+test) where both
sides are non-empty, the rate of equal raw strings vs equal `comparison` keys, separately for
label 1 (same entity) and label 0. Keys are match candidates, not identity.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from normapi.app import build_dispatcher
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType

ROOT = Path(os.environ["BENCH_DIR"]) / "datasets" / "A"
CASES = [
    ("structured-amazon-google", "manufacturer", "COMPANY_NAME"),
    ("structured-dblp-acm", "year", "DATE"),
    ("dirty-dblp-acm", "year", "DATE"),
]


def _table(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def main() -> None:
    d = build_dispatcher(env_id="bench-em")
    out = []
    for name, column, sem in CASES:
        base = next((ROOT / f"deepmatcher-{name}").rglob("tableA.csv")).parent
        a, b = _table(base / "tableA.csv"), _table(base / "tableB.csv")
        ctx = NormalizationContext(field_name=column, semantic_type=FieldSemanticType(sem))
        key_cache: dict[str, str | None] = {}

        def key(
            v: str,
            ctx: NormalizationContext = ctx,
            sem: str = sem,
            key_cache: dict[str, str | None] = key_cache,
        ) -> str | None:
            if v not in key_cache:
                r = d.normalize(v, FieldSemanticType(sem), ctx, SCAFFOLD_PROFILE)
                key_cache[v] = r.comparison if r.comparison is not None else r.display
            return key_cache[v]

        stats = {lab: {"pairs": 0, "raw_equal": 0, "key_equal": 0} for lab in ("1", "0")}
        for split in ("train", "valid", "test"):
            with (base / f"{split}.csv").open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    va = a[r["ltable_id"]][column].strip()
                    vb = b[r["rtable_id"]][column].strip()
                    if not va or not vb:
                        continue
                    s = stats[r["label"]]
                    s["pairs"] += 1
                    s["raw_equal"] += va == vb
                    ka, kb = key(va), key(vb)
                    s["key_equal"] += ka is not None and ka == kb
        out.append({"dataset": name, "column": column, "type": sem, "by_label": stats})
        print(json.dumps(out[-1]), flush=True)


if __name__ == "__main__":
    main()
