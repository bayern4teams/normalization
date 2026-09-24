"""UnitNormalizer must parse a quantity, never evaluate one.

`_UREG(str)` is pint's expression evaluator. Handing a data value to an
evaluator produced three separate faults, one of each kind that matters:
a crash, a silently wrong answer, and a denial of service.
"""

from __future__ import annotations

import pytest
from normalizers.unit import UnitNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus


@pytest.fixture
def normalizer() -> UnitNormalizer:
    return UnitNormalizer()


@pytest.fixture
def ctx() -> NormalizationContext:
    return NormalizationContext(field_name="weight", semantic_type=FieldSemanticType.QUANTITY)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5 kg", "5 kilogram"),
        ("5kg", "5 kilogram"),
        ("100 km/h", "27.77777777777778 meter / second"),
        ("1.5e3 m", "1500.0 meter"),
        ("5 m^2", "5 meter ** 2"),
    ],
)
def test_ordinary_quantities_still_convert(
    normalizer: UnitNormalizer, ctx: NormalizationContext, value: str, expected: str
) -> None:
    assert normalizer.normalize(value, ctx).display == expected


@pytest.mark.parametrize(("value", "kelvin"), [("5 °C", "278.15"), ("-40 degC", "233.1")])
def test_offset_units_work_at_all(
    normalizer: UnitNormalizer, ctx: NormalizationContext, value: str, kelvin: str
) -> None:
    # Every temperature used to raise OffsetUnitCalculusError — a TypeError,
    # which the old `except (..., ValueError)` did not catch, so it escaped
    # the normalizer and would have killed the surrounding clone chunk.
    result = normalizer.normalize(value, ctx)
    assert result.normalization_status is NormalizationStatus.NORMALIZED
    assert result.display.startswith(kelvin)
    assert result.display.endswith("kelvin")


def test_a_compound_measure_is_refused_not_multiplied(
    normalizer: UnitNormalizer, ctx: NormalizationContext
) -> None:
    # Juxtaposition means multiply to an evaluator, so "3 feet 2 inches"
    # silently became an AREA (0.046 m**2). A refusal is recoverable; a
    # plausible wrong number is not.
    result = normalizer.normalize("3 ft 2 in", ctx)
    assert result.normalization_status is NormalizationStatus.INVALID
    assert result.display == "3 ft 2 in"


def test_an_arithmetic_bomb_cannot_exhaust_memory(
    normalizer: UnitNormalizer, ctx: NormalizationContext
) -> None:
    # This genuinely consumed all available memory when evaluated, and
    # nothing bounds a per-value parse. It must be refused immediately.
    result = normalizer.normalize("2**2**99 kg", ctx)
    assert result.normalization_status is NormalizationStatus.INVALID


@pytest.mark.parametrize("value", ["abc", "kg", "1,5 kg"])
def test_values_without_one_clean_magnitude_and_unit_are_refused(
    normalizer: UnitNormalizer, ctx: NormalizationContext, value: str
) -> None:
    # "1,5 kg" is refused deliberately: a comma is ambiguous between a
    # decimal mark and thousands grouping, so it is not guessed at.
    result = normalizer.normalize(value, ctx)
    assert result.normalization_status is NormalizationStatus.INVALID


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_values_are_missing_not_invalid(
    normalizer: UnitNormalizer, ctx: NormalizationContext, value: str
) -> None:
    assert normalizer.normalize(value, ctx).original_kind is not None
