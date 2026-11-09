"""D31 (owner "b7. a"): LANGUAGE is confirmed by a language-code validator, only
with a matching column name; NUMERIC and FREE_TEXT are never inferred from values."""

from __future__ import annotations

import pytest
from normanalysis.type_detection import suggest_semantic_type
from normapi.app import build_normalizer_registry

from normapi import clone_executor
from normcore import FieldSemanticType, NormalizerRegistry

pytestmark = pytest.mark.unit

_TAGS = ["en", "de", "fr-CA", "pt-BR", "es"]


@pytest.fixture(scope="module")
def registry() -> NormalizerRegistry:
    return build_normalizer_registry()


def _top(column: str, values: list[str], registry: NormalizerRegistry) -> tuple[str, float]:
    best = suggest_semantic_type(column, sample_values=values, registry=registry)[0]
    return best.semantic_type.value, best.confidence


def test_a_lang_column_of_valid_tags_reaches_the_apply_line(registry: NormalizerRegistry) -> None:
    semantic_type, confidence = _top("lang", _TAGS, registry)
    assert semantic_type == "LANGUAGE"
    assert confidence >= clone_executor._AUTODETECT_MIN_CONFIDENCE


def test_a_lang_column_of_other_values_stays_below_it(registry: NormalizerRegistry) -> None:
    best = suggest_semantic_type(
        "lang", sample_values=["zzzzzz1", "qq qq", "12345"], registry=registry
    )
    language = next(s for s in best if s.semantic_type is FieldSemanticType.LANGUAGE)
    assert language.confidence < clone_executor._AUTODETECT_MIN_CONFIDENCE


@pytest.mark.parametrize("column", ["code", "status", "slang"])
def test_language_needs_the_column_name(column: str, registry: NormalizerRegistry) -> None:
    candidates = suggest_semantic_type(column, sample_values=_TAGS, registry=registry)
    assert all(
        s.semantic_type is not FieldSemanticType.LANGUAGE
        or s.confidence < clone_executor._AUTODETECT_MIN_CONFIDENCE
        for s in candidates
    )


@pytest.mark.parametrize("column", ["code", "number", "reference"])
def test_leading_zeros_are_not_numeric(column: str, registry: NormalizerRegistry) -> None:
    semantic_type, confidence = _top(column, ["00123", "00456", "00789"], registry)
    assert semantic_type != "NUMERIC" or confidence < clone_executor._AUTODETECT_MIN_CONFIDENCE


def test_the_apply_line_is_still_nine_tenths() -> None:
    assert clone_executor._AUTODETECT_MIN_CONFIDENCE == 0.9
