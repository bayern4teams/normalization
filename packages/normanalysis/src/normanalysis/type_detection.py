"""Automatic field-type detection — Source.txt §61.

"The system may automatically suggest semantic type... The user must be
able to override" — this module only ever *suggests*, ranked by
confidence; nothing here mutates a profile or a field's configured
semantic type on its own (§85 "no silent changes" applies just as much
to an automated suggestion as to anything else).

Deliberately does not call an LLM (§129 explicitly allows one for this
exact use case — "LLMs may optionally help with suggesting semantic
field type" — but also requires "the final normalization transformation
must be deterministic and reproducible," and this suggestion feeds
directly into what a user might accept as that configuration). Two real,
deterministic signals instead:

1. Field-name pattern matching against a curated keyword table (this
   project's established "curated subset, extend on evidence" policy —
   not exhaustive, and a name matching nothing suggests FREE_TEXT at low
   confidence rather than guessing).
2. Optional value-shape sniffing: when sample values are supplied, they
   are actually run through the real candidate normalizers'
   `.validate()` — the suggestion is confirmed or demoted based on real
   parse success/failure, not just the field name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, QualityFlag

from normcore import multivalue

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.dispatch import NormalizerRegistry

_MAX_SAMPLE_VALUES_CHECKED = 20
_MIN_SAMPLE_MATCH_RATIO_TO_CONFIRM = 0.6

# Detection used to be name-first with values only ever CONFIRMING or
# demoting a name match, so a column whose name matched nothing was never
# offered to any validator at all — a `logo` column full of perfectly
# well-formed URLs stayed unrecognised purely because "logo" is not in the
# keyword table, and no keyword table is ever going to be complete.
#
# So: when the name yields nothing confident, ask the data instead. The bar
# is deliberately much higher than for confirming a name match (essentially
# every sampled value must validate), and the resulting confidence is
# capped so a real name match always outranks it.
_MIN_VALUE_ONLY_RATIO = 0.95
_VALUE_ONLY_CONFIDENCE = 0.9

# A value-only match is only evidence if the validator can actually say no.
# `PassthroughNormalizer` declares every semantic type and accepts anything,
# so wherever it is the registered handler for a type, 100% of any sample
# "validates" and every column would be detected as that type. Probing with
# a string no real type accepts proves the validator discriminates before
# its agreement is believed. (The name-match path never needed this: a
# permissive validator there can only CONFIRM a guess the name already
# made.)
_NEGATIVE_CONTROL = "zz~not~a~value~zz"

# A SECOND negative control, for the value-only path only. A validator that
# accepts a bare integer cannot identify a column from its values alone,
# because a column of digit strings is the most common thing in any
# database: MONEY accepts `368938835` as cleanly as it accepts `$17.6
# Million`, so on values alone it claimed every ID column in a real 7-table
# source — six false positives, each one a primary key. BOOLEAN accepts
# `1`/`0` the same way, and a column of 1s and 0s is just as likely a
# count.
#
# Such a type is still allowed to CONFIRM a name match, where the name
# already said what the column is; it is only barred from naming a column
# by itself. Probed rather than hand-listed so a normalizer that starts
# accepting bare numbers is caught without anyone remembering to add it.
_BARE_NUMBER_CONTROL = "12345"


@dataclass(frozen=True)
class TypeSuggestion:
    semantic_type: FieldSemanticType
    confidence: float
    reason: str


# Curated, not exhaustive — ordered so a more specific pattern (checked
# first in `_FIELD_NAME_PATTERNS`) wins over a more generic one matching
# the same field name (e.g. "company_name" matches COMPANY_NAME before
# the generic "name" -> PERSON_NAME fallback gets a chance).
_FIELD_NAME_PATTERNS: tuple[tuple[re.Pattern[str], FieldSemanticType, float], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), semantic_type, confidence)
    for pattern, semantic_type, confidence in (
        (r"\b(e[-_]?mail)\b", FieldSemanticType.EMAIL, 0.97),
        (r"\b(mobile|cell[-_]?phone|phone|tel(ephone)?|fax)\b", FieldSemanticType.PHONE, 0.9),
        (r"\b(dob|date[-_]?of[-_]?birth|birth[-_]?date)\b", FieldSemanticType.DATE, 0.97),
        (r"\b(date|_at|_on)\b", FieldSemanticType.DATETIME, 0.55),
        (
            r"\b(company|business|org(anization)?|employer)[-_]?name?\b",
            FieldSemanticType.COMPANY_NAME,
            0.9,
        ),
        (r"\b(given|first)[-_]?name\b", FieldSemanticType.GIVEN_NAME, 0.9),
        (r"\b(family|last|sur)[-_]?name\b", FieldSemanticType.FAMILY_NAME, 0.9),
        (
            r"\b(customer|full|contact|person)?[-_]?name\b",
            FieldSemanticType.PERSON_NAME,
            0.8,
        ),
        (r"\b(street[-_]?)?address|addr\b", FieldSemanticType.ADDRESS, 0.85),
        (r"\b(zip|postal|postcode)([-_]?code)?\b", FieldSemanticType.POSTCODE, 0.9),
        (r"\bcountry\b", FieldSemanticType.COUNTRY, 0.9),
        (r"\blang(uage)?\b", FieldSemanticType.LANGUAGE, 0.85),
        (r"\b(url|website|link|homepage|domain)\b", FieldSemanticType.URL, 0.9),
        (r"\b(uuid|guid)\b", FieldSemanticType.UUID, 0.95),
        (
            r"\b(user|customer|account|order|product)[-_]?id\b",
            FieldSemanticType.IDENTIFIER,
            0.91,
        ),
        (r"\b(tax[-_]?id|vat[-_]?number|ein)\b", FieldSemanticType.TAX_ID, 0.9),
        (r"\bcurrency\b", FieldSemanticType.CURRENCY, 0.85),
        # The separator is optional: `is_public`, `isPublic` and the very
        # common flat `ispublic` are the same convention. ANCHORED, because
        # `\b` does not keep this out of the middle of a word once the
        # relaxed pass (below) drops the boundaries: measured on a real
        # source, `displayName` matched on the "is" in "display" and
        # `personHashtags` on the "has" in "Hashtags". Both survived only
        # because their values demoted the guess — which is luck, not a
        # rule. `is`/`has` is a PREFIX convention, so say so.
        (r"^(is|has)[-_]?[a-z]|[-_]flag\b", FieldSemanticType.BOOLEAN, 0.8),
        (r"\b(quantity|qty|weight|height|length|volume)\b", FieldSemanticType.QUANTITY, 0.75),
        # Only words that mean money and nothing else. `price`/`amount`/
        # `cost`/`balance` stay NUMERIC below: they are just as often a bare
        # number with the currency held elsewhere (or nowhere), and MONEY
        # writes a second companion column — too much to do on a name alone.
        # Deliberately under the apply threshold, like QUANTITY: a MONEY
        # guess only sticks once real values parse as money.
        (
            r"\b(revenue|salary|income|turnover|valuation|arr|mrr|fee|wage|payroll)\b",
            FieldSemanticType.MONEY,
            0.75,
        ),
        (r"\b(price|amount|cost|total|balance|count|number|num)\b", FieldSemanticType.NUMERIC, 0.6),
    )
)

# Which real normalizer to trial-run a value sample against, per
# candidate type, and the semantic_type the resulting NormalizationContext
# must declare (Dispatcher requires the two to match).
_SAMPLE_VALIDATORS: dict[FieldSemanticType, FieldSemanticType] = {
    FieldSemanticType.EMAIL: FieldSemanticType.EMAIL,
    FieldSemanticType.PHONE: FieldSemanticType.PHONE,
    FieldSemanticType.DATE: FieldSemanticType.DATE,
    FieldSemanticType.DATETIME: FieldSemanticType.DATETIME,
    FieldSemanticType.URL: FieldSemanticType.URL,
    FieldSemanticType.UUID: FieldSemanticType.UUID,
    FieldSemanticType.COUNTRY: FieldSemanticType.COUNTRY,
    FieldSemanticType.CURRENCY: FieldSemanticType.CURRENCY,
    FieldSemanticType.BOOLEAN: FieldSemanticType.BOOLEAN,
    FieldSemanticType.MONEY: FieldSemanticType.MONEY,
}


# Flat, separator-free column names (`firsthiredate`, `postalcode`) carry no
# word boundary for `\b` to find, so the curated patterns above miss them
# entirely. A second pass drops the boundaries and matches as a substring —
# which is genuinely loose ("candidate" contains "date"), so it is allowed
# ONLY for types whose guess can be checked against real values below, and
# it starts well under any sane apply threshold. A relaxed name match on its
# own is never enough; it has to be confirmed by the data.
_RELAXED_CONFIDENCE_FACTOR = 0.6

_RELAXED_NAME_PATTERNS: tuple[tuple[re.Pattern[str], FieldSemanticType, float], ...] = tuple(
    (
        re.compile(pattern.pattern.replace(r"\b", ""), re.IGNORECASE),
        semantic_type,
        confidence * _RELAXED_CONFIDENCE_FACTOR,
    )
    for pattern, semantic_type, confidence in _FIELD_NAME_PATTERNS
    if semantic_type in _SAMPLE_VALIDATORS
)


def _name_variants(field_name: str) -> tuple[str, ...]:
    """Every spelling of one column name the curated patterns may match,
    tried in order; any one matching is a match.

    `firstHireDate` becomes `first_Hire_Date` so camelCase gets the word
    boundaries snake_case already has — and then `first Hire Date`, because
    `_` is a WORD character, so `\b` finds no boundary inside
    `company_Phone` at all and `\bphone\b` simply never matched it. That is
    why detection missed `companyPhone` on a real 1.27M-row source: not a
    missing keyword, a boundary that cannot see the separator most column
    names actually use. Splitting on the separator lets every `\b...\b`
    pattern in the table work on camelCase and snake_case alike, with no
    pattern rewritten.

    The separator-joined spellings are kept too: a pattern that spells the
    separator itself (`\b(company|...)[-_]?name?\b`) matches those and not
    the spaced form.
    """
    snaked = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", field_name)
    spaced = re.sub(r"[-_]+", " ", snaked).strip()
    return tuple(dict.fromkeys(v for v in (field_name, snaked, spaced) if v))


def _sample_context(
    validator_type: FieldSemanticType, country: str | None, locale: str | None
) -> NormalizationContext:
    """The context a sampled value is validated under.

    `country`/`locale` matter more here than anywhere else: without a
    country, PHONE validates only numbers carrying their own `+CC` and
    without a locale MONEY refuses every comma-grouped amount — so a
    column really full of phones or money gets DEMOTED for holding what it
    holds. Measured on a real source, `companyPhone` came out PHONE at
    0.27 (name matched, values "disagreed") purely because detection asked
    the question with no country. The job already knows both; detection
    just was not told.
    """
    return NormalizationContext(
        field_name="__type_detection_sample__",
        semantic_type=validator_type,
        country=country,
        locale=locale,
    )


def suggest_semantic_type(
    field_name: str,
    *,
    sample_values: Sequence[str | None] | None = None,
    registry: NormalizerRegistry | None = None,
    country: str | None = None,
    locale: str | None = None,
) -> list[TypeSuggestion]:
    """Returns candidates ranked by confidence, highest first. Always
    includes a FREE_TEXT fallback at low confidence so callers never get
    an empty list — "no confident match" is itself useful information,
    not an error."""
    candidates: dict[FieldSemanticType, TypeSuggestion] = {}

    variants = _name_variants(field_name)
    for patterns, exact in ((_FIELD_NAME_PATTERNS, True), (_RELAXED_NAME_PATTERNS, False)):
        for pattern, semantic_type, confidence in patterns:
            if semantic_type in candidates:
                continue
            if not any(pattern.search(variant) for variant in variants):
                continue
            candidates[semantic_type] = TypeSuggestion(
                semantic_type=semantic_type,
                confidence=confidence,
                reason=(
                    f"field name matches /{pattern.pattern}/"
                    if exact
                    else f"field name contains /{pattern.pattern}/ (no word boundary)"
                ),
            )

    if sample_values is not None and registry is not None:
        _refine_with_sample_values(candidates, sample_values, registry, country, locale)
        if not any(c.confidence >= _VALUE_ONLY_CONFIDENCE for c in candidates.values()):
            _suggest_from_values_alone(candidates, sample_values, registry, country, locale)

    if not candidates:
        candidates[FieldSemanticType.FREE_TEXT] = TypeSuggestion(
            semantic_type=FieldSemanticType.FREE_TEXT,
            confidence=0.3,
            reason="no field-name pattern matched; defaulting to free text rather than guessing",
        )

    return sorted(candidates.values(), key=lambda s: s.confidence, reverse=True)


def _parses_cleanly(normalizer: object, value: str, ctx: NormalizationContext) -> bool:
    """Valid AND not arrived at by repair. `validate` alone is too weak
    here: URL repairs a bare host, so `report.txt` is "valid" and a column
    of filenames would be rewritten to https://report.txt."""
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    if not normalizer.validate(value, ctx).is_valid:  # type: ignore[attr-defined]  # normalizer: object — duck-typed over the registry; every entry exposes validate/normalize (Dispatcher contract)
        return False
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    result = normalizer.normalize(value, ctx)  # type: ignore[attr-defined]  # same duck-typed registry entry as validate above
    # A value read only as a year states a 4-digit number, not a date: Brreg's
    # postcodes (`0150`) came out DATE once DATETIME stopped tying with DATE
    # (PART1 N2 makes `0150` an hhmm too), and the clone parsed them as years.
    year_only = (result.structured or {}).get("precision") == "year"
    return (
        QualityFlag.PARSER_FALLBACK not in result.flags
        and result.original_kind is None
        and not year_only
    )


def _discriminates(normalizer: object, ctx: NormalizationContext) -> bool:
    """Whether this validator can say no at all. One that accepts a string
    no real type would accept proves nothing by accepting real values
    either, so its verdict is ignored entirely — it neither confirms nor
    demotes."""
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    return not normalizer.validate(_NEGATIVE_CONTROL, ctx).is_valid  # type: ignore[attr-defined]  # duck-typed registry entry (see _parses_cleanly)


def _flatten_sample(sample_values: Sequence[str | None]) -> list[str]:
    """A list-shaped sample is validated element by element, the same way
    Dispatcher.normalize will actually process it. Validating the raw
    `['a@b.com']` instead would demote every correct guess about a column
    that happens to hold lists."""
    return [
        element
        for value in sample_values
        if value
        for element in (multivalue.split(value) or ([value], ""))[0]
        if element
    ][:_MAX_SAMPLE_VALUES_CHECKED]


def _suggest_from_values_alone(
    candidates: dict[FieldSemanticType, TypeSuggestion],
    sample_values: Sequence[str | None],
    registry: NormalizerRegistry,
    country: str | None = None,
    locale: str | None = None,
) -> None:
    non_null_sample = _flatten_sample(sample_values)
    if not non_null_sample:
        return
    matched: list[tuple[FieldSemanticType, int]] = []
    for semantic_type, validator_type in _SAMPLE_VALIDATORS.items():
        if semantic_type in candidates:
            continue
        normalizer = registry.get(validator_type)
        if normalizer is None:
            continue
        ctx = _sample_context(validator_type, country, locale)
        if not _discriminates(normalizer, ctx):
            continue
        if normalizer.validate(_BARE_NUMBER_CONTROL, ctx).is_valid:
            continue
        # Only CLEANLY parsed values are evidence here. A normalizer that
        # had to repair the value accepted it on a guess, and a guess is
        # not proof of what the column is: URL repairs a bare host, so a
        # column of `report.txt` / `v1.2.tar` filenames would otherwise
        # "validate" as URLs and get rewritten to https://report.txt. A
        # name match may still be confirmed by a repaired value — there the
        # column name already said what the type was.
        matches = sum(1 for v in non_null_sample if _parses_cleanly(normalizer, v, ctx))
        if matches / len(non_null_sample) >= _MIN_VALUE_ONLY_RATIO:
            matched.append((semantic_type, matches))

    # With no name to break the tie, two types both claiming the column is
    # not evidence for either — say nothing rather than let dict order pick.
    if len(matched) != 1:
        return
    semantic_type, matches = matched[0]
    candidates[semantic_type] = TypeSuggestion(
        semantic_type=semantic_type,
        confidence=_VALUE_ONLY_CONFIDENCE,
        reason=(
            f"field name matched nothing, but {matches}/{len(non_null_sample)} "
            "sample values validate as this type"
        ),
    )


def _refine_with_sample_values(
    candidates: dict[FieldSemanticType, TypeSuggestion],
    sample_values: Sequence[str | None],
    registry: NormalizerRegistry,
    country: str | None = None,
    locale: str | None = None,
) -> None:
    non_null_sample = _flatten_sample(sample_values)
    if not non_null_sample:
        return

    for semantic_type in list(candidates):
        validator_type = _SAMPLE_VALIDATORS.get(semantic_type)
        if validator_type is None:
            continue
        normalizer = registry.get(validator_type)
        if normalizer is None:
            continue

        ctx = _sample_context(validator_type, country, locale)
        if not _discriminates(normalizer, ctx):
            continue
        matches = sum(1 for v in non_null_sample if normalizer.validate(v, ctx).is_valid)
        ratio = matches / len(non_null_sample)

        existing = candidates[semantic_type]
        if ratio >= _MIN_SAMPLE_MATCH_RATIO_TO_CONFIRM:
            confirmed_confidence = min(0.99, max(existing.confidence, 0.85 + ratio * 0.1))
            candidates[semantic_type] = TypeSuggestion(
                semantic_type=semantic_type,
                confidence=confirmed_confidence,
                reason=(
                    f"{existing.reason}; confirmed by real parsing "
                    f"({matches}/{len(non_null_sample)} sample values validated)"
                ),
            )
        else:
            candidates[semantic_type] = TypeSuggestion(
                semantic_type=semantic_type,
                confidence=existing.confidence * 0.5,
                reason=(
                    f"{existing.reason}; demoted — only {matches}/{len(non_null_sample)} "
                    "sample values actually validated as this type"
                ),
            )
