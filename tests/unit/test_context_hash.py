"""`NormalizationContext.context_hash` — Phase 1 of the 2026-08-29
throughput program memoized this via a `PrivateAttr` (see
`packages/normcore/src/normcore/context.py`'s own comment for why not
`functools.cached_property`). These tests pin down the behavior that
memoization must not change: the same logical context always hashes the
same, on repeated access AND across independently-constructed instances,
and `pii_visibility` never participates.
"""

from __future__ import annotations

import pytest
from normcore.context import NormalizationContext
from normcore.enums import ErrorPolicy, FieldSemanticType


def _ctx(**overrides: object) -> NormalizationContext:
    defaults: dict[str, object] = {
        "field_name": "fullName",
        "semantic_type": FieldSemanticType.PERSON_NAME,
    }
    defaults.update(overrides)
    return NormalizationContext(**defaults)


@pytest.mark.unit
class TestContextHashMemoization:
    def test_stable_across_repeated_access_on_the_same_instance(self) -> None:
        ctx = _ctx()
        assert ctx.context_hash == ctx.context_hash == ctx.context_hash

    def test_two_independent_instances_with_identical_fields_hash_equal(self) -> None:
        ctx_a = _ctx(country="US", locale="en_US")
        ctx_b = _ctx(country="US", locale="en_US")
        assert ctx_a.context_hash == ctx_b.context_hash

    def test_differing_fields_hash_differently(self) -> None:
        ctx_a = _ctx(country="US")
        ctx_b = _ctx(country="GB")
        assert ctx_a.context_hash != ctx_b.context_hash

    def test_pii_visibility_is_excluded_from_the_hash(self) -> None:
        ctx_a = _ctx(pii_visibility="masked")
        ctx_b = _ctx(pii_visibility="visible")
        assert ctx_a.context_hash == ctx_b.context_hash

    def test_error_policy_does_participate_in_the_hash(self) -> None:
        """Sanity check that the exclusion above is specific to
        pii_visibility, not a sign every field is silently excluded."""
        ctx_a = _ctx(error_policy=ErrorPolicy.RETURN_ORIGINAL)
        ctx_b = _ctx(error_policy=ErrorPolicy.FAIL_RECORD)
        assert ctx_a.context_hash != ctx_b.context_hash

    def test_context_is_still_frozen(self) -> None:
        """The PrivateAttr memoization must not have loosened
        model_config's frozen=True for real fields."""
        ctx = _ctx()
        with pytest.raises(Exception, match=r"(?i)frozen"):
            ctx.field_name = "other"  # type: ignore[misc]
