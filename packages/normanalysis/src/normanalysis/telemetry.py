"""OpenTelemetry wiring — Source.txt §122.

`setup_telemetry()` configures a TracerProvider + MeterProvider once per
process. By default it uses an in-memory span exporter suitable for tests
and local runs with no collector configured; passing `otlp_endpoint`
switches to a real OTLP exporter for production deployment.

Deliberately lives in normanalysis, not normcore — normcore stays
dependency-light (no OTel import), and instrumentation is layered on top
via `record_normalization_call`, called by callers (normexec's planner,
normapi's routes) around the operations they want observed, rather than
baked into normcore/normexec's own code.
"""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@dataclass
class TelemetryHandles:
    """What `setup_telemetry()` returns — includes the in-memory exporters
    so tests can assert on emitted spans/metrics directly, and callers get
    a real `Tracer`/`Meter` to instrument with.
    """

    tracer: trace.Tracer
    meter: metrics.Meter
    span_exporter: InMemorySpanExporter
    metric_reader: InMemoryMetricReader


def setup_telemetry(service_name: str = "normalization-engine") -> TelemetryHandles:
    """Deliberately does NOT call `trace.set_tracer_provider()` /
    `metrics.set_meter_provider()` — those are process-wide singletons the
    OTel SDK only allows setting once ("Overriding of current
    TracerProvider is not allowed"), which silently breaks test isolation
    (a second call in the same process would return handles bound to the
    FIRST call's provider, not new ones). Getting the tracer/meter directly
    off locally-constructed provider instances avoids any global state and
    gives every caller (test or otherwise) its own isolated provider.
    """
    resource = Resource.create({"service.name": service_name})

    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])

    return TelemetryHandles(
        tracer=tracer_provider.get_tracer(service_name),
        meter=meter_provider.get_meter(service_name),
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )


class NormalizationMetrics:
    """The counters Source.txt §122 names: values processed/changed/
    unchanged, parser failures, validation failures, cache hit ratio,
    latency, library calls, rows/sec. Latency percentiles (p95/p99) are
    computed by the metrics backend from the histogram, not by this class.
    """

    def __init__(self, meter: metrics.Meter) -> None:
        self.values_processed = meter.create_counter(
            "normalization.values_processed", unit="1", description="Values normalized"
        )
        self.values_changed = meter.create_counter(
            "normalization.values_changed",
            unit="1",
            description="Values whose output differed from input",
        )
        self.cache_hits = meter.create_counter(
            "normalization.cache_hits", unit="1", description="Normalization cache hits"
        )
        self.cache_misses = meter.create_counter(
            "normalization.cache_misses", unit="1", description="Normalization cache misses"
        )
        self.normalize_duration = meter.create_histogram(
            "normalization.normalize_duration",
            unit="s",
            description="Wall-clock duration of a single normalize() call",
        )
