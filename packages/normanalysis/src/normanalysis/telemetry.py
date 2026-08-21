"""OpenTelemetry wiring — Source.txt §122.

`setup_telemetry()` configures a TracerProvider + MeterProvider once per
process. An in-memory span exporter + metric reader are ALWAYS attached
(tests assert against them directly, and this doubles as the built-in
"observability, no collector required" default for local runs); passing
`otlp_endpoint` (M12 — previously promised by this docstring since M1 but
never actually implemented, a real gap found while wiring this into the
live app for the first time) ADDS a real `OTLPSpanExporter`/OTLP metric
reader as a second destination on the same providers — spans/metrics
still land in the in-memory exporter too, so existing tests and this
module's own contract are unaffected by opting into OTLP export.

Deliberately lives in normanalysis, not normcore — normcore stays
dependency-light (no OTel import), and instrumentation is layered on top
via `record_normalization_call`, called by callers (normexec's planner,
normapi's routes) around the operations they want observed, rather than
baked into normcore/normexec's own code.
"""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@dataclass
class TelemetryHandles:
    """What `setup_telemetry()` returns — includes the in-memory exporters
    so tests can assert on emitted spans/metrics directly, and callers get
    a real `Tracer`/`Meter` to instrument with. `tracer_provider`/
    `meter_provider` are exposed so a caller using OTLP export can call
    `force_flush()` before process shutdown — a `PeriodicExportingMetricReader`
    otherwise only exports on its own schedule.
    """

    tracer: trace.Tracer
    meter: metrics.Meter
    span_exporter: InMemorySpanExporter
    metric_reader: InMemoryMetricReader
    tracer_provider: TracerProvider
    meter_provider: MeterProvider


def setup_telemetry(
    service_name: str = "normalization-engine", *, otlp_endpoint: str | None = None
) -> TelemetryHandles:
    """Deliberately does NOT call `trace.set_tracer_provider()` /
    `metrics.set_meter_provider()` — those are process-wide singletons the
    OTel SDK only allows setting once ("Overriding of current
    TracerProvider is not allowed"), which silently breaks test isolation
    (a second call in the same process would return handles bound to the
    FIRST call's provider, not new ones). Getting the tracer/meter directly
    off locally-constructed provider instances avoids any global state and
    gives every caller (test or otherwise) its own isolated provider.

    `otlp_endpoint`, when given, is the base URL of a real OTLP/HTTP
    receiver (e.g. `http://localhost:4318`) — traces/metrics both actually
    leave the process over the network, not just accumulate in memory.
    """
    resource = Resource.create({"service.name": service_name})

    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    metric_readers: list[InMemoryMetricReader | PeriodicExportingMetricReader] = [metric_reader]

    if otlp_endpoint is not None:
        tracer_provider.add_span_processor(
            SimpleSpanProcessor(OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces"))
        )
        metric_readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{otlp_endpoint}/v1/metrics")
            )
        )

    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)

    return TelemetryHandles(
        tracer=tracer_provider.get_tracer(service_name),
        meter=meter_provider.get_meter(service_name),
        span_exporter=span_exporter,
        metric_reader=metric_reader,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )


class NormalizationMetrics:
    """The counters Source.txt §122 names: values processed/changed/
    unchanged, parser failures, validation failures, cache hit ratio
    (derived at query time from `cache_hits`/`cache_misses`, not stored
    separately), latency, library calls, rows/sec. Latency percentiles
    (p95/p99) are computed by the metrics backend from the histogram, not
    by this class.
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
        self.values_unchanged = meter.create_counter(
            "normalization.values_unchanged",
            unit="1",
            description="Values whose output matched input exactly",
        )
        self.parser_failures = meter.create_counter(
            "normalization.parser_failures", unit="1", description="Parser failures"
        )
        self.validation_failures = meter.create_counter(
            "normalization.validation_failures", unit="1", description="Validation failures"
        )
        self.library_calls = meter.create_counter(
            "normalization.library_calls",
            unit="1",
            description="Calls into third-party normalization libraries",
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
        self.rows_per_second = meter.create_histogram(
            "normalization.rows_per_second",
            unit="1",
            description="Throughput observed at the end of one run's execution",
        )
