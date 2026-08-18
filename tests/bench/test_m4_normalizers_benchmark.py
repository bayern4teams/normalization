"""Performance baseline for the M4 standalone normalizers (date, country,
language, script) — Source.txt §102, §122; Gate G4 requirement.
`AddressNormalizer` is excluded here since it requires the live libpostal
sidecar network dependency; its latency is proven directly in
tests/integration/test_address_normalizer_integration.py instead.
"""

from __future__ import annotations

import pytest
from normalizers.country import CountryNormalizer
from normalizers.date import DateNormalizer
from normalizers.language import LanguageNormalizer
from normalizers.script import ScriptNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType


@pytest.fixture(scope="module")
def date_normalizer() -> DateNormalizer:
    return DateNormalizer()


@pytest.fixture(scope="module")
def country_normalizer() -> CountryNormalizer:
    return CountryNormalizer()


@pytest.fixture(scope="module")
def language_normalizer() -> LanguageNormalizer:
    return LanguageNormalizer()


@pytest.fixture(scope="module")
def script_normalizer() -> ScriptNormalizer:
    return ScriptNormalizer()


@pytest.mark.bench
def test_bench_date_normalize_single_value(
    benchmark: object, date_normalizer: DateNormalizer
) -> None:
    ctx = NormalizationContext(field_name="date", semantic_type=FieldSemanticType.DATE)
    benchmark(date_normalizer.normalize, "2026-08-18", ctx)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_country_normalize_single_value(
    benchmark: object, country_normalizer: CountryNormalizer
) -> None:
    ctx = NormalizationContext(field_name="country", semantic_type=FieldSemanticType.COUNTRY)
    benchmark(country_normalizer.normalize, "United States", ctx)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_language_normalize_single_value(
    benchmark: object, language_normalizer: LanguageNormalizer
) -> None:
    ctx = NormalizationContext(field_name="lang", semantic_type=FieldSemanticType.LANGUAGE)
    benchmark(language_normalizer.normalize, "English", ctx)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_script_normalize_single_value(
    benchmark: object, script_normalizer: ScriptNormalizer
) -> None:
    ctx = NormalizationContext(field_name="text", semantic_type=FieldSemanticType.SCRIPT)
    benchmark(script_normalizer.normalize, "Hello world", ctx)  # type: ignore[operator]
