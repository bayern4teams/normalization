"""Regenerate `normalizers._cldr_country_names` from Babel's CLDR data.

Run after a Babel upgrade:

    python scripts/generate_cldr_country_names.py

The map is generated rather than built at import time for one reason:
walking all ~1080 CLDR locales costs ~0.6s and peaks around 95MB of
resident memory, and the clone executor runs a POOL of worker processes
that would each pay that. A generated dict costs ~5MB and no locale I/O.
`tests/unit/test_locale_normalizers.py` rebuilds the map from Babel and
asserts the shipped file still matches, so it cannot silently drift.

Only names pycountry does NOT already resolve are emitted — pycountry
stays the authority (`country_codes.resolve_country_alpha2` consults it
first), so shipping its 239 overlapping names here would be dead weight
and would risk shadowing it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import babel
import pycountry
from babel import localedata

_OUT = Path(__file__).resolve().parents[1] / (
    "packages/normalizers/src/normalizers/_cldr_country_names.py"
)
_ALPHA2_LEN = 2


def _pycountry_resolves(name: str) -> bool:
    try:
        pycountry.countries.lookup(name)
    except LookupError:
        return False
    return True


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


def build() -> dict[str, str]:
    """name (casefolded) -> ISO 3166-1 alpha-2.

    A name that different languages give to DIFFERENT territories is
    dropped entirely rather than resolved to whichever locale happened to
    be read first — the same "never guess" rule the resolver follows.
    """
    names: dict[str, str | None] = {}
    for locale_id in localedata.locale_identifiers():
        try:
            territories = localedata.load(locale_id).get("territories", {})
        except Exception:
            territories = {}
        finally:
            # Evict: only `territories` is ever needed, and retaining every
            # locale's full data is what makes the walk expensive.
            localedata._cache.pop(locale_id, None)
        for code, name in territories.items():
            if len(code) != _ALPHA2_LEN or not isinstance(name, str):
                continue
            key = name.casefold().strip()
            if not key:
                continue
            if key in names and names[key] != code:
                names[key] = None
            elif key not in names:
                names[key] = code
    return {
        k: v
        for k, v in sorted(names.items())
        if v is not None and v in _ISO_3166_1_ALPHA2 and not _pycountry_resolves(k)
    }


def main() -> None:
    mapping = build()
    lines = [
        '"""CLDR country/territory names -> ISO 3166-1 alpha-2.',
        "",
        "GENERATED FILE - DO NOT EDIT.",
        "Regenerate with `python scripts/generate_cldr_country_names.py`.",
        "",
        f"Source: Unicode CLDR via Babel {babel.__version__}",
        "License: Unicode-3.0 (CLDR data) - https://www.unicode.org/license.txt",
        f"Generated: {dt.datetime.now(tz=dt.UTC).date().isoformat()}",
        f"Entries: {len(mapping)}",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        f"BABEL_VERSION = {babel.__version__!r}",
        "",
        "CLDR_COUNTRY_NAMES: dict[str, str] = {",
    ]
    lines += [f"    {name!r}: {code!r}," for name, code in mapping.items()]
    lines += ["}", ""]
    _OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {_OUT} ({len(mapping)} entries, {_OUT.stat().st_size / 1048576:.2f} MB)")


if __name__ == "__main__":
    main()
