"""Disguised missing data, at cell level (improvement-report D4).

`type_detection` types a column, never a cell, so a column that is 97% dates
and 3% `N/A` / `unknown` / `-` is one type for the whole column and the
disguised nulls are mis-normalized. This reports WHICH distinct values of a
typed column do not conform, with counts. It only reports: it never rewrites
a value, and its input is `value -> count` (never row lists).

A distinct value is reported when all of these hold:

- the column's type has a validator that can say no (the same
  `_discriminates` probe `type_detection` uses; FREE_TEXT and UNKNOWN have
  none, so they abstain, a validator that cannot say no is no evidence);
- the real normalizer's `validate` rejects it, so `NA` in a COUNTRY column
  (Namibia) or a year-only DATE is valid and never reported;
- it recurs (seen more than once): a disguised null is a value somebody
  typed over and over, a value seen once is noise or a typo, not a sentinel;
- the failing cells are a minority of the column: if as many cells fail as
  conform, the type is wrong and no cell is "the odd one out".

`hint` comes from the shared `missing-values.common` dictionary, the same
table the Dispatcher applies; it is a hint, not a verdict, and `None` when a
value is not in it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind

from normanalysis.type_detection import _discriminates, _sample_context

if TYPE_CHECKING:
    from collections.abc import Mapping

    from normcore.dispatch import NormalizerRegistry

# ponytail: numeric magic numbers (-999, 9999) are out of reach here. A bare
# number is a valid number to every validator, so telling a magic number from
# data needs a column-level model of the numeric distribution. The upgrade
# path is `ptype` (column type inference with missing/anomalous classes) once
# it supports pandas 3 / greenery 4 (feasibility gate: `.handoff/D4.feasibility.md`).


@dataclass(frozen=True)
class DisguisedMissing:
    value: str
    count: int
    hint: MissingKind | None


@cache
def _defaults() -> tuple[NormalizerRegistry, dict[str, str]]:
    # Lazy: normapi depends on normanalysis, so an import at module load is a cycle.
    from normalizers.generic_text import load_missing_value_sentinels  # noqa: PLC0415
    from normapi.app import _DEFAULT_DICTIONARIES_DIR, build_normalizer_registry  # noqa: PLC0415

    from normdict import DictionaryLoader  # noqa: PLC0415

    loader = DictionaryLoader(_DEFAULT_DICTIONARIES_DIR)
    return build_normalizer_registry(loader), load_missing_value_sentinels(loader)


def detect_disguised_missing(
    value_counts: Mapping[str, int],
    semantic_type: FieldSemanticType | str,
    context: NormalizationContext | None = None,
    *,
    registry: NormalizerRegistry | None = None,
    sentinels: Mapping[str, str] | None = None,
) -> list[DisguisedMissing]:
    """Distinct non-conforming recurring values of a column typed `semantic_type`,
    most frequent first, ties by value. Unknown type names raise ValueError."""
    sem = FieldSemanticType(semantic_type)
    if registry is None or sentinels is None:
        default_registry, default_sentinels = _defaults()
        registry = default_registry if registry is None else registry
        sentinels = default_sentinels if sentinels is None else sentinels

    normalizer = registry.get(sem)
    if normalizer is None or sem in {FieldSemanticType.FREE_TEXT, FieldSemanticType.UNKNOWN}:
        return []
    ctx = _sample_context(
        sem, context.country if context else None, context.locale if context else None
    )
    if not _discriminates(normalizer, ctx):
        return []

    valid_cells = failing_cells = 0
    failing: dict[str, int] = {}
    for value, count in value_counts.items():
        if count <= 0 or not isinstance(value, str):
            continue
        if normalizer.validate(value, ctx).is_valid:
            valid_cells += count
        else:
            failing[value] = count
            failing_cells += count
    if failing_cells >= valid_cells:
        return []
    return [
        DisguisedMissing(
            value,
            count,
            MissingKind(kind) if (kind := sentinels.get(value.strip().casefold())) else None,
        )
        for value, count in sorted(failing.items(), key=lambda kv: (-kv[1], kv[0]))
        if count > 1
    ]
