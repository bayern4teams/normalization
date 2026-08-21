"""normanalysis — run recording (Source.txt §70), OpenTelemetry
observability wiring (§122), and impact/collision/A-B/invariant/overview/
quality analysis (§71, §77-§80, §90, §93, §96-§97, landed in M6-M7).
"""

from normanalysis.ab_comparison import AbComparisonReport, SideMetrics, compare_runs
from normanalysis.collisions import (
    CollisionDecision,
    CollisionDecisionType,
    CollisionGroup,
    find_collisions,
)
from normanalysis.handoff import (
    HandoffArtifact,
    HandoffFieldSchema,
    HandoffProfileVersion,
    HandoffRecord,
    build_handoff_artifact,
)
from normanalysis.impact import ImpactReport, compute_impact
from normanalysis.instrumentation import instrumented_normalize
from normanalysis.invariant_sampler import (
    InvariantSampleReport,
    InvariantViolation,
    sample_and_check,
)
from normanalysis.overview import OverviewReport, compute_overview
from normanalysis.profile_suggestion import ProfileSuggestion, suggest_profile
from normanalysis.profiling import FieldProfile, TransformationPatternCount, profile_field
from normanalysis.quality import QualityMetric, QualityReport, compute_quality_report
from normanalysis.run_recorder import InvalidRunTransitionError, RunRecorder
from normanalysis.telemetry import NormalizationMetrics, TelemetryHandles, setup_telemetry
from normanalysis.type_detection import TypeSuggestion, suggest_semantic_type

__all__ = [
    "AbComparisonReport",
    "CollisionDecision",
    "CollisionDecisionType",
    "CollisionGroup",
    "FieldProfile",
    "HandoffArtifact",
    "HandoffFieldSchema",
    "HandoffProfileVersion",
    "HandoffRecord",
    "ImpactReport",
    "InvalidRunTransitionError",
    "InvariantSampleReport",
    "InvariantViolation",
    "NormalizationMetrics",
    "OverviewReport",
    "ProfileSuggestion",
    "QualityMetric",
    "QualityReport",
    "RunRecorder",
    "SideMetrics",
    "TelemetryHandles",
    "TransformationPatternCount",
    "TypeSuggestion",
    "build_handoff_artifact",
    "compare_runs",
    "compute_impact",
    "compute_overview",
    "compute_quality_report",
    "find_collisions",
    "instrumented_normalize",
    "profile_field",
    "sample_and_check",
    "setup_telemetry",
    "suggest_profile",
    "suggest_semantic_type",
]
