"""Independent acceptance checks for D7 (stdnum catalogue, tri-state) and D8 (TAX_ID/CODE split).

Derived from docs/archive/plans/DEFECTS_IMPLEMENTATION_PLAN.md section 9 (D7, D8 *Accept*) and
docs/improvement-report.md D7/D8, not from the implementation. Target contract:

* `normalizers.identifier.tax_id_module_for(country) -> (chosen | None, candidates)`;
* TAX_ID + country: module found -> validation_status VALID / INVALID by the module's own
  check; no applicable offline validator -> validation_status "UNKNOWN",
  structured["verification"] == "unverifiable", structured["verification_reason"] (str) and,
  with several candidates, structured["candidate_modules"]. Never VALID, never INVALID.
* CODE is only canonicalized; it never carries a check-digit verdict.
* IDENTIFIER output is unchanged (literals below were produced by running the code BEFORE
  D7/D8, on branch feat/defects-fixes, 2026-10-05).

Nothing here counts countries by literal: the catalogue is enumerated from python-stdnum at
run time.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import stdnum
from normapi.app import build_normalizer_registry
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType as F
from normcore.enums import NormalizationStatus

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ holds the `defects` package
from defects.fixtures_phase1 import (
    D7_ALL,
    D8_PAIRS,
    TAX_NUMBERS,
    UNLISTED_COUNTRY,
)
from defects.scorer import classify, real_engine
from normalizers import identifier as identifier_mod

pytestmark = pytest.mark.unit


def _FW(digits: str) -> str:
    return "".join(chr(ord(c) + 0xFEE0) for c in digits)


_COMPAT = frozenset({"US", "GB", "DE", "FR"})  # the four modules that exist today
_REGISTRY = build_normalizer_registry()


def _run(sem: F, text: str | None, country: str | None = None) -> Any:
    ctx = NormalizationContext(field_name="f", semantic_type=sem, country=country)
    return _REGISTRY.require(sem).normalize(text, ctx)


def _stdnum_countries() -> list[str]:
    """Two-letter country packages of the installed python-stdnum (enumerated at run time)."""
    return sorted(
        m.name.upper()
        for m in pkgutil.iter_modules(stdnum.__path__)
        if m.ispkg and len(m.name) == 2
    )


def _resolve(name: str, country: str) -> ModuleType:
    """A module name as `tax_id_module_for` reports it -> the stdnum module (any naming form)."""
    cc = country.lower()
    for dotted in (name, f"stdnum.{name}", f"stdnum.{cc}.{name}", f"stdnum.{cc}_.{name}"):
        try:
            return importlib.import_module(dotted)
        except ImportError:
            continue
    raise AssertionError(f"{name!r} reported for {country} is not an importable stdnum module")


def _classify(country: str) -> tuple[str | None, tuple[str, ...]]:
    result: tuple[str | None, tuple[str, ...]] = identifier_mod.tax_id_module_for(country)  # type: ignore[attr-defined]
    return result


def _assert_unverifiable(r: Any) -> None:
    assert r.validation_status == "UNKNOWN", r.validation_status
    assert r.normalization_status is not NormalizationStatus.INVALID
    s = r.structured
    assert s["verification"] == "unverifiable"
    assert isinstance(s["verification_reason"], str) and s["verification_reason"].strip()
    assert s.get("check_digit_valid") is None  # no True/False verdict of any kind


# ----------------------------------------------------------------------------- D7 discovery


def test_discovery_is_exposed_and_total() -> None:
    """tax_id_module_for exists, returns (str|None, tuple[str,...]) for every stdnum country."""
    assert hasattr(identifier_mod, "tax_id_module_for")
    countries = _stdnum_countries()
    assert countries, "stdnum enumeration returned nothing"
    for cc in countries:
        chosen, cands = _classify(cc)
        assert chosen is None or isinstance(chosen, str)
        assert isinstance(cands, tuple)
        assert all(isinstance(c, str) for c in cands)
        if chosen is not None:
            _resolve(chosen, cc)  # a real stdnum module


def test_discovery_follows_the_library_not_four_entries() -> None:
    """Classified countries (enumerated, no literal count) exceed today's four; none is invented."""
    countries = _stdnum_countries()
    classified = {cc for cc in countries if _classify(cc)[0] is not None}
    assert len(classified - _COMPAT) >= 3
    assert classified <= set(countries)
    # no country the library does not ship may be classified (no hand list ahead of the library)
    for cc in ("ZZ", "XX", "", "NOT-A-COUNTRY"):
        assert _classify(cc) == (None, ())


def test_every_classified_country_is_reachable_through_the_normalizer() -> None:
    """For every country the discovery classifies, TAX_ID routes to that module (VALID iff its
    own is_valid) and never answers 'unverifiable'; every unclassified one is unverifiable."""
    probes = ("0", "123456789", "AB12", "1000000000", "\U0001f642", "x" * 80)
    seen_module = 0
    for cc in _stdnum_countries():
        chosen, _cands = _classify(cc)
        for p in probes:
            r = _run(F.TAX_ID, p, cc)
            if chosen is None:
                _assert_unverifiable(r)
                continue
            module = _resolve(chosen, cc)
            try:
                expected = bool(module.is_valid(r.structured["cleaned"]))
            except Exception:
                expected = False
            # Lead amendment (D7 round 2): a number the chosen module rejects but a
            # sibling module of the same country accepts is unverifiable, not
            # INVALID — the module still ran, so the country is still reachable.
            if r.structured.get("verification_reason", "").startswith("valid under another"):
                assert not expected and r.validation_status == "UNKNOWN", (cc, chosen, p)
                continue
            assert r.validation_status in {"VALID", "INVALID"}, (cc, chosen, p)
            assert r.structured.get("verification") != "unverifiable", (cc, p)
            assert (r.validation_status == "VALID") is expected, (cc, chosen, p)
            if r.validation_status == "INVALID":
                assert r.normalization_status is NormalizationStatus.INVALID
        seen_module += chosen is not None
    assert seen_module > len(_COMPAT)


def _valid_twin_pairs() -> dict[str, tuple[str, str]]:
    """{country: (valid, one-character-changed invalid)} built from each classified module's
    own calc_check_digit, over every country the discovery classifies outside US/GB/DE/FR."""
    out: dict[str, tuple[str, str]] = {}
    for cc in _stdnum_countries():
        chosen, _ = _classify(cc)
        if chosen is None or cc in _COMPAT:
            continue
        mod = _resolve(chosen, cc)
        calc = getattr(mod, "calc_check_digit", None)
        if calc is None:
            continue
        for width in (7, 8, 9, 10, 11):
            found = None
            for body in range(10 ** (width - 1), 10 ** (width - 1) + 300):
                s = str(body)
                try:
                    number = s + str(calc(s))
                    ok = mod.is_valid(number)
                except Exception:
                    break
                if ok:
                    found = number
                    break
            if found:
                twin = next(
                    (
                        found[:-1] + ch
                        for ch in "0123456789"
                        if ch != found[-1] and not mod.is_valid(found[:-1] + ch)
                    ),
                    None,
                )
                if twin:
                    out[cc] = (found, twin)
                break
    return out


def test_generic_valid_and_one_digit_twin_for_many_discovered_countries() -> None:
    pairs = _valid_twin_pairs()
    assert len(pairs) >= 3, (
        f"need >=3 non-compat countries with calc_check_digit, got {sorted(pairs)}"
    )
    for cc, (good, bad) in pairs.items():
        g, b = _run(F.TAX_ID, good, cc), _run(F.TAX_ID, bad, cc)
        assert g.validation_status == "VALID", (cc, good)
        assert b.validation_status == "INVALID", (cc, bad)
        assert b.normalization_status is NormalizationStatus.INVALID
        assert g.structured.get("verification") != "unverifiable"


def test_planted_fixture_numbers_three_or_more_countries() -> None:
    """Planted numbers (fixtures_phase1.TAX_NUMBERS, from stdnum's own check digits): at least
    three non-compat countries validate and their twins fail; any other is unverifiable, never
    VALID/INVALID by guess."""
    ok = 0
    for cc, (good, bad) in TAX_NUMBERS.items():
        assert cc not in _COMPAT
        g, b = _run(F.TAX_ID, good, cc), _run(F.TAX_ID, bad, cc)
        if _classify(cc)[0] is not None:
            assert (g.validation_status, b.validation_status) == ("VALID", "INVALID"), cc
            ok += 1
        else:
            _assert_unverifiable(g)
            _assert_unverifiable(b)
    assert ok >= 3


def test_scorer_no_wrong_confident_and_old_failure_gone() -> None:
    """Phase 0 BEFORE: 6/6 twins wrong-confident, unlisted/no-country VALID. After: none."""
    outcomes = [classify(c, *real_engine(c)) for c in D7_ALL]
    assert "wrong-confident" not in outcomes
    assert outcomes.count("correct") >= 6  # >=3 valid + >=3 invalid twins
    assert outcomes.count("correct-abstain") >= 2  # unlisted country and no country


# ----------------------------------------------------------------------------- D7 tri-state


def test_unlisted_country_is_unverifiable_not_valid_not_invalid() -> None:
    good = TAX_NUMBERS["PT"][0]
    assert _classify(UNLISTED_COUNTRY)[0] is None
    r = _run(F.TAX_ID, good, UNLISTED_COUNTRY)
    _assert_unverifiable(r)
    assert not r.structured.get("candidate_modules")
    # a number valid under another country's module must not leak across countries
    assert _run(F.TAX_ID, good, "PT").validation_status == "VALID"


@pytest.mark.parametrize("country", [None, "", "ZZ"])
def test_no_or_unknown_country_is_unverifiable(country: str | None) -> None:
    for text in (TAX_NUMBERS["PT"][0], TAX_NUMBERS["PT"][1], "garbage"):
        _assert_unverifiable(_run(F.TAX_ID, text, country))


def _is_multi(cc: str) -> bool:
    chosen, cands = _classify(cc)
    return chosen is None and len(cands) > 1


def test_several_candidate_modules_are_unverifiable_and_listed() -> None:
    """Never the first match: where the discovery returns (None, candidates) with len > 1, the
    result lists all candidates and is unverifiable even for a number valid under one of them."""
    multi = [(cc, _classify(cc)[1]) for cc in _stdnum_countries() if _is_multi(cc)]
    if not multi:
        pytest.skip("this stdnum/term list yields no multi-candidate country (property vacuous)")
    for cc, cands in multi:
        r = _run(F.TAX_ID, TAX_NUMBERS["PT"][0], cc)
        _assert_unverifiable(r)
        assert sorted(r.structured["candidate_modules"]) == sorted(cands)
        # also a number each candidate would accept is never picked by the first-match rule
        for name in cands:
            mod = _resolve(name, cc)
            calc = getattr(mod, "calc_check_digit", None)
            if calc is None:
                continue
            try:
                good = next(
                    n for b in range(1000000, 1000300) if mod.is_valid(n := f"{b}{calc(str(b))}")
                )
            except Exception:
                continue
            assert _run(F.TAX_ID, good, cc).validation_status == "UNKNOWN", (cc, name)


def test_chosen_module_has_no_rival_candidate() -> None:
    """Zero-or-several => unverifiable: a chosen module implies no second candidate."""
    for cc in _stdnum_countries():
        chosen, cands = _classify(cc)
        if chosen is not None and cc not in _COMPAT:
            assert set(cands) <= {chosen} or len(cands) <= 1, (cc, chosen, cands)


def test_old_four_countries_outputs_are_byte_identical() -> None:
    """Literals produced by the code BEFORE D7 (US/GB/DE/FR keep today's modules/outputs)."""
    cases = [
        ("042103594", "US", "VALID", "NORMALIZED", 1.0, True, "US"),
        ("12-345", "us", "INVALID", "INVALID", 0.3, False, "US"),
        ("GB980780684", "GB", "VALID", "NORMALIZED", 1.0, True, "GB"),
        ("GB980780685", "GB", "INVALID", "INVALID", 0.3, False, "GB"),
        ("DE136695976", "DE", "VALID", "NORMALIZED", 1.0, True, "DE"),
        ("DE136695977", "DE", "INVALID", "INVALID", 0.3, False, "DE"),
        ("123456782", "fr", "VALID", "NORMALIZED", 1.0, True, "FR"),
        ("123456780", "FR", "INVALID", "INVALID", 0.3, False, "FR"),
        ("garbage", "DE", "INVALID", "INVALID", 0.3, False, "DE"),
    ]
    for text, cc, vstat, nstat, conf, cd, itype in cases:
        r = _run(F.TAX_ID, text, cc)
        cleaned = text.upper()
        assert (r.display, r.comparison, r.search) == (cleaned, cleaned, cleaned)
        assert r.structured == {
            "cleaned": cleaned,
            "has_internal_separator": "-" in text,
            "check_digit_valid": cd,
            "identifier_type": itype,
        }, text
        assert (r.validation_status, r.normalization_status.value, r.confidence) == (
            vstat,
            nstat,
            conf,
        )


def test_missing_values_unchanged_for_tax_id() -> None:
    for text, kind in ((None, "NULL"), ("", "EMPTY_STRING"), ("   ", "EMPTY_STRING")):
        r = _run(F.TAX_ID, text, "PT")
        assert r.validation_status == "MISSING"
        assert r.original_kind is not None and r.original_kind.value == kind


def test_lowercase_country_and_idempotence_tax_id() -> None:
    good, bad = TAX_NUMBERS["PT"]
    assert (
        _run(F.TAX_ID, good, "pt").validation_status == _run(F.TAX_ID, good, "PT").validation_status
    )
    for text, want in ((good, "VALID"), (bad, "INVALID")):
        first = _run(F.TAX_ID, text, "PT")
        again = _run(F.TAX_ID, first.comparison, "PT")
        assert again.comparison == first.comparison
        assert again.validation_status == want


# ----------------------------------------------------------------------------- D8

# Snapshot of IDENTIFIER outputs produced by running the code BEFORE D7/D8 (2026-10-05):
# (input, country) -> (display, comparison, search, structured, validation_status,
#                      normalization_status, confidence, flags)
_IDENT_SNAPSHOT: list[tuple[tuple[str, str | None], tuple[Any, ...]]] = [
    (
        ("  ab-001 ", None),
        (
            "AB-001",
            "AB-001",
            "AB-001",
            {
                "cleaned": "AB-001",
                "has_internal_separator": True,
                "check_digit_valid": None,
                "identifier_type": None,
            },
            "VALID",
            "NORMALIZED",
            1.0,
            ["POTENTIAL_COLLISION"],
        ),
    ),
    (
        ("AB001", None),
        (
            "AB001",
            "AB001",
            "AB001",
            {
                "cleaned": "AB001",
                "has_internal_separator": False,
                "check_digit_valid": None,
                "identifier_type": None,
            },
            "VALID",
            "NORMALIZED",
            1.0,
            [],
        ),
    ),
    (
        ("000123", None),
        (
            "000123",
            "000123",
            "000123",
            {
                "cleaned": "000123",
                "has_internal_separator": False,
                "check_digit_valid": None,
                "identifier_type": None,
            },
            "VALID",
            "NORMALIZED",
            1.0,
            [],
        ),
    ),
    (
        (_FW("123456"), None),
        (
            "123456",
            "123456",
            "123456",
            {
                "cleaned": "123456",
                "has_internal_separator": False,
                "check_digit_valid": None,
                "identifier_type": None,
            },
            "VALID",
            "NORMALIZED",
            1.0,
            [],
        ),
    ),
    (
        ("ab 12-cd", None),
        (
            "AB 12-CD",
            "AB 12-CD",
            "AB 12-CD",
            {
                "cleaned": "AB 12-CD",
                "has_internal_separator": True,
                "check_digit_valid": None,
                "identifier_type": None,
            },
            "VALID",
            "NORMALIZED",
            1.0,
            ["POTENTIAL_COLLISION"],
        ),
    ),
    (  # IDENTIFIER never runs a check digit, even with a country whose module exists
        ("123456780", "FR"),
        (
            "123456780",
            "123456780",
            "123456780",
            {
                "cleaned": "123456780",
                "has_internal_separator": False,
                "check_digit_valid": None,
                "identifier_type": None,
            },
            "VALID",
            "NORMALIZED",
            1.0,
            [],
        ),
    ),
    (
        ("DE136695977", "DE"),
        (
            "DE136695977",
            "DE136695977",
            "DE136695977",
            {
                "cleaned": "DE136695977",
                "has_internal_separator": False,
                "check_digit_valid": None,
                "identifier_type": None,
            },
            "VALID",
            "NORMALIZED",
            1.0,
            [],
        ),
    ),
    (
        ("xxx", "AE"),
        (
            "XXX",
            "XXX",
            "XXX",
            {
                "cleaned": "XXX",
                "has_internal_separator": False,
                "check_digit_valid": None,
                "identifier_type": None,
            },
            "VALID",
            "NORMALIZED",
            1.0,
            [],
        ),
    ),
    (
        ("abc.def/1", None),
        (
            "ABC.DEF/1",
            "ABC.DEF/1",
            "ABC.DEF/1",
            {
                "cleaned": "ABC.DEF/1",
                "has_internal_separator": False,
                "check_digit_valid": None,
                "identifier_type": None,
            },
            "VALID",
            "NORMALIZED",
            1.0,
            [],
        ),
    ),
]


@pytest.mark.parametrize(
    ("key", "want"), _IDENT_SNAPSHOT, ids=[repr(k) for k, _ in _IDENT_SNAPSHOT]
)
def test_identifier_output_unchanged_from_before(
    key: tuple[str, str | None], want: tuple[Any, ...]
) -> None:
    r = _run(F.IDENTIFIER, *key)
    got = (
        r.display,
        r.comparison,
        r.search,
        r.structured,
        r.validation_status,
        r.normalization_status.value,
        r.confidence,
        [f.value for f in r.flags],
    )
    assert got == want


_CHECKISH = re.compile(r"check|valid|verif|luhn|digit", re.I)


def _check_verdicts(structured: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in structured.items() if _CHECKISH.search(k) and isinstance(v, bool)}


def test_code_never_reports_a_check_digit_verdict() -> None:
    """Same strings that TAX_ID judges: CODE gives no verdict, and none of its keys says so."""
    good, bad = TAX_NUMBERS["PT"]
    for text in (good, bad, "123456782", "123456780", "GB980780685", "DE136695977"):
        for cc in (None, "PT", "FR", "GB", "DE", UNLISTED_COUNTRY):
            r = _run(F.CODE, text, cc)
            assert _check_verdicts(r.structured) == {}, (text, cc, r.structured)
            assert r.normalization_status is not NormalizationStatus.INVALID, (text, cc)
            assert r.confidence == 1.0
            assert r.structured.get("identifier_type") is None
        # the verdict cannot depend on the check digit: valid and corrupted twin are alike
    a, b = _run(F.CODE, good, "PT"), _run(F.CODE, bad, "PT")
    assert a.validation_status == b.validation_status
    assert (a.normalization_status, a.confidence) == (b.normalization_status, b.confidence)


def test_code_still_canonicalizes() -> None:
    """Digit folding, case, trim, leading zeros, separators: as before, not widened."""
    cases = {
        "  ab-001 ": "AB-001",
        _FW("123"): "123",
        "000123": "000123",
        "ab 12-cd": "AB 12-CD",
        "abc.def/1": "ABC.DEF/1",
    }
    for text, want in cases.items():
        r = _run(F.CODE, text, None)
        assert (r.display, r.comparison, r.search) == (want, want, want)
        assert r.structured["cleaned"] == want
    assert _run(F.CODE, None).validation_status == "MISSING"
    assert _run(F.CODE, "").validation_status == "MISSING"
    again = _run(F.CODE, _run(F.CODE, "  ab-001 ").comparison)
    assert again.comparison == "AB-001"  # idempotent


def test_same_string_tax_id_vs_code_differs_where_a_check_digit_applies() -> None:
    """Phase 0 BEFORE: identical validation_status in 2 of 3 pairs. After: in 0 of 3."""
    assert len(D8_PAIRS) == 3
    for tax_case, code_case in D8_PAIRS:
        assert tax_case.input == code_case.input and tax_case.context == code_case.context
        tax = _run(F.TAX_ID, tax_case.input, tax_case.context["country"])
        code = _run(F.CODE, code_case.input, code_case.context["country"])
        assert tax.validation_status in {"VALID", "INVALID"}, tax_case.id
        assert tax.validation_status != code.validation_status, (
            tax_case.id,
            code.validation_status,
        )
        # canonical text is shared: the split changes the claim, not the cleaning
        assert tax.comparison == code.comparison


def test_code_invalid_twin_is_not_invalid_while_tax_id_is() -> None:
    for tax_case, code_case in D8_PAIRS:
        if tax_case.expected != "invalid":
            continue
        tax = _run(F.TAX_ID, tax_case.input, tax_case.context["country"])
        code = _run(F.CODE, code_case.input, code_case.context["country"])
        assert tax.validation_status == "INVALID"
        assert code.validation_status != "INVALID"
        assert code.normalization_status is not NormalizationStatus.INVALID


def test_registry_maps_24_of_25_types_to_a_real_normalizer() -> None:
    """Every semantic type except UNKNOWN has a non-passthrough normalizer that handles it."""
    types = list(F)
    real = [
        t
        for t in types
        if (n := _REGISTRY.get(t)) is not None
        and n.name != "PassthroughNormalizer"
        and t in n.supported_types
    ]
    assert F.UNKNOWN not in real
    assert {t for t in types if t is not F.UNKNOWN} == set(real)
    assert len(real) == len(types) - 1  # 24 of 25 follows from the enum, no literal
    assert _REGISTRY.require(F.UNKNOWN).name == "PassthroughNormalizer"
    for t in (F.TAX_ID, F.CODE, F.IDENTIFIER):
        n = _REGISTRY.require(t)
        assert n.can_handle(t, NormalizationContext(field_name="f", semantic_type=t))


def test_code_idempotent_and_tax_id_unchanged_through_dispatcher() -> None:
    """The dispatcher (the real path) sees the same split."""
    from normapi.scaffold_profile import SCAFFOLD_PROFILE  # noqa: PLC0415

    from defects.scorer import _dispatcher  # noqa: PLC0415

    good, bad = TAX_NUMBERS["PT"]
    for sem, text, want in ((F.TAX_ID, bad, "INVALID"), (F.TAX_ID, good, "VALID")):
        ctx = NormalizationContext(field_name="f", semantic_type=sem, country="PT")
        assert _dispatcher().normalize(text, sem, ctx, SCAFFOLD_PROFILE).validation_status == want
    ctx = NormalizationContext(field_name="f", semantic_type=F.CODE, country="PT")
    r = _dispatcher().normalize(bad, F.CODE, ctx, SCAFFOLD_PROFILE)
    assert r.validation_status != "INVALID"


# ----------------------------------------------------------------------------- 2.4 literals


def _iso_like_literals(tree: ast.AST) -> set[str]:
    """Two-letter alphabetic string constants used as elements/keys of a dict/set/list/tuple."""
    found: set[str] = set()
    for node in ast.walk(tree):
        parts: list[ast.expr | None] = []
        if isinstance(node, ast.Dict):
            parts = [*node.keys, *node.values]
        elif isinstance(node, ast.Set | ast.List | ast.Tuple):
            parts = list(node.elts)
        for p in parts:
            if (
                isinstance(p, ast.Constant)
                and isinstance(p.value, str)
                and re.fullmatch(r"[A-Za-z]{2}", p.value)
            ):
                found.add(p.value.upper())
    return found


def test_no_country_list_literal_in_identifier_module() -> None:
    """Plan 2.4: no hand-written ISO country table; only the US/GB/DE/FR compat map may stay."""
    tree = ast.parse(inspect.getsource(identifier_mod))
    assert _iso_like_literals(tree) <= _COMPAT


def test_no_static_import_of_other_country_stdnum_modules() -> None:
    tree = ast.parse(inspect.getsource(identifier_mod))
    countries = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("stdnum."):
            countries.add(node.module.split(".")[1].upper())
        elif isinstance(node, ast.Import):
            countries |= {
                a.name.split(".")[1].upper() for a in node.names if a.name.startswith("stdnum.")
            }
    countries.discard("UTIL")
    countries.discard("LUHN")
    assert countries <= {"US", "GB", "DE", "FR"}, countries
