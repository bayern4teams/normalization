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
from enum import StrEnum
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


class CollisionDecisionType(StrEnum):
    """§92's Collision Dashboard actions: "Accept rule" (the current
    normalization outcome is correct as-is), "Reject rule" (it's wrong —
    the profile/rule needs a change), "Whitelist collision" (reviewed,
    intentional, don't re-flag as a NEW collision in future runs). No
    separate mechanism distinguishes "accept/reject A RULE" from
    "accept/reject THIS COLLISION" here — this codebase has no rule-
    proposal engine to make that a meaningfully different action, so a
    human's disposition on one collision group is recorded directly.
    "Inspect" (view group detail) and "Change configuration" (navigate
    to the profile/rule editor) need no new state — they're already
    real via GET .../collisions and the existing Profiles/Rules UI."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WHITELISTED = "WHITELISTED"


class CollisionDecision(BaseModel):
    """A human reviewer's real, persisted disposition on one collision
    group within one run — Source.txt §92, ADR-013 (collisions are
    explicitly named as Postgres-backed metadata). Keyed by
    `(run_id, normalized_value)`, not a separate synthetic id: a
    collision group's own identity already IS that pair (see
    `find_collisions`), and a run's execution is immutable once
    terminal, so `normalized_value` cannot silently drift out from under
    an existing decision."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    normalized_value: str
    decision: CollisionDecisionType
    decided_by: str
    decided_at: str  # ISO 8601
    note: str | None = None


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
