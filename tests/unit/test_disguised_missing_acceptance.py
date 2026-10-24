"""D4 acceptance (derived from improvement-report D4 + plan 2.4 and 9 "D4", not the implementation).

Report: `type_detection` classifies columns, never cells, so a column that is 97% dates and 3%
`N/A` / `unknown` / `-` is one type for the whole column and the disguised nulls are silently
mis-normalized. Fix: a detector that reports WHICH distinct values are non-conforming, with
counts and a `MissingKind` hint, and never rewrites data. Plan: native fallback
`normanalysis.disguised_missing.detect_disguised_missing(value_counts, semantic_type, context)`;
"report the distinct values that fail that type's validator, recur as a small set, and match no
valid parse". Numeric magic numbers (`-999`) are only reachable through ptype; the native path
states that ceiling in a `ponytail:` comment.

Planted ground truth: `tests/defects/fixtures_phase23.py::build_d4_columns` (exact by construction).
Column-type identity: `tests/defects/d4_detection_snapshot.json` is a snapshot of TODAY's
`suggest_semantic_type` output (see `capture_d4_detection_snapshot.py`); never regenerate it.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import importlib
import inspect
import json
import random
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from normanalysis.type_detection import suggest_semantic_type
from normapi.app import build_normalizer_registry
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType as F
from normcore.enums import MissingKind

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))  # tests/ is not a package; the planted fixtures live there

# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
from defects import fixtures_phase23 as fx  # noqa: E402

PKG = "packages/normanalysis"
MODULE_PY = ROOT / PKG / "src" / "normanalysis" / "disguised_missing.py"
TYPE_DETECTION_PY = ROOT / PKG / "src" / "normanalysis" / "type_detection.py"
SNAPSHOT = ROOT / "tests" / "defects" / "d4_detection_snapshot.json"
COLUMNS = {c.name: c for c in fx.build_d4_columns()}


def dm() -> Any:
    """Import lazily so every test fails on its own (not one collection error) before D4 exists."""
    return importlib.import_module("normanalysis.disguised_missing")


# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
def detect(counts: Mapping[str, int], sem: Any, context: Any = None) -> list[Any]:
    return dm().detect_disguised_missing(counts, sem, context)  # type: ignore[no-any-return]


def reported(counts: Mapping[str, int], sem: Any) -> dict[str, int]:
    out = detect(counts, sem)
    d = {r.value: r.count for r in out}
    assert len(d) == len(out), "one entry per distinct value"
    return d


def counts_of(name: str) -> dict[str, int]:
    return dict(Counter(COLUMNS[name].values))


# --- the module and its shape ------------------------------------------------------------


@pytest.mark.unit
class TestModuleShape:
    def test_module_and_api_exist(self) -> None:
        assert MODULE_PY.is_file()
        m = dm()
        assert callable(m.detect_disguised_missing)
        assert dataclasses.is_dataclass(m.DisguisedMissing)

    def test_result_is_a_frozen_dataclass_of_value_count_hint(self) -> None:
        cls = dm().DisguisedMissing
        assert cls.__dataclass_params__.frozen
        assert {f.name for f in dataclasses.fields(cls)} == {"value", "count", "hint"}
        out = detect(counts_of("dates_3pct_sentinels"), F.DATE)
        assert out, "the planted column must report something"
        for r in out:
            assert isinstance(r, cls)
            assert isinstance(r.value, str)
            assert isinstance(r.count, int) and not isinstance(r.count, bool)
            assert r.hint is None or isinstance(r.hint, MissingKind)
        # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
        with pytest.raises(dataclasses.FrozenInstanceError):
            out[0].count = 0  # type: ignore[misc]


# --- the planted column ------------------------------------------------------------------


@pytest.mark.unit
class TestPlantedColumn:
    def test_97pct_dates_reports_exactly_the_three_sentinels_with_exact_counts(self) -> None:
        col = COLUMNS["dates_3pct_sentinels"]
        assert reported(counts_of(col.name), F.DATE) == col.expected_reported == fx.SENTINEL_COUNTS

    def test_semantic_type_may_be_the_enum_or_its_name(self) -> None:
        c = counts_of("dates_3pct_sentinels")
        assert detect(c, F.DATE) == detect(c, "DATE") == detect(c, F.DATE.value)

    def test_a_context_does_not_change_the_answer(self) -> None:
        c = counts_of("dates_3pct_sentinels")
        ctx = NormalizationContext(field_name="dob", semantic_type=F.DATE)
        assert detect(c, F.DATE, ctx) == detect(c, F.DATE)

    def test_sentinels_are_reported_verbatim_and_never_merged(self) -> None:
        # `N/A` and `n/a` are two distinct values; summing them would invent an equivalence.
        c = {f"2020-01-{d:02d}": 1000 for d in range(1, 29)} | {"N/A": 100, "n/a": 50, " N/A ": 7}
        assert reported(c, F.DATE) == {"N/A": 100, "n/a": 50, " N/A ": 7}

    def test_counts_are_per_distinct_value_not_rows(self) -> None:
        # >1B rows: input is value -> count, never a row list. Counts far past any row-list size.
        c = {f"2020-01-{d:02d}": 10**8 for d in range(1, 29)} | {"unknown": 3 * 10**7, "-": 11}
        assert reported(c, F.DATE) == {"unknown": 3 * 10**7, "-": 11}

    def test_counts_scale_with_input_not_with_a_constant(self) -> None:
        # A constant that the corpus count would not produce: same shape, other counts.
        a = {f"2020-01-{d:02d}": 1000 for d in range(1, 29)} | {"N/A": 1234, "unknown": 77, "-": 5}
        assert reported(a, F.DATE) == {"N/A": 1234, "unknown": 77, "-": 5}


# --- never report what is valid ----------------------------------------------------------


@pytest.mark.unit
class TestNothingToReport:
    def test_na_in_a_country_column_is_namibia_not_missing(self) -> None:
        col = COLUMNS["country_with_namibia"]
        assert col.values.count("NA") == fx.COUNTRY_NA_COUNT
        assert reported(counts_of(col.name), F.COUNTRY) == {}
        assert reported(counts_of(col.name), "COUNTRY") == {}

    def test_country_column_still_reports_the_values_that_are_not_countries(self) -> None:
        # Type-dependence: NA stays out while real sentinels of the same column come in.
        c = counts_of("country_with_namibia") | {"unknown": 30, "-": 20}
        assert reported(c, F.COUNTRY) == {"unknown": 30, "-": 20}

    def test_no_sentinels_reports_nothing(self) -> None:
        assert detect(counts_of("dates_no_sentinels"), F.DATE) == []

    def test_empty_input_reports_nothing(self) -> None:
        assert detect({}, F.DATE) == []
        assert detect(Counter(), F.COUNTRY) == []

    def test_a_value_with_count_zero_is_not_present_so_not_reported(self) -> None:
        assert detect({"2020-01-01": 5, "N/A": 0}, F.DATE) == []

    def test_valid_but_rare_values_are_never_reported(self) -> None:
        c = counts_of("dates_no_sentinels") | {"1999-12-31": 2, "2020": 3, "2020-05": 2}
        assert detect(c, F.DATE) == []  # a legit date, a year-only and a year-month are all valid
        countries = counts_of("country_with_namibia") | {"NR": 3}  # Nauru: real and rare
        assert reported(countries, F.COUNTRY) == {}

    def test_noise_that_does_not_recur_is_not_a_sentinel(self) -> None:
        # 30 distinct junk strings each once: not "a small recurring set", so reporting is guessing.
        assert detect(counts_of("dates_noise_not_sentinels"), F.DATE) == []

    def test_a_column_where_nothing_conforms_is_a_wrong_type_not_missing_data(self) -> None:
        # never guess: if EVERY value fails the validator the type is wrong; no cell is the odd one.
        c = {"alpha": 400, "bravo": 300, "charlie": 200, "delta": 100}
        assert detect(c, F.DATE) == []


# --- never guess -------------------------------------------------------------------------


@pytest.mark.unit
class TestUntypedAbstains:
    """Where no validator can say no there is no basis to call a cell non-conforming."""

    @pytest.mark.parametrize("sem", [F.FREE_TEXT, F.UNKNOWN, "FREE_TEXT", "UNKNOWN"])
    def test_free_text_and_unknown_report_nothing(self, sem: Any) -> None:
        c = {f"word{i}": 3 for i in range(60)} | {"N/A": 150, "unknown": 100, "-": 50}
        assert detect(c, sem) == []

    def test_unrecognised_type_name_abstains_or_raises_cleanly(self) -> None:
        try:
            out = detect({"N/A": 5, "2020-01-01": 100}, "NOT_A_SEMANTIC_TYPE")
        except (ValueError, KeyError):
            return
        assert out == []


# --- numeric magic numbers: ptype reaches them, the native path states its ceiling -------


@pytest.mark.unit
class TestNumericMagicNumber:
    def test_minus_999_is_reported_exactly_or_the_ceiling_is_stated(self) -> None:
        col = fx.MAGIC_NUMBER_COLUMN
        got = reported(dict(Counter(col.values)), F.NUMERIC)
        if got:
            assert got == {"-999": col.values.count("-999")}, "970 distinct valid numbers stay out"
            return
        text = MODULE_PY.read_text()
        blocks, cur = [], []
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                cur.append(line.lower())
            elif cur:
                blocks.append(" ".join(cur))
                cur = []
        blocks.append(" ".join(cur))
        assert any("ponytail:" in b and "magic" in b for b in blocks), (
            "native path reports nothing for -999, so a `ponytail:` comment must name the "
            "magic-number ceiling"
        )

    def test_numeric_column_without_magic_numbers_reports_nothing(self) -> None:
        assert detect({str(i): 1 for i in range(1, 971)}, F.NUMERIC) == []


# --- purity: never mutate, deterministic -------------------------------------------------


@pytest.mark.unit
class TestPurityAndDeterminism:
    def test_input_mapping_is_not_mutated(self) -> None:
        c = counts_of("dates_3pct_sentinels")
        before = copy.deepcopy(c)
        detect(c, F.DATE)
        assert c == before and list(c) == list(before)

    def test_works_on_a_read_only_mapping(self) -> None:
        c = counts_of("dates_3pct_sentinels")
        assert detect(MappingProxyType(c), F.DATE) == detect(c, F.DATE)

    def test_order_is_deterministic_and_independent_of_input_order(self) -> None:
        c = counts_of("dates_3pct_sentinels")
        base = detect(c, F.DATE)
        assert len(base) == 3
        assert detect(c, F.DATE) == base
        items = list(c.items())
        for seed in range(5):
            random.Random(seed).shuffle(items)
            assert detect(dict(items), F.DATE) == base
        assert detect(dict(reversed(list(c.items()))), F.DATE) == base

    def test_the_same_counts_in_equal_tied_sentinels_have_a_stable_order(self) -> None:
        c = {f"2020-01-{d:02d}": 1000 for d in range(1, 29)} | {"b?": 40, "a?": 40, "c?": 40}
        first = detect(c, F.DATE)
        assert [r.value for r in first] == [
            r.value for r in detect(dict(reversed(c.items())), F.DATE)
        ]


# --- column-type results identical to today ----------------------------------------------


@pytest.mark.unit
class TestColumnTypeResultsUnchanged:
    def test_type_detection_negative_controls_untouched(self) -> None:
        src = TYPE_DETECTION_PY.read_text()
        assert '_NEGATIVE_CONTROL = "zz~not~a~value~zz"' in src
        assert '_BARE_NUMBER_CONTROL = "12345"' in src
        assert "def _discriminates" in src

    def test_suggest_semantic_type_keeps_every_todays_parameter(self) -> None:
        params = inspect.signature(suggest_semantic_type).parameters
        for name in ("field_name", "sample_values", "registry", "country", "locale"):
            assert name in params
        for name, p in params.items():  # a hook may add parameters only if they are optional
            if name != "field_name":
                assert p.default is not inspect.Parameter.empty, name

    def test_name_only_results_equal_the_snapshot_of_the_old_code(self) -> None:
        snap = json.loads(SNAPSHOT.read_text())["cases"]
        names = [k for k in snap if k.startswith("name_only|")]
        assert len(names) >= 20
        for key in names:
            got = [
                [str(s.semantic_type), s.confidence, s.reason]
                for s in suggest_semantic_type(key.split("|", 1)[1])
            ]
            assert got == snap[key], key

    def test_planted_column_results_equal_the_snapshot_of_the_old_code(self) -> None:
        snap = json.loads(SNAPSHOT.read_text())["cases"]
        registry = build_normalizer_registry()
        cols = {c.name: c for c in [*fx.build_d4_columns(), fx.MAGIC_NUMBER_COLUMN]}
        # dob (name layer + value confirm) on every planted column, plus the values-only path.
        keys = [f"{n}|dob|first20" for n in cols] + [
            f"{n}|col_a|first20" for n in ("dates_3pct_sentinels", "country_with_namibia")
        ]
        for key in keys:
            name, field, _ = key.split("|")
            out = suggest_semantic_type(
                field, sample_values=cols[name].values[:20], registry=registry
            )
            assert [[str(s.semantic_type), s.confidence, s.reason] for s in out] == snap[key], key

    def test_snapshot_was_taken_on_the_old_code_and_covers_the_planted_columns(self) -> None:
        snap = json.loads(SNAPSHOT.read_text())["cases"]
        assert len(snap) == 40
        assert snap["dates_3pct_sentinels|dob|first20"][0][:2] == ["DATE", 0.97]
        assert snap["country_with_namibia|country|first20"][0][:2] == ["COUNTRY", 0.95]


# --- section 2.4: grep over what D4 adds to packages/normanalysis ------------------------

_VOCAB = {
    "n/a", "na", "nan", "null", "none", "nil", "unknown", "missing", "undefined", "tbd", "?", "-",
    "--", "#n/a", "not available", "not applicable", "999", "-999", "9999", "-9999", "n.a.",
}  # fmt: skip
_QUOTED = re.compile(r"""(["'])(.*?)\1""")
_BAD = {
    "hand sentinel literal": lambda s: any(
        m.group(2).strip().casefold() in _VOCAB for m in _QUOTED.finditer(s)
    ),
    "hand string table": lambda s: bool(re.search(r"""(["'][^"']{1,12}["']\s*,\s*){2,}""", s)),
    "iso/country code table": lambda s: bool(re.search(r"""(["'][A-Z]{2}["']\s*,\s*){2,}""", s)),
    "fractional or percent threshold": lambda s: bool(
        re.search(r"(?<![\w.])0?\.\d+(?![\w.])|\b\d+(\.\d+)?\s*%", s)
    ),
    "integer threshold in a comparison": lambda s: bool(
        re.search(r"(<=|>=|<|>)\s*(\d{2,}|[2-9])\b", s)
    ),
    "magic number literal": lambda s: bool(re.search(r"(?<![\w.])-?999+(?![\w.])", s)),
    "fixture count copied": lambda s: bool(re.search(r"\b(150|10_?000|9850|970)\b", s)),
}
_EXEMPT = re.compile(r"ponytail:|deriv", re.IGNORECASE)


def _violations(lines: list[str]) -> list[tuple[str, str]]:
    """Code lines that carry a hand list or a bare threshold. A comment line, or a code line in
    the block right after a comment/line carrying `ponytail:` or a derivation, is exempt."""
    out: list[tuple[str, str]] = []
    exempt_block = False
    for raw in lines:
        code = raw.strip()
        if not code:
            exempt_block = False
            continue
        if code.startswith("#"):
            exempt_block = exempt_block or bool(_EXEMPT.search(code))
            continue
        if _EXEMPT.search(code):
            continue
        if not exempt_block:
            out += [(name, code) for name, bad in _BAD.items() if bad(code)]
    return out


def _module_code_lines(path: Path) -> list[str]:
    """Source lines with docstring lines blanked (docstrings may quote `N/A` as prose)."""
    src = path.read_text()
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
                and first.end_lineno is not None
            ):
                for i in range(first.lineno - 1, first.end_lineno):
                    lines[i] = ""
    return lines


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git unavailable")


@pytest.mark.unit
class TestSection24Grep:
    def test_the_grep_catches_what_it_is_meant_to_catch(self) -> None:
        planted = [
            'SENTINELS = ["N/A", "unknown", "-"]',
            '_NULLS = {"na", "null"}',
            'if v.lower() in ("n/a", "none"):',
            "THRESHOLD = 0.05",
            "if count / total < .03:",
            "if share > 5%:",
            "if len(distinct) > 12:",
            "MAGIC = -999",
            '_CC = ("NA", "NR", "NG")',
            'ALLOWED = ("ab", "cd", "ef")',
            "assert total == 10_000",
        ]
        for line in planted:
            assert _violations([line]), line

    def test_the_grep_leaves_legitimate_code_alone(self) -> None:
        clean = [
            "if count <= 0:",
            "if count > 1:",
            "return sorted(found, key=lambda d: (-d.count, d.value))",
            "# ponytail: ceiling 5%, upgrade path is ptype",
            "THRESHOLD = 0.05  # ponytail: 5% is a ceiling, per-type share later",
            "x = 0.5  # derived from the sample size",
            "hint = MissingKind.UNKNOWN_VALUE",
            "def detect_disguised_missing(value_counts, semantic_type, context=None):",
        ]
        assert _violations(clean) == []
        # A ponytail comment covers the next block, and only that block.
        block = [
            "# ponytail: share ceiling, ptype is the upgrade path",
            "LIMIT = 0.05",
            "",
            "B = 0.07",
        ]
        assert _violations(block) == [("fractional or percent threshold", "B = 0.07")]

    def test_only_the_planned_files_changed_under_normanalysis(self) -> None:
        names = _git("diff", "HEAD", "--name-only", "--", PKG).split()
        # gold.py (D6) and calibration.py (D2) are phase 3's other lanes in this package (lead).
        allowed = {
            f"{PKG}/src/normanalysis/{n}"
            for n in ("disguised_missing.py", "type_detection.py", "gold.py", "calibration.py")
        } | {f"{PKG}/src/normanalysis/__init__.py", f"{PKG}/pyproject.toml"}
        assert set(names) <= allowed, sorted(set(names) - allowed)

    def test_the_new_module_has_no_hand_sentinel_list_or_bare_threshold(self) -> None:
        assert MODULE_PY.is_file()  # it is a new file: `git diff HEAD` cannot show it untracked
        v = _violations(_module_code_lines(MODULE_PY))
        assert v == [], "authoritative validators or a runtime count must produce these"

    def test_added_lines_in_existing_files_are_clean(self) -> None:
        diff = _git("diff", "HEAD", "--unified=0", "--", PKG)
        added = [ln[1:] for ln in diff.splitlines() if ln.startswith("+") and ln[:3] != "+++"]
        assert _violations(added) == []
        # the hook in type_detection adds, it does not remove the negative controls
        removed = [ln for ln in diff.splitlines() if ln.startswith("-") and ln[:3] != "---"]
        assert not any("_NEGATIVE_CONTROL" in ln or "_BARE_NUMBER_CONTROL" in ln for ln in removed)

    def test_no_fixture_value_is_copied_into_the_module(self) -> None:
        src = MODULE_PY.read_text()
        for needle in ("dates_3pct_sentinels", "country_with_namibia", "garbage-", "numbers_magic"):
            assert needle not in src
