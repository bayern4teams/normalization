"""Unit tests for PhoneNormalizer — Source.txt §36-§38."""

from __future__ import annotations

import pyarrow as pa
import pytest
from normalizers.phone import PhoneNormalizer
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)


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
class TestExactFields:
    """A real mutmut run (M12) found 42 surviving mutants in
    `PhoneNormalizer.normalize` — mostly literal constants (confidence
    values, empty-list/dict defaults, `lossiness`) the field-by-field
    checks above never pinned down exactly."""

    def test_missing_none_every_field(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize(None, _ctx())
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0
        assert result.display is None
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_missing_empty_every_field(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("", _ctx())
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_valid_via_explicit_plus_every_field(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("+1 415-555-2671", _ctx())
        assert result.original == "+1 415-555-2671"
        assert result.display == "+1 415-555-2671"
        assert result.comparison == "+14155552671"
        assert result.search == "+14155552671"
        assert result.structured == {
            "country_code": 1,
            "national_number": "4155552671",
            "extension": None,
            "e164": "+14155552671",
            "international_format": "+1 415-555-2671",
            "national_format": "(415) 555-2671",
            "is_possible": True,
            "is_valid": True,
            "region": "US",
            "region_source": "number_prefix",
            "validation_message": None,
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.confidence == 1.0
        assert result.flags == []
        assert result.errors == []
        assert result.lossiness is Reversibility.PARTIALLY_REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is True
        assert result.trace[0].library == "phonenumbers"

    def test_parses_but_fails_validity_every_field(self, normalizer: PhoneNormalizer) -> None:
        """A well-formed-enough string that `phonenumbers.parse()`
        accepts but `is_valid_number()` rejects — a distinct code path
        from the NumberParseException branch below."""
        result = normalizer.normalize("123", _ctx(country="US"))
        assert result.structured["is_possible"] is False
        assert result.structured["is_valid"] is False
        assert result.structured["region"] is None
        assert (
            result.structured["validation_message"]
            == "Number is not a valid number for its region."
        )
        assert result.validation_status == "INVALID"
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.confidence == 0.5
        assert result.flags == [QualityFlag.PHONE_INVALID]
        assert result.errors == []
        assert result.lossiness is Reversibility.PARTIALLY_REVERSIBLE

    def test_unparseable_string_every_field(self, normalizer: PhoneNormalizer) -> None:
        """`phonenumbers.parse()` itself raising `NumberParseException` —
        `structured` stays `{}` (never partially populated), `trace`
        stays empty (no parse step was completed), and `lossiness`
        defaults to LOSSLESS rather than claiming PARTIALLY_REVERSIBLE
        for a parse that never happened."""
        result = normalizer.normalize("not a phone number", _ctx(country="US"))
        assert result.original == "not a phone number"
        assert result.display == "not a phone number"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "INVALID"
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.confidence == 0.0
        assert result.flags == [QualityFlag.PHONE_INVALID]
        assert result.errors == ["(1) The string supplied did not seem to be a phone number."]
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.trace == []
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_ambiguous_no_region_every_field(self, normalizer: PhoneNormalizer) -> None:
        result = normalizer.normalize("415-555-2671", _ctx())
        assert result.original == "415-555-2671"
        assert result.display == "415-555-2671"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {"region_source": "unknown"}
        assert result.validation_status == "AMBIGUOUS"
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.confidence == 0.0
        assert result.flags == []
        assert result.errors == []
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.trace == []
        assert result.profile_version == ""
        assert result.env_id == ""


@pytest.mark.unit
class TestBatch:
    def test_normalize_batch_matches_scalar(self, normalizer: PhoneNormalizer) -> None:
        ctx = _ctx(country="US")
        values = ["415-555-2671", "+1 415-555-2671"]
        batch = normalizer.normalize_batch(pa.array(values, type=pa.large_string()), ctx)
        displays = batch.field("display").to_pylist()
        assert displays == [normalizer.normalize(v, ctx).display for v in values]
