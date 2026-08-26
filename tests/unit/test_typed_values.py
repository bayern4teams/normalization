"""Unit tests for M19's typed NUMERIC/DATE destination-column extraction
contract (`normsink.typed_values`) — real `NumericNormalizer`/
`DateNormalizer` output, not hand-built `NormalizedValue` fixtures, so
this test locks the actual contract between those normalizers and the
extraction functions, not an assumption about their shape.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from normalizers.date import DateNormalizer
from normalizers.numeric import NumericNormalizer
from normsink.typed_values import extract_date, extract_numeric

from normcore import ErrorPolicy, FieldSemanticType, NormalizationContext, NormalizationStatus

_CTX_NUMERIC = NormalizationContext(
    field_name="amount",
    semantic_type=FieldSemanticType.NUMERIC,
    error_policy=ErrorPolicy.RETURN_ORIGINAL,
)
_CTX_DATE = NormalizationContext(
    field_name="d", semantic_type=FieldSemanticType.DATE, error_policy=ErrorPolicy.RETURN_ORIGINAL
)


@pytest.mark.unit
class TestExtractNumeric:
    def test_a_real_clean_number_extracts_as_a_decimal(self) -> None:
        result = NumericNormalizer().normalize("1,234.50", _CTX_NUMERIC)
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert extract_numeric(result) == Decimal("1234.50")

    def test_a_real_unparseable_value_extracts_as_none(self) -> None:
        result = NumericNormalizer().normalize("not a number at all", _CTX_NUMERIC)
        assert result.normalization_status is NormalizationStatus.INVALID
        assert extract_numeric(result) is None

    def test_missing_value_extracts_as_none(self) -> None:
        result = NumericNormalizer().normalize(None, _CTX_NUMERIC)
        assert extract_numeric(result) is None


@pytest.mark.unit
class TestExtractDate:
    def test_a_real_iso_date_extracts_as_a_date(self) -> None:
        result = DateNormalizer().normalize("2024-03-04", _CTX_DATE)
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert extract_date(result) == date(2024, 3, 4)

    def test_a_real_unparseable_value_extracts_as_none(self) -> None:
        result = DateNormalizer().normalize("definitely not a date", _CTX_DATE)
        assert result.normalization_status is NormalizationStatus.INVALID
        assert extract_date(result) is None

    def test_missing_value_extracts_as_none(self) -> None:
        result = DateNormalizer().normalize(None, _CTX_DATE)
        assert extract_date(result) is None
