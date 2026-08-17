"""The normalization dispatcher — Source.txt §100, §101.

There is deliberately no `normalize_string(value)` anywhere in this
codebase. The only entrypoint is a Dispatcher bound to a specific registry
and environment, exposing `normalize(value, semantic_type, context,
profile)`. Semantic-type routing, error-policy application, and
env_id/profile_version stamping all happen here, once, rather than being
re-implemented per normalizer.
"""

from __future__ import annotations

from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from normcore.errors import NormalizerFailure, apply_error_policy
from normcore.interfaces import Normalizer
from normcore.models import NormalizedValue
from normcore.rules import NormalizationProfile


class NoNormalizerRegisteredError(RuntimeError):
    """Raised when no Normalizer is registered for a semantic type.

    This is a system configuration error (a profile references a semantic
    type the running process has no adapter for), NOT a per-value error —
    it is never caught by ErrorPolicy and always propagates, because
    silently falling back to some generic behavior here would be exactly
    the "universal clean function" Source.txt §100 forbids.
    """


class NormalizerRegistry:
    """Maps FieldSemanticType -> Normalizer instance.

    One registry per running process (or per test), constructed once and
    reused — Normalizer instances themselves may hold expensive-to-build
    state (compiled ICU transliterators, dictionary lookups), so the
    registry is where "construct once, reuse across the whole distinct-value
    batch" (ADR-016) is anchored.
    """

    def __init__(self) -> None:
        self._normalizers: dict[FieldSemanticType, Normalizer] = {}

    def register(self, normalizer: Normalizer) -> None:
        for semantic_type in normalizer.supported_types:
            self._normalizers[semantic_type] = normalizer

    def get(self, semantic_type: FieldSemanticType) -> Normalizer | None:
        return self._normalizers.get(semantic_type)

    def require(self, semantic_type: FieldSemanticType) -> Normalizer:
        normalizer = self.get(semantic_type)
        if normalizer is None:
            msg = f"No Normalizer registered for semantic type {semantic_type!r}"
            raise NoNormalizerRegisteredError(msg)
        return normalizer


class Dispatcher:
    """Bound to one `NormalizerRegistry` and one `env_id` (computed once
    per run/process, per ADR-014 — never recomputed per value).
    """

    def __init__(self, registry: NormalizerRegistry, *, env_id: str) -> None:
        self._registry = registry
        self._env_id = env_id

    @property
    def env_id(self) -> str:
        """Public so callers building cache keys (normexec) don't need to
        track env_id separately from the Dispatcher that stamps it."""
        return self._env_id

    def normalize(
        self,
        value: str | None,
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
        profile: NormalizationProfile,
    ) -> NormalizedValue:
        """The one entrypoint. `context.semantic_type` must match
        `semantic_type` — both are required explicitly (rather than reading
        semantic_type off context alone) so a call site cannot accidentally
        normalize a value against a context built for a different field.
        """
        if context.semantic_type is not semantic_type:
            msg = (
                f"semantic_type argument ({semantic_type!r}) does not match "
                f"context.semantic_type ({context.semantic_type!r})"
            )
            raise ValueError(msg)

        normalizer = self._registry.require(semantic_type)

        try:
            result = normalizer.normalize(value, context)
        except NormalizerFailure as exc:
            output_value, status_str = apply_error_policy(
                context.error_policy, original_value=value
            )
            return NormalizedValue(
                original=value,
                display=output_value,
                normalization_status=NormalizationStatus(status_str),
                errors=[str(exc)],
                profile_version=profile.version,
                env_id=self._env_id,
                semantic_type=semantic_type,
                context_hash=context.context_hash,
            )

        # profile_version and env_id are run-level bookkeeping a Normalizer
        # implementation has no way to know (NormalizationContext carries
        # neither) — the dispatcher stamps them here, once, so every
        # Normalizer author is relieved of getting this right. context_hash
        # IS derivable from `context` alone, so a mismatch there indicates
        # an actual normalizer bug worth catching rather than silently
        # overwriting (ADR-014's byte-identical replay guarantee depends on
        # context_hash being correct, not just present).
        if result.context_hash != context.context_hash:
            msg = (
                f"Normalizer {normalizer.name!r} returned context_hash "
                f"{result.context_hash!r}, expected {context.context_hash!r} "
                f"(derived from the same NormalizationContext passed in)"
            )
            raise AssertionError(msg)

        return result.model_copy(
            update={"profile_version": profile.version, "env_id": self._env_id}
        )
