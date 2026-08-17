"""Wraps a `Dispatcher.normalize()` call with a trace span + metrics —
Source.txt §122. Kept separate from `normcore.dispatch.Dispatcher` itself
so normcore never depends on OpenTelemetry (see telemetry.py's module
docstring for the layering rationale).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from normcore.enums import FieldSemanticType

    from normanalysis.telemetry import NormalizationMetrics, TelemetryHandles
    from normcore import Dispatcher, NormalizationContext, NormalizationProfile, NormalizedValue


def instrumented_normalize(
    handles: TelemetryHandles,
    metrics: NormalizationMetrics,
    dispatcher: Dispatcher,
    *,
    value: str | None,
    semantic_type: FieldSemanticType,
    context: NormalizationContext,
    profile: NormalizationProfile,
) -> NormalizedValue:
    with handles.tracer.start_as_current_span(
        "normalization.normalize",
        attributes={
            "normalization.semantic_type": semantic_type.value,
            "normalization.field_name": context.field_name,
            "normalization.profile_version": profile.version,
        },
    ) as span:
        start = time.perf_counter()
        result = dispatcher.normalize(value, semantic_type, context, profile)
        duration = time.perf_counter() - start

        changed = result.normalization_status.value != "UNCHANGED"
        metrics.values_processed.add(1, {"semantic_type": semantic_type.value})
        if changed:
            metrics.values_changed.add(1, {"semantic_type": semantic_type.value})
        metrics.normalize_duration.record(duration, {"semantic_type": semantic_type.value})

        span.set_attribute("normalization.status", result.normalization_status.value)
        span.set_attribute("normalization.changed", changed)
        span.set_attribute("normalization.duration_s", duration)

        return result
