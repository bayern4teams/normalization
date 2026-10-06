"""NameNormalizer — Source.txt Phase 4 (§20-§25, §76).

Wraps `nameparser.HumanName` in a deterministic adapter bound to our own
versioned honorific/suffix dictionaries. Two things `nameparser` does NOT
do out of the box, which this module exists specifically to add:

1. **Ambiguity preservation (§21, §76).** `HumanName("Smith John")` (a
   bare two-token name, no comma) silently guesses first="Smith",
   last="John" — exactly the kind of unstated assumption §21 forbids.
   This module detects that shape and returns `AMBIGUOUS` with both
   candidate interpretations in `structured`, rather than trusting
   nameparser's default guess.
2. **Nicknames are explicitly NOT implemented (§24).** No Robert->Bob
   mapping exists or is attempted; `structured["nickname"]` is always
   `None` in this milestone. Enabling it requires a curated, versioned,
   locale-aware dictionary — out of scope here by design, not an
   oversight.

Title is never treated as identity evidence (§22): it is stored
separately in `structured` and never feeds `comparison`/`search`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import blake3
import icu
import jellyfish
import phonetics
import pyarrow as pa
from nameparser import HumanName
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    Reversibility,
)
from normcore.errors import NormalizerFailure
from normcore.models import NormalizedValue
from normcore.pii import character_class_mask, content_hash
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome
from normcore.trace import TraceStep
from normcore.unicode_policy import UnicodeForm
from normdict.loader import DictionaryLoader, DictionaryNotFoundError

from normalizers import _bmpm, text_ops
from normalizers.unicode_normalizer import (
    UnicodeNormalizer,
    UnicodeProcessingOptions,
    UnicodeProcessingResult,
    build_unicode_trace,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_NAME_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

_VERSION = "0.1.0"

_SUPPORTED_TYPES = frozenset(
    {
        FieldSemanticType.PERSON_NAME,
        FieldSemanticType.GIVEN_NAME,
        FieldSemanticType.FAMILY_NAME,
    }
)


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_NAME_PARSE_STEP = _StaticStepSpec(
    "name.parse_western", "name.parse_western", Reversibility.LOSSLESS, False
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (
    *(
        _StaticStepSpec(name, spec.operation, spec.claimed_reversibility, spec.lossy)
        for name, spec in text_ops.OPERATIONS.items()
    ),
    _NAME_PARSE_STEP,
)


def _load_dictionary(loader: DictionaryLoader, dictionary_id: str) -> dict[str, str]:
    try:
        dictionary = loader.load(dictionary_id)
    except DictionaryNotFoundError:
        return {}
    return {str(k).casefold(): str(v) for k, v in dictionary.entries.items()}


def _legacy_codes(value: str) -> dict[str, str] | None:
    """jellyfish's Soundex/NYSIIS/Metaphone/Match-Rating-Codex all expect
    Latin-alphabet input; the caller only passes Latin-script names (after
    anyascii folds diacritics, a lossy, best-effort step: the codes are a
    DERIVED diagnostic field, never the canonical name).
    """
    ascii_form, _ = text_ops.transliterate_ascii(value)
    letters_only = "".join(ch for ch in ascii_form if ch.isalpha())
    if not letters_only:
        return None
    return {
        "soundex": jellyfish.soundex(letters_only),
        "nysiis": jellyfish.nysiis(letters_only),
        "metaphone": jellyfish.metaphone(letters_only),
        "match_rating_codex": jellyfish.match_rating_codex(letters_only),
    }


def _scripts(value: str) -> frozenset[str]:
    """ICU names of the scripts of the value's letters (Common/Inherited ignored)."""
    names = {icu.Script.getScript(ord(ch)).getName() for ch in value if ch.isalpha()}
    return frozenset(names - {"Common", "Inherited"})


_BEIDER_MORSE_MAX_CHARS = 255  # ponytail: measured bound, see _language_aware_codes


def _language_aware_codes(value: str) -> dict[str, object]:
    """Double Metaphone (of the anyascii form, lossy and language-agnostic) and
    Beider-Morse (of the name as written) as lists of alternative codes."""
    ascii_form, _ = text_ops.transliterate_ascii(value)
    double = [c for c in phonetics.dmetaphone("".join(filter(str.isalpha, ascii_form))) if c]
    codes: dict[str, object] = {"double_metaphone": double}
    # ponytail: Beider-Morse output and time grow super-linearly with length
    # (measured: 255 chars ~15 ms / ~25 KB of codes, 7k chars 3.8 s / 2.4 MB,
    # identical to Commons Codec), so a longer value, which is no name, gets no
    # beider_morse key. Upgrade path: encode per token with a total budget.
    if len(value) <= _BEIDER_MORSE_MAX_CHARS:
        codes["beider_morse"] = list(_bmpm.encode(value))
    return {k: v for k, v in codes.items() if v}


def _phonetic_fields(value: str) -> dict[str, object]:
    """The `phonetic*` / `script` entries of `structured` for one name (D11).

    * Latin script: the four legacy keys (unchanged) plus the language-aware
      `double_metaphone` and `beider_morse` keys (lists of alternative codes;
      Beider-Morse's own language guess only selects rules, no language is
      ever reported).
    * Cyrillic or Arabic/Persian script: `phonetic_status = "not_applicable"`
      (the Anglo-centric keys do not describe it) and the two language-aware
      keys; Beider-Morse's rule files read these scripts directly.
    * Anything else, or mixed scripts: `not_applicable` and the script, no key.
      ponytail: Han/Hangul/Devanagari/Thai readings are polyphonic (one
      character, several readings chosen by the language), so no key is
      emitted rather than a guessed one. Upgrade path: a pinyin/romaji/
      transliteration source plus the language to read the name in.
    """
    scripts = _scripts(value)
    if not scripts:
        return {}
    if scripts == {"Latin"}:
        phonetic = {**(_legacy_codes(value) or {}), **_language_aware_codes(value)}
        return {"phonetic": phonetic} if phonetic else {}
    fields: dict[str, object] = {
        "phonetic_status": "not_applicable",
        "script": "+".join(sorted(scripts)),
    }
    if scripts in ({"Cyrillic"}, {"Arabic"}) and (codes := _language_aware_codes(value)):
        fields["phonetic"] = codes
    return fields


class NameNormalizer:
    """Registered for PERSON_NAME, GIVEN_NAME, FAMILY_NAME."""

    name = "NameNormalizer"
    supported_types = _SUPPORTED_TYPES

    def __init__(self, dictionary_loader: DictionaryLoader) -> None:
        self._unicode = UnicodeNormalizer()
        self._honorifics = _load_dictionary(dictionary_loader, "honorifics.common")
        self._suffixes = _load_dictionary(dictionary_loader, "name-suffixes.common")

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        options = UnicodeProcessingOptions(
            form=UnicodeForm.NFC, include_accent_stripped=True, include_confusables=False
        )
        try:
            unicode_result = self._unicode.process(value, options)
        except Exception as exc:
            msg = f"UnicodeNormalizer failed on field {ctx.field_name!r}: {exc}"
            raise NormalizerFailure(msg, operation="unicode_process") from exc

        cleaned = unicode_result.final_value
        if cleaned.strip() == "":
            # only invisible/control characters (a soft hyphen): same as "", or
            # re-normalizing the '' display would disagree with this pass
            return _missing(value, MissingKind.EMPTY_STRING, ctx)
        trace = build_unicode_trace(unicode_result, enabled=ctx.include_trace)

        if ctx.semantic_type in (FieldSemanticType.GIVEN_NAME, FieldSemanticType.FAMILY_NAME):
            return _normalize_single_component(value, cleaned, trace, unicode_result, ctx)

        return self._normalize_person_name(value, cleaned, trace, unicode_result, ctx)

    def _normalize_person_name(
        self,
        original: str,
        cleaned: str,
        trace: list[TraceStep],
        unicode_result: UnicodeProcessingResult,
        ctx: NormalizationContext,
    ) -> NormalizedValue:
        parsed = HumanName(cleaned)
        title_raw = str(parsed.title) or None
        suffix_raw = str(parsed.suffix) or None
        title_canonical = self._honorifics.get(_strip_dots(title_raw)) if title_raw else None
        suffix_canonical = self._suffixes.get(_strip_dots(suffix_raw)) if suffix_raw else None

        tokens = cleaned.split()
        ambiguous = len(tokens) == 2 and "," not in cleaned and not title_raw and not suffix_raw

        structured: dict[str, object] = {
            "title_raw": title_raw,
            "title_canonical": title_canonical,
            "suffix_raw": suffix_raw,
            "suffix_canonical": suffix_canonical,
            "nickname": None,  # §24: deliberately not implemented
        }

        if ambiguous:
            status = NormalizationStatus.AMBIGUOUS
            confidence = 0.5
            structured["candidates"] = [
                {"given_name": tokens[0], "family_name": tokens[1]},
                {"given_name": tokens[1], "family_name": tokens[0]},
            ]
            structured["given_name"] = None
            structured["middle_name"] = None
            structured["family_name"] = None
            phonetic_source = None
        else:
            status = NormalizationStatus.PARSED
            confidence = 1.0
            structured["given_name"] = str(parsed.first) or None
            structured["middle_name"] = str(parsed.middle) or None
            structured["family_name"] = str(parsed.last) or None
            phonetic_source = str(parsed.last) or None

        if phonetic_source:
            structured.update(_phonetic_fields(phonetic_source))

        trace = [*trace, _name_parse_trace_step(cleaned, changed=not ambiguous)]

        comparison, _ = text_ops.casefold(cleaned, ctx.locale)
        search_base = unicode_result.accent_stripped or cleaned
        search, _ = text_ops.casefold(search_base, ctx.locale)

        return NormalizedValue(
            original=original,
            display=cleaned,
            comparison=comparison,
            search=search,
            structured=structured,
            validation_status="AMBIGUOUS" if ambiguous else "PARSED",
            normalization_status=status,
            confidence=confidence,
            trace=trace,
            lossiness=(
                Reversibility.LOSSLESS if not ambiguous else Reversibility.PARTIALLY_REVERSIBLE
            ),
            profile_version="",
            env_id="",
            semantic_type=ctx.semantic_type,
            context_hash=ctx.context_hash,
        )

    def normalize_batch(self, values: pa.Array, ctx: NormalizationContext) -> pa.StructArray:
        results = [self.normalize(v, ctx) for v in values.to_pylist()]
        return pa.StructArray.from_arrays(
            [
                pa.array([r.original for r in results], type=pa.large_string()),
                pa.array([r.display for r in results], type=pa.large_string()),
                pa.array([r.comparison for r in results], type=pa.large_string()),
                pa.array([r.normalization_status.value for r in results], type=pa.large_string()),
            ],
            names=["original", "display", "comparison", "status"],
        )

    def validate(self, value: str | None, ctx: NormalizationContext) -> ValidationResult:
        result = self.normalize(value, ctx)
        if result.original_kind is not None:
            return ValidationOutcome(
                is_valid=False, status="MISSING", reason=result.original_kind.value
            )
        is_ambiguous = result.normalization_status is NormalizationStatus.AMBIGUOUS
        return ValidationOutcome(
            is_valid=not is_ambiguous,
            status=result.normalization_status.value,
            reason="ambiguous token order" if is_ambiguous else None,
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.normalization_status is NormalizationStatus.AMBIGUOUS:
            return ExplanationText(
                plain_language=(
                    "Could not determine which part of the name is the given name and which "
                    "is the family name without more context."
                ),
                technical=f"AMBIGUOUS: candidates={result.structured.get('candidates')}",
            )
        return ExplanationText(
            plain_language="Parsed into name components.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        if step_id.startswith("unicode_normalize_"):
            form_name = step_id.removeprefix("unicode_normalize_").upper()
            form = UnicodeForm(form_name)
            inverse_form = text_ops.inverse_unicode_form(form)
            if inverse_form is None:
                return None
            output, _ = text_ops.unicode_normalize(value, inverse_form)
            return output
        return None


def _normalize_single_component(
    original: str,
    cleaned: str,
    trace: list[TraceStep],
    unicode_result: UnicodeProcessingResult,
    ctx: NormalizationContext,
) -> NormalizedValue:
    field_key = "given_name" if ctx.semantic_type is FieldSemanticType.GIVEN_NAME else "family_name"
    comparison, _ = text_ops.casefold(cleaned, ctx.locale)
    search_base = unicode_result.accent_stripped or cleaned
    search, _ = text_ops.casefold(search_base, ctx.locale)
    structured: dict[str, object] = {field_key: cleaned, "nickname": None}
    structured.update(_phonetic_fields(cleaned))

    return NormalizedValue(
        original=original,
        display=cleaned,
        comparison=comparison,
        search=search,
        structured=structured,
        validation_status="VALID",
        normalization_status=(
            NormalizationStatus.NORMALIZED if cleaned != original else NormalizationStatus.UNCHANGED
        ),
        confidence=1.0,
        trace=trace,
        lossiness=Reversibility.LOSSLESS,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _missing(value: str | None, kind: MissingKind, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        original_kind=kind,
        normalization_status=NormalizationStatus.NORMALIZED,
        validation_status="MISSING",
        confidence=1.0,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _strip_dots(value: str) -> str:
    return value.strip().rstrip(".").casefold()


def _name_parse_trace_step(value: str, *, changed: bool) -> TraceStep:
    return TraceStep(
        step_order=99,
        rule_id="name.parse_western",
        operation="name.parse_western",
        params_hash=_NAME_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=False,
        reversibility=Reversibility.LOSSLESS,
        library="nameparser",
        library_version="2.x",
    )
