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

from normalizers import text_ops

_KNOWN_NON_ISO_ALIASES: dict[str, str] = {
    "uk": "GB",
    "great britain": "GB",
    # Everything below was found empirically, per this module's own rule,
    # in a real 1.76M-row CountryCode column: these are the values that
    # actually appeared and that pycountry 24.6.1 returns nothing for.
    # Trailing counts are rows in that column. Together they account for
    # ~95% of that column's 17,102 resolution failures; the rest of the
    # tail is genuinely not country data (postcodes, city names, "Oo").
    #
    # Most are ISO renames the old name no longer resolves under. Note
    # "Türkiye" with the diacritic ALREADY resolves, so it is deliberately
    # not listed — a dead alias is worse than none.
    "turkey": "TR",  # 14,707 — ISO renamed it Türkiye in 2022
    "turkiye": "TR",  # 5 — the new name, undiacriticked
    "macedonia, the former yugoslav republic of": "MK",  # 682 — renamed 2019
    "macedonia": "MK",  # 17
    "russia": "RU",  # 250 — only the formal "Russian Federation" resolves
    "us virgin islands": "VI",  # 198 (+54 as "U.S. Virgin Islands")
    "democratic republic of the congo": "CD",  # 136 — CD (Kinshasa), NOT CG (Brazzaville)
    "cape verde": "CV",  # 67 — renamed Cabo Verde
    "swaziland": "SZ",  # 63 — renamed Eswatini in 2018
    "the bahamas": "BS",  # 19
    "ivory coast": "CI",  # 11 — ISO lists only "Côte d'Ivoire"
    "bosnia and herzegowina": "BA",  # 9 — misspelling of Herzegovina
    # Deliberately absent: "Kosovo" (has no ISO 3166-1 code at all) and a
    # bare "Virgin Islands" (ambiguous — US is VI, British is VG).
}


def resolve_country_alpha2(raw: str) -> str | None:
    """Best-effort resolution of a raw country string (code, name, or
    common alias) to its ISO 3166-1 alpha-2 code. Returns None if no
    confident match is found — callers must treat that as "unresolved,"
    never guess further (§33's own country-vs-alias caution applies
    equally to normalization inputs, not just outputs).

    Each spelling variant is tried against the alias table first, then
    pycountry. The variants, and why each earns its place:

    - as written.
    - dots removed: "U.S." and "U.S.A." fail pycountry's lookup outright
      even though "US"/"USA" resolve fine (found empirically in M4
      against §33's own "U.S." example). This also lets one alias entry
      cover both "US Virgin Islands" and "U.S. Virgin Islands".
    - diacritics stripped: "Panamá", "México", "Perú", "Sénégal",
      "Israël" are the country's real name in its own language and
      resolve once the accents are folded. Found empirically in a real
      1.76M-row column. Folding here is a LOOKUP KEY only — it never
      touches the value a caller sees, so §15's prohibition on universal
      accent stripping is not in play.

    A loop over variants rather than nested try/except: each new variant
    was otherwise another level of nesting, and the three are tried by
    exactly the same rules.
    """
    candidate = raw.strip()
    if not candidate:
        return None

    deaccented, _ = text_ops.strip_diacritics(candidate)
    seen: set[str] = set()
    for variant in (candidate, candidate.replace(".", ""), deaccented):
        if not variant or variant in seen:
            continue
        seen.add(variant)
        alias = _KNOWN_NON_ISO_ALIASES.get(variant.casefold())
        if alias is not None:
            return alias
        try:
            return str(pycountry.countries.lookup(variant).alpha_2)
        except LookupError:
            continue
    return None
