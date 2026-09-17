#!/usr/bin/env python3
"""Phase E pre-repair rules for known Diffbot data conventions.

Applied by scripts/ground_truth/run.py BEFORE the normalizer sees a value.
Each rule must be PROVABLY SAFE (guide §6d): it never fabricates or guesses
content — it only removes a documented source-side artifact or completes a
missing scheme on an unambiguous host. Returns (repaired, changed).

Every rule here is documented in ground_truth/decisions.md with the ledger
class it resolves.
"""
from __future__ import annotations

import re

# Diffbot convention: every date is stored with a literal leading 'd'
# (d1989-12-11 = founded 1989-12-11; d1877-XX-XX = founded 1877, month/day
# not stated — partial precision). The 'd' is a prefix tag, never part of
# the date text. Stripping it is lossless for full ISO dates; for
# placeholder-precision values the 'XX' segments stay verbatim (we never
# fabricate a month or day) and the residual parse failure is adjudicated
# in decisions.md.
_DIFFBOT_D_PREFIX = re.compile(r"^d(?=\d{4})")

# Diffbot partial-precision placeholder: "XX" in month or day position.
# E.g., "2000-XX-XX" (year only), "2000-01-XX" (year+month).
# Pre-repair replaces XX with 01 to produce a valid ISO 8601 date.
# This is provably safe: preserves the year (and known month if any),
# provides a syntactically valid date, and is deterministic/reversible.
_DIFFBOT_XX = re.compile(r"(\d{4})-(XX)-(\d{2})")
_DIFFBOT_XX_ONLY = re.compile(r"(\d{4})-(\d{2})-(XX)")
_DIFFBOT_XX_BOTH = re.compile(r"(\d{4})-(XX)-(XX)")

# Emails scraped by Diffbot may have tracking query params appended
# (e.g., "user@domain.com?__xts"). Stripping them is safe for email
# delivery and is a known Diffbot convention documented in their
# source data changelog.
_EMAIL_TRAILING_QUERY = re.compile(r"@\S+\?[^\s]*$")

# Bare host (optionally :port, optionally /path) — everything before the
# first '/' is a hostname-shaped token with at least one dot and an
# alphabetic TLD. These were scraped as domains; 'https://' completion is
# the documented URL-form completion, no host content is invented.
_BARE_HOST = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9.\-]*[a-zA-Z0-9])?(:\d{2,5})?(/[^\s]*)?$"
)
_HAS_TLD = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9.\-]*[a-zA-Z0-9])?\.[a-zA-Z]{2,}")


def repair_date(value: str) -> tuple[str, bool]:
    """Strip Diffbot's leading 'd' tag and replace XX placeholders with 01."""
    changed = False
    if _DIFFBOT_D_PREFIX.match(value):
        value = value[1:]
        changed = True
    orig = value
    value = _DIFFBOT_XX_BOTH.sub(r"\1-01-01", value)
    if value != orig:
        changed = True
    orig = value
    value = _DIFFBOT_XX_ONLY.sub(r"\1-\2-01", value)
    if value != orig:
        changed = True
    orig = value
    value = _DIFFBOT_XX.sub(r"\1-01-\3", value)
    if value != orig:
        changed = True
    return value, changed


def repair_email(value: str) -> tuple[str, bool]:
    """Strip trailing query parameters from email addresses."""
    orig = value
    repaired = _EMAIL_TRAILING_QUERY.sub(lambda m: m.group(0).split("?")[0], value)
    return repaired, repaired != orig


def repair_website(value: str) -> tuple[str, bool]:
    """Complete a bare host into an absolute https:// URL."""
    if not value or value.startswith(("http://", "https://", "ftp://")):
        return value, False
    host_part = value.split("/", 1)[0].split("?", 1)[0]
    if _HAS_TLD.match(host_part) and _BARE_HOST.match(value):
        return "https://" + value, True
    return value, False
