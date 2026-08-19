"""Unit tests for normanalysis.profile_suggestion — Source.txt §62, §84.

Reproduces §62's own worked examples' spirit (phone -> libphonenumber
parser; risk callouts) and verifies `real_steps` is genuinely sourced
from a live registry, not fabricated.
"""

from __future__ import annotations

import pytest
from normalizers.name import NameNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normalizers.phone import PhoneNormalizer
from normanalysis.profile_suggestion import suggest_profile
from normcore.enums import FieldSemanticType

from normcore import NormalizerRegistry
from normdict import DictionaryLoader

_DICT_ROOT = "data/dictionaries"


@pytest.fixture(scope="module")
def registry() -> NormalizerRegistry:
    reg = NormalizerRegistry()
    reg.register(PassthroughNormalizer())
    reg.register(PhoneNormalizer())
    reg.register(NameNormalizer(DictionaryLoader(_DICT_ROOT)))
    return reg


@pytest.mark.unit
class TestCuratedSuggestions:
    def test_phone_mentions_libphonenumber_and_e164(self) -> None:
        suggestion = suggest_profile(FieldSemanticType.PHONE)
        assert "libphonenumber" in suggestion.recommended_summary
        assert "E.164" in suggestion.recommended_summary

    def test_phone_risk_mentions_country_ambiguity(self) -> None:
        suggestion = suggest_profile(FieldSemanticType.PHONE)
        assert "ambiguity" in suggestion.risk.lower()

    def test_address_mentions_libpostal(self) -> None:
        suggestion = suggest_profile(FieldSemanticType.ADDRESS)
        assert "libpostal" in suggestion.recommended_summary

    def test_person_name_risk_mentions_culture_dependent_order(self) -> None:
        suggestion = suggest_profile(FieldSemanticType.PERSON_NAME)
        assert "culture" in suggestion.risk.lower()

    def test_every_field_semantic_type_returns_something_never_crashes(self) -> None:
        for semantic_type in FieldSemanticType:
            suggestion = suggest_profile(semantic_type)
            assert suggestion.recommended_summary
            assert suggestion.risk

    def test_unknown_type_gets_honest_generic_fallback_not_fabricated_specifics(self) -> None:
        suggestion = suggest_profile(FieldSemanticType.UNKNOWN)
        assert "no curated recommendation" in suggestion.recommended_summary.lower()


@pytest.mark.unit
class TestRealStepsFromLiveRegistry:
    def test_no_registry_means_no_real_steps_not_fabricated_ones(self) -> None:
        suggestion = suggest_profile(FieldSemanticType.PHONE, registry=None)
        assert suggestion.real_steps == ()

    def test_registry_without_that_normalizer_registered_returns_no_steps(self) -> None:
        # No PassthroughNormalizer registered here (unlike the real app,
        # which always registers one as a fallback for every type) —
        # this is the one way `registry.get()` genuinely returns None.
        bare_registry = NormalizerRegistry()
        bare_registry.register(PhoneNormalizer())
        suggestion = suggest_profile(FieldSemanticType.CURRENCY, registry=bare_registry)
        assert suggestion.real_steps == ()

    def test_passthrough_fallback_reports_its_own_real_identity_step(
        self, registry: NormalizerRegistry
    ) -> None:
        # The real app always registers PassthroughNormalizer first as a
        # fallback (normapi/app.py) — a type with no dedicated adapter
        # still reports a real (if trivial) step, never a fabricated one.
        suggestion = suggest_profile(FieldSemanticType.CURRENCY, registry=registry)
        assert suggestion.real_steps == tuple(
            step.operation for step in PassthroughNormalizer().steps()
        )

    def test_static_steps_come_from_the_real_normalizer(self, registry: NormalizerRegistry) -> None:
        suggestion = suggest_profile(FieldSemanticType.PHONE, registry=registry)
        assert suggestion.real_steps == tuple(step.operation for step in PhoneNormalizer().steps())

    def test_sample_value_produces_a_real_executed_trace(
        self, registry: NormalizerRegistry
    ) -> None:
        suggestion = suggest_profile(
            FieldSemanticType.PHONE, registry=registry, sample_value="+1-202-555-0143"
        )
        assert suggestion.real_steps == ("phone.parse",)

    def test_sample_value_trace_can_differ_from_static_steps(
        self, registry: NormalizerRegistry
    ) -> None:
        # `.steps()` declares the full universe of steps a normalizer
        # *could* run (including optional variant-producing steps like
        # NFD/NFKC/NFKD forms); a real trace for one specific value only
        # lists what actually fired for that input — expected to be a
        # subset, not a superset.
        static_only = suggest_profile(FieldSemanticType.PERSON_NAME, registry=registry)
        with_sample = suggest_profile(
            FieldSemanticType.PERSON_NAME, registry=registry, sample_value="Jose Garcia"
        )
        assert with_sample.real_steps != static_only.real_steps
        assert set(with_sample.real_steps) <= set(static_only.real_steps)
