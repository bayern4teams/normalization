"""Proves the dispatch layer end-to-end: registry lookup, semantic-type
mismatch guard, error-policy routing on NormalizerFailure, and that
profile_version/env_id get stamped by the dispatcher (never trusted from
the normalizer, per the design note in normcore.dispatch).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from normalizers.passthrough import PassthroughNormalizer
from normcore.interfaces import Normalizer
from normcore.models import NormalizedValue

if TYPE_CHECKING:
    from collections.abc import Sequence

from normcore import (
    Dispatcher,
    ErrorPolicy,
    FieldSemanticType,
    NoNormalizerRegisteredError,
    NormalizationContext,
    NormalizationProfile,
    NormalizationStatus,
    NormalizerFailure,
    NormalizerRegistry,
)


def _profile() -> NormalizationProfile:
    return NormalizationProfile(
        id="p1",
        name="test",
        version="v3",
        created_at="2026-08-17T00:00:00Z",
        updated_at="2026-08-17T00:00:00Z",
        created_by="test",
    )


def _context(**overrides: object) -> NormalizationContext:
    defaults: dict[str, object] = {
        "field_name": "first_name",
        "semantic_type": FieldSemanticType.PERSON_NAME,
    }
    defaults.update(overrides)
    return NormalizationContext(**defaults)


@pytest.mark.unit
def test_dispatcher_stamps_profile_version_and_env_id() -> None:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    dispatcher = Dispatcher(registry, env_id="e" * 64)

    profile = _profile()
    ctx = _context()
    result = dispatcher.normalize("  John  ", FieldSemanticType.PERSON_NAME, ctx, profile)

    assert result.profile_version == "v3"
    assert result.env_id == "e" * 64
    assert result.context_hash == ctx.context_hash
    assert result.original == "  John  "


@pytest.mark.unit
def test_dispatcher_raises_on_semantic_type_mismatch() -> None:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    dispatcher = Dispatcher(registry, env_id="e" * 64)

    ctx = _context(semantic_type=FieldSemanticType.EMAIL)
    with pytest.raises(ValueError, match="does not match"):
        dispatcher.normalize("x", FieldSemanticType.PERSON_NAME, ctx, _profile())


@pytest.mark.unit
def test_dispatcher_raises_when_no_normalizer_registered() -> None:
    registry = NormalizerRegistry()  # empty
    dispatcher = Dispatcher(registry, env_id="e" * 64)

    ctx = _context()
    with pytest.raises(NoNormalizerRegisteredError):
        dispatcher.normalize("x", FieldSemanticType.PERSON_NAME, ctx, _profile())


class _AlwaysFailsNormalizer:
    name = "AlwaysFails"
    supported_types = frozenset({FieldSemanticType.PERSON_NAME})

    def can_handle(self, field_type: object, ctx: object) -> bool:
        return True

    def normalize(self, value: str | None, ctx: object) -> object:
        raise NormalizerFailure("boom", operation="test_failure")

    def validate(self, value: object, ctx: object) -> object:
        raise NotImplementedError

    def explain(self, result: object) -> object:
        raise NotImplementedError

    def version(self) -> object:
        raise NotImplementedError

    def steps(self) -> object:
        return ()

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("policy", "expected_status", "expected_value"),
    [
        (ErrorPolicy.RETURN_ORIGINAL, NormalizationStatus.INVALID, "raw"),
        (ErrorPolicy.RETURN_NULL, NormalizationStatus.INVALID, None),
        (ErrorPolicy.MARK_INVALID, NormalizationStatus.INVALID, "raw"),
        (ErrorPolicy.SKIP_FIELD, NormalizationStatus.FAILED, "raw"),
        (ErrorPolicy.FAIL_RECORD, NormalizationStatus.FAILED, "raw"),
    ],
)
def test_dispatcher_applies_every_error_policy_on_normalizer_failure(
    policy: ErrorPolicy, expected_status: NormalizationStatus, expected_value: str | None
) -> None:
    registry = NormalizerRegistry()
    registry.register(_AlwaysFailsNormalizer())  # type: ignore[arg-type]
    dispatcher = Dispatcher(registry, env_id="e" * 64)

    ctx = _context(error_policy=policy)
    result = dispatcher.normalize("raw", FieldSemanticType.PERSON_NAME, ctx, _profile())

    assert result.normalization_status is expected_status
    assert result.display == expected_value
    # Source.txt §1: original is NEVER dropped, regardless of policy
    assert result.original == "raw"
    assert "boom" in result.errors[0]


@pytest.mark.unit
def test_dispatcher_rejects_context_hash_mismatch_from_a_buggy_normalizer() -> None:
    class _BuggyNormalizer:
        name = "Buggy"
        supported_types = frozenset({FieldSemanticType.PERSON_NAME})

        def can_handle(self, field_type: object, ctx: object) -> bool:
            return True

        def normalize(self, value: str | None, ctx: NormalizationContext) -> object:
            return NormalizedValue(
                original=value,
                normalization_status=NormalizationStatus.UNCHANGED,
                profile_version="",
                env_id="",
                semantic_type=ctx.semantic_type,
                context_hash="wrong-hash",  # bug: should be ctx.context_hash
            )

        def validate(self, value: object, ctx: object) -> object:
            raise NotImplementedError

        def explain(self, result: object) -> object:
            raise NotImplementedError

        def version(self) -> object:
            raise NotImplementedError

        def steps(self) -> object:
            return ()

        def inverse(self, step_id: str, value: str) -> str | None:
            return None

    registry = NormalizerRegistry()
    registry.register(_BuggyNormalizer())  # type: ignore[arg-type]
    dispatcher = Dispatcher(registry, env_id="e" * 64)

    with pytest.raises(AssertionError, match="context_hash"):
        dispatcher.normalize("x", FieldSemanticType.PERSON_NAME, _context(), _profile())


@pytest.mark.unit
def test_registry_requires_normalizer_to_be_actual_normalizer_protocol() -> None:
    passthrough = PassthroughNormalizer()
    assert isinstance(passthrough, Normalizer)


class _BatchNormalizer:
    """Phase 3 item 5: a minimal `BatchCapableNormalizer` test double —
    `normalize_many` is a real batch entrypoint (one call for the whole
    list), opt-in and separate from the required `Normalizer.normalize`
    every normalizer implements."""

    name = "Batch"
    supported_types = frozenset({FieldSemanticType.PERSON_NAME})

    def __init__(self, *, fail_whole_batch: bool = False, wrong_length: bool = False) -> None:
        self.batch_call_count = 0
        self._fail_whole_batch = fail_whole_batch
        self._wrong_length = wrong_length

    def can_handle(self, field_type: object, ctx: object) -> bool:
        return True

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        return NormalizedValue(
            original=value,
            display=f"scalar:{value}",
            normalization_status=NormalizationStatus.UNCHANGED,
            profile_version="",
            env_id="",
            semantic_type=ctx.semantic_type,
            context_hash=ctx.context_hash,
        )

    def normalize_many(
        self, values: Sequence[str | None], ctx: NormalizationContext
    ) -> list[NormalizedValue]:
        self.batch_call_count += 1
        if self._fail_whole_batch:
            raise NormalizerFailure("batch boom", operation="test_batch_failure")
        values_list = list(values)
        results = [
            NormalizedValue(
                original=v,
                display=f"batch:{v}",
                normalization_status=NormalizationStatus.UNCHANGED,
                profile_version="",
                env_id="",
                semantic_type=ctx.semantic_type,
                context_hash=ctx.context_hash,
            )
            for v in values_list
        ]
        return results[:-1] if self._wrong_length and results else results

    def validate(self, value: object, ctx: object) -> object:
        raise NotImplementedError

    def explain(self, result: object) -> object:
        raise NotImplementedError

    def version(self) -> object:
        raise NotImplementedError

    def steps(self) -> object:
        return ()

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


@pytest.mark.unit
class TestDispatcherNormalizeMany:
    def test_non_batch_capable_normalizer_falls_back_to_per_value_loop(self) -> None:
        registry = NormalizerRegistry()
        registry.register(PassthroughNormalizer())
        dispatcher = Dispatcher(registry, env_id="e" * 64)
        ctx = _context()

        results = dispatcher.normalize_many(
            ["a", "b"], FieldSemanticType.PERSON_NAME, ctx, _profile()
        )
        expected = [
            dispatcher.normalize(v, FieldSemanticType.PERSON_NAME, ctx, _profile())
            for v in ["a", "b"]
        ]
        assert [r.display for r in results] == [r.display for r in expected]

    def test_batch_capable_normalizer_makes_exactly_one_call(self) -> None:
        normalizer = _BatchNormalizer()
        registry = NormalizerRegistry()
        registry.register(normalizer)  # type: ignore[arg-type]
        dispatcher = Dispatcher(registry, env_id="e" * 64)
        ctx = _context()

        results = dispatcher.normalize_many(
            ["a", "b", "c"], FieldSemanticType.PERSON_NAME, ctx, _profile()
        )

        assert normalizer.batch_call_count == 1
        assert [r.display for r in results] == ["batch:a", "batch:b", "batch:c"]

    def test_batch_results_get_profile_version_and_env_id_stamped(self) -> None:
        registry = NormalizerRegistry()
        registry.register(_BatchNormalizer())  # type: ignore[arg-type]
        dispatcher = Dispatcher(registry, env_id="e" * 64)

        results = dispatcher.normalize_many(
            ["a"], FieldSemanticType.PERSON_NAME, _context(), _profile()
        )

        assert results[0].profile_version == "v3"
        assert results[0].env_id == "e" * 64

    def test_whole_batch_failure_falls_back_to_per_value_retry(self) -> None:
        normalizer = _BatchNormalizer(fail_whole_batch=True)
        registry = NormalizerRegistry()
        registry.register(normalizer)  # type: ignore[arg-type]
        dispatcher = Dispatcher(registry, env_id="e" * 64)

        results = dispatcher.normalize_many(
            ["a", "b"], FieldSemanticType.PERSON_NAME, _context(), _profile()
        )

        # Falls back to normalize() per value — _BatchNormalizer.normalize()
        # succeeds unconditionally (only normalize_many is rigged to fail).
        assert [r.display for r in results] == ["scalar:a", "scalar:b"]

    def test_wrong_length_batch_result_raises(self) -> None:
        registry = NormalizerRegistry()
        registry.register(_BatchNormalizer(wrong_length=True))  # type: ignore[arg-type]
        dispatcher = Dispatcher(registry, env_id="e" * 64)

        with pytest.raises(AssertionError, match="results for"):
            dispatcher.normalize_many(
                ["a", "b"], FieldSemanticType.PERSON_NAME, _context(), _profile()
            )

    def test_semantic_type_mismatch_raises_same_as_normalize(self) -> None:
        registry = NormalizerRegistry()
        registry.register(_BatchNormalizer())  # type: ignore[arg-type]
        dispatcher = Dispatcher(registry, env_id="e" * 64)
        ctx = _context(semantic_type=FieldSemanticType.EMAIL)

        with pytest.raises(ValueError, match="does not match"):
            dispatcher.normalize_many(["x"], FieldSemanticType.PERSON_NAME, ctx, _profile())

    def test_empty_values_returns_empty_list_without_calling_the_batch(self) -> None:
        normalizer = _BatchNormalizer()
        registry = NormalizerRegistry()
        registry.register(normalizer)  # type: ignore[arg-type]
        dispatcher = Dispatcher(registry, env_id="e" * 64)

        results = dispatcher.normalize_many(
            [], FieldSemanticType.PERSON_NAME, _context(), _profile()
        )

        assert results == []
        assert normalizer.batch_call_count == 0
