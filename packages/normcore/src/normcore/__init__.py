"""normcore — domain model, contracts, enums, context, trace, and the
Normalizer interface shared by every normalization adapter.

This package has no dependency on any specific normalization library
(ICU, libpostal, phonenumbers, ...) — those live in `normalizers`. normcore
is the stable contract everything else is built against.
"""

from normcore.context import NormalizationContext
from normcore.dispatch import Dispatcher, NoNormalizerRegisteredError, NormalizerRegistry
from normcore.enums import (
    ErrorPolicy,
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    OnErrorAction,
    ProfileStatus,
    QualityFlag,
    Reversibility,
    RunStatus,
    SemanticSource,
)
from normcore.errors import (
    NormalizationError,
    NormalizationWarning,
    NormalizerFailure,
    apply_error_policy,
)
from normcore.interfaces import Normalizer
from normcore.models import NormalizedValue
from normcore.rules import (
    ComponentVersionInfo,
    ExplanationText,
    FieldNormalizationConfig,
    NormalizationPipeline,
    NormalizationProfile,
    NormalizationRule,
    NormalizationStep,
    ValidationOutcome,
)
from normcore.run import NormalizationRun, NormalizationRunMetrics, NormalizationVersion
from normcore.trace import TraceStep

__all__ = [
    "ComponentVersionInfo",
    "Dispatcher",
    "ErrorPolicy",
    "ExplanationText",
    "FieldNormalizationConfig",
    "FieldSemanticType",
    "MissingKind",
    "NoNormalizerRegisteredError",
    "NormalizationContext",
    "NormalizationError",
    "NormalizationPipeline",
    "NormalizationProfile",
    "NormalizationRule",
    "NormalizationRun",
    "NormalizationRunMetrics",
    "NormalizationStatus",
    "NormalizationStep",
    "NormalizationVersion",
    "NormalizationWarning",
    "NormalizedValue",
    "Normalizer",
    "NormalizerFailure",
    "NormalizerRegistry",
    "OnErrorAction",
    "ProfileStatus",
    "QualityFlag",
    "Reversibility",
    "RunStatus",
    "SemanticSource",
    "TraceStep",
    "ValidationOutcome",
    "apply_error_policy",
]
