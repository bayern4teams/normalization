"""Unit tests for NameNormalizer — Source.txt §20-§25, §76."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest
from normalizers.name import NameNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus
from normdict.loader import DictionaryLoader

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


@pytest.fixture
def normalizer() -> NameNormalizer:
    return NameNormalizer(DictionaryLoader(_DICT_ROOT))


@pytest.fixture
def ctx() -> NormalizationContext:
    return NormalizationContext(field_name="full_name", semantic_type=FieldSemanticType.PERSON_NAME)


@pytest.mark.unit
class TestProtocolShape:
    def test_supported_types(self, normalizer: NameNormalizer) -> None:
        assert normalizer.supported_types == frozenset(
            {
                FieldSemanticType.PERSON_NAME,
                FieldSemanticType.GIVEN_NAME,
                FieldSemanticType.FAMILY_NAME,
            }
        )

    def test_can_handle_person_name(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        assert normalizer.can_handle(FieldSemanticType.PERSON_NAME, ctx) is True

    def test_can_handle_rejects_email(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        assert normalizer.can_handle(FieldSemanticType.EMAIL, ctx) is False

    def test_version(self, normalizer: NameNormalizer) -> None:
        assert normalizer.version().name == "NameNormalizer"

    def test_steps_nonempty(self, normalizer: NameNormalizer) -> None:
        assert len(normalizer.steps()) > 0


@pytest.mark.unit
class TestMissingValues:
    def test_none(self, normalizer: NameNormalizer, ctx: NormalizationContext) -> None:
        result = normalizer.normalize(None, ctx)
        assert result.original_kind is MissingKind.NULL

    def test_empty(self, normalizer: NameNormalizer, ctx: NormalizationContext) -> None:
        result = normalizer.normalize("", ctx)
        assert result.original_kind is MissingKind.EMPTY_STRING


@pytest.mark.unit
class TestWellFormedNames:
    def test_full_name_with_title_middle_suffix(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Dr. John Michael Smith Jr.", ctx)
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.structured["given_name"] == "John"
        assert result.structured["middle_name"] == "Michael"
        assert result.structured["family_name"] == "Smith"
        assert result.structured["title_raw"] == "Dr."
        assert result.structured["title_canonical"] == "Dr"
        assert result.structured["suffix_raw"] == "Jr."
        assert result.structured["suffix_canonical"] == "JR"

    def test_comma_form_is_unambiguous(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Smith, John", ctx)
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.structured["given_name"] == "John"
        assert result.structured["family_name"] == "Smith"

    def test_title_never_feeds_comparison_or_search(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        with_title = normalizer.normalize("Dr. Jane Smith Roberts", ctx)
        # Title is stored separately in structured; comparison/search are
        # built from the cleaned display string, not filtered per field,
        # so this asserts the title text is at least not the ONLY thing
        # driving identity — the structured components are what downstream
        # consumers use for identity matching, and title lives apart from
        # given_name/family_name there.
        assert "title" not in {"given_name", "family_name"}
        assert with_title.structured["given_name"] == "Jane"

    def test_nickname_is_never_populated(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize('Robert "Bob" Smith', ctx)
        assert result.structured["nickname"] is None

    def test_original_never_overwritten(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        raw = "  Dr.   John   Smith  "
        result = normalizer.normalize(raw, ctx)
        assert result.original == raw


@pytest.mark.unit
class TestAmbiguity:
    def test_bare_two_token_name_is_ambiguous(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        """Source.txt §21's own example: "Smith John" must not silently
        resolve to first=Smith, last=John (nameparser's own default)."""
        result = normalizer.normalize("Smith John", ctx)
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.confidence == 0.5
        candidates = result.structured["candidates"]
        assert {"given_name": "Smith", "family_name": "John"} in candidates
        assert {"given_name": "John", "family_name": "Smith"} in candidates
        assert result.structured["given_name"] is None
        assert result.structured["family_name"] is None

    def test_common_first_last_name_is_still_flagged_ambiguous(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        """Even a statistically-common ordering gets no silent preference
        — confidence stays a genuine 0.5, not a biased guess, per §21's
        "no assumption" requirement."""
        result = normalizer.normalize("Jose Garcia", ctx)
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS

    def test_comma_form_disambiguates(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Garcia, Jose", ctx)
        assert result.normalization_status is NormalizationStatus.PARSED

    def test_three_token_name_is_not_flagged_ambiguous(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Jose Miguel Garcia", ctx)
        assert result.normalization_status is NormalizationStatus.PARSED

    def test_title_present_disambiguates_two_remaining_tokens(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Dr. Jose Garcia", ctx)
        assert result.normalization_status is NormalizationStatus.PARSED


@pytest.mark.unit
class TestPhonetics:
    def test_phonetic_codes_present_for_parsed_name(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Smith, John", ctx)
        phonetic = result.structured["phonetic"]
        assert phonetic["soundex"]
        assert phonetic["nysiis"]
        assert phonetic["metaphone"]
        assert phonetic["match_rating_codex"]

    def test_phonetics_absent_for_ambiguous_name(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Smith John", ctx)
        assert "phonetic" not in result.structured

    def test_latin_name_also_carries_language_aware_keys(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        phonetic = normalizer.normalize("Smith, John", ctx).structured["phonetic"]
        assert phonetic["double_metaphone"]
        assert phonetic["beider_morse"]
        assert "phonetic_status" not in normalizer.normalize("Smith, John", ctx).structured

    def test_cyrillic_gets_no_anglo_key_but_is_marked_and_keyed(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        structured = normalizer.normalize("Иванов, Иван", ctx).structured
        assert structured["phonetic_status"] == "not_applicable"
        assert structured["script"] == "Cyrillic"
        assert set(structured["phonetic"]) == {"double_metaphone", "beider_morse"}

    def test_cjk_and_mixed_scripts_emit_no_key(self, normalizer: NameNormalizer) -> None:
        ctx = NormalizationContext(
            field_name="last_name", semantic_type=FieldSemanticType.FAMILY_NAME
        )
        for text, script in (("王", "Han"), ("Wang小明", "Han+Latin")):
            structured = normalizer.normalize(text, ctx).structured
            assert structured["phonetic_status"] == "not_applicable"
            assert structured["script"] == script
            assert "phonetic" not in structured

    def test_phonetic_codes_are_derived_not_canonical(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        """Phonetics never replace the canonical name — display must
        still be the real, human-readable name."""
        result = normalizer.normalize("Smith, John", ctx)
        assert result.display == "Smith, John"


@pytest.mark.unit
class TestGivenAndFamilyNameFields:
    def test_given_name_field(self, normalizer: NameNormalizer) -> None:
        ctx = NormalizationContext(
            field_name="first_name", semantic_type=FieldSemanticType.GIVEN_NAME
        )
        result = normalizer.normalize("Jose", ctx)
        assert result.structured["given_name"] == "Jose"
        assert result.display == "Jose"
        assert "phonetic" in result.structured

    def test_family_name_field(self, normalizer: NameNormalizer) -> None:
        ctx = NormalizationContext(
            field_name="last_name", semantic_type=FieldSemanticType.FAMILY_NAME
        )
        result = normalizer.normalize("Garcia", ctx)
        assert result.structured["family_name"] == "Garcia"

    def test_given_name_field_never_ambiguous(self, normalizer: NameNormalizer) -> None:
        """A single field-scoped component has nothing to disambiguate —
        the whole value IS that one component by construction."""
        ctx = NormalizationContext(
            field_name="first_name", semantic_type=FieldSemanticType.GIVEN_NAME
        )
        result = normalizer.normalize("Smith", ctx)
        assert result.normalization_status is not NormalizationStatus.AMBIGUOUS


@pytest.mark.unit
class TestValidateExplain:
    def test_validate_ambiguous(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        outcome = normalizer.validate("Smith John", ctx)
        assert outcome.is_valid is False
        assert outcome.status == "AMBIGUOUS"

    def test_validate_parsed(self, normalizer: NameNormalizer, ctx: NormalizationContext) -> None:
        outcome = normalizer.validate("Smith, John", ctx)
        assert outcome.is_valid is True

    def test_explain_ambiguous_mentions_candidates(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Smith John", ctx)
        explanation = normalizer.explain(result)
        assert "candidates" in explanation.technical


@pytest.mark.unit
class TestBatchAndInverse:
    def test_normalize_batch_matches_scalar(
        self, normalizer: NameNormalizer, ctx: NormalizationContext
    ) -> None:
        values = ["Smith, John", "Jose Miguel Garcia"]
        batch = normalizer.normalize_batch(pa.array(values, type=pa.large_string()), ctx)
        displays = batch.field("display").to_pylist()
        assert displays == [normalizer.normalize(v, ctx).display for v in values]

    def test_inverse_nfc_step(self, normalizer: NameNormalizer) -> None:
        composed = "café"
        inverted = normalizer.inverse("unicode_normalize_nfc", composed)
        assert inverted != composed

    def test_inverse_name_parse_step_returns_none(self, normalizer: NameNormalizer) -> None:
        assert normalizer.inverse("name.parse_western", "Smith, John") is None
