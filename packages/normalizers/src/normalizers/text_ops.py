"""Stateless Unicode/text primitive operations — Source.txt §9-§19, §56.

Every function here is a pure `(value) -> (output, changed)` (or a small
variant returning extra diagnostic data) operation with no knowledge of
`NormalizedValue`, trace assembly, or the `Normalizer` protocol — those
concerns live in `unicode_normalizer.py` and `generic_text.py`, which
compose these into a traced pipeline. Keeping this layer pure makes each
operation independently unit-testable and keeps the reversibility
classification in `OPERATIONS` (below) auditable in one place.
"""

# This file's entire purpose is matching specific Unicode punctuation/
# space/invisible characters (curly quotes, en/em dash, NBSP variants,
# ZWSP/ZWJ/ZWNJ, ...) — ruff's RUF001 "ambiguous character, did you mean
# ASCII X" is exactly backwards here: these ARE the intended, correctly-
# typed characters, not typos.
# ruff: noqa: RUF001

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyascii as anyascii_lib
import ftfy
import icu
import regex
from charset_normalizer import from_bytes as charset_from_bytes
from normcore.enums import Reversibility
from normcore.unicode_policy import UnicodeForm

if TYPE_CHECKING:
    from collections.abc import Callable

_ICU_NORMALIZERS: dict[UnicodeForm, icu.Normalizer2] = {
    UnicodeForm.NFC: icu.Normalizer2.getNFCInstance(),
    UnicodeForm.NFD: icu.Normalizer2.getNFDInstance(),
    UnicodeForm.NFKC: icu.Normalizer2.getNFKCInstance(),
    UnicodeForm.NFKD: icu.Normalizer2.getNFKDInstance(),
}

# Characters removed by strip_control_chars: NUL, BOM, zero-width space,
# soft hyphen, word joiner. Source.txt §18 also names ZWJ/ZWNJ as
# characters to *detect* -- but both are load-bearing, not noise: ZWJ
# joins emoji into a single glyph (e.g. the "family" emoji is four base
# emoji joined by three ZWJs -- stripping them un-joins it into four
# separate emoji, a real regression caught by the M2 golden corpus) and
# both ZWJ/ZWNJ control ligature/joining behavior in Arabic, Indic, and
# other scripts. "Remove only where safe" (§18) means ZWJ/ZWNJ are left
# alone by a script-agnostic generic normalizer; a future script-aware
# adapter could safely strip them in contexts it can prove are non-emoji,
# non-orthographic runs, but that is out of scope here. General Cc
# controls (except \t\n\r, which whitespace ops own) and any other Cf
# format character not in this explicit set are likewise left alone.
_EXPLICIT_INVISIBLE_CHARS = frozenset("\x00﻿\u200b­⁠")

_WHITESPACE_RUN_RE = regex.compile(r"[^\S\n]+")
_NON_BREAKING_SPACE_CHARS = frozenset("   ")

# Conservative punctuation normalization table: curly quotes/dashes to
# their plain-ASCII equivalents. Deliberately small — §14 requires this be
# field-specific and dictionary-driven, not a blanket global table; this
# is the safe, narrow default GenericTextNormalizer applies before any
# field-specific dictionary layers on top (M6).
_PUNCTUATION_MAP: dict[str, str] = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "…": "...",
}

_COMBINING_MARK_CATEGORY_PREFIX = "M"  # Mn, Mc, Me


@dataclass(frozen=True)
class OperationSpec:
    """Static reversibility/lossy metadata for one named text operation —
    the single place these claims are declared, so ADR-012's empirical
    verification (tests/golden/test_reversibility.py) has one source to
    check against."""

    operation: str
    claimed_reversibility: Reversibility
    lossy: bool
    library: str
    library_version: str


def _icu_version() -> str:
    return str(icu.ICU_VERSION)


OPERATIONS: dict[str, OperationSpec] = {
    "text_repair": OperationSpec(
        "text_repair", Reversibility.LOSSY, True, "ftfy", ftfy.__version__
    ),
    "unicode_normalize_nfc": OperationSpec(
        "unicode_normalize_nfc", Reversibility.REVERSIBLE, False, "PyICU", _icu_version()
    ),
    "unicode_normalize_nfd": OperationSpec(
        "unicode_normalize_nfd", Reversibility.REVERSIBLE, False, "PyICU", _icu_version()
    ),
    "unicode_normalize_nfkc": OperationSpec(
        "unicode_normalize_nfkc", Reversibility.LOSSY, True, "PyICU", _icu_version()
    ),
    "unicode_normalize_nfkd": OperationSpec(
        "unicode_normalize_nfkd", Reversibility.LOSSY, True, "PyICU", _icu_version()
    ),
    "strip_control_chars": OperationSpec(
        "strip_control_chars", Reversibility.LOSSY, True, "normalizers", "0.1.0"
    ),
    "normalize_nbsp": OperationSpec(
        "normalize_nbsp", Reversibility.LOSSY, True, "normalizers", "0.1.0"
    ),
    "collapse_whitespace": OperationSpec(
        "collapse_whitespace", Reversibility.LOSSY, True, "normalizers", "0.1.0"
    ),
    "trim": OperationSpec("trim", Reversibility.LOSSY, True, "normalizers", "0.1.0"),
    "normalize_punctuation": OperationSpec(
        "normalize_punctuation", Reversibility.LOSSY, True, "normalizers", "0.1.0"
    ),
    "casefold": OperationSpec("casefold", Reversibility.LOSSY, True, "PyICU", _icu_version()),
    "strip_diacritics": OperationSpec(
        "strip_diacritics", Reversibility.LOSSY, True, "PyICU", _icu_version()
    ),
    "transliterate_ascii": OperationSpec(
        "transliterate_ascii", Reversibility.LOSSY, True, "anyascii", anyascii_lib.__version__
    ),
}


def detect_encoding_confidence(value: str) -> tuple[str | None, float]:
    """Diagnostic-only: re-encodes `value` as UTF-8 and asks
    charset-normalizer how confidently that byte sequence would itself be
    identified as UTF-8. A low-confidence result on already-decoded text
    is a signal (not proof) that upstream decoding may have used the
    wrong codec before this string ever reached us — distinct from
    mojibake baked into an otherwise-correctly-decoded string, which
    `repair_mojibake` below handles. Returns (best_guess_encoding,
    confidence in [0, 1]); (None, 0.0) if charset-normalizer finds no
    plausible match at all.
    """
    if not value:
        return None, 1.0
    matches = charset_from_bytes(value.encode("utf-8"))
    best = matches.best()
    if best is None:
        return None, 0.0
    # charset-normalizer exposes a "chaos"/coherence-derived ratio via
    # `.coherence`; a well-formed UTF-8 re-encode of an already-str value
    # should score at or near 1.0 coherence when correctly identified as
    # utf_8. We report that directly rather than inventing our own metric.
    confidence = 1.0 - best.chaos
    return best.encoding, max(0.0, min(1.0, confidence))


_MAX_REPAIR_PASSES = 5


def repair_mojibake(value: str) -> tuple[str, bool, list[str]]:
    """Evidence-gated mojibake repair per ADR-002. Returns (output,
    changed, explanations) — explanations is ftfy's own list of the exact
    fixes it applied (possibly empty even when `changed` is True in the
    rare case ftfy normalizes without an explanation entry, though in
    practice `changed` and non-empty `explanations` coincide).

    Iterates `ftfy.fix_and_explain` to a fixed point (bounded) rather than
    applying it once: a single pass is not guaranteed idempotent on
    adversarial or multiply-mis-encoded input — Hypothesis found a
    concrete counterexample during M2 property testing where one pass of
    already-"fixed" text still looked like mojibake to ftfy's own
    heuristics and got transformed again into a THIRD, different value.
    Looping to a fixed point (or `_MAX_REPAIR_PASSES` passes, whichever
    comes first — bounded so genuinely pathological input can never hang
    the pipeline) makes `repair_mojibake` idempotent by construction,
    which downstream code (GenericTextNormalizer, the idempotency
    property test) depends on.
    """
    current = value
    all_explanation_lines: list[str] = []
    changed_overall = False
    for _ in range(_MAX_REPAIR_PASSES):
        fixed, explanation = ftfy.fix_and_explain(current)
        if fixed == current:
            break
        changed_overall = True
        if explanation:
            all_explanation_lines.extend(str(step) for step in explanation)
        current = fixed
    return current, changed_overall, all_explanation_lines


def unicode_normalize(value: str, form: UnicodeForm) -> tuple[str, bool]:
    normalizer = _ICU_NORMALIZERS[form]
    output = normalizer.normalize(value)
    return output, output != value


def strip_control_chars(value: str) -> tuple[str, bool]:
    output = "".join(ch for ch in value if ch not in _EXPLICIT_INVISIBLE_CHARS)
    return output, output != value


def normalize_nbsp(value: str) -> tuple[str, bool]:
    output = "".join(" " if ch in _NON_BREAKING_SPACE_CHARS else ch for ch in value)
    return output, output != value


def collapse_whitespace(value: str) -> tuple[str, bool]:
    """Collapses runs of horizontal whitespace to a single space. Newlines
    are left alone here — a free-text field's internal line breaks are
    semantically meaningful and collapsing them is a separate, explicit
    per-field decision, not part of the safe default."""
    output = _WHITESPACE_RUN_RE.sub(" ", value)
    return output, output != value


def trim(value: str) -> tuple[str, bool]:
    output = value.strip()
    return output, output != value


# List and path separators, plus the whitespace that usually comes with
# them. NOT ".", which is load-bearing in "U.S." and "U.K.", and not "-",
# which is inside real names ("Guinea-Bissau", "Timor-Leste").
_ENCLOSING_SEPARATORS = " \t\n\r/\\,;:|" + "\u00b7\u2022\u2219"


def strip_enclosing_separators(value: str) -> tuple[str, bool]:
    """Drop list/path separators from BOTH ENDS of a value.

    A LOOKUP KEY transform, like `strip_diacritics`: for values that are
    supposed to BE a code or a name, a separator at the edge is packaging
    left over from whatever produced the cell, not part of the value.
    Measured on real sources, `/türkiye` (a URL path fragment that reached a
    country column) and `, , , , United Kingdom` (a list that lost all but
    one element) were both unresolvable purely because of their edges.

    Only the ends. An interior separator is genuinely ambiguous — `US, GB`
    stays unresolved rather than becoming a guess about which one was meant
    — and that is the whole difference between this and splitting.
    """
    output = value.strip(_ENCLOSING_SEPARATORS)
    return output, output != value


def normalize_punctuation(value: str) -> tuple[str, bool]:
    output = "".join(_PUNCTUATION_MAP.get(ch, ch) for ch in value)
    return output, output != value


def casefold(value: str, locale: str | None = None) -> tuple[str, bool]:
    """ICU locale-aware casefold — correctly handles Turkish dotted/
    dotless I, Lithuanian, and Greek final sigma when `locale` names a
    relevant BCP-47 tag, unlike stdlib `str.casefold()` which has no
    locale concept at all."""
    icu_locale = icu.Locale(locale) if locale else icu.Locale.getRoot()
    output = str(icu.UnicodeString(value).foldCase())
    if locale and locale.startswith("tr"):
        # ICU's generic foldCase() does not apply Turkish dotted-I rules
        # (those live on toLower/toUpper with an explicit locale); apply
        # locale-aware lowercasing first, then foldCase the result, so
        # Turkish input still folds consistently under this operation.
        output = str(icu.UnicodeString(value).toLower(icu_locale).foldCase())
    return output, output != value


def strip_diacritics(value: str) -> tuple[str, bool]:
    """NFKD-decompose then drop combining marks (Unicode category M*).
    Always a DERIVED, opt-in view (`accent_stripped`) — never overwrites
    `display`, per Source.txt §15's explicit prohibition on universal
    accent stripping."""
    decomposed = _ICU_NORMALIZERS[UnicodeForm.NFKD].normalize(value)
    output = "".join(
        ch
        for ch in decomposed
        if not unicodedata.category(ch).startswith(_COMBINING_MARK_CATEGORY_PREFIX)
    )
    output = _ICU_NORMALIZERS[UnicodeForm.NFC].normalize(output)
    return output, output != value


def transliterate_ascii(value: str) -> tuple[str, bool]:
    """anyascii (ISC-licensed) lossy ASCII transliteration — Source.txt
    §16. Always a DERIVED, opt-in view (`ascii`); never substitutes for
    the Unicode representation."""
    output = anyascii_lib.anyascii(value)
    return output, output != value


@dataclass(frozen=True)
class ConfusableReport:
    confusable_skeleton: str
    scripts_present: tuple[str, ...]
    mixed_script_detected: bool


_spoof_checker: icu.SpoofChecker | None = None


def _get_spoof_checker() -> icu.SpoofChecker:
    global _spoof_checker  # noqa: PLW0603 - module-level lazy singleton, ICU object is expensive to construct
    if _spoof_checker is None:
        checker = icu.SpoofChecker()
        checker.setChecks(
            icu.USpoofChecks.SINGLE_SCRIPT_CONFUSABLE
            | icu.USpoofChecks.MIXED_SCRIPT_CONFUSABLE
            | icu.USpoofChecks.WHOLE_SCRIPT_CONFUSABLE
        )
        _spoof_checker = checker
    return _spoof_checker


def analyze_confusables(value: str) -> ConfusableReport:
    """Source.txt §17: additive diagnostic fields only. Never triggers
    automatic character substitution — the caller only ever *records*
    this, it does not feed back into `display`/`comparison`."""
    checker = _get_spoof_checker()
    skeleton = checker.getSkeleton(0, value) if value else ""

    scripts: set[str] = set()
    for ch in value:
        if ch.isspace() or not ch.isalpha():
            continue
        script_code = icu.Script.getScript(ord(ch))
        scripts.add(script_code.getName())
    # COMMON and INHERITED are shared by every script (digits, punctuation,
    # combining marks) and never indicate genuine script-mixing on their own.
    meaningful_scripts = scripts - {"Common", "Inherited"}

    return ConfusableReport(
        confusable_skeleton=skeleton,
        scripts_present=tuple(sorted(meaningful_scripts)),
        mixed_script_detected=len(meaningful_scripts) > 1,
    )


def openrefine_fingerprint(value: str) -> str:
    """OpenRefine's `fingerprint` key-collision algorithm: casefold, strip
    punctuation, collapse whitespace, alphabetically sort whitespace-
    separated tokens, dedupe, rejoin. Deterministic and fully specified —
    Source.txt §19/§56 names this as a standard derived key, opt-in per
    field, never the primary comparison value."""
    ascii_form = anyascii_lib.anyascii(value)
    folded = ascii_form.casefold()
    stripped = "".join(ch for ch in folded if ch.isalnum() or ch.isspace())
    tokens = sorted(set(stripped.split()))
    return " ".join(tokens)


def openrefine_ngram_fingerprint(value: str, n: int = 1) -> str:
    """OpenRefine's `ngram-fingerprint`: casefold, strip punctuation,
    remove ALL whitespace, take sorted unique character n-grams, rejoin.
    Distinct from `openrefine_fingerprint` in that it is whitespace-
    insensitive (catches token-order AND token-boundary variation)."""
    ascii_form = anyascii_lib.anyascii(value)
    folded = ascii_form.casefold()
    stripped = "".join(ch for ch in folded if ch.isalnum())
    if len(stripped) < n:
        grams = {stripped} if stripped else set()
    else:
        grams = {stripped[i : i + n] for i in range(len(stripped) - n + 1)}
    return "".join(sorted(grams))


_OP_FUNCTIONS: dict[str, Callable[[str], tuple[str, bool]]] = {
    "unicode_normalize_nfc": lambda v: unicode_normalize(v, UnicodeForm.NFC),
    "unicode_normalize_nfd": lambda v: unicode_normalize(v, UnicodeForm.NFD),
    "unicode_normalize_nfkc": lambda v: unicode_normalize(v, UnicodeForm.NFKC),
    "unicode_normalize_nfkd": lambda v: unicode_normalize(v, UnicodeForm.NFKD),
    "strip_control_chars": strip_control_chars,
    "normalize_nbsp": normalize_nbsp,
    "collapse_whitespace": collapse_whitespace,
    "trim": trim,
    "normalize_punctuation": normalize_punctuation,
    "strip_diacritics": strip_diacritics,
    "transliterate_ascii": transliterate_ascii,
}


def apply_named_operation(operation: str, value: str) -> tuple[str, bool]:
    """Public dispatch into `_OP_FUNCTIONS` for callers (UnicodeNormalizer)
    that walk the default step order by name rather than calling each
    function directly."""
    return _OP_FUNCTIONS[operation](value)


def inverse_unicode_form(form: UnicodeForm) -> UnicodeForm | None:
    """NFC and NFD are each other's structural inverse for values that
    were canonically composable/decomposable in the first place — used
    only by the empirical reversibility test (tests/golden/
    test_reversibility.py), never by the runtime pipeline."""
    return {UnicodeForm.NFC: UnicodeForm.NFD, UnicodeForm.NFD: UnicodeForm.NFC}.get(form)
