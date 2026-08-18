"""Shared country-code resolution — Source.txt §33.

`pycountry.countries.lookup()` is the authority (per
docs/normalization-tool-evaluation.md's M0 selection) and handles ISO
alpha-2/alpha-3 codes, full names, and most common aliases
case-insensitively — including, somewhat surprisingly, "USA" (a
registered pycountry alias) but NOT the equally common "UK" or "Great
Britain" (neither is an ISO code or a registered pycountry alias; the
ISO code for both, per §33's own worked example, is "GB").
`_KNOWN_NON_ISO_ALIASES` closes exactly that kind of gap, curated from
real values (`libpostal`'s country component, and §33's own named
examples) — extend it as new gaps are found empirically, not
speculatively. "Great Britain" resolving via `pycountry.countries.
search_fuzzy()` was considered and rejected: fuzzy search is unreliable
for short strings (`search_fuzzy("uk")` ranks Uganda first), so it is not
used as a fallback anywhere in this module.

Used by both `AddressNormalizer` (to resolve a postal-code validation
country from libpostal's raw `country` component) and `CountryNormalizer`
(the field-level §33 adapter) — one resolver, not two independently
drifting implementations.
"""

from __future__ import annotations

import pycountry

_KNOWN_NON_ISO_ALIASES: dict[str, str] = {
    "uk": "GB",
    "great britain": "GB",
}


def resolve_country_alpha2(raw: str) -> str | None:
    """Best-effort resolution of a raw country string (code, name, or
    common alias) to its ISO 3166-1 alpha-2 code. Returns None if no
    confident match is found — callers must treat that as "unresolved,"
    never guess further (§33's own country-vs-alias caution applies
    equally to normalization inputs, not just outputs)."""
    candidate = raw.strip()
    if not candidate:
        return None

    alias = _KNOWN_NON_ISO_ALIASES.get(candidate.casefold())
    if alias is not None:
        return alias

    try:
        country = pycountry.countries.lookup(candidate)
    except LookupError:
        # Dotted abbreviations ("U.S.", "U.S.A.") fail pycountry's lookup
        # outright even though the un-dotted form ("US", "USA") resolves
        # fine — found empirically in M4 against §33's own "U.S." example.
        # Retried once, not looped, so this never masks a genuinely
        # unresolvable value behind silent extra attempts.
        dotless = candidate.replace(".", "")
        if dotless == candidate:
            return None
        try:
            country = pycountry.countries.lookup(dotless)
        except LookupError:
            return None
    return str(country.alpha_2)
