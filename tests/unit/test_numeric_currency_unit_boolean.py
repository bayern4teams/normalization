"""Unit tests for NumericNormalizer, CurrencyNormalizer, UnitNormalizer,
BooleanNormalizer — Source.txt Phase 12 (§46-§48, §52)."""

from __future__ import annotations

import pytest
from normalizers.boolean import BooleanNormalizer
from normalizers.currency import CurrencyNormalizer
from normalizers.numeric import NumericNormalizer
from normalizers.unit import UnitNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus


def _ctx(
    semantic_type: FieldSemanticType, *, country: str | None = None, locale: str | None = None
) -> NormalizationContext:
    return NormalizationContext(
        field_name="f", semantic_type=semantic_type, country=country, locale=locale
    )


# --- NumericNormalizer ------------------------------------------------


@pytest.fixture(scope="module")
def numeric_normalizer() -> NumericNormalizer:
    return NumericNormalizer()


@pytest.mark.unit
class TestNumericNormalizer:
    def test_supported_types(self, numeric_normalizer: NumericNormalizer) -> None:
        assert numeric_normalizer.supported_types == frozenset({FieldSemanticType.NUMERIC})

    def test_none_and_empty(self, numeric_normalizer: NumericNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.NUMERIC)
        assert numeric_normalizer.normalize(None, ctx).original_kind is MissingKind.NULL
        assert numeric_normalizer.normalize("", ctx).original_kind is MissingKind.EMPTY_STRING

    def test_us_thousands_dot_decimal(self, numeric_normalizer: NumericNormalizer) -> None:
        """Source.txt §46's own worked example: "1,234.56"."""
        result = numeric_normalizer.normalize("1,234.56", _ctx(FieldSemanticType.NUMERIC))
        assert result.display == "1234.56"

    def test_european_dot_thousands_comma_decimal(
        self, numeric_normalizer: NumericNormalizer
    ) -> None:
        """Source.txt §46's own worked example: "1.234,56"."""
        result = numeric_normalizer.normalize("1.234,56", _ctx(FieldSemanticType.NUMERIC))
        assert result.display == "1.23456"

    def test_bare_thousands_grouping_is_ambiguous_without_context(
        self, numeric_normalizer: NumericNormalizer
    ) -> None:
        result = numeric_normalizer.normalize("1,234", _ctx(FieldSemanticType.NUMERIC))
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS

    def test_context_resolves_ambiguous_grouping_as_thousands(
        self, numeric_normalizer: NumericNormalizer
    ) -> None:
        result = numeric_normalizer.normalize(
            "1,234", _ctx(FieldSemanticType.NUMERIC, country="US")
        )
        assert result.display == "1234"

    def test_context_resolves_ambiguous_grouping_as_decimal(
        self, numeric_normalizer: NumericNormalizer
    ) -> None:
        result = numeric_normalizer.normalize(
            "1,234", _ctx(FieldSemanticType.NUMERIC, country="DE")
        )
        assert result.display == "1.234"

    def test_repeated_grouping_is_unambiguous(self, numeric_normalizer: NumericNormalizer) -> None:
        result = numeric_normalizer.normalize("1,234,567", _ctx(FieldSemanticType.NUMERIC))
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.display == "1234567"

    def test_parentheses_negative(self, numeric_normalizer: NumericNormalizer) -> None:
        """Source.txt §46's own worked example: "(1,234.56)"."""
        result = numeric_normalizer.normalize("(1,234.56)", _ctx(FieldSemanticType.NUMERIC))
        assert result.display == "-1234.56"

    def test_leading_currency_symbol_stripped_and_recorded(
        self, numeric_normalizer: NumericNormalizer
    ) -> None:
        """Source.txt §46's own worked example: "£1,234.56"."""
        result = numeric_normalizer.normalize("£1,234.56", _ctx(FieldSemanticType.NUMERIC))
        assert result.display == "1234.56"
        assert result.structured["leading_symbol"] == "£"

    def test_original_never_overwritten(self, numeric_normalizer: NumericNormalizer) -> None:
        raw = "  1,234.56  "
        result = numeric_normalizer.normalize(raw, _ctx(FieldSemanticType.NUMERIC))
        assert result.original == raw


# --- CurrencyNormalizer ----------------------------------------------


@pytest.fixture(scope="module")
def currency_normalizer() -> CurrencyNormalizer:
    return CurrencyNormalizer()


@pytest.mark.unit
class TestCurrencyNormalizer:
    def test_supported_types(self, currency_normalizer: CurrencyNormalizer) -> None:
        assert currency_normalizer.supported_types == frozenset({FieldSemanticType.CURRENCY})

    def test_bare_dollar_sign_stays_ambiguous(
        self, currency_normalizer: CurrencyNormalizer
    ) -> None:
        """Source.txt §47's own worked example: bare "$" is ambiguous
        and stays ambiguous without context."""
        result = currency_normalizer.normalize("$", _ctx(FieldSemanticType.CURRENCY))
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS

    def test_dollar_sign_resolves_with_country_context(
        self, currency_normalizer: CurrencyNormalizer
    ) -> None:
        result = currency_normalizer.normalize("$", _ctx(FieldSemanticType.CURRENCY, country="US"))
        assert result.display == "USD"

    def test_iso_code_always_resolves(self, currency_normalizer: CurrencyNormalizer) -> None:
        result = currency_normalizer.normalize("USD", _ctx(FieldSemanticType.CURRENCY))
        assert result.display == "USD"
        assert result.confidence == 1.0

    def test_full_name_resolves(self, currency_normalizer: CurrencyNormalizer) -> None:
        """Source.txt §47's own worked example: "US Dollars"."""
        result = currency_normalizer.normalize("US Dollars", _ctx(FieldSemanticType.CURRENCY))
        assert result.display == "USD"

    def test_us_dollar_variant_resolves(self, currency_normalizer: CurrencyNormalizer) -> None:
        """Source.txt §47's own worked example: "US$"."""
        result = currency_normalizer.normalize(
            "US$", _ctx(FieldSemanticType.CURRENCY, country="US")
        )
        assert result.display == "USD"


# --- UnitNormalizer -----------------------------------------------------


@pytest.fixture(scope="module")
def unit_normalizer() -> UnitNormalizer:
    return UnitNormalizer()


@pytest.mark.unit
class TestUnitNormalizer:
    def test_supported_types(self, unit_normalizer: UnitNormalizer) -> None:
        assert unit_normalizer.supported_types == frozenset({FieldSemanticType.QUANTITY})

    def test_km_and_m_convert_to_same_base_value(self, unit_normalizer: UnitNormalizer) -> None:
        """Source.txt §48's own worked example: "5 km" / "5000 m"."""
        ctx = _ctx(FieldSemanticType.QUANTITY)
        km_result = unit_normalizer.normalize("5 km", ctx)
        m_result = unit_normalizer.normalize("5000 m", ctx)
        assert km_result.structured["canonical_unit"] == m_result.structured["canonical_unit"]
        assert float(km_result.structured["canonical_value"]) == float(
            m_result.structured["canonical_value"]
        )

    def test_original_value_and_unit_retained(self, unit_normalizer: UnitNormalizer) -> None:
        result = unit_normalizer.normalize("5 km", _ctx(FieldSemanticType.QUANTITY))
        assert result.structured["original_value"] == "5"
        assert "kilometer" in result.structured["original_unit"]

    def test_unrecognized_unit_is_invalid(self, unit_normalizer: UnitNormalizer) -> None:
        result = unit_normalizer.normalize("5 fakeunit", _ctx(FieldSemanticType.QUANTITY))
        assert result.normalization_status is NormalizationStatus.INVALID

    def test_bare_number_with_no_unit_is_dimensionless_not_invalid(
        self, unit_normalizer: UnitNormalizer
    ) -> None:
        """Pint treats a bare number as a genuinely valid "dimensionless"
        quantity (found empirically in M5) rather than an error — this
        normalizer reports that honestly via `dimensionality`, which
        callers can check for fields that require a real unit, rather
        than this normalizer silently inventing a rejection."""
        result = unit_normalizer.normalize("42", _ctx(FieldSemanticType.QUANTITY))
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.structured["dimensionality"] == "dimensionless"


# --- BooleanNormalizer --------------------------------------------------


@pytest.fixture(scope="module")
def boolean_normalizer() -> BooleanNormalizer:
    return BooleanNormalizer()


@pytest.mark.unit
class TestBooleanNormalizer:
    def test_supported_types(self, boolean_normalizer: BooleanNormalizer) -> None:
        assert boolean_normalizer.supported_types == frozenset({FieldSemanticType.BOOLEAN})

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "yes", "Yes", "Y", "1"])
    def test_true_synonyms(self, boolean_normalizer: BooleanNormalizer, value: str) -> None:
        """Source.txt §52's own worked example."""
        result = boolean_normalizer.normalize(value, _ctx(FieldSemanticType.BOOLEAN))
        assert result.display == "true"
        assert result.structured["canonical_value"] is True

    @pytest.mark.parametrize("value", ["false", "False", "no", "N", "0"])
    def test_false_synonyms(self, boolean_normalizer: BooleanNormalizer, value: str) -> None:
        result = boolean_normalizer.normalize(value, _ctx(FieldSemanticType.BOOLEAN))
        assert result.display == "false"
        assert result.structured["canonical_value"] is False

    @pytest.mark.parametrize("value", ["maybe", "unknown", "N/A"])
    def test_ambiguous_values_never_silently_coerced(
        self, boolean_normalizer: BooleanNormalizer, value: str
    ) -> None:
        """Source.txt §52: "maybe"/"unknown"/"N/A" -> NULL/UNKNOWN, never
        silently coerced to true or false."""
        result = boolean_normalizer.normalize(value, _ctx(FieldSemanticType.BOOLEAN))
        assert result.original_kind is MissingKind.UNKNOWN_VALUE
        assert result.display is None

    def test_unrecognized_text_is_invalid_not_coerced(
        self, boolean_normalizer: BooleanNormalizer
    ) -> None:
        result = boolean_normalizer.normalize("banana", _ctx(FieldSemanticType.BOOLEAN))
        assert result.normalization_status is NormalizationStatus.INVALID

    def test_original_preserved(self, boolean_normalizer: BooleanNormalizer) -> None:
        result = boolean_normalizer.normalize("YES", _ctx(FieldSemanticType.BOOLEAN))
        assert result.original == "YES"
