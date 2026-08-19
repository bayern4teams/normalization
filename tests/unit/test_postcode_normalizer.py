"""Unit tests for PostcodeNormalizer — Source.txt §32.

Closes a real gap found during the M7-follow-up self-audit:
`FieldSemanticType.POSTCODE` existed since M1 but had no registered
normalizer, silently falling through to `PassthroughNormalizer`.
"""

from __future__ import annotations

import pytest
from normalizers.postcode import PostcodeNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus


@pytest.fixture
def normalizer() -> PostcodeNormalizer:
    return PostcodeNormalizer()


def _ctx(country: str | None = None) -> NormalizationContext:
    return NormalizationContext(
        field_name="zip", semantic_type=FieldSemanticType.POSTCODE, country=country
    )


@pytest.mark.unit
class TestMissingValues:
    def test_none(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize(None, _ctx())
        assert result.original_kind is MissingKind.NULL

    def test_empty(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("", _ctx())
        assert result.original_kind is MissingKind.EMPTY_STRING


@pytest.mark.unit
class TestValidPostcodes:
    def test_uk_postcode_valid(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("SW1A 1AA", _ctx("GB"))
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.structured["format_valid"] is True

    def test_us_zip_valid(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("90210", _ctx("US"))
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.structured["format_valid"] is True

    def test_canadian_postcode_valid(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("K1A 0B1", _ctx("CA"))
        assert result.structured["format_valid"] is True

    def test_case_insensitive_comparison(self, normalizer: PostcodeNormalizer) -> None:
        lower = normalizer.normalize("sw1a 1aa", _ctx("GB"))
        upper = normalizer.normalize("SW1A 1AA", _ctx("GB"))
        assert lower.comparison == upper.comparison

    def test_whitespace_collapsed(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("SW1A   1AA", _ctx("GB"))
        assert result.display == "SW1A 1AA"


@pytest.mark.unit
class TestInvalidPostcodes:
    def test_us_zip_wrong_shape_is_invalid(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("ABCDE", _ctx("US"))
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.structured["format_valid"] is False
        assert result.errors


@pytest.mark.unit
class TestNoCountryContext:
    def test_no_country_context_stays_ambiguous_never_invalid(
        self, normalizer: PostcodeNormalizer
    ) -> None:
        """§32's own "locale-aware" requirement: refuse to validate
        format without knowing which country's rules apply, rather than
        guessing or defaulting to always-valid/always-invalid."""
        result = normalizer.normalize("12345", _ctx())
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.structured["format_valid"] is None

    def test_unresolvable_country_also_stays_ambiguous(
        self, normalizer: PostcodeNormalizer
    ) -> None:
        result = normalizer.normalize("12345", _ctx("Not A Real Country"))
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
