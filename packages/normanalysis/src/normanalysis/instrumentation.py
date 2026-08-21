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
    from normcore import (
        Dispatcher,
        NormalizationContext,
        NormalizationProfile,
        NormalizationRunMetrics,
        NormalizedValue,
    )


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


def record_run_metrics(
    handles: TelemetryHandles,
    metrics: NormalizationMetrics,
    run_metrics: NormalizationRunMetrics,
    *,
    field_name: str,
    semantic_type: FieldSemanticType,
) -> None:
    """Exports a completed run's real counters — Source.txt §122 — as
    real OTel metrics/a real span. Bulk-recorded once at run completion
    rather than per-value: the live execution path
    (`InMemoryStore._normalize_deduped` -> `DistinctValuePlanner`) dedups
    on distinct values and calls `dispatcher.normalize()` directly, not
    through `instrumented_normalize` above — retrofitting per-value
    instrumentation into the planner's dedup logic would mean
    restructuring it, out of scope for wiring already-real, already-
    tested telemetry into the live app for the first time. The counters
    themselves are exactly as real either way: `run_metrics` already
    reflects genuine execution, not a placeholder.
    """
    attrs = {"semantic_type": semantic_type.value, "field_name": field_name}
    with handles.tracer.start_as_current_span("normalization.run", attributes=attrs) as span:
        metrics.values_processed.add(run_metrics.records_processed, attrs)
        metrics.values_changed.add(run_metrics.changed_values, attrs)
        metrics.values_unchanged.add(run_metrics.unchanged_values, attrs)
        metrics.parser_failures.add(run_metrics.parser_failures, attrs)
        metrics.validation_failures.add(run_metrics.validation_failures, attrs)
        metrics.library_calls.add(run_metrics.library_calls, attrs)
        metrics.cache_hits.add(run_metrics.cache_hits, attrs)
        metrics.cache_misses.add(run_metrics.cache_misses, attrs)
        metrics.normalize_duration.record(run_metrics.duration_seconds, attrs)
        metrics.rows_per_second.record(run_metrics.rows_per_second, attrs)

        span.set_attribute("normalization.records_processed", run_metrics.records_processed)
        span.set_attribute("normalization.changed_values", run_metrics.changed_values)
        span.set_attribute("normalization.duration_s", run_metrics.duration_seconds)
