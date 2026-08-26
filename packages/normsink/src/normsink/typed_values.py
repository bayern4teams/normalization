"""The typed NUMERIC/DATE destination-column extraction contract —
M13-M22 program plan's M19 callout #1 ("Typed NUMERIC/DATE columns have
no contract... Recommend (a) [an explicit tested per-semantic-type
extraction contract from `structured`]. Decide before starting.").

Decided here: extract from `NormalizedValue.display`, not from
`structured`'s normalizer-internal keys. Verified live (reading
`packages/normalizers/src/normalizers/numeric.py` and `date.py`
directly): `NumericNormalizer` sets `display = str(decimal_value)` (the
same canonical value it also stashes in `structured["canonical_value"]`)
and `DateNormalizer` sets `display = iso_value` (the same value it
stashes in `structured["parsed_date"]`) on every success path.
`display` is the STABLE, cross-normalizer contract every `NormalizedValue`
already guarantees (part of the data contract's own JSON/Arrow schema
since M1), whereas `structured` keys are normalizer-internal and free to
change — extracting from `display` is simpler and does not couple this
package to another package's private implementation detail.

On a parse failure or a non-success `normalization_status` (AMBIGUOUS,
INVALID, FAILED, NEEDS_REVIEW), both extractors return `None` — the
destination column is written `NULL`, and the caller is expected to also
write a side-table row explaining why (never a silently-dropped value).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from normcore import NormalizationStatus, NormalizedValue

_SUCCESSFUL_STATUSES = frozenset(
    {
        NormalizationStatus.NORMALIZED,
        NormalizationStatus.REPAIRED,
        NormalizationStatus.PARSED,
        NormalizationStatus.UNCHANGED,
    }
)


def extract_numeric(result: NormalizedValue) -> Decimal | None:
    """`display` for a real `NumericNormalizer`/`CurrencyNormalizer`
    success is always a plain, locale-independent decimal string (e.g.
    `"1234.50"`) — `Decimal(display)` never needs locale handling here,
    unlike the normalizer's own parsing step."""
    if result.normalization_status not in _SUCCESSFUL_STATUSES or not result.display:
        return None
    try:
        return Decimal(result.display)
    except InvalidOperation:
        return None


def extract_date(result: NormalizedValue) -> date | None:
    """`display` for a real `DateNormalizer` success is always a plain
    ISO-8601 `YYYY-MM-DD` string."""
    if result.normalization_status not in _SUCCESSFUL_STATUSES or not result.display:
        return None
    try:
        return date.fromisoformat(result.display)
    except ValueError:
        return None
