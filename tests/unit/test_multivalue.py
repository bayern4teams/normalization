"""One cell holding many values.

Sources park serialized lists in text columns. Handing the whole cell to a
single-value normalizer fails every row: one real 35M-row source produced
4.3M identical "invalid email" errors from a single such column, which
said nothing about the data and buried every genuine error. Handled in
Dispatcher.normalize because that is the one point every call path
converges on, so every semantic type gets it without knowing about it.
"""

from __future__ import annotations

import pytest
from normalizers.email import EmailNormalizer

from normcore import (
    Dispatcher,
    FieldSemanticType,
    NormalizationContext,
    NormalizationProfile,
    NormalizationStatus,
    NormalizerRegistry,
    multivalue,
)


@pytest.fixture
def dispatcher() -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(EmailNormalizer())
    return Dispatcher(registry, env_id="test-env")


@pytest.fixture
def profile() -> NormalizationProfile:
    return NormalizationProfile(
        id="p1",
        name="test",
        version="v1",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        created_by="test",
    )


def _normalize(dispatcher: Dispatcher, profile: NormalizationProfile, value: str):
    ctx = NormalizationContext(field_name="mails", semantic_type=FieldSemanticType.EMAIL)
    return dispatcher.normalize(value, FieldSemanticType.EMAIL, ctx, profile)


# --- shape detection ------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "elements", "style"),
    [
        ("['a@b.com', 'c@d.com']", ["a@b.com", "c@d.com"], "python"),
        ('["a@b.com"]', ["a@b.com"], "json"),
        ("[]", [], "json"),
        ("[None, 'x']", [None, "x"], "python"),
    ],
)
def test_list_shapes_are_recognised(value: str, elements: list, style: str) -> None:
    assert multivalue.split(value) == (elements, style)


@pytest.mark.parametrize(
    "value",
    [
        "a@b.com",
        "not a list",
        "Some prose [with brackets] inside",
        '{"k": 1}',
        "[[1], [2]]",  # nested, not scalars
        "",
    ],
)
def test_non_lists_are_left_alone(value: str) -> None:
    assert multivalue.split(value) is None


def test_the_arrival_style_is_preserved(
    dispatcher: Dispatcher, profile: NormalizationProfile
) -> None:
    # Rewriting a Python repr as JSON (or the reverse) would be an
    # unrequested change to data that was not this field's problem.
    assert _normalize(dispatcher, profile, "['a@B.com']").display == "['a@b.com']"
    assert _normalize(dispatcher, profile, '["a@B.com"]').display == '["a@b.com"]'


# --- normalization --------------------------------------------------------


def test_every_element_is_normalized(
    dispatcher: Dispatcher, profile: NormalizationProfile
) -> None:
    result = _normalize(dispatcher, profile, "['a@B.COM', 'c@D.com']")
    assert result.display == "['a@b.com', 'c@d.com']"
    assert result.normalization_status is NormalizationStatus.NORMALIZED
    assert result.errors == []


def test_a_cell_is_only_as_good_as_its_worst_element(
    dispatcher: Dispatcher, profile: NormalizationProfile
) -> None:
    result = _normalize(dispatcher, profile, "['good@x.com', 'not-an-email']")
    assert result.normalization_status is NormalizationStatus.INVALID
    assert len(result.errors) == 1
    assert result.errors[0].startswith("element 1:")


def test_an_empty_list_is_a_real_answer_not_a_malformed_value(
    dispatcher: Dispatcher, profile: NormalizationProfile
) -> None:
    result = _normalize(dispatcher, profile, "[]")
    assert result.display == "[]"
    assert result.errors == []
    assert result.normalization_status is not NormalizationStatus.INVALID


def test_single_values_are_untouched_by_any_of_this(
    dispatcher: Dispatcher, profile: NormalizationProfile
) -> None:
    result = _normalize(dispatcher, profile, "a@B.com")
    assert result.display == "a@b.com"
    assert result.structured.get("element_count") is None


def test_element_count_and_per_element_detail_are_kept(
    dispatcher: Dispatcher, profile: NormalizationProfile
) -> None:
    result = _normalize(dispatcher, profile, "['a@b.com', 'c@d.com']")
    assert result.structured["element_count"] == 2
    assert len(result.structured["elements"]) == 2
