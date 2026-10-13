"""The scorer, proven both ways (plan 8 Phase 0 step 4), and the fixtures proven
self-consistent against their authoritative sources.

No engine under test here: `oracle`, `guesser` and `abstainer` are synthetic
engines, so this file passes before any defect is fixed.
"""

from __future__ import annotations

import importlib
from collections import Counter

import pytest
from normcore.enums import NormalizationStatus as S

from . import fixtures_phase1 as fx
from .scorer import Case, Outcome, classify, real_engine, score

CLEAN = Case("c", "PHONE", "x", "clean", expected_value="+1")
ABSTAIN = Case(
    "a", "DATE", "01/02/2024", "abstain", candidates=frozenset({"2024-01-02", "2024-02-01"})
)
INVALID = Case("i", "TAX_ID", "000", "invalid")


def oracle(case: Case) -> tuple[S, str | None]:
    if case.expected == "clean":
        return S.PARSED, case.expected_value
    return (S.AMBIGUOUS if case.expected == "abstain" else S.INVALID), None


def guesser(case: Case) -> tuple[S, str | None]:
    """Injects a confident wrong value wherever the truth is not a plain clean answer."""
    return S.NORMALIZED, "WRONG"


def abstainer(case: Case) -> tuple[S, str | None]:
    """Needlessly abstains on everything."""
    return S.AMBIGUOUS, None


@pytest.mark.unit
class TestClassify:
    @pytest.mark.parametrize(
        ("case", "status", "value", "outcome"),
        [
            (CLEAN, S.PARSED, "+1", "correct"),
            (CLEAN, S.NORMALIZED, "+1", "correct"),
            (CLEAN, S.PARSED, "+2", "wrong-confident"),
            (CLEAN, S.PARSED, None, "wrong-confident"),
            (CLEAN, S.AMBIGUOUS, None, "over-abstain"),
            (CLEAN, S.INVALID, None, "wrong-status"),
            (CLEAN, S.FAILED, None, "wrong-status"),
            (CLEAN, S.NEEDS_REVIEW, "+1", "wrong-status"),  # not "clean": D12
            (ABSTAIN, S.AMBIGUOUS, "01/02/2024", "correct-abstain"),
            (ABSTAIN, S.PARSED, "2024-01-02", "wrong-confident"),  # a guess, even a plausible one
            (ABSTAIN, S.INVALID, None, "wrong-status"),
            (INVALID, S.INVALID, None, "correct"),
            (INVALID, S.NORMALIZED, "000", "wrong-confident"),
            (INVALID, S.AMBIGUOUS, None, "wrong-status"),
        ],
    )
    def test_table(self, case: Case, status: S, value: str | None, outcome: Outcome) -> None:
        assert classify(case, status, value) == outcome

    def test_every_status_gets_an_outcome(self) -> None:
        for case in (CLEAN, ABSTAIN, INVALID):
            for status in S:
                assert classify(case, status, None) in set(Outcome.__args__)  # type: ignore[attr-defined]


@pytest.mark.unit
class TestScoreBothWays:
    CASES = (CLEAN, ABSTAIN, INVALID)

    def test_oracle_scores_all_correct(self) -> None:
        assert score(self.CASES, oracle) == Counter({"correct": 2, "correct-abstain": 1})

    def test_confident_wrong_value_is_named(self) -> None:
        got = score(self.CASES, guesser)
        assert got["wrong-confident"] == 3 and got["correct"] == 0

    def test_one_injected_guess_among_correct_answers_is_the_only_wrong_confident(self) -> None:
        def mostly_oracle(case: Case) -> tuple[S, str | None]:
            return (S.PARSED, "2024-01-02") if case.id == "a" else oracle(case)

        assert score(self.CASES, mostly_oracle) == Counter({"correct": 2, "wrong-confident": 1})

    def test_needless_abstention_is_named_not_counted_as_safe(self) -> None:
        got = score(self.CASES, abstainer)
        assert got["over-abstain"] == 1  # the clean case
        assert got["correct-abstain"] == 1  # the genuinely ambiguous one is still right
        assert got["wrong-status"] == 1  # the invalid one is not "ambiguous"
        assert got["wrong-confident"] == 0

    def test_empty_input(self) -> None:
        assert score([], oracle) == Counter()


@pytest.mark.unit
class TestRealEngineIsWired:
    """Smoke: the real dispatcher answers the plan's own examples (not a stub)."""

    def test_ambiguous_phone_abstains_and_regioned_phone_is_clean(self) -> None:
        assert real_engine(Case("p", "PHONE", "(212) 555-0123", "abstain"))[0] is S.AMBIGUOUS
        status, value = real_engine(
            Case("p", "PHONE", "(212) 555-0123", "clean", context={"country": "US"})
        )
        assert (status, value) == (S.PARSED, "+12125550123")

    def test_context_is_actually_passed(self) -> None:
        us = real_engine(Case("d", "DATE", "01/02/2024", "clean", context={"country": "US"}))
        de = real_engine(Case("d", "DATE", "01/02/2024", "clean", context={"country": "DE"}))
        assert us[1] != de[1]


@pytest.mark.unit
class TestFixturesAreGroundTruth:
    """The fixtures are built from authoritative sources; check the construction, not the engine."""

    def test_groups_are_non_trivial_and_cover_both_expectations(self) -> None:
        for group in (fx.D1_PHONE_AMBIGUOUS, fx.D1_DATE_AMBIGUOUS, fx.D1_MONEY_AMBIGUOUS):
            assert len(group) >= 3
            assert all(c.expected == "abstain" and len(c.candidates or ()) >= 2 for c in group)
        for group in (fx.D1_PHONE_CLEAN, fx.D1_DATE_CLEAN, fx.D1_MONEY_CLEAN):
            assert group and all(c.expected == "clean" and c.expected_value for c in group)

    def test_ids_are_unique(self) -> None:
        ids = [c.id for c in fx.D1_ALL + fx.D7_ALL + fx.D8_ALL]
        assert len(ids) == len(set(ids))

    def test_date_candidates_are_the_two_calendar_readings(self) -> None:
        case = next(c for c in fx.D1_DATE_AMBIGUOUS if c.input == "01/02/2024")
        assert case.candidates == frozenset({"2024-01-02", "2024-02-01"})

    def test_money_candidates_come_from_cldr(self) -> None:
        case = next(c for c in fx.D1_MONEY_AMBIGUOUS if c.input == "1,234")
        assert case.candidates == frozenset({"1234", "1.234"})

    def test_tax_numbers_use_stdnum_check_digits_for_three_plus_non_registry_countries(
        self,
    ) -> None:
        outside = {cc for cc in fx.TAX_NUMBERS if cc not in {"US", "GB", "DE", "FR"}}
        assert len(outside) >= 3
        modules = {cc: importlib.import_module(m) for cc, m, _ in fx._TAX_SPECS}
        for cc, (good, bad) in fx.TAX_NUMBERS.items():
            assert modules[cc].is_valid(good), cc
            assert not modules[cc].is_valid(bad), cc
            assert len(good) == len(bad)
            assert sum(a != b for a, b in zip(good, bad, strict=True)) == 1  # one character changed

    def test_unlisted_country_really_has_no_stdnum_package(self) -> None:
        assert not fx._stdnum_has_country(fx.UNLISTED_COUNTRY)
        assert fx._stdnum_has_country("PT")

    def test_naive_last_two_labels_is_exposed_by_the_url_table(self) -> None:
        wrong = {
            c.id
            for c in fx.D9_CASES
            if fx.naive_registrable_domain(c.host) not in fx.registrable_answers(c)
        }
        # the report's own argument: a.co.uk, b.a.co.uk, x.github.io, an IP, an unlisted TLD
        assert {"d9-co-uk", "d9-sub-co-uk", "d9-github-io", "d9-ipv4", "d9-unlisted-tld"} <= wrong
        # a single label has no last two, so the naive rule is right about localhost by accident
        assert "d9-localhost" not in wrong
        assert any(c.is_private_suffix for c in fx.D9_CASES)  # ICANN vs PRIVATE is represented
