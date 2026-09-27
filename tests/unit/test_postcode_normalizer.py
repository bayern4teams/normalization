"""Unit tests for PostcodeNormalizer — Source.txt §32.

Closes a real gap found during the M7-follow-up self-audit:
`FieldSemanticType.POSTCODE` existed since M1 but had no registered
normalizer, silently falling through to `PassthroughNormalizer`.
"""

from __future__ import annotations

import pytest
from normalizers.postcode import PostcodeNormalizer
from normalizers.postcode_validation import (
    country_from_postcode_format,
    validate_postcode_format,
)
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


@pytest.mark.unit
class TestCountryFromPostcodeFormat:
    """The inverse of format validation, and far stricter: it answers only
    when exactly one country accepts the value, because a unique match is a
    determination while a most-likely match is a guess.

    Measured on 20,000 distinct real postcodes: 18.9% match exactly one
    country, 0.8% match none, 65.8% match 56 or 57.
    """

    @pytest.mark.parametrize(
        ("postcode", "expected"),
        [
            ("SW1A 1AA", "GB"),
            ("BT28 1AU", "GB"),
            ("dy9 8hs", "GB"),  # lowercase: the rules are uppercase-only
            ("L3V 6J3", "CA"),
            ("00-844", "PL"),
        ],
    )
    def test_a_format_only_one_country_uses_identifies_it(
        self, postcode: str, expected: str
    ) -> None:
        assert country_from_postcode_format(postcode) == expected

    @pytest.mark.parametrize("postcode", ["94043", "10115", "75001", "1234", ""])
    def test_an_ambiguous_or_empty_format_identifies_nothing(self, postcode: str) -> None:
        assert country_from_postcode_format(postcode) is None

    def test_a_value_no_country_accepts_identifies_nothing(self) -> None:
        assert country_from_postcode_format("not-a-postcode-at-all") is None

    def test_it_agrees_with_the_validator_it_is_the_inverse_of(self) -> None:
        """Whatever this names must pass that country's own validation —
        they read the same google-i18n-address rules, and a disagreement
        would mean one of them is reading them wrong."""
        for postcode in ("SW1A 1AA", "L3V 6J3", "00-844"):
            country = country_from_postcode_format(postcode)
            assert country is not None
            assert validate_postcode_format(postcode, country) is True
