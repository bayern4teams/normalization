"""ftfy false-positive corpus — ADR-002's mandatory M2 gate requirement:
"a corpus of correctly-decoded, heavily-accented, multi-script text that
MUST emerge byte-identical after both stages."

Every value here is valid, correctly-decoded Unicode text (no encoding
corruption). `repair_mojibake` / the pipeline's `text_repair` step must
never fire on any of them — firing would mean ftfy is producing a false
positive, corrupting good data.
"""

# This corpus deliberately contains non-Latin script samples and an
# em-dash literal as test fixtures, not typos.
# ruff: noqa: RUF001

from __future__ import annotations

from pathlib import Path

import pytest
from normalizers.generic_text import GenericTextNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, QualityFlag
from normdict.loader import DictionaryLoader

from normalizers import text_ops

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"

# Correctly-decoded, heavily-accented, multi-script strings. None of these
# are mojibake -- they are exactly what a correctly-configured UTF-8
# pipeline produces, and must survive ftfy untouched.
CLEAN_TEXT_SAMPLES: tuple[str, ...] = (
    "café",
    "naïve",
    "ZURÜCK",  # ftfy 6.3's own documented uppercase-German heuristic target
    "über die Straße",
    "Müller-Lüdenscheidt",
    "façade",
    "señor",
    "château",
    "Ångström",
    "Kraków",
    "İstanbul",
    "Zürich",
    "São Paulo",
    "Þórshöfn",
    "Reykjavík",
    "Đorđe",
    "Wrocław",
    "Košice",
    "Brønnøysund",
    "Москва",  # Cyrillic, correctly decoded
    "北京",  # Chinese, correctly decoded
    "東京",  # Japanese, correctly decoded
    "한국어",  # Korean, correctly decoded
    "الرياض",  # Arabic, correctly decoded
    "ירושלים",  # Hebrew, correctly decoded
    "Αθήνα",  # Greek, correctly decoded
    "मुंबई",  # Hindi, correctly decoded
    "plain ascii text with no diacritics at all",
    "punctuation: quotes \"like this\" and 'this', em—dash, en–dash",
)


@pytest.fixture(scope="module")
def normalizer() -> GenericTextNormalizer:
    return GenericTextNormalizer(DictionaryLoader(_DICT_ROOT))


@pytest.fixture(scope="module")
def ctx() -> NormalizationContext:
    return NormalizationContext(field_name="notes", semantic_type=FieldSemanticType.FREE_TEXT)


@pytest.mark.golden
@pytest.mark.parametrize("value", CLEAN_TEXT_SAMPLES)
def test_repair_mojibake_reports_no_change_on_clean_text(value: str) -> None:
    output, changed, explanations = text_ops.repair_mojibake(value)
    assert output == value, f"ftfy altered correctly-decoded text: {value!r} -> {output!r}"
    assert changed is False
    assert explanations == []


@pytest.mark.golden
@pytest.mark.parametrize("value", CLEAN_TEXT_SAMPLES)
def test_pipeline_never_flags_clean_text_as_repaired(
    normalizer: GenericTextNormalizer, ctx: NormalizationContext, value: str
) -> None:
    result = normalizer.normalize(value, ctx)
    assert result.repaired is None, f"false-positive repair on {value!r}"
    assert QualityFlag.MOJIBAKE_FIXED not in result.flags
    assert QualityFlag.ENCODING_REPAIRED not in result.flags
