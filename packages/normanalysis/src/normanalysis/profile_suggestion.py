"""Normalization profile auto-generation — Source.txt §62, §84.

"After semantic typing, generate a proposed normalization profile" (§62)
/ "System should suggest: Field type, Recommended normalization,
Potential risks" (§84). Every user-facing recommendation and risk string
here is curated prose (this project's established "curated subset,
extend on evidence" policy) grounded in what the real registered
normalizer for that semantic type *actually does* — `real_steps` is
never invented: when a live `NormalizerRegistry` is supplied, it is
read directly from that normalizer's real `.steps()` sequence, the same
source of truth the Rule Builder UI (§81/§116) renders from.

Per §85 ("Every recommendation: Accept / Modify / Reject. No silent
changes.") this module only ever returns a suggestion — nothing here
writes to a profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType

if TYPE_CHECKING:
    from normcore.dispatch import NormalizerRegistry


@dataclass(frozen=True)
class ProfileSuggestion:
    semantic_type: FieldSemanticType
    recommended_summary: str
    risk: str
    real_steps: tuple[str, ...]


# Curated, not exhaustive — every entry reflects an adapter that was
# actually built (M2-M6/M7); a semantic type with no curated entry falls
# back to a generic, honest "no specific recommendation" suggestion
# rather than fabricating one (see `_GENERIC_FALLBACK`).
_CURATED_SUGGESTIONS: dict[FieldSemanticType, tuple[str, str]] = {
    FieldSemanticType.PHONE: (
        "Parse with libphonenumber; canonical output is E.164.",
        "Country ambiguity — a bare local number cannot be resolved to "
        "E.164 without a region from the number's own '+' prefix, "
        "ctx.country, or ctx.default_region; without one it stays AMBIGUOUS "
        "rather than guessing a country.",
    ),
    FieldSemanticType.ADDRESS: (
        "Parse with libpostal; validate the postcode against CLDR/"
        "google-i18n-address rules for the resolved country.",
        "Address parsing ambiguity — libpostal's statistical parser can "
        "mis-segment unusual formats, and postcode validation only runs "
        "when a country can be resolved from the parsed components.",
    ),
    FieldSemanticType.PERSON_NAME: (
        "Unicode repair/NFC, trim, collapse whitespace, then parse with a "
        "name parser; keep both an accent-preserved display form and a "
        "casefolded (optionally accent-stripped) comparison variant.",
        "Culture-dependent name order — a bare two-token name with no "
        "comma is genuinely ambiguous (given-family vs family-given) and "
        "is reported AMBIGUOUS with both candidate interpretations rather "
        "than guessed.",
    ),
    FieldSemanticType.GIVEN_NAME: (
        "Same pipeline as PERSON_NAME, applied to a single name component.",
        "A given name alone cannot detect swapped given/family order — "
        "that check only applies when both components are present.",
    ),
    FieldSemanticType.FAMILY_NAME: (
        "Same pipeline as PERSON_NAME, applied to a single name component.",
        "Multi-word family names (e.g. compound or particled surnames) "
        "are preserved as given, never split heuristically.",
    ),
    FieldSemanticType.COMPANY_NAME: (
        "Unicode normalization, then dictionary-driven legal-entity-"
        "suffix stripping (curated GLEIF-derived list) for the "
        "comparison variant only — the display form keeps the suffix.",
        "The legal-entity-suffix dictionary is a curated subset, not the "
        "full ~3,400-entry GLEIF list — an uncommon suffix may not be "
        "recognized and stripped.",
    ),
    FieldSemanticType.EMAIL: (
        "Validate and normalize with email-validator; lowercase the "
        "domain, preserve local-part case in the display form.",
        "Deliverability is never checked (no DNS/MX lookup) — only "
        "syntax validity, per this project's read-only, network-averse "
        "design.",
    ),
    FieldSemanticType.DATE: (
        "Try an ISO-8601 fast path first; otherwise infer field order "
        "(D/M/Y) from ctx.country/ctx.locale.",
        "A bare numeric date with no locale/country context and both "
        "leading groups <= 12 is genuinely ambiguous (e.g. 03/04/2024) "
        "and is reported AMBIGUOUS rather than guessed.",
    ),
    FieldSemanticType.DATETIME: (
        "Same as DATE, plus explicit timezone handling — never silently "
        "assumes UTC for a naive timestamp.",
        "Non-Gregorian calendars (Jalali/Hijri/etc.) are not converted — "
        "disclosed as an unimplemented gap, not silently mishandled.",
    ),
    FieldSemanticType.COUNTRY: (
        "Resolve via ISO 3166-1 alpha-2/alpha-3/name lookup, with a small "
        "curated alias table for common non-ISO forms (e.g. 'UK').",
        "Aliases resolved via the non-ISO table are flagged "
        "AMBIGUOUS_LOCALE at reduced confidence, since they're an "
        "approximation, not an exact code match.",
    ),
    FieldSemanticType.LANGUAGE: (
        "Resolve via ISO 639 alpha-2/alpha-3 code lookup first, falling "
        "back to name lookup only if no code matches.",
        "Free-text language names can collide with unrelated ISO "
        "entries in naive name-based lookups; this is why code lookup is "
        "tried first.",
    ),
    FieldSemanticType.SCRIPT: (
        "Detect the dominant Unicode script per character; optionally "
        "surface a language hint — never auto-transliterates.",
        "Mixed-script values report the statistically dominant script "
        "only; minority-script characters in the same value are not "
        "separately flagged.",
    ),
    FieldSemanticType.IDENTIFIER: (
        "Normalize Unicode digits without numeric casting (leading "
        "zeros always preserved); flag internal-separator variants as a "
        "potential collision rather than silently equating them.",
        '"AB-001" and "AB001" are NOT treated as equal — flagged for '
        "human review instead, since collapsing them could be wrong.",
    ),
    FieldSemanticType.TAX_ID: (
        "Same as IDENTIFIER, plus country-specific check-digit "
        "validation where a validator is registered for ctx.country.",
        "The direct per-country check-digit registry is small (curated); "
        "unregistered countries skip check-digit validation rather than "
        "guessing a scheme.",
    ),
    FieldSemanticType.UUID: (
        "Parse and re-emit in canonical lowercase-hyphenated form.",
        "An input that isn't a syntactically valid UUID is reported INVALID, never coerced.",
    ),
    FieldSemanticType.URL: (
        "Lowercase scheme/host, strip a default port, IDN-encode a "
        "non-ASCII host to punycode, normalize percent-encoding where "
        "RFC 3986 guarantees it's safe.",
        "Query parameters are never stripped, including known tracking "
        "parameters — only flagged, per this spec's explicit prohibition "
        "on blind query-string cleaning.",
    ),
    FieldSemanticType.NUMERIC: (
        "Parse with Babel/CLDR locale rules when a country/locale is known.",
        "A single-separator number with no locale/country context and "
        'exactly 3 trailing digits (e.g. "1,234") is genuinely '
        "ambiguous between thousands-grouping and a decimal fraction, "
        "and is reported AMBIGUOUS rather than guessed.",
    ),
    FieldSemanticType.CURRENCY: (
        "ISO codes and full names resolve confidently; a small curated "
        "set of unambiguous symbols (€, £, ¥) also resolve directly.",
        'A bare "$" needs ctx.country to resolve to a specific '
        "currency (USD/CAD/AUD/...) — without it, stays AMBIGUOUS.",
    ),
    FieldSemanticType.QUANTITY: (
        "Parse with Pint; canonical form is the SI base-unit representation.",
        'A bare number with no unit is a legitimate Pint "dimensionless" '
        "quantity, not an error — reported honestly, not rejected.",
    ),
    FieldSemanticType.BOOLEAN: (
        "Match against a small explicit true/false dictionary.",
        "Uncertain values ('maybe', 'unknown', 'N/A') are never coerced "
        "to true or false — routed to an explicit UNKNOWN_VALUE state.",
    ),
    FieldSemanticType.POSTCODE: (
        "Collapse whitespace and validate format against "
        "google-i18n-address's per-country regex rules.",
        "Format validation needs a resolvable country context — without "
        "one, only whitespace/case cleanup happens and the result stays "
        "AMBIGUOUS rather than assumed valid or invalid.",
    ),
    FieldSemanticType.FREE_TEXT: (
        "Unicode repair, NFC, trim, collapse whitespace, normalize "
        "punctuation; detect known missing-value sentinels.",
        "This is the most general pipeline in the system — consider a "
        "more specific semantic type if the field's actual content is "
        "more structured than free text.",
    ),
}

_GENERIC_FALLBACK = (
    "No curated recommendation for this semantic type yet.",
    "No specific risk profile has been curated for this semantic type — "
    "review its normalizer's real trace output directly (Rule Builder) "
    "before trusting a default.",
)


def suggest_profile(
    semantic_type: FieldSemanticType,
    *,
    registry: NormalizerRegistry | None = None,
    sample_value: str | None = None,
) -> ProfileSuggestion:
    summary, risk = _CURATED_SUGGESTIONS.get(semantic_type, _GENERIC_FALLBACK)
    real_steps = _real_steps(semantic_type, registry, sample_value)
    return ProfileSuggestion(
        semantic_type=semantic_type,
        recommended_summary=summary,
        risk=risk,
        real_steps=real_steps,
    )


def _real_steps(
    semantic_type: FieldSemanticType,
    registry: NormalizerRegistry | None,
    sample_value: str | None,
) -> tuple[str, ...]:
    if registry is None:
        return ()
    normalizer = registry.get(semantic_type)
    if normalizer is None:
        return ()

    if sample_value is not None:
        # A real executed trace for this exact value is strictly more
        # informative than the normalizer's static declared step list
        # (some steps are conditional — e.g. AddressNormalizer's postcode
        # validation step only appears when a country resolves).
        ctx = NormalizationContext(
            field_name="__profile_suggestion_sample__", semantic_type=semantic_type
        )
        result = normalizer.normalize(sample_value, ctx)
        if result.trace:
            return tuple(dict.fromkeys(step.operation for step in result.trace))

    return tuple(step.operation for step in normalizer.steps())
