"""D13 acceptance (derive): the LANGUAGE code is the contract.

Written from `docs/improvement-report.md` D13 ("Verified state", "Fix", decisions R11-R13) and
the plan, section 9, before any implementation. Every expected value comes from pycountry (ISO
639), from CLDR territory data read through Babel (`territory_languages`), from BCP 47 or from
the report's own table. None comes from running the normalizer.

Names assumed (the existing public surface only):
- `normalizers.language.LanguageNormalizer().normalize(value, ctx)`
- row evidence: `NormalizationContext(country="MM")`, the ISO 3166 alpha-2 country the clone
  executor already gives every non-COUNTRY column of a row.
- the language code is `NormalizedValue.comparison`: ISO 639-1 where one exists, else the ISO
  639-3 code (the report's own rows: `ga`, `gaa`, `ukv`, `mn`, `da`).

Run: ( ulimit -v 16777216; uv run pytest -p no:cacheprovider --import-mode=importlib -q \
    tests/unit/test_language_code_contract.py )
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pycountry
import pytest
from babel.core import get_global
from normalizers.language import LanguageNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType as T
from normcore.enums import NormalizationStatus as S

pytestmark = pytest.mark.unit

_NORMALIZER = LanguageNormalizer()
_LANGS = list(pycountry.languages)
_REFUSED = {S.AMBIGUOUS, S.INVALID, S.FAILED, S.NEEDS_REVIEW}
_REPO = Path(__file__).resolve().parents[2]
_LANGUAGE_PY = _REPO / "packages" / "normalizers" / "src" / "normalizers" / "language.py"


def _ctx(country: str | None = None) -> NormalizationContext:
    return NormalizationContext(field_name="lang", semantic_type=T.LANGUAGE, country=country)


def _code(lang: pycountry.db.Data) -> str:
    """The report's `comparison` convention: ISO 639-1 if it exists, else ISO 639-3."""
    return getattr(lang, "alpha_2", None) or lang.alpha_3


def _by_name(name: str) -> pycountry.db.Data:
    hits = [x for x in _LANGS if x.name == name]
    assert len(hits) == 1, f"pycountry has {len(hits)} languages named {name!r}"
    return hits[0]


def _collisions() -> list[tuple[pycountry.db.Data, pycountry.db.Data]]:
    """(language whose NAME is the text, language whose CODE is the text), computed from
    pycountry: the text is a 2- or 3-letter name and, lowercased, another language's ISO 639-1
    or ISO 639-3 code (report cause 3)."""
    by_code = {}
    for x in _LANGS:
        by_code[x.alpha_3] = x
        if hasattr(x, "alpha_2"):
            by_code[x.alpha_2] = x
    pairs = []
    for x in _LANGS:
        other = by_code.get(x.name.lower())
        if other is not None and other is not x:
            pairs.append((x, other))
    return pairs


_COLLISIONS = _collisions()


def _territories_by_language() -> dict[str, set[str]]:
    """CLDR's `territory_languages` inverted: language code -> territories that list it."""
    out: dict[str, set[str]] = {}
    for territory, langs in get_global("territory_languages").items():
        for key in langs:
            out.setdefault(key.split("_")[0], set()).add(territory)
    return out


_TERRITORIES = _territories_by_language()
_ALL_COUNTRIES = sorted(c.alpha_2 for c in pycountry.countries)


def _fmt(bad: list[str], limit: int = 12) -> str:
    return f"{len(bad)} wrong; first: " + "; ".join(bad[:limit])


# ---------------------------------------------------------------------------------------------
# 1. The report's table
# ---------------------------------------------------------------------------------------------


class TestReportTable:
    def test_derivation_matches_the_report_counts(self) -> None:
        """Sanity of the test's own pycountry derivation (report cause 2 and 3)."""
        two = [(n, c) for n, c in _COLLISIONS if len(n.name) == 2]
        assert len(two) == 13
        assert {n.name for n, _ in two} == {
            *("Ga", "En", "Ko", "Ha", "Hu", "Sa", "Wa", "Na", "To", "As", "Ak", "Ho", "Ik"),
        }
        assert sum("-" in x.name for x in _LANGS) == 384

    def test_thai_script_ga_is_gaa(self) -> None:
        """Row 1, the control: the Thai-script name of Ga is unambiguous and stays `gaa`."""
        r = _NORMALIZER.normalize("กา", _ctx())
        assert r.normalization_status is S.NORMALIZED
        assert r.comparison == "gaa"

    def test_ga_alone_is_ambiguous_not_irish(self) -> None:
        """Row 2: `Ga` is the ISO 639-1 code of Irish and the name of `gaa`. Old: `ga`."""
        r = _NORMALIZER.normalize("Ga", _ctx())
        assert r.normalization_status is S.AMBIGUOUS
        assert r.comparison not in {"ga", "gaa"}
        assert r.display != "Irish"
        assert r.structured.get("canonical_code") not in {"ga", "gaa"}

    def test_kuku_yalanji_is_its_own_language_not_kuku(self) -> None:
        """Row 3. The pycountry name `Kuku-Yalanji` belongs to `gvn`; `ukv` is the language
        named `Kuku`, the old confident-wrong cut at the hyphen. (The report's table lists
        `ukv` as the wrong answer; the fixed answer is the whole name's own code.)"""
        r = _NORMALIZER.normalize("Kuku-Yalanji", _ctx())
        assert r.normalization_status is S.NORMALIZED
        assert r.comparison == _code(_by_name("Kuku-Yalanji")) == "gvn"
        assert r.comparison != _code(_by_name("Kuku"))
        assert r.display == "Kuku-Yalanji"

    def test_judeo_arabic_is_resolved_not_invalid(self) -> None:
        """Row 4. Old: INVALID."""
        r = _NORMALIZER.normalize("Judeo-Arabic", _ctx())
        assert r.normalization_status is S.NORMALIZED
        assert r.comparison == _code(_by_name("Judeo-Arabic"))
        assert r.display == "Judeo-Arabic"

    def test_mon_without_evidence_is_ambiguous_not_mongolian(self) -> None:
        """Row 5. `Mon` is the ISO 639-2 code of Mongolian and the name of `mnw`."""
        r = _NORMALIZER.normalize("Mon", _ctx())
        assert r.normalization_status is S.AMBIGUOUS
        assert r.comparison not in {"mn", "mnw"}
        assert r.display != "Mongolian"
        assert r.structured.get("canonical_code") not in {"mn", "mnw"}

    @pytest.mark.parametrize("country", ["MM", "TH"])
    def test_mon_in_a_myanmar_or_thailand_row_is_mnw(self, country: str) -> None:
        """Report fix 2: 'Mon in a Myanmar or Thailand row is mnw' (CLDR lists mnw there)."""
        r = _NORMALIZER.normalize("Mon", _ctx(country))
        assert r.normalization_status not in _REFUSED
        assert r.comparison == _code(_by_name("Mon")) == "mnw"

    def test_dan_without_evidence_is_ambiguous_not_danish(self) -> None:
        """Row 6. `Dan` is the ISO 639-2 code of Danish and the name of `dnj`."""
        r = _NORMALIZER.normalize("Dan", _ctx())
        assert r.normalization_status is S.AMBIGUOUS
        assert r.comparison not in {"da", "dnj"}
        assert r.display != "Danish"

    def test_row_evidence_for_the_two_letter_example(self) -> None:
        """`Ga`: Ireland's CLDR languages list `ga`, Ghana's list `gaa`."""
        assert "IE" in _TERRITORIES["ga"]
        assert "GH" in _TERRITORIES["gaa"]
        assert _NORMALIZER.normalize("Ga", _ctx("IE")).comparison == "ga"
        assert _NORMALIZER.normalize("Ga", _ctx("GH")).comparison == "gaa"


# ---------------------------------------------------------------------------------------------
# 2. Every value that is both a code and a name (computed from pycountry)
# ---------------------------------------------------------------------------------------------


class TestEveryCollision:
    def test_each_collision_is_ambiguous_without_evidence(self) -> None:
        bad = []
        for name_lang, code_lang in _COLLISIONS:
            r = _NORMALIZER.normalize(name_lang.name, _ctx())
            guessed = {_code(name_lang), _code(code_lang)}
            if (
                r.normalization_status is not S.AMBIGUOUS
                or r.comparison in guessed
                or r.structured.get("canonical_code") in guessed
                or r.display == code_lang.name
            ):
                bad.append(f"{name_lang.name!r}: {r.normalization_status.value} {r.comparison}")
        assert len(_COLLISIONS) >= 134
        assert not bad, _fmt(bad)

    def test_cldr_row_country_settles_each_collision_it_can(self) -> None:
        """Evidence: a territory whose CLDR languages list exactly one of the two readings
        selects that reading; one that lists both or neither leaves the value AMBIGUOUS."""
        bad = []
        settled_name = settled_code = neither = 0
        for name_lang, code_lang in _COLLISIONS:
            t_name = _TERRITORIES.get(_code(name_lang), set())
            t_code = _TERRITORIES.get(_code(code_lang), set())
            cases = [(t, _code(name_lang)) for t in sorted(t_name - t_code)]
            cases += [(t, _code(code_lang)) for t in sorted(t_code - t_name)]
            cases += [(t, None) for t in sorted(t_name & t_code)]
            quiet = [c for c in _ALL_COUNTRIES if c not in t_name | t_code][:2]
            cases += [(t, None) for t in quiet]
            for territory, expected in cases:
                r = _NORMALIZER.normalize(name_lang.name, _ctx(territory))
                if expected is None:
                    neither += 1
                    ok = r.normalization_status is S.AMBIGUOUS
                else:
                    settled_name += expected == _code(name_lang)
                    settled_code += expected == _code(code_lang)
                    ok = r.normalization_status not in _REFUSED and r.comparison == expected
                if not ok:
                    bad.append(
                        f"{name_lang.name!r}@{territory}: want {expected}, got "
                        f"{r.normalization_status.value} {r.comparison}"
                    )
        assert settled_name > 0 and settled_code > 0 and neither > 0  # the test has teeth
        assert not bad, _fmt(bad)

    def test_a_country_that_lists_neither_reading_does_not_settle_it(self) -> None:
        """Never guess. Denmark lists neither `mn` nor `mnw`; an unknown or empty country is
        no evidence at all."""
        assert "DK" not in _TERRITORIES["mn"] | _TERRITORIES["mnw"]
        for country in ("DK", "ZZ", "", "00"):
            r = _NORMALIZER.normalize("Mon", _ctx(country))
            assert r.normalization_status is S.AMBIGUOUS, country
            assert r.comparison not in {"mn", "mnw"}, country

    def test_whitespace_does_not_add_certainty(self) -> None:
        r = _NORMALIZER.normalize(" Ga ", _ctx())
        assert r.normalization_status is S.AMBIGUOUS
        assert r.comparison not in {"ga", "gaa"}

    def test_evidence_never_overrides_a_value_that_is_not_a_collision(self) -> None:
        """A row country is evidence only where a value is ambiguous. `Irish` in a Ghana row is
        still `ga`; `Mongolian` in a Myanmar row is still `mn`."""
        assert _NORMALIZER.normalize("Irish", _ctx("GH")).comparison == "ga"
        assert _NORMALIZER.normalize("Mongolian", _ctx("MM")).comparison == "mn"
        collision_names = {n.name for n, _ in _COLLISIONS}
        sample = [x for x in _LANGS if x.name not in collision_names and "-" not in x.name][::25]
        assert len(sample) > 200
        bad = []
        for x in sample:
            plain = _NORMALIZER.normalize(x.name, _ctx())
            for country in ("MM", "IE"):
                r = _NORMALIZER.normalize(x.name, _ctx(country))
                if (r.comparison, r.normalization_status) != (
                    plain.comparison,
                    plain.normalization_status,
                ):
                    bad.append(f"{x.name!r}@{country}")
        assert not bad, _fmt(bad)


# ---------------------------------------------------------------------------------------------
# 3. The code is a fixed point
# ---------------------------------------------------------------------------------------------


class TestCodeIsAFixedPoint:
    @pytest.mark.parametrize("country", [None, "US"])
    def test_every_pycountry_code_normalizes_to_itself(self, country: str | None) -> None:
        """The report's probe: feeding `comparison` back changes 0 of the 7,910 languages. A
        guard, not a failing test today. It catches an over-eager ambiguity rule: `ga`, `en`,
        `ko`, `mon`-like codes that equal another language's name must stay codes."""
        ctx = _ctx(country)
        bad = []
        for x in _LANGS:
            code = _code(x)
            r = _NORMALIZER.normalize(code, ctx)
            if r.normalization_status in _REFUSED or r.comparison != code:
                bad.append(f"{code!r}: {r.normalization_status.value} {r.comparison}")
        assert len(_LANGS) == 7910
        assert not bad, _fmt(bad)

    def test_the_second_pass_of_every_table_row_keeps_the_code(self) -> None:
        for value, country in [
            ("กา", None),
            ("Kuku-Yalanji", None),
            ("Judeo-Arabic", None),
            ("Mon", "MM"),
            ("Ga", "GH"),
            ("Ga", "IE"),
        ]:
            first = _NORMALIZER.normalize(value, _ctx(country))
            assert first.comparison is not None
            second = _NORMALIZER.normalize(first.comparison, _ctx())
            assert second.comparison == first.comparison, (value, country)

    def test_the_upper_case_code_still_means_the_language(self) -> None:
        """Existing behaviour (`tests/unit/test_locale_normalizers.py`): `EN`, `en`, `eng`
        are English. The ambiguity rule is for the exact pycountry name spelling only."""
        for value in ("EN", "en", "eng"):
            assert _NORMALIZER.normalize(value, _ctx()).comparison == "en"


# ---------------------------------------------------------------------------------------------
# 4. The hyphen rule
# ---------------------------------------------------------------------------------------------

_TAG_REGIONS = ("US", "DE", "BR")
_TAG_SCRIPTS = ("Latn", "Cyrl", "Hant")
# Deprecated ISO 639-1 codes whose tags the IANA subtag registry maps to a Preferred-Value
# (`tl-US` is `fil-US`, `tw-US` is `ak-US`, `sh-US` is `sr-US`); the old code already follows
# the registry, so these three are not a "keeps working" case.
_TAG_PREFERRED_VALUE = {"sh", "tl", "tw"}


class TestHyphenRule:
    def test_valid_bcp47_tags_split_as_before(self) -> None:
        for tag, code, key, part in [
            ("en-GB", "en", "tag_territory", "GB"),
            ("pt-BR", "pt", "tag_territory", "BR"),
            ("zh-Hant", "zh", "tag_script", "Hant"),
            ("en_GB", "en", "tag_territory", "GB"),
        ]:
            r = _NORMALIZER.normalize(tag, _ctx())
            assert r.normalization_status is S.NORMALIZED, tag
            assert r.comparison == code, tag
            assert r.structured.get(key) == part, tag

    def test_a_tag_of_every_two_letter_language_keeps_working(self) -> None:
        """Generated from pycountry: `xx-US`, `xx-Latn`... with a lowercase language subtag
        (BCP 47 case rules); region and script come from pycountry too."""
        regions = {c.alpha_2 for c in pycountry.countries}
        scripts = {s.alpha_4 for s in pycountry.scripts}
        assert set(_TAG_REGIONS) <= regions and set(_TAG_SCRIPTS) <= scripts
        bad = []
        for x in _LANGS:
            if not hasattr(x, "alpha_2") or x.alpha_2 in _TAG_PREFERRED_VALUE:
                continue
            for sub in (*_TAG_REGIONS, *_TAG_SCRIPTS):
                r = _NORMALIZER.normalize(f"{x.alpha_2}-{sub}", _ctx())
                if r.normalization_status in _REFUSED or r.comparison != x.alpha_2:
                    bad.append(f"{x.alpha_2}-{sub}: {r.normalization_status.value} {r.comparison}")
        assert not bad, _fmt(bad)

    def test_every_hyphenated_name_resolves_to_its_own_code_or_is_ambiguous(self) -> None:
        """Report fix 3 and cause 2: all 384 pycountry names with `-`. Never INVALID, never
        another language. 46 of them start with another language's ISO 639 code (`Aka-Bea`
        is not Akan); three are also well-formed tags (`Aka-Cari`, `Aka-Bo`, `Uru-Pa-In`),
        where R12 allows only the whole name's own code or AMBIGUOUS, never the tag's."""
        names = [x for x in _LANGS if "-" in x.name]
        assert len(names) == 384
        bad = []
        for x in names:
            r = _NORMALIZER.normalize(x.name, _ctx())
            if r.normalization_status is S.AMBIGUOUS:
                continue
            if r.normalization_status in _REFUSED or r.comparison != _code(x):
                bad.append(f"{x.name!r}: {r.normalization_status.value} {r.comparison}")
        assert not bad, _fmt(bad)

    def test_a_name_that_starts_with_another_languages_code_is_not_cut(self) -> None:
        by_code = {}
        for x in _LANGS:
            by_code[x.alpha_3] = x
            if hasattr(x, "alpha_2"):
                by_code[x.alpha_2] = x
        hits = [
            x
            for x in _LANGS
            if "-" in x.name and by_code.get(x.name.split("-")[0].lower()) not in (None, x)
        ]
        assert len(hits) == 46
        for x in hits:
            first = by_code[x.name.split("-")[0].lower()]
            r = _NORMALIZER.normalize(x.name, _ctx())
            assert r.comparison != _code(first), x.name

    def test_no_pycountry_name_comes_back_as_another_language_or_invalid(self) -> None:
        """The report's other probe: feeding the English name back changed 440 of 7,910 (208
        another language, 232 INVALID). A name is a name lookup: its own code or AMBIGUOUS.
        (Brief-derived: the report states the 440 as the defect, not the exact after-state.)"""
        bad = []
        for x in _LANGS:
            r = _NORMALIZER.normalize(x.name, _ctx())
            if r.normalization_status is S.AMBIGUOUS:
                continue
            if r.normalization_status in _REFUSED or r.comparison != _code(x):
                bad.append(f"{x.name!r}: {r.normalization_status.value} {r.comparison}")
        assert not bad, _fmt(bad)


# ---------------------------------------------------------------------------------------------
# 5. Plan 2.4 on the production file: no tuned table
# ---------------------------------------------------------------------------------------------


def _hand_typed_lists(source: str) -> list[str]:
    """String literals in collections that are ISO 639 codes or pycountry language names,
    five or more in one collection (a hand-typed copy of pycountry or CLDR data), plus any
    literal naming one of the report's examples."""
    known = {x.name for x in _LANGS} | {x.alpha_3 for x in _LANGS}
    known |= {x.alpha_2 for x in _LANGS if hasattr(x, "alpha_2")}
    examples = {"Kuku-Yalanji", "Judeo-Arabic", "gvn", "jrb", "ukv", "mnw", "dnj", "gaa"}
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Set | ast.List | ast.Tuple | ast.Dict):
            elts = node.keys if isinstance(node, ast.Dict) else node.elts
            strings = [
                e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
            if sum(s in known for s in strings) >= 5:
                hits.append(f"line {node.lineno}: collection of {len(strings)} language strings")
        if isinstance(node, ast.Constant) and node.value in examples:
            hits.append(f"line {node.lineno}: report example {node.value!r}")
    return hits


class TestNoTunedTable:
    def test_scanner_catches_a_planted_table(self) -> None:
        planted = "X = {'en', 'de', 'fr', 'ga', 'gaa', 'mnw'}\nY = ['Kuku-Yalanji']\n"
        hits = _hand_typed_lists(planted)
        assert any("collection" in h for h in hits)
        assert any("'Kuku-Yalanji'" in h for h in hits)
        assert any("'mnw'" in h for h in hits)
        assert _hand_typed_lists("X = frozenset(range(3))\n") == []

    def test_language_module_has_no_hand_typed_language_list_or_fixture_literal(self) -> None:
        assert _hand_typed_lists(_LANGUAGE_PY.read_text(encoding="utf-8")) == []

    def test_language_module_has_no_hand_typed_territory_table(self) -> None:
        """CLDR is the source for 'which languages a territory lists' (via Babel or the
        generated CLDR modules), never a dict keyed by country code written in language.py."""
        tree = ast.parse(_LANGUAGE_PY.read_text(encoding="utf-8"))
        alpha2 = re.compile(r"^[A-Z]{2}$")
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
                assert sum(bool(alpha2.match(k)) for k in keys if isinstance(k, str)) < 5, (
                    f"line {node.lineno}"
                )
