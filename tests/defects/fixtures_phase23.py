"""Planted ground truth for D10, D11, D5 and D4 (plan 8 Phase 0 step 4, P0-B).

Constants and pure builders only: no test functions, nothing here imports a
normalizer. Truth comes from an authoritative source wherever one exists, so
none of it is tuned to a database or copied from a unit test:

- D10: libphonenumber example numbers (`phonenumbers.example_number`).
- D11: same-name groups are human assertions (the spellings are listed in the
  plan and report); extra spellings are generated with ICU's published
  BGN/PCGN transliteration schemes (CLDR data, `iuliia` is not installed).
- D5: the typed set and the numeric ceilings are read from the destination's
  own `storage_types` at run time, never listed here.
- D4: counts are constructed, so they are exact by construction; the alpha-2
  list comes from `pycountry` (ISO 3166).

D6 and D2 build their own corpus in phase 3; nothing for them lives here.
"""

from __future__ import annotations

import datetime
import decimal
import re
from dataclasses import dataclass, field
from typing import Final

import icu
import phonenumbers
import pycountry
from phonenumbers import PhoneNumberFormat as Fmt

# ---------------------------------------------------------------------------
# D10: phone extensions
# ---------------------------------------------------------------------------

# Spelling label -> suffix appended to the base number. The four spellings of
# the report/plan; each of them parses to extension "45" in libphonenumber.
EXTENSION_SPELLINGS: Final[dict[str, str]] = {
    "x": " x45",
    "ext.": " ext. 45",
    ";ext=": ";ext=45",
    "#": " #45",
}
EXTENSION: Final = "45"
OTHER_EXTENSION: Final = "46"

# Regions whose example number is a valid fixed line; spread over country-code
# lengths and national-number shapes so one regex cannot fit all of them.
PHONE_REGIONS: Final = ("US", "GB", "DE", "FR", "AU", "JP", "BR", "IN", "ES", "NZ")


@dataclass(frozen=True)
class PhoneExtensionCase:
    region: str
    base_e164: str  # truth: what the number is without the extension
    base_international: str  # what a source column would hold
    base_national: str  # needs a region to parse
    spellings: dict[str, str]  # label -> international form + extension spelling
    other_extension: str  # same base, extension OTHER_EXTENSION
    rfc3966_libphonenumber: str  # libphonenumber's own RFC 3966 output with ext 45
    national_with_extension: str  # national form + " ext. 45": region must come from context


def build_phone_extension_cases() -> list[PhoneExtensionCase]:
    cases = []
    for region in PHONE_REGIONS:
        base = phonenumbers.example_number(region)
        assert base is not None, region
        with_ext = phonenumbers.PhoneNumber()
        with_ext.merge_from(base)
        with_ext.extension = EXTENSION
        intl = phonenumbers.format_number(base, Fmt.INTERNATIONAL)
        national = phonenumbers.format_number(base, Fmt.NATIONAL)
        cases.append(
            PhoneExtensionCase(
                region=region,
                base_e164=phonenumbers.format_number(base, Fmt.E164),
                base_international=intl,
                base_national=national,
                spellings={label: intl + suffix for label, suffix in EXTENSION_SPELLINGS.items()},
                other_extension=intl + " x" + OTHER_EXTENSION,
                rfc3966_libphonenumber=phonenumbers.format_number(with_ext, Fmt.RFC3966),
                national_with_extension=national + " ext. " + EXTENSION,
            )
        )
    return cases


# Never-guess: a national-format number with an extension and no country
# anywhere must stay ambiguous, and an impossible country code stays invalid.
PHONE_NO_REGION_WITH_EXTENSION: Final = "020 7946 0000 x45"
PHONE_INVALID_WITH_EXTENSION: Final = "+999 123 4567 x45"


# ---------------------------------------------------------------------------
# D11: names across scripts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Spelling:
    text: str
    script: str  # planted truth: Latin / Cyrillic / Arabic / Han / ...
    source: str  # "human" (asserted) or "icu:<transliterator id>" (generated)


@dataclass(frozen=True)
class NameGroup:
    group: str  # one real name; every spelling in it is the same name
    spellings: tuple[Spelling, ...]

    def pairs(self, *, generated: bool) -> list[tuple[Spelling, Spelling]]:
        """Distinct-text pairs. `generated=False` keeps human-asserted spellings only:
        the headline counts use these. Generated ones are informational, since a
        scheme that drops vowels (Arabic) cannot be expected to match a vowelled
        spelling and the plan does not demand it."""
        pool = [s for s in self.spellings if generated or s.source == "human"]
        return [(a, b) for i, a in enumerate(pool) for b in pool[i + 1 :] if a.text != b.text]


def _icu(transliterator_id: str, text: str) -> str:
    return str(icu.Transliterator.createInstance(transliterator_id).transliterate(text))


def _human(text: str, script: str) -> Spelling:
    return Spelling(text, script, "human")


def build_name_groups() -> list[NameGroup]:
    groups = [
        NameGroup(
            "muhammad",
            (
                _human("Мухаммед", "Cyrillic"),
                _human("Muhammad", "Latin"),
                _human("Mohammed", "Latin"),
                _human("Mohammad", "Latin"),
                _human("محمد", "Arabic"),
            ),
        ),
        NameGroup(
            "yuri",
            (
                _human("Юрий", "Cyrillic"),
                _human("Yuri", "Latin"),
                _human("Yury", "Latin"),
                _human("Yuriy", "Latin"),
            ),
        ),
        NameGroup(
            "alexander",
            (
                _human("Александр", "Cyrillic"),
                _human("Aleksandr", "Latin"),
                _human("Alexander", "Latin"),
                _human("Alexandr", "Latin"),
            ),
        ),
        NameGroup(
            "hossein",
            (
                _human("حسین", "Arabic"),
                _human("Hossein", "Latin"),
                _human("Hussein", "Latin"),
                _human("Husayn", "Latin"),
            ),
        ),
        NameGroup(
            "elena",
            (
                _human("Елена", "Cyrillic"),
                _human("Yelena", "Latin"),
                _human("Elena", "Latin"),
            ),
        ),
    ]
    schemes = {"Cyrillic": "Russian-Latin/BGN", "Arabic": "Persian-Latin/BGN"}
    out = []
    for g in groups:
        extra: list[Spelling] = []
        for s in g.spellings:
            scheme = schemes.get(s.script)
            latin = _icu(scheme, s.text) if scheme else None
            if latin and latin != s.text:
                extra.append(Spelling(latin, "Latin", f"icu:{scheme}"))
        out.append(NameGroup(g.group, g.spellings + tuple(extra)))
    return out


# Planted different-name pairs: skeletons differ in every consonant, so no
# reasonable phonetic key may share. (Real homophones such as Robert/Rupert are
# deliberately NOT used: sharing a key there is correct behaviour.)
DIFFERENT_NAME_PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("Muhammad", "Yuri"),
    ("Мухаммед", "Юрий"),
    ("محمد", "Юрий"),
    ("Мухаммед", "Yuri"),
    ("محمد", "Yuri"),
    ("Alexander", "Hossein"),
    ("Александр", "Hossein"),
    ("Елена", "Muhammad"),
    ("حسین", "Alexander"),
    ("Mohammad", "Olga"),
)

# CJK: readings are polyphonic (单 is Shan or Dan, 乐 is Yue or Le), so the plan
# says no key is emitted at all. 김민준 is Hangul, non-Latin but not Han.
CJK_NAMES: Final = ("王小明", "山田太郎", "单田芳", "乐嘉", "김민준", "田中 太郎")

# One planted name per further non-Latin script, for "no non-Latin input ever
# carries Soundex/NYSIIS/Metaphone/MRC".
OTHER_NON_LATIN_NAMES: Final = (
    ("Greek", "Γιώργος"),
    ("Hebrew", "משה"),
    ("Devanagari", "राजेश"),
    ("Thai", "สมชาย"),
    ("Arabic", "محمدرضا"),
)

# Latin script with diacritics: today transliterated by anyascii. The plan's
# "or whose transliteration source is anyascii" is ambiguous for these (they are
# Latin script, and "old keys for Latin input byte-identical" applies). No
# expectation is planted; the lead decides, the fixture only names them.
LATIN_DIACRITIC_NAMES: Final = ("Müller", "José", "Łukasz", "Dvořák")

# Plain ASCII Latin names whose four keys must stay byte-identical (plan D11
# accept). Captured from the current code (jellyfish 1.2.1) by
# measure_phase23_before.py: a regression snapshot of OLD output, not truth.
LATIN_OLD_KEYS: Final[dict[str, dict[str, str]]] = {
    "Smith": {
        "soundex": "S530",
        "nysiis": "SNAT",
        "metaphone": "SM0",
        "match_rating_codex": "SMTH",
    },
    "Robert": {
        "soundex": "R163",
        "nysiis": "RABAD",
        "metaphone": "RBRT",
        "match_rating_codex": "RBRT",
    },
    "Rupert": {
        "soundex": "R163",
        "nysiis": "RAPAD",
        "metaphone": "RPRT",
        "match_rating_codex": "RPRT",
    },
    "Muhammad": {
        "soundex": "M530",
        "nysiis": "MAHANAD",
        "metaphone": "MHMT",
        "match_rating_codex": "MHMD",
    },
    "Mohammed": {
        "soundex": "M530",
        "nysiis": "MAHANAD",
        "metaphone": "MHMT",
        "match_rating_codex": "MHMD",
    },
    "Yuri": {"soundex": "Y600", "nysiis": "YAR", "metaphone": "YR", "match_rating_codex": "YR"},
    "Olga": {"soundex": "O420", "nysiis": "OLG", "metaphone": "OLK", "match_rating_codex": "OLG"},
}
LATIN_PLAIN_NAMES: Final = tuple(LATIN_OLD_KEYS)
PHONETIC_KEYS: Final = ("soundex", "nysiis", "metaphone", "match_rating_codex")


def non_latin_inputs() -> list[str]:
    texts = [s.text for g in build_name_groups() for s in g.spellings if s.script != "Latin"]
    return texts + list(CJK_NAMES) + [t for _, t in OTHER_NON_LATIN_NAMES]


# ---------------------------------------------------------------------------
# D5: adversarial strings for the natively typed destination columns
# ---------------------------------------------------------------------------

ADVERSARIAL_STRINGS: Final[tuple[tuple[str, str], ...]] = (
    ("date-typo", "d1989-12-11"),
    ("nan", "NaN"),
    ("snan", "sNaN"),
    ("inf", "Infinity"),
    ("exp999", "1e999"),
    ("exp-huge", "1e1000000"),
    ("exp-tiny", "1e-1000000"),
    ("thousands", "1,234"),
    ("nul", "\x00"),
    ("ten-pow-40", str(10**40)),
    ("neg-ten-pow-40", str(-(10**40))),
    ("yes-please", "yes please"),
    ("empty", ""),
    ("spaces", "   "),
    ("tab-newline", "\t\n"),
    ("underscore", "1_000"),  # Python's Decimal accepts this; a database does not
    ("arabic-indic", "١٢٣"),  # Python's Decimal accepts these digits too
)

# Strings a valid cell of each typed type looks like; keyed by SemanticType name.
GOOD_TYPED_VALUES: Final[dict[str, str]] = {
    "NUMERIC": "1234.56",
    "MONEY": "0.1",
    "BOOLEAN": "true",
}

# Partial dates the date normalizer emits (EDTF-style). DATE/DATETIME are TEXT on
# purpose; if D5 ever types them these must survive with no month/day invented.
PARTIAL_DATES: Final = ("1990", "1990-03", "1990-03-15", "1990-03-15T10:30:00")

_TYPE_RE = re.compile(r"(?:Decimal|NUMERIC)\((\d+),\s*(\d+)\)")


def engine_precision_scale(sql_type: str) -> tuple[int, int] | None:
    """(precision, scale) of a bounded decimal type string, or None when unbounded.

    The numbers come out of the destination's own type string (storage_types),
    so a changed DDL moves this oracle with it."""
    m = _TYPE_RE.search(sql_type)
    return (int(m.group(1)), int(m.group(2))) if m else None


# Postgres docs (numeric): up to 131072 digits before the decimal point.
PG_UNBOUNDED_INTEGER_DIGITS: Final = 131072


def engine_accepts(sql_type: str, value: object) -> bool:
    """Would the engine take this cast value without overflowing?

    Models integer-digit overflow only (what kills a chunk transaction). It does
    not model every rounding path; that needs a live database (LOCAL_VERIFY)."""
    if value is None or isinstance(value, bool):
        return True
    if not isinstance(value, decimal.Decimal):
        return True
    if not value.is_finite():
        return False
    bounds = engine_precision_scale(sql_type)
    # Integer-digit count after rounding to the column's scale, from the exponent:
    # no big-int expansion of 1e1000000.
    int_digits = max(value.adjusted() + 1, 0) if value != 0 else 0
    if bounds is None:
        return int_digits <= PG_UNBOUNDED_INTEGER_DIGITS
    precision, scale = bounds
    return int_digits <= precision - scale


# ---------------------------------------------------------------------------
# D4: disguised missing data
# ---------------------------------------------------------------------------

DATE_COLUMN_ROWS: Final = 10_000
# Exact, by construction: 3% of the rows, split over three sentinels.
SENTINEL_COUNTS: Final[dict[str, int]] = {"N/A": 150, "unknown": 100, "-": 50}
COUNTRY_NA_COUNT: Final = 40


def _dates(n: int) -> list[str]:
    start = datetime.date(1950, 1, 1)
    return [(start + datetime.timedelta(days=i * 7 % 25_000)).isoformat() for i in range(n)]


def _interleave(valid: list[str], junk: list[str]) -> list[str]:
    """Deterministic spread of the junk through the column (no clustering at the end)."""
    out = list(valid)
    step = max(len(out) // max(len(junk), 1), 1)
    for k, j in enumerate(junk):
        out.insert(min(k * (step + 1), len(out)), j)
    return out


@dataclass(frozen=True)
class PlantedColumn:
    name: str
    values: list[str]
    expected_reported: dict[str, int] = field(default_factory=dict)  # value -> exact count
    note: str = ""


def build_d4_columns() -> list[PlantedColumn]:
    total_junk = sum(SENTINEL_COUNTS.values())
    assert total_junk * 100 == 3 * DATE_COLUMN_ROWS
    valid = _dates(DATE_COLUMN_ROWS - total_junk)
    junk = [v for v, n in SENTINEL_COUNTS.items() for _ in range(n)]

    # ISO 3166; "NA" is Namibia and is added back below as DATA
    alpha2 = sorted(c.alpha_2 for c in pycountry.countries if c.alpha_2 != "NA")
    country = [alpha2[i % len(alpha2)] for i in range(2_000)]
    country = _interleave(country, ["NA"] * COUNTRY_NA_COUNT)

    garbage = [f"garbage-{i:03d}" for i in range(total_junk)]
    return [
        PlantedColumn(
            "dates_3pct_sentinels",
            _interleave(valid, junk),
            dict(SENTINEL_COUNTS),
            "97% ISO dates, 3% over three sentinels with exact known counts",
        ),
        PlantedColumn(
            "country_with_namibia",
            country,
            {},
            "NA is Namibia in an alpha-2 column and must NOT be reported as missing",
        ),
        PlantedColumn("dates_no_sentinels", valid, {}, "nothing to report"),
        PlantedColumn(
            "dates_noise_not_sentinels",
            _interleave(valid, garbage),
            {},
            "30 distinct junk strings, each once: they do not recur as a small set, so a "
            "detector that reports them is guessing",
        ),
    ]


# Ceiling, not a requirement: numeric magic numbers are only reachable through
# ptype (plan D4). A native detector may legitimately report nothing here.
MAGIC_NUMBER_COLUMN: Final = PlantedColumn(
    "numbers_magic_999",
    [str(i) for i in range(1, 971)] + ["-999"] * 30,
    {},
    "ceiling: only ptype can see -999; do not demand it of the native path",
)
