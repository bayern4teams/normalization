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
class TestTableQualifiedDetection:
    """A bare "name" column means something different per table — found
    live against a real Company table (M21 Explore auto-suggest), where
    field-name-only detection picked PERSON_NAME for Company.name."""

    def test_bare_name_column_under_company_table_prefers_company_name(self) -> None:
        top = suggest_semantic_type("name", table_name="Company")[0]
        assert top.semantic_type is FieldSemanticType.COMPANY_NAME

    def test_bare_name_column_without_table_context_still_falls_back_to_person_name(
        self,
    ) -> None:
        top = suggest_semantic_type("name")[0]
        assert top.semantic_type is FieldSemanticType.PERSON_NAME

    def test_field_name_pattern_still_wins_over_table_qualified_match(self) -> None:
        # "email" alone already matches EMAIL directly; a table named
        # "Company" must not somehow steer it toward COMPANY_NAME instead.
        top = suggest_semantic_type("email", table_name="Company")[0]
        assert top.semantic_type is FieldSemanticType.EMAIL

    def test_unrelated_table_name_does_not_manufacture_a_false_match(self) -> None:
        top = suggest_semantic_type("id", table_name="Company")[0]
        assert top.semantic_type is FieldSemanticType.FREE_TEXT


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
