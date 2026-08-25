"""Unit tests for NumericNormalizer, CurrencyNormalizer, UnitNormalizer,
BooleanNormalizer — Source.txt Phase 12 (§46-§48, §52)."""

from __future__ import annotations

import pytest
from normalizers.boolean import BooleanNormalizer
from normalizers.currency import CurrencyNormalizer
from normalizers.numeric import NumericNormalizer
from normalizers.unit import UnitNormalizer
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)


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


@pytest.mark.unit
class TestNumericNormalizerExactFields:
    """A real mutmut run (M12) found 30 surviving mutants in
    `NumericNormalizer.normalize` — the field-by-field checks above
    only ever assert `display`/`normalization_status`, never pin down
    exact `confidence`/`structured`/`lossiness`/defaults."""

    def test_missing_none_every_field(self, numeric_normalizer: NumericNormalizer) -> None:
        result = numeric_normalizer.normalize(None, _ctx(FieldSemanticType.NUMERIC))
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0
        assert result.display is None
        assert result.structured == {}
        assert result.errors == []
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.trace == []
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_missing_empty_every_field(self, numeric_normalizer: NumericNormalizer) -> None:
        result = numeric_normalizer.normalize("", _ctx(FieldSemanticType.NUMERIC))
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_ambiguous_every_field(self, numeric_normalizer: NumericNormalizer) -> None:
        result = numeric_normalizer.normalize("1,234", _ctx(FieldSemanticType.NUMERIC))
        assert result.original == "1,234"
        assert result.display == "1,234"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {"assumption": None}
        assert result.validation_status == "AMBIGUOUS"
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.confidence == 0.5
        assert result.errors == []
        assert QualityFlag.AMBIGUOUS_LOCALE in result.flags
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.trace[0].library == "Babel"

    def test_invalid_every_field(self, numeric_normalizer: NumericNormalizer) -> None:
        result = numeric_normalizer.normalize(
            "not a number at all!!", _ctx(FieldSemanticType.NUMERIC)
        )
        assert result.original == "not a number at all!!"
        assert result.display == "not a number at all!!"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "INVALID"
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.confidence == 0.0
        assert result.errors == ["could not parse as a number"]
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is False

    def test_valid_no_locale_every_field(self, numeric_normalizer: NumericNormalizer) -> None:
        """No locale/country context -> confidence is 0.9, not 1.0."""
        result = numeric_normalizer.normalize("42.5", _ctx(FieldSemanticType.NUMERIC))
        assert result.original == "42.5"
        assert result.display == "42.5"
        assert result.comparison == "42.5"
        assert result.search == "42.5"
        assert result.structured == {
            "canonical_value": "42.5",
            "original_locale": None,
            "leading_symbol": None,
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 0.9
        assert result.errors == []
        assert result.lossiness is Reversibility.LOSSY
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.trace[0].library == "Babel"

    def test_valid_with_country_confidence_is_full(
        self, numeric_normalizer: NumericNormalizer
    ) -> None:
        """A resolved locale/country context -> confidence is 1.0,
        `structured["original_locale"]` is populated."""
        result = numeric_normalizer.normalize(
            "1,234.56", _ctx(FieldSemanticType.NUMERIC, country="US")
        )
        assert result.confidence == 1.0
        assert result.structured == {
            "canonical_value": "1234.56",
            "original_locale": "en_US",
            "leading_symbol": None,
        }
        assert result.normalization_status is NormalizationStatus.NORMALIZED


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

    def test_missing_none_every_field(self, currency_normalizer: CurrencyNormalizer) -> None:
        result = currency_normalizer.normalize(None, _ctx(FieldSemanticType.CURRENCY))
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0
        assert result.display is None
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_missing_empty_every_field(self, currency_normalizer: CurrencyNormalizer) -> None:
        result = currency_normalizer.normalize("", _ctx(FieldSemanticType.CURRENCY))
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_iso_code_every_field(self, currency_normalizer: CurrencyNormalizer) -> None:
        """A real mutmut run (M12) found 33 surviving mutants in
        `CurrencyNormalizer.normalize` — mostly literal constants
        (confidence values, `""` defaults, `lossiness`) never pinned
        down exactly by the checks above."""
        result = currency_normalizer.normalize("USD", _ctx(FieldSemanticType.CURRENCY))
        assert result.original == "USD"
        assert result.display == "USD"
        assert result.comparison == "USD"
        assert result.search == "USD"
        assert result.structured == {
            "original_currency": "USD",
            "canonical_currency": "USD",
            "currency_confidence": 1.0,
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.lossiness is Reversibility.PARTIALLY_REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is True
        assert result.trace[0].library == "normalizers"

    def test_unambiguous_symbol_confidence_is_0_95(
        self, currency_normalizer: CurrencyNormalizer
    ) -> None:
        result = currency_normalizer.normalize("€", _ctx(FieldSemanticType.CURRENCY))
        assert result.display == "EUR"
        assert result.structured["currency_confidence"] == 0.95
        assert result.confidence == 0.95

    def test_dollar_with_country_context_confidence_is_0_8(
        self, currency_normalizer: CurrencyNormalizer
    ) -> None:
        result = currency_normalizer.normalize("$", _ctx(FieldSemanticType.CURRENCY, country="US"))
        assert result.structured == {
            "original_currency": "$",
            "canonical_currency": "USD",
            "currency_confidence": 0.8,
        }
        assert result.confidence == 0.8
        assert result.lossiness is Reversibility.PARTIALLY_REVERSIBLE
        assert result.trace[0].changed is True

    def test_ambiguous_dollar_no_context_every_field(
        self, currency_normalizer: CurrencyNormalizer
    ) -> None:
        result = currency_normalizer.normalize("$", _ctx(FieldSemanticType.CURRENCY))
        assert result.original == "$"
        assert result.display == "$"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {"original_currency": "$", "canonical_currency": None}
        assert result.validation_status == "AMBIGUOUS"
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.confidence == 0.0
        assert result.errors == []
        assert result.lossiness is Reversibility.LOSSLESS
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_unresolvable_text_every_field(self, currency_normalizer: CurrencyNormalizer) -> None:
        result = currency_normalizer.normalize("not a currency", _ctx(FieldSemanticType.CURRENCY))
        assert result.structured == {
            "original_currency": "not a currency",
            "canonical_currency": None,
        }
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.confidence == 0.0
        assert result.lossiness is Reversibility.LOSSLESS


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

    def test_missing_none_every_field(self, unit_normalizer: UnitNormalizer) -> None:
        result = unit_normalizer.normalize(None, _ctx(FieldSemanticType.QUANTITY))
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0
        assert result.display is None
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_missing_empty_every_field(self, unit_normalizer: UnitNormalizer) -> None:
        result = unit_normalizer.normalize("", _ctx(FieldSemanticType.QUANTITY))
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_valid_conversion_every_field(self, unit_normalizer: UnitNormalizer) -> None:
        """A real mutmut run (M12) found 41 surviving mutants in
        `UnitNormalizer.normalize` — mostly literal constants
        (confidence, `""` defaults, `lossiness`) never pinned down
        exactly by the field-by-field checks above."""
        result = unit_normalizer.normalize("5 km", _ctx(FieldSemanticType.QUANTITY))
        assert result.original == "5 km"
        assert result.display == "5000.0 meter"
        assert result.comparison == "5000.0 meter"
        assert result.search == "5000.0 meter"
        assert result.structured == {
            "original_value": "5",
            "original_unit": "kilometer",
            "canonical_value": "5000.0",
            "canonical_unit": "meter",
            "dimensionality": "[length]",
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.lossiness is Reversibility.REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is True
        assert result.trace[0].library == "Pint"

    def test_undefined_unit_error_every_field(self, unit_normalizer: UnitNormalizer) -> None:
        result = unit_normalizer.normalize("5 fakeunit", _ctx(FieldSemanticType.QUANTITY))
        assert result.original == "5 fakeunit"
        assert result.display == "5 fakeunit"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "INVALID"
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.confidence == 0.0
        assert result.errors == ["'fakeunit' is not defined in the unit registry"]
        assert result.lossiness is Reversibility.LOSSLESS
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_dimensionality_error_is_invalid(self, unit_normalizer: UnitNormalizer) -> None:
        """`Pint` raises `DimensionalityError` for mismatched-dimension
        arithmetic (e.g. adding a length to a mass) inside the parsed
        expression itself — a distinct exception type from
        `UndefinedUnitError`, both caught by the same except clause."""
        result = unit_normalizer.normalize("5 km + 3 kg", _ctx(FieldSemanticType.QUANTITY))
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.confidence == 0.0
        assert result.errors != []


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
class TestBooleanNormalizerExactFields:
    """A real mutmut run (M12) found 13 surviving mutants in
    `BooleanNormalizer.normalize` — the field-by-field checks above
    only ever assert `display`/`structured["canonical_value"]`, never
    pin down exact `confidence`/`lossiness`/defaults, and there was no
    missing-value coverage at all."""

    def test_missing_none_every_field(self, boolean_normalizer: BooleanNormalizer) -> None:
        result = boolean_normalizer.normalize(None, _ctx(FieldSemanticType.BOOLEAN))
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.display is None
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "MISSING"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert result.trace == []

    def test_missing_empty_every_field(self, boolean_normalizer: BooleanNormalizer) -> None:
        result = boolean_normalizer.normalize("", _ctx(FieldSemanticType.BOOLEAN))
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_unknown_value_every_field(self, boolean_normalizer: BooleanNormalizer) -> None:
        result = boolean_normalizer.normalize("maybe", _ctx(FieldSemanticType.BOOLEAN))
        assert result.original == "maybe"
        assert result.original_kind is MissingKind.UNKNOWN_VALUE
        assert result.display is None
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "MISSING"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert result.trace == []

    def test_resolved_true_every_field(self, boolean_normalizer: BooleanNormalizer) -> None:
        result = boolean_normalizer.normalize("true", _ctx(FieldSemanticType.BOOLEAN))
        assert result.original == "true"
        assert result.display == "true"
        assert result.comparison == "true"
        assert result.search == "true"
        assert result.structured == {"canonical_value": True}
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.lossiness is Reversibility.PARTIALLY_REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.trace[0].library == "normalizers"

    def test_resolved_true_from_synonym_trace_changed_is_true(
        self, boolean_normalizer: BooleanNormalizer
    ) -> None:
        """`changed` compares the casefolded input against the
        canonical `"true"`/`"false"` string, not just checks
        `original_kind` — a non-canonical synonym must report changed."""
        result = boolean_normalizer.normalize("Y", _ctx(FieldSemanticType.BOOLEAN))
        assert result.trace[0].changed is True

    def test_resolved_false_every_field(self, boolean_normalizer: BooleanNormalizer) -> None:
        result = boolean_normalizer.normalize("no", _ctx(FieldSemanticType.BOOLEAN))
        assert result.original == "no"
        assert result.display == "false"
        assert result.comparison == "false"
        assert result.search == "false"
        assert result.structured == {"canonical_value": False}
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.lossiness is Reversibility.PARTIALLY_REVERSIBLE
        assert len(result.trace) == 1
        assert result.trace[0].changed is True

    def test_invalid_every_field(self, boolean_normalizer: BooleanNormalizer) -> None:
        result = boolean_normalizer.normalize("banana", _ctx(FieldSemanticType.BOOLEAN))
        assert result.original == "banana"
        assert result.display == "banana"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "INVALID"
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.confidence == 0.0
        assert result.errors == ["not a recognized boolean value"]
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
