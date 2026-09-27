"""Shared postal-code format validation — Source.txt §32.

Extracted from `AddressNormalizer`'s originally address-only postcode
check so `PostcodeNormalizer` (a standalone POSTCODE-typed field, e.g. a
dataset's own "zip_code" column, distinct from a postcode embedded
inside a full address string) can validate against the exact same real
`google-i18n-address` regex rules rather than a second, independently-
drifting implementation.
"""

from __future__ import annotations

from typing import Any

import i18naddress
import pycountry


def validate_postcode_format(postcode: str, country_alpha2: str) -> bool | None:
    """None means "no validation rule available for this country" (not a
    failure) — callers must not treat that as invalid. `country_alpha2`
    must already be resolved (see `country_codes.resolve_country_alpha2`)."""
    try:
        rules = i18naddress.get_validation_rules({"country_code": country_alpha2})
    except ValueError:
        return None
    if not rules.postal_code_matchers:
        return None
    # google-i18n-address's postal-code regex patterns are uppercase
    # (matching ValidationRules.upper_fields including "postal_code") —
    # found empirically in M4: lowercase input (as libpostal always
    # produces) silently failed every real postcode regardless of actual
    # correctness until this uppercase step was added.
    normalized = postcode.strip().upper()
    return any(matcher.match(normalized) for matcher in rules.postal_code_matchers)


# Every country google-i18n-address has postcode rules for, built once. 178
# of ~250 have any, and the scan below is O(that) per value — measured at
# 41us per distinct postcode, so ~6s for the 149,261 distinct postcodes of
# a real 1.76M-row table.
def _all_postcode_matchers() -> dict[str, tuple[Any, ...]]:
    matchers: dict[str, tuple[Any, ...]] = {}
    for country in pycountry.countries:
        try:
            rules = i18naddress.get_validation_rules({"country_code": country.alpha_2})
        except ValueError:
            continue
        if rules.postal_code_matchers:
            matchers[country.alpha_2] = tuple(rules.postal_code_matchers)
    return matchers


_POSTCODE_MATCHERS_BY_COUNTRY = _all_postcode_matchers()


def country_from_postcode_format(postcode: str) -> str | None:
    """The one country whose postcode format this value fits, or None.

    The inverse of `validate_postcode_format`, and deliberately far
    stricter: it answers only when EXACTLY ONE country accepts the value.
    A unique match is a determination, not a pick — which is the only way
    a postcode may be used as a country signal here.

    Measured on 20,000 distinct real postcodes: 18.9% match exactly one
    country (alphanumeric GB/CA forms, hyphenated PL forms), 0.8% match
    none, and 65.8% match 56 or 57 countries because a bare five-digit
    number is a valid postcode almost everywhere. Those return None, which
    is the honest answer rather than the most populous candidate.
    """
    normalized = postcode.strip().upper()
    if not normalized:
        return None
    found: str | None = None
    for country, matchers in _POSTCODE_MATCHERS_BY_COUNTRY.items():
        if any(matcher.match(normalized) for matcher in matchers):
            if found is not None:
                return None
            found = country
    return found
