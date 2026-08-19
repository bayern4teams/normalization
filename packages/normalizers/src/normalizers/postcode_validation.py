"""Shared postal-code format validation — Source.txt §32.

Extracted from `AddressNormalizer`'s originally address-only postcode
check so `PostcodeNormalizer` (a standalone POSTCODE-typed field, e.g. a
dataset's own "zip_code" column, distinct from a postcode embedded
inside a full address string) can validate against the exact same real
`google-i18n-address` regex rules rather than a second, independently-
drifting implementation.
"""

from __future__ import annotations

import i18naddress


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
