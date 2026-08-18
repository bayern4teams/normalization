"""Property tests: idempotency (§71) and determinism (§72) for
GenericTextNormalizer, using Hypothesis to search for counterexamples
rather than relying solely on the fixed golden corpus.

Source.txt §71: normalize(normalize(x)) == normalize(x).
Source.txt §72: normalize(x) called twice on the same input/context must
produce byte-identical output (no hidden randomness, no wall-clock
dependence in the *value* fields).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from normalizers.generic_text import GenericTextNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType
from normdict.loader import DictionaryLoader

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"
_normalizer = GenericTextNormalizer(DictionaryLoader(_DICT_ROOT))
_ctx = NormalizationContext(field_name="notes", semantic_type=FieldSemanticType.FREE_TEXT)

# A broad mix of categories (letters across scripts, marks, punctuation,
# whitespace, symbols) — deliberately not restricted to ASCII, since the
# whole point of this milestone is Unicode-correctness under fuzzing, not
# just on the hand-picked golden corpus.
_TEXT_STRATEGY = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # exclude lone surrogates (invalid Unicode)
        min_codepoint=0x20,
    ),
    min_size=0,
    max_size=40,
)

_SUPPRESSED_HEALTH_CHECKS = (HealthCheck.too_slow, HealthCheck.function_scoped_fixture)


@pytest.mark.property
@settings(max_examples=200, suppress_health_check=_SUPPRESSED_HEALTH_CHECKS)
@given(value=_TEXT_STRATEGY)
def test_determinism_same_input_same_output(value: str) -> None:
    first = _normalizer.normalize(value, _ctx)
    second = _normalizer.normalize(value, _ctx)

    assert first.display == second.display
    assert first.comparison == second.comparison
    assert first.search == second.search
    assert first.normalization_status == second.normalization_status
    assert first.original_kind == second.original_kind
    assert [s.operation for s in first.trace] == [s.operation for s in second.trace]
    assert [s.output_hash for s in first.trace] == [s.output_hash for s in second.trace]


@pytest.mark.property
@settings(max_examples=200, suppress_health_check=_SUPPRESSED_HEALTH_CHECKS)
@given(value=_TEXT_STRATEGY)
def test_idempotency_display_is_a_fixed_point(value: str) -> None:
    """Feeding a value's own `display` output back in as a new `original`
    must reproduce the same `display` — the pipeline should converge in
    one pass, never keep changing the value on repeated application."""
    first = _normalizer.normalize(value, _ctx)
    if first.display is None:
        return  # missing-value sentinel path, nothing to re-normalize
    second = _normalizer.normalize(first.display, _ctx)
    assert second.display == first.display, (
        f"input codepoints={[hex(ord(c)) for c in value]!r} "
        f"first.display codepoints={[hex(ord(c)) for c in first.display]!r} "
        f"second.display codepoints={[hex(ord(c)) for c in (second.display or '')]!r}"
    )


@pytest.mark.property
@settings(max_examples=200, suppress_health_check=_SUPPRESSED_HEALTH_CHECKS)
@given(value=_TEXT_STRATEGY)
def test_normalize_never_raises_or_fails_on_arbitrary_unicode(value: str) -> None:
    """A hard requirement independent of idempotency/determinism: no
    input this normalizer is asked to handle should ever raise an
    uncaught exception (Source.txt §68's "one malformed value must never
    abort a run")."""
    result = _normalizer.normalize(value, _ctx)
    assert result.errors == []
