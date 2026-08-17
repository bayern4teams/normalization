"""normcore — domain model, contracts, enums, context, trace, and the
Normalizer interface shared by every normalization adapter.

This package has no dependency on any specific normalization library
(ICU, libpostal, phonenumbers, ...) — those live in `normalizers`. normcore
is the stable contract everything else is built against.
"""

from normcore.context import NormalizationContext
from normcore.enums import (
    ErrorPolicy,
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    ProfileStatus,
    QualityFlag,
    Reversibility,
    SemanticSource,
)
from normcore.errors import NormalizationError, NormalizerFailure, apply_error_policy
from normcore.interfaces import Normalizer
from normcore.models import NormalizedValue
from normcore.trace import TraceStep

__all__ = [
    "ErrorPolicy",
    "FieldSemanticType",
    "MissingKind",
    "NormalizationContext",
    "NormalizationError",
    "NormalizationStatus",
    "NormalizedValue",
    "Normalizer",
    "NormalizerFailure",
    "ProfileStatus",
    "QualityFlag",
    "Reversibility",
    "SemanticSource",
    "TraceStep",
    "apply_error_policy",
]
