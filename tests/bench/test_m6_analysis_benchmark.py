"""Performance baseline for M6's impact/collision/A-B analysis
functions (normanalysis) — Source.txt §102, §122; Gate G6 requirement.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from normalizers.generic_text import GenericTextNormalizer
from normcore.enums import FieldSemanticType

from normanalysis import compare_runs, compute_impact, find_collisions, profile_field
from normcore import NormalizationContext
from normdict import DictionaryLoader

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"
_BATCH_SIZE = 1000

_Batch = tuple[list[str], list[object]]


@pytest.fixture(scope="module")
def normalizer() -> GenericTextNormalizer:
    return GenericTextNormalizer(DictionaryLoader(_DICT_ROOT))


@pytest.fixture(scope="module")
def batch(normalizer: GenericTextNormalizer) -> _Batch:
    ctx = NormalizationContext(field_name="name", semantic_type=FieldSemanticType.FREE_TEXT)
    originals = [f"Value {i % (_BATCH_SIZE // 4)}" for i in range(_BATCH_SIZE)]
    results = [normalizer.normalize(v, ctx) for v in originals]
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    return originals, results  # type: ignore[return-value]


@pytest.mark.bench
def test_bench_compute_impact_1000_values(benchmark: object, batch: _Batch) -> None:
    originals, results = batch
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    benchmark(compute_impact, "name", originals, results)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_find_collisions_1000_values(benchmark: object, batch: _Batch) -> None:
    originals, results = batch
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    benchmark(find_collisions, originals, results)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_compare_runs_1000_values(benchmark: object, batch: _Batch) -> None:
    _, results = batch
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    benchmark(  # type: ignore[operator]
        compare_runs,
        "name",
        profile_version_a="v1",
        results_a=results,
        profile_version_b="v1",
        results_b=results,
    )


@pytest.mark.bench
def test_bench_profile_field_1000_values(benchmark: object, batch: _Batch) -> None:
    _, results = batch
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    benchmark(profile_field, "name", results)  # type: ignore[operator]
