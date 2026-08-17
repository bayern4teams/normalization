"""PassthroughNormalizer — proves the full Normalizer interface and the
whole M1 vertical (connector -> planner -> cache -> normalizer -> contract
-> sidecar store -> run record -> API) without depending on any real
semantic-domain library. Real adapters (GenericTextNormalizer,
NameNormalizer, etc.) land in M2+.

Deliberately trivial: `display` and `comparison` both mirror `original`
(comparison casefolded), status is always UNCHANGED unless the input is
None, and every declared step is LOSSLESS with a trivial identity inverse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus, QualityFlag, Reversibility
from normcore.models import NormalizedValue
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import StepSpec

_VERSION = "0.1.0"


class _PassthroughStep:
    step_id = "passthrough.identity"
    operation = "identity"
    claimed_reversibility = Reversibility.LOSSLESS
    lossy = False


class PassthroughNormalizer:
    name = "PassthroughNormalizer"
    supported_types = frozenset(FieldSemanticType)  # handles every type — placeholder only

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return True

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return NormalizedValue(
                original=None,
                normalization_status=NormalizationStatus.UNCHANGED,
                flags=[QualityFlag.UNKNOWN_SEMANTIC_TYPE],
                profile_version="",  # stamped by caller in real pipelines; see dispatch.Dispatcher
                env_id="",
                semantic_type=ctx.semantic_type,
                context_hash=ctx.context_hash,
            )

        return NormalizedValue(
            original=value,
            display=value,
            comparison=value.casefold(),
            normalization_status=NormalizationStatus.UNCHANGED,
            confidence=1.0,
            profile_version="",
            env_id="",
            semantic_type=ctx.semantic_type,
            context_hash=ctx.context_hash,
        )

    def normalize_batch(self, values: pa.Array, ctx: NormalizationContext) -> pa.StructArray:
        originals = values.to_pylist()
        displays = originals
        comparisons = [v.casefold() if v is not None else None for v in originals]
        statuses = [NormalizationStatus.UNCHANGED.value for _ in originals]

        return pa.StructArray.from_arrays(
            [
                pa.array(originals, type=pa.large_string()),
                pa.array(displays, type=pa.large_string()),
                pa.array(comparisons, type=pa.large_string()),
                pa.array(statuses, type=pa.large_string()),
            ],
            names=["original", "display", "comparison", "status"],
        )

    def validate(self, value: str | None, ctx: NormalizationContext) -> ValidationOutcome:
        return ValidationOutcome(is_valid=value is not None, status="UNVALIDATED")

    def explain(self, result: NormalizedValue) -> ExplanationText:
        return ExplanationText(
            plain_language="No transformation was applied.",
            technical="PassthroughNormalizer: identity mapping, no rules applied.",
        )

    def version(self) -> ComponentVersionInfo:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return (_PassthroughStep(),)

    def inverse(self, step_id: str, value: str) -> str | None:
        if step_id == _PassthroughStep.step_id:
            return value
        return None
