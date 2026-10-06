"""D6 acceptance (derive mode): a gold corpus that measures accuracy, not regression.

Written from improvement-report D6 (Evidence/Fix), plan 2.4 and 9 "D6" and the lead's fixed API,
before any implementation exists. These tests MUST fail today: the import below is the negative
case (`normanalysis.gold` does not exist).

Pure arithmetic is checked against published numbers; the scorer against synthetic engines
(oracle / guesser / abstainer); the injectors against authoritative data (libphonenumber, CLDR via
Babel), never against literals copied out of the implementation.
"""

from __future__ import annotations

import csv
import datetime
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import phonenumbers
import pytest
from babel import Locale
from normanalysis.gold import (
    GoldCase,
    GoldReport,
    cohen_kappa,
    default_engine,
    dump_cases,
    generate_corpus,
    krippendorff_alpha,
    load_cases,
    score,
)
from normcli.cli import main as normcli_main
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus

ROOT = Path(__file__).resolve().parents[2]
CLASSES = ("correct", "correct-abstain", "wrong-confident", "over-abstain")
CLEAN = {"NORMALIZED", "UNCHANGED", "REPAIRED", "PARSED"}
Engine = Callable[[GoldCase], tuple[str, str | None, float | None]]


def _case(  # noqa: PLR0917
    sem: str,
    inp: str,
    status: str,
    value: str | None = None,
    cands: tuple[str, ...] = (),
    ctx: dict[str, str] | None = None,
) -> GoldCase:
    return GoldCase(
        semantic_type=sem,
        context=ctx or {},
        input=inp,
        expected_status=status,
        expected_value=value,
        candidates=cands,
        source="hand-written for this test",
    )


def _outcomes(report: GoldReport, cases: list[GoldCase]) -> list[str]:
    """Per-case outcomes, aligned with `cases`. `report.outcomes` is a list of strings in input
    order, or a list of (case, outcome) pairs. (A dict keyed by case is impossible: the dataclass
    holds a dict, so it is unhashable.)"""
    out = list(report.outcomes)
    assert len(out) == len(cases), "one outcome per case"
    if out and isinstance(out[0], tuple):
        assert [c for c, _ in out] == cases
        return [o for _, o in out]
    return [str(o) for o in out]


def _count(report: GoldReport, klass: str) -> int:
    return report.counts.get(klass, 0)


def oracle(case: GoldCase) -> tuple[str, str | None, float | None]:
    if case.expected_status == "AMBIGUOUS":
        return "AMBIGUOUS", None, None
    return case.expected_status, case.expected_value, 1.0


def guesser(case: GoldCase) -> tuple[str, str | None, float | None]:
    return "PARSED", "WRONG", 0.99


def abstainer(case: GoldCase) -> tuple[str, str | None, float | None]:
    return "AMBIGUOUS", None, None


HAND = [
    _case("PHONE", "x1", "PARSED", "+1"),
    _case("PHONE", "x2", "PARSED", "+2"),
    _case("COUNTRY", "x3", "NORMALIZED", "DE"),
    _case("DATE", "03/04/2024", "AMBIGUOUS", None, ("2024-03-04", "2024-04-03")),
    _case("DATE", "05/06/2024", "AMBIGUOUS", None, ("2024-05-06", "2024-06-05")),
]


# --- the scorer, proven both ways ---


@pytest.mark.unit
class TestScorerBothWays:
    def test_oracle_is_all_correct(self) -> None:
        r = score(HAND, oracle)
        assert _count(r, "correct") == 3
        assert _count(r, "correct-abstain") == 2
        assert _count(r, "wrong-confident") == 0
        assert _count(r, "over-abstain") == 0
        assert _outcomes(r, HAND) == ["correct"] * 3 + ["correct-abstain"] * 2

    def test_counts_cover_the_four_classes_and_sum_to_the_cases(self) -> None:
        r = score(HAND, guesser)
        assert set(CLASSES) <= set(r.counts)
        assert sum(r.counts.get(k, 0) for k in CLASSES) == len(HAND)
        empty = score([], oracle)
        assert all(empty.counts.get(k, 0) == 0 for k in CLASSES)
        assert empty.pairs == []

    def test_wrong_confident_engine_is_caught_and_named_per_case(self) -> None:
        r = score(HAND, guesser)
        assert _outcomes(r, HAND) == ["wrong-confident"] * 5
        assert _count(r, "wrong-confident") == 5
        assert _count(r, "correct") == _count(r, "correct-abstain") == 0

    def test_over_abstaining_engine_is_caught_and_named_per_case(self) -> None:
        r = score(HAND, abstainer)
        assert _outcomes(r, HAND) == ["over-abstain"] * 3 + ["correct-abstain"] * 2
        assert _count(r, "over-abstain") == 3

    def test_a_single_wrong_case_is_named_not_averaged_away(self) -> None:
        def one_wrong(case: GoldCase) -> tuple[str, str | None, float | None]:
            if case.input == "x2":
                return "PARSED", "+999", 0.9
            return oracle(case)

        out = _outcomes(score(HAND, one_wrong), HAND)
        assert [i for i, o in enumerate(out) if o == "wrong-confident"] == [1]
        assert out.count("correct") == 2

    def test_engine_is_called_once_per_case(self) -> None:
        calls: list[str] = []

        def spy(case: GoldCase) -> tuple[str, str | None, float | None]:
            calls.append(case.input)
            return oracle(case)

        score(HAND, spy)
        assert calls == [c.input for c in HAND]

    def test_right_status_wrong_value_is_wrong_confident(self) -> None:
        c = _case("PHONE", "x", "PARSED", "+1")
        assert _count(score([c], lambda _c: ("PARSED", "+2", 0.5)), "wrong-confident") == 1
        assert _count(score([c], lambda _c: ("PARSED", None, 0.5)), "wrong-confident") == 1


@pytest.mark.unit
class TestScorerNeverGuess:
    def test_precise_value_for_a_year_only_truth_is_wrong_confident(self) -> None:
        year_only = _case("DATE", "2024", "PARSED", "2024")
        r = score([year_only], lambda _c: ("PARSED", "2024-01-01", 0.97))
        assert _outcomes(r, [year_only]) == ["wrong-confident"]
        # ... and stating exactly the precision the source had is correct
        assert _outcomes(score([year_only], lambda _c: ("PARSED", "2024", 0.97)), [year_only]) == [
            "correct"
        ]

    def test_answering_an_ambiguous_case_is_wrong_even_with_a_plausible_candidate(self) -> None:
        amb = HAND[3]
        for guess in amb.candidates:
            r = score([amb], lambda _c, g=guess: ("PARSED", g, 0.6))  # type: ignore[misc]
            assert _outcomes(r, [amb]) == ["wrong-confident"]

    def test_abstaining_is_correct_with_or_without_listing_candidates(self) -> None:
        amb = HAND[3]
        for value in (None, amb.candidates[0]):
            r = score([amb], lambda _c, v=value: ("AMBIGUOUS", v, None))  # type: ignore[misc]
            assert _outcomes(r, [amb]) == ["correct-abstain"]

    def test_expected_invalid_answered_with_a_value_is_wrong_confident(self) -> None:
        bad = _case("TAX_ID", "000", "INVALID")
        assert _count(score([bad], lambda _c: ("NORMALIZED", "000", 0.9)), "wrong-confident") == 1
        assert _count(score([bad], lambda _c: ("INVALID", None, None)), "correct") == 1


@pytest.mark.unit
class TestPairsForD2:
    def test_pairs_are_stated_confidence_and_correctness_for_non_abstaining_answers(self) -> None:
        def engine(case: GoldCase) -> tuple[str, str | None, float | None]:
            return {
                "x1": ("PARSED", "+1", 0.9),  # right
                "x2": ("PARSED", "+9", 0.8),  # wrong
                "x3": ("NORMALIZED", "DE", 0.5),  # right
            }.get(case.input, ("AMBIGUOUS", None, None))

        r = score(HAND, engine)
        assert sorted(r.pairs) == [(0.5, True), (0.8, False), (0.9, True)]
        assert all(isinstance(c, float) and isinstance(ok, bool) for c, ok in r.pairs)

    def test_abstentions_contribute_no_pair(self) -> None:
        assert score(HAND, abstainer).pairs == []

    def test_guesser_pairs_are_all_incorrect(self) -> None:
        r = score(HAND, guesser)
        assert r.pairs == [(0.99, False)] * 5

    def test_oracle_pairs_are_the_clean_cases_only(self) -> None:
        assert score(HAND, oracle).pairs == [(1.0, True)] * 3


# --- the real engine, and a corpus that is not vacuous ---


@pytest.mark.unit
class TestDefaultEngine:
    def test_returns_status_value_confidence(self) -> None:
        status, value, conf = default_engine(_case("COUNTRY", "Germany", "NORMALIZED", "DE"))
        assert status in {s.value for s in NormalizationStatus}
        assert value == "DE"
        assert conf is None or 0.0 <= conf <= 1.0

    def test_day_month_swap_is_abstained(self) -> None:
        c = _case("DATE", "03/04/2024", "AMBIGUOUS", None, ("2024-03-04", "2024-04-03"))
        assert default_engine(c)[0] == "AMBIGUOUS"
        assert _outcomes(score([c], default_engine), [c]) == ["correct-abstain"]

    def test_year_only_stays_a_year(self) -> None:
        status, value, _ = default_engine(_case("DATE", "2024", "PARSED", "2024"))
        assert status in CLEAN
        assert value == "2024"

    def test_region_context_is_passed_through(self) -> None:
        no_ctx = _case("PHONE", "(201) 555-0123", "AMBIGUOUS")
        with_ctx = _case("PHONE", "(201) 555-0123", "PARSED", "+12015550123", ctx={"country": "US"})
        assert default_engine(no_ctx)[0] == "AMBIGUOUS"
        assert default_engine(with_ctx)[1] == "+12015550123"


@pytest.mark.unit
class TestCorpusIsNotVacuous:
    def test_real_engine_is_wrong_or_abstains_on_at_least_one_generated_case(self) -> None:
        cases = generate_corpus(seed=0, n_per_injector=30)
        r = score(cases, default_engine)
        out = _outcomes(r, cases)
        bad = [
            (c, o)
            for c, o in zip(cases, out, strict=True)
            if o in {"wrong-confident", "over-abstain"}
        ]
        assert bad, "the engine scores 100%: the injectors only test what already works"
        assert _count(r, "wrong-confident") + _count(r, "over-abstain") == len(bad)
        # and the engine is not simply broken: the same corpus is mostly right
        assert _count(r, "correct") + _count(r, "correct-abstain") > len(cases) // 2

    def test_oracle_on_the_generated_corpus_is_all_correct(self) -> None:
        cases = generate_corpus(seed=3, n_per_injector=10)
        r = score(cases, oracle)
        assert set(_outcomes(r, cases)) <= {"correct", "correct-abstain"}

    def test_injected_engines_are_caught_on_the_generated_corpus(self) -> None:
        cases = generate_corpus(seed=3, n_per_injector=10)
        n_clean = sum(c.expected_status in CLEAN for c in cases)
        n_amb = sum(c.expected_status == "AMBIGUOUS" for c in cases)
        assert n_clean and n_amb, "corpus needs both clean and ambiguous truths"
        assert _count(score(cases, guesser), "wrong-confident") >= n_clean + n_amb
        r = score(cases, abstainer)
        assert _count(r, "over-abstain") == n_clean
        assert _count(r, "correct-abstain") == n_amb


# --- determinism ---


@pytest.mark.unit
class TestDeterminism:
    def test_same_seed_is_byte_identical(self) -> None:
        a = dump_cases(generate_corpus(seed=7, n_per_injector=12))
        b = dump_cases(generate_corpus(seed=7, n_per_injector=12))
        assert a == b
        assert a.encode() == b.encode()

    def test_different_seed_differs(self) -> None:
        a = dump_cases(generate_corpus(seed=7, n_per_injector=12))
        assert a != dump_cases(generate_corpus(seed=8, n_per_injector=12))

    def test_size_follows_n_and_zero_is_empty(self) -> None:
        small = generate_corpus(seed=1, n_per_injector=2)
        big = generate_corpus(seed=1, n_per_injector=6)
        assert 0 < len(small) < len(big)
        assert generate_corpus(seed=1, n_per_injector=0) == []

    def test_dump_is_jsonl_with_the_schema_fields(self) -> None:
        text = dump_cases(generate_corpus(seed=1, n_per_injector=3))
        lines = [ln for ln in text.splitlines() if ln]
        assert lines
        keys = {
            "semantic_type",
            "context",
            "input",
            "expected_status",
            "expected_value",
            "candidates",
            "source",
        }
        for ln in lines:
            assert set(json.loads(ln)) == keys

    def test_dump_load_round_trip(self, tmp_path: Path) -> None:
        cases = generate_corpus(seed=5, n_per_injector=6)
        p = tmp_path / "c.jsonl"
        p.write_text(dump_cases(cases), encoding="utf-8")
        assert load_cases(p) == cases
        assert load_cases(str(p)) == cases

    def test_non_ascii_survives_the_round_trip(self, tmp_path: Path) -> None:
        c = _case("COUNTRY", "Deutschland ü 日本", "NORMALIZED", "DE")
        p = tmp_path / "u.jsonl"
        p.write_text(dump_cases([c]), encoding="utf-8")
        assert load_cases(p) == [c]


# --- the injectors against authoritative truth ---

_DATE = re.compile(r"(\d{1,2})\D+(\d{1,2})\D+(\d{4})")


@pytest.fixture(scope="module")
def corpus() -> list[GoldCase]:
    return generate_corpus(seed=11, n_per_injector=25)


def _of(cases: list[GoldCase], sem: str) -> list[GoldCase]:
    return [c for c in cases if c.semantic_type == sem]


@pytest.mark.unit
class TestInjectors:
    def test_every_injector_family_is_present(self, corpus: list[GoldCase]) -> None:
        assert {"PHONE", "DATE", "NUMERIC", "EMAIL", "URL", "COUNTRY"} <= {
            c.semantic_type for c in corpus
        }

    def test_cases_are_well_formed_for_the_real_engine(self, corpus: list[GoldCase]) -> None:
        fields = set(NormalizationContext.model_fields)
        for c in corpus:
            assert c.semantic_type in FieldSemanticType.__members__
            assert c.expected_status in NormalizationStatus.__members__
            assert set(c.context) <= fields, c
            assert isinstance(c.candidates, tuple)
            assert c.source, "provenance is required"
            if c.expected_status in CLEAN:
                assert c.expected_value is not None
            if c.expected_status == "AMBIGUOUS":
                assert c.expected_value is None

    def test_phone_truth_comes_from_libphonenumber(self, corpus: list[GoldCase]) -> None:
        phones = _of(corpus, "PHONE")
        parsed = [c for c in phones if c.expected_status in CLEAN]
        ambiguous = [c for c in phones if c.expected_status == "AMBIGUOUS"]
        assert parsed
        assert ambiguous, "region removal must yield AMBIGUOUS cases"
        for c in parsed:
            region = c.context.get("country") or c.context.get("default_region")
            n = phonenumbers.parse(c.input, region)
            assert phonenumbers.is_valid_number(n)
            assert phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164) == (
                c.expected_value
            )
        for c in ambiguous:
            assert not {"country", "default_region"} & set(c.context)
            assert not c.input.lstrip().startswith("+")
            with pytest.raises(phonenumbers.NumberParseException):
                phonenumbers.parse(c.input, None)

    def test_date_swaps_are_ambiguous_exactly_when_both_parts_are_at_most_12(
        self, corpus: list[GoldCase]
    ) -> None:
        dates = _of(corpus, "DATE")
        amb = [c for c in dates if c.expected_status == "AMBIGUOUS"]
        assert amb
        for c in amb:
            m = _DATE.fullmatch(c.input.strip())
            assert m, c.input
            a, b, y = (int(x) for x in m.groups())
            assert a <= 12 and b <= 12 and a != b, "a==b is not ambiguous; >12 is not either"
            assert not c.context.get("locale") and not c.context.get("country")
            readings = {datetime.date(y, b, a), datetime.date(y, a, b)}
            assert {datetime.date.fromisoformat(s) for s in c.candidates} == readings
        for c in dates:
            m = _DATE.fullmatch(c.input.strip())
            if m and c.expected_status != "AMBIGUOUS":
                a, b, _ = (int(x) for x in m.groups())
                assert a > 12 or b > 12 or a == b or c.context, c  # never a guess

    def test_numeric_separators_are_ambiguous_without_a_locale(
        self, corpus: list[GoldCase]
    ) -> None:
        nums = _of(corpus, "NUMERIC")
        assert any(c.expected_status == "AMBIGUOUS" for c in nums)
        group_like = re.compile(r"\d{1,3}[.,]\d{3}")
        for c in nums:
            if group_like.fullmatch(c.input.strip()) and not c.context.get("locale"):
                assert c.expected_status == "AMBIGUOUS", c.input
            if c.expected_status in CLEAN:
                assert re.fullmatch(r"-?\d+(\.\d+)?", c.expected_value or ""), c

    def test_email_and_url_case_and_scheme_truth(self, corpus: list[GoldCase]) -> None:
        emails = [c for c in _of(corpus, "EMAIL") if c.expected_status in CLEAN]
        urls = [c for c in _of(corpus, "URL") if c.expected_status in CLEAN]
        assert emails
        assert urls
        for c in emails:
            assert c.input.rsplit("@", 1)[1].lower() == (c.expected_value or "").rsplit("@", 1)[1]
        for c in urls:
            u = urlsplit(c.expected_value or "")
            assert u.scheme == u.scheme.lower() and u.netloc == u.netloc.lower(), c
            assert u.scheme in {"http", "https"}

    def test_country_names_come_from_cldr(self, corpus: list[GoldCase]) -> None:
        countries = [c for c in _of(corpus, "COUNTRY") if c.expected_status in CLEAN]
        assert countries
        names: dict[str, set[str]] = {}
        for loc in ("en", "de", "fr", "es", "it", "ja", "ru"):
            for code, name in Locale(loc).territories.items():
                names.setdefault(code, set()).add(name.casefold())
        for c in countries:
            code = c.expected_value or ""
            assert code in names, f"{code} is not a CLDR territory"
            assert c.input.strip().casefold() in names[code] | {code.casefold()}, c


# --- the loader ---


@pytest.mark.unit
class TestLoader:
    def test_jsonl_hand_written_with_list_candidates(self, tmp_path: Path) -> None:
        row = {
            "semantic_type": "DATE",
            "context": {"locale": "en-GB"},
            "input": "03/04/2024",
            "expected_status": "AMBIGUOUS",
            "expected_value": None,
            "candidates": ["2024-03-04", "2024-04-03"],
            "source": "unit",
        }
        p = tmp_path / "a.jsonl"
        p.write_text(json.dumps(row) + "\n\n", encoding="utf-8")
        (c,) = load_cases(p)
        assert c == GoldCase(**{**row, "candidates": tuple(row["candidates"])})  # type: ignore[arg-type]
        assert isinstance(c.candidates, tuple)

    def _csv(self, tmp_path: Path, rows: list[list[str]], header: list[str]) -> Path:
        p = tmp_path / "raha.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        return p

    def test_csv_dirty_clean_with_keyword_semantic_type(self, tmp_path: Path) -> None:
        p = self._csv(
            tmp_path,
            [["germany", "DE"], ["DE", "DE"], ["Deutschland", "DE"]],
            ["dirty", "clean"],
        )
        cases = load_cases(p, semantic_type="COUNTRY")
        assert [c.input for c in cases] == ["germany", "DE", "Deutschland"]
        for c in cases:
            assert c.semantic_type == "COUNTRY"
            assert c.expected_status == "PARSED"
            assert c.expected_value == "DE"
            assert c.context == {}
            assert c.source

    def test_csv_with_semantic_type_column_extra_columns_and_commas(self, tmp_path: Path) -> None:
        p = self._csv(
            tmp_path,
            [["7", "COUNTRY", "usa", "US"], ["8", "NUMERIC", "1,234.50", "1234.50"]],
            ["tid", "semantic_type", "dirty", "clean"],
        )
        a, b = load_cases(p)
        assert (a.semantic_type, a.input, a.expected_value) == ("COUNTRY", "usa", "US")
        assert (b.semantic_type, b.input, b.expected_value) == ("NUMERIC", "1,234.50", "1234.50")
        assert a.expected_status == b.expected_status == "PARSED"

    def test_csv_dirty_equals_clean_expects_that_value_unchanged(self, tmp_path: Path) -> None:
        p = self._csv(tmp_path, [["2024", "2024"]], ["dirty", "clean"])
        (c,) = load_cases(p, semantic_type="DATE")
        assert (c.expected_status, c.expected_value) == ("PARSED", "2024")  # nothing invents a day

    def test_csv_without_any_semantic_type_is_refused_not_guessed(self, tmp_path: Path) -> None:
        p = self._csv(tmp_path, [["a", "b"]], ["dirty", "clean"])
        with pytest.raises((ValueError, KeyError)):
            load_cases(p)

    def test_csv_unicode(self, tmp_path: Path) -> None:
        p = self._csv(tmp_path, [["München", "München"]], ["dirty", "clean"])
        (c,) = load_cases(p, semantic_type="FREE_TEXT")
        assert c.input == "München"

    def test_a_loaded_csv_is_scoreable(self, tmp_path: Path) -> None:
        p = self._csv(tmp_path, [["germany", "DE"], ["usa", "US"]], ["dirty", "clean"])
        cases = load_cases(p, semantic_type="COUNTRY")
        r = score(cases, default_engine)
        assert sum(r.counts.get(k, 0) for k in CLASSES) == 2


# --- published reference values for kappa and alpha ---


def _labels(table: dict[tuple[str, str], int]) -> tuple[list[str], list[str]]:
    a: list[str] = []
    b: list[str] = []
    for (x, y), n in table.items():
        a += [x] * n
        b += [y] * n
    return a, b


@pytest.mark.unit
class TestKappa:
    def test_artstein_poesio_2008_table2_dialogue_acts(self) -> None:
        # Artstein & Poesio (2008), "Inter-Coder Agreement for Computational Linguistics",
        # Computational Linguistics 34(4), section 2.2 / Table 2: two coders, 100 utterances,
        # tags Stat / IReq. Cells (coder A, coder B): Stat/Stat 20, Stat/IReq 20, IReq/Stat 10,
        # IReq/IReq 50.  (Cell values and the quoted kappa=0.35 reconstructed from the paper's
        # worked example; the number itself is pure arithmetic and re-derived here.)
        #   Ao = (20 + 50) / 100                      = 0.70
        #   A marginals: Stat 40/100, IReq 60/100;  B marginals: Stat 30/100, IReq 70/100
        #   Ae = 0.4*0.3 + 0.6*0.7 = 0.12 + 0.42     = 0.54
        #   kappa = (Ao - Ae) / (1 - Ae) = 0.16 / 0.46 = 0.347826...  (paper: 0.35)
        a, b = _labels(
            {("Stat", "Stat"): 20, ("Stat", "IReq"): 20, ("IReq", "Stat"): 10, ("IReq", "IReq"): 50}
        )
        assert cohen_kappa(a, b) == pytest.approx(0.16 / 0.46, abs=1e-9)
        assert round(cohen_kappa(a, b), 2) == 0.35

    def test_cohen_textbook_50_proposals(self) -> None:
        # Cohen (1960) style example as given on the Wikipedia "Cohen's kappa" page:
        # 50 grant proposals, two readers; Yes/Yes 20, Yes/No 5, No/Yes 10, No/No 15.
        #   Ao = 35/50 = 0.70;  Ae = (25/50)(30/50) + (25/50)(20/50) = 0.30 + 0.20 = 0.50
        #   kappa = (0.70 - 0.50) / (1 - 0.50) = 0.40
        a, b = _labels({("Y", "Y"): 20, ("Y", "N"): 5, ("N", "Y"): 10, ("N", "N"): 15})
        assert cohen_kappa(a, b) == pytest.approx(0.40, abs=1e-9)

    def test_chance_level_agreement_is_zero_and_perfect_is_one(self) -> None:
        # Ao = 0.5, Ae = 0.5  ->  kappa = 0
        assert cohen_kappa([0, 0, 1, 1], [0, 1, 0, 1]) == pytest.approx(0.0, abs=1e-12)
        assert cohen_kappa(list("abcab"), list("abcab")) == pytest.approx(1.0)

    def test_symmetric_and_label_type_agnostic(self) -> None:
        a, b = _labels({("Y", "Y"): 20, ("Y", "N"): 5, ("N", "Y"): 10, ("N", "N"): 15})
        assert cohen_kappa(a, b) == pytest.approx(cohen_kappa(b, a))
        mapped = [{"Y": 1, "N": 0}[x] for x in a], [{"Y": 1, "N": 0}[x] for x in b]
        assert cohen_kappa(*mapped) == pytest.approx(cohen_kappa(a, b))

    def test_unequal_lengths_are_refused(self) -> None:
        with pytest.raises(ValueError):
            cohen_kappa([1, 2, 3], [1, 2])


@pytest.mark.unit
class TestKrippendorffAlpha:
    # Layout decided for this suite: `data` is coders x units (a list of per-coder lists), None
    # marks a missing judgement; units with fewer than two judgements are not pairable and drop out.

    def test_krippendorff_2011_nominal_example_with_missing_data(self) -> None:
        # Krippendorff (2011), "Computing Krippendorff's Alpha-Reliability", the 4 observers x 12
        # units example (also on Wikipedia "Krippendorff's alpha"): nominal alpha = 0.743.
        # Hand derivation: unit 12 has one value -> dropped; n = 40 pairable values; category
        # totals n_c: 1->9, 2->13, 3->10, 4->5, 5->3 (sum 40).  Disagreeing coincidences in the
        # coincidence matrix sum to 8.0.  sum_c n_c^2 = 81+169+100+25+9 = 384, so
        # sum_{c!=k} n_c n_k = 40^2 - 384 = 1216.
        #   alpha = 1 - (n-1) * 8 / 1216 = 1 - 312/1216 = 904/1216 = 0.743421...
        n = None
        data = [
            [1, 2, 3, 3, 2, 1, 4, 1, 2, n, n, n],
            [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, n, 3],
            [n, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, n],
            [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, n],
        ]
        assert krippendorff_alpha(data) == pytest.approx(904 / 1216, abs=1e-9)
        assert krippendorff_alpha(data, level="nominal") == pytest.approx(0.743, abs=5e-4)

    def test_two_coders_at_chance_hand_derived(self) -> None:
        # coders [0,0,1,1] and [0,1,0,1]: n = 8, n_0 = n_1 = 4, off-diagonal coincidences = 4,
        # sum_{c!=k} n_c n_k = 2*4*4 = 32  ->  alpha = 1 - 7*4/32 = 0.125 (kappa here is 0).
        assert krippendorff_alpha([[0, 0, 1, 1], [0, 1, 0, 1]]) == pytest.approx(0.125)

    def test_perfect_agreement_is_one(self) -> None:
        assert krippendorff_alpha([[1, 2, 3, 1], [1, 2, 3, 1], [1, 2, 3, 1]]) == pytest.approx(1.0)

    def test_string_labels_and_missing_values(self) -> None:
        data = [["a", "b", None, "a"], ["a", "b", "c", "a"]]  # unit 3 has one judgement: ignored
        assert krippendorff_alpha(data) == pytest.approx(1.0)

    def test_unknown_level_is_refused_not_defaulted(self) -> None:
        with pytest.raises(ValueError):
            krippendorff_alpha([[1, 2], [1, 2]], level="no-such-level")


# --- the CLI ---


@pytest.mark.unit
class TestCli:
    def test_generate_writes_the_same_bytes_as_dump_cases(self, tmp_path: Path) -> None:
        out = tmp_path / "g.jsonl"
        rc = normcli_main(["gold", "generate", "--seed", "4", "--n", "5", "--out", str(out)])
        assert rc == 0
        assert out.read_text(encoding="utf-8") == dump_cases(generate_corpus(4, 5))
        out2 = tmp_path / "g2.jsonl"
        normcli_main(["gold", "generate", "--seed", "4", "--n", "5", "--out", str(out2)])
        assert out.read_bytes() == out2.read_bytes()

    def test_score_names_every_class_and_the_offending_case(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # "Germany" is plainly NORMALIZED to DE: labelling it AMBIGUOUS makes the real engine
        # wrong-confident on exactly this case, and the report must name it.
        p = tmp_path / "c.jsonl"
        p.write_text(
            dump_cases(
                [
                    _case("DATE", "03/04/2024", "AMBIGUOUS", None, ("2024-03-04", "2024-04-03")),
                    _case("COUNTRY", "Germany", "AMBIGUOUS", None, ("DE",)),
                ]
            ),
            encoding="utf-8",
        )
        capsys.readouterr()
        rc = normcli_main(["gold", "score", str(p)])
        text = capsys.readouterr().out
        assert isinstance(rc, int)
        for k in CLASSES:
            assert k in text
        assert "Germany" in text
        assert re.search(r"wrong-confident\D{0,20}1", text)

    def test_missing_corpus_is_an_error_not_an_empty_report(self, tmp_path: Path) -> None:
        try:
            rc = normcli_main(["gold", "score", str(tmp_path / "nope.jsonl")])
        except (FileNotFoundError, SystemExit, OSError):
            return
        assert rc != 0


# --- plan 2.4: no corpus/fixture literal in non-test code, nothing else touched ---

_BAD = {
    "ISO-code / country table": re.compile(r"""(["'][A-Z]{2}["']\s*,\s*){2,}"""),
    "phone-like literal": re.compile(r"""\d{7,}|["']\+\d"""),
    "email literal": re.compile(r"""["'][^"'@\s]+@[^"'\s]+\.[A-Za-z]{2,}["']"""),
    "url literal": re.compile(r"""["'](https?|ftp)://""", re.IGNORECASE),
    "dd/mm/yyyy literal": re.compile(r"""\d{1,2}[/.-]\d{1,2}[/.-]\d{4}"""),
    "iso date literal": re.compile(r"""\d{4}-\d{2}-\d{2}"""),
    "grouped-number literal": re.compile(r"""["']\d{1,3}[.,]\d{3}"""),
}
_QUOTED = re.compile(r"""["']([^"'\\]{3,})["']""")


def _authoritative_literals() -> set[str]:
    """Strings the authoritative sources produce: every libphonenumber example number (E.164)
    and every CLDR English territory name. A quoted literal equal to one is a copied value."""
    out = {
        phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)
        for r in phonenumbers.SUPPORTED_REGIONS
        if (n := phonenumbers.example_number(r)) is not None
    }
    out |= set(Locale("en").territories.values())
    return out


def _fixture_literals() -> set[str]:
    """Data-like string literals (digits, '@', '://') in the test fixtures and golden corpora."""
    out: set[str] = set()
    files = [
        *(ROOT / "tests" / "defects").glob("fixtures_*.py"),
        *(ROOT / "tests" / "golden").glob("*.py"),
    ]
    for f in files:
        for m in _QUOTED.finditer(f.read_text(encoding="utf-8")):
            s = m.group(1)
            if len(s) >= 6 and (any(ch.isdigit() for ch in s) or "@" in s or "://" in s):
                out.add(s)
    return out


def _violations(added: list[str], banned: set[str] | None = None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in added:
        code = line.lstrip("+").strip()
        if code.startswith("#") or "ponytail:" in code:
            continue
        out += [(name, code) for name, rx in _BAD.items() if rx.search(code)]
        if banned:
            out += [
                ("copied corpus/authoritative value", code)
                for m in _QUOTED.finditer(code)
                if m.group(1) in banned
            ]
    return out


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def _added_lines() -> tuple[list[str], list[str]]:
    """(added lines, scanned files) over packages/normanalysis and packages/normcli: tracked diff
    against HEAD plus every untracked file (a brand-new gold.py is invisible to `git diff`)."""
    paths = ["packages/normanalysis", "packages/normcli"]
    diff = _git("diff", "HEAD", "--unified=0", "--", *paths)
    added = [ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    files = [ln[6:] for ln in diff.splitlines() if ln.startswith("+++ b/")]
    for f in _git("ls-files", "--others", "--exclude-standard", "--", *paths).split():
        if f.endswith(".py"):
            files.append(f)
            added += ["+" + ln for ln in (ROOT / f).read_text(encoding="utf-8").splitlines()]
    return added, files


@pytest.mark.unit
class TestSection24Grep:
    def test_the_grep_catches_what_it_is_meant_to_catch(self) -> None:
        planted = [
            '+_CC = ["US", "GB", "DE"]',
            '+if v == "+14155552671":',
            '+EX = "John.Smith@Example.COM"',
            '+U = "HTTP://Example.COM/a"',
            '+D = "03/04/2024"',
            '+D = "2024-03-04"',
            '+N = "1,234"',
        ]
        assert len(_violations(planted)) >= len(planted)
        assert _violations(['+x = "Germany"', '+y = "+12015550123"'], {"Germany", "+12015550123"})

    def test_the_grep_does_not_flag_clean_code_or_noted_lines(self) -> None:
        clean = [
            "+def score(cases, engine):",
            "+    return Counter(outcome(c, engine(c)) for c in cases)",
            "+    rng = random.Random(seed)",
            "+# example: 03/04/2024 is ambiguous",
            '+K = "03/04/2024"  # ponytail: demo only',
        ]
        assert _violations(clean) == []

    def test_added_lines_hold_no_corpus_value(self) -> None:
        added, files = _added_lines()
        assert any(f.endswith("normanalysis/gold.py") for f in files), "scan must cover gold.py"
        banned = _authoritative_literals() | _fixture_literals()
        assert _violations(added, banned) == [], "authoritative data must produce these values"

    def test_existing_golden_tests_are_untouched(self) -> None:
        assert _git("diff", "HEAD", "--stat", "--", "tests/golden") == ""
        assert _git("status", "--porcelain", "--", "tests/golden").strip() == ""
