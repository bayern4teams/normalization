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
        """ "1.5e3" has a 3-character trailing run, but it is not 3 DIGITS,
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
        """ "cup" IS a real ISO 4217 code (Cuban peso), so case-insensitive
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


@pytest.mark.unit
class TestCurrencyCldrNamesAndSymbols:
    """CLDR replaced 8 hand-written names and 3 symbols with 22.8k names
    and 197 symbols (`_cldr_currency_names`). §47's ambiguity rule has to
    survive that intact — and mostly does so for free, because a name or
    symbol meaning different currencies in different locales is dropped at
    generation time."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("US-Dollar", "USD"),  # de
            ("Dollar des États-Unis", "USD"),  # fr
            ("Yen japonais", "JPY"),
            ("Dólar estadounidense", "USD"),  # es
            ("Japanischer Yen", "JPY"),
            ("人民币", "CNY"),
            ("Индийская рупия", "INR"),
        ],
    )
    def test_localized_currency_names(
        self, currency_normalizer: CurrencyNormalizer, value: str, expected: str
    ) -> None:
        result = currency_normalizer.normalize(value, _ctx(FieldSemanticType.CURRENCY))
        assert result.structured["canonical_currency"] == expected
        assert result.normalization_status is NormalizationStatus.NORMALIZED

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("₹", "INR"), ("₽", "RUB"), ("₩", "KRW"), ("₪", "ILS"), ("฿", "THB"), ("₫", "VND")],
    )
    def test_letter_free_symbols_resolve_anywhere_in_the_value(
        self, currency_normalizer: CurrencyNormalizer, value: str, expected: str
    ) -> None:
        for candidate in (value, f"{value}1,234.00", f"1 234 {value}"):
            result = currency_normalizer.normalize(candidate, _ctx(FieldSemanticType.CURRENCY))
            assert result.structured["canonical_currency"] == expected, candidate

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("A$", "AUD"), ("R$", "BRL"), ("CA$", "CAD"), ("$US", "USD"), ("zł", "PLN")],
    )
    def test_letter_bearing_symbols_resolve_as_the_whole_value(
        self, currency_normalizer: CurrencyNormalizer, value: str, expected: str
    ) -> None:
        result = currency_normalizer.normalize(value, _ctx(FieldSemanticType.CURRENCY))
        assert result.structured["canonical_currency"] == expected

    @pytest.mark.parametrize(
        "value",
        [
            "$",  # USD in en_US, CAD in en_CA — collapsed to None at generation
            "$100",
            "kr",  # four Nordic currencies
            "¤",  # U+00A4, CLDR's generic placeholder — belongs to XXX
            "unknown currency",  # every CLDR name for XXX, "no currency"
            "test currency",  # XTS
            "or",  # French for gold, i.e. CLDR's name for XAU
            "cup of tea",  # CUP is Cuba's real ISO 4217 code
        ],
    )
    def test_ambiguous_and_non_currency_values_never_resolve(
        self, currency_normalizer: CurrencyNormalizer, value: str
    ) -> None:
        """Two classes of value that a bigger table makes easier to get
        wrong: symbols that genuinely mean more than one currency, and the
        two ISO 4217 entries that are definitionally not a currency at all
        (XXX "no currency", XTS "testing"). Resolving a value to either
        would report a successful normalization for exactly the input that
        has none."""
        result = currency_normalizer.normalize(value, _ctx(FieldSemanticType.CURRENCY))
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.structured["canonical_currency"] is None

    def test_metals_and_special_drawing_rights_do_resolve(
        self, currency_normalizer: CurrencyNormalizer
    ) -> None:
        """XAU/XAG/XDR are real ISO 4217 code-list entries for real
        financial instruments, not placeholders like XXX and XTS, so their
        CLDR names resolve. Typing the CODE already did before CLDR was
        added; excluding only the names would be inconsistent."""
        for value, expected in (("Gold", "XAU"), ("Silver", "XAG"), ("XAU", "XAU")):
            result = currency_normalizer.normalize(value, _ctx(FieldSemanticType.CURRENCY))
            assert result.structured["canonical_currency"] == expected, value

    def test_hand_curated_symbols_still_win_over_cldr(
        self, currency_normalizer: CurrencyNormalizer
    ) -> None:
        """CLDR drops "¥" (JPY in ja, CNY in zh) and has no unambiguous
        entry for "£", but in real data both overwhelmingly mean JPY and
        GBP — so the three hand-curated symbols are consulted first."""
        for value, expected in (("¥", "JPY"), ("£", "GBP"), ("€", "EUR")):
            result = currency_normalizer.normalize(value, _ctx(FieldSemanticType.CURRENCY))
            assert result.structured["canonical_currency"] == expected

    def test_plural_names_still_resolve(self, currency_normalizer: CurrencyNormalizer) -> None:
        """CLDR ships singular display names only, so the plurals real
        data contains stay hand-listed. Deleting them would regress."""
        for value, expected in (
            ("US Dollars", "USD"),
            ("euros", "EUR"),
            ("united states dollar", "USD"),
            ("pound sterling", "GBP"),
        ):
            result = currency_normalizer.normalize(value, _ctx(FieldSemanticType.CURRENCY))
            assert result.structured["canonical_currency"] == expected, value


@pytest.mark.unit
class TestADollarSignInsideProseIsNotACurrency:
    """`"$" in cleaned` made any string CONTAINING a dollar sign resolve to
    the context country's dollar. Measured on a real source, a column of
    revenue RANGE strings came back VALID USD at 0.8 confidence under
    `country=US` — a guess about arbitrary prose, which §47 forbids.
    """

    @pytest.mark.parametrize(
        "value", ["$5 mil. - $10 mil.", "Under $500,000", "$500,000 - $1 mil.", "costs $5"]
    )
    def test_prose_containing_a_dollar_sign_stays_unresolved(self, value: str) -> None:
        normalizer = CurrencyNormalizer()
        ctx = NormalizationContext(
            field_name="c", semantic_type=FieldSemanticType.CURRENCY, country="US"
        )
        result = normalizer.normalize(value, ctx)
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.comparison is None

    def test_a_bare_dollar_sign_still_resolves_from_the_country(self) -> None:
        """The behaviour the substring check existed for is unchanged."""
        normalizer = CurrencyNormalizer()
        for country, expected in (("US", "USD"), ("CA", "CAD"), ("AU", "AUD")):
            ctx = NormalizationContext(
                field_name="c", semantic_type=FieldSemanticType.CURRENCY, country=country
            )
            assert normalizer.normalize("$", ctx).comparison == expected
            # Surrounding whitespace is not a different value.
            assert normalizer.normalize(" $ ", ctx).comparison == expected

    def test_a_wrapped_currency_code_resolves(self) -> None:
        """Same edge-stripping COUNTRY got: `, USD` is USD."""
        normalizer = CurrencyNormalizer()
        ctx = NormalizationContext(field_name="c", semantic_type=FieldSemanticType.CURRENCY)
        assert normalizer.normalize(", USD", ctx).comparison == "USD"
