"""D4 attack tests (adversarial verifier). Independent of the worker's own acceptance file.

Passing tests pin behaviour that survived the attack. `xfail(strict=True)` marks a confirmed
defect: it fails today and will XPASS (and so fail the suite) the day it is fixed.
Valid values come from authoritative data (phonenumbers examples, pycountry, datetime).
"""

from __future__ import annotations

import copy
import datetime as dt
import subprocess
import sys
import time
from collections import Counter

import phonenumbers
import pycountry
import pytest
from normanalysis.disguised_missing import DisguisedMissing, detect_disguised_missing
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType as F
from normcore.enums import MissingKind

pytestmark = pytest.mark.unit

SENTINELS = ["N/A", "n/a", "NULL", "none", "?", "--", "TBD", "#N/A", "nan", "unknown", "null", "-"]


def _ctx(t: F, **kw: str) -> NormalizationContext:
    return NormalizationContext(field_name="x", semantic_type=t, **kw)


def _phones() -> list[str]:
    fmt = phonenumbers.PhoneNumberFormat.INTERNATIONAL
    return [
        phonenumbers.format_number(phonenumbers.example_number(r), fmt)
        for r in sorted(phonenumbers.SUPPORTED_REGIONS)
        if phonenumbers.example_number(r)
    ]


def _dates() -> list[str]:
    d0 = dt.date(1990, 1, 1)
    return [(d0 + dt.timedelta(days=37 * i)).isoformat() for i in range(400)]


def _datetimes() -> list[str]:
    t0 = dt.datetime(2020, 1, 1)
    return [(t0 + dt.timedelta(minutes=533 * i)).isoformat() for i in range(400)]


VALID: dict[F, tuple[list[str], dict[str, str]]] = {
    F.EMAIL: ([f"user{i}@example{i % 40}.org" for i in range(400)], {}),
    F.PHONE: (_phones(), {}),
    F.COUNTRY: ([c.alpha_2 for c in pycountry.countries], {}),
    F.CURRENCY: ([c.alpha_3 for c in pycountry.currencies], {}),
    F.URL: ([f"https://www.site{i}.example.com/p/{i}" for i in range(400)], {}),
    F.DATE: (_dates(), {}),
    F.DATETIME: (_datetimes(), {}),
    F.POSTCODE: (["10115", "75008", "90210", "12345", "60601"], {"country": "US"}),
}


def _column(t: F, planted: dict[str, int]) -> tuple[Counter[str], NormalizationContext | None]:
    vals, ckw = VALID[t]
    c: Counter[str] = Counter({v: max(5, 2000 // len(vals)) for v in vals})
    c.update(planted)
    return c, (_ctx(t, **ckw) if ckw else None)


# --- recall: realistic disguised nulls in columns of authoritative valid values -------------


# PHONE and CURRENCY were strict xfails here (HANDOFF escalation j) until their
# validators said INVALID for text that names no number or currency (PART1 N7).
@pytest.mark.parametrize("t", sorted(VALID, key=str))
def test_recall_planted_sentinels(t: F) -> None:
    planted = dict.fromkeys(SENTINELS, 4)
    col, ctx = _column(t, planted)
    got = {r.value: r for r in detect_disguised_missing(col, t, ctx)}
    assert set(planted) <= set(got), set(planted) - set(got)
    assert all(got[s].count == 4 for s in planted)
    assert not set(got) - set(planted)  # no valid value reported


@pytest.mark.parametrize("t", [F.DATE, F.DATETIME])
def test_recall_zero_date_and_blank(t: F) -> None:
    planted = {"0000-00-00": 4, "": 3, "   ": 3}
    col, ctx = _column(t, planted)
    got = {r.value: r.count for r in detect_disguised_missing(col, t, ctx)}
    assert got == planted


@pytest.mark.parametrize("pct", [1, 2, 5])
def test_recall_at_one_to_five_percent(pct: int) -> None:
    n = 2000
    k = n * pct // 100
    col: Counter[str] = Counter(dict.fromkeys(_dates(), 1))
    col.update({"2020-01-01": n - k - len(col)})
    col.update({"N/A": k // 2, "unknown": k - k // 2})
    got = {r.value: r.count for r in detect_disguised_missing(col, F.DATE)}
    assert got == {"N/A": k // 2, "unknown": k - k // 2}


def test_hint_matches_dictionary_with_case_and_padding() -> None:
    col = Counter({"2020-01-01": 100, "N/A": 3, "n/a": 3, " none ": 3, "Unknown": 3, "?": 3})
    got = {r.value: r.hint for r in detect_disguised_missing(col, F.DATE)}
    assert got == {
        "N/A": MissingKind.NOT_APPLICABLE,
        "n/a": MissingKind.NOT_APPLICABLE,
        " none ": MissingKind.NULL,
        "Unknown": MissingKind.UNKNOWN_VALUE,
        "?": MissingKind.UNKNOWN_VALUE,
    }


# --- precision: legitimate but rare valid values are never reported -------------------------
def test_all_iso_countries_incl_namibia_not_reported() -> None:
    col = Counter({c.alpha_2: 2 for c in pycountry.countries})
    col["DE"] = 500
    assert detect_disguised_missing(col, F.COUNTRY) == []


def test_two_letter_sentinel_lookalike_codes_valid_in_country() -> None:
    # real ISO alpha-2 codes that look like sentinels: NA (Namibia), NO (Norway), IN, IS, ...
    col = Counter({"NA": 5, "NO": 5, "IN": 5, "IS": 5, "ID": 5, "TO": 5, "DE": 300, "N/A": 5})
    assert [r.value for r in detect_disguised_missing(col, F.COUNTRY)] == ["N/A"]


def test_example_phones_all_valid() -> None:
    col = Counter(dict.fromkeys(_phones(), 3))
    assert detect_disguised_missing(col, F.PHONE) == []


def test_partial_and_year_only_dates_not_reported() -> None:
    col = Counter(dict.fromkeys(_dates()[:20], 50))
    col.update({"2020": 3, "2020-05": 3, "1999": 3, "April 2020": 3, "2020-05-01": 3})
    assert detect_disguised_missing(col, F.DATE) == []


def test_numeric_zero_and_minus_one_are_valid_numbers() -> None:
    col = Counter({"0": 5, "-1": 5, "3.5": 500, "-999": 5})
    assert detect_disguised_missing(col, F.NUMERIC) == []  # documented ponytail ceiling


def test_one_off_junk_reports_nothing_even_in_huge_column() -> None:
    col = Counter(dict.fromkeys(_dates(), 1))
    col.update({f"junk-{i}": 1 for i in range(200)})
    col["2020-01-01"] = 10**9
    assert detect_disguised_missing(col, F.DATE) == []


# --- boundaries -----------------------------------------------------------------------------
@pytest.mark.parametrize(("bad", "expect"), [(49, True), (50, False), (51, False)])
def test_minority_boundary(bad: int, expect: bool) -> None:
    got = detect_disguised_missing({"2020-01-01": 100 - bad, "N/A": bad}, F.DATE)
    assert bool(got) is expect


def test_huge_counts_exact() -> None:
    got = detect_disguised_missing({"N/A": 10**15, "2020-01-01": 10**18}, F.DATE)
    assert got == [DisguisedMissing("N/A", 10**15, MissingKind.NOT_APPLICABLE)]


def test_non_str_keys_and_bad_counts_do_not_raise_or_report() -> None:
    col = {None: 5, 1: 5, b"x": 5, ("a",): 5, "N/A": 3, "2020-01-01": 50, "x": -3, "y": 0}
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    got = detect_disguised_missing(col, F.DATE)  # type: ignore[arg-type]
    assert [r.value for r in got] == ["N/A"]


def test_input_not_mutated_and_order_independent() -> None:
    col = {"N/A": 3, "unknown": 3, "2020-01-01": 50, "-": 2}
    before = copy.deepcopy(col)
    a = detect_disguised_missing(col, F.DATE)
    b = detect_disguised_missing(dict(reversed(col.items())), F.DATE)
    assert col == before
    assert a == b
    assert [r.value for r in a] == ["N/A", "unknown", "-"]


def test_garbage_context_does_not_raise() -> None:
    ctx = _ctx(F.PHONE, country="ZZ", locale="xx")
    got = detect_disguised_missing({"+14155552671": 50, "n/a": 3}, F.PHONE, ctx)
    assert [r.value for r in got] == ["n/a"]


def test_context_changes_validity_phone_region() -> None:
    nat = phonenumbers.format_number(
        phonenumbers.example_number("US"), phonenumbers.PhoneNumberFormat.NATIONAL
    )
    col = {"+44 20 7946 0958": 50, nat: 10, "n/a": 3}
    no_region = {r.value for r in detect_disguised_missing(col, F.PHONE)}
    with_us = {r.value for r in detect_disguised_missing(col, F.PHONE, _ctx(F.PHONE, country="US"))}
    # lead round 2: without a region a national number is AMBIGUOUS, not invalid: never reported
    assert nat not in no_region
    assert nat not in with_us  # ... and with one it conforms: validity is context-relative
    # `n/a` is no number in any region: reported with or without one (PART1 N7;
    # it used to be AMBIGUOUS without a region, escalation j).
    assert "n/a" in no_region
    assert "n/a" in with_us


def test_free_text_and_identifier_abstain() -> None:
    col = {"abc": 50, "N/A": 5, "": 3}
    for t in (F.FREE_TEXT, F.UNKNOWN, F.IDENTIFIER, F.PERSON_NAME, F.COMPANY_NAME):
        assert detect_disguised_missing(col, t) == []


def test_unknown_type_name_raises_value_error() -> None:
    with pytest.raises(ValueError, match="not a valid"):
        detect_disguised_missing({"a": 5}, "nonsense")


# --- confirmed defects ----------------------------------------------------------------------
def test_ambiguous_date_is_not_reported_as_missing() -> None:
    col = {"2020-01-01": 100, "03/04/2020": 4}
    assert detect_disguised_missing(col, F.DATE) == []


def test_many_distinct_recurring_invalid_values_not_all_reported() -> None:
    col = Counter(dict.fromkeys(_dates(), 5))
    col.update({f"junk value {i}": 2 for i in range(300)})
    assert len(detect_disguised_missing(col, F.DATE)) < 300  # reports all 300 today


# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
@pytest.mark.xfail(
    strict=True,
    reason="D4 attack: DateNormalizer.validate costs ~11-430 ms per FAILING value (dateparser), "
    "~150 ms for digit strings; the detector validates every distinct value, no short-circuit, "
    "so 100k distinct failing dates is hours. 40 digit strings must take < 1 s.",
)
def test_failing_dates_validate_fast() -> None:
    col = Counter({"2020-01-01": 10_000})
    col.update({str(1000 + i): 1 for i in range(40)})
    detect_disguised_missing({"2020-01-01": 1}, F.DATE)  # warm caches
    t0 = time.perf_counter()
    detect_disguised_missing(col, F.DATE)
    assert time.perf_counter() - t0 < 1.0


def test_lone_surrogate_key_does_not_crash_process() -> None:
    code = (
        "from normanalysis.disguised_missing import detect_disguised_missing as D\n"
        "from normcore.enums import FieldSemanticType as F\n"
        "D({'\\ud800': 3, '2020-01-01': 50}, F.DATE)\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=120, check=False)
    assert r.returncode == 0
