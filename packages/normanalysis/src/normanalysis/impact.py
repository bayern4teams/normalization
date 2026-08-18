"""Impact analysis — Source.txt §78, §97.

Computes the exact metric set §78 specifies for reviewing a normalization
profile before accepting it: unique values before/after, collision count
before/after, null count before/after, average length before/after,
plus a "potential information loss" signal derived from the real
`Reversibility`/`QualityFlag` data every normalizer already produces —
never a fabricated heuristic bolted on afterward.

"New collisions" (§78's own worked example: 82,400 unique before, 74,200
after, "New collisions: 8,200") is defined the same way the worked
example implies: `unique_before - unique_after`, i.e. how many distinct
raw values were merged together by normalization. A profile that
*increases* distinctness (rare, but possible for a lossy repair that
splits an ambiguous value) reports a negative delta rather than clamping
to zero — clamping would silently hide a real, worth-inspecting signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from normcore.enums import Reversibility
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.models import NormalizedValue


class ImpactReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_name: str
    total_values: int
    unique_before: int
    unique_after: int
    new_collisions: int
    null_before: int
    null_after: int
    avg_length_before: float
    avg_length_after: float
    lossy_count: int
    partially_reversible_count: int
    warnings: list[str]


def compute_impact(
    field_name: str,
    originals: Sequence[str | None],
    results: Sequence[NormalizedValue],
) -> ImpactReport:
    if len(originals) != len(results):
        msg = f"originals ({len(originals)}) and results ({len(results)}) must be the same length"
        raise ValueError(msg)

    non_null_originals = [v for v in originals if v is not None and v != ""]
    non_null_display = [r.display for r in results if r.display is not None and r.display != ""]
    non_null_comparison = [
        r.comparison for r in results if r.comparison is not None and r.comparison != ""
    ]

    unique_before = len(set(non_null_originals))
    # "Unique after" must be measured on `comparison` (the actual dedup/
    # equality key normalizers compute), not `display` — two values can
    # render differently (case, accents preserved) yet be the SAME
    # comparison key, and that merge is exactly what §78's "new
    # collisions" is meant to surface. Using `display` here would silently
    # under-report collisions whenever a normalizer's display view isn't
    # itself the comparison view (true for every M2+ normalizer).
    unique_after = len(set(non_null_comparison))

    null_before = sum(1 for v in originals if v is None or v == "")
    null_after = sum(1 for r in results if r.display is None or r.display == "")

    avg_length_before = (
        sum(len(v) for v in non_null_originals) / len(non_null_originals)
        if non_null_originals
        else 0.0
    )
    avg_length_after = (
        sum(len(v) for v in non_null_display) / len(non_null_display) if non_null_display else 0.0
    )

    lossy_count = sum(1 for r in results if r.lossiness is Reversibility.LOSSY)
    partially_reversible_count = sum(
        1 for r in results if r.lossiness is Reversibility.PARTIALLY_REVERSIBLE
    )

    new_collisions = unique_before - unique_after

    warnings = list(_build_warnings(field_name, unique_before, new_collisions, results))

    return ImpactReport(
        field_name=field_name,
        total_values=len(originals),
        unique_before=unique_before,
        unique_after=unique_after,
        new_collisions=new_collisions,
        null_before=null_before,
        null_after=null_after,
        avg_length_before=avg_length_before,
        avg_length_after=avg_length_after,
        lossy_count=lossy_count,
        partially_reversible_count=partially_reversible_count,
        warnings=warnings,
    )


_COLLISION_WARNING_RATIO = 0.02  # §78's own example: 8,200/82,400 ~= 10%; flag well below that


def _build_warnings(
    field_name: str,
    unique_before: int,
    new_collisions: int,
    results: Sequence[NormalizedValue],
) -> list[str]:
    warnings: list[str] = []
    if unique_before > 0 and new_collisions > 0:
        ratio = new_collisions / unique_before
        if ratio >= _COLLISION_WARNING_RATIO:
            top_op = _top_lossy_operation(results)
            cause = f" — most commonly attributable to the '{top_op}' step" if top_op else ""
            warnings.append(
                f"{field_name}: normalization created {new_collisions} new collisions "
                f"({ratio:.1%} of {unique_before} unique values){cause}."
            )
    if new_collisions < 0:
        warnings.append(
            f"{field_name}: normalization increased distinct-value count by "
            f"{-new_collisions} — a lossy repair may be splitting previously-equal values."
        )
    lossy_ratio = (
        sum(1 for r in results if r.lossiness is Reversibility.LOSSY) / len(results)
        if results
        else 0.0
    )
    if lossy_ratio >= _COLLISION_WARNING_RATIO:
        warnings.append(
            f"{field_name}: {lossy_ratio:.1%} of values passed through at least one "
            "LOSSY transformation step — original values remain available via `original`, "
            "but `display`/`comparison` are not reconstructable from it."
        )
    return warnings


def _top_lossy_operation(results: Sequence[NormalizedValue]) -> str | None:
    """Tally which trace step operation appears most often among lossy
    steps, real computation over the results actually produced (not a
    canned message) — matches §78's example of naming the responsible
    step ("Accent removal creates additional collisions")."""
    counts: dict[str, int] = {}
    for result in results:
        for step in result.trace:
            if step.lossy:
                counts[step.operation] = counts.get(step.operation, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]
