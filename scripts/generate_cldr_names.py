"""Regenerate the `normalizers._cldr_*_names` tables from Babel's CLDR data.

Run after a Babel upgrade:

    python scripts/generate_cldr_names.py

The maps are generated rather than built at import time for one reason:
walking all ~1080 CLDR locales costs ~0.6s and peaks around 95MB of
resident memory, and the clone executor runs a POOL of worker processes
that would each pay that. A generated dict costs a few MB and no locale
I/O. `tests/unit/test_locale_normalizers.py` rebuilds every map from
Babel and asserts the shipped files still match, so they cannot silently
drift.

One walk, three modules: the walk is shared (loading each locale once for
all four tables is most of the cost), but `_cldr_country_names` alone is
1MB and `_cldr_language_names` 1.4MB, so a single combined module would
make `CurrencyNormalizer` pay for the language table it never reads. Each
normalizer imports only its own.

Babel exposes no `alt="short"` territory names, so those come from CLDR's own
XML, and only when a `core.zip` of the same CLDR version is given:

    python scripts/generate_cldr_names.py --cldr-core <path>/core.zip

Without it `_cldr_country_short_names` is left as it is.

Only names the existing authority does NOT already resolve are emitted.
pycountry stays the authority for countries and languages, so shipping
its overlapping names here would be dead weight and would risk shadowing
it. Currency is the exception: `currency.py` never looks a currency up by
name in pycountry, so there is nothing to defer to.
"""

from __future__ import annotations

import argparse
import datetime as dt
import unicodedata
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree

import babel
import pycountry
from babel import localedata
from normalizers.currency import NON_CURRENCY_CODES

if TYPE_CHECKING:
    from collections.abc import Iterable

_PACKAGE = Path(__file__).resolve().parents[1] / "packages/normalizers/src/normalizers"
_ALPHA2_LEN = 2
_MIN_LATIN_NAME_LEN = 3

# CLDR's territory list is wider than ISO 3166-1: it also carries
# organizations (EU, EZ, UN), macro-regions (QO), exceptionally reserved
# and subdivision codes (AC, CP, CQ, DG, EA, IC, TA), the user-assigned
# XK for Kosovo, the "unknown region" ZZ, and even the XA/XB pseudo-
# locales CLDR ships for UI testing. `resolve_country_alpha2` promises an
# ISO 3166-1 alpha-2 code and its callers (postcode validation,
# downstream pycountry lookups) rely on that, so anything ISO does not
# list is dropped here rather than filtered at every call site. This is
# also what keeps "European Union" and "Unknown Region" from resolving to
# a country at all.
_ISO_3166_1_ALPHA2 = {country.alpha_2 for country in pycountry.countries}

_ISO_4217 = {currency.alpha_3 for currency in pycountry.currencies}

# Every CLDR name of XXX and XTS is a variant of "Unknown Currency" or "Test
# Currency", so they are dropped. Dropping XXX also drops "¤" (U+00A4 CURRENCY
# SIGN), which is CLDR's generic placeholder and must never resolve.


def _pycountry_keys(database: Iterable[pycountry.db.Data]) -> frozenset[str]:
    """Every string `pycountry.<db>.lookup()` would resolve, lowercased.

    `lookup()` itself is O(n) on a MISS, and the filters below are ~87k
    misses by construction — 1ms each, which was ~90s of the ~95s a naive
    regeneration cost. `lookup()` matches any field of any record
    case-insensitively, so the set of every field value is exactly the set
    it resolves, at O(1). Reading `_fields` rather than the public
    `indices` matters: `indices` covers only name/alpha_2/alpha_3/
    bibliographic, and misses `common_name` — which is the one and only
    reason "Bangla" resolves to Bengali.

    Only used to decide what to OMIT (pycountry resolves it already), so a
    false negative costs one redundant entry, never a wrong answer.
    """
    return frozenset(
        value.lower()
        for record in database
        for value in record._fields.values()
        if isinstance(value, str)
    )


_PYCOUNTRY_COUNTRY_KEYS = _pycountry_keys(pycountry.countries)
_PYCOUNTRY_LANGUAGE_KEYS = _pycountry_keys(pycountry.languages)

# The subtag a language NAME maps to must itself be a real ISO 639 code —
# not merely something pycountry resolves, which would also accept a
# language's name where a code belongs.
_ISO_639_SUBTAGS = frozenset(
    code.lower()
    for language in pycountry.languages
    for code in (getattr(language, "alpha_2", None), language.alpha_3)
    if code
)


def _is_too_short_to_be_a_name(key: str) -> bool:
    """A one- or two-letter Latin string is a CODE shape, not a name.

    CLDR offers "or" (French for gold) as a name for XAU and a handful of
    two-letter strings as language names. Matching those on a whole-value
    lookup resolves junk and near-misses at confidence 1.0, and for
    languages it would shadow ISO 639-1, which pycountry already owns.
    Non-Latin names are not filtered: "中文" (Chinese) and "美元" (US
    dollar) are two characters and entirely unambiguous.

    Deliberately NOT applied to the standard country names, where a two-letter
    ASCII name is a real win: CLDR is the only source here that resolves
    "UK", which is neither an ISO code nor a pycountry alias.
    """
    return len(key) < _MIN_LATIN_NAME_LEN and key.isascii() and key.isalpha()


def _is_invisible(symbol: str) -> bool:
    """CLDR ships a zero-width space as one locale's symbol for CVE."""
    return all(unicodedata.category(ch) in {"Zs", "Cf", "Cc"} for ch in symbol)


def _record(target: dict[str, str | None], key: str, code: str) -> None:
    """Accumulate key -> code, collapsing to None on disagreement.

    A name that different languages give to DIFFERENT things is dropped
    entirely rather than resolved to whichever locale happened to be read
    first — the same "never guess" rule the resolvers follow. For symbols
    this is what keeps §47 honest for free: "$" is USD in en_US and CAD
    in en_CA, so it collapses to None without anyone curating a list.
    """
    if key not in target:
        target[key] = code
    elif target[key] != code:
        target[key] = None


def _resolved(raw: dict[str, str | None]) -> Iterable[tuple[str, str]]:
    for key, code in sorted(raw.items()):
        if code is not None:
            yield key, code


def build() -> dict[str, dict[str, str]]:
    """Every generated map, from one pass over the CLDR locale set."""
    countries: dict[str, str | None] = {}
    currency_names: dict[str, str | None] = {}
    currency_symbols: dict[str, str | None] = {}
    symbol_codes: dict[str, set[str]] = {}
    languages: dict[str, str | None] = {}

    for locale_id in localedata.locale_identifiers():
        try:
            data = localedata.load(locale_id)
            territories = data.get("territories", {})
            raw_currency_names = data.get("currency_names", {})
            raw_currency_symbols = data.get("currency_symbols", {})
            raw_languages = data.get("languages", {})
        except Exception:
            territories, raw_currency_names, raw_currency_symbols, raw_languages = {}, {}, {}, {}
        finally:
            # Evict: only these four sections are ever needed, and
            # retaining every locale's full data is what makes the walk
            # expensive.
            localedata._cache.pop(locale_id, None)

        for code, name in territories.items():
            if len(code) == _ALPHA2_LEN and isinstance(name, str) and name.casefold().strip():
                _record(countries, name.casefold().strip(), code)

        for code, name in raw_currency_names.items():
            if isinstance(name, str) and name.casefold().strip():
                _record(currency_names, name.casefold().strip(), code)

        for code, symbol in raw_currency_symbols.items():
            # A symbol equal to its own code carries no information — the
            # ISO-code path already resolves those.
            if isinstance(symbol, str) and symbol.strip() and symbol.strip() != code:
                _record(currency_symbols, symbol.strip(), code)
                symbol_codes.setdefault(symbol.strip(), set()).add(code)

        for code, name in raw_languages.items():
            # "en_GB" -> "British English": the language subtag is what
            # LanguageNormalizer resolves, and the region it would throw
            # away here is exactly what the BCP 47 tag path preserves in
            # `tag_territory`. Skipped rather than flattened.
            if "_" not in code and isinstance(name, str) and name.casefold().strip():
                _record(languages, name.casefold().strip(), code)

    return {
        "CLDR_COUNTRY_NAMES": {
            name: code
            for name, code in _resolved(countries)
            if code in _ISO_3166_1_ALPHA2 and name not in _PYCOUNTRY_COUNTRY_KEYS
        },
        "CLDR_CURRENCY_NAMES": {
            name: code
            for name, code in _resolved(currency_names)
            if code in _ISO_4217
            and code not in NON_CURRENCY_CODES
            and not _is_too_short_to_be_a_name(name)
        },
        "CLDR_CURRENCY_SYMBOLS": {
            symbol: code
            for symbol, code in _resolved(currency_symbols)
            if code in _ISO_4217 and code not in NON_CURRENCY_CODES and not _is_invisible(symbol)
        },
        # The symbols `_record` dropped for naming several currencies ("$":
        # USD in en_US, CAD in en_CA): a value that is one of them is a
        # currency whose code is unstated, AMBIGUOUS rather than INVALID.
        "CLDR_SHARED_CURRENCY_SYMBOLS": {
            symbol: " ".join(sorted(real))
            for symbol, codes in sorted(symbol_codes.items())
            if len(real := {c for c in codes if c in _ISO_4217 and c not in NON_CURRENCY_CODES}) > 1
            and not _is_invisible(symbol)
        },
        "CLDR_LANGUAGE_NAMES": {
            name: subtag
            for name, subtag in _resolved(languages)
            if subtag.lower() in _ISO_639_SUBTAGS
            and name not in _PYCOUNTRY_LANGUAGE_KEYS
            and not _is_too_short_to_be_a_name(name)
        },
    }


def build_short_names(core_zip: Path) -> dict[str, str]:
    """CLDR's `alt="short"` territory names. Every other territory name in the
    XML takes part in the clash check, so a short name that also means another
    territory in any locale is dropped, as in `build`."""
    every_name: dict[str, str | None] = {}
    short: set[str] = set()
    with zipfile.ZipFile(core_zip) as archive:
        for member in archive.namelist():
            if not (member.startswith("common/main/") and member.endswith(".xml")):
                continue
            for element in ElementTree.fromstring(archive.read(member)).iter("territory"):
                code, name = element.get("type", ""), (element.text or "").casefold().strip()
                if len(code) != _ALPHA2_LEN or not name or name == "↑↑↑":
                    continue
                if element.get("draft") == "unconfirmed":
                    continue
                _record(every_name, name, code)
                if element.get("alt") == "short":
                    short.add(name)
    return {
        name: code
        for name, code in _resolved(every_name)
        if name in short
        and code in _ISO_3166_1_ALPHA2
        and name not in _PYCOUNTRY_COUNTRY_KEYS
        and not _is_too_short_to_be_a_name(name)  # "su" must stay the withdrawn code
    }


_MODULES: dict[str, tuple[str, ...]] = {
    "_cldr_country_names": ("CLDR_COUNTRY_NAMES",),
    "_cldr_currency_names": (
        "CLDR_CURRENCY_NAMES",
        "CLDR_CURRENCY_SYMBOLS",
        "CLDR_SHARED_CURRENCY_SYMBOLS",
    ),
    "_cldr_language_names": ("CLDR_LANGUAGE_NAMES",),
    "_cldr_country_short_names": ("CLDR_COUNTRY_SHORT_NAMES",),
}

_SUMMARIES: dict[str, str] = {
    "CLDR_COUNTRY_NAMES": "country/territory name (casefolded) -> ISO 3166-1 alpha-2",
    "CLDR_COUNTRY_SHORT_NAMES": "CLDR alt=short country name (casefolded) -> ISO 3166-1 alpha-2",
    "CLDR_CURRENCY_NAMES": "currency name (casefolded) -> ISO 4217 alpha-3",
    "CLDR_CURRENCY_SYMBOLS": "currency symbol (as written) -> ISO 4217 alpha-3",
    "CLDR_SHARED_CURRENCY_SYMBOLS": "currency symbol naming several currencies -> their codes",
    "CLDR_LANGUAGE_NAMES": "language name (casefolded) -> ISO 639 subtag",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cldr-core", type=Path, help="CLDR core.zip of Babel's CLDR version")
    core_zip = parser.parse_args().cldr_core
    maps = build()
    if core_zip:
        maps["CLDR_COUNTRY_SHORT_NAMES"] = build_short_names(core_zip)
    for module, map_names in _MODULES.items():
        if map_names[0] not in maps:
            continue
        lines = [
            f'"""{_SUMMARIES[map_names[0]]}.',
            "",
            "GENERATED FILE - DO NOT EDIT.",
            "Regenerate with `python scripts/generate_cldr_names.py`.",
            "",
            f"Source: Unicode CLDR via Babel {babel.__version__}",
            "License: Unicode-3.0 (CLDR data) - https://www.unicode.org/license.txt",
            f"Generated: {dt.datetime.now(tz=dt.UTC).date().isoformat()}",
            '"""',
            "",
            "from __future__ import annotations",
            "",
            f"BABEL_VERSION = {babel.__version__!r}",
        ]
        for map_name in map_names:
            mapping = maps[map_name]
            lines += ["", f"# {len(mapping)} entries.", f"{map_name}: dict[str, str] = {{"]
            lines += [f"    {key!r}: {code!r}," for key, code in mapping.items()]
            lines += ["}"]
        out = _PACKAGE / f"{module}.py"
        out.write_text("\n".join([*lines, ""]), encoding="utf-8")
        print(f"wrote {out} ({out.stat().st_size / 1048576:.2f} MB)")


if __name__ == "__main__":
    main()
