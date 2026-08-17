"""normanalysis — run recording (Source.txt §70) and OpenTelemetry
observability wiring (§122). Profiling/impact/collision/reversibility/A-B
analysis (§77-§80, §96) land in M6.
"""

from normanalysis.instrumentation import instrumented_normalize
from normanalysis.run_recorder import InvalidRunTransitionError, RunRecorder
from normanalysis.telemetry import NormalizationMetrics, TelemetryHandles, setup_telemetry

__all__ = [
    "InvalidRunTransitionError",
    "NormalizationMetrics",
    "RunRecorder",
    "TelemetryHandles",
    "instrumented_normalize",
    "setup_telemetry",
]
