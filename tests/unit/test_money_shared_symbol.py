"""D30: an amount with a symbol several currencies share is a question about the currency."""

from __future__ import annotations

from normalizers._cldr_currency_names import CLDR_SHARED_CURRENCY_SYMBOLS
from normalizers.money import MoneyNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus


def _normalize(value: str, country: str | None = None):
    ctx = NormalizationContext(
        field_name="m", semantic_type=FieldSemanticType.MONEY, country=country
    )
    return MoneyNormalizer().normalize(value, ctx)


def test_dollar_without_a_country_is_ambiguous_and_keeps_the_amount() -> None:
    result = _normalize("$5")
    assert result.normalization_status is NormalizationStatus.AMBIGUOUS
    assert result.structured["canonical_amount"] == "5"
    assert result.structured["currency"] is None
    assert result.comparison is None
    codes = CLDR_SHARED_CURRENCY_SYMBOLS["$"].split()
    assert result.structured["candidates"] == [f"5 {code}" for code in codes]
    assert result.errors


def test_each_reading_is_a_value_a_reviewer_can_decide() -> None:
    for reading in _normalize("$5").structured["candidates"]:
        assert _normalize(reading).normalization_status is NormalizationStatus.NORMALIZED


def test_country_settles_it() -> None:
    result = _normalize("$5", country="US")
    assert result.normalization_status is NormalizationStatus.NORMALIZED
    assert result.comparison == "5 USD"


def test_no_symbol_at_all_stays_normalized() -> None:
    result = _normalize("5")
    assert result.normalization_status is NormalizationStatus.NORMALIZED
    assert result.comparison == "5"


def test_other_shared_symbols_follow_the_same_rule() -> None:
    assert _normalize("£5").normalization_status is NormalizationStatus.AMBIGUOUS


def test_validate_accepts_an_amount_whose_currency_is_the_only_question() -> None:
    ctx = NormalizationContext(field_name="m", semantic_type=FieldSemanticType.MONEY)
    assert MoneyNormalizer().validate("$5", ctx).is_valid
    assert not MoneyNormalizer().validate("free", ctx).is_valid
