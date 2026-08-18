"""Unit tests for PhoneNormalizer — Source.txt §36-§38."""

from __future__ import annotations

import pyarrow as pa
import pytest
from normalizers.phone import PhoneNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus, QualityFlag


@pytest.fixture
def normalizer() -> PhoneNormalizer:
    return PhoneNormalizer()


def _ctx(*, country: str | None = None, default_region: str | None = None) -> NormalizationContext:
    return NormalizationContext(
        field_name="phone",
        semantic_type=FieldSemanticType.PHONE,
        country=country,
        default_region=default_region,
    )


@pytest.mark.unit
class TestProtocolShape:
    def test_supported_types(self, normalizer: PhoneNormalizer) -> None:
        assert normalizer.supported_types == frozenset({FieldSemanticType.PHONE})

    def test_version(self, normalizer: PhoneNormalizer) -> None:
        assert normalizer.version().name == "PhoneNormalizer"


@pytest.mark.unit
class TestMissingValues:
    def test_none(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize(None, _ctx())
        assert result.original_kind is MissingKind.NULL

    def test_empty(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("", _ctx())
        assert result.original_kind is MissingKind.EMPTY_STRING


@pytest.mark.unit
class TestExplicitCountryCode:
    def test_plus_prefixed_number_parses_without_context(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("+1 415-555-2671", _ctx())
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.structured["is_valid"] is True
        assert result.structured["e164"] == "+14155552671"
        assert result.structured["region_source"] == "number_prefix"

    def test_e164_is_the_comparison_view(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("+1 415-555-2671", _ctx())
        assert result.comparison == result.structured["e164"]


@pytest.mark.unit
class TestRegionPrecedence:
    def test_explicit_context_country_used(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("415-555-2671", _ctx(country="US"))
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.structured["region_source"] == "explicit"
        assert QualityFlag.PHONE_REGION_INFERRED not in result.flags

    def test_default_region_used_as_fallback(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("415-555-2671", _ctx(default_region="US"))
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.structured["region_source"] == "default_region"
        assert QualityFlag.PHONE_REGION_INFERRED in result.flags

    def test_explicit_country_wins_over_default_region(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("415-555-2671", _ctx(country="US", default_region="GB"))
        assert result.structured["region_source"] == "explicit"
        assert result.structured["region"] == "US"

    def test_number_prefix_wins_over_any_context(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("+1 415-555-2671", _ctx(country="GB"))
        assert result.structured["region_source"] == "number_prefix"
        assert result.structured["region"] == "US"


@pytest.mark.unit
class TestNoGuessing:
    def test_no_region_and_no_plus_is_ambiguous(self, normalizer: PhoneNormalizer) -> None:
        """Source.txt §36: no country inferable -> AMBIGUOUS, never a
        silent guess."""
        result = normalizer.normalize("415-555-2671", _ctx())
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.comparison is None
        assert result.structured["region_source"] == "unknown"

    def test_ambiguous_original_still_preserved(self, normalizer: PhoneNormalizer) -> None:
        raw = "415-555-2671"
        result = normalizer.normalize(raw, _ctx())
        assert result.original == raw

    def test_validate_ambiguous_is_invalid(self, normalizer: PhoneNormalizer) -> None:
        outcome = normalizer.validate("415-555-2671", _ctx())
        assert outcome.is_valid is False
        assert outcome.status == "AMBIGUOUS"


@pytest.mark.unit
class TestExtensions:
    def test_extension_stored_separately(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("+1 415-555-2671 ext. 123", _ctx())
        assert result.structured["extension"] == "123"

    def test_extension_never_merged_into_e164(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("+1 415-555-2671 ext. 123", _ctx())
        assert "123" not in result.structured["e164"]
        assert result.structured["e164"] == "+14155552671"

    def test_no_extension_is_none(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("+1 415-555-2671", _ctx())
        assert result.structured["extension"] is None


@pytest.mark.unit
class TestInvalidNumbers:
    def test_garbage_text_with_context_is_invalid(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("not a phone number", _ctx(country="US"))
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.errors != []

    def test_too_short_number_is_invalid_not_valid(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("123", _ctx(country="US"))
        if result.normalization_status is NormalizationStatus.PARSED:
            assert result.structured["is_valid"] is False
        else:
            assert result.normalization_status is NormalizationStatus.INVALID


@pytest.mark.unit
class TestBatch:
    def test_normalize_batch_matches_scalar(self, normalizer: PhoneNormalizer) -> None:
        ctx = _ctx(country="US")
        values = ["415-555-2671", "+1 415-555-2671"]
        batch = normalizer.normalize_batch(pa.array(values, type=pa.large_string()), ctx)
        displays = batch.field("display").to_pylist()
        assert displays == [normalizer.normalize(v, ctx).display for v in values]
