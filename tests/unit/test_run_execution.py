"""Unit tests for InMemoryStore.execute_run (M6) — real run execution
against a live Dispatcher, including the NormalizerFailure -> real
NormalizationError surfacing path (Source.txt §68, §69, §98
`/runs/{id}/errors`).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from normalizers.passthrough import PassthroughNormalizer
from normapi.app import create_app
from normapi.store import InMemoryStore, RunNotExecutableError, RunNotFoundError

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
class TestStartRunExecution:
    """M11: `start_run_execution` — the background-thread wrapper around
    `execute_run` used by the live HTTP route. `execute_run` itself is
    untouched (see TestExecuteRun above); these tests are scoped to the
    async wrapper's own contract: returns immediately, the run reaches
    COMPLETED/FAILED asynchronously, and a resolve_values failure becomes
    a real FAILED status with a reason rather than an unhandled crash."""

    def _wait_for_terminal(
        self, store: InMemoryStore, run_id: str, *, timeout: float = 5.0
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if store.get_run(run_id).is_terminal():
                return
            time.sleep(0.02)
        pytest.fail(f"Run {run_id} did not reach a terminal status within {timeout}s")

    def test_returns_immediately_without_blocking_on_execution(self) -> None:
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

        release = threading.Event()

        def slow_resolve_values() -> list[str | None]:
            release.wait(timeout=5.0)
            return ["a", "b"]

        started = time.monotonic()
        returned = store.start_run_execution(
            run.id,
            dispatcher=dispatcher,
            field_name="f",
            semantic_type=FieldSemanticType.UNKNOWN,
            resolve_values=slow_resolve_values,
        )
        elapsed = time.monotonic() - started

        assert elapsed < 1.0  # did not block on the 5s-capped resolve_values
        assert returned.status is RunStatus.PENDING  # real transition happens in the background
        release.set()
        self._wait_for_terminal(store, run.id)
        assert store.get_run(run.id).status is RunStatus.COMPLETED

    def test_reaches_completed_with_real_results_via_polling(self) -> None:
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

        store.start_run_execution(
            run.id,
            dispatcher=dispatcher,
            field_name="f",
            semantic_type=FieldSemanticType.UNKNOWN,
            resolve_values=lambda: ["a", "b", "a"],
        )
        self._wait_for_terminal(store, run.id)

        finished = store.get_run(run.id)
        assert finished.status is RunStatus.COMPLETED
        assert finished.metrics.records_processed == 3
        execution = store.get_execution(run.id)
        assert execution is not None
        assert execution.originals == ["a", "b", "a"]

    def test_resolve_values_failure_sets_failed_status_with_reason(self) -> None:
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

        def failing_resolve_values() -> list[str | None]:
            msg = "simulated connector outage"
            raise RuntimeError(msg)

        store.start_run_execution(
            run.id,
            dispatcher=dispatcher,
            field_name="f",
            semantic_type=FieldSemanticType.UNKNOWN,
            resolve_values=failing_resolve_values,
        )
        self._wait_for_terminal(store, run.id)

        finished = store.get_run(run.id)
        assert finished.status is RunStatus.FAILED
        assert finished.failure_reason == "simulated connector outage"
        assert finished.finished_at is not None

    def test_double_start_on_a_terminal_run_raises_synchronously(self) -> None:
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
        store.start_run_execution(
            run.id,
            dispatcher=dispatcher,
            field_name="f",
            semantic_type=FieldSemanticType.UNKNOWN,
            resolve_values=lambda: ["a"],
        )
        self._wait_for_terminal(store, run.id)

        with pytest.raises(RunNotExecutableError):
            store.start_run_execution(
                run.id,
                dispatcher=dispatcher,
                field_name="f",
                semantic_type=FieldSemanticType.UNKNOWN,
                resolve_values=lambda: ["b"],
            )


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

    # M11: execution is asynchronous — poll until the run leaves RUNNING
    # before checking /errors, instead of assuming the POST response
    # already reflects a completed run.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        status = client.get(f"/normalization/runs/{run['id']}").json()["status"]
        if status in ("COMPLETED", "FAILED", "PARTIAL"):
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"Run {run['id']} did not reach a terminal status in time")

    errors = client.get(f"/normalization/runs/{run['id']}/errors")
    assert errors.status_code == 200
    body = errors.json()
    assert len(body) == 2
    assert all(e["error"] == "boom" for e in body)
    assert all(e["field"] == "name" for e in body)
