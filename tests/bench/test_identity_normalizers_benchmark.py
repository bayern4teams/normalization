"""Performance baseline for the M3 identity normalizers — Source.txt
§102, §122; Gate G3 requirement mirroring M2's bench-baseline pattern.

Run via `uv run pytest -m bench --benchmark-json=bench-results.json`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from normalizers.company import CompanyNormalizer
from normalizers.email import EmailNormalizer
from normalizers.name import NameNormalizer
from normalizers.phone import PhoneNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType
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


@pytest.mark.bench
def test_bench_name_normalize_single_value(
    benchmark: object, name_normalizer: NameNormalizer
) -> None:
    ctx = NormalizationContext(field_name="full_name", semantic_type=FieldSemanticType.PERSON_NAME)
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    benchmark(name_normalizer.normalize, "Dr. John Michael Smith Jr.", ctx)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_company_normalize_single_value(
    benchmark: object, company_normalizer: CompanyNormalizer
) -> None:
    ctx = NormalizationContext(field_name="company", semantic_type=FieldSemanticType.COMPANY_NAME)
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    benchmark(company_normalizer.normalize, "Acme Corp Inc.", ctx)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_phone_normalize_single_value(
    benchmark: object, phone_normalizer: PhoneNormalizer
) -> None:
    ctx = NormalizationContext(field_name="phone", semantic_type=FieldSemanticType.PHONE)
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    benchmark(phone_normalizer.normalize, "+1 415-555-2671", ctx)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_email_normalize_single_value(
    benchmark: object, email_normalizer: EmailNormalizer
) -> None:
    ctx = NormalizationContext(field_name="email", semantic_type=FieldSemanticType.EMAIL)
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    benchmark(email_normalizer.normalize, "John.Smith+tag@Example.com", ctx)  # type: ignore[operator]
