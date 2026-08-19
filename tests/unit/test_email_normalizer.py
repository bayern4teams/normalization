"""Unit tests for EmailNormalizer — Source.txt §39-§41."""

from __future__ import annotations

import pyarrow as pa
import pytest
from normalizers.email import EmailNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus


@pytest.fixture
def normalizer() -> EmailNormalizer:
    return EmailNormalizer()


@pytest.fixture
def ctx() -> NormalizationContext:
    return NormalizationContext(field_name="email", semantic_type=FieldSemanticType.EMAIL)


@pytest.mark.unit
class TestProtocolShape:
    def test_supported_types(self, normalizer: EmailNormalizer) -> None:
        assert normalizer.supported_types == frozenset({FieldSemanticType.EMAIL})

    def test_version(self, normalizer: EmailNormalizer) -> None:
        assert normalizer.version().name == "EmailNormalizer"


@pytest.mark.unit
class TestMissingValues:
    def test_none(self, normalizer: EmailNormalizer, ctx: NormalizationContext) -> None:
        result = normalizer.normalize(None, ctx)
        assert result.original_kind is MissingKind.NULL

    def test_empty(self, normalizer: EmailNormalizer, ctx: NormalizationContext) -> None:
        result = normalizer.normalize("", ctx)
        assert result.original_kind is MissingKind.EMPTY_STRING


@pytest.mark.unit
class TestBasicNormalization:
    def test_domain_is_lowercased_local_part_case_preserved(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("John.Smith+tag@Example.COM", ctx)
        assert result.structured["domain"] == "example.com"
        assert result.structured["local_part"] == "John.Smith+tag"

    def test_display_name_and_angle_brackets_split_correctly(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        """Source.txt §39's own worked example."""
        result = normalizer.normalize(" John Smith <john.smith@example.com> ", ctx)
        assert result.structured["display_name"] == "John Smith"
        assert result.structured["local_part"] == "john.smith"
        assert result.structured["domain"] == "example.com"

    def test_no_display_name_is_none(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("plain@example.com", ctx)
        assert result.structured["display_name"] is None

    def test_original_never_overwritten(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        raw = " John.Smith+tag@Example.COM "
        result = normalizer.normalize(raw, ctx)
        assert result.original == raw


@pytest.mark.unit
class TestProviderSpecificRulesOffByDefault:
    def test_gmail_dots_are_not_removed(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        """Source.txt §39/§4.5: no dot removal unless explicitly
        configured per-domain (not implemented in this milestone at all,
        so it can never fire by accident)."""
        result = normalizer.normalize("j.o.h.n@gmail.com", ctx)
        assert result.structured["local_part"] == "j.o.h.n"

    def test_plus_tag_is_not_stripped(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("john+newsletter@example.com", ctx)
        assert result.structured["local_part"] == "john+newsletter"
        assert result.display is not None
        assert "+newsletter" in result.display


@pytest.mark.unit
class TestInternationalizedDomains:
    def test_unicode_domain_preserved_with_ascii_form_available(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("user@münchen.de", ctx)
        assert result.structured["domain"] == "münchen.de"
        assert result.structured["domain_ascii"] == "xn--mnchen-3ya.de"
        assert result.validation_status == "INTERNATIONALIZED"

    def test_ascii_domain_gets_valid_syntax_status(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("user@example.com", ctx)
        assert result.validation_status == "VALID_SYNTAX"


@pytest.mark.unit
class TestInvalidEmails:
    def test_missing_at_sign_is_invalid(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("not an email", ctx)
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.validation_status == "INVALID_SYNTAX"
        assert result.errors != []
        assert result.comparison is None

    def test_validate_invalid_email(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        outcome = normalizer.validate("not an email", ctx)
        assert outcome.is_valid is False


@pytest.mark.unit
class TestDeliverabilityNeverChecked:
    def test_never_emits_deliverability_dependent_statuses(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        """§41's determinism requirement: check_deliverability is always
        False, so UNKNOWN/POSSIBLY_DELIVERABLE/UNDELIVERABLE are never
        reachable outcomes of this implementation."""
        result = normalizer.normalize("user@example.com", ctx)
        assert result.validation_status not in {
            "UNKNOWN",
            "POSSIBLY_DELIVERABLE",
            "UNDELIVERABLE",
        }


@pytest.mark.unit
class TestBatch:
    def test_normalize_batch_matches_scalar(
        self, normalizer: EmailNormalizer, ctx: NormalizationContext
    ) -> None:
        values = ["John.Smith@Example.com", "not an email"]
        batch = normalizer.normalize_batch(pa.array(values, type=pa.large_string()), ctx)
        displays = batch.field("display").to_pylist()
        assert displays == [normalizer.normalize(v, ctx).display for v in values]
