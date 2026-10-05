"""Planted ground truth for Phase 1 (D1 abstention, D7/D8 identifiers, D9 URL).

Module-level constants only, no test functions. Nothing here is copied from
`tests/` or from the output of the code under test: every expected value is
produced by an authoritative source at import time -

* phones: libphonenumber example numbers (`phonenumbers`), candidate sets from
  `is_valid_number` over every supported region;
* dates: calendar arithmetic over both day/month readings (`datetime.date`);
* amounts: CLDR number patterns via Babel (`format_decimal` / `parse_decimal`);
* tax ids: python-stdnum's own `calc_check_digit` and `is_valid`;
* URLs: Public Suffix List semantics (rules and ICANN/PRIVATE sections verified
  against publicsuffix.org/list on 2026-10-05; see D9 note below).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

import phonenumbers
import pycountry
from babel.numbers import format_decimal, parse_decimal
from stdnum import luhn
from stdnum.fr import siren as fr_siren

from .scorer import Case

# --------------------------------------------------------------------------- D1
# Ambiguous phones: a national-format number with no region and no "+" is
# undecidable when it is valid in several regions with DIFFERENT E.164 results.
# Candidate set = the distinct E.164 strings over all regions it is valid in.


def _phone_candidates(national: str) -> frozenset[str]:
    out: set[str] = set()
    for region in sorted(phonenumbers.SUPPORTED_REGIONS):
        try:
            parsed = phonenumbers.parse(national, region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(parsed):
            out.add(phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164))
    return frozenset(out)


def _example_numbers() -> list[tuple[str, str, str]]:
    """(region, national-format string, E.164) from libphonenumber's own examples."""
    rows = []
    for region in sorted(phonenumbers.SUPPORTED_REGIONS):
        for kind in (phonenumbers.PhoneNumberType.MOBILE, phonenumbers.PhoneNumberType.FIXED_LINE):
            num = phonenumbers.example_number_for_type(region, kind)
            if num is not None:
                rows.append(
                    (
                        region,
                        phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL),
                        phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164),
                    )
                )
    return rows


_EXAMPLES = _example_numbers()


def _ambiguous_phone_cases(limit: int = 8) -> tuple[Case, ...]:
    """A spread of libphonenumber examples that are valid in 2+ regions with different E.164s."""
    out: list[Case] = []
    for region, national, _ in _EXAMPLES[:: max(1, len(_EXAMPLES) // 60)]:
        candidates = _phone_candidates(national)
        if len(candidates) >= 2:
            out.append(
                Case(f"d1-phone-amb-{region}", "PHONE", national, "abstain", candidates=candidates)
            )
        if len(out) == limit:
            break
    return tuple(out)


D1_PHONE_AMBIGUOUS: tuple[Case, ...] = _ambiguous_phone_cases()

# Controls: the same libphonenumber example numbers, but the region is given
# (context country) or the number carries "+": must come out clean, so an
# engine that abstains on everything cannot pass.
_CONTROL_ROWS = _EXAMPLES[:: max(1, len(_EXAMPLES) // 6)][:6]
D1_PHONE_CLEAN: tuple[Case, ...] = tuple(
    Case(f"d1-phone-region-{r}-{n}", "PHONE", n, "clean", expected_value=e, context={"country": r})
    for r, n, e in _CONTROL_ROWS
) + tuple(
    Case(f"d1-phone-plus-{e}", "PHONE", e, "clean", expected_value=e)
    for _, _, e in _CONTROL_ROWS[:3]
)

# Dates: day and month both <= 12 and different -> two readings (DMY/MDY).
# Same day and month (05/05/2024) has ONE reading: a control that must be clean.
_AMBIGUOUS_DATE_PARTS = [(1, 2, 2024), (3, 4, 2023), (11, 12, 1999), (7, 8, 2010)]


def _iso(y: int, m: int, d: int) -> str:
    return date(y, m, d).isoformat()


D1_DATE_AMBIGUOUS: tuple[Case, ...] = tuple(
    Case(
        f"d1-date-amb-{a:02d}-{b:02d}-{y}",
        "DATE",
        f"{a:02d}/{b:02d}/{y}",
        "abstain",
        candidates=frozenset({_iso(y, b, a), _iso(y, a, b)}),
    )
    for a, b, y in _AMBIGUOUS_DATE_PARTS
)
# The context decides it: US month-first, DE day-first (country conventions, not guesses).
D1_DATE_CLEAN: tuple[Case, ...] = (
    Case("d1-date-us", "DATE", "01/02/2024", "clean", _iso(2024, 1, 2), context={"country": "US"}),
    Case("d1-date-de", "DATE", "01/02/2024", "clean", _iso(2024, 2, 1), context={"country": "DE"}),
    Case("d1-date-day>12", "DATE", "13/02/2024", "clean", _iso(2024, 2, 13)),
    Case("d1-date-iso", "DATE", "2024-02-13", "clean", _iso(2024, 2, 13)),
    # Both readings are the same date, so there is nothing to choose between.
    # NOT a report example: an engine that abstains here is over-abstaining.
    Case("d1-date-same-day-month", "DATE", "05/05/2024", "clean", _iso(2024, 5, 5)),
)


# Precision is preserved, never invented (CLAUDE.md): a source that states only a
# month or a year normalizes to that month or year. Kept OUT of D1_ALL: this is a
# never-guess control for any item that touches dates, not a report example.
D1_DATE_PRECISION: tuple[Case, ...] = (
    Case("prec-iso-month", "DATE", "2024-03", "clean", "2024-03"),
    Case("prec-iso-year", "DATE", "1990", "clean", "1990"),
    Case("prec-month-year", "DATE", "03/2024", "clean", "2024-03"),  # 2024 cannot be a day
)


# Amounts: "1,234" is 1234 under en and 1.234 under de (CLDR); it stays ambiguous
# without a locale. The candidate set is parsed from CLDR, not typed in.
def _canon(d: Decimal) -> str:
    return format(d.normalize(), "f")


def _amount_candidates(text: str) -> frozenset[str]:
    return frozenset(_canon(parse_decimal(text, locale=loc)) for loc in ("en", "de"))


def _formatted(amount: str, locale: str) -> str:
    return format_decimal(Decimal(amount), locale=locale)


_AMBIGUOUS_AMOUNTS = [_formatted("1234", "en"), _formatted("7654", "en"), "2,500", "9.999"]
D1_MONEY_AMBIGUOUS: tuple[Case, ...] = tuple(
    Case(f"d1-money-amb-{t}", "MONEY", t, "abstain", candidates=_amount_candidates(t))
    for t in _AMBIGUOUS_AMOUNTS
    if len(_amount_candidates(t)) == 2
)
# Both separators present, so the last one is the decimal mark under any CLDR locale.
D1_MONEY_CLEAN: tuple[Case, ...] = tuple(
    Case(f"d1-money-{loc}-{amt}", "MONEY", _formatted(amt, loc), "clean", _canon(Decimal(amt)))
    for loc in ("en", "de")
    for amt in ("1234.56", "9876543.21")
)

D1_ALL: tuple[Case, ...] = (
    D1_PHONE_AMBIGUOUS
    + D1_DATE_AMBIGUOUS
    + D1_MONEY_AMBIGUOUS
    + D1_PHONE_CLEAN
    + D1_DATE_CLEAN
    + D1_MONEY_CLEAN
)
D1_AMBIGUOUS_ONLY: tuple[Case, ...] = tuple(c for c in D1_ALL if c.expected == "abstain")

# --------------------------------------------------------------------------- D7
# Valid tax numbers for countries OUTSIDE the registry's US/GB/DE/FR, built from
# python-stdnum's own check-digit functions: (country, module, first body to try).
# One module per country is "the tax identifier" in stdnum's own title
# (VAT / tax number); countries with several such modules are left out on purpose.
_TAX_SPECS = [
    ("PT", "stdnum.pt.nif", 10000000),
    ("GR", "stdnum.gr.vat", 10000000),
    ("CL", "stdnum.cl.rut", 10000000),
    ("CO", "stdnum.co.nit", 100000000),
    ("TR", "stdnum.tr.vkn", 100000000),
    ("AR", "stdnum.ar.cuit", 3000000000),
]


def _build_valid(module_path: str, start: int) -> tuple[str, str]:
    """(valid number, one-check-character-changed invalid twin) via stdnum itself."""
    mod = importlib.import_module(module_path)
    width = len(str(start))
    for body in range(start, start + 5000):
        number = f"{body:0{width}d}" + str(mod.calc_check_digit(f"{body:0{width}d}"))
        if mod.is_valid(number):
            twin = next(
                number[:-1] + ch
                for ch in "0123456789"
                if ch != number[-1] and not mod.is_valid(number[:-1] + ch)
            )
            return number, twin
    raise AssertionError(f"no valid number found for {module_path}")  # pragma: no cover


TAX_NUMBERS: dict[str, tuple[str, str]] = {cc: _build_valid(m, s) for cc, m, s in _TAX_SPECS}


def _stdnum_has_country(code: str) -> bool:
    for name in (code.lower(), code.lower() + "_"):
        try:
            importlib.import_module(f"stdnum.{name}")
        except ImportError:
            continue
        return True
    return False


# ISO 3166-1 countries python-stdnum has no package for: no offline validator applies.
UNLISTED_COUNTRY: str = next(
    c.alpha_2
    for c in sorted(pycountry.countries, key=lambda c: c.alpha_2)
    if not _stdnum_has_country(c.alpha_2)
)

D7_VALID: tuple[Case, ...] = tuple(
    Case(f"d7-valid-{cc}", "TAX_ID", good, "clean", good, context={"country": cc})
    for cc, (good, _) in TAX_NUMBERS.items()
)
D7_INVALID: tuple[Case, ...] = tuple(
    Case(f"d7-invalid-{cc}", "TAX_ID", bad, "invalid", context={"country": cc})
    for cc, (_, bad) in TAX_NUMBERS.items()
)
# Never-guess: nothing offline can decide these, so the answer is "unverifiable"
# (an abstention), neither VALID nor INVALID. Today they come back NORMALIZED/VALID.
_ANY_NUMBER = next(iter(TAX_NUMBERS.values()))[0]
D7_UNVERIFIABLE: tuple[Case, ...] = (
    Case(
        "d7-unlisted-country",
        "TAX_ID",
        _ANY_NUMBER,
        "abstain",
        context={"country": UNLISTED_COUNTRY},
    ),
    Case("d7-no-country", "TAX_ID", _ANY_NUMBER, "abstain"),
)
D7_ALL: tuple[Case, ...] = D7_VALID + D7_INVALID + D7_UNVERIFIABLE


# --------------------------------------------------------------------------- D8
# One string, two semantic types. TAX_ID with a country is verifiable (an
# invalid check digit is INVALID); CODE is only canonicalized: it never reports a
# check-digit verdict. Pairs are (TAX_ID case, CODE case) over the same input.
def _fr_siren() -> tuple[str, str]:
    """A SIREN (one of today's four registry countries) from stdnum's own luhn check digit."""
    body = "12345678"
    number = body + luhn.calc_check_digit(body)
    twin = next(
        number[:-1] + ch
        for ch in "0123456789"
        if ch != number[-1] and not fr_siren.is_valid(number[:-1] + ch)
    )
    assert fr_siren.is_valid(number)
    return number, twin


_FR_VALID, _FR_INVALID = _fr_siren()
_PT_INVALID = TAX_NUMBERS["PT"][1]


def _pair(
    tag: str, text: str, country: str, tax_expected: Literal["clean", "invalid"]
) -> tuple[Case, Case]:
    canonical = text.strip().upper()
    return (
        Case(
            f"d8-{tag}-tax",
            "TAX_ID",
            text,
            tax_expected,
            canonical if tax_expected == "clean" else None,
            context={"country": country},
        ),
        Case(f"d8-{tag}-code", "CODE", text, "clean", canonical, context={"country": country}),
    )


D8_PAIRS: tuple[tuple[Case, Case], ...] = (
    _pair("fr-siren-badcheck", _FR_INVALID, "FR", "invalid"),  # a registry country today
    _pair("pt-nif-badcheck", _PT_INVALID, "PT", "invalid"),
    _pair("pt-nif-valid", TAX_NUMBERS["PT"][0], "PT", "clean"),
)
D8_ALL: tuple[Case, ...] = tuple(c for pair in D8_PAIRS for c in pair)

# --------------------------------------------------------------------------- D9
# Expected registrable_domain / public_suffix / is_private_suffix per the Public
# Suffix List algorithm. Verified against publicsuffix.org/list 2026-10-05:
# `uk`, `co.uk`, `jp` are ICANN-section rules; `github.io` is in the PRIVATE
# section; `notatld` has no rule. For IP literals, `localhost`, single labels and
# unlisted suffixes the plan (9 D9) requires registrable_domain None, never "the
# last two labels". `例え.jp` carries both forms: compute on one, test the other.


@dataclass(frozen=True)
class UrlCase:
    id: str
    url: str
    host: str  # the host as the URL states it
    registrable_domain: str | None
    public_suffix: str | None
    is_private_suffix: bool | None  # None when there is no public suffix
    registrable_domain_ascii: str | None = None  # A-label form of registrable_domain, if it differs


D9_CASES: tuple[UrlCase, ...] = (
    UrlCase("d9-co-uk", "https://a.co.uk/", "a.co.uk", "a.co.uk", "co.uk", False),
    UrlCase("d9-sub-co-uk", "https://b.a.co.uk/x", "b.a.co.uk", "a.co.uk", "co.uk", False),
    UrlCase("d9-uk", "https://a.uk/", "a.uk", "a.uk", "uk", False),
    UrlCase(
        "d9-github-io", "https://x.github.io/", "x.github.io", "x.github.io", "github.io", True
    ),
    UrlCase(
        "d9-idn-unicode",
        "https://例え.jp/",
        "例え.jp",
        "例え.jp",
        "jp",
        False,
        registrable_domain_ascii="xn--r8jz45g.jp",
    ),
    UrlCase(
        "d9-idn-alabel",
        "https://xn--r8jz45g.jp/",
        "xn--r8jz45g.jp",
        "例え.jp",
        "jp",
        False,
        registrable_domain_ascii="xn--r8jz45g.jp",
    ),
    UrlCase("d9-ipv4", "http://192.0.2.1/", "192.0.2.1", None, None, None),
    UrlCase("d9-ipv6", "http://[2001:db8::1]/", "2001:db8::1", None, None, None),
    UrlCase("d9-localhost", "http://localhost:8080/", "localhost", None, None, None),
    UrlCase("d9-unlisted-tld", "http://foo.notatld/", "foo.notatld", None, None, None),
)


def naive_registrable_domain(host: str) -> str | None:
    """The wrong implementation the cases must expose: the last two labels."""
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else None


def registrable_answers(case: UrlCase) -> frozenset[str | None]:
    """Every acceptable spelling of the expected registrable domain."""
    return frozenset(
        {case.registrable_domain, case.registrable_domain_ascii or case.registrable_domain}
    )
