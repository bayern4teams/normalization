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
- the real normalizer's `validate` rejects it with a definitive verdict (not
  AMBIGUOUS or UNKNOWN: a day/month-ambiguous date needs a locale, it is not
  missing; such cells count on neither side of the minority rule), so `NA` in
  a COUNTRY column (Namibia) or a year-only DATE is valid and never reported;
- it recurs (seen more than once) as part of a small set: the recurring
  failing values are no more numerous than the spellings of a missing value in the
  project's missing-value table. A larger set is dirty data, not disguised
  nulls, and then only the values that table names are reported;
- the failing cells are a minority of the column: if as many cells fail as
  conform, the type is wrong and no cell is "the odd one out".

Results are *candidates* for a person to confirm, never a rewrite.
`hint` comes from the shared `missing-values.common` dictionary, the same
table the Dispatcher applies; it is a hint, not a verdict, and `None` when a
value is not in it ("not in the table", not "known to be missing").
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

# ponytail: ceiling, every distinct value is validated once, and a failing value
# can cost 10-400 ms in DateNormalizer (100k distinct failing dates = hours).
# Upgrade path: validate a sample of distinct values, or fix the date slow path.

# ponytail: numeric magic numbers (-999, 9999) are out of reach here. A bare
# number is a valid number to every validator, so telling a magic number from
# data needs a column-level model of the numeric distribution. The upgrade
# path is `ptype` (column type inference with missing/anomalous classes) once
# it supports pandas 3 / greenery 4 (feasibility gate:
# `docs/archive/plans/defects/FINAL_REPORT.md`, F6).


# Verdict statuses that mean "cannot decide", not "does not conform"; derived
# from the status strings the validators return (see dispatch._VALIDATION_SEVERITY).
_UNDECIDED = frozenset({"AMBIGUOUS", "UNKNOWN"})


@dataclass(frozen=True)
class DisguisedMissing:
    """A CANDIDATE disguised-missing value, never a verdict. `hint` is the
    `MissingKind` the shared dictionary gives it; `None` means "not in the
    missing-value table", NOT "known missing": the value merely fails the
    column's validator and recurs (a malformed date or e-mail lands here too)."""

    value: str
    count: int
    hint: MissingKind | None


@cache
def _defaults() -> tuple[NormalizerRegistry, dict[str, str]]:
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    # Lazy: normapi depends on normanalysis, so an import at module load is a cycle.
    from normalizers.generic_text import load_missing_value_sentinels  # noqa: PLC0415
    from normapi.app import _DEFAULT_DICTIONARIES_DIR, build_normalizer_registry  # noqa: PLC0415

    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
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

    # AMBIGUOUS / UNKNOWN ("needs context", never guess) are neither failing
    # nor valid: excluded from the minority rule and from the mean below.
    valid_counts: list[int] = []
    failing: dict[str, int] = {}
    for value, count in value_counts.items():
        if count <= 0 or not isinstance(value, str):
            continue
        verdict = normalizer.validate(value, ctx)
        if verdict.is_valid:
            valid_counts.append(count)
        elif verdict.status not in _UNDECIDED:
            failing[value] = count
    return candidates(failing, sum(valid_counts), sentinels=sentinels)


def candidates(
    failing: Mapping[str, int], valid_cells: int, *, sentinels: Mapping[str, str] | None = None
) -> list[DisguisedMissing]:
    """The rule above on counts a caller already has: `failing` is each value
    the type rejected with a definitive verdict and its count, `valid_cells`
    how many cells conformed. A clone has both for every cell it wrote, so
    it reports exact counts without validating anything again."""
    if sentinels is None:
        sentinels = _defaults()[1]
    failing_cells = sum(failing.values())
    if not valid_cells or failing_cells >= valid_cells:
        return []
    # "Recurs as a small set": the recurring failing values are candidates when there are no more
    # of them than the missing-value table has spellings of a missing value (no column holds more
    # ways to write it than the project's own table knows). More than that is dirty data, not
    # disguised nulls, and only the values the table names are reported.
    # ponytail: the table's size is the bound; a frequency model (ptype) is the upgrade path.
    recurring = sorted(
        ((v, c) for v, c in failing.items() if c > 1), key=lambda kv: (-kv[1], kv[0])
    )
    small_set = len(recurring) <= len(sentinels)
    out = []
    for value, count in recurring:
        kind = sentinels.get(value.strip().casefold())
        if kind or small_set:
            out.append(DisguisedMissing(value, count, MissingKind(kind) if kind else None))
    return out
