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
from normcore.interfaces import BatchCapableNormalizer, Normalizer
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

    @property
    def registry(self) -> NormalizerRegistry:
        """Public read-only access to the bound registry — callers that
        need to introspect which normalizer handles a semantic type
        (§61 field-type detection, §62/§84 profile suggestion) without
        reaching into a private attribute across a package boundary."""
        return self._registry

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
            return self._failure_result(exc, value, context, profile)

        return self._finalize(result, normalizer, context, profile)

    def normalize_many(
        self,
        values: list[str | None],
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
        profile: NormalizationProfile,
    ) -> list[NormalizedValue]:
        """Phase 3 item 5 of the throughput/memory program (2026-08-29):
        the real batch entrypoint `DistinctValuePlanner._compute_serial`
        uses instead of a per-value `normalize()` loop, when — and only
        when — the resolved normalizer implements `BatchCapableNormalizer`
        (today: `AddressNormalizer` only). Every other semantic type
        falls back to exactly the same per-value loop this method
        replaces, so this is a no-op change in behavior or call count
        for 19 of the 20 registered normalizers.

        Same per-result contract as `normalize()` (context_hash
        assertion, profile_version/env_id stamping, NormalizerFailure
        handling) — factored into `_finalize`/`_failure_result` so both
        methods apply it identically rather than duplicating it.
        """
        if context.semantic_type is not semantic_type:
            msg = (
                f"semantic_type argument ({semantic_type!r}) does not match "
                f"context.semantic_type ({context.semantic_type!r})"
            )
            raise ValueError(msg)
        if not values:
            return []

        normalizer = self._registry.require(semantic_type)
        if not isinstance(normalizer, BatchCapableNormalizer):
            return [self.normalize(v, semantic_type, context, profile) for v in values]

        try:
            raw_results = normalizer.normalize_many(values, context)
        except NormalizerFailure:
            # A batch-capable normalizer's real batch call failed as a
            # WHOLE (e.g. the one HTTP call itself errored, rather than
            # any single value being unparsable — a single value's own
            # failure is expected to come back as a normal per-value
            # result, not an exception, exactly like `normalize()`).
            # Falling back to the per-value path re-attempts each value
            # independently rather than failing every value in the batch
            # for what might have been a transient, single-call problem.
            return [self.normalize(v, semantic_type, context, profile) for v in values]

        if len(raw_results) != len(values):
            msg = (
                f"Normalizer {normalizer.name!r}.normalize_many returned "
                f"{len(raw_results)} results for {len(values)} input values"
            )
            raise AssertionError(msg)
        return [self._finalize(result, normalizer, context, profile) for result in raw_results]

    def _failure_result(
        self,
        exc: NormalizerFailure,
        value: str | None,
        context: NormalizationContext,
        profile: NormalizationProfile,
    ) -> NormalizedValue:
        output_value, status_str = apply_error_policy(context.error_policy, original_value=value)
        return NormalizedValue(
            original=value,
            display=output_value,
            normalization_status=NormalizationStatus(status_str),
            errors=[str(exc)],
            profile_version=profile.version,
            env_id=self._env_id,
            semantic_type=context.semantic_type,
            context_hash=context.context_hash,
        )

    def _finalize(
        self,
        result: NormalizedValue,
        normalizer: Normalizer,
        context: NormalizationContext,
        profile: NormalizationProfile,
    ) -> NormalizedValue:
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

        # Phase 2 (2026-08-29 throughput program): was
        # `result.model_copy(update={...})`, which builds a SECOND
        # NormalizedValue per value (every normalizer already builds one,
        # with profile_version/env_id as "" placeholders — see e.g.
        # normalizers/boolean.py) — measured 3.81 µs/value of pure
        # redundant construction. `NormalizedValue` (unlike most other
        # domain models in this codebase) is NOT `frozen=True`, so
        # stamping these two fields directly onto the same object is a
        # plain attribute assignment, not a frozen-model workaround.
        # Changing the `Normalizer` Protocol instead, so every
        # implementation builds the final object directly (the
        # alternative the plan considered), would touch all 20
        # normalizer files' every `NormalizedValue` construction site
        # for the same 3.81 µs/value — not a good trade for the risk.
        result.profile_version = profile.version
        result.env_id = self._env_id
        return result
