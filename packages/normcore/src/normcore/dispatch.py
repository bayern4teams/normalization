"""The normalization dispatcher — Source.txt §100, §101.

There is deliberately no `normalize_string(value)` anywhere in this
codebase. The only entrypoint is a Dispatcher bound to a specific registry
and environment, exposing `normalize(value, semantic_type, context,
profile)`. Semantic-type routing, error-policy application, and
env_id/profile_version stamping all happen here, once, rather than being
re-implemented per normalizer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from normcore import multivalue
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    Reversibility,
)
from normcore.errors import NormalizerFailure, apply_error_policy
from normcore.interfaces import Normalizer
from normcore.models import NormalizedValue
from normcore.pii import sanitize_surrogates
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

    def __init__(
        self,
        registry: NormalizerRegistry,
        *,
        env_id: str,
        missing_sentinels: Mapping[str, str] | None = None,
    ) -> None:
        self._registry = registry
        self._env_id = env_id
        # Recognizing "N/A"/"unknown"/"-" as MISSING rather than INVALID
        # was implemented only inside GenericTextNormalizer, so it applied
        # to FREE_TEXT and nothing else — every other semantic type
        # reported a sentinel as a hard parse failure. It belongs here
        # instead: this is the one place every semantic type converges, so
        # one check covers all of them. Injected rather than loaded,
        # because normcore deliberately has no dependencies and the
        # dictionary lives in normdict.
        self._missing_sentinels = dict(missing_sentinels or {})

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

        # Sanitize once, here, before any normalizer or trace/cache-key
        # hashing ever sees `value` — found via live testing that a lone
        # UTF-16 surrogate crashed the whole pipeline downstream (not
        # caught as a per-value NormalizerFailure), since it can't be
        # UTF-8 encoded at all. This is the one place every call path
        # (direct dispatch, and the distinct-value planner on a cache
        # miss) converges before producing a NormalizedValue.
        if value is not None:
            value = sanitize_surrogates(value)

        normalizer = self._registry.require(semantic_type)

        # One cell, many values. Sources routinely park a serialized list
        # in a text column; without this every such row fails as a single
        # malformed value, which is both wrong and drowns the real errors.
        # Handled here rather than in each normalizer because this is the
        # one place every call path converges (direct dispatch and the
        # distinct-value planner's cache miss alike), so every semantic
        # type gets it for free and none of them has to know about it.
        if value is not None:
            elements = multivalue.split(value)
            if elements is not None:
                return self._normalize_elements(
                    value,
                    elements,
                    normalizer=normalizer,
                    semantic_type=semantic_type,
                    context=context,
                    profile=profile,
                )

        return self._normalize_one(
            value,
            normalizer=normalizer,
            semantic_type=semantic_type,
            context=context,
            profile=profile,
        )

    def _normalize_elements(
        self,
        value: str,
        elements: tuple[list[str | None], str],
        *,
        normalizer: Normalizer,
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
        profile: NormalizationProfile,
    ) -> NormalizedValue:
        items, style = elements
        results = [
            self._normalize_one(
                item,
                normalizer=normalizer,
                semantic_type=semantic_type,
                context=context,
                profile=profile,
            )
            for item in items
        ]

        def view(field: str) -> str | None:
            values = [getattr(r, field) for r in results]
            # A view no element produced stays absent, rather than becoming
            # a list of nulls that looks like real content.
            if values and all(v is None for v in values):
                return None
            return multivalue.join(values, style)

        confidences = [r.confidence for r in results if r.confidence is not None]
        trace = [
            step.model_copy(update={"step_order": order})
            for order, step in enumerate(
                (step for r in results for step in r.trace), start=1
            )
        ]
        return NormalizedValue(
            original=value,
            display=view("display"),
            comparison=view("comparison"),
            search=view("search"),
            structured={
                "element_count": len(results),
                "elements": [r.structured for r in results],
            },
            validation_status=_worst(r.validation_status for r in results),
            normalization_status=_worst_status(r.normalization_status for r in results),
            confidence=min(confidences) if confidences else None,
            flags=list(dict.fromkeys(flag for r in results for flag in r.flags)),
            warnings=[w for r in results for w in r.warnings],
            errors=[
                f"element {i}: {error}"
                for i, r in enumerate(results)
                for error in r.errors
            ],
            trace=trace,
            lossiness=_worst_lossiness(r.lossiness for r in results),
            profile_version=profile.version,
            env_id=self._env_id,
            semantic_type=semantic_type,
            context_hash=context.context_hash,
        )

    def _normalize_one(
        self,
        value: str | None,
        *,
        normalizer: Normalizer,
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
        profile: NormalizationProfile,
    ) -> NormalizedValue:
        if value is not None:
            sentinel_kind = self._missing_sentinels.get(value.strip().casefold())
            if sentinel_kind is not None:
                return NormalizedValue(
                    original=value,
                    original_kind=MissingKind(sentinel_kind),
                    normalization_status=NormalizationStatus.NORMALIZED,
                    validation_status="MISSING",
                    confidence=1.0,
                    profile_version=profile.version,
                    env_id=self._env_id,
                    semantic_type=semantic_type,
                    context_hash=context.context_hash,
                )

        try:
            result = normalizer.normalize(value, context)
        except NormalizerFailure as exc:
            output_value, status_str = apply_error_policy(
                context.error_policy, original_value=value
            )
            # lossiness must be set explicitly here, not left to
            # NormalizedValue's own LOSSLESS default: found via live
            # testing that a failed/invalid value was silently stamped
            # "losslessly reversible" regardless of what actually
            # happened. RETURN_NULL policies genuinely discard real
            # content (value -> None), which is lossy by definition;
            # every other policy returns the original value unchanged,
            # which is exactly what LOSSLESS means, so it's derived here
            # rather than assumed for every outcome alike.
            lossiness = (
                Reversibility.LOSSY
                if output_value is None and value is not None
                else Reversibility.LOSSLESS
            )
            return NormalizedValue(
                original=value,
                display=output_value,
                normalization_status=NormalizationStatus(status_str),
                errors=[str(exc)],
                lossiness=lossiness,
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


# Aggregating a list-shaped cell: the cell is only as good as its worst
# element, so each of these collapses the elements by severity rather than
# by majority — a list with one unparseable member is not a clean cell.
_STATUS_SEVERITY: tuple[NormalizationStatus, ...] = (
    NormalizationStatus.UNCHANGED,
    NormalizationStatus.NORMALIZED,
    NormalizationStatus.REPAIRED,
    NormalizationStatus.PARSED,
    NormalizationStatus.PARTIAL,
    NormalizationStatus.NEEDS_REVIEW,
    NormalizationStatus.AMBIGUOUS,
    NormalizationStatus.INVALID,
    NormalizationStatus.FAILED,
)
_VALIDATION_SEVERITY: tuple[str, ...] = ("VALID", "MISSING", "UNKNOWN", "AMBIGUOUS", "INVALID")
_LOSSINESS_SEVERITY: tuple[Reversibility, ...] = (
    Reversibility.LOSSLESS,
    Reversibility.REVERSIBLE,
    Reversibility.PARTIALLY_REVERSIBLE,
    Reversibility.LOSSY,
)


def _worst_by(order: tuple[object, ...], values: Iterable[object], default: object) -> object:
    ranked = [v for v in values if v in order]
    return max(ranked, key=order.index) if ranked else default


def _worst_status(values: Iterable[NormalizationStatus]) -> NormalizationStatus:
    return _worst_by(_STATUS_SEVERITY, values, NormalizationStatus.NORMALIZED)


def _worst(values: Iterable[str | None]) -> str | None:
    return _worst_by(_VALIDATION_SEVERITY, values, None)


def _worst_lossiness(values: Iterable[Reversibility]) -> Reversibility:
    return _worst_by(_LOSSINESS_SEVERITY, values, Reversibility.LOSSLESS)
