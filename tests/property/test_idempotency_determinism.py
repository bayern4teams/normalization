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
from normapi.app import build_normalizer_registry
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.context import NormalizationContext
from normcore.dispatch import Dispatcher
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


# §71 is a claim about the whole pipeline, not about one normalizer, but
# only GenericTextNormalizer was ever fuzzed for it. These reach every
# semantic type a clone job can configure, through the Dispatcher that a
# clone job actually calls — including the multivalue and missing-sentinel
# paths, which live in the Dispatcher and so were never covered above.
_ALL_TYPES = [
    FieldSemanticType.COUNTRY,
    FieldSemanticType.LANGUAGE,
    FieldSemanticType.CURRENCY,
    FieldSemanticType.MONEY,
    FieldSemanticType.NUMERIC,
    FieldSemanticType.POSTCODE,
    FieldSemanticType.PHONE,
    FieldSemanticType.EMAIL,
    FieldSemanticType.URL,
    FieldSemanticType.DATE,
    FieldSemanticType.BOOLEAN,
    FieldSemanticType.IDENTIFIER,
    FieldSemanticType.COMPANY_NAME,
    FieldSemanticType.PERSON_NAME,
]


@pytest.fixture(scope="module")
def dispatcher() -> Dispatcher:
    return Dispatcher(
        build_normalizer_registry(DictionaryLoader(_DICT_ROOT)), env_id="property-test"
    )


@pytest.mark.property
@pytest.mark.parametrize("semantic_type", _ALL_TYPES, ids=lambda t: t.value)
@settings(max_examples=60, suppress_health_check=_SUPPRESSED_HEALTH_CHECKS, deadline=None)
@given(value=_TEXT_STRATEGY)
def test_every_semantic_type_converges_in_one_pass(
    dispatcher: Dispatcher, semantic_type: FieldSemanticType, value: str
) -> None:
    """`normalize(normalize(x)) == normalize(x)`, for each type, with a
    country and locale supplied — the context a clone job runs under, and
    the one where a normalizer has the most freedom to rewrite a value."""
    ctx = NormalizationContext(
        field_name="probe", semantic_type=semantic_type, country="US", locale="en-US"
    )
    first = dispatcher.normalize(value, semantic_type, ctx, SCAFFOLD_PROFILE)
    if first.display is None:
        return
    second = dispatcher.normalize(first.display, semantic_type, ctx, SCAFFOLD_PROFILE)
    assert second.display == first.display, (
        f"{semantic_type.value}: {value!r} -> {first.display!r} -> {second.display!r}"
    )


@pytest.mark.property
def test_language_ga_script_input_converges_in_one_pass(dispatcher: Dispatcher) -> None:
    ctx = NormalizationContext(
        field_name="probe", semantic_type=FieldSemanticType.LANGUAGE, country="US", locale="en-US"
    )
    first = dispatcher.normalize("กา", FieldSemanticType.LANGUAGE, ctx, SCAFFOLD_PROFILE)
    assert first.display == "Ga", f"unexpected first pass: {first.display!r}"
    # ADR-010 amendment 2026-10-27: the code is the contract; `display` is output only.
    second = dispatcher.normalize(
        first.comparison, FieldSemanticType.LANGUAGE, ctx, SCAFFOLD_PROFILE
    )
    assert second.comparison == first.comparison, (
        f"'กา' -> {first.comparison!r} -> {second.comparison!r}"
    )
