"""Unit tests for PostcodeNormalizer — Source.txt §32.

Closes a real gap found during the M7-follow-up self-audit:
`FieldSemanticType.POSTCODE` existed since M1 but had no registered
normalizer, silently falling through to `PassthroughNormalizer`.

Assertions here check every field `normalize()` sets for each real code
path (not just one or two per case) — found via a real mutmut run
(M12) that this function alone had 65 surviving mutants, almost all of
them literal constants (confidence values, status strings, comparison
operators) no existing assertion ever actually pinned down.
"""

from __future__ import annotations

import pytest
from normalizers.postcode import PostcodeNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus, Reversibility


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
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0
        assert result.display is None
        assert result.comparison is None
        assert result.errors == []
        assert result.warnings == []

    def test_empty(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("", _ctx())
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_whitespace_only_is_treated_as_empty(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("   ", _ctx("GB"))
        assert result.original_kind is MissingKind.EMPTY_STRING


@pytest.mark.unit
class TestValidPostcodes:
    def test_uk_postcode_valid(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("SW1A 1AA", _ctx("GB"))
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "VALID"
        assert result.structured == {"country": "GB", "format_valid": True}
        assert result.confidence == 1.0
        assert result.original == "SW1A 1AA"
        assert result.display == "SW1A 1AA"
        assert result.comparison == "SW1A 1AA"
        assert result.search == "SW1A 1AA"
        assert result.errors == []
        assert result.warnings == []
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.trace[0].library == "google-i18n-address"
        assert result.lossiness is Reversibility.REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_us_zip_valid(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("90210", _ctx("US"))
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "VALID"
        assert result.structured == {"country": "US", "format_valid": True}
        assert result.confidence == 1.0

    def test_canadian_postcode_valid(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("K1A 0B1", _ctx("CA"))
        assert result.structured["format_valid"] is True
        assert result.validation_status == "VALID"

    def test_case_insensitive_comparison(self, normalizer: PostcodeNormalizer) -> None:
        lower = normalizer.normalize("sw1a 1aa", _ctx("GB"))
        upper = normalizer.normalize("SW1A 1AA", _ctx("GB"))
        assert lower.comparison == upper.comparison == "SW1A 1AA"
        assert lower.display == "sw1a 1aa"  # display preserves original case
        assert lower.trace[0].changed is False  # collapsing case isn't a "change" here

    def test_whitespace_collapsed(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("SW1A   1AA", _ctx("GB"))
        assert result.display == "SW1A 1AA"
        assert result.trace[0].changed is True


@pytest.mark.unit
class TestInvalidPostcodes:
    def test_us_zip_wrong_shape_is_invalid(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("ABCDE", _ctx("US"))
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.validation_status == "INVALID"
        assert result.structured == {"country": "US", "format_valid": False}
        assert result.confidence == 0.0
        assert result.original == "ABCDE"
        assert result.errors == ["does not match the expected postcode format for US"]
        assert result.warnings == []
        assert result.display == "ABCDE"
        assert result.comparison == "ABCDE"
        assert result.search == "ABCDE"
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.lossiness is Reversibility.REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_uk_postcode_wrong_shape_is_invalid(self, normalizer: PostcodeNormalizer) -> None:
        result = normalizer.normalize("NOTAPOSTCODE123456", _ctx("GB"))
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.confidence == 0.0
        assert result.errors == ["does not match the expected postcode format for GB"]


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
        assert result.validation_status == "UNKNOWN"
        assert result.structured == {"country": None, "format_valid": None}
        assert result.confidence == 0.5
        assert result.original == "12345"
        assert result.warnings == [
            "No country context available to validate postcode format against."
        ]
        assert result.errors == []
        assert result.display == "12345"
        assert result.comparison == "12345"
        assert result.search == "12345"
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.lossiness is Reversibility.REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_unresolvable_country_also_stays_ambiguous(
        self, normalizer: PostcodeNormalizer
    ) -> None:
        result = normalizer.normalize("12345", _ctx("Not A Real Country"))
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.structured == {"country": None, "format_valid": None}
        assert result.confidence == 0.5


@pytest.mark.unit
class TestNoValidationRulesAvailable:
    """A resolved, real country that google-i18n-address simply has no
    postal-code validation rules for — `validate_postcode_format`
    returns `None` (distinct from `False`), a real third outcome
    `normalize()` must not conflate with either "valid" or "invalid".
    Verified empirically against the real library (UAE has no postal
    code system), not assumed."""

    def test_country_with_no_postal_rules_is_unknown_not_invalid(
        self, normalizer: PostcodeNormalizer
    ) -> None:
        result = normalizer.normalize("00000", _ctx("AE"))
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "UNKNOWN"
        assert result.structured == {"country": "AE", "format_valid": None}
        assert result.confidence == 0.7
        assert result.original == "00000"
        assert result.errors == []
        assert result.warnings == []
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.lossiness is Reversibility.REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""
