"""Runtime-sampled idempotency/determinism invariants — Source.txt §71.

`tests/property/test_idempotency_determinism.py` already proves these
invariants hold under Hypothesis-generated fuzzing at development time
(and caught 4 real bugs doing so across M2/M3). This module is the
production-time complement: a cheap, sampled check run against a real
batch of *actual* values as they pass through a live run, so a
regression introduced by e.g. a dictionary update or a library upgrade
(neither of which Hypothesis re-runs automatically) surfaces as a
run-level warning instead of silently shipping.

Two invariants, both re-using the already-computed first-pass result
rather than re-deriving it, so this stays cheap:

- Idempotency: normalizing `result.display` again produces the same
  `display` (normalize(normalize(x)) == normalize(x)).
- Determinism: normalizing the *original* value twice in a row (with the
  same context/profile) produces byte-identical `display` both times.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.enums import FieldSemanticType
    from normcore.models import NormalizedValue

    from normcore import Dispatcher, NormalizationContext, NormalizationProfile

_DEFAULT_MAX_SAMPLE = 25


@dataclass(frozen=True)
class InvariantViolation:
    original: str | None
    kind: str  # "idempotency" | "determinism"
    first: str | None
    second: str | None


@dataclass(frozen=True)
class InvariantSampleReport:
    sampled: int
    violations: tuple[InvariantViolation, ...]

    @property
    def is_clean(self) -> bool:
        return not self.violations


def sample_and_check(
    dispatcher: Dispatcher,
    semantic_type: FieldSemanticType,
    ctx: NormalizationContext,
    profile: NormalizationProfile,
    *,
    originals: Sequence[str | None],
    results: Sequence[NormalizedValue],
    sample_rate: float = 0.2,
    max_sample: int = _DEFAULT_MAX_SAMPLE,
    seed: int | None = None,
) -> InvariantSampleReport:
    """Samples up to `max_sample` values from a already-computed batch and
    re-runs the dispatcher to verify idempotency/determinism against the
    LIVE dispatcher/profile, not just re-checking stored data."""
    if len(originals) != len(results):
        msg = f"originals ({len(originals)}) and results ({len(results)}) must be the same length"
        raise ValueError(msg)

    candidate_indexes = [i for i, o in enumerate(originals) if o not in (None, "")]
    sample_size = min(max_sample, max(0, round(len(candidate_indexes) * sample_rate)))
    rng = random.Random(seed)
    sampled_indexes = rng.sample(candidate_indexes, sample_size) if candidate_indexes else []

    violations: list[InvariantViolation] = []
    for idx in sampled_indexes:
        original = originals[idx]
        first_result = results[idx]

        determinism_repeat = dispatcher.normalize(original, semantic_type, ctx, profile)
        if determinism_repeat.display != first_result.display:
            violations.append(
                InvariantViolation(
                    original=original,
                    kind="determinism",
                    first=first_result.display,
                    second=determinism_repeat.display,
                )
            )

        if first_result.display is not None:
            idempotency_repeat = dispatcher.normalize(
                first_result.display, semantic_type, ctx, profile
            )
            if idempotency_repeat.display != first_result.display:
                violations.append(
                    InvariantViolation(
                        original=original,
                        kind="idempotency",
                        first=first_result.display,
                        second=idempotency_repeat.display,
                    )
                )

    return InvariantSampleReport(sampled=len(sampled_indexes), violations=tuple(violations))
