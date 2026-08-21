"""Proves OpenTelemetry wiring actually emits spans and records metrics —
captured via the in-memory exporter/reader `setup_telemetry()` returns,
not just "the call didn't crash."
"""

from __future__ import annotations

import http.server
import threading
from typing import ClassVar

import pytest
from normalizers.passthrough import PassthroughNormalizer
from opentelemetry.sdk.metrics.export import NumberDataPoint

from normanalysis import (
    NormalizationMetrics,
    instrumented_normalize,
    record_run_metrics,
    setup_telemetry,
)
from normcore import (
    Dispatcher,
    FieldSemanticType,
    NormalizationContext,
    NormalizationProfile,
    NormalizationRunMetrics,
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


def _run_metrics() -> NormalizationRunMetrics:
    return NormalizationRunMetrics(
        records_processed=5,
        fields_processed=1,
        changed_values=2,
        unchanged_values=3,
        parser_failures=1,
        validation_failures=1,
        cache_hits=4,
        cache_misses=1,
        library_calls=7,
        duration_seconds=0.25,
        rows_per_second=20.0,
    )


@pytest.mark.unit
def test_record_run_metrics_records_every_real_counter() -> None:
    handles = setup_telemetry("test-service-run-metrics")
    metrics = NormalizationMetrics(handles.meter)

    record_run_metrics(
        handles,
        metrics,
        _run_metrics(),
        field_name="name",
        semantic_type=FieldSemanticType.PERSON_NAME,
    )

    handles.metric_reader.collect()
    data = handles.metric_reader.get_metrics_data()
    assert data is not None
    values: dict[str, float] = {}
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                for point in metric.data.data_points:
                    # normalize_duration/rows_per_second are histograms
                    # (HistogramDataPoint, no .value) — only the Counter
                    # metrics asserted on below are NumberDataPoint.
                    if isinstance(point, NumberDataPoint):
                        values[metric.name] = point.value

    assert values["normalization.values_processed"] == 5
    assert values["normalization.values_changed"] == 2
    assert values["normalization.values_unchanged"] == 3
    assert values["normalization.parser_failures"] == 1
    assert values["normalization.validation_failures"] == 1
    assert values["normalization.library_calls"] == 7
    assert values["normalization.cache_hits"] == 4
    assert values["normalization.cache_misses"] == 1

    spans = handles.span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "normalization.run"


class _OtlpCapture(http.server.BaseHTTPRequestHandler):
    """A real, minimal local HTTP receiver — proves OTLP export actually
    puts bytes on a socket, not just "the SDK call didn't raise"."""

    received: ClassVar[list[tuple[str, bytes]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _OtlpCapture.received.append((self.path, body))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence default request logging to stdout during tests


@pytest.mark.unit
@pytest.mark.slow_fork
def test_otlp_export_sends_real_bytes_to_a_real_receiver() -> None:
    _OtlpCapture.received = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _OtlpCapture)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        handles = setup_telemetry("test-service-otlp", otlp_endpoint=f"http://127.0.0.1:{port}")
        metrics = NormalizationMetrics(handles.meter)
        record_run_metrics(
            handles,
            metrics,
            _run_metrics(),
            field_name="name",
            semantic_type=FieldSemanticType.PERSON_NAME,
        )

        handles.tracer_provider.force_flush(timeout_millis=5000)
        handles.meter_provider.force_flush(timeout_millis=5000)
    finally:
        # Stops PeriodicExportingMetricReader's own background export
        # thread — otherwise it outlives this test on its default
        # schedule and retries against the now-dead receiver, polluting
        # later tests' stderr with harmless-but-confusing connection
        # errors.
        handles.tracer_provider.shutdown()
        handles.meter_provider.shutdown()
        server.shutdown()
        thread.join(timeout=5)

    paths = {path for path, _ in _OtlpCapture.received}
    assert "/v1/traces" in paths
    assert "/v1/metrics" in paths
    # Every captured body is real, non-empty protobuf-encoded bytes — an
    # empty body would mean the exporter sent a request with no actual
    # payload, not a real export.
    assert all(len(body) > 0 for _, body in _OtlpCapture.received)
