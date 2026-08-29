"""Shared postal-code format validation — Source.txt §32.

Extracted from `AddressNormalizer`'s originally address-only postcode
check so `PostcodeNormalizer` (a standalone POSTCODE-typed field, e.g. a
dataset's own "zip_code" column, distinct from a postcode embedded
inside a full address string) can validate against the exact same real
`google-i18n-address` regex rules rather than a second, independently-
drifting implementation.
"""

from __future__ import annotations

import functools
from typing import Any

import i18naddress


# Phase 1 (2026-08-29 throughput program): `i18naddress.get_validation_rules`
# has no memoization upstream — every call re-`open()`s and `json.load()`s
# country data from disk (twice: "zz" plus the country) and recompiles a
# regex. Measured 768.9 µs/call uncached vs. 0.186 µs cached — a 4,127x
# difference, hit once per value by both PostcodeNormalizer and
# AddressNormalizer._validate_postcode. Bounded by real country count
# (~254), so an unbounded-growth concern doesn't apply.
@functools.lru_cache(maxsize=256)
def _cached_validation_rules(country_alpha2: str) -> Any:
    return i18naddress.get_validation_rules({"country_code": country_alpha2})


def validate_postcode_format(postcode: str, country_alpha2: str) -> bool | None:
    """None means "no validation rule available for this country" (not a
    failure) — callers must not treat that as invalid. `country_alpha2`
    must already be resolved (see `country_codes.resolve_country_alpha2`)."""
    try:
        rules = _cached_validation_rules(country_alpha2)
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
