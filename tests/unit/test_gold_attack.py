"""D6 attack tests (adversarial verifier): are the generated gold labels TRUE, is the scorer total,
is the loader robust, is the corpus deterministic, do kappa/alpha match an independent computation.

Every truth below is re-derived from libphonenumber / Babel (CLDR) / datetime / RFC 3986 rules with
code written independently of gold.py. `xfail(strict=True)` marks a confirmed defect: it flips to a
failure (XPASS) the day the defect is fixed, so the marker must then be removed.
"""

from __future__ import annotations

import itertools
import math
import os
import random
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import phonenumbers as pn
import pytest
from babel import Locale, localedata
from babel.dates import parse_date
from babel.numbers import parse_decimal
from normanalysis.gold import (
    GoldCase,
    classify,
    cohen_kappa,
    default_engine,
    dump_cases,
    generate_corpus,
    krippendorff_alpha,
    load_cases,
    score,
)
from normcli.cli import main as normcli_main
from normcore.enums import NormalizationStatus

SEEDS = range(6)
N = 120


def _corpus(family: str) -> list[GoldCase]:
    return [c for s in SEEDS for c in generate_corpus(s, N) if c.semantic_type == family]


# ---------------------------------------------------------------- (1) are the labels true?


@pytest.mark.unit
class TestLabelsAreTrue:
    def test_phone_parsed_is_libphonenumber_e164_and_valid(self) -> None:
        for c in _corpus("PHONE"):
            if c.expected_status != "PARSED":
                continue
            region = c.context.get("country") or c.context.get("default_region")
            num = pn.parse(c.input, region)
            assert pn.is_valid_number(num), c
            assert pn.format_number(num, pn.PhoneNumberFormat.E164) == c.expected_value, c

    def test_phone_ambiguous_names_no_country_and_no_region_given(self) -> None:
        n = 0
        for c in _corpus("PHONE"):
            if c.expected_status != "AMBIGUOUS":
                continue
            n += 1
            assert not c.context and not c.input.lstrip().startswith("+"), c
            with pytest.raises(pn.NumberParseException):
                pn.parse(c.input, None)
        assert n > 50

    def test_date_locale_text_means_what_the_cldr_short_pattern_says(self) -> None:
        n = 0
        for c in _corpus("DATE"):
            if not c.source.startswith("date/locale"):
                continue
            n += 1
            loc = Locale.parse(c.context["locale"].replace("-", "_"))
            assert parse_date(c.input, locale=loc, format="short").isoformat() == c.expected_value
        assert n > 50

    def test_date_ambiguous_and_decided_cases_are_what_they_say(self) -> None:
        for c in _corpus("DATE"):
            if c.source.startswith(("date/locale", "date/year-only")):
                continue
            a, b, y = (int(x) for x in re.split(r"[/.\-]", c.input))
            if c.expected_status == "AMBIGUOUS":
                assert a <= 12 and b <= 12 and a != b, c
                assert set(c.candidates) == {f"{y}-{b:02d}-{a:02d}", f"{y}-{a:02d}-{b:02d}"}
            elif a == b:
                assert c.expected_value == f"{y}-{a:02d}-{a:02d}"
            else:  # one part > 12 can only be the day
                day, month = (a, b) if a > 12 else (b, a)
                assert day > 12 and month <= 12, c
                assert c.expected_value == f"{y}-{month:02d}-{day:02d}"

    def test_date_year_only_is_never_promoted(self) -> None:
        ys = [c for c in _corpus("DATE") if c.source.startswith("date/year-only")]
        assert ys and all(c.input == c.expected_value and len(c.input) == 4 for c in ys)

    def test_numeric_locale_text_parses_back_to_the_truth_under_cldr(self) -> None:
        n = 0
        for c in _corpus("NUMERIC"):
            if c.source.startswith("numeric/locale"):
                n += 1
                loc = Locale.parse(c.context["locale"].replace("-", "_"))
                v = parse_decimal(c.input, locale=loc, strict=True)
                assert c.expected_value is not None
                assert v == Decimal(c.expected_value), c
        assert n > 50

    def test_numeric_decided_cases_by_an_independent_rule(self) -> None:
        for c in _corpus("NUMERIC"):
            if c.source.startswith("numeric/locale"):
                continue
            t = c.input
            if c.expected_status == "AMBIGUOUS":
                assert re.fullmatch(r"\d{1,3}[.,]\d{3}", t), c
                assert not c.context
                continue
            if "," in t and "." in t:
                dec = max(",", ".", key=t.rfind)
                grp = "," if dec == "." else "."
                assert t.rfind(grp) < t.rfind(dec) and t.count(dec) == 1, c
                want = t.replace(grp, "").replace(dec, ".")
            else:
                mark = "," if "," in t else "."
                if t.count(mark) > 1:  # a repeating mark groups
                    want = t.replace(mark, "")
                else:  # lone mark followed by 1-2 digits cannot be a group
                    assert mark == "." and len(t.split(".")[1]) in (1, 2), c
                    want = t
            assert want == c.expected_value, c

    def test_country_meaning_is_unique_across_every_cldr_locale(self) -> None:
        meaning: dict[str, set[str]] = {}
        for ident in localedata.locale_identifiers():
            try:
                loc = Locale.parse(ident)
            except Exception:
                continue
            for code, name in loc.territories.items():
                meaning.setdefault(name.casefold(), set()).add(code)
        for c in _corpus("COUNTRY"):
            codes = set(meaning.get(c.input.casefold(), ()))
            if len(c.input) == 2 and c.input.isascii():
                codes.add(c.input.upper())
            assert c.expected_status == "NORMALIZED"  # no ambiguous country exists in 7 locales
            assert codes == {c.expected_value}, (c, codes)

    def test_email_truth_is_rfc5321_domain_lowercase_local_part_kept(self) -> None:
        for c in _corpus("EMAIL"):
            local, _, domain = c.input.strip().rpartition("@")
            assert c.expected_value == f"{local}@{domain.lower()}"
            assert domain.lower().endswith(".example")  # RFC 2606: cannot be a real mailbox

    def test_url_truth_is_rfc3986_scheme_host_lowercase_path_kept(self) -> None:
        for c in _corpus("URL"):
            if c.expected_status == "AMBIGUOUS":
                assert "://" not in c.input
                assert set(c.candidates) == {f"http://{c.input}", f"https://{c.input}"}
                continue
            u = urlsplit(c.input)
            assert c.expected_value == f"{u.scheme.lower()}://{u.netloc.lower()}{u.path}", c

    @pytest.mark.xfail(
        strict=True,
        reason="CONFIRMED label defect: 'NA' (Namibia) is the classic missing-value token. The "
        "text does not state a country, so truth NORMALIZED/NA punishes an engine that abstains",
    )
    def test_no_country_case_collides_with_a_missing_value_token(self) -> None:
        tokens = {"na", "n/a", "nan", "none", "null", "nil"}
        bad = [
            c
            for s in range(50)
            for c in generate_corpus(s, 60)
            if c.semantic_type == "COUNTRY"
            and c.expected_status == "NORMALIZED"
            and c.input.casefold() in tokens
        ]
        assert bad == []


# ---------------------------------------------------------------- (2) classify is total


@pytest.mark.unit
class TestClassifyMatrix:
    CLEAN = ("NORMALIZED", "UNCHANGED", "REPAIRED", "PARSED")
    NONCLEAN = ("AMBIGUOUS", "INVALID", "FAILED", "PARTIAL", "NEEDS_REVIEW")

    @staticmethod
    def _case(truth: str, value: str | None) -> GoldCase:
        return GoldCase("DATE", {}, "x", truth, value, (), "t")

    @pytest.mark.parametrize("status", [s.value for s in NormalizationStatus])
    @pytest.mark.parametrize("value", ["v", "w", None])
    def test_every_combination_lands_in_exactly_one_known_class(
        self, status: str, value: str | None
    ) -> None:
        for truth, ev in (("PARSED", "v"), ("AMBIGUOUS", None), ("INVALID", None)):
            assert classify(self._case(truth, ev), status, value) in {
                "correct",
                "correct-abstain",
                "wrong-confident",
                "over-abstain",
            }

    @pytest.mark.parametrize("status", NONCLEAN)
    @pytest.mark.parametrize("value", ["v", None])
    def test_any_non_clean_answer_to_a_decidable_input_is_over_abstain(
        self, status: str, value: str | None
    ) -> None:
        assert classify(self._case("PARSED", "v"), status, value) == "over-abstain"

    @pytest.mark.parametrize("status", CLEAN)
    def test_clean_answer_to_ambiguous_truth_is_wrong_confident_whatever_the_value(
        self, status: str
    ) -> None:
        for v in ("v", None):
            assert classify(self._case("AMBIGUOUS", None), status, v) == "wrong-confident"

    @pytest.mark.parametrize("status", CLEAN)
    def test_clean_status_without_a_value_is_wrong_confident(self, status: str) -> None:
        assert classify(self._case("PARSED", "v"), status, None) == "wrong-confident"

    @pytest.mark.xfail(
        strict=True,
        reason="CONFIRMED: INVALID/FAILED on an AMBIGUOUS truth is credited correct-abstain. "
        "tests/defects/scorer.py calls it wrong-status; a crash (FAILED) or a confident "
        "'invalid' verdict on '1,234' is not a deliberate abstention",
    )
    @pytest.mark.parametrize("status", ["INVALID", "FAILED"])
    def test_invalid_or_failed_is_not_credited_as_a_deliberate_abstention(
        self, status: str
    ) -> None:
        assert classify(self._case("AMBIGUOUS", None), status, None) != "correct-abstain"

    @pytest.mark.xfail(
        strict=True,
        reason="CONFIRMED: GoldCase accepts a clean truth with expected_value None, and a "
        "value-less clean answer then scores 'correct' (reachable via a short CSV row)",
    )
    def test_a_clean_truth_without_a_value_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            self._case("PARSED", None)

    def test_unknown_status_string_raises_instead_of_being_scored(self) -> None:
        with pytest.raises(ValueError):
            classify(self._case("PARSED", "v"), "BOGUS", "v")

    def test_pairs_only_for_clean_answers_with_a_stated_confidence(self) -> None:
        cases = [self._case("PARSED", "v")] * 4
        answers = iter(
            [
                ("PARSED", "v", 0.9),
                ("PARSED", "w", 0.8),
                ("PARSED", "v", None),
                ("AMBIGUOUS", "v", 0.5),
            ]
        )
        r = score(cases, lambda _c: next(answers))
        assert r.pairs == [(0.9, True), (0.8, False)]
        assert sum(r.counts.values()) == 4


# ---------------------------------------------------------------- (3) loader robustness

_ROW = (
    '{"candidates":[],"context":{},"expected_status":"PARSED","expected_value":"v",'
    '"input":"x","semantic_type":"DATE","source":"s"}'
)


@pytest.mark.unit
class TestLoader:
    def test_empty_and_blank_files(self, tmp_path: Path) -> None:
        for name, body in (
            ("a.jsonl", ""),
            ("b.jsonl", "\n \n"),
            ("c.csv", ""),
            ("d.csv", "dirty,clean\n"),
        ):
            p = tmp_path / name
            p.write_text(body)
            assert load_cases(p, semantic_type="DATE") == []

    @pytest.mark.parametrize(
        "row",
        [
            '{"semantic_type":"DATE","input":"x"}',  # missing keys
            _ROW.replace('"PARSED"', '"BOGUS"'),  # bad status name
            _ROW.replace('"DATE"', '"BOGUS"'),  # bad semantic type
            _ROW.replace('"context":{}', '"context":{"zz":"1"}'),  # bad context field
            _ROW.rstrip("}") + ',"extra":1}',  # unknown key
            "not json",
        ],
    )
    def test_malformed_jsonl_fails_loudly_never_scores(self, tmp_path: Path, row: str) -> None:
        p = tmp_path / "m.jsonl"
        p.write_text(row + "\n")
        with pytest.raises((ValueError, TypeError, KeyError)):
            load_cases(p)

    def test_csv_without_dirty_clean_columns_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "n.csv"
        p.write_text("a,b\n1,2\n")
        with pytest.raises((ValueError, KeyError)):
            load_cases(p, semantic_type="DATE")

    def test_crlf_jsonl(self, tmp_path: Path) -> None:
        p = tmp_path / "x.jsonl"
        p.write_bytes((_ROW + "\r\n" + _ROW + "\r\n").encode())
        assert len(load_cases(p)) == 2

    @pytest.mark.xfail(
        strict=True,
        reason="CONFIRMED: an Excel-style UTF-8 BOM CSV fails with KeyError('dirty'); the header "
        "is read as '\\ufeffdirty'. encoding='utf-8-sig' fixes it",
    )
    def test_csv_with_a_utf8_bom(self, tmp_path: Path) -> None:
        p = tmp_path / "bom.csv"
        p.write_bytes(b"\xef\xbb\xbfdirty,clean\n1,2\n")
        assert load_cases(p, semantic_type="DATE")[0].input == "1"

    @pytest.mark.xfail(
        strict=True,
        reason="CONFIRMED: a JSONL file with a BOM is rejected (JSONDecodeError)",
    )
    def test_jsonl_with_a_utf8_bom(self, tmp_path: Path) -> None:
        p = tmp_path / "bom.jsonl"
        p.write_bytes(b"\xef\xbb\xbf" + _ROW.encode() + b"\n")
        assert len(load_cases(p)) == 1

    @pytest.mark.xfail(
        strict=True,
        reason="CONFIRMED: dump_cases emits raw U+2028/U+2029/U+0085 (ensure_ascii=False) and "
        "load_cases splits lines with str.splitlines(), so a case with such an input cannot "
        "round-trip (JSONDecodeError)",
    )
    @pytest.mark.parametrize("ch", ["\u2028", "\u2029", "\x85"])
    def test_round_trip_survives_unicode_line_separators(self, tmp_path: Path, ch: str) -> None:
        c = GoldCase("DATE", {}, f"a{ch}b", "PARSED", f"a{ch}b", (), "s")
        p = tmp_path / "rt.jsonl"
        p.write_text(dump_cases([c]), encoding="utf-8")
        assert load_cases(p) == [c]

    @pytest.mark.parametrize("ch", ["\x0b", "\x0c", "\x1c", "\r", "\n", "\ufeff", "\x00", "é"])
    def test_round_trip_other_awkward_characters(self, tmp_path: Path, ch: str) -> None:
        c = GoldCase("DATE", {}, f"a{ch}b", "PARSED", f"a{ch}b", (), "s")
        p = tmp_path / "rt.jsonl"
        p.write_text(dump_cases([c]), encoding="utf-8")
        assert load_cases(p) == [c]

    @pytest.mark.xfail(
        strict=True,
        reason="CONFIRMED: a short CSV row ('1' with no clean cell) loads as PARSED with "
        "expected_value None, and a clean answer with value None then scores 'correct'",
    )
    def test_short_csv_row_is_rejected_not_turned_into_a_none_truth(self, tmp_path: Path) -> None:
        p = tmp_path / "short.csv"
        p.write_text("dirty,clean\n1\n")
        with pytest.raises((ValueError, KeyError)):
            load_cases(p, semantic_type="DATE")

    def test_csv_semantic_type_is_never_guessed(self, tmp_path: Path) -> None:
        p = tmp_path / "t.csv"
        p.write_text("dirty,clean\n1,2\n")
        with pytest.raises(ValueError):
            load_cases(p)


# ---------------------------------------------------------------- (4) determinism


@pytest.mark.unit
class TestDeterminism:
    CODE = (
        "import hashlib; from normanalysis.gold import generate_corpus, dump_cases;"
        "print(hashlib.sha256(dump_cases(generate_corpus(7, 40)).encode()).hexdigest())"
    )

    def test_identical_across_processes_and_hash_seeds(self) -> None:
        out = set()
        for h in ("0", "1", "random", "31337"):
            r = subprocess.run(
                [sys.executable, "-I", "-c", self.CODE],
                env={**os.environ, "PYTHONHASHSEED": h},
                capture_output=True,
                text=True,
                check=True,
                cwd="/",
            )
            out.add(r.stdout.strip())
        assert len(out) == 1

    def test_a_larger_n_extends_each_family_and_never_reshuffles_it(self) -> None:
        small, big = generate_corpus(3, 10), generate_corpus(3, 40)
        for fam in ("PHONE", "DATE", "NUMERIC", "EMAIL", "URL", "COUNTRY"):
            a = [c for c in small if c.semantic_type == fam]
            b = [c for c in big if c.semantic_type == fam]
            assert a == b[:10], fam

    def test_seeds_do_not_collide_and_extremes_work(self) -> None:
        assert dump_cases(generate_corpus(1, 5)) != dump_cases(generate_corpus(-1, 5))
        assert dump_cases(generate_corpus(1, 5)) != dump_cases(generate_corpus(2, 5))
        assert len(generate_corpus(2**70, 2)) == 12
        assert generate_corpus(0, 0) == []

    def test_every_kind_appears_once_n_covers_the_kinds(self) -> None:
        kinds = {"/".join(c.source.split()[0].split("/")[:2]) for c in generate_corpus(0, 30)}
        for want in (
            "phone/national+region",
            "phone/international",
            "phone/region-removed",
            "date/swap-ambiguous",
            "date/locale",
            "numeric/locale",
            "url/bare-host",
            "country/code-lower",
            "email/upper-domain",
        ):
            assert want in kinds, want


# ----------------------------------------------- (5) kappa / alpha vs independent code


def _kappa(a: list[int], b: list[int]) -> float:
    n = len(a)
    cats = sorted(set(a) | set(b))
    cm = {(i, j): 0 for i in cats for j in cats}
    for x, y in zip(a, b, strict=True):
        cm[x, y] += 1
    po = sum(cm[c, c] for c in cats) / n
    pe = sum((sum(cm[c, j] for j in cats) / n) * (sum(cm[i, c] for i in cats) / n) for c in cats)
    return math.nan if pe == 1 else (po - pe) / (1 - pe)


def _alpha(data: list[list[int | None]]) -> float:
    units = [[v for v in col if v is not None] for col in zip(*data, strict=True)]
    units = [u for u in units if len(u) >= 2]
    vals = [v for u in units for v in u]
    n = len(vals)
    if n < 2:
        return math.nan
    d_o = (
        sum(sum(x != y for x, y in itertools.permutations(u, 2)) / (len(u) - 1) for u in units) / n
    )
    d_e = sum(x != y for x, y in itertools.permutations(vals, 2)) / (n * (n - 1))
    return math.nan if d_e == 0 else 1 - d_o / d_e


def _same(x: float, y: float) -> bool:
    return (math.isnan(x) and math.isnan(y)) or abs(x - y) < 1e-9


@pytest.mark.unit
class TestAgreement:
    def test_cohen_kappa_matches_an_independent_confusion_matrix_on_random_data(self) -> None:
        rng = random.Random(11)
        for _ in range(1500):
            k, n = rng.randint(1, 4), rng.randint(1, 15)
            a = [rng.randrange(k) for _ in range(n)]
            b = [rng.randrange(k) for _ in range(n)]
            assert _same(cohen_kappa(a, b), _kappa(a, b)), (a, b)

    def test_alpha_matches_an_independent_pair_enumeration_with_missing_data(self) -> None:
        rng = random.Random(12)
        for _ in range(1500):
            k, coders, units = rng.randint(1, 4), rng.randint(1, 5), rng.randint(1, 12)
            data: list[list[int | None]] = [
                [None if rng.random() < 0.3 else rng.randrange(k) for _ in range(units)]
                for _ in range(coders)
            ]
            assert _same(krippendorff_alpha(data), _alpha(data)), data

    def test_undefined_cases_are_nan_not_a_number_and_not_an_exception(self) -> None:
        assert math.isnan(krippendorff_alpha([]))
        assert math.isnan(krippendorff_alpha([[1, 2]]))  # one coder: nothing pairable
        assert math.isnan(krippendorff_alpha([[None, None], [None, None]]))
        assert math.isnan(krippendorff_alpha([[1, 1], [1, 1]]))  # no variation: undefined
        assert math.isnan(cohen_kappa([1, 1], [1, 1]))

    def test_alpha_two_unit_disagreement_known_value(self) -> None:
        # [[0,1],[1,0]]: every unit disagrees, alpha = 1 - D_o/D_e = 1 - 1/(2/3) = -0.5
        assert krippendorff_alpha([[0, 1], [1, 0]]) == pytest.approx(-0.5)

    def test_bad_shapes_raise(self) -> None:
        with pytest.raises(ValueError):
            krippendorff_alpha([[1, 2], [1]])
        with pytest.raises(ValueError):
            cohen_kappa([], [])
        with pytest.raises(ValueError):
            cohen_kappa([1], [1, 2])


# ---------------------------------------------------------------- (6) CLI


@pytest.mark.unit
class TestCli:
    def test_generate_then_score_a_jsonl_prints_four_classes_and_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = tmp_path / "g.jsonl"
        assert normcli_main(["gold", "generate", "--seed", "2", "--n", "6", "--out", str(p)]) == 0
        assert p.read_text() == dump_cases(generate_corpus(2, 6))
        assert normcli_main(["gold", "score", str(p)]) == 0
        out = capsys.readouterr().out
        for name in ("correct:", "correct-abstain:", "wrong-confident:", "over-abstain:"):
            assert name in out
        assert "36 cases" in out

    def test_score_a_csv_with_the_type_flag_and_without(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = tmp_path / "c.csv"
        p.write_text("dirty,clean\nGermany,DE\nFrance,FR\n")
        assert normcli_main(["gold", "score", str(p), "--semantic-type", "COUNTRY"]) == 0
        assert "correct: 2" in capsys.readouterr().out
        assert normcli_main(["gold", "score", str(p)]) == 2  # type never guessed
        assert "semantic_type" in capsys.readouterr().err

    def test_a_wrong_label_is_named_in_the_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = tmp_path / "w.csv"
        p.write_text("dirty,clean\nGermany,FR\n")
        assert normcli_main(["gold", "score", str(p), "--semantic-type", "COUNTRY"]) == 0
        out = capsys.readouterr().out
        assert "wrong-confident: 1" in out and "'Germany'" in out

    @pytest.mark.parametrize("name", ["missing.jsonl", "bad.jsonl"])
    def test_unreadable_or_malformed_corpus_exits_2(self, tmp_path: Path, name: str) -> None:
        p = tmp_path / name
        if name == "bad.jsonl":
            p.write_text("{nope\n")
        assert normcli_main(["gold", "score", str(p)]) == 2

    @pytest.mark.xfail(
        strict=True,
        reason="CONFIRMED: `gold generate --out` into a missing directory is an uncaught "
        "FileNotFoundError traceback (rc 1), unlike `gold score` which exits 2 with a message",
    )
    def test_generate_to_a_missing_directory_exits_2_not_a_traceback(self, tmp_path: Path) -> None:
        assert normcli_main(["gold", "generate", "--out", str(tmp_path / "no" / "x.jsonl")]) == 2


# ---------------------------------------------------------------- (8) the real engine on the corpus

# Known, triaged reasons the real engine disagrees with a TRUE label (see D6 verdict). The set may
# only shrink as engine defects are fixed; a case outside it is a new finding or a bad label.
_TRIAGED = {
    ("DATE", "date/same-day-month"),  # engine abstains though both readings give one date
    ("DATE", "date/locale"),  # engine hand table _MDY_COUNTRIES = {US}, CLDR has 34 M/d/y locales
    ("URL", "url/bare-host"),  # policy: engine assumes https; the label says never invent
    ("COUNTRY", "country/code"),  # 'NA' = Namibia vs missing token (label defect above)
    ("COUNTRY", "country/code-lower"),
}


@pytest.mark.unit
def test_every_real_engine_miss_on_the_corpus_is_triaged() -> None:
    cases = generate_corpus(0, 30)
    r = score(cases, default_engine)
    assert sum(r.counts.values()) == len(cases)
    assert r.counts["correct"] > len(cases) // 2
    untriaged = [
        (c, a)
        for c, o, a in zip(cases, r.outcomes, r.answers, strict=True)
        if o in {"wrong-confident", "over-abstain"}
        and (c.semantic_type, c.source.split()[0]) not in _TRIAGED
    ]
    assert untriaged == []


@pytest.mark.unit
def test_real_engine_phone_numeric_email_country_have_no_misses_on_a_wider_corpus() -> None:
    cases = [c for c in generate_corpus(5, 150) if c.semantic_type in {"PHONE", "NUMERIC", "EMAIL"}]
    r = score(cases, default_engine)
    bad = [
        (c, a)
        for c, o, a in zip(cases, r.outcomes, r.answers, strict=True)
        if o not in {"correct", "correct-abstain"}
    ]
    assert bad == []
