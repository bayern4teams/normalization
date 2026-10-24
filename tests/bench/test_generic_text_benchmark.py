"""Performance baseline for GenericTextNormalizer — Source.txt §102, §122;
Gate G2 requirement ("performance baseline recorded, becomes the
no-regression reference for all later gates").

Run via `uv run pytest -m bench --benchmark-json=bench-results.json`.
`.github/workflows/gate.yml` and `release.yml` already wire this into the
gate/release pipeline (from M0) — this is the first real `bench`-marked
test for them to actually execute against.
"""

# One sample value below deliberately contains a Cyrillic confusable
# character, matching the mixed-script case a real workload would see.
# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
# ruff: noqa: RUF001

from __future__ import annotations

from pathlib import Path

import pytest
from normalizers.generic_text import GenericTextNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType
from normdict.loader import DictionaryLoader

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"

# A representative mixed batch: plain ASCII, accented Latin, mojibake
# needing repair, mixed-script, and whitespace-messy values — the same
# mix a real free-text column would contain, not a best-case single value.
_SAMPLE_VALUES: tuple[str, ...] = (
    "hello world",
    "  José   García  ",
    "cafÃ© au lait",
    "plain text with no special characters whatsoever",
    "ZURÜCK zum Bahnhof",
    "北京市 East District",
    "  multiple   spaces   here  ",
    "N/A",
    'a normal sentence with punctuation, quotes "like this", and more.',
    "hаrvest season",
)


@pytest.fixture(scope="module")
def normalizer() -> GenericTextNormalizer:
    return GenericTextNormalizer(DictionaryLoader(_DICT_ROOT))


@pytest.fixture(scope="module")
def ctx() -> NormalizationContext:
    return NormalizationContext(field_name="notes", semantic_type=FieldSemanticType.FREE_TEXT)


@pytest.mark.bench
def test_bench_normalize_single_value(
    benchmark: object, normalizer: GenericTextNormalizer, ctx: NormalizationContext
) -> None:  # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    benchmark(normalizer.normalize, "  José   García, Jr.  ", ctx)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_normalize_mixed_batch_of_1000(
    benchmark: object, normalizer: GenericTextNormalizer, ctx: NormalizationContext
) -> None:
    values = [_SAMPLE_VALUES[i % len(_SAMPLE_VALUES)] for i in range(1000)]

    def run() -> None:
        for value in values:
            normalizer.normalize(value, ctx)

    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    benchmark(run)  # type: ignore[operator]
