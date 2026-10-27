"""D13 acceptance (derive), report fix 4 and decision R13: the second-pass property test runs for
every code-based type. For country, currency, script, unit (QUANTITY) and language, feeding a
result's `comparison` back in gives the same `comparison`.

Expected values come from the property itself (the report: "normalizing it again gives the same
code"), and the inputs from pycountry and pint. None is read from running a normalizer.

L6: Hypothesis prints the seed and a reproduce blob when a case fails (`print_blob=True`); a
found failure becomes a fixed `@example` in the moved-in copy. The deterministic sweeps below
need no seed.

Names assumed: the five existing normalizer classes and `.normalize(value, ctx)`; `unit` is
`FieldSemanticType.QUANTITY` (the only type `UnitNormalizer` supports).

Run: ( ulimit -v 16777216; uv run pytest -p no:cacheprovider --import-mode=importlib -q \
    .handoff/D13.test_second_pass_property.py )
"""

from __future__ import annotations

import pint
import pycountry
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from normalizers.country import CountryNormalizer
from normalizers.currency import CurrencyNormalizer
from normalizers.language import LanguageNormalizer
from normalizers.script import ScriptNormalizer
from normalizers.unit import UnitNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType as T
from normcore.enums import NormalizationStatus as S

pytestmark = pytest.mark.property

_REFUSED = {S.AMBIGUOUS, S.INVALID, S.FAILED, S.NEEDS_REVIEW}
_SETTINGS = settings(
    max_examples=150,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)


def _pool_country() -> list[str]:
    out = []
    for c in pycountry.countries:
        out += [c.alpha_2, c.alpha_3, c.name, getattr(c, "official_name", c.name)]
    return out


def _pool_currency() -> list[str]:
    out = []
    for c in pycountry.currencies:
        out += [c.alpha_3, c.name, c.numeric]
    return out


def _pool_language() -> list[str]:
    out = []
    for x in pycountry.languages:
        out += [x.alpha_3, x.name]
        if hasattr(x, "alpha_2"):
            out.append(x.alpha_2)
    return out


def _pool_script() -> list[str]:
    # ScriptNormalizer reads a script off text: the names and 4-letter codes of pycountry are
    # inputs it must also leave stable, plus text in several scripts (escapes, not glyphs).
    out = []
    for s in pycountry.scripts:
        out += [s.alpha_4, s.name]
    return [
        *out,
        "Hello",
        "\u041c\u043e\u0441\u043a\u0432\u0430",
        "\u5317\u4eac\u5e02",
        "\u0e01\u0e32",
    ]


def _pool_unit() -> list[str]:
    registry = pint.UnitRegistry()
    names = [n for n in dir(registry) if not n.startswith("_")]
    return [f"{amount} {n}" for n in names for amount in ("5", "12.5")]


_CASES = {
    T.COUNTRY: (CountryNormalizer(), _pool_country()),
    T.CURRENCY: (CurrencyNormalizer(), _pool_currency()),
    T.LANGUAGE: (LanguageNormalizer(), _pool_language()),
    T.SCRIPT: (ScriptNormalizer(), _pool_script()),
    T.QUANTITY: (UnitNormalizer(), _pool_unit()),
}
_IDS = [t.value for t in _CASES]


def _ctx(semantic_type: T, country: str | None) -> NormalizationContext:
    return NormalizationContext(
        field_name="probe", semantic_type=semantic_type, country=country, locale="en-US"
    )


def _second_pass_moves(semantic_type: T, value: str, country: str | None) -> str | None:
    """None when the property holds (or the first pass states no value); else a description."""
    normalizer = _CASES[semantic_type][0]
    ctx = _ctx(semantic_type, country)
    first = normalizer.normalize(value, ctx)
    if first.normalization_status in _REFUSED or first.comparison is None:
        return None
    second = normalizer.normalize(first.comparison, ctx)
    if second.comparison != first.comparison:
        return f"{value!r} -> {first.comparison!r} -> {second.comparison!r}"
    return None


@pytest.mark.parametrize("semantic_type", list(_CASES), ids=_IDS)
@pytest.mark.parametrize("country", [None, "US"])
def test_comparison_is_a_fixed_point_over_the_authoritative_inputs(
    semantic_type: T, country: str | None
) -> None:
    """Deterministic sweep: every pycountry code and name, every pint unit name."""
    pool = _CASES[semantic_type][1]
    assert len(pool) > 100  # the pool is real, not empty
    bad = [m for v in pool if (m := _second_pass_moves(semantic_type, v, country))]
    assert not bad, f"{len(bad)} not stable; first: " + "; ".join(bad[:10])


@pytest.mark.parametrize("semantic_type", list(_CASES), ids=_IDS)
@_SETTINGS
@given(data=st.data())
def test_comparison_is_a_fixed_point_for_pool_and_arbitrary_text(
    semantic_type: T, data: st.DataObject
) -> None:
    """Hypothesis: a pool value, a pool value with its case or edges changed, or free text."""
    pool = _CASES[semantic_type][1]
    base = data.draw(st.sampled_from(pool))
    value = data.draw(
        st.sampled_from(
            [base, base.upper(), base.lower(), f" {base} ", data.draw(st.text(max_size=24))]
        )
    )
    country = data.draw(st.sampled_from([None, "US", "MM", "IE"]))
    moved = _second_pass_moves(semantic_type, value, country)
    assert moved is None, moved


def test_the_pinned_ga_case_holds_on_comparison() -> None:
    """The pre-approved edit of `test_language_ga_script_input_converges_in_one_pass` (plan
    2.9): the first pass of the Thai-script name gives `gaa`; the second pass of the code
    gives `gaa` again. (On `display` the second pass names Irish; display is output only.)"""
    normalizer = LanguageNormalizer()
    ctx = _ctx(T.LANGUAGE, "US")
    first = normalizer.normalize("กา", ctx)
    assert first.comparison == "gaa"
    second = normalizer.normalize(first.comparison, ctx)
    assert second.comparison == first.comparison
    assert second.normalization_status not in _REFUSED


def test_the_property_has_teeth_display_is_not_a_fixed_point() -> None:
    """Teeth: feeding `display` back does not return the first code (before D13 it named Irish,
    now it is AMBIGUOUS), so display is output only (R11) and the contract is the code."""
    normalizer = LanguageNormalizer()
    ctx = _ctx(T.LANGUAGE, "US")
    first = normalizer.normalize("\u0e01\u0e32", ctx)
    assert first.display == "Ga"
    second = normalizer.normalize(first.display, ctx)
    # Fed back, the name is read as a code or stays ambiguous: it is never the first code again.
    assert second.comparison != first.comparison
