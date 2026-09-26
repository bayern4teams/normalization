"""Native destination column types, the pre-insert cast that makes them
safe, and the MONEY semantic type.

Every semantic type mapped to TEXT because decision #8 puts a failed
value's raw string in the cell and a typed column rejects it — taking the
whole chunk down, error report included. These cover the cast that lifts
that restriction.
"""

from __future__ import annotations

import decimal

import pytest
from normalizers.money import MoneyNormalizer
from normapi.clone_executor import _destination_plan
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from normio.connectors.clickhouse_destination import SEMANTIC_TYPE_TO_CH_TYPE
from normio.connectors.postgres_destination import SEMANTIC_TYPE_TO_PG_TYPE

from normio import storage_types


def _ctx() -> NormalizationContext:
    return NormalizationContext(field_name="amount", semantic_type=FieldSemanticType.MONEY)


@pytest.mark.unit
class TestStorageTypes:
    @pytest.mark.parametrize("semantic_type", ["NUMERIC", "MONEY", "BOOLEAN"])
    def test_typed_types_have_a_native_type_per_engine(self, semantic_type: str) -> None:
        assert storage_types.sql_type(semantic_type, "postgres")
        assert storage_types.sql_type(semantic_type, "clickhouse")

    @pytest.mark.parametrize("semantic_type", ["DATE", "DATETIME", "FREE_TEXT", "COUNTRY", "UUID"])
    def test_everything_else_stays_text(self, semantic_type: str) -> None:
        """DATE especially: dates normalize to partial values ("1990")
        when that is all the source knew, and no SQL DATE column holds
        those — typing them would NULL every year-only date."""
        assert storage_types.sql_type(semantic_type, "postgres") is None
        assert storage_types.sql_type(semantic_type, "clickhouse") is None

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("1234.56", decimal.Decimal("1234.56")), ("-50", decimal.Decimal("-50")), ("0", 0)],
    )
    def test_numeric_casts(self, value: str, expected: object) -> None:
        cast, error = storage_types.coerce("NUMERIC", value)
        assert error is None
        assert cast == expected

    def test_decimal_not_float(self) -> None:
        """Money in binary float drifts; 0.1 is not representable."""
        cast, _ = storage_types.coerce("MONEY", "0.1")
        assert isinstance(cast, decimal.Decimal)

    @pytest.mark.parametrize("value", ["not a number", "d1989-12-11", "1,234", "12/05/1990"])
    def test_uncastable_becomes_null_and_an_error(self, value: str) -> None:
        """This is the whole point: decision #8's raw-string fallback is
        reported, not handed to the database to reject."""
        cast, error = storage_types.coerce("NUMERIC", value)
        assert cast is None
        assert error is not None

    @pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_numbers_are_rejected(self, value: str) -> None:
        """Valid Decimals and valid Postgres NUMERIC, but they poison the
        SUM/AVG this column is typed for."""
        cast, error = storage_types.coerce("NUMERIC", value)
        assert cast is None
        assert error is not None

    @pytest.mark.parametrize(("value", "expected"), [("true", True), ("false", False)])
    def test_boolean_casts(self, value: str, expected: bool) -> None:
        cast, error = storage_types.coerce("BOOLEAN", value)
        assert error is None
        assert cast is expected

    def test_boolean_rejects_anything_else(self) -> None:
        cast, error = storage_types.coerce("BOOLEAN", "maybe")
        assert cast is None
        assert error is not None

    def test_null_stays_null_without_an_error(self) -> None:
        assert storage_types.coerce("NUMERIC", None) == (None, None)

    def test_untyped_semantic_type_passes_through(self) -> None:
        assert storage_types.coerce("FREE_TEXT", "hello") == ("hello", None)


@pytest.mark.unit
class TestMoneyNormalizer:
    @pytest.mark.parametrize(
        ("value", "amount", "currency"),
        [
            ("$1,234.56", "1234.56", None),  # bare "$" is ambiguous by design
            ("USD 1234.56", "1234.56", "USD"),
            ("1234.56 USD", "1234.56", "USD"),
            ("1234.56 usd", "1234.56", "USD"),
            ("1.234,56 EUR", "1234.56", "EUR"),
            ("€99.99", "99.99", "EUR"),
            ("¥1000", "1000", "JPY"),
            ("(1,234.56) USD", "-1234.56", "USD"),
            ("-50 GBP", "-50", "GBP"),
            ("1234", "1234", None),
        ],
    )
    def test_amount_and_currency_are_both_kept(
        self, value: str, amount: str, currency: str | None
    ) -> None:
        """NUMERIC parses the amount and throws the currency away. You
        cannot sum a column whose currency you discarded."""
        result = MoneyNormalizer().normalize(value, _ctx())
        assert result.display == amount
        assert result.structured["currency"] == currency

    def test_display_is_bare_so_the_column_can_be_summed(self) -> None:
        result = MoneyNormalizer().normalize("1234.56 USD", _ctx())
        cast, error = storage_types.coerce("MONEY", result.display)
        assert error is None
        assert cast == decimal.Decimal("1234.56")

    def test_trailing_code_is_the_common_spelling(self) -> None:
        """NumericNormalizer strips only a LEADING symbol, so delegating
        the whole string made "1234.56 USD" INVALID."""
        assert (
            MoneyNormalizer().normalize("1234.56 USD", _ctx()).normalization_status
            is NormalizationStatus.NORMALIZED
        )

    @pytest.mark.parametrize(("value", "units"), [("100 JPY", 0), ("100 KWD", 3), ("100 USD", 2)])
    def test_iso_minor_units_are_recorded(self, value: str, units: int) -> None:
        """Most currencies have 2 decimals; JPY has 0 and KWD has 3."""
        assert MoneyNormalizer().normalize(value, _ctx()).structured["minor_units"] == units

    @pytest.mark.parametrize("value", ["free", "$", "USD", "no charge"])
    def test_a_value_with_no_amount_is_invalid(self, value: str) -> None:
        result = MoneyNormalizer().normalize(value, _ctx())
        assert result.normalization_status is NormalizationStatus.INVALID

    def test_ambiguous_amount_stays_ambiguous(self) -> None:
        """ "1,234" is undecidable without a locale — it must not be
        downgraded to a flat failure, nor guessed."""
        result = MoneyNormalizer().normalize("1,234", _ctx())
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS


@pytest.mark.unit
class TestTypeMapsStillCoverEverySemanticType:
    @pytest.mark.parametrize("semantic_type", list(FieldSemanticType))
    def test_money_did_not_break_the_exhaustive_maps(
        self, semantic_type: FieldSemanticType
    ) -> None:
        assert semantic_type.value in SEMANTIC_TYPE_TO_PG_TYPE
        assert semantic_type.value in SEMANTIC_TYPE_TO_CH_TYPE


@pytest.mark.unit
class TestDestinationPlan:
    def test_typed_off_by_default_changes_nothing(self) -> None:
        overrides, _, typed = _destination_plan({"amount": "NUMERIC"}, "postgres", (), typed=False)
        assert overrides == {}
        assert typed == {}

    def test_typed_on_gives_numeric_a_native_type(self) -> None:
        overrides, _, typed = _destination_plan({"amount": "NUMERIC"}, "postgres", (), typed=True)
        assert overrides == {"amount": "NUMERIC"}
        assert typed == {"amount": "NUMERIC"}

    def test_key_columns_are_never_typed(self) -> None:
        """ClickHouse refuses a nullable sorting key, so a value that
        failed to cast would have nowhere to go."""
        overrides, _, typed = _destination_plan(
            {"id": "NUMERIC"}, "clickhouse", ("id",), typed=True
        )
        assert overrides == {}
        assert typed == {}

    def test_money_always_gets_a_currency_companion(self) -> None:
        """Even untyped: display is the bare amount either way, so
        without the companion the currency is simply lost."""
        _, extras, _ = _destination_plan({"price": "MONEY"}, "postgres", (), typed=False)
        assert extras == {"price_currency": "TEXT"}

    def test_companion_column_type_follows_the_engine(self) -> None:
        _, extras, _ = _destination_plan({"price": "MONEY"}, "clickhouse", (), typed=False)
        assert extras == {"price_currency": "String"}

    def test_untyped_semantic_types_get_no_override(self) -> None:
        overrides, _, _ = _destination_plan(
            {"born": "DATE", "name": "PERSON_NAME"}, "postgres", (), typed=True
        )
        assert overrides == {}


@pytest.mark.unit
class TestMoneyMagnitudeWords:
    """Regression for a silent 1,000,000x error.

    The original split treated every non-numeric token as the currency half
    and dropped whatever did not resolve, so "$10.5 Million" normalized to
    10.5 and reported NORMALIZED with full confidence. Found against a real
    1.27M-row revenue column where EVERY value has that shape, which means
    every revenue figure in it would have been wrong by a factor of a
    million with nothing to indicate it.
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("$10.5 Million", "10500000"),
            ("$17.6 Million", "17600000"),
            ("$1 Billion", "1000000000"),
            ("$500 Thousand", "500000"),
            ("$3.4 trillion", "3400000000000"),
            ("1.2bn", "1200000000"),
            ("2 hundred", "200"),
        ],
    )
    def test_magnitude_words_multiply_the_amount(self, value: str, expected: str) -> None:
        result = MoneyNormalizer().normalize(value, _ctx())
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.structured["canonical_amount"] == expected
        # Exact integers, not floats: 10.5 * 10**6 in binary floating point
        # is 10499999.999999998, which would not equal the string above.
        assert "." not in result.structured["canonical_amount"]

    def test_magnitude_and_currency_together(self) -> None:
        for value in ("USD 2 million", "2 Million USD"):
            result = MoneyNormalizer().normalize(value, _ctx())
            assert result.structured["canonical_amount"] == "2000000", value
            assert result.structured["currency"] == "USD", value

    @pytest.mark.parametrize(
        "value",
        [
            "$10.5 Milliarde",  # German 10^9 — long-scale locales are not guessed
            "$10.5 Billiarde",
            "5 lakh",  # Indian 10^5
            "100 per share",
            "$50 each",
        ],
    )
    def test_unrecognised_words_are_ambiguous_never_dropped(self, value: str) -> None:
        """An unexplained word means the value was not understood. Refusing
        is the only safe answer: a wrong number is far worse than none."""
        result = MoneyNormalizer().normalize(value, _ctx())
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.structured["canonical_amount"] is None

    @pytest.mark.parametrize("value", ["10.5M", "3B", "20k", "7T"])
    def test_single_letter_suffixes_are_ambiguous(self, value: str) -> None:
        """ "M" is the CLDR currency symbol for the Lesotho loti, so "10.5M"
        used to resolve to 10.5 LSL — wrong in both halves at once. A single
        letter beside a number cannot be told from a currency symbol
        without knowing the column."""
        result = MoneyNormalizer().normalize(value, _ctx())
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS

    def test_ambiguous_symbol_still_keeps_its_amount(self) -> None:
        """The guard must not catch a bare "$": a symbol we cannot pin to
        one currency is a known unknown and the amount is still good. Only
        an unrecognised WORD is refused."""
        result = MoneyNormalizer().normalize("$1234.56", _ctx())
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.structured["canonical_amount"] == "1234.56"
        assert result.structured["currency"] is None

    def test_values_without_a_magnitude_are_byte_identical(self) -> None:
        """The multiplier path reformats through Decimal, so the no-magnitude
        path must not go through it — "1234.5600" must not become "1234.56"
        (or vice versa) as a side effect of this fix."""
        for value, expected in (("1234.56 USD", "1234.56"), ("€1.234,56", "1234.56")):
            result = MoneyNormalizer().normalize(value, _ctx())
            assert result.structured["canonical_amount"] == expected, value
