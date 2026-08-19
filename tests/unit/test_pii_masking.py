"""Source.txt §123 (Security) — traces/logs must never leak raw PII by
default. `normcore.pii` is the one place this guarantee is implemented;
this file is the one place it's directly, adversarially tested rather
than only exercised incidentally as a side effect of other tests.
"""

from __future__ import annotations

import pytest
from normalizers.email import EmailNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType
from normcore.pii import character_class_mask, content_hash, safe_preview

_REALISTIC_PII_VALUES = (
    "jane.doe@example.com",
    "+1-202-555-0143",
    "José García",
    "4111 1111 1111 1111",
    "123-45-6789",
)


@pytest.mark.unit
class TestSafePreview:
    @pytest.mark.parametrize("value", _REALISTIC_PII_VALUES)
    def test_default_visibility_never_contains_the_raw_value(self, value: str) -> None:
        preview = safe_preview(value)
        assert value not in preview

    @pytest.mark.parametrize("value", _REALISTIC_PII_VALUES)
    def test_masked_visibility_never_contains_the_raw_value_or_any_3char_substring(
        self, value: str
    ) -> None:
        preview = safe_preview(value, pii_visibility="masked")
        assert value not in preview
        # A stronger check than "the whole value is absent": no 3+
        # character contiguous substring of the raw value should survive
        # into the masked preview either (guards against a mask
        # implementation that echoes fragments of the input).
        for start in range(len(value) - 2):
            fragment = value[start : start + 3]
            if fragment.strip() and fragment.isalnum():
                assert fragment not in preview, f"leaked fragment {fragment!r} from {value!r}"

    def test_unmasked_visibility_is_an_explicit_opt_in_that_really_returns_raw(self) -> None:
        value = "jane.doe@example.com"
        assert safe_preview(value, pii_visibility="unmasked") == value

    def test_default_parameter_value_is_masked_not_unmasked(self) -> None:
        value = "jane.doe@example.com"
        assert safe_preview(value) == safe_preview(value, pii_visibility="masked")
        assert safe_preview(value) != value


@pytest.mark.unit
class TestCharacterClassMask:
    @pytest.mark.parametrize("value", _REALISTIC_PII_VALUES)
    def test_mask_never_contains_original_characters(self, value: str) -> None:
        mask = character_class_mask(value)
        # Unicode category codes are always exactly 2 uppercase/lowercase
        # letters (e.g. "Lu", "Nd", "Zs") — none of the original alnum
        # characters from a realistic PII value should ever appear as a
        # standalone token in the mask output.
        original_chars = {ch for ch in value if ch.isalnum()}
        mask_tokens = set(mask.replace("…", "").split())
        assert not (original_chars & mask_tokens)

    def test_mask_preserves_length_structure_for_short_values(self) -> None:
        mask = character_class_mask("ab1")
        assert len(mask.split()) == 3

    def test_mask_is_deterministic(self) -> None:
        value = "jane.doe@example.com"
        assert character_class_mask(value) == character_class_mask(value)


@pytest.mark.unit
class TestContentHash:
    def test_hash_never_equals_the_raw_value(self) -> None:
        value = "jane.doe@example.com"
        assert content_hash(value) != value

    def test_hash_is_deterministic(self) -> None:
        value = "jane.doe@example.com"
        assert content_hash(value) == content_hash(value)

    def test_different_values_produce_different_hashes(self) -> None:
        assert content_hash("jane.doe@example.com") != content_hash("john.doe@example.com")


@pytest.mark.unit
class TestTraceMasksOnARealNormalizer:
    def test_email_normalizer_trace_masks_never_leak_the_raw_address(self) -> None:
        normalizer = EmailNormalizer()
        ctx = NormalizationContext(field_name="email", semantic_type=FieldSemanticType.EMAIL)
        raw = "jane.doe@example.com"
        result = normalizer.normalize(raw, ctx)

        for step in result.trace:
            assert raw not in step.input_mask
            assert raw not in step.output_mask
            assert raw not in step.input_hash
            assert raw not in step.output_hash
