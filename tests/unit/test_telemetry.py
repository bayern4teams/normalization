"""Proves OpenTelemetry wiring actually emits spans and records metrics —
captured via the in-memory exporter/reader `setup_telemetry()` returns,
not just "the call didn't crash."
"""

from __future__ import annotations

import pytest
from normalizers.passthrough import PassthroughNormalizer
from opentelemetry.sdk.metrics.export import NumberDataPoint

from normanalysis import NormalizationMetrics, instrumented_normalize, setup_telemetry
from normcore import (
    Dispatcher,
    FieldSemanticType,
    NormalizationContext,
    NormalizationProfile,
    NormalizerRegistry,
)


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
def test_setup_telemetry_returns_working_handles() -> None:
    handles = setup_telemetry("test-service")
    assert handles.tracer is not None
    assert handles.meter is not None
    assert handles.span_exporter.get_finished_spans() == ()


@pytest.mark.unit
def test_instrumented_normalize_emits_a_real_span() -> None:
    handles = setup_telemetry("test-service-spans")
    metrics = NormalizationMetrics(handles.meter)

    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    ctx = NormalizationContext(field_name="first_name", semantic_type=FieldSemanticType.PERSON_NAME)

    result = instrumented_normalize(
        handles,
        metrics,
        dispatcher,
        value="  John  ",
        semantic_type=FieldSemanticType.PERSON_NAME,
        context=ctx,
        profile=_profile(),
    )
    assert result.original == "  John  "

    spans = handles.span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "normalization.normalize"
    assert span.attributes is not None
    assert span.attributes["normalization.semantic_type"] == "PERSON_NAME"
    assert span.attributes["normalization.field_name"] == "first_name"
    assert span.attributes["normalization.status"] == "UNCHANGED"
    assert span.attributes["normalization.changed"] is False


@pytest.mark.unit
def test_instrumented_normalize_records_metrics() -> None:
    handles = setup_telemetry("test-service-metrics")
    metrics = NormalizationMetrics(handles.meter)

    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    ctx = NormalizationContext(field_name="email", semantic_type=FieldSemanticType.EMAIL)

    for _ in range(3):
        instrumented_normalize(
            handles,
            metrics,
            dispatcher,
            value="x@example.com",
            semantic_type=FieldSemanticType.EMAIL,
            context=ctx,
            profile=_profile(),
        )

    handles.metric_reader.collect()
    data = handles.metric_reader.get_metrics_data()
    assert data is not None

    found_processed_count = None
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == "normalization.values_processed":
                    for point in metric.data.data_points:
                        # Always a real NumberDataPoint here — this metric
                        # is a Counter (meter.create_counter), which
                        # OTel's SDK only ever backs with NumberDataPoint,
                        # never Histogram/ExponentialHistogram.
                        assert isinstance(point, NumberDataPoint)
                        found_processed_count = point.value
    assert found_processed_count == 3
