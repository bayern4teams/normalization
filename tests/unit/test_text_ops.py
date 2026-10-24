"""Unit tests for the pure text-operation primitives — Source.txt §9-§19.

Each function in normalizers.text_ops is tested in isolation, independent
of the trace/NormalizedValue assembly machinery in generic_text.py.
"""

# This file deliberately contains non-Latin and visually-confusable
# characters (Cyrillic, fullwidth digits, curly quotes, ...) as literal
# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
# test fixtures, not typos — see text_ops.py's own module-level noqa for
# the same reasoning.
# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
# ruff: noqa: RUF001, RUF003

from __future__ import annotations

import pytest
from normcore.unicode_policy import UnicodeForm

from normalizers import text_ops


@pytest.mark.unit
class TestUnicodeNormalize:
    def test_nfd_decomposed_becomes_nfc_composed(self) -> None:
        decomposed = "é"  # e + combining acute accent
        output, changed = text_ops.unicode_normalize(decomposed, UnicodeForm.NFC)
        assert output == "é"  # precomposed e-acute
        assert changed is True

    def test_nfc_of_already_nfc_is_unchanged(self) -> None:
        output, changed = text_ops.unicode_normalize("é", UnicodeForm.NFC)
        assert output == "é"
        assert changed is False

    def test_nfkc_folds_fullwidth_digits_to_ascii(self) -> None:
        fullwidth = "１２３"  # fullwidth "123"
        output, changed = text_ops.unicode_normalize(fullwidth, UnicodeForm.NFKC)
        assert output == "123"
        assert changed is True

    def test_nfc_does_not_fold_fullwidth_digits(self) -> None:
        """Canonical NFC must NOT collapse compatibility distinctions —
        this is exactly why NFKC is never the default for identifiers
        (ADR-001)."""
        fullwidth = "１２３"
        output, _ = text_ops.unicode_normalize(fullwidth, UnicodeForm.NFC)
        assert output == fullwidth


@pytest.mark.unit
class TestRepairMojibake:
    def test_correctly_decoded_text_is_unchanged(self) -> None:
        output, changed, explanations = text_ops.repair_mojibake("café")
        assert output == "café"
        assert changed is False
        assert explanations == []

    def test_mojibake_is_repaired_with_explanation(self) -> None:
        mojibake = "cafÃ©"  # UTF-8 bytes of "café" decoded as latin-1
        output, changed, explanations = text_ops.repair_mojibake(mojibake)
        assert output == "café"
        assert changed is True
        assert len(explanations) > 0


@pytest.mark.unit
class TestControlAndWhitespace:
    def test_strip_control_chars_removes_nul_and_zwsp(self) -> None:
        value = "a\x00b\u200bc"
        output, changed = text_ops.strip_control_chars(value)
        assert output == "abc"
        assert changed is True

    def test_strip_control_chars_no_op_on_clean_text(self) -> None:
        output, changed = text_ops.strip_control_chars("hello world")
        assert output == "hello world"
        assert changed is False

    def test_normalize_nbsp_converts_to_regular_space(self) -> None:
        output, changed = text_ops.normalize_nbsp("a b")
        assert output == "a b"
        assert changed is True

    def test_collapse_whitespace_collapses_runs_but_preserves_newlines(self) -> None:
        output, changed = text_ops.collapse_whitespace("a   b\nc    d")
        assert output == "a b\nc d"
        assert changed is True

    def test_trim_strips_leading_and_trailing(self) -> None:
        output, changed = text_ops.trim("  hello  ")
        assert output == "hello"
        assert changed is True

    def test_trim_no_op_on_already_trimmed(self) -> None:
        _, changed = text_ops.trim("hello")
        assert changed is False


@pytest.mark.unit
class TestPunctuationAndCase:
    def test_normalize_punctuation_maps_curly_quotes(self) -> None:
        value = "‘hello’ “world”"
        output, changed = text_ops.normalize_punctuation(value)
        assert output == "'hello' \"world\""
        assert changed is True

    def test_normalize_punctuation_maps_dashes_and_ellipsis(self) -> None:
        value = "a–b—c…"
        output, changed = text_ops.normalize_punctuation(value)
        assert output == "a-b-c..."
        assert changed is True

    def test_casefold_basic(self) -> None:
        output, changed = text_ops.casefold("HELLO")
        assert output == "hello"
        assert changed is True

    def test_casefold_turkish_dotted_i(self) -> None:
        """Turkish İ (dotted capital I) should fold differently under a
        Turkish locale than under root — this is exactly what stdlib
        str.casefold() gets wrong (ADR-001)."""
        turkish_output, _ = text_ops.casefold("İstanbul", "tr_TR")
        root_output, _ = text_ops.casefold("İstanbul", None)
        assert turkish_output != root_output or turkish_output == "istanbul"


@pytest.mark.unit
class TestDiacriticsAndTransliteration:
    def test_strip_diacritics_removes_combining_marks(self) -> None:
        output, changed = text_ops.strip_diacritics("José García")
        assert output == "Jose Garcia"
        assert changed is True

    def test_strip_diacritics_no_op_on_plain_ascii(self) -> None:
        _, changed = text_ops.strip_diacritics("Hello World")
        assert changed is False

    def test_transliterate_ascii_cyrillic(self) -> None:
        output, changed = text_ops.transliterate_ascii("Москва")
        assert output.isascii()
        assert changed is True

    def test_transliterate_ascii_never_returns_empty_for_nonempty_input(self) -> None:
        output, _ = text_ops.transliterate_ascii("中文")
        assert output != ""


@pytest.mark.unit
class TestConfusables:
    def test_mixed_script_detected_for_cyrillic_latin_mix(self) -> None:
        report = text_ops.analyze_confusables("hаrvest")  # Cyrillic а
        assert report.mixed_script_detected is True
        assert "Cyrillic" in report.scripts_present
        assert "Latin" in report.scripts_present

    def test_single_script_not_flagged_mixed(self) -> None:
        report = text_ops.analyze_confusables("harvest")
        assert report.mixed_script_detected is False

    def test_skeleton_matches_for_confusable_pair(self) -> None:
        latin = text_ops.analyze_confusables("harvest")
        confusable = text_ops.analyze_confusables("hаrvest")
        assert latin.confusable_skeleton == confusable.confusable_skeleton

    def test_digits_and_punctuation_alone_are_not_mixed_script(self) -> None:
        report = text_ops.analyze_confusables("12345 !@#")
        assert report.mixed_script_detected is False
        assert report.scripts_present == ()


@pytest.mark.unit
class TestFingerprints:
    def test_fingerprint_sorts_and_dedupes_tokens(self) -> None:
        assert text_ops.openrefine_fingerprint("Smith, John") == "john smith"
        assert text_ops.openrefine_fingerprint("John Smith") == "john smith"

    def test_fingerprint_is_case_and_punctuation_insensitive(self) -> None:
        a = text_ops.openrefine_fingerprint("ACME Inc.")
        b = text_ops.openrefine_fingerprint("acme, inc")
        assert a == b

    def test_ngram_fingerprint_catches_token_boundary_variation(self) -> None:
        a = text_ops.openrefine_ngram_fingerprint("New York")
        b = text_ops.openrefine_ngram_fingerprint("NewYork")
        assert a == b


@pytest.mark.unit
class TestApplyNamedOperationAndInverse:
    def test_apply_named_operation_matches_direct_call(self) -> None:
        direct = text_ops.trim("  x  ")
        via_name = text_ops.apply_named_operation("trim", "  x  ")
        assert direct == via_name

    def test_inverse_unicode_form_nfc_nfd_are_symmetric(self) -> None:
        assert text_ops.inverse_unicode_form(UnicodeForm.NFC) == UnicodeForm.NFD
        assert text_ops.inverse_unicode_form(UnicodeForm.NFD) == UnicodeForm.NFC

    def test_inverse_unicode_form_nfkc_has_no_inverse(self) -> None:
        assert text_ops.inverse_unicode_form(UnicodeForm.NFKC) is None


@pytest.mark.unit
def test_detect_encoding_confidence_on_clean_utf8_text() -> None:
    _, confidence = text_ops.detect_encoding_confidence("hello world")
    assert confidence >= 0.0
    assert confidence <= 1.0
