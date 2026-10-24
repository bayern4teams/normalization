"""Shared scorer for the D1-D12 acceptance fixtures (plan 2.7, 8 Phase 0 step 4).

"Completed is not evidence": an engine is judged only by comparing what it
emitted to planted ground truth. Five outcomes, so a metric can never be
improved by guessing (a confident wrong value is named, not hidden) or by
abstaining on everything (a needless abstention is named too).

`classify` and `score` are pure. `real_engine` is the one function that runs
the project's own dispatcher; it is the only place that touches the registry.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Literal

from normapi.app import build_dispatcher
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.context import NormalizationContext
from normcore.dispatch import Dispatcher
from normcore.enums import FieldSemanticType, NormalizationStatus

Outcome = Literal["correct", "correct-abstain", "wrong-confident", "over-abstain", "wrong-status"]

# Statuses that mean "the engine emitted a value and stands behind it".
# AMBIGUOUS is the abstention; INVALID/FAILED/PARTIAL/NEEDS_REVIEW are neither
# (NEEDS_REVIEW has no producer today - D12 - so it is not "clean").
CLEAN_STATUSES = frozenset(
    {
        NormalizationStatus.NORMALIZED,
        NormalizationStatus.UNCHANGED,
        NormalizationStatus.REPAIRED,
        NormalizationStatus.PARSED,
    }
)


@dataclass(frozen=True)
class Case:
    id: str
    semantic_type: str  # SemanticType member name, e.g. "PHONE"
    input: str
    expected: Literal["clean", "abstain", "invalid"]
    expected_value: str | None = None  # canonical value when expected == "clean"
    candidates: frozenset[str] | None = None  # known candidate set when expected == "abstain"
    context: Mapping[str, str] = field(default_factory=dict)  # e.g. {"country": "DE"}


def classify(case: Case, status: NormalizationStatus, value: str | None) -> Outcome:
    clean = status in CLEAN_STATUSES
    if case.expected == "clean":
        if clean:
            return "correct" if value == case.expected_value else "wrong-confident"
        return "over-abstain" if status is NormalizationStatus.AMBIGUOUS else "wrong-status"
    if case.expected == "abstain":
        if clean:
            return "wrong-confident"
        return "correct-abstain" if status is NormalizationStatus.AMBIGUOUS else "wrong-status"
    # expected == "invalid": the engine must say so, not emit a value and not abstain
    if clean:
        return "wrong-confident"
    return "correct" if status is NormalizationStatus.INVALID else "wrong-status"


def score(
    cases: Iterable[Case],
    engine: Callable[[Case], tuple[NormalizationStatus, str | None]],
) -> Counter[Outcome]:
    return Counter(classify(c, *engine(c)) for c in cases)


@cache
def _dispatcher() -> Dispatcher:
    return build_dispatcher(env_id="defects-fixtures")


def real_engine(case: Case) -> tuple[NormalizationStatus, str | None]:
    """Run the real dispatcher + registry for `case.semantic_type` in `case.context`.

    The emitted value is the `comparison` view (E.164, ISO date, canonical
    amount, cleaned identifier): the key entity resolution matches on, so the
    one a wrong answer would corrupt. `display` is the fallback when a
    normalizer fills no comparison view.

    Abstention vocabulary: a TAX_ID whose result carries validation_status
    UNKNOWN (D7 "unverifiable") or AMBIGUOUS is reported as AMBIGUOUS, since
    the Engine signature has no validation channel and "I could not check" must
    be distinguishable from "checked and valid" (today an unlisted country
    comes back NORMALIZED/VALID, which is exactly the D7 defect).
    """
    sem = FieldSemanticType[case.semantic_type]
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    ctx = NormalizationContext(field_name="f", semantic_type=sem, **dict(case.context))  # type: ignore[arg-type]
    result = _dispatcher().normalize(case.input, sem, ctx, SCAFFOLD_PROFILE)
    status = result.normalization_status
    if status in CLEAN_STATUSES and result.validation_status in {"UNKNOWN", "AMBIGUOUS"}:
        status = NormalizationStatus.AMBIGUOUS
    return status, result.comparison if result.comparison is not None else result.display
