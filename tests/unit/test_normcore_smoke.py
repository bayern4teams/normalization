"""M0 smoke test: proves the normcore skeleton actually works end to end
(construct a context, construct a NormalizedValue, hash a trace step) —
not a golden/behavioral test (those start in M2), just a scaffold-sanity
check that the domain model is usable.
"""

from __future__ import annotations

import pytest
from normcore.enums import ErrorPolicy
from normcore.errors import apply_error_policy

from normcore import (
    FieldSemanticType,
    NormalizationContext,
    NormalizationStatus,
    NormalizedValue,
    Reversibility,
    TraceStep,
)


@pytest.mark.unit
def test_context_hash_is_stable_and_sensitive() -> None:
    ctx_a = NormalizationContext(
        field_name="first_name", semantic_type=FieldSemanticType.PERSON_NAME
    )
    ctx_b = NormalizationContext(
        field_name="first_name", semantic_type=FieldSemanticType.PERSON_NAME
    )
    ctx_c = NormalizationContext(
        field_name="last_name", semantic_type=FieldSemanticType.PERSON_NAME
    )

    assert ctx_a.context_hash == ctx_b.context_hash
    assert ctx_a.context_hash != ctx_c.context_hash


@pytest.mark.unit
def test_normalized_value_round_trips_through_json() -> None:
    step = TraceStep(
        step_order=1,
        rule_id="whitespace.collapse",
        operation="collapse_whitespace",
        params_hash="deadbeef",
        input_hash="aaaa",
        output_hash="bbbb",
        input_mask="Lu Ll Ll Zs Lu Ll Ll",
        output_mask="Lu Ll Ll Zs Lu Ll Ll",
        changed=True,
        lossy=False,
        reversibility=Reversibility.REVERSIBLE,
        library="normcore",
        library_version="0.1.0",
    )
    value = NormalizedValue(
        original="  John   Smith  ",
        display="John Smith",
        comparison="john smith",
        normalization_status=NormalizationStatus.NORMALIZED,
        confidence=0.99,
        trace=[step],
        profile_version="v1",
        env_id="0" * 64,
        semantic_type=FieldSemanticType.PERSON_NAME,
        context_hash="1" * 64,
    )

    dumped = value.model_dump_json()
    restored = NormalizedValue.model_validate_json(dumped)

    assert restored.display == "John Smith"
    assert restored.is_lossy() is False
    assert len(restored.trace) == 1
    assert restored.trace[0].to_explanation_line().startswith("Step 1: collapse_whitespace")


@pytest.mark.unit
def test_original_is_never_silently_dropped_on_error_policy() -> None:
    value, status = apply_error_policy(ErrorPolicy.RETURN_ORIGINAL, original_value="000123")
    assert value == "000123"
    assert status == "INVALID"
