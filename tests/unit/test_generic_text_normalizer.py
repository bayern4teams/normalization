"""Unit tests for GenericTextNormalizer — Source.txt §9-§19, §53, §54, §63.

Exercises the full Normalizer Protocol surface (normalize, normalize_batch,
validate, explain, version, steps, inverse) plus the missing-value
sentinel detection and multi-view assembly this normalizer is responsible
for.
"""

# One test below deliberately contains a Cyrillic confusable character.
# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
# ruff: noqa: RUF001, RUF003

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest
from normalizers.generic_text import GenericTextNormalizer
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)
from normdict.loader import DictionaryLoader

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


@pytest.fixture
def normalizer() -> GenericTextNormalizer:
    return GenericTextNormalizer(DictionaryLoader(_DICT_ROOT))


@pytest.fixture
def ctx() -> NormalizationContext:
    return NormalizationContext(field_name="bio", semantic_type=FieldSemanticType.FREE_TEXT)


@pytest.mark.unit
class TestProtocolShape:
    def test_supported_types_is_free_text_only(self, normalizer: GenericTextNormalizer) -> None:
        assert normalizer.supported_types == frozenset({FieldSemanticType.FREE_TEXT})

    def test_can_handle_free_text(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        assert normalizer.can_handle(FieldSemanticType.FREE_TEXT, ctx) is True

    def test_can_handle_rejects_other_types(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        assert normalizer.can_handle(FieldSemanticType.EMAIL, ctx) is False

    def test_version_reports_name(self, normalizer: GenericTextNormalizer) -> None:
        version = normalizer.version()
        assert version.name == "GenericTextNormalizer"
        assert version.version

    def test_steps_nonempty_and_shape_matches_step_spec(
        self, normalizer: GenericTextNormalizer
    ) -> None:
        steps = normalizer.steps()
        assert len(steps) > 0
        for step in steps:
            assert isinstance(step.step_id, str)
            assert isinstance(step.claimed_reversibility, Reversibility)
            assert isinstance(step.lossy, bool)


@pytest.mark.unit
class TestMissingValueDetection:
    def test_none_is_null(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize(None, ctx)
        assert result.original_kind is MissingKind.NULL
        assert result.original is None

    def test_empty_string(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("", ctx)
        assert result.original_kind is MissingKind.EMPTY_STRING

    def test_whitespace_only_is_empty_string(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("   ", ctx)
        assert result.original_kind is MissingKind.EMPTY_STRING

    @pytest.mark.parametrize(
        ("raw", "expected_kind"),
        [
            ("N/A", MissingKind.NOT_APPLICABLE),
            ("n/a", MissingKind.NOT_APPLICABLE),
            ("NULL", MissingKind.NULL),
            ("null", MissingKind.NULL),
            ("unknown", MissingKind.UNKNOWN_VALUE),
            ("--", MissingKind.NOT_APPLICABLE),
            ("[REDACTED]", MissingKind.REDACTED),
        ],
    )
    def test_dictionary_sentinels(
        self,
        normalizer: GenericTextNormalizer,
        ctx: NormalizationContext,
        raw: str,
        expected_kind: MissingKind,
    ) -> None:
        result = normalizer.normalize(raw, ctx)
        assert result.original_kind is expected_kind
        assert result.original == raw

    def test_real_value_is_not_flagged_missing(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Jane Doe", ctx)
        assert result.original_kind is None


@pytest.mark.unit
class TestMultiViewAssembly:
    def test_original_is_byte_preserved(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        raw = "  José   García  "
        result = normalizer.normalize(raw, ctx)
        assert result.original == raw

    def test_display_is_cleaned_but_accented(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("  José   García  ", ctx)
        assert result.display == "José García"

    def test_comparison_is_casefolded_but_keeps_accents(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("José", ctx)
        assert result.comparison == "josé"

    def test_search_is_casefolded_and_accent_stripped(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("José", ctx)
        assert result.search == "jose"

    def test_ascii_view_is_null_by_default(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("José", ctx)
        assert result.ascii is None

    def test_ascii_view_populated_when_opted_in(self, ctx: NormalizationContext) -> None:
        opted_in = GenericTextNormalizer(DictionaryLoader(_DICT_ROOT), include_ascii=True)
        result = opted_in.normalize("José", ctx)
        assert result.ascii == "Jose"

    def test_structured_carries_accent_stripped_and_confusable_diagnostics(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("José", ctx)
        assert result.structured["accent_stripped"] == "Jose"
        assert "confusable_skeleton" in result.structured
        assert result.structured["mixed_script_detected"] is False

    def test_fingerprints_absent_by_default(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Smith, John", ctx)
        assert "fingerprint" not in result.structured

    def test_fingerprints_present_when_opted_in(self, ctx: NormalizationContext) -> None:
        opted_in = GenericTextNormalizer(DictionaryLoader(_DICT_ROOT), include_fingerprints=True)
        result = opted_in.normalize("Smith, John", ctx)
        assert result.structured["fingerprint"] == "john smith"


@pytest.mark.unit
class TestStatusAndFlags:
    def test_unchanged_value_stays_unchanged(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("hello world", ctx)
        assert result.normalization_status is NormalizationStatus.UNCHANGED
        assert result.flags == []

    def test_whitespace_cleanup_yields_normalized_status(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("  hello   world  ", ctx)
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.display == "hello world"

    def test_mojibake_repair_yields_repaired_status_and_flags(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        mojibake = "cafÃ©"
        result = normalizer.normalize(mojibake, ctx)
        assert result.normalization_status is NormalizationStatus.REPAIRED
        assert result.repaired is not None
        assert QualityFlag.MOJIBAKE_FIXED in result.flags
        assert QualityFlag.ENCODING_REPAIRED in result.flags

    def test_correctly_decoded_accented_text_is_not_flagged_as_repaired(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        """ADR-002's zero-false-positive requirement, exercised directly
        (the dedicated corpus test lives in tests/golden)."""
        result = normalizer.normalize("ZURÜCK", ctx)
        assert result.repaired is None
        assert QualityFlag.MOJIBAKE_FIXED not in result.flags

    def test_mixed_script_sets_confusable_flags(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("hаrvest", ctx)  # Cyrillic а
        assert QualityFlag.MIXED_SCRIPT in result.flags
        assert QualityFlag.CONFUSABLE_DETECTED in result.flags

    def test_original_never_overwritten_regardless_of_transformation(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        raw = "  cafÃ©   test  "
        result = normalizer.normalize(raw, ctx)
        assert result.original == raw


@pytest.mark.unit
class TestTrace:
    def test_trace_records_every_pipeline_step(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("  hello  world  ", ctx)
        operations = [step.operation for step in result.trace]
        assert "text_repair" in operations
        assert "unicode_normalize_nfc" in operations
        assert "collapse_whitespace" in operations
        assert "trim" in operations

    def test_trace_masks_never_contain_raw_characters(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("SecretName123", ctx)
        for step in result.trace:
            assert "SecretName123" not in step.input_mask
            assert "SecretName123" not in step.output_mask

    def test_changed_steps_have_differing_hashes(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("  hello  ", ctx)
        trim_step = next(s for s in result.trace if s.operation == "trim")
        assert trim_step.changed is True
        assert trim_step.input_hash != trim_step.output_hash


@pytest.mark.unit
class TestValidateExplainInverse:
    def test_validate_missing_value(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        outcome = normalizer.validate("N/A", ctx)
        assert outcome.is_valid is False
        assert outcome.status == "MISSING"

    def test_validate_real_value(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        outcome = normalizer.validate("hello", ctx)
        assert outcome.is_valid is True

    def test_explain_no_changes(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("hello", ctx)
        explanation = normalizer.explain(result)
        assert "No changes" in explanation.plain_language

    def test_explain_reports_changes(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("  hello  ", ctx)
        explanation = normalizer.explain(result)
        assert explanation.plain_language != "No changes were needed."

    def test_inverse_nfc_step_round_trips_via_nfd(self, normalizer: GenericTextNormalizer) -> None:
        composed = "café"
        inverted = normalizer.inverse("unicode_normalize_nfc", composed)
        assert inverted is not None
        # NFD form of "café" decomposes e-acute into e + combining accent.
        assert inverted != composed
        assert len(inverted) > len(composed)

    def test_inverse_lossy_step_returns_none(self, normalizer: GenericTextNormalizer) -> None:
        assert normalizer.inverse("trim", "hello") is None
        assert normalizer.inverse("text_repair", "hello") is None


@pytest.mark.unit
class TestNormalizeBatch:
    def test_batch_matches_scalar_results(
        self, normalizer: GenericTextNormalizer, ctx: NormalizationContext
    ) -> None:
        values = ["  hello  ", "world", None]
        batch_result = normalizer.normalize_batch(pa.array(values, type=pa.large_string()), ctx)
        displays = batch_result.field("display").to_pylist()
        expected = [normalizer.normalize(v, ctx).display for v in values]
        assert displays == expected
