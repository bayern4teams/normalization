"""IdentifierNormalizer — Source.txt Phase 11 (§49-§51, §55).

Architecture per §51: generic operations (Unicode-digit normalization,
whitespace/case normalization) always apply; country-specific check-digit
validation via `python-stdnum` applies only to `TAX_ID` and only when the
installed library has exactly one tax-identifier module for `ctx.country`
(`tax_id_module_for`, discovered at run time from stdnum's own package
listing and module titles — no hand-kept country table). Every other case
is `unverifiable` (validation_status "UNKNOWN"), never a guessed verdict.
`CODE` is canonicalized only and never reports a check-digit verdict.
There is no global regex (§51's explicit prohibition).

Two hard invariants, both mandatory golden tests:
- Leading zeros are NEVER removed (§49): `"000123"` stays `"000123"`.
- An identifier is NEVER cast to numeric (§55): comparison/search stay
  string-typed, never `int(value)`.

Separator ambiguity (§111): `"AB-001"` and `"AB001"` are never silently
treated as equal — an internal separator is preserved in `comparison`,
and its presence is flagged `POTENTIAL_COLLISION` so a human can decide
whether the two forms should actually be merged.
"""

from __future__ import annotations

import functools
import importlib
import pkgutil
import re
import unicodedata
import uuid as uuid_module
from typing import TYPE_CHECKING, Protocol

import blake3
import pyarrow as pa
import stdnum
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)
from normcore.models import NormalizedValue
from normcore.pii import character_class_mask, content_hash
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome
from normcore.trace import TraceStep

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

_INTERNAL_SEPARATOR_RE = re.compile(r"[A-Za-z0-9][-][A-Za-z0-9]")


class _StdnumModule(Protocol):
    def is_valid(self, value: str) -> bool: ...
    def compact(self, value: str) -> str: ...


# Which stdnum module is a country's *tax identifier* comes from stdnum's own
# module titles (first docstring line, e.g. "NIF (Número de identificação
# fiscal, Portuguese VAT number)."): a module is a tax-id candidate when its
# title contains one of these words. Source: python-stdnum module titles,
# which say "VAT number" or "tax number"/"Taxpayer ..." in English for every
# fiscal identifier. This is the only hand-written table of the discovery.
# ponytail: English title words only; a module whose title says neither is not
# found (-> unverifiable). Ceiling: personal tax ids and VAT ids of one country
# are both matched, so such a country has several candidates and is unverifiable.
_TAX_ID_TITLE_TERMS = ("tax", "vat")
_TAX_ID_TITLE_RE = re.compile(r"\b(?:" + "|".join(_TAX_ID_TITLE_TERMS) + r")", re.IGNORECASE)

# Backward compatibility: the four countries this normalizer validated before
# discovery existed keep exactly their old module (their titles match several
# candidates, e.g. US ein/itin/ssn-style TINs), so their outputs stay unchanged.
# ponytail: hand map of four legacy modules; drop it once stdnum itself names
# "the" tax id per country (deferred alternative).
_LEGACY_TAX_ID_MODULE = {
    "US": "stdnum.us.ein",
    "GB": "stdnum.gb.vat",
    "DE": "stdnum.de.vat",
    "FR": "stdnum.fr.siren",
}


@functools.cache
def _stdnum_country_packages() -> dict[str, str]:
    """ISO-style country code -> stdnum package name, from stdnum's own package
    listing (a trailing underscore marks a Python keyword, e.g. `in_`)."""
    return {
        m.name.rstrip("_").upper(): m.name
        for m in pkgutil.iter_modules(stdnum.__path__)
        if m.ispkg and len(m.name.rstrip("_")) == 2 and m.name.rstrip("_").isalpha()
    }


def _title(mod: object) -> str:
    return (getattr(mod, "__doc__", None) or "").strip().partition("\n")[0]


@functools.cache
def _country_validators(package: str) -> tuple[str, ...]:
    """Every module of one stdnum country package that has an `is_valid`."""
    pkg = importlib.import_module(f"stdnum.{package}")
    return tuple(
        dotted
        for sub in pkgutil.iter_modules(pkg.__path__)
        if callable(
            getattr(
                importlib.import_module(dotted := f"{pkg.__name__}.{sub.name}"), "is_valid", None
            )
        )
    )


@functools.cache
def tax_id_module_for(country: str | None) -> tuple[str | None, tuple[str, ...]]:
    """(chosen stdnum module, candidate modules) for a country's tax id.

    Chosen is None when zero or several stdnum modules claim to be the tax
    identifier (`candidates` then lists the several, empty for zero) — never
    the first match. Discovery runs once per country (cached), not per value.
    """
    package = _stdnum_country_packages().get((country or "").upper())
    if package is None:
        return None, ()
    legacy = _LEGACY_TAX_ID_MODULE.get((country or "").upper())
    if legacy is not None:
        return legacy, (legacy,)
    candidates = [
        name
        for name in _country_validators(package)
        if _TAX_ID_TITLE_RE.search(_title(importlib.import_module(name)))
    ]
    return (candidates[0] if len(candidates) == 1 else None), tuple(candidates)


# ponytail: a country whose single title-matched module is a narrower id (AU TFN
# not ABN, UA RNTRC, LI PEID, ZA TIN) is still "classified"; the sibling rule
# below turns a number another module accepts into unverifiable, at the cost of
# running every sibling on a rejection. "EU" is a stdnum package, not an ISO
# country (multi-candidate, so harmless). Upgrade: a per-country tax-id choice
# from an authoritative source if one appears.
def _sibling_acceptors(module_name: str, cleaned: str) -> list[str]:
    """Other modules of the same stdnum country package that accept `cleaned`."""
    package = module_name.split(".")[1]
    accepting = []
    for name in _country_validators(package):
        if name == module_name:
            continue
        try:
            if importlib.import_module(name).is_valid(cleaned):
                accepting.append(name)
        except Exception:  # a sibling that cannot run does not vote
            continue
    return accepting


def _tax_id_verdict(
    cleaned: str, country: str | None
) -> tuple[bool | None, str | None, dict[str, object]]:
    """(check_digit_valid, identifier_type, verification info) for a TAX_ID.

    A verdict exists only when exactly one stdnum module applies and it ran;
    otherwise the info dict says why it is unverifiable (never a guess)."""
    cc = (country or "").upper()
    module_name, candidates = tax_id_module_for(cc)
    if module_name is None:
        if not cc:
            reason = "no country given"
        elif candidates:
            reason = "several tax-id validators for this country"
        else:
            reason = "no offline validator for this country"
        info: dict[str, object] = {"verification": "unverifiable", "verification_reason": reason}
        if candidates:
            info["candidate_modules"] = list(candidates)
        return None, None, info
    module: _StdnumModule = importlib.import_module(module_name)
    try:
        if module.is_valid(cleaned):
            return True, cc, {}
        # A tax-id title match is not proof that this is the only fiscal id of
        # the country: a number that another module of the same country accepts
        # is not "invalid", it is merely not decidable here.
        accepting = _sibling_acceptors(module_name, cleaned)
        if accepting:
            return (
                None,
                None,
                {
                    "verification": "unverifiable",
                    "verification_reason": f"valid under another {cc} identifier",
                    "candidate_modules": accepting,
                },
            )
        return False, cc, {}
    except Exception as exc:  # could not run the check: that is not "invalid"
        reason = f"validator raised {type(exc).__name__}"
        return None, None, {"verification": "unverifiable", "verification_reason": reason}


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_NORMALIZE_STEP = _StaticStepSpec(
    "identifier.normalize", "identifier.normalize", Reversibility.REVERSIBLE, False
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_NORMALIZE_STEP,)


class IdentifierNormalizer:
    name = "IdentifierNormalizer"
    supported_types = frozenset(
        {FieldSemanticType.IDENTIFIER, FieldSemanticType.TAX_ID, FieldSemanticType.CODE}
    )

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = _normalize_unicode_digits(value.strip())
        cleaned = cleaned.upper()

        has_internal_separator = bool(_INTERNAL_SEPARATOR_RE.search(cleaned))
        flags: list[QualityFlag] = []
        if has_internal_separator:
            flags.append(QualityFlag.POTENTIAL_COLLISION)

        structured: dict[str, object] = {
            "cleaned": cleaned,
            "has_internal_separator": has_internal_separator,
        }
        status = NormalizationStatus.NORMALIZED
        confidence = 1.0
        if ctx.semantic_type is FieldSemanticType.CODE:
            # Canonicalization only: a code carries no jurisdiction, so no
            # check-digit verdict is made and the status says "not checked".
            structured["verification"] = "not_applicable"
            validation_status = "UNKNOWN"
        else:
            check_digit_valid, identifier_type, verification = (
                _tax_id_verdict(cleaned, ctx.country)
                if ctx.semantic_type is FieldSemanticType.TAX_ID
                else (None, None, {})
            )
            structured |= {
                "check_digit_valid": check_digit_valid,
                "identifier_type": identifier_type,
                **verification,
            }
            validation_status = "VALID"
            if check_digit_valid is False:
                status = NormalizationStatus.INVALID
                confidence = 0.3
                validation_status = "INVALID"
            elif verification:
                validation_status = "UNKNOWN"

        return NormalizedValue(
            original=value,
            display=cleaned,
            comparison=cleaned,
            search=cleaned,
            structured=structured,
            validation_status=validation_status,
            normalization_status=status,
            confidence=confidence,
            flags=flags,
            trace=[_normalize_trace_step(value, changed=cleaned != value)],
            lossiness=Reversibility.REVERSIBLE,
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
        is_valid = result.structured.get("check_digit_valid") is not False
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "failed check-digit validation",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.structured.get("has_internal_separator"):
            return ExplanationText(
                plain_language=(
                    "Contains an internal separator; a separator-free variant of this "
                    "identifier is a potential (not automatic) match."
                ),
                technical=f"structured={result.structured}",
            )
        return ExplanationText(
            plain_language="Normalized (case/Unicode-digit cleanup only).",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


class UuidNormalizer:
    """Registered separately for UUID (§50): canonical lowercase
    hyphenated form. Kept apart from IdentifierNormalizer since UUID
    canonicalization has nothing to do with country/check-digit logic."""

    name = "UuidNormalizer"
    supported_types = frozenset({FieldSemanticType.UUID})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()
        try:
            parsed = uuid_module.UUID(cleaned)
        except ValueError:
            return NormalizedValue(
                original=value,
                display=value,
                normalization_status=NormalizationStatus.INVALID,
                validation_status="INVALID",
                confidence=0.0,
                errors=["not a valid UUID"],
                structured={},
                trace=[_normalize_trace_step(value, changed=False)],
                lossiness=Reversibility.LOSSLESS,
                profile_version="",
                env_id="",
                semantic_type=ctx.semantic_type,
                context_hash=ctx.context_hash,
            )

        canonical = str(parsed)
        return NormalizedValue(
            original=value,
            display=canonical,
            comparison=canonical,
            search=canonical,
            structured={"version": parsed.version, "canonical": canonical},
            validation_status="VALID",
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=1.0,
            trace=[_normalize_trace_step(value, changed=canonical != cleaned)],
            lossiness=Reversibility.REVERSIBLE,
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
        is_valid = result.normalization_status is NormalizationStatus.NORMALIZED
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "not a valid UUID",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        return ExplanationText(
            plain_language=f"Canonical form: {result.display}.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _normalize_unicode_digits(value: str) -> str:
    """Converts any Unicode decimal digit (Arabic-Indic, Devanagari,
    fullwidth, ...) to its ASCII equivalent, character by character —
    never via `int()`/numeric parsing, so leading zeros and non-digit
    structure are always preserved (§49)."""
    chars = []
    for ch in value:
        digit = unicodedata.decimal(ch, None)
        chars.append(str(digit) if digit is not None else ch)
    return "".join(chars)


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


def _normalize_trace_step(value: str, *, changed: bool) -> TraceStep:
    return TraceStep(
        step_order=1,
        rule_id="identifier.normalize",
        operation="identifier.normalize",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=False,
        reversibility=Reversibility.REVERSIBLE,
        library="python-stdnum",
        library_version="1.x",
    )
