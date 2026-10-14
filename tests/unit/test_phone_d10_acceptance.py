"""D10 acceptance (derived from improvement-report D10 + plan section 9, not the implementation).

Report: E.164 has no place for an extension, so two numbers differing only by extension used to
compare equal. Fix: RFC 3966 is the canonical form, `structured["rfc3966"]` is added, and
`comparison` is the RFC 3966 form ONLY when an extension is present; every other output is
unchanged. `search` stays extension-free. Truth values come from libphonenumber at run time
(`phonenumbers.format_number`), never from literals copied into the test.

Baseline: `tests/defects/phone_d10_baseline.json` is a snapshot of the pre-D10 outputs
(see `tests/defects/measure_phone_d10_before.py`); never regenerate it after the fix.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import phonenumbers
import pyarrow as pa
import pytest
from normalizers.phone import PhoneNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from phonenumbers import PhoneNumberFormat as Fmt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))  # tests/ is not a package; the planted fixtures live there

from defects import fixtures_phase23 as fx  # noqa: E402

BASELINE = ROOT / "tests" / "defects" / "phone_d10_baseline.json"
PHONE_PY = "packages/normalizers/src/normalizers/phone.py"
N = PhoneNormalizer()
CASES = fx.build_phone_extension_cases()


def norm(value: str | None, **ctx: str | None) -> Any:
    c = NormalizationContext(
        field_name="phone",
        semantic_type=FieldSemanticType.PHONE,
        country=ctx.get("country"),
        default_region=ctx.get("default_region"),
    )
    return N.normalize(value, c)


def _oracle(case: fx.PhoneExtensionCase, ext: str = fx.EXTENSION) -> str:
    n = phonenumbers.parse(case.base_international, None)
    n.extension = ext
    return phonenumbers.format_number(n, Fmt.RFC3966)


def _spellings(case: fx.PhoneExtensionCase) -> dict[str, str]:
    # The four report spellings plus libphonenumber's own RFC 3966 `tel:` URI.
    return {**case.spellings, "tel:": case.rfc3966_libphonenumber}


@pytest.mark.unit
class TestOneNumberOneComparison:
    """x45 / ext. 45 / ;ext=45 / #45 / tel: spellings -> ONE comparison (fails today)."""

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.region)
    def test_all_spellings_share_one_comparison(self, case: fx.PhoneExtensionCase) -> None:
        got = {label: norm(text).comparison for label, text in _spellings(case).items()}
        assert len(set(got.values())) == 1, got

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.region)
    def test_comparison_is_libphonenumbers_rfc3966(self, case: fx.PhoneExtensionCase) -> None:
        # the oracle is computed by libphonenumber, so a hand-built string cannot satisfy it
        assert case.rfc3966_libphonenumber == _oracle(case)
        for label, text in _spellings(case).items():
            r = norm(text)
            assert r.normalization_status is NormalizationStatus.PARSED, (label, text)
            assert r.comparison == _oracle(case), (label, text)

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.region)
    def test_national_form_plus_context_region_agrees(self, case: fx.PhoneExtensionCase) -> None:
        r = norm(case.national_with_extension, country=case.region)
        assert r.comparison == _oracle(case)

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.region)
    def test_tel_uri_with_context_agrees(self, case: fx.PhoneExtensionCase) -> None:
        assert norm(case.rfc3966_libphonenumber, country=case.region).comparison == _oracle(case)

    def test_tel_global_number_needs_no_context(self) -> None:
        """A `tel:+...` URI carries its own country code: not ambiguous, no guess involved."""
        r = norm(CASES[0].rfc3966_libphonenumber)
        assert r.normalization_status is NormalizationStatus.PARSED


@pytest.mark.unit
class TestStructuredRfc3966:
    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.region)
    def test_rfc3966_key_present_and_correct(self, case: fx.PhoneExtensionCase) -> None:
        for label, text in _spellings(case).items():
            s = norm(text).structured
            assert s.get("rfc3966") == _oracle(case), (label, text, s.get("rfc3966"))
            assert s["extension"] == fx.EXTENSION
            assert s["e164"] == case.base_e164  # E.164 stays beside it, extension-free
            assert s["region"] is not None and s["country_code"]

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.region)
    def test_comparison_equals_rfc3966_when_extension_present(
        self, case: fx.PhoneExtensionCase
    ) -> None:
        r = norm(case.spellings["x"])
        assert r.comparison == r.structured["rfc3966"]
        assert r.comparison.startswith("tel:+")
        assert r.comparison.endswith(";ext=" + fx.EXTENSION)

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.region)
    def test_search_stays_extension_free_and_display_keeps_it(
        self, case: fx.PhoneExtensionCase
    ) -> None:
        for text in case.spellings.values():  # pre-D10 behaviour too: a regression guard
            r = norm(text)
            assert r.search == case.base_e164  # a search for the base line must find it
            n = phonenumbers.parse(case.base_international, None)
            n.extension = fx.EXTENSION
            assert r.display == phonenumbers.format_number(n, Fmt.INTERNATIONAL)


@pytest.mark.unit
class TestExtensionIsPartOfIdentity:
    """Two numbers differing only by extension must compare UNEQUAL (equal today: the defect)."""

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.region)
    def test_other_extension_unequal(self, case: fx.PhoneExtensionCase) -> None:
        a, b = norm(case.spellings["x"]), norm(case.other_extension)
        assert a.comparison != b.comparison
        assert b.comparison == _oracle(case, fx.OTHER_EXTENSION)

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.region)
    def test_base_line_unequal_to_its_extension(self, case: fx.PhoneExtensionCase) -> None:
        base, ext = norm(case.base_international), norm(case.spellings["x"])
        assert base.comparison == case.base_e164  # unchanged bytes when no extension
        assert base.comparison != ext.comparison

    def test_leading_zero_extension_is_not_conflated(self) -> None:
        """Precision preserved: ext 045 and 45 are different strings; neither is rewritten."""
        c = next(c for c in CASES if c.region == "GB")
        a, b = norm(c.base_international + " x045"), norm(c.base_international + " x45")
        assert a.comparison != b.comparison
        assert a.comparison.endswith(";ext=045")
        assert a.structured["extension"] == "045"


def _baseline() -> list[dict[str, Any]]:
    return json.loads(BASELINE.read_text())


@pytest.mark.unit
class TestNoExtensionOutputUnchanged:
    """Whole pre-D10 corpus (1014 inputs, none with an extension): nothing may move.

    The only permitted difference is the NEW `structured["rfc3966"]` key (absent, None, or the
    libphonenumber RFC 3966 string of the base number)."""

    def test_baseline_is_the_extension_free_corpus(self) -> None:
        rows = _baseline()
        assert len(rows) > 900
        assert all(not r["out"]["structured"].get("extension") for r in rows)

    def test_byte_identical_outputs(self) -> None:
        moved = []
        for row in _baseline():
            r = norm(row["value"], country=row["country"], default_region=row["default_region"])
            got = {
                "status": r.normalization_status.value,
                "display": r.display,
                "comparison": r.comparison,
                "search": r.search,
                "structured": {k: v for k, v in r.structured.items() if k != "rfc3966"},
                "flags": sorted(str(f.value) for f in r.flags),
                "errors": [str(e) for e in r.errors],
            }
            # fix/robustness: letters read as keypad digits are no longer a
            # confident number; the original is kept as AMBIGUOUS instead.
            if phonenumbers.is_alpha_number(row["value"].strip()):
                assert got["status"] == "AMBIGUOUS", row["value"]
                assert got["display"] == row["value"]
                continue
            # fix/followups: so are fewer letters libphonenumber did not read
            # (`x45`, a dangling `... x`); only ever toward AMBIGUOUS, kept.
            if (
                got != row["out"]
                and any(ch.isalpha() for ch in row["value"])
                and got["status"] == "AMBIGUOUS"
                and got["display"] == row["value"]
            ):
                continue
            # fix/confident-wrong (PART1 N7): text libphonenumber says is no
            # number in any region moves AMBIGUOUS -> INVALID, original kept.
            if (
                got != row["out"]
                and row["out"]["status"] == "AMBIGUOUS"
                and got["status"] == "INVALID"
                and got["display"] == row["value"]
            ):
                continue
            if got != row["out"]:
                moved.append((row["value"], row["country"], row["default_region"]))
        assert moved == [], f"{len(moved)} extension-free outputs changed, e.g. {moved[:5]}"

    def test_rfc3966_key_when_no_extension_is_none_or_the_base_uri(self) -> None:
        for row in _baseline():
            s = norm(row["value"], country=row["country"], default_region=row["default_region"])
            v = s.structured.get("rfc3966")
            if v is None:
                continue
            assert ";ext=" not in v, row["value"]  # never an invented extension
            assert s.structured["e164"] is not None
            n = phonenumbers.parse(s.structured["e164"], None)
            assert v == phonenumbers.format_number(n, Fmt.RFC3966), row["value"]
            assert s.comparison == s.structured["e164"], row["value"]  # E.164 when no ext


@pytest.mark.unit
class TestIdempotency:
    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.region)
    def test_renormalizing_the_emitted_comparison_is_a_fixed_point(
        self, case: fx.PhoneExtensionCase
    ) -> None:
        for text in (case.base_international, case.spellings["x"]):
            first = norm(text)
            second = norm(first.comparison)  # no context at all
            assert second.normalization_status is NormalizationStatus.PARSED
            assert second.comparison == first.comparison
            assert second.search == first.search
            assert second.structured["extension"] == first.structured["extension"]

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.region)
    def test_a_foreign_context_cannot_change_a_self_describing_comparison(
        self, case: fx.PhoneExtensionCase
    ) -> None:
        first = norm(case.spellings["x"])
        other = "GB" if case.region != "GB" else "US"
        assert norm(first.comparison, country=other).comparison == first.comparison


@pytest.mark.unit
class TestNeverGuess:
    def test_no_region_with_extension_stays_ambiguous(self) -> None:
        r = norm(fx.PHONE_NO_REGION_WITH_EXTENSION)
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS
        assert r.comparison is None
        assert r.structured.get("rfc3966") is None

    def test_national_tel_uri_without_region_stays_ambiguous(self) -> None:
        r = norm("tel:415-555-2671;ext=45")
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS
        assert r.comparison is None
        assert r.structured.get("rfc3966") is None

    def test_bare_extension_is_not_a_number(self) -> None:
        for text in ("x45", "ext. 45", ";ext=45", "#45"):
            r = norm(text)
            assert r.normalization_status is not NormalizationStatus.PARSED, text
            assert r.comparison is None, text

    def test_invalid_number_with_extension_stays_invalid(self) -> None:
        r = norm(fx.PHONE_INVALID_WITH_EXTENSION)
        assert r.normalization_status is NormalizationStatus.INVALID
        assert r.structured.get("is_valid") is not True

    def test_invalid_number_with_extension_via_context_stays_invalid(self) -> None:
        r = norm("123 x45", country="US")
        assert r.normalization_status is not NormalizationStatus.PARSED or (
            r.structured["is_valid"] is False
        )

    def test_precision_no_extension_is_invented(self) -> None:
        """Precision is preserved: no extension marker -> no `;ext=`, and a bare marker with no
        digits yields no empty `;ext=` either."""
        c = CASES[0]
        for text in (
            c.base_international,
            c.base_international + " x",
            c.base_international + " ext.",
        ):
            r = norm(text)
            for view in (r.comparison, r.structured.get("rfc3966")):
                assert view is None or not re.search(r";ext=\D*$", view), (text, view)
            assert r.structured.get("extension") in (None, ""), text
        # trailing digits without a marker are part of the number, never silently an extension
        r = norm(c.base_international + " 45")
        assert r.structured["extension"] in (None, "")
        assert ";ext=" not in (r.comparison or "")

    def test_two_extension_markers_are_not_silently_merged(self) -> None:
        c = CASES[0]
        r = norm(c.base_international + " x45 x46")
        assert r.normalization_status is not NormalizationStatus.PARSED or (
            r.comparison != _oracle(c)
        )


@pytest.mark.unit
class TestBatchPath:
    def test_batch_comparison_matches_scalar_for_extension_values(self) -> None:
        values = [c.spellings["ext."] for c in CASES] + [c.base_international for c in CASES]
        ctx = NormalizationContext(field_name="phone", semantic_type=FieldSemanticType.PHONE)
        batch = N.normalize_batch(pa.array(values, type=pa.large_string()), ctx)
        assert batch.field("comparison").to_pylist() == [norm(v).comparison for v in values]
        assert batch.field("comparison").to_pylist()[0] == _oracle(CASES[0])


# --- section 2.4: grep over the lines D10 adds to phone.py ---------------------------------
_BAD = {
    "country-code/region literal table": re.compile(r"""(["'][A-Z]{2}["']\s*,\s*){2,}"""),
    "dialing-code number table": re.compile(r"\{\s*\d{1,3}\s*[:,]\s*[\d\"']"),
    "extension-prefix literal": re.compile(
        r"""["'](ext|extn|ext\.|x|доб\.?|;ext=|;ext)["']|\(\?:?[^)]*\bext\b[^)]*\|"""
    ),
    "phone-like fixture literal": re.compile(r"""\d{7,}|["']\+\d"""),
}


def _violations(added: list[str]) -> list[tuple[str, str]]:
    out = []
    for line in added:
        code = line.lstrip("+").strip()
        if code.startswith("#") or "ponytail:" in code:
            continue
        out += [(name, code) for name, rx in _BAD.items() if rx.search(code)]
    return out


@pytest.mark.unit
class TestSection24Grep:
    def test_the_grep_catches_what_it_is_meant_to_catch(self) -> None:
        planted = [
            '+PREFIXES = ("ext", "x", "extn")',
            '+_CC = {"US", "GB", "DE"}',
            '+EXT_RE = re.compile(r"(?:ext|x|#)\\s*(\\d+)")',
            '+if value == "+14155552671":',
            "+CODES = {1: 2, 44: 3}",
        ]
        assert len(_violations(planted)) >= len(planted)

    def test_added_lines_of_phone_py_are_clean(self) -> None:
        try:
            diff = subprocess.run(
                ["git", "diff", "main", "--unified=0", "--", PHONE_PY],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            pytest.skip("git or branch main unavailable")
        added = [ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
        assert _violations(added) == [], "authoritative data (libphonenumber) must produce these"

    def test_no_baseline_or_fixture_value_leaks_into_packages(self) -> None:
        src = (ROOT / PHONE_PY).read_text()
        for case in CASES:
            for needle in (case.base_e164, case.base_international, case.base_national):
                assert needle not in src
