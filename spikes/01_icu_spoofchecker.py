"""Spike: PyICU normalization forms + SpoofChecker (Source.txt §11, §17).

Proves:
- NFC/NFD/NFKC/NFKD all work and behave differently on the same input.
- ICU SpoofChecker detects a Cyrillic-for-Latin confusable substitution
  (the classic "harvest" vs "hаrvest" example, "а" is Cyrillic U+0430).
- Locale-aware case mapping handles Turkish dotted/dotless I correctly,
  which stdlib `str.lower()`/`str.upper()` gets wrong.

Run: uv run python spikes/01_icu_spoofchecker.py
"""

from __future__ import annotations

import sys

import icu

# Windows consoles default to a legacy codepage (cp1252) that cannot encode
# most of the Unicode text this spike prints. Force UTF-8 stdout so the
# spike's output reflects the actual normalization behavior, not a console
# encoding artifact. Production code paths never print to a console this
# way — this is spike-only.
sys.stdout.reconfigure(encoding="utf-8")


def demo_normalization_forms() -> None:
    # "café" with a combining acute accent (NFD-style) vs precomposed (NFC-style)
    precomposed = "café"  # é as one codepoint
    decomposed = "café"  # e + combining acute accent

    print("=== Unicode normalization forms ===")
    print(f"precomposed bytes: {[hex(ord(c)) for c in precomposed]}")
    print(f"decomposed  bytes: {[hex(ord(c)) for c in decomposed]}")

    nfc = icu.Normalizer2.getNFCInstance()
    nfd = icu.Normalizer2.getNFDInstance()
    nfkc = icu.Normalizer2.getNFKCInstance()
    nfkd = icu.Normalizer2.getNFKDInstance()

    assert nfc.normalize(decomposed) == precomposed
    assert nfd.normalize(precomposed) == decomposed
    print(f"NFC(decomposed)  == precomposed: {nfc.normalize(decomposed) == precomposed}")
    print(f"NFD(precomposed) == decomposed:  {nfd.normalize(precomposed) == decomposed}")

    # NFKC/NFKD compatibility example: full-width digit vs ASCII digit
    fullwidth_digit = "１２３"  # "１２３"
    print(
        f"NFKC('１２３') = {nfkc.normalize(fullwidth_digit)!r} (compatibility folds full-width to ASCII)"
    )
    print(
        f"NFC('１２３')  = {nfc.normalize(fullwidth_digit)!r} (canonical form leaves it full-width — this is why we never apply NFKC to identifiers by default, see ADR-001)"
    )
    print(f"NFKD('１２３') = {nfkd.normalize(fullwidth_digit)!r}")


def demo_locale_aware_case_mapping() -> None:
    print("\n=== Locale-aware case mapping (Turkish dotted/dotless I) ===")
    turkish_locale = icu.Locale("tr_TR")
    root_locale = icu.Locale.getRoot()

    word = "İstanbul"  # capital dotted I
    lowered_root = icu.UnicodeString(word).toLower(root_locale)
    lowered_turkish = icu.UnicodeString(word).toLower(turkish_locale)

    print(f"'{word}'.lower() [root/English rules]  = '{lowered_root}'")
    print(f"'{word}'.lower() [tr_TR rules]          = '{lowered_turkish}'")
    print(f"stdlib str.lower() (locale-unaware)     = '{word.lower()}'")
    print(
        "Turkish 'İ' should lower to dotted 'i' under tr_TR rules, and to 'i̇' "
        "(i + combining dot above) or plain 'i' depending on ICU version under root — "
        "stdlib gets this wrong because Python's str.lower() has no locale concept at all."
    )


def demo_spoofchecker_confusables() -> None:
    print("\n=== ICU SpoofChecker: confusable detection (Source.txt §17) ===")
    checker = icu.SpoofChecker()
    # Constants live on icu.USpoofChecks (the wrapped C enum), not on the
    # SpoofChecker class itself — confirmed empirically against PyICU 2.16.2
    # (this was not obvious from PyICU's own docs, which mostly mirror the
    # ICU4J Javadoc's class-level constant layout).
    checker.setChecks(
        icu.USpoofChecks.SINGLE_SCRIPT_CONFUSABLE
        | icu.USpoofChecks.MIXED_SCRIPT_CONFUSABLE
        | icu.USpoofChecks.WHOLE_SCRIPT_CONFUSABLE
    )

    latin = "harvest"
    # Replace the Latin 'a' (U+0061) with Cyrillic 'а' (U+0430) — visually identical
    mixed_script_confusable = "hаrvest"

    print(f"Latin string:          {latin!r}")
    print(f"Confusable string:     {mixed_script_confusable!r} (contains Cyrillic 'а' U+0430)")

    skeleton_latin = checker.getSkeleton(0, latin)
    skeleton_confusable = checker.getSkeleton(0, mixed_script_confusable)
    print(f"UTS#39 skeleton(latin)      = {skeleton_latin!r}")
    print(f"UTS#39 skeleton(confusable) = {skeleton_confusable!r}")
    print(f"Skeletons match (=> confusable per UTS#39): {skeleton_latin == skeleton_confusable}")

    result = checker.areConfusable(latin, mixed_script_confusable)
    print(f"areConfusable() bitmask (nonzero => confusable): {result}")

    # Also demonstrate mixed-script detection on the confusable string alone
    check_result = checker.check(mixed_script_confusable)
    print(f"check() on confusable string alone -> issues bitmask: {check_result}")

    print(
        "\nPer Source.txt §17: we NEVER auto-substitute characters based on this. "
        "The engine only emits confusable_skeleton / confusable_detected / "
        "mixed_script_detected as diagnostic fields — decision-making stays "
        "with the downstream consumer (or a human), never automatic."
    )


if __name__ == "__main__":
    print(f"ICU_VERSION={icu.ICU_VERSION}  UNICODE_VERSION={icu.UNICODE_VERSION}")
    demo_normalization_forms()
    demo_locale_aware_case_mapping()
    demo_spoofchecker_confusables()
