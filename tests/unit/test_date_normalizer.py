"""Unit tests for DateNormalizer — Source.txt §43-§45."""

from __future__ import annotations

import pyarrow as pa
import pytest
from normalizers.date import DateNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus, QualityFlag


@pytest.fixture
def normalizer() -> DateNormalizer:
    return DateNormalizer()


def _ctx(*, country: str | None = None, locale: str | None = None) -> NormalizationContext:
    return NormalizationContext(
        field_name="date", semantic_type=FieldSemanticType.DATE, country=country, locale=locale
    )


@pytest.mark.unit
class TestProtocolShape:
    def test_supported_types(self, normalizer: DateNormalizer) -> None:
        assert normalizer.supported_types == frozenset(
            {FieldSemanticType.DATE, FieldSemanticType.DATETIME}
        )

    def test_version(self, normalizer: DateNormalizer) -> None:
        assert normalizer.version().name == "DateNormalizer"


@pytest.mark.unit
class TestMissingValues:
    def test_none(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize(None, _ctx())
        assert result.original_kind is MissingKind.NULL

    def test_empty(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("", _ctx())
        assert result.original_kind is MissingKind.EMPTY_STRING


@pytest.mark.unit
class TestIsoFastPath:
    def test_already_iso_date(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("2026-08-18", _ctx())
        assert result.display == "2026-08-18"
        assert result.structured["source_format"] == "ISO8601"
        assert result.confidence == 1.0

    def test_iso_date_original_preserved(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("2026-08-18", _ctx())
        assert result.original == "2026-08-18"


@pytest.mark.unit
class TestAmbiguousDates:
    def test_ambiguous_slash_date_without_context(self, normalizer: DateNormalizer) -> None:
        """Source.txt §43's own worked example: "03/04/2024" must not
        silently resolve without locale context."""
        result = normalizer.normalize("03/04/2024", _ctx())
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.confidence == 0.5
        assert QualityFlag.AMBIGUOUS_DATE in result.flags
        candidates = result.structured["candidates"]
        assert len(candidates) == 2
        interpretations = {c["interpretation"] for c in candidates}
        assert interpretations == {"DMY", "MDY"}

    def test_ambiguous_date_original_preserved(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("03/04/2024", _ctx())
        assert result.original == "03/04/2024"
        assert result.display == "03/04/2024"

    def test_unambiguous_day_over_12_resolves_without_context(
        self, normalizer: DateNormalizer
    ) -> None:
        """25 cannot be a month, so this is NOT actually ambiguous even
        with zero context."""
        result = normalizer.normalize("25/12/2024", _ctx())
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.display == "2024-12-25"

    def test_named_month_is_unambiguous(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("March 4, 2024", _ctx())
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.display == "2024-03-04"


@pytest.mark.unit
class TestContextResolvesAmbiguity:
    def test_us_country_context_resolves_as_mdy(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("03/04/2024", _ctx(country="US"))
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.display == "2024-03-04"  # March 4th

    def test_gb_country_context_resolves_as_dmy(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("03/04/2024", _ctx(country="GB"))
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.display == "2024-04-03"  # 3rd April

    def test_context_resolved_dates_have_lower_confidence_than_unambiguous(
        self, normalizer: DateNormalizer
    ) -> None:
        context_resolved = normalizer.normalize("03/04/2024", _ctx(country="US"))
        unambiguous = normalizer.normalize("25/12/2024", _ctx())
        assert context_resolved.confidence < unambiguous.confidence


@pytest.mark.unit
class TestInvalidDates:
    def test_garbage_text_is_invalid(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("not a date", _ctx())
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.errors != []

    def test_validate_ambiguous_is_invalid(self, normalizer: DateNormalizer) -> None:
        outcome = normalizer.validate("03/04/2024", _ctx())
        assert outcome.is_valid is False
        assert outcome.status == "AMBIGUOUS"


@pytest.mark.unit
class TestBatch:
    def test_normalize_batch_matches_scalar(self, normalizer: DateNormalizer) -> None:
        ctx = _ctx(country="US")
        values = ["2026-08-18", "03/04/2024"]
        batch = normalizer.normalize_batch(pa.array(values, type=pa.large_string()), ctx)
        displays = batch.field("display").to_pylist()
        assert displays == [normalizer.normalize(v, ctx).display for v in values]
