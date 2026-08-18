"""Collision analysis — Source.txt §79, §92.

Groups original values by the normalized `comparison` key they collapse
into. A "collision" is a group backed by >= 2 *distinct* original values
(§79's own examples: "José García"/"Jose Garcia"/"JOSÉ GARCÍA" all
collapsing to "jose garcia" is a real collision worth surfacing; three
literal duplicate rows of the exact same original string collapsing to
one comparison key is not — that is normal deduplication, not a
normalization side effect, so identical originals are counted once
before the >= 2 threshold is applied).
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.models import NormalizedValue


class CollisionGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    normalized_value: str
    original_values: list[str]
    total_occurrences: int


def find_collisions(
    originals: Sequence[str | None],
    results: Sequence[NormalizedValue],
) -> list[CollisionGroup]:
    if len(originals) != len(results):
        msg = f"originals ({len(originals)}) and results ({len(results)}) must be the same length"
        raise ValueError(msg)

    by_comparison: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for original, result in zip(originals, results, strict=True):
        if original is None or original == "":
            continue
        if result.comparison is None or result.comparison == "":
            continue
        by_comparison[result.comparison][original] += 1

    groups: list[CollisionGroup] = []
    for comparison_value, originals_counts in by_comparison.items():
        if len(originals_counts) < 2:
            continue
        groups.append(
            CollisionGroup(
                normalized_value=comparison_value,
                original_values=sorted(originals_counts),
                total_occurrences=sum(originals_counts.values()),
            )
        )

    groups.sort(key=lambda g: g.total_occurrences, reverse=True)
    return groups
