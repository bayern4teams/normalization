"""Unit tests for IdentifierNormalizer and UuidNormalizer — Source.txt
§49-§51, §55."""

from __future__ import annotations

import pyarrow as pa
import pytest
from normalizers.identifier import IdentifierNormalizer, UuidNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus, QualityFlag


@pytest.fixture
def normalizer() -> IdentifierNormalizer:
    return IdentifierNormalizer()


@pytest.fixture
def uuid_normalizer() -> UuidNormalizer:
    return UuidNormalizer()


def _ctx(
    semantic_type: FieldSemanticType = FieldSemanticType.IDENTIFIER,
    *,
    country: str | None = None,
) -> NormalizationContext:
    return NormalizationContext(field_name="id", semantic_type=semantic_type, country=country)


@pytest.mark.unit
class TestProtocolShape:
    def test_supported_types(self, normalizer: IdentifierNormalizer) -> None:
        assert normalizer.supported_types == frozenset(
            {FieldSemanticType.IDENTIFIER, FieldSemanticType.TAX_ID, FieldSemanticType.CODE}
        )

    def test_version(self, normalizer: IdentifierNormalizer) -> None:
        assert normalizer.version().name == "IdentifierNormalizer"


@pytest.mark.unit
class TestMissingValues:
    def test_none(self, normalizer: IdentifierNormalizer) -> None:
        result = normalizer.normalize(None, _ctx())
        assert result.original_kind is MissingKind.NULL

    def test_empty(self, normalizer: IdentifierNormalizer) -> None:
        result = normalizer.normalize("", _ctx())
        assert result.original_kind is MissingKind.EMPTY_STRING


@pytest.mark.unit
class TestLeadingZeros:
    def test_leading_zeros_never_removed(self, normalizer: IdentifierNormalizer) -> None:
        """Source.txt §49's mandatory golden test."""
        result = normalizer.normalize("000123", _ctx())
        assert result.display == "000123"
        assert result.structured["cleaned"] == "000123"

    def test_never_cast_to_numeric(self, normalizer: IdentifierNormalizer) -> None:
        """Source.txt §55: "00123" != 123 as an identifier."""
        result = normalizer.normalize("00123", _ctx())
        assert isinstance(result.display, str)
        assert result.display == "00123"
        assert result.comparison == "00123"


@pytest.mark.unit
class TestUnicodeDigitNormalization:
    def test_arabic_indic_digits_normalized_to_ascii(
        self, normalizer: IdentifierNormalizer
    ) -> None:
        result = normalizer.normalize("١٢٣", _ctx())
        assert result.display == "123"

    def test_arabic_indic_leading_zero_preserved(self, normalizer: IdentifierNormalizer) -> None:
        result = normalizer.normalize("٠٠١٢٣", _ctx())
        assert result.display == "00123"


@pytest.mark.unit
class TestSeparatorAmbiguity:
    def test_hyphenated_form_flagged_potential_collision(
        self, normalizer: IdentifierNormalizer
    ) -> None:
        """Source.txt §111: "AB-001" vs "AB001" -> POTENTIAL_COLLISION,
        not silent equality."""
        result = normalizer.normalize("AB-001", _ctx())
        assert QualityFlag.POTENTIAL_COLLISION in result.flags
        assert result.structured["has_internal_separator"] is True

    def test_non_hyphenated_form_not_flagged(self, normalizer: IdentifierNormalizer) -> None:
        result = normalizer.normalize("AB001", _ctx())
        assert QualityFlag.POTENTIAL_COLLISION not in result.flags

    def test_hyphenated_and_non_hyphenated_are_not_silently_equal(
        self, normalizer: IdentifierNormalizer
    ) -> None:
        with_sep = normalizer.normalize("AB-001", _ctx())
        without_sep = normalizer.normalize("AB001", _ctx())
        assert with_sep.comparison != without_sep.comparison


@pytest.mark.unit
class TestCountrySpecificCheckDigits:
    def test_valid_us_ein(self, normalizer: IdentifierNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.TAX_ID, country="US")
        result = normalizer.normalize("12-3456789", ctx)
        assert result.structured["check_digit_valid"] is True
        assert result.normalization_status is NormalizationStatus.NORMALIZED

    def test_invalid_us_ein(self, normalizer: IdentifierNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.TAX_ID, country="US")
        result = normalizer.normalize("00-0000000", ctx)
        assert result.structured["check_digit_valid"] is False
        assert result.normalization_status is NormalizationStatus.INVALID

    def test_no_country_context_skips_check_digit_validation(
        self, normalizer: IdentifierNormalizer
    ) -> None:
        ctx = _ctx(FieldSemanticType.TAX_ID)
        result = normalizer.normalize("12-3456789", ctx)
        assert result.structured["check_digit_valid"] is None

    def test_unregistered_country_skips_validation(self, normalizer: IdentifierNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.TAX_ID, country="ZZ")
        result = normalizer.normalize("12-3456789", ctx)
        assert result.structured["check_digit_valid"] is None

    def test_identifier_type_not_checked_for_plain_identifier(
        self, normalizer: IdentifierNormalizer
    ) -> None:
        """Check-digit validation only applies to TAX_ID, not the
        generic IDENTIFIER type — no unwarranted validation."""
        ctx = _ctx(FieldSemanticType.IDENTIFIER, country="US")
        result = normalizer.normalize("12-3456789", ctx)
        assert result.structured["check_digit_valid"] is None


@pytest.mark.unit
class TestBatch:
    def test_normalize_batch_matches_scalar(self, normalizer: IdentifierNormalizer) -> None:
        ctx = _ctx()
        values = ["000123", "AB-001"]
        batch = normalizer.normalize_batch(pa.array(values, type=pa.large_string()), ctx)
        displays = batch.field("display").to_pylist()
        assert displays == [normalizer.normalize(v, ctx).display for v in values]


# --- UuidNormalizer ---------------------------------------------------


@pytest.mark.unit
class TestUuidNormalizer:
    def test_supported_types(self, uuid_normalizer: UuidNormalizer) -> None:
        assert uuid_normalizer.supported_types == frozenset({FieldSemanticType.UUID})

    def test_canonical_lowercase_hyphenated_form(self, uuid_normalizer: UuidNormalizer) -> None:
        """Source.txt §50's own worked example."""
        ctx = _ctx(FieldSemanticType.UUID)
        result = uuid_normalizer.normalize("{550E8400-E29B-41D4-A716-446655440000}", ctx)
        assert result.display == "550e8400-e29b-41d4-a716-446655440000"

    def test_original_retained(self, uuid_normalizer: UuidNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.UUID)
        raw = "{550E8400-E29B-41D4-A716-446655440000}"
        result = uuid_normalizer.normalize(raw, ctx)
        assert result.original == raw

    def test_invalid_uuid(self, uuid_normalizer: UuidNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.UUID)
        result = uuid_normalizer.normalize("not-a-uuid", ctx)
        assert result.normalization_status is NormalizationStatus.INVALID

    def test_already_canonical_form_unchanged(self, uuid_normalizer: UuidNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.UUID)
        canonical = "550e8400-e29b-41d4-a716-446655440000"
        result = uuid_normalizer.normalize(canonical, ctx)
        assert result.display == canonical

    def test_none_and_empty(self, uuid_normalizer: UuidNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.UUID)
        assert uuid_normalizer.normalize(None, ctx).original_kind is MissingKind.NULL
        assert uuid_normalizer.normalize("", ctx).original_kind is MissingKind.EMPTY_STRING
