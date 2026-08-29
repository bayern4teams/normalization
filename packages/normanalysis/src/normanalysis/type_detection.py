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
from normcore.enums import FieldSemanticType

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.dispatch import NormalizerRegistry

_MAX_SAMPLE_VALUES_CHECKED = 20
_MIN_SAMPLE_MATCH_RATIO_TO_CONFIRM = 0.6


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
        (r"\b(url|website|link|homepage)\b", FieldSemanticType.URL, 0.9),
        (r"\b(uuid|guid)\b", FieldSemanticType.UUID, 0.95),
        (
            r"\b(user|customer|account|order|product)[-_]?id\b",
            FieldSemanticType.IDENTIFIER,
            0.91,
        ),
        (r"\b(tax[-_]?id|vat[-_]?number|ein)\b", FieldSemanticType.TAX_ID, 0.9),
        (r"\bcurrency\b", FieldSemanticType.CURRENCY, 0.85),
        (r"\b(is|has)[-_]|[-_]flag\b", FieldSemanticType.BOOLEAN, 0.8),
        (r"\b(quantity|qty|weight|height|length|volume)\b", FieldSemanticType.QUANTITY, 0.75),
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
}


def suggest_semantic_type(
    field_name: str,
    *,
    table_name: str | None = None,
    sample_values: Sequence[str | None] | None = None,
    registry: NormalizerRegistry | None = None,
) -> list[TypeSuggestion]:
    """Returns candidates ranked by confidence, highest first. Always
    includes a FREE_TEXT fallback at low confidence so callers never get
    an empty list — "no confident match" is itself useful information,
    not an error."""
    candidates: dict[FieldSemanticType, TypeSuggestion] = {}

    for pattern, semantic_type, confidence in _FIELD_NAME_PATTERNS:
        if pattern.search(field_name) and semantic_type not in candidates:
            candidates[semantic_type] = TypeSuggestion(
                semantic_type=semantic_type,
                confidence=confidence,
                reason=f"field name matches /{pattern.pattern}/",
            )

    # A generic column name (bare "name") only becomes specific with its
    # table in view — "name" inside a Company table means something
    # different than inside a Person table. Re-run the same curated
    # patterns against "{table}_{field}"; a match there only ever *adds*
    # a candidate for a semantic type the field name alone didn't already
    # claim with its own pattern — it never overrides one.
    if table_name:
        qualified = f"{table_name}_{field_name}"
        for pattern, semantic_type, confidence in _FIELD_NAME_PATTERNS:
            if pattern.search(qualified) and semantic_type not in candidates:
                candidates[semantic_type] = TypeSuggestion(
                    semantic_type=semantic_type,
                    confidence=confidence,
                    reason=f"table+field name matches /{pattern.pattern}/",
                )

    if sample_values is not None and registry is not None:
        _refine_with_sample_values(candidates, sample_values, registry)

    if not candidates:
        candidates[FieldSemanticType.FREE_TEXT] = TypeSuggestion(
            semantic_type=FieldSemanticType.FREE_TEXT,
            confidence=0.3,
            reason="no field-name pattern matched; defaulting to free text rather than guessing",
        )

    return sorted(candidates.values(), key=lambda s: s.confidence, reverse=True)


def _refine_with_sample_values(
    candidates: dict[FieldSemanticType, TypeSuggestion],
    sample_values: Sequence[str | None],
    registry: NormalizerRegistry,
) -> None:
    non_null_sample = [v for v in sample_values if v][:_MAX_SAMPLE_VALUES_CHECKED]
    if not non_null_sample:
        return

    for semantic_type in list(candidates):
        validator_type = _SAMPLE_VALIDATORS.get(semantic_type)
        if validator_type is None:
            continue
        normalizer = registry.get(validator_type)
        if normalizer is None:
            continue

        ctx = NormalizationContext(
            field_name="__type_detection_sample__", semantic_type=validator_type
        )
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
