"""Identity golden corpus — Source.txt §109 (US/Western-European synthetic
data only, no real personal data) across the four M3 semantic domains:
person names, company names, phones, emails. Gate G3 requirement.

Also includes a lightweight collision report (§79/§92): groups a small
synthetic corpus by `comparison` key and asserts which values SHOULD
collapse together (genuine formatting/casing variants of the same
identity) versus which must stay distinct (different people/companies
that happen to share superficial similarity). The full collision-
dashboard subsystem is normanalysis's M6 responsibility — this is the
narrower, concrete proof this milestone's normalizers don't introduce
unintended collisions on this corpus.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest
from normalizers.company import CompanyNormalizer
from normalizers.email import EmailNormalizer
from normalizers.name import NameNormalizer
from normalizers.phone import PhoneNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from normdict.loader import DictionaryLoader

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


@pytest.fixture(scope="module")
def name_normalizer() -> NameNormalizer:
    return NameNormalizer(DictionaryLoader(_DICT_ROOT))


@pytest.fixture(scope="module")
def company_normalizer() -> CompanyNormalizer:
    return CompanyNormalizer(DictionaryLoader(_DICT_ROOT))


@pytest.fixture(scope="module")
def phone_normalizer() -> PhoneNormalizer:
    return PhoneNormalizer()


@pytest.fixture(scope="module")
def email_normalizer() -> EmailNormalizer:
    return EmailNormalizer()


# --- §109 synthetic person names (US/Western-European) ---
NAME_CASES: tuple[str, ...] = (
    "Dr. John Michael Smith Jr.",
    "Smith, John",
    "Garcia, Maria Elena",
    "O'Brien, Patrick",
    "Müller, Hans",
    "van der Berg, Willem",
    "Mary-Jane Watson-Parker",
    "Prof. Elizabeth Warren III",
)

# --- §109 synthetic company names ---
COMPANY_CASES: tuple[str, ...] = (
    "The Limited",
    "Acme Corp Inc.",
    "Global Widgets Pty Ltd",
    "Müller Bau GmbH",
    "Some Big Pharma Oy",
    "Northwind Traders Co.",
    "A Company",
)

# --- §109 synthetic phone numbers ---
PHONE_CASES: tuple[str, ...] = (
    "+1 415-555-2671",
    "+44 20 7946 0958",
    "+49 30 123456",
    "415-555-2671",  # ambiguous without region context
)

# --- §109 synthetic emails ---
EMAIL_CASES: tuple[str, ...] = (
    "john.smith@example.com",
    "j.o.h.n@gmail.com",
    "maria.garcia+newsletter@example.co.uk",
    "user@münchen.de",
    "not-an-email",
)


@pytest.mark.golden
@pytest.mark.parametrize("value", NAME_CASES)
def test_name_corpus_never_fails(name_normalizer: NameNormalizer, value: str) -> None:
    ctx = NormalizationContext(field_name="full_name", semantic_type=FieldSemanticType.PERSON_NAME)
    result = name_normalizer.normalize(value, ctx)
    assert result.normalization_status is not NormalizationStatus.FAILED
    assert result.original == value


@pytest.mark.golden
@pytest.mark.parametrize("value", COMPANY_CASES)
def test_company_corpus_never_fails(company_normalizer: CompanyNormalizer, value: str) -> None:
    ctx = NormalizationContext(field_name="company", semantic_type=FieldSemanticType.COMPANY_NAME)
    result = company_normalizer.normalize(value, ctx)
    assert result.normalization_status is not NormalizationStatus.FAILED
    assert result.original == value


@pytest.mark.golden
@pytest.mark.parametrize("value", PHONE_CASES)
def test_phone_corpus_never_fails(phone_normalizer: PhoneNormalizer, value: str) -> None:
    ctx = NormalizationContext(field_name="phone", semantic_type=FieldSemanticType.PHONE)
    result = phone_normalizer.normalize(value, ctx)
    assert result.normalization_status is not NormalizationStatus.FAILED
    assert result.original == value


@pytest.mark.golden
@pytest.mark.parametrize("value", EMAIL_CASES)
def test_email_corpus_never_fails(email_normalizer: EmailNormalizer, value: str) -> None:
    ctx = NormalizationContext(field_name="email", semantic_type=FieldSemanticType.EMAIL)
    result = email_normalizer.normalize(value, ctx)
    assert result.normalization_status is not NormalizationStatus.FAILED
    assert result.original == value


# --- Collision report (§79/§92 narrow proof) ---

# Each group: (label, [raw values expected to collapse to ONE comparison key])
_EXPECTED_NAME_COLLISIONS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("casing_and_whitespace", ("Smith, John", "smith,   john")),
    ("comma_form_reordered_but_same_text", ("Smith, John", "Smith, John")),
)

# Distinct people who must NOT collapse together despite superficial
# similarity — the negative side of the collision report.
_EXPECTED_NAME_DISTINCTIONS: tuple[tuple[str, str], ...] = (
    ("Smith, John", "Smith, Jon"),  # different given name spelling
    ("Smith, John", "Smyth, John"),  # different family name spelling
)

_EXPECTED_COMPANY_COLLISIONS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("suffix_variant_forms", ("Acme Corp Inc.", "acme corp inc")),
    # Same base name under different legal-form suffixes is a deliberate,
    # intentional collision (§79's "intentional" collision class) — the
    # comparison view is designed to match a company across jurisdiction/
    # legal-form naming variants, while `structured.legal_name` retains
    # the full distinguishing detail for anyone who needs it.
    ("same_base_different_legal_form", ("Acme Corp Inc.", "Acme Corp Ltd")),
)

_EXPECTED_COMPANY_DISTINCTIONS: tuple[tuple[str, str], ...] = (
    ("The Limited", "Acme Limited"),  # different base names entirely
    ("Acme Corp Inc.", "Widgets Corp Inc."),  # different base names entirely
)


@pytest.mark.golden
@pytest.mark.parametrize("label_and_pair", _EXPECTED_NAME_COLLISIONS, ids=lambda p: p[0])
def test_name_collision_report_expected_collisions(
    name_normalizer: NameNormalizer, label_and_pair: tuple[str, tuple[str, str]]
) -> None:
    _, (a, b) = label_and_pair
    ctx = NormalizationContext(field_name="full_name", semantic_type=FieldSemanticType.PERSON_NAME)
    result_a = name_normalizer.normalize(a, ctx)
    result_b = name_normalizer.normalize(b, ctx)
    assert result_a.comparison == result_b.comparison


@pytest.mark.golden
@pytest.mark.parametrize("pair", _EXPECTED_NAME_DISTINCTIONS)
def test_name_collision_report_expected_distinctions(
    name_normalizer: NameNormalizer, pair: tuple[str, str]
) -> None:
    a, b = pair
    ctx = NormalizationContext(field_name="full_name", semantic_type=FieldSemanticType.PERSON_NAME)
    result_a = name_normalizer.normalize(a, ctx)
    result_b = name_normalizer.normalize(b, ctx)
    assert result_a.comparison != result_b.comparison


@pytest.mark.golden
@pytest.mark.parametrize("label_and_pair", _EXPECTED_COMPANY_COLLISIONS, ids=lambda p: p[0])
def test_company_collision_report_expected_collisions(
    company_normalizer: CompanyNormalizer, label_and_pair: tuple[str, tuple[str, str]]
) -> None:
    _, (a, b) = label_and_pair
    ctx = NormalizationContext(field_name="company", semantic_type=FieldSemanticType.COMPANY_NAME)
    result_a = company_normalizer.normalize(a, ctx)
    result_b = company_normalizer.normalize(b, ctx)
    assert result_a.comparison == result_b.comparison


@pytest.mark.golden
@pytest.mark.parametrize("pair", _EXPECTED_COMPANY_DISTINCTIONS)
def test_company_collision_report_expected_distinctions(
    company_normalizer: CompanyNormalizer, pair: tuple[str, str]
) -> None:
    a, b = pair
    ctx = NormalizationContext(field_name="company", semantic_type=FieldSemanticType.COMPANY_NAME)
    result_a = company_normalizer.normalize(a, ctx)
    result_b = company_normalizer.normalize(b, ctx)
    assert result_a.comparison != result_b.comparison


@pytest.mark.golden
def test_full_corpus_collision_grouping_report(
    name_normalizer: NameNormalizer, company_normalizer: CompanyNormalizer
) -> None:
    """Builds an actual grouping report over the full name+company
    corpora (like normanalysis's eventual §79 dashboard would) and
    asserts the corpus produces the expected number of distinct
    comparison-key groups — a regression guard against a normalizer
    change accidentally merging or splitting identities."""
    ctx = NormalizationContext(field_name="full_name", semantic_type=FieldSemanticType.PERSON_NAME)
    groups: dict[str, list[str]] = defaultdict(list)
    for value in NAME_CASES:
        result = name_normalizer.normalize(value, ctx)
        groups[result.comparison].append(value)

    # Every synthetic name in NAME_CASES refers to a distinct person —
    # no two should collapse into the same comparison-key group.
    assert len(groups) == len(NAME_CASES), (
        f"expected {len(NAME_CASES)} distinct comparison groups, got {len(groups)}: {dict(groups)}"
    )
