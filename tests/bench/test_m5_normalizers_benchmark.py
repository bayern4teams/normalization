"""Performance baseline for the M5 normalizers (identifier, UUID,
numeric, currency, unit, boolean) — Source.txt §102, §122; Gate G5
requirement.
"""

from __future__ import annotations

import pytest
from normalizers.boolean import BooleanNormalizer
from normalizers.currency import CurrencyNormalizer
from normalizers.identifier import IdentifierNormalizer, UuidNormalizer
from normalizers.numeric import NumericNormalizer
from normalizers.unit import UnitNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType


@pytest.fixture(scope="module")
def identifier_normalizer() -> IdentifierNormalizer:
    return IdentifierNormalizer()


@pytest.fixture(scope="module")
def uuid_normalizer() -> UuidNormalizer:
    return UuidNormalizer()


@pytest.fixture(scope="module")
def numeric_normalizer() -> NumericNormalizer:
    return NumericNormalizer()


@pytest.fixture(scope="module")
def currency_normalizer() -> CurrencyNormalizer:
    return CurrencyNormalizer()


@pytest.fixture(scope="module")
def unit_normalizer() -> UnitNormalizer:
    return UnitNormalizer()


@pytest.fixture(scope="module")
def boolean_normalizer() -> BooleanNormalizer:
    return BooleanNormalizer()


@pytest.mark.bench
def test_bench_identifier_normalize_single_value(
    benchmark: object, identifier_normalizer: IdentifierNormalizer
) -> None:
    ctx = NormalizationContext(field_name="id", semantic_type=FieldSemanticType.IDENTIFIER)
    benchmark(identifier_normalizer.normalize, "AB-000123", ctx)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_uuid_normalize_single_value(
    benchmark: object, uuid_normalizer: UuidNormalizer
) -> None:
    ctx = NormalizationContext(field_name="uuid", semantic_type=FieldSemanticType.UUID)
    benchmark(  # type: ignore[operator]
        uuid_normalizer.normalize, "550E8400-E29B-41D4-A716-446655440000", ctx
    )


@pytest.mark.bench
def test_bench_numeric_normalize_single_value(
    benchmark: object, numeric_normalizer: NumericNormalizer
) -> None:
    ctx = NormalizationContext(field_name="n", semantic_type=FieldSemanticType.NUMERIC)
    benchmark(numeric_normalizer.normalize, "1,234.56", ctx)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_currency_normalize_single_value(
    benchmark: object, currency_normalizer: CurrencyNormalizer
) -> None:
    ctx = NormalizationContext(field_name="c", semantic_type=FieldSemanticType.CURRENCY)
    benchmark(currency_normalizer.normalize, "USD", ctx)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_unit_normalize_single_value(
    benchmark: object, unit_normalizer: UnitNormalizer
) -> None:
    ctx = NormalizationContext(field_name="q", semantic_type=FieldSemanticType.QUANTITY)
    benchmark(unit_normalizer.normalize, "5 km", ctx)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_boolean_normalize_single_value(
    benchmark: object, boolean_normalizer: BooleanNormalizer
) -> None:
    ctx = NormalizationContext(field_name="b", semantic_type=FieldSemanticType.BOOLEAN)
    benchmark(boolean_normalizer.normalize, "yes", ctx)  # type: ignore[operator]
