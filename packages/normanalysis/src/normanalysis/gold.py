"""Gold corpus: measure whether the engine is RIGHT, not only that it did not change (D6).

Golden tests pin behaviour; they cannot say whether the pinned behaviour is correct. This module
scores an engine against cases whose truth is known, in outcome classes that a metric cannot
game: guessing shows up as `wrong-confident`, refusing everything as `over-abstain`.

* `GoldCase` / `load_cases` / `dump_cases`: the case schema, as JSONL, plus any dirty/clean CSV
  (so BART or Raha output feeds in with no new code).
* `score`: the scorer. It also returns the `(stated confidence, correct)` pairs D2 calibrates on.
* `generate_corpus`: seeded injectors that turn a clean value into a dirty one with derivable truth.
  Every seed value comes from authoritative data at run time (libphonenumber example numbers,
  CLDR via Babel, ISO 3166 via pycountry, `datetime`), never from tests.
* `cohen_kappa` / `krippendorff_alpha`: how ambiguous the corpus itself is; where annotators
  genuinely disagree, AMBIGUOUS is the correct label.

ponytail: the injector families are the types whose truth is derivable without hand labels
(phone, date, numeric, email, URL, country). Names, addresses and company names need a human or a
BART run; BART and Raha output are consumed only through `load_cases` on a dirty/clean CSV.
"""

from __future__ import annotations

import csv
import json
import math
import random
import re
import string
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

import phonenumbers
import pycountry
from babel import Locale, localedata
from babel.dates import format_date
from babel.numbers import format_decimal
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus

OUTCOMES = ("correct", "correct-abstain", "wrong-confident", "over-abstain", "wrong-status")

# Statuses where the engine emitted a value and stands behind it. Mirrors
# tests/defects/scorer.py: AMBIGUOUS is the abstention, everything else is neither clean nor a
# deliberate abstention (INVALID/FAILED/PARTIAL/NEEDS_REVIEW).
_CLEAN = frozenset(
    {
        NormalizationStatus.NORMALIZED,
        NormalizationStatus.UNCHANGED,
        NormalizationStatus.REPAIRED,
        NormalizationStatus.PARSED,
    }
)
_AMBIGUOUS = NormalizationStatus.AMBIGUOUS
_INVALID = NormalizationStatus.INVALID

Answer = tuple[str, str | None, float | None]  # (status, value, stated confidence)
Engine = Callable[["GoldCase"], Answer]


@dataclass(frozen=True)
class GoldCase:
    semantic_type: str  # FieldSemanticType member name
    context: dict[str, str]  # NormalizationContext fields (country, locale, default_region ...)
    input: str
    expected_status: str  # NormalizationStatus member name; AMBIGUOUS = abstaining is correct
    expected_value: str | None  # comparison-view value when the truth is a clean value
    candidates: tuple[str, ...]  # the readings an AMBIGUOUS input could have
    source: str  # provenance: which injector (with its seed) or which file made the case

    def __post_init__(self) -> None:
        # A mislabelled corpus must fail loudly, never be scored against a guessed meaning.
        if self.semantic_type not in FieldSemanticType.__members__:
            raise ValueError(f"unknown semantic_type {self.semantic_type!r}")
        if self.expected_status not in NormalizationStatus.__members__:
            raise ValueError(f"unknown expected_status {self.expected_status!r}")
        if unknown := set(self.context) - set(NormalizationContext.model_fields):
            raise ValueError(f"unknown context field(s) {sorted(unknown)}")
        if NormalizationStatus[self.expected_status] in _CLEAN and self.expected_value is None:
            raise ValueError(f"{self.expected_status} truth needs an expected_value")


@dataclass
class GoldReport:
    counts: dict[str, int]  # over OUTCOMES, every key present
    outcomes: list[str]  # per case, in input order
    pairs: list[tuple[float, bool]]  # (stated confidence, correct), non-abstaining answers only
    answers: list[Answer] = field(default_factory=list)  # what the engine said, in input order
    pair_types: list[str] = field(default_factory=list)  # semantic type of each pair (D2 groups)


def classify(case: GoldCase, status: str, value: str | None) -> str:
    """Five classes, the same as tests/defects/scorer.py. `wrong-status` is an answer that is
    neither a value nor the AMBIGUOUS abstention (INVALID, FAILED, PARTIAL, NEEDS_REVIEW) where the
    truth is a value or AMBIGUOUS, or neither INVALID nor a value where the truth is INVALID: a
    crash or an "invalid" verdict is never credited as a deliberate abstention."""
    truth = NormalizationStatus[case.expected_status]
    answer = NormalizationStatus(status)
    if truth in _CLEAN:
        if answer in _CLEAN:
            return "correct" if value == case.expected_value else "wrong-confident"
        return "over-abstain" if answer is _AMBIGUOUS else "wrong-status"
    if truth is _AMBIGUOUS:
        if answer in _CLEAN:
            return "wrong-confident"
        return "correct-abstain" if answer is _AMBIGUOUS else "wrong-status"
    # expected INVALID (or any other non-clean truth): the engine must say so, not emit a value
    if answer in _CLEAN:
        return "wrong-confident"
    return "correct" if answer is _INVALID else "wrong-status"


def score(cases: Iterable[GoldCase], engine: Engine) -> GoldReport:
    report = GoldReport(counts=dict.fromkeys(OUTCOMES, 0), outcomes=[], pairs=[])
    for case in cases:
        status, value, confidence = engine(case)
        outcome = classify(case, status, value)
        report.counts[outcome] += 1
        report.outcomes.append(outcome)
        report.answers.append((status, value, confidence))
        if NormalizationStatus(status) in _CLEAN and confidence is not None:
            report.pairs.append((float(confidence), outcome == "correct"))
            report.pair_types.append(case.semantic_type)
    return report


# --- the real engine ---


@cache
def _dispatcher() -> Any:
    # Lazy: normapi imports normanalysis, so a top-level import here would be a cycle.
    from normapi.app import build_dispatcher  # noqa: PLC0415

    return build_dispatcher(env_id="gold-corpus")


def default_engine(case: GoldCase) -> Answer:
    """The project's own dispatcher and registry, run on one case in its context.

    The value is the `comparison` view (the key entity resolution matches on, so the one a wrong
    answer corrupts), `display` when a normalizer fills none. A clean answer whose validation
    status is UNKNOWN/AMBIGUOUS is reported as the abstention it is (same rule as the D1-D12
    scorer in tests/defects/scorer.py).
    """
    from normapi.scaffold_profile import SCAFFOLD_PROFILE  # noqa: PLC0415

    sem = FieldSemanticType[case.semantic_type]
    ctx = NormalizationContext(field_name="f", semantic_type=sem, **case.context)
    result = _dispatcher().normalize(case.input, sem, ctx, SCAFFOLD_PROFILE)
    status = result.normalization_status
    if status in _CLEAN and result.validation_status in {"UNKNOWN", "AMBIGUOUS"}:
        status = _AMBIGUOUS
    value = result.comparison if result.comparison is not None else result.display
    return str(status.value), value, result.confidence


# --- the loader and the dumper ---


def dump_cases(cases: Iterable[GoldCase]) -> str:
    """JSONL, sorted keys, one case per line: byte-identical for equal cases."""
    return "".join(
        json.dumps(asdict(c), sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
        for c in cases
    )


_CONTEXT_COLUMNS = ("country", "locale")


def load_cases(
    path: str | Path,
    semantic_type: str | None = None,
    context: Mapping[str, str] | None = None,
) -> list[GoldCase]:
    """JSONL (the `dump_cases` schema) or a dirty/clean CSV (`.csv`).

    CSV: columns `dirty` and `clean`, plus the semantic type from a `semantic_type` column or the
    keyword; with neither it raises (a column's type is never guessed). Every row expects PARSED
    with the clean value as truth, so dirty == clean expects the value back unchanged, and a
    year-only value is never promoted to a date. Context: optional `country` / `locale` columns
    per row, else `context` (the caller's statement); none is ever inferred.
    ponytail: Raha ships dirty.csv and clean.csv as two files; merge them into one dirty/clean CSV
    first. BART's output is a table pair too. No cell-alignment loader until someone needs it.
    """
    path = Path(path)
    if path.suffix.lower() != ".csv":
        cases = []
        # split on "\n" only: str.splitlines() also cuts at U+2028/U+2029/U+0085, which JSON allows
        for line in path.read_text(encoding="utf-8-sig").split("\n"):
            if line.strip():
                row = json.loads(line)
                cases.append(GoldCase(**{**row, "candidates": tuple(row.get("candidates", ()))}))
        return cases
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    cases = []
    for n, row in enumerate(rows, start=2):  # line 1 is the header
        sem = row.get("semantic_type") or semantic_type
        if not sem:
            raise ValueError(f"{path}: no semantic_type column and none given")
        if row.get("dirty") is None or row.get("clean") is None:
            raise ValueError(f"{path}:{n}: row has no dirty or no clean cell")
        ctx = dict(context or {})
        ctx.update({k: row[k] for k in _CONTEXT_COLUMNS if row.get(k)})
        cases.append(
            GoldCase(sem, ctx, row["dirty"], "PARSED", row["clean"], (), f"csv:{path.name}:{n}")
        )
    return cases


# --- inter-annotator agreement ---


def cohen_kappa(a: Sequence[Any], b: Sequence[Any]) -> float:
    """Cohen's kappa for two raters over the same items; NaN when chance agreement is total."""
    if len(a) != len(b) or not a:
        raise ValueError("need two equal-length, non-empty label sequences")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in ca) / (n * n)
    return (observed - expected) / (1 - expected) if expected != 1 else math.nan


def krippendorff_alpha(data: Sequence[Sequence[Any]], level: str = "nominal") -> float:
    """Krippendorff's alpha, `data` = coders x units, None = missing. NaN when the pairable
    values are all one category (expected disagreement is zero, alpha is undefined).
    ponytail: nominal only (the AMBIGUOUS-or-not label); interval/ordinal need a distance metric.
    """
    if level != "nominal":
        raise ValueError(f"unsupported level {level!r}: only 'nominal'")
    coincidence: defaultdict[tuple[Any, Any], float] = defaultdict(float)
    for unit in zip(*data, strict=True):
        values = [v for v in unit if v is not None]
        if len(values) < 2:  # not pairable
            continue
        for i, c in enumerate(values):
            for j, k in enumerate(values):
                if i != j:
                    coincidence[c, k] += 1 / (len(values) - 1)
    totals: defaultdict[Any, float] = defaultdict(float)
    for (c, _), w in coincidence.items():
        totals[c] += w
    n = sum(totals.values())
    disagree = sum(w for (c, k), w in coincidence.items() if c != k)
    chance = n * n - sum(t * t for t in totals.values())  # sum over c != k of n_c * n_k
    return 1 - (n - 1) * disagree / chance if chance else math.nan


# --- injectors ---
# Each takes (rng, i) and returns one GoldCase. The kind rotates with i, so every kind appears
# once n >= number of kinds. Truth comes from the authoritative library, never from the engine.


def _case(
    sem: str,
    inp: str,
    status: str,
    value: str | None,
    source: str,
    *,
    context: dict[str, str] | None = None,
    candidates: tuple[str, ...] = (),
) -> GoldCase:
    return GoldCase(sem, context or {}, inp, status, value, candidates, source)


def _phone(rng: random.Random, i: int) -> GoldCase:
    kinds = ("national+region", "international", "region-removed")
    kind = kinds[i % len(kinds)]
    fmt = phonenumbers.PhoneNumberFormat
    regions = sorted(phonenumbers.SUPPORTED_REGIONS)
    for _ in range(1000):
        region = rng.choice(regions)
        num = phonenumbers.example_number(region)
        if num is None or not phonenumbers.is_valid_number(num):
            continue
        e164 = phonenumbers.format_number(num, fmt.E164)
        national = phonenumbers.format_number(num, fmt.NATIONAL)
        try:  # the truth must survive libphonenumber's own round trip, or it is not truth
            back = phonenumbers.parse(national, region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.format_number(back, fmt.E164) != e164:
            continue
        src = f"phone/{kind}/{region}"
        if kind == "international":
            style = rng.choice((fmt.E164, fmt.INTERNATIONAL))
            return _case("PHONE", phonenumbers.format_number(num, style), "PARSED", e164, src)
        if kind == "national+region":
            ctx = {rng.choice(("country", "default_region")): region}
            return _case("PHONE", national, "PARSED", e164, src, context=ctx)
        # region removed: the same national string with no region and no '+' names no country
        try:
            phonenumbers.parse(national, None)
        except phonenumbers.NumberParseException:
            return _case("PHONE", national, "AMBIGUOUS", None, src)
    raise RuntimeError("no libphonenumber example number met the injector's conditions")


def _short_date_pattern(locale: Locale) -> str | None:
    """The CLDR short date pattern widened to a 4-digit year, if it is purely numeric d/M/y."""
    pattern = re.sub("y+", "y", locale.date_formats["short"].pattern)  # never a 2-digit year
    letters = "".join(ch for ch in pattern if ch.isalpha())
    return pattern if set(letters) <= set("dMy") and letters[:1] in ("d", "M") else None


@cache
def _region_locales() -> tuple[Locale, ...]:
    """CLDR language_REGION locales (no script variants), in a fixed order."""
    out = []
    for ident in sorted(localedata.locale_identifiers()):
        loc = Locale.parse(ident)
        if loc.territory and not loc.script and str(loc) == ident:
            out.append(loc)
    return tuple(out)


def _date(rng: random.Random, i: int) -> GoldCase:
    kinds = ("swap-ambiguous", "day-over-12", "same-day-month", "locale", "year-only")
    kind = kinds[i % len(kinds)]
    day = date.fromordinal(
        rng.randint(date(1990, 1, 1).toordinal(), date(2035, 12, 31).toordinal())
    )
    src = f"date/{kind}"
    sep = rng.choice("/-.")
    pad = rng.choice(("{:02d}", "{}"))
    if kind == "year-only":  # precision is preserved: the source stated a year, the truth is a year
        return _case("DATE", str(day.year), "PARSED", str(day.year), src)
    if kind == "locale":
        for _ in range(1000):
            loc = rng.choice(_region_locales())
            pattern = _short_date_pattern(loc)
            d = date(day.year, rng.randint(1, 12), rng.randint(1, 12))
            text = format_date(d, pattern, locale=loc) if pattern else ""
            if text and text.isascii() and d.day != d.month:
                ctx = {"locale": str(loc).replace("_", "-")}
                return _case("DATE", text, "PARSED", d.isoformat(), src, context=ctx)
        raise RuntimeError("no CLDR locale gave a numeric short date")
    if kind == "swap-ambiguous":  # both parts <= 12 and different: day/month order is not stated
        a, b = rng.sample(range(1, 13), 2)
        readings = tuple(
            sorted({date(day.year, b, a).isoformat(), date(day.year, a, b).isoformat()})
        )
        text = sep.join((pad.format(a), pad.format(b), str(day.year)))
        return _case("DATE", text, "AMBIGUOUS", None, src, candidates=readings)
    if kind == "same-day-month":  # both readings agree, so the value is decided
        d = date(day.year, day.month, day.month)
    else:  # a part above 12 can only be a day
        d = date(day.year, day.month, rng.randint(13, 28))
    first, second = (d.day, d.month) if rng.random() < 0.5 else (d.month, d.day)
    text = sep.join((pad.format(first), pad.format(second), str(d.year)))
    return _case("DATE", text, "PARSED", d.isoformat(), src)


def _digits(rng: random.Random, n: int, *, last_nonzero: bool = False) -> str:
    s = "".join(rng.choice(string.digits) for _ in range(n))
    return s[:-1] + rng.choice(string.digits[1:]) if last_nonzero else s


def _numeric(rng: random.Random, i: int) -> GoldCase:
    kinds = ("lone-group-like", "us-both", "eu-both", "repeated-group", "plain", "locale")
    kind = kinds[i % len(kinds)]
    src = f"numeric/{kind}"
    whole = rng.randint(1000, 999_999_999)
    frac = _digits(rng, rng.randint(1, 2), last_nonzero=True)
    truth = f"{whole}.{frac}"
    groups = f"{whole:,}"
    if kind == "lone-group-like":  # d.ddd / d,ddd: thousands or decimals, the text cannot say
        head, tail = rng.randint(1, 999), _digits(rng, 3)
        return _case(
            "NUMERIC",
            f"{head}{rng.choice(',.')}{tail}",
            "AMBIGUOUS",
            None,
            src,
            candidates=tuple(sorted({f"{head}{tail}", f"{head}.{tail}"})),
        )
    if kind == "us-both":  # the last mark is the decimal one when both appear
        return _case("NUMERIC", f"{groups}.{frac}", "NORMALIZED", truth, src)
    if kind == "eu-both":
        return _case("NUMERIC", f"{groups.replace(',', '.')},{frac}", "NORMALIZED", truth, src)
    if kind == "repeated-group":  # a mark that repeats can only group; whole >= 1e6 repeats it
        mark = rng.choice(",.")
        text = f"{rng.randint(1_000_000, 999_999_999):,}".replace(",", mark)
        return _case("NUMERIC", text, "NORMALIZED", text.replace(mark, ""), src)
    if kind == "plain":  # 1-2 fraction digits, so never group-like
        return _case("NUMERIC", truth, "NORMALIZED", truth, src)
    for _ in range(1000):  # locale: CLDR formats the known value; the engine must read it back
        loc = rng.choice(_region_locales())
        if loc.default_numbering_system == "latn":
            ctx = {"locale": str(loc).replace("_", "-")}
            text = format_decimal(Decimal(truth), locale=loc)
            return _case("NUMERIC", text, "NORMALIZED", truth, src, context=ctx)
    raise RuntimeError("no CLDR locale uses Latin digits")


def _mixed_case(rng: random.Random, text: str) -> str:
    return "".join(rng.choice((str.upper, str.lower))(ch) for ch in text)


@cache
def _words() -> tuple[str, ...]:
    """Seed words: single-word ASCII CLDR English territory names, lower-cased."""
    names = Locale("en").territories.values()
    return tuple(sorted({n.lower() for n in names if n.isascii() and n.isalpha()}))


def _email(rng: random.Random, i: int) -> GoldCase:
    kinds = ("upper-domain", "mixed-domain", "mixed-local-and-domain")
    kind = kinds[i % len(kinds)]
    local = f"{rng.choice(_words())}.{rng.choice(_words())}"
    host = f"{rng.choice(_words())}.example"  # RFC 2606 reserved TLD
    host = _mixed_case(rng, host) if kind == "mixed-domain" else host.upper()
    if kind == "mixed-local-and-domain":  # the local part is case-sensitive (RFC 5321): kept
        local = _mixed_case(rng, local)
    lead = rng.choice(("", " "))
    return _case(
        "EMAIL",
        f"{lead}{local}@{host}",
        "NORMALIZED",
        f"{local}@{host.lower()}",
        f"email/{kind}",
    )


_SCHEMES = ("http", "https")


def _url(rng: random.Random, i: int) -> GoldCase:
    kinds = ("upper-scheme-host", "mixed-host-and-path", "bare-host")
    kind = kinds[i % len(kinds)]
    host = f"{rng.choice(_words())}.example"  # RFC 2606 reserved TLD
    path = f"/{_mixed_case(rng, rng.choice(_words()))}"  # the path is case-sensitive: kept
    scheme = rng.choice(_SCHEMES)
    src = f"url/{kind}"
    if kind == "bare-host":
        # ponytail: a bare host states no scheme, so the truth is both readings. url.py assumes
        # https and flags it (a documented policy); under "never invent" that is a miss, and this
        # kind is where it shows. Drop the kind to score only the policy-neutral cases.
        return _case(
            "URL",
            host + path,
            "AMBIGUOUS",
            None,
            src,
            candidates=tuple(f"{s}://{host}{path}" for s in _SCHEMES),
        )
    if kind == "upper-scheme-host":
        text = f"{scheme.upper()}://{host.upper()}{path}"
    else:
        text = f"{scheme}://{_mixed_case(rng, host)}{path}"
    return _case("URL", text, "NORMALIZED", f"{scheme}://{host}{path}", src)


# ponytail: seven CLDR locales' names per country; more locales mean more coverage, no new code.
_COUNTRY_LOCALES = ("en", "de", "fr", "es", "it", "ja", "ru")


@cache
def _country_names() -> tuple[tuple[str, ...], dict[str, set[str]]]:
    """(ISO 3166-1 alpha-2 codes CLDR names in some locale,
    casefolded name or code -> the codes it could mean)."""
    codes = sorted(c.alpha_2 for c in pycountry.countries)
    meaning: dict[str, set[str]] = {}
    for code in codes:
        meaning.setdefault(code.casefold(), set()).add(code)
        for loc in _COUNTRY_LOCALES:
            if name := Locale(loc).territories.get(code):
                meaning.setdefault(name.casefold(), set()).add(code)
    named = tuple(
        c for c in codes if any(Locale(loc).territories.get(c) for loc in _COUNTRY_LOCALES)
    )
    return named, meaning


def _country(rng: random.Random, i: int) -> GoldCase:
    kinds = ("name", "name-upper", "name-lower", "code", "code-lower")
    kind = kinds[i % len(kinds)]
    codes, meaning = _country_names()
    code = rng.choice(codes)
    name = ""
    while not name:  # a few CLDR locales lack a name for a rare territory
        name = Locale(rng.choice(_COUNTRY_LOCALES)).territories.get(code, "")
    text = {
        "name": name,
        "name-upper": name.upper(),
        "name-lower": name.lower(),
        "code": code,
        "code-lower": code.lower(),
    }[kind]
    hits = sorted(meaning[text.casefold()])  # a name two countries share is not decidable
    src = f"country/{kind}"
    if len(hits) > 1:
        return _case("COUNTRY", text, "AMBIGUOUS", None, src, candidates=tuple(hits))
    return _case("COUNTRY", text, "NORMALIZED", hits[0], src)


_INJECTORS = {
    "phone": _phone,
    "date": _date,
    "numeric": _numeric,
    "email": _email,
    "url": _url,
    "country": _country,
}


def generate_corpus(seed: int, n_per_injector: int) -> list[GoldCase]:
    """`n_per_injector` cases per family, deterministic in `seed` alone. Each family has its own
    `random.Random` seeded by a string (hashed with SHA-512, not `hash()`), so output does not
    depend on PYTHONHASHSEED nor does one family's size shift another's draws."""
    cases: list[GoldCase] = []
    for name, inject in _INJECTORS.items():
        rng = random.Random(f"{seed}/{name}")
        cases += [inject(rng, i) for i in range(n_per_injector)]
    missing = _missing_value_tokens()
    return [_label(c, seed, missing) for c in cases]


@cache
def _missing_value_tokens() -> frozenset[str]:
    """The engine's own missing-value table (the dictionary the Dispatcher loads), casefolded."""
    # Lazy: normapi imports normanalysis (a top-level import would be a cycle).
    from normalizers.generic_text import load_missing_value_sentinels  # noqa: PLC0415
    from normapi.app import _DEFAULT_DICTIONARIES_DIR  # noqa: PLC0415

    from normdict import DictionaryLoader  # noqa: PLC0415

    return frozenset(load_missing_value_sentinels(DictionaryLoader(_DEFAULT_DICTIONARIES_DIR)))


def _label(case: GoldCase, seed: int, missing: frozenset[str]) -> GoldCase:
    """Stamp provenance. A text that is also a missing-value token (the code NA, say) states no
    value, so the truth is AMBIGUOUS between the injector's value and 'missing'."""
    case = replace(case, source=f"{case.source} seed={seed}")
    if case.input.strip().casefold() in missing and case.expected_value is not None:
        return replace(
            case,
            expected_status="AMBIGUOUS",
            expected_value=None,
            candidates=(case.expected_value,),
        )
    return case
