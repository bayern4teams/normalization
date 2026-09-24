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
