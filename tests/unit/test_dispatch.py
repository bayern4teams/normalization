"""Proves the dispatch layer end-to-end: registry lookup, semantic-type
mismatch guard, error-policy routing on NormalizerFailure, and that
profile_version/env_id get stamped by the dispatcher (never trusted from
the normalizer, per the design note in normcore.dispatch).
"""

from __future__ import annotations

import pytest
from normalizers.passthrough import PassthroughNormalizer
from normcore.enums import MissingKind
from normcore.interfaces import Normalizer
from normcore.models import NormalizedValue

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
    return NormalizationContext(**defaults)  # type: ignore[arg-type]


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

    def normalize_batch(self, values: object, ctx: object) -> object:
        raise NotImplementedError

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

        def normalize_batch(self, values: object, ctx: object) -> object:
            raise NotImplementedError

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


@pytest.mark.unit
class TestMissingSentinels:
    """Sentinel recognition ("N/A", "unknown", "-") lived inside
    GenericTextNormalizer, so it applied to FREE_TEXT alone — every other
    semantic type reported a sentinel as a hard parse failure. The
    dispatcher is where all types converge, so the check belongs there.
    """

    @staticmethod
    def _dispatcher(**kwargs: object) -> Dispatcher:
        registry = NormalizerRegistry()
        registry.register(PassthroughNormalizer())
        return Dispatcher(registry, env_id="test-env", **kwargs)  # type: ignore[arg-type]

    @classmethod
    def _with_sentinels(cls) -> Dispatcher:
        return cls._dispatcher(
            missing_sentinels={"n/a": "NOT_APPLICABLE", "unknown": "UNKNOWN_VALUE"}
        )

    @pytest.mark.parametrize(
        ("value", "kind"),
        [
            ("N/A", MissingKind.NOT_APPLICABLE),
            ("n/a", MissingKind.NOT_APPLICABLE),
            ("  N/A  ", MissingKind.NOT_APPLICABLE),
            ("Unknown", MissingKind.UNKNOWN_VALUE),
        ],
    )
    def test_sentinel_is_missing_not_invalid(self, value: str, kind: MissingKind) -> None:
        result = self._with_sentinels().normalize(
            value, FieldSemanticType.PERSON_NAME, _context(), _profile()
        )
        assert result.original_kind is kind
        assert result.validation_status == "MISSING"

    def test_ordinary_value_is_untouched(self) -> None:
        result = self._with_sentinels().normalize(
            "real value", FieldSemanticType.PERSON_NAME, _context(), _profile()
        )
        assert result.original_kind is None

    def test_sentinel_inside_a_list_cell_is_per_element(self) -> None:
        """The check sits in the per-value path, so a list cell gets it
        element by element rather than only for the cell as a whole."""
        result = self._with_sentinels().normalize(
            '["N/A", "real"]', FieldSemanticType.PERSON_NAME, _context(), _profile()
        )
        assert result.structured["element_count"] == 2

    def test_no_sentinels_configured_changes_nothing(self) -> None:
        result = self._dispatcher().normalize(
            "N/A", FieldSemanticType.PERSON_NAME, _context(), _profile()
        )
        assert result.original_kind is None

    def test_sentinel_result_is_stamped_like_any_other(self) -> None:
        """The early return must not skip the profile_version/env_id
        stamping every other path gets."""
        result = self._with_sentinels().normalize(
            "N/A", FieldSemanticType.PERSON_NAME, _context(), _profile()
        )
        assert result.env_id == "test-env"
        assert result.profile_version == "v3"
