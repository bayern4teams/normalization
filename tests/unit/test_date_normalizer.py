"""Unit tests for DateNormalizer — Source.txt §43-§45."""

from __future__ import annotations

import pyarrow as pa
import pytest
from normalizers.date import DateNormalizer
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)


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
        assert context_resolved.confidence is not None
        assert unambiguous.confidence is not None
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
class TestDateNormalizerExactFields:
    """A real mutmut run (M12) found 17 surviving mutants in
    `DateNormalizer.normalize` — the field-by-field checks above only
    ever assert `display`/`normalization_status`/a few `structured`
    keys, never pin down exact `comparison`/`search`/`lossiness`/
    defaults across every branch."""

    def test_missing_none_every_field(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize(None, _ctx())
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

    def test_missing_empty_every_field(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("", _ctx())
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_iso_fast_path_every_field(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("2026-08-18", _ctx())
        assert result.original == "2026-08-18"
        assert result.display == "2026-08-18"
        assert result.comparison == "2026-08-18"
        assert result.search == "2026-08-18"
        assert result.structured == {
            "parsed_date": "2026-08-18",
            "source_format": "ISO8601",
            "assumption": "already ISO 8601, no locale inference needed",
            "confidence": 1.0,
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.lossiness is Reversibility.LOSSY
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is True
        assert result.trace[0].library == "dateparser/ciso8601"

    def test_ambiguous_every_field(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("03/04/2024", _ctx())
        assert result.original == "03/04/2024"
        assert result.display == "03/04/2024"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {
            "candidates": [
                {"interpretation": "DMY", "day": "03", "month": "04", "year": "2024"},
                {"interpretation": "MDY", "day": "04", "month": "03", "year": "2024"},
            ],
            "assumption": None,
        }
        assert result.validation_status == "AMBIGUOUS"
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.confidence == 0.5
        assert result.errors == []
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.trace[0].library == "dateparser/ciso8601"

    def test_context_resolved_every_field(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("03/04/2024", _ctx(country="US"))
        assert result.original == "03/04/2024"
        assert result.display == "2024-03-04"
        assert result.comparison == "2024-03-04"
        assert result.search == "2024-03-04"
        assert result.structured == {
            "parsed_date": "2024-03-04",
            "source_locale": None,
            "assumption": "resolved using inferred day/month order MDY",
            "confidence": 0.85,
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.confidence == 0.85
        assert result.lossiness is Reversibility.LOSSY
        assert len(result.trace) == 1
        assert result.trace[0].changed is True

    def test_unambiguous_no_context_confidence_is_095(self, normalizer: DateNormalizer) -> None:
        """No context needed AND no ambiguity -> confidence is exactly
        0.95, distinct from both the 1.0 ISO-fast-path and the 0.85
        context-resolved tiers."""
        result = normalizer.normalize("25/12/2024", _ctx())
        assert result.display == "2024-12-25"
        assert result.structured == {
            "parsed_date": "2024-12-25",
            "source_locale": None,
            "assumption": "unambiguous format, no order assumption needed",
            "confidence": 0.95,
        }
        assert result.confidence == 0.95
        assert result.normalization_status is NormalizationStatus.PARSED

    def test_invalid_every_field(self, normalizer: DateNormalizer) -> None:
        result = normalizer.normalize("not a date", _ctx())
        assert result.original == "not a date"
        assert result.display == "not a date"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "INVALID"
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.confidence == 0.0
        assert result.errors == ["could not parse as a date"]
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is False


@pytest.mark.unit
class TestBatch:
    def test_normalize_batch_matches_scalar(self, normalizer: DateNormalizer) -> None:
        ctx = _ctx(country="US")
        values = ["2026-08-18", "03/04/2024"]
        batch = normalizer.normalize_batch(pa.array(values, type=pa.large_string()), ctx)
        displays = batch.field("display").to_pylist()
        assert displays == [normalizer.normalize(v, ctx).display for v in values]
