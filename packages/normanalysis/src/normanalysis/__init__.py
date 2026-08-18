"""normanalysis — run recording (Source.txt §70), OpenTelemetry
observability wiring (§122), and impact/collision/A-B/invariant analysis
(§71, §77-§80, §96-§97, landed in M6).
"""

from normanalysis.ab_comparison import AbComparisonReport, SideMetrics, compare_runs
from normanalysis.collisions import CollisionGroup, find_collisions
from normanalysis.impact import ImpactReport, compute_impact
from normanalysis.instrumentation import instrumented_normalize
from normanalysis.invariant_sampler import (
    InvariantSampleReport,
    InvariantViolation,
    sample_and_check,
)
from normanalysis.profiling import FieldProfile, TransformationPatternCount, profile_field
from normanalysis.run_recorder import InvalidRunTransitionError, RunRecorder
from normanalysis.telemetry import NormalizationMetrics, TelemetryHandles, setup_telemetry

__all__ = [
    "AbComparisonReport",
    "CollisionGroup",
    "FieldProfile",
    "ImpactReport",
    "InvalidRunTransitionError",
    "InvariantSampleReport",
    "InvariantViolation",
    "NormalizationMetrics",
    "RunRecorder",
    "SideMetrics",
    "TelemetryHandles",
    "TransformationPatternCount",
    "compare_runs",
    "compute_impact",
    "find_collisions",
    "instrumented_normalize",
    "profile_field",
    "sample_and_check",
    "setup_telemetry",
]
