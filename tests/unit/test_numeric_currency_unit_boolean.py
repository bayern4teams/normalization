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
        """Source.txt §46's own worked example: "1.234,56".

        Same amount as `test_us_thousands_dot_decimal` written the other
        way round, so it must produce the same number. This previously
        asserted "1.23456" — the US convention applied to a European
        value, i.e. the 1000x error this pair exists to catch.
        """
        result = numeric_normalizer.normalize("1.234,56", _ctx(FieldSemanticType.NUMERIC))
        assert result.display == "1234.56"

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


@pytest.mark.unit
class TestNumericSeparatorDisambiguation:
    """The module docstring's two context-free rules were documented but
    never implemented — every value went to Babel under "en_US", so any
    European-formatted amount came back silently wrong by a factor of
    10^n with NORMALIZED status and no error.
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # Rule 1: both separators present, the LAST one is decimal.
            ("1.234,56", "1234.56"),
            ("1,234.56", "1234.56"),
            ("1.234.567,89", "1234567.89"),
            ("1,234,567.89", "1234567.89"),
            # Rule 2: a single separator with a trailing run that is not
            # exactly 3 digits cannot be a thousands group.
            ("1,23", "1.23"),
            ("1,2345", "1.2345"),
            ("1.23", "1.23"),
            # A separator that repeats cannot be a decimal point.
            ("1.234.567", "1234567"),
            ("1,234,567", "1234567"),
        ],
    )
    def test_context_free_shapes_resolve_to_the_same_number(
        self, numeric_normalizer: NumericNormalizer, value: str, expected: str
    ) -> None:
        result = numeric_normalizer.normalize(value, _ctx(FieldSemanticType.NUMERIC))
        assert result.display == expected

    def test_genuinely_ambiguous_shape_still_refuses_to_guess(
        self, numeric_normalizer: NumericNormalizer
    ) -> None:
        """The fix must not turn AMBIGUOUS into a guess: one separator
        with exactly 3 trailing digits stays undecidable without a locale.
        """
        result = numeric_normalizer.normalize("1,234", _ctx(FieldSemanticType.NUMERIC))
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS

    def test_scientific_notation_is_not_mistaken_for_grouping(
        self, numeric_normalizer: NumericNormalizer
    ) -> None:
        """"1.5e3" has a 3-character trailing run, but it is not 3 DIGITS,
        so it is not an ambiguous thousands group."""
        result = numeric_normalizer.normalize("1.5e3", _ctx(FieldSemanticType.NUMERIC))
        assert result.normalization_status is not NormalizationStatus.AMBIGUOUS

    def test_currency_symbol_does_not_defeat_disambiguation(
        self, numeric_normalizer: NumericNormalizer
    ) -> None:
        result = numeric_normalizer.normalize("$1.234,56", _ctx(FieldSemanticType.NUMERIC))
        assert result.display == "1234.56"


@pytest.mark.unit
class TestCurrencyCodeRecognition:
    @pytest.mark.parametrize("value", ["USD", "usd", "Usd", "  usd  "])
    def test_iso_alpha_code_is_case_insensitive(self, value: str) -> None:
        """COUNTRY has always been case-insensitive; CURRENCY matched
        uppercase only, so a lowercase code came back AMBIGUOUS."""
        result = CurrencyNormalizer().normalize(value, _ctx(FieldSemanticType.CURRENCY))
        assert result.display == "USD"

    @pytest.mark.parametrize(("value", "expected"), [("840", "USD"), ("978", "EUR")])
    def test_iso_numeric_code_resolves(self, value: str, expected: str) -> None:
        result = CurrencyNormalizer().normalize(value, _ctx(FieldSemanticType.CURRENCY))
        assert result.display == expected

    def test_lowercase_prose_is_not_read_as_a_code(self) -> None:
        """"cup" IS a real ISO 4217 code (Cuban peso), so case-insensitive
        matching anywhere in the text would resolve ordinary prose. Only a
        value whose sole alphabetic token is the code may match.
        """
        result = CurrencyNormalizer().normalize("cup of tea", _ctx(FieldSemanticType.CURRENCY))
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS

    def test_bare_amount_is_not_read_as_a_numeric_code(self) -> None:
        result = CurrencyNormalizer().normalize("123", _ctx(FieldSemanticType.CURRENCY))
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS

    def test_unreal_three_letter_token_still_ambiguous(self) -> None:
        result = CurrencyNormalizer().normalize("XYZ", _ctx(FieldSemanticType.CURRENCY))
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
