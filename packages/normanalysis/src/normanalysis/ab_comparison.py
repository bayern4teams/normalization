"""A/B normalization comparison — Source.txt §96, §97.

Compares two independently-computed result sets for the *same* input
values (typically produced under two different profile versions) on the
metrics §96 names explicitly: unique values, collision rate, invalid
rate, changed-value %, plus the §97 downstream-ER-relevant diagnostics
(candidate-key uniqueness ratio before/after — the same "unique / total"
ratio §97 asks for, computed for each side independently so the caller
can see which profile version yields the healthier candidate key).

Deliberately does not perform or approximate entity resolution itself
(§97: "Do not perform Splink. Just expose downstream-relevant
diagnostics.").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from normcore.enums import NormalizationStatus
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.models import NormalizedValue


class SideMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_version: str
    total_values: int
    unique_values: int
    unique_ratio: float
    invalid_count: int
    invalid_rate: float


class AbComparisonReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_name: str
    a: SideMetrics
    b: SideMetrics
    changed_between_a_and_b: int
    changed_between_a_and_b_pct: float
    collision_rate_delta: float


def _side_metrics(profile_version: str, results: Sequence[NormalizedValue]) -> SideMetrics:
    total = len(results)
    unique = len({r.comparison for r in results if r.comparison is not None and r.comparison != ""})
    invalid = sum(
        1
        for r in results
        if r.normalization_status in (NormalizationStatus.INVALID, NormalizationStatus.FAILED)
    )
    return SideMetrics(
        profile_version=profile_version,
        total_values=total,
        unique_values=unique,
        unique_ratio=(unique / total) if total else 0.0,
        invalid_count=invalid,
        invalid_rate=(invalid / total) if total else 0.0,
    )


def compare_runs(
    field_name: str,
    *,
    profile_version_a: str,
    results_a: Sequence[NormalizedValue],
    profile_version_b: str,
    results_b: Sequence[NormalizedValue],
) -> AbComparisonReport:
    if len(results_a) != len(results_b):
        msg = (
            f"results_a ({len(results_a)}) and results_b ({len(results_b)}) must be "
            "computed over the same aligned input values to be comparable"
        )
        raise ValueError(msg)

    side_a = _side_metrics(profile_version_a, results_a)
    side_b = _side_metrics(profile_version_b, results_b)

    pairs = zip(results_a, results_b, strict=True)
    changed = sum(1 for ra, rb in pairs if ra.display != rb.display)
    total = len(results_a)

    # "collision rate" per side: fraction of values that are NOT unique
    # after normalization (1 - unique_ratio) — how much normalization
    # merged distinct inputs together, the same signal impact.py's
    # new_collisions exposes for a single run, here compared side-by-side.
    collision_rate_a = 1.0 - side_a.unique_ratio
    collision_rate_b = 1.0 - side_b.unique_ratio

    return AbComparisonReport(
        field_name=field_name,
        a=side_a,
        b=side_b,
        changed_between_a_and_b=changed,
        changed_between_a_and_b_pct=(changed / total) if total else 0.0,
        collision_rate_delta=collision_rate_b - collision_rate_a,
    )
