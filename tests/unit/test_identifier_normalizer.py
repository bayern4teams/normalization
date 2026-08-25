"""Unit tests for IdentifierNormalizer and UuidNormalizer — Source.txt
§49-§51, §55."""

from __future__ import annotations

import pyarrow as pa
import pytest
from normalizers.identifier import IdentifierNormalizer, UuidNormalizer
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)


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
class TestIdentifierNormalizerExactFields:
    """A real mutmut run (M12) found 29 surviving mutants in
    `IdentifierNormalizer.normalize` — the field-by-field checks above
    only ever assert one or two fields per branch, never pin down
    exact `confidence`/`structured`/`lossiness`/defaults."""

    def test_missing_none_every_field(self, normalizer: IdentifierNormalizer) -> None:
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
        assert result.flags == []
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert result.trace == []

    def test_missing_empty_every_field(self, normalizer: IdentifierNormalizer) -> None:
        result = normalizer.normalize("", _ctx())
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.validation_status == "MISSING"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0

    def test_plain_valid_identifier_every_field(self, normalizer: IdentifierNormalizer) -> None:
        result = normalizer.normalize("000123", _ctx())
        assert result.original == "000123"
        assert result.original_kind is None
        assert result.display == "000123"
        assert result.comparison == "000123"
        assert result.search == "000123"
        assert result.structured == {
            "cleaned": "000123",
            "has_internal_separator": False,
            "check_digit_valid": None,
            "identifier_type": None,
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.flags == []
        assert result.lossiness is Reversibility.REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.trace[0].library == "python-stdnum"

    def test_hyphenated_every_field(self, normalizer: IdentifierNormalizer) -> None:
        result = normalizer.normalize("AB-001", _ctx())
        assert result.flags == [QualityFlag.POTENTIAL_COLLISION]
        assert result.structured["has_internal_separator"] is True
        assert result.confidence == 1.0
        assert result.validation_status == "VALID"

    def test_valid_us_ein_every_field(self, normalizer: IdentifierNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.TAX_ID, country="US")
        result = normalizer.normalize("12-3456789", ctx)
        assert result.confidence == 1.0
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.structured == {
            "cleaned": "12-3456789",
            "has_internal_separator": True,
            "check_digit_valid": True,
            "identifier_type": "US",
        }

    def test_lowercase_letters_are_uppercased(self, normalizer: IdentifierNormalizer) -> None:
        """Case normalization is always upper, never lower — a mutant
        flipping `.upper()` to `.lower()` is invisible to every other
        test in this file since they all use inputs with no letters or
        already-uppercase letters."""
        result = normalizer.normalize("ab-cd1234", _ctx())
        assert result.display == "AB-CD1234"
        assert result.comparison == "AB-CD1234"

    def test_invalid_us_ein_every_field(self, normalizer: IdentifierNormalizer) -> None:
        """The check-digit-invalid branch: confidence drops to exactly
        0.3, not just <1.0, and validation_status flips to INVALID."""
        ctx = _ctx(FieldSemanticType.TAX_ID, country="US")
        result = normalizer.normalize("00-0000000", ctx)
        assert result.confidence == 0.3
        assert result.validation_status == "INVALID"
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.structured == {
            "cleaned": "00-0000000",
            "has_internal_separator": True,
            "check_digit_valid": False,
            "identifier_type": "US",
        }


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

    def test_missing_none_every_field(self, uuid_normalizer: UuidNormalizer) -> None:
        result = uuid_normalizer.normalize(None, _ctx(FieldSemanticType.UUID))
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0
        assert result.display is None
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_missing_empty_every_field(self, uuid_normalizer: UuidNormalizer) -> None:
        result = uuid_normalizer.normalize("", _ctx(FieldSemanticType.UUID))
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_valid_uuid_every_field(self, uuid_normalizer: UuidNormalizer) -> None:
        """A real mutmut run (M12) found 41 surviving mutants in
        `UuidNormalizer.normalize` — mostly literal constants
        (confidence, `""` defaults, `lossiness`) never pinned down
        exactly by the field-by-field checks above."""
        raw = "{550E8400-E29B-41D4-A716-446655440000}"
        result = uuid_normalizer.normalize(raw, _ctx(FieldSemanticType.UUID))
        assert result.original == raw
        assert result.display == "550e8400-e29b-41d4-a716-446655440000"
        assert result.comparison == "550e8400-e29b-41d4-a716-446655440000"
        assert result.search == "550e8400-e29b-41d4-a716-446655440000"
        assert result.structured == {
            "version": 4,
            "canonical": "550e8400-e29b-41d4-a716-446655440000",
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.lossiness is Reversibility.REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is True
        assert result.trace[0].library == "python-stdnum"

    def test_already_canonical_form_trace_changed_is_false(
        self, uuid_normalizer: UuidNormalizer
    ) -> None:
        """`changed` compares the canonical form against the
        already-stripped `cleaned` value, not the raw `value` —
        already-canonical input must report unchanged."""
        canonical = "550e8400-e29b-41d4-a716-446655440000"
        result = uuid_normalizer.normalize(canonical, _ctx(FieldSemanticType.UUID))
        assert result.trace[0].changed is False

    def test_invalid_uuid_every_field(self, uuid_normalizer: UuidNormalizer) -> None:
        result = uuid_normalizer.normalize("not-a-uuid", _ctx(FieldSemanticType.UUID))
        assert result.original == "not-a-uuid"
        assert result.display == "not-a-uuid"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "INVALID"
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.confidence == 0.0
        assert result.errors == ["not a valid UUID"]
        assert result.lossiness is Reversibility.LOSSLESS
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.profile_version == ""
        assert result.env_id == ""
