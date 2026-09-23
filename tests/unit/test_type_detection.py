"""Unit tests for normanalysis.type_detection — Source.txt §61.

Reproduces §61's own worked examples (mobile->PHONE, dob->DATE,
customer_name->PERSON_NAME, user_id->IDENTIFIER) and verifies the
sample-value confirmation path against real normalizers.
"""

from __future__ import annotations

import pytest
from normalizers.date import DateNormalizer
from normalizers.email import EmailNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normalizers.phone import PhoneNormalizer
from normanalysis.type_detection import suggest_semantic_type
from normcore.enums import FieldSemanticType

from normcore import NormalizerRegistry


@pytest.fixture(scope="module")
def registry() -> NormalizerRegistry:
    reg = NormalizerRegistry()
    reg.register(PassthroughNormalizer())
    reg.register(EmailNormalizer())
    reg.register(PhoneNormalizer())
    reg.register(DateNormalizer())
    return reg


@pytest.mark.unit
class TestFieldNameOnlyDetection:
    @pytest.mark.parametrize(
        ("field_name", "expected_type"),
        [
            ("mobile", FieldSemanticType.PHONE),
            ("dob", FieldSemanticType.DATE),
            ("customer_name", FieldSemanticType.PERSON_NAME),
            ("user_id", FieldSemanticType.IDENTIFIER),
            ("email", FieldSemanticType.EMAIL),
            ("company_name", FieldSemanticType.COMPANY_NAME),
            ("first_name", FieldSemanticType.GIVEN_NAME),
            ("last_name", FieldSemanticType.FAMILY_NAME),
            ("zip_code", FieldSemanticType.POSTCODE),
            ("country", FieldSemanticType.COUNTRY),
            ("website", FieldSemanticType.URL),
            ("uuid", FieldSemanticType.UUID),
        ],
    )
    def test_matches_source_txt_61_worked_examples(
        self, field_name: str, expected_type: FieldSemanticType
    ) -> None:
        top = suggest_semantic_type(field_name)[0]
        assert top.semantic_type is expected_type

    def test_no_match_falls_back_to_free_text_at_low_confidence_not_a_guess(self) -> None:
        top = suggest_semantic_type("xyzzy_plugh_frotz")[0]
        assert top.semantic_type is FieldSemanticType.FREE_TEXT
        assert top.confidence < 0.5

    def test_never_returns_an_empty_list(self) -> None:
        assert len(suggest_semantic_type("")) >= 1

    def test_results_are_ranked_by_confidence_descending(self) -> None:
        results = suggest_semantic_type("mobile")
        confidences = [r.confidence for r in results]
        assert confidences == sorted(confidences, reverse=True)

    def test_more_specific_pattern_wins_over_generic_name_pattern(self) -> None:
        top = suggest_semantic_type("company_name")[0]
        assert top.semantic_type is FieldSemanticType.COMPANY_NAME


@pytest.mark.unit
class TestSampleValueConfirmation:
    def test_confirmed_by_real_parsing_raises_confidence(
        self, registry: NormalizerRegistry
    ) -> None:
        without_samples = suggest_semantic_type("mobile")[0]
        with_samples = suggest_semantic_type(
            "mobile",
            sample_values=["+1-202-555-0143", "+44 20 7946 0958", "+33 1 42 68 53 00"],
            registry=registry,
        )[0]
        assert with_samples.semantic_type is FieldSemanticType.PHONE
        assert with_samples.confidence >= without_samples.confidence
        assert "confirmed by real parsing" in with_samples.reason

    def test_contradicted_by_real_parsing_lowers_confidence(
        self, registry: NormalizerRegistry
    ) -> None:
        without_samples = suggest_semantic_type("mobile")[0]
        with_bad_samples = suggest_semantic_type(
            "mobile",
            sample_values=["not a phone", "still not a phone", "definitely not"],
            registry=registry,
        )[0]
        assert with_bad_samples.confidence < without_samples.confidence

    def test_all_null_samples_leaves_field_name_guess_unchanged(
        self, registry: NormalizerRegistry
    ) -> None:
        without_samples = suggest_semantic_type("mobile")[0]
        with_null_samples = suggest_semantic_type(
            "mobile", sample_values=[None, None], registry=registry
        )[0]
        assert with_null_samples.confidence == without_samples.confidence


@pytest.mark.unit
class TestValueOnlyDetection:
    """A name that matches nothing is not the end of the story — the data
    itself is evidence. `logo` holds URLs; no keyword table will ever list
    every name anyone gives a URL column."""

    def test_a_name_that_matches_nothing_is_detected_from_its_values(self) -> None:
        from normapi.app import build_normalizer_registry

        top = suggest_semantic_type(
            "logo",
            sample_values=["https://a.example/x.png", "https://b.example/y.png"],
            registry=build_normalizer_registry(),
        )[0]
        assert top.semantic_type is FieldSemanticType.URL
        assert "sample values validate" in top.reason

    def test_a_permissive_validator_is_not_treated_as_evidence(
        self, registry: NormalizerRegistry
    ) -> None:
        # This registry has PassthroughNormalizer registered for every type
        # it does not otherwise cover, and it accepts anything. Without the
        # negative control, every column would detect as one of those types.
        suggestions = suggest_semantic_type(
            "qqq_column",
            sample_values=["some arbitrary text", "more arbitrary text"],
            registry=registry,
        )
        assert [s.semantic_type for s in suggestions] == [FieldSemanticType.FREE_TEXT]

    def test_a_permissive_validator_cannot_confirm_a_loose_name_match(
        self, registry: NormalizerRegistry
    ) -> None:
        # "unrecognised" contains "is", which the relaxed boolean pattern
        # matches. That match is only ever meant to survive if real values
        # back it up, so a validator that accepts everything must not be
        # what backs it up.
        suggestions = suggest_semantic_type(
            "unrecognised_column",
            sample_values=["some arbitrary text", "more arbitrary text"],
            registry=registry,
        )
        assert all(s.confidence < 0.9 for s in suggestions), suggestions

    def test_values_never_outrank_a_confirmed_name_match(self) -> None:
        from normapi.app import build_normalizer_registry

        top = suggest_semantic_type(
            "website",
            sample_values=["https://a.example", "https://b.example"],
            registry=build_normalizer_registry(),
        )[0]
        assert top.semantic_type is FieldSemanticType.URL
        assert "field name matches" in top.reason

    def test_a_repaired_value_is_not_evidence_of_the_type(self) -> None:
        from normapi.app import build_normalizer_registry

        # URL repairs a bare host, so filenames would otherwise all
        # "validate" and a column of them would be rewritten to https://.
        suggestions = suggest_semantic_type(
            "attachment",
            sample_values=["report.txt", "archive.tar", "notes.doc"],
            registry=build_normalizer_registry(),
        )
        assert all(s.semantic_type is not FieldSemanticType.URL for s in suggestions), suggestions

    def test_cleanly_parsed_values_still_count(self) -> None:
        from normapi.app import build_normalizer_registry

        top = suggest_semantic_type(
            "attachment",
            sample_values=["https://a.example/r.txt", "https://b.example/a.tar"],
            registry=build_normalizer_registry(),
        )[0]
        assert top.semantic_type is FieldSemanticType.URL

    def test_two_types_both_claiming_the_column_is_evidence_for_neither(self) -> None:
        from normapi.app import build_normalizer_registry

        # With no name to break the tie, dict order must not decide.
        suggestions = suggest_semantic_type(
            "col", sample_values=["2020-01-02", "2021-03-04"], registry=build_normalizer_registry()
        )
        assert len({s.semantic_type for s in suggestions if s.confidence >= 0.9}) <= 1
