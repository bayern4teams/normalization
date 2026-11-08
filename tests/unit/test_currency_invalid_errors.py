"""D29: an INVALID currency says why and how to fix it, so a clone writes an error row."""

from __future__ import annotations

import pytest
from normalizers.currency import CurrencyNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus


def _normalize(value: str):
    ctx = NormalizationContext(field_name="c", semantic_type=FieldSemanticType.CURRENCY)
    return CurrencyNormalizer().normalize(value, ctx)


@pytest.mark.parametrize("value", ["XYZ", "XTS", "XXX", "xxx", "999", "963", "TBD"])
def test_invalid_with_a_message_that_says_how_to_fix_it(value: str) -> None:
    result = _normalize(value)
    assert result.normalization_status is NormalizationStatus.INVALID
    assert result.comparison is None
    assert len(result.errors) == 1
    assert "ISO 4217" in result.errors[0]
    assert "replace" in result.errors[0].lower()


def test_real_code_is_untouched() -> None:
    result = _normalize("USD")
    assert result.comparison == "USD"
    assert result.errors == []


def test_explain_does_not_claim_a_resolution() -> None:
    result = _normalize("XYZ")
    assert "Resolved" not in CurrencyNormalizer().explain(result).plain_language
