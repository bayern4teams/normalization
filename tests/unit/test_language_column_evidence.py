"""D13: what a LANGUAGE column's own values prove settles `Ga` (ADR-010 amendment 2026-10-27)."""

import pytest
from normalizers.language import LanguageNormalizer, column_language_evidence
from normapi.clone_executor import _proven
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus

# Distinct two- and three-letter ISO 639 codes and distinct English names, taken from ISO 639.
CODES = ["fr", "de", "es", "it", "pt", "nl", "sv", "fi", "pl", "cs"]
NAMES = ["French", "German", "Spanish", "Italian", "Portuguese", "Dutch", "Swedish", "Finnish"]


def _ctx(**kw: object) -> NormalizationContext:
    return NormalizationContext(field_name="lang", semantic_type=FieldSemanticType.LANGUAGE, **kw)


def test_a_column_of_codes_proves_codes() -> None:
    assert column_language_evidence(CODES)["form"] == "code"


def test_a_column_of_names_proves_names() -> None:
    assert column_language_evidence(NAMES)["form"] == "name"


def test_a_mixed_column_proves_nothing() -> None:
    assert column_language_evidence([*CODES, *NAMES])["form"] is None


def test_too_few_values_prove_nothing() -> None:
    assert column_language_evidence(["fr"])["form"] is None


def test_a_value_that_is_both_proves_nothing() -> None:
    assert column_language_evidence(["Ga", "Mon", "Dan"])["form"] is None


@pytest.mark.parametrize(("form", "code"), [("code", "ga"), ("name", "gaa")])
def test_the_column_settles_ga(form: str, code: str) -> None:
    result = LanguageNormalizer().normalize("Ga", _ctx(column_language_form=(form, 8)))
    assert result.normalization_status is NormalizationStatus.NORMALIZED
    assert result.comparison == code
    assert result.structured["evidence"] == "column"


def test_no_evidence_leaves_ga_ambiguous() -> None:
    result = LanguageNormalizer().normalize("Ga", _ctx())
    assert result.normalization_status is NormalizationStatus.AMBIGUOUS
    assert result.comparison is None


def test_a_row_and_a_column_that_disagree_settle_nothing() -> None:
    # Ghana lists `gaa` (the name reading); the column says codes.
    ctx = _ctx(country="GH", column_language_form=("code", 8))
    result = LanguageNormalizer().normalize("Ga", ctx)
    assert result.normalization_status is NormalizationStatus.AMBIGUOUS


def test_a_row_and_a_column_that_agree_settle_it() -> None:
    ctx = _ctx(country="GH", column_language_form=("name", 8))
    assert LanguageNormalizer().normalize("Ga", ctx).comparison == "gaa"


def test_the_clone_reads_the_form_from_the_stored_evidence() -> None:
    job = {"column_evidence": {"t": {"c": {"code": 8, "name": 0, "form": "code"}}}}
    assert _proven(job, "t", "c") == {"column_language_form": ("code", 8)}
