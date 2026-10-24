"""Capture TODAY's `suggest_semantic_type` output over planted columns (D4 acceptance).

Run ONCE, on the code as it was before D4 (2026-10-06):
    uv run python tests/defects/capture_d4_detection_snapshot.py
Writes tests/defects/d4_detection_snapshot.json. A regression snapshot of OLD output (not
truth): after D4 the column-type results must be byte-identical. NEVER regenerate it after
the fix (that would make the identity check vacuous). Not collected by pytest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from normanalysis.type_detection import suggest_semantic_type
from normapi.app import build_normalizer_registry

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "tests"))

# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
from defects import fixtures_phase23 as fx  # noqa: E402

# Field names chosen so the name layer alone, the name+values layer and the values-only layer
# are all exercised; the same names are re-used with every planted column.
FIELD_NAMES = ("dob", "country", "col_a", "value")
NAME_ONLY = (
    "mobile", "dob", "customer_name", "user_id", "email", "company_name", "first_name",
    "last_name", "zip_code", "country", "website", "uuid", "isPublic", "displayName",
    "quantity", "currency", "language", "tax_id", "amount", "logo",
)  # fmt: skip


REGISTRY = build_normalizer_registry()


def _row(field: str, sample: list[str] | None) -> list[list[object]]:
    out = suggest_semantic_type(field, sample_values=sample, registry=REGISTRY if sample else None)
    return [[str(s.semantic_type), s.confidence, s.reason] for s in out]


def snapshot() -> dict[str, object]:
    columns = [*fx.build_d4_columns(), fx.MAGIC_NUMBER_COLUMN]
    cases: dict[str, object] = {f"name_only|{n}": _row(n, None) for n in NAME_ONLY}
    for col in columns:
        for field in FIELD_NAMES:
            cases[f"{col.name}|{field}|first20"] = _row(field, col.values[:20])
    return {"cases": cases}


if __name__ == "__main__":
    (Path(__file__).with_name("d4_detection_snapshot.json")).write_text(
        json.dumps(snapshot(), indent=1, sort_keys=True) + "\n"
    )
