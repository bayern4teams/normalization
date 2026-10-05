"""Capture today's NameNormalizer output over Latin-script names (D11 acceptance (d)).

Run ONCE, on the code as it was before D11 (2026-10-05, jellyfish 1.2.1):
    uv run python tests/defects/capture_d11_latin_snapshot.py
Writes tests/defects/d11_latin_snapshot.json. This is a regression snapshot of OLD
output (not truth): after D11 every Latin input must still produce these bytes for
all pre-existing fields, the four legacy phonetic keys included. Not collected by pytest.
"""

from __future__ import annotations

import json
from pathlib import Path

from normalizers.name import NameNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType as F
from normdict.loader import DictionaryLoader

ROOT = Path(__file__).parents[2]

SINGLE = (
    "Smith", "Robert", "Rupert", "Muhammad", "Mohammed", "Mohammad", "Yuri", "Yury", "Olga",
    "Müller", "José", "Łukasz", "Dvořák", "O'Brien", "McDonald", "Fitzgerald", "Nguyen",
    "Washington", "Wojciechowski", "Schwarzenegger", "Jean-Pierre", "Garcia-Lopez", "SMITH",
    "  smith  ", "Aleksandr", "Yelena", "Hossein", "Ahmad", "Mariya", "d'Artagnan",
)  # fmt: skip
PERSON = (
    "Dr. John Smith Jr.", "Smith, John", "John Smith", "María José García López",
    "Anna Maria Mueller", "Ludwig van Beethoven", "Mr. Robert Rupert Jones III",
    "Jean-Pierre Dupont", "Muhammad Ali Khan", "Yuri Alexandrovich Gagarin",
)  # fmt: skip


def snapshot() -> list[dict[str, object]]:
    norm = NameNormalizer(DictionaryLoader(ROOT / "data" / "dictionaries"))
    cases: list[tuple[F, str]] = [(t, s) for s in SINGLE for t in (F.FAMILY_NAME, F.GIVEN_NAME)]
    cases += [(F.PERSON_NAME, p) for p in PERSON]
    out = []
    for sem, text in cases:
        ctx = NormalizationContext(field_name="f", semantic_type=sem)
        r = norm.normalize(text, ctx)
        out.append(
            {
                "semantic_type": sem.name,
                "input": text,
                "display": r.display,
                "comparison": r.comparison,
                "search": r.search,
                "structured": r.structured,
                "validation_status": r.validation_status,
                "normalization_status": r.normalization_status.value,
                "confidence": r.confidence,
            }
        )
    return out


if __name__ == "__main__":
    path = Path(__file__).with_name("d11_latin_snapshot.json")
    path.write_text(json.dumps(snapshot(), ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(f"wrote {len(snapshot())} cases to {path}")
