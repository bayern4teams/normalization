"""Text-behaviour golden corpus — Source.txt §75 (cross-script coverage)
and §110 (Unicode edge cases). Gate G2 requirement.

Per the plan's resolution of the §109-vs-§75/§110 tension (see the
project's M0 planning notes / docs/normalization-architecture.md): this
corpus uses only synthetic, non-identity strings (no person/company
names) across the scripts §75 names, plus the specific edge-case classes
§110 calls out (mojibake, mixed normalization forms, zero-width
characters, emoji, non-Latin scripts, punctuation, grapheme clusters,
bidi text). The *identity* corpus (US/Western-European names/addresses
per §109) is separate M3+ scope.

Every case in `CASES` must: never raise, never produce
normalization_status FAILED, never corrupt the value into mojibake
(false positive from `ftfy`), and round-trip idempotently through a
second normalize() call on its own `display` output.
"""

# This corpus deliberately spans many scripts (Turkish, Cyrillic, Greek,
# Arabic, Hebrew, Han, Hiragana/Katakana, Hangul, Devanagari, ...) and
# includes intentional confusable/mixed-script fixtures — none of this is
# a typo.
# ruff: noqa: RUF001, RUF003

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from normalizers.generic_text import GenericTextNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from normdict.loader import DictionaryLoader

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


@dataclass(frozen=True)
class GoldenCase:
    label: str
    value: str
    expect_mixed_script: bool = False
    expect_scripts: tuple[str, ...] | None = None
    note: str = ""


CASES: tuple[GoldenCase, ...] = (
    # --- §75 script coverage: neutral, synthetic technical phrases, not names ---
    GoldenCase("turkish", "Sistem güncellemesi başarılı oldu", expect_scripts=("Latin",)),
    GoldenCase(
        "turkish_dotless_i",
        "IŞIK ışık sınır",
        expect_scripts=("Latin",),
        note="dotted/dotless I round-trip, §75",
    ),
    GoldenCase("russian", "Система успешно обновлена сегодня", expect_scripts=("Cyrillic",)),
    GoldenCase("greek", "Το σύστημα ενημερώθηκε επιτυχώς", expect_scripts=("Greek",)),
    GoldenCase("arabic", "تم تحديث النظام بنجاح اليوم", expect_scripts=("Arabic",)),
    GoldenCase("hebrew", "המערכת עודכנה בהצלחה היום", expect_scripts=("Hebrew",)),
    GoldenCase("chinese_simplified", "系统今天已成功更新", expect_scripts=("Han",)),
    GoldenCase(
        "japanese_mixed",
        "システムは正常に更新されました",
        expect_scripts=("Han", "Hiragana", "Katakana"),
    ),
    GoldenCase("korean", "시스템이 성공적으로 업데이트되었습니다", expect_scripts=("Hangul",)),
    GoldenCase("hindi", "सिस्टम सफलतापूर्वक अपडेट हो गया", expect_scripts=("Devanagari",)),
    # --- §110 non-Latin + mixed-script edge cases ---
    GoldenCase(
        "mixed_latin_cyrillic_confusable",
        "hаrvest",  # Cyrillic 'а' among Latin
        expect_mixed_script=True,
        expect_scripts=("Cyrillic", "Latin"),
        note="classic UTS#39 confusable pair",
    ),
    GoldenCase(
        "mixed_greek_latin",
        "Ηello",  # Greek capital Eta + Latin
        expect_mixed_script=True,
        note="mixed-script detection, not auto-corrected",
    ),
    # --- §110 zero-width / invisible characters ---
    GoldenCase("zero_width_space", "hello\u200bworld", note="ZWSP removed"),
    GoldenCase("zero_width_joiner", "abc‍def", note="ZWJ preserved, not stripped (emoji-safety)"),
    GoldenCase("bom_prefix", "﻿hello", note="BOM stripped"),
    GoldenCase("soft_hyphen", "hyphen­ated", note="soft hyphen removed"),
    # --- §110 emoji (must survive intact, never stripped/corrupted) ---
    GoldenCase("emoji_simple", "great work 🎉🚀", note="emoji preserved"),
    GoldenCase(
        "emoji_zwj_sequence", "👨‍👩‍👧‍👦 family", note="ZWJ emoji sequence preserved as a unit"
    ),
    # --- §110 mixed normalization forms in one string ---
    GoldenCase(
        "mixed_nfc_nfd_forms",
        "café and café",  # first café is NFD, second is NFC
        note="both forms compose to the same NFC result",
    ),
    # --- §110 grapheme clusters (combining marks stacking) ---
    GoldenCase("stacked_combining_marks", "ȩ́", note="e + acute + cedilla"),
    # --- §110 bidi text ---
    GoldenCase(
        "bidi_arabic_latin_mixed",
        "Order #12345 تم الشحن",
        expect_mixed_script=True,
        note="RTL/LTR mixed content",
    ),
    # --- punctuation-heavy / whitespace edge cases ---
    GoldenCase(
        "full_width_punctuation",
        "こんにちは、世界！",
        note="fullwidth comma/exclamation preserved under NFC",
    ),
    GoldenCase(
        "tabs_and_newlines",
        "line one\tindented\nline two",
        note="newline preserved, tab collapsed",
    ),
)


@pytest.fixture(scope="module")
def normalizer() -> GenericTextNormalizer:
    return GenericTextNormalizer(DictionaryLoader(_DICT_ROOT), include_fingerprints=True)


@pytest.fixture(scope="module")
def ctx() -> NormalizationContext:
    return NormalizationContext(field_name="notes", semantic_type=FieldSemanticType.FREE_TEXT)


@pytest.mark.golden
@pytest.mark.parametrize("case", CASES, ids=[c.label for c in CASES])
def test_golden_case_never_fails_and_preserves_original(
    normalizer: GenericTextNormalizer, ctx: NormalizationContext, case: GoldenCase
) -> None:
    result = normalizer.normalize(case.value, ctx)

    assert result.normalization_status is not NormalizationStatus.FAILED, case.note
    assert result.errors == []
    assert result.original == case.value, "original must be byte-preserved regardless of script"
    assert result.display is not None
    assert result.display != "", "no golden case should normalize down to empty"


@pytest.mark.golden
@pytest.mark.parametrize("case", CASES, ids=[c.label for c in CASES])
def test_golden_case_is_idempotent(
    normalizer: GenericTextNormalizer, ctx: NormalizationContext, case: GoldenCase
) -> None:
    """Source.txt §71: normalize(normalize(x)) == normalize(x) — checked
    here by feeding the first pass's `display` output back in as a new
    `original` and confirming the second pass's `display` is identical."""
    first = normalizer.normalize(case.value, ctx)
    second = normalizer.normalize(first.display, ctx)
    assert second.display == first.display, case.note


@pytest.mark.golden
@pytest.mark.parametrize(
    "case", [c for c in CASES if c.expect_scripts is not None], ids=lambda c: c.label
)
def test_golden_case_script_detection(
    normalizer: GenericTextNormalizer, ctx: NormalizationContext, case: GoldenCase
) -> None:
    assert case.expect_scripts is not None  # parametrize already filtered on this
    result = normalizer.normalize(case.value, ctx)
    detected = set(result.structured.get("scripts_present", []))
    assert detected == set(case.expect_scripts), (
        f"{case.label}: expected scripts {case.expect_scripts}, got {sorted(detected)}"
    )


@pytest.mark.golden
@pytest.mark.parametrize("case", [c for c in CASES if c.expect_mixed_script], ids=lambda c: c.label)
def test_golden_case_mixed_script_flagged(
    normalizer: GenericTextNormalizer, ctx: NormalizationContext, case: GoldenCase
) -> None:
    result = normalizer.normalize(case.value, ctx)
    assert result.structured["mixed_script_detected"] is True, case.note


@pytest.mark.golden
def test_zero_width_characters_actually_removed(
    normalizer: GenericTextNormalizer, ctx: NormalizationContext
) -> None:
    result = normalizer.normalize("hello\u200bworld", ctx)
    assert result.display == "helloworld"


@pytest.mark.golden
def test_bom_actually_stripped(
    normalizer: GenericTextNormalizer, ctx: NormalizationContext
) -> None:
    result = normalizer.normalize("﻿hello", ctx)
    assert result.display == "hello"


@pytest.mark.golden
def test_emoji_zwj_sequence_survives_intact(
    normalizer: GenericTextNormalizer, ctx: NormalizationContext
) -> None:
    value = "👨‍👩‍👧‍👦 family"
    result = normalizer.normalize(value, ctx)
    assert result.display is not None
    assert "👨‍👩‍👧‍👦" in result.display


@pytest.mark.golden
def test_mixed_normalization_forms_converge_to_same_nfc(
    normalizer: GenericTextNormalizer, ctx: NormalizationContext
) -> None:
    nfd_form = normalizer.normalize("café", ctx)
    nfc_form = normalizer.normalize("café", ctx)
    assert nfd_form.display == nfc_form.display


@pytest.mark.golden
def test_tabs_collapse_but_newlines_are_preserved(
    normalizer: GenericTextNormalizer, ctx: NormalizationContext
) -> None:
    result = normalizer.normalize("line one\tindented\nline two", ctx)
    assert result.display is not None
    assert "\n" in result.display
    assert "\t" not in result.display
