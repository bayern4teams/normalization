"""Unit tests for InMemoryStore.execute_run (M6) — real run execution
against a live Dispatcher, including the NormalizerFailure -> real
NormalizationError surfacing path (Source.txt §68, §69, §98
`/runs/{id}/errors`).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from normalizers.passthrough import PassthroughNormalizer
from normapi.app import create_app
from normapi.store import InMemoryStore, RunNotFoundError

from normcore import (
    Dispatcher,
    ErrorPolicy,
    FieldSemanticType,
    NormalizationProfile,
    NormalizerFailure,
    NormalizerRegistry,
    RunStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pyarrow as pa
    from normcore.context import NormalizationContext
    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult
    from normcore.models import NormalizedValue

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


class _AlwaysFailsNormalizer:
    """Same test-double convention as tests/unit/test_dispatch.py's
    `_AlwaysFailsNormalizer` — a Normalizer that deterministically raises
    NormalizerFailure, since no real M2-M5 adapter fails under any valid
    (non-infra-outage) input, so this is the only way to exercise the
    error-surfacing path deterministically."""

    name = "AlwaysFails"
    supported_types = frozenset({FieldSemanticType.PERSON_NAME})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return True

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        raise NormalizerFailure("boom", operation="test_failure")

    def normalize_batch(self, values: pa.Array, ctx: NormalizationContext) -> pa.StructArray:
        raise NotImplementedError

    def validate(self, value: str | None, ctx: NormalizationContext) -> ValidationResult:
        raise NotImplementedError

    def explain(self, result: NormalizedValue) -> Explanation:
        raise NotImplementedError

    def version(self) -> ComponentVersion:
        raise NotImplementedError

    def steps(self) -> Sequence[StepSpec]:
        return []

    def inverse(self, step_id: str, value: str) -> None:
        return None


def _profile() -> NormalizationProfile:
    return NormalizationProfile(
        id="p1",
        name="test",
        version="v1",
        created_at="2026-08-17T00:00:00Z",
        updated_at="2026-08-17T00:00:00Z",
        created_by="test",
    )


@pytest.mark.unit
class TestExecuteRun:
    def test_execute_run_reaches_completed_with_real_metrics(self) -> None:
        store = InMemoryStore()
        registry = NormalizerRegistry()
        registry.register(PassthroughNormalizer())
        dispatcher = Dispatcher(registry, env_id="e" * 64)

        profile = store.create_profile(
            name="p",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        run = store.create_run(profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s")

        finished = store.execute_run(
            run.id,
            dispatcher=dispatcher,
            field_name="f",
            semantic_type=FieldSemanticType.UNKNOWN,
            values=["a", "b", "a"],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        assert finished.status is RunStatus.COMPLETED
        assert finished.metrics.records_processed == 3
        assert finished.metrics.fields_processed == 1

        execution = store.get_execution(run.id)
        assert execution is not None
        assert execution.originals == ["a", "b", "a"]
        assert len(execution.results) == 3

    def test_execute_run_surfaces_normalizer_failures_in_metrics(self) -> None:
        store = InMemoryStore()
        registry = NormalizerRegistry()
        registry.register(_AlwaysFailsNormalizer())
        dispatcher = Dispatcher(registry, env_id="e" * 64)

        profile = store.create_profile(
            name="p",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        run = store.create_run(profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s")

        finished = store.execute_run(
            run.id,
            dispatcher=dispatcher,
            field_name="name",
            semantic_type=FieldSemanticType.PERSON_NAME,
            values=["John", "Jane"],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        assert finished.metrics.errors == 2
        execution = store.get_execution(run.id)
        assert execution is not None
        assert all(r.errors == ["boom"] for r in execution.results)

    def test_get_execution_none_for_unexecuted_run(self) -> None:
        store = InMemoryStore()
        profile = store.create_profile(
            name="p",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        run = store.create_run(profile_id=profile.id, env_id="e" * 64, source_snapshot="s")
        assert store.get_execution(run.id) is None

    def test_get_execution_unknown_run_raises(self) -> None:
        store = InMemoryStore()
        with pytest.raises(RunNotFoundError):
            store.get_execution("nonexistent")


@pytest.mark.unit
def test_errors_route_surfaces_real_normalizer_failures(tmp_path: Path) -> None:
    """Full HTTP round-trip: /runs/{id}/errors returns real
    NormalizationError rows derived from an actual NormalizerFailure, not
    a hardcoded empty list."""
    app = create_app(
        dictionaries_dir=_DICT_ROOT, custom_dictionaries_dir=tmp_path / "custom-dictionaries"
    )
    # Swap in a failing double for PERSON_NAME on top of the real registry
    # so the live-server /errors route has something real to surface —
    # same test-double technique as test_dispatch.py, applied at the
    # already-constructed app's registry rather than a fresh one.
    app.state.dispatcher._registry.register(_AlwaysFailsNormalizer())

    client = TestClient(app)
    profile = client.post(
        "/normalization/profiles", json={"name": "p", "field_configs": [], "created_by": "u"}
    ).json()
    run = client.post(
        f"/normalization/runs?profile_id={profile['id']}&source_snapshot=s",
        json={"field_name": "name", "semantic_type": "PERSON_NAME", "values": ["John", "Jane"]},
    ).json()

    errors = client.get(f"/normalization/runs/{run['id']}/errors")
    assert errors.status_code == 200
    body = errors.json()
    assert len(body) == 2
    assert all(e["error"] == "boom" for e in body)
    assert all(e["field"] == "name" for e in body)
