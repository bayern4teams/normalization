"""Unit tests for CompanyNormalizer — Source.txt §26-§28."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest
from normalizers.company import CompanyNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus, Reversibility
from normcore.errors import NormalizerFailure
from normdict.loader import DictionaryLoader

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


@pytest.fixture
def normalizer() -> CompanyNormalizer:
    return CompanyNormalizer(DictionaryLoader(_DICT_ROOT))


@pytest.fixture
def ctx() -> NormalizationContext:
    return NormalizationContext(
        field_name="company_name", semantic_type=FieldSemanticType.COMPANY_NAME
    )


@pytest.mark.unit
class TestProtocolShape:
    def test_supported_types(self, normalizer: CompanyNormalizer) -> None:
        assert normalizer.supported_types == frozenset({FieldSemanticType.COMPANY_NAME})

    def test_version(self, normalizer: CompanyNormalizer) -> None:
        assert normalizer.version().name == "CompanyNormalizer"


@pytest.mark.unit
class TestMissingValues:
    def test_none(self, normalizer: CompanyNormalizer, ctx: NormalizationContext) -> None:
        result = normalizer.normalize(None, ctx)
        assert result.original_kind is MissingKind.NULL

    def test_empty(self, normalizer: CompanyNormalizer, ctx: NormalizationContext) -> None:
        result = normalizer.normalize("", ctx)
        assert result.original_kind is MissingKind.EMPTY_STRING


@pytest.mark.unit
class TestConservativeSuffixStripping:
    def test_the_limited_is_never_stripped_to_the(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        """Source.txt §26's mandatory golden test. cleanco.basename("The
        Limited") was independently verified in M3 to return "The" —
        this is exactly the bug this module's conservative stripper
        exists to avoid."""
        result = normalizer.normalize("The Limited", ctx)
        assert result.structured["base_name"] == "The Limited"
        assert result.structured["organization_type"] is None

    def test_a_company_is_never_stripped_to_a(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("A Company", ctx)
        assert result.structured["base_name"] == "A Company"

    def test_the_company_is_never_stripped(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("The Company", ctx)
        assert result.structured["base_name"] == "The Company"

    def test_ordinary_suffix_is_stripped(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Acme Corp Inc.", ctx)
        assert result.structured["base_name"] == "Acme Corp"
        assert result.structured["organization_type"] == "Corporation"
        assert result.structured["elf_code"] is not None

    def test_multi_word_suffix_is_stripped(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Widgets Pty Ltd", ctx)
        assert result.structured["base_name"] == "Widgets"
        assert result.structured["organization_type"] == "Proprietary Limited Company"

    def test_no_suffix_present_leaves_name_unchanged(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Wonderland Systems", ctx)
        assert result.structured["base_name"] == "Wonderland Systems"
        assert result.structured["organization_type"] is None

    def test_original_never_overwritten(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        raw = "  Acme  Corp   Inc.  "
        result = normalizer.normalize(raw, ctx)
        assert result.original == raw


@pytest.mark.unit
class TestJurisdictionHint:
    def test_finnish_oy_hint(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        """Source.txt §28's own worked example."""
        result = normalizer.normalize("Some Big Pharma Oy", ctx)
        assert result.structured["base_name"] == "Some Big Pharma"
        assert result.structured["jurisdiction_hint"] == "FI"

    def test_german_gmbh_hint(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Müller GmbH", ctx)
        assert result.structured["jurisdiction_hint"] == "DE"

    def test_ambiguous_suffix_gets_no_hint(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        """ "SA" is used by many countries (France, Spain, Switzerland,
        ...) — never asserted as a single jurisdiction fact (§28)."""
        result = normalizer.normalize("Foo Bar SA", ctx)
        assert result.structured["jurisdiction_hint"] is None

    def test_jurisdiction_hint_is_never_treated_as_asserted_fact(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Some Big Pharma Oy", ctx)
        assert "jurisdiction" not in result.structured  # only "jurisdiction_hint" exists
        assert "jurisdiction_hint" in result.structured


@pytest.mark.unit
class TestStatusAndViews:
    def test_unchanged_status_when_nothing_normalized(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Wonderland Systems", ctx)
        assert result.normalization_status is NormalizationStatus.UNCHANGED

    def test_normalized_status_when_suffix_stripped(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Acme Corp Inc.", ctx)
        assert result.normalization_status is NormalizationStatus.NORMALIZED

    def test_display_keeps_full_legal_name(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        """`display` is the full cleaned legal name, INCLUDING the
        suffix — stripping only happens in the `structured.base_name`
        derived view, never destructively on `display`."""
        result = normalizer.normalize("Acme Corp Inc.", ctx)
        assert result.display == "Acme Corp Inc."

    def test_comparison_uses_base_name_not_legal_name(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Acme Corp Inc.", ctx)
        assert result.comparison is not None
        assert "inc" not in result.comparison.casefold()
        assert "acme corp" in result.comparison.casefold()


@pytest.mark.unit
class TestExactFields:
    """A real mutmut run (M12) found 43 surviving mutants in
    `CompanyNormalizer.normalize` — mostly literal constants (`VALID`,
    `1.0`, `""`) and the `strip_changed or unicode_result.changed`
    boolean-or the field checks above never pinned down exactly."""

    def test_no_suffix_no_cleanup_change_every_field(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Wonderland Systems", ctx)
        assert result.original == "Wonderland Systems"
        assert result.display == "Wonderland Systems"
        assert result.comparison == "wonderland systems"
        assert result.search == result.comparison
        assert result.structured == {
            "legal_name": "Wonderland Systems",
            "base_name": "Wonderland Systems",
            "organization_type": None,
            "elf_code": None,
            "jurisdiction_hint": None,
            "suffix_canonical": None,
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.UNCHANGED
        assert result.confidence == 1.0
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert result.trace[-1].rule_id == "company.strip_legal_suffix"
        assert result.trace[-1].changed is False
        assert result.trace[-1].lossy is True
        assert result.trace[-1].library == "normalizers"

    def test_cleanup_change_without_suffix_strip_is_still_normalized(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        """`status` is `strip_changed OR unicode_result.changed` — extra
        whitespace collapsed by unicode cleanup alone (no suffix to
        strip) must still flip status to NORMALIZED, proving this is a
        real OR and neither operand alone."""
        result = normalizer.normalize("  Wonderland   Systems  ", ctx)
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.display == "Wonderland Systems"
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.trace[-1].changed is False  # the suffix-strip step itself didn't change

    def test_suffix_stripped_every_field(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("Acme Corp Inc.", ctx)
        assert result.original == "Acme Corp Inc."
        assert result.display == "Acme Corp Inc."
        assert result.comparison == "acme corp"
        assert result.search == "acme corp"
        assert result.structured == {
            "legal_name": "Acme Corp Inc.",
            "base_name": "Acme Corp",
            "organization_type": "Corporation",
            "elf_code": "XXX1",
            "jurisdiction_hint": "US",
            "suffix_canonical": "Inc",
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.lossiness is Reversibility.PARTIALLY_REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""
        assert result.trace[-1].changed is True
        assert result.trace[-1].lossy is True

    def test_comparison_applies_punctuation_normalization_after_casefold(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        """`comparison` is `normalize_punctuation(casefold(base_name))`
        — a base name that itself contains punctuation (not just the
        stripped suffix) must go through both steps, not just casefold."""
        result = normalizer.normalize("Acme, Corp. Inc.", ctx)
        assert result.structured["base_name"] == "Acme, Corp."
        assert result.comparison == "acme, corp."

    def test_missing_none_every_field(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize(None, ctx)
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0
        assert result.display is None
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_missing_empty_every_field(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("", ctx)
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_unicode_processing_failure_raises_normalizer_failure_with_exact_message(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        """`self._unicode.process()` failing is wrapped into a
        `NormalizerFailure` — the message/operation must be exact, not
        just "an exception happened"."""

        class BoomUnicode:
            def process(self, value: str, options: object) -> object:
                raise RuntimeError("unicode boom")

        normalizer._unicode = BoomUnicode()  # type: ignore[assignment]
        with pytest.raises(NormalizerFailure) as excinfo:
            normalizer.normalize("Acme Inc", ctx)
        assert str(excinfo.value) == (
            "UnicodeNormalizer failed on field 'company_name': unicode boom"
        )
        assert excinfo.value.operation == "unicode_process"

    def test_turkish_locale_uses_dotless_i_casefold(self, normalizer: CompanyNormalizer) -> None:
        """`comparison` is `text_ops.casefold(base_name, ctx.locale)` —
        Turkish casefolding of 'I' differs from the locale-agnostic
        default (U+0131 dotless-i vs U+0069 dotted-i), verified against
        the real ICU casefold implementation before writing this
        assertion."""
        ctx_tr = NormalizationContext(
            field_name="company_name", semantic_type=FieldSemanticType.COMPANY_NAME, locale="tr"
        )
        result = normalizer.normalize("ISTANBUL Systems", ctx_tr)
        dotless_i = chr(0x0131)  # RUF001: avoid the ambiguous glyph literally in source
        assert result.comparison == f"{dotless_i}stanbul systems"

    def test_no_locale_uses_default_casefold(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("ISTANBUL Systems", ctx)
        assert result.comparison == "istanbul systems"


@pytest.mark.unit
class TestBatchAndInverse:
    def test_normalize_batch_matches_scalar(
        self, normalizer: CompanyNormalizer, ctx: NormalizationContext
    ) -> None:
        values = ["Acme Corp Inc.", "The Limited"]
        batch = normalizer.normalize_batch(pa.array(values, type=pa.large_string()), ctx)
        displays = batch.field("display").to_pylist()
        assert displays == [normalizer.normalize(v, ctx).display for v in values]

    def test_inverse_suffix_strip_returns_none(self, normalizer: CompanyNormalizer) -> None:
        assert normalizer.inverse("company.strip_legal_suffix", "Acme Corp") is None
