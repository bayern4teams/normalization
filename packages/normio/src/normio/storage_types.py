"""Native destination column types, and the pre-insert cast that makes
them safe.

A semantic type not listed here maps to TEXT, and that is deliberate:
decision #8 puts a failed
value's ORIGINAL raw string in the cell, and a DATE/NUMERIC column
rejects exactly the malformed strings decision #8 exists to carry — the
DB rejects the whole chunk, taking the job down with it, before the
error-report row can even be written.

That note names its own precondition for lifting the restriction: "real
pre-insert type validation/casting (route a value that won't cast
through the same error-report path as a normalization failure, instead
of relying on the DB to reject it)". `coerce` is that. A value that will
not cast becomes NULL and an error-report row, which is the same outcome
a normalization failure already gets, so the chunk always inserts.

Only three semantic types are typed natively, because only they have a
scalar SQL equivalent that every well-formed value fits:

- NUMERIC / MONEY -> exact decimal. Never a float: binary floats cannot
  represent 0.1, and summing money in float drifts.
- BOOLEAN -> boolean.

DATE and DATETIME are deliberately NOT here. They normalize to EDTF-style
partial values ("1990", "1990-03") when that is all the source knew, and
a SQL DATE column cannot hold a partial date — typing them would turn
every year-only date into NULL, which is precisely the precision loss the
date normalizer exists to prevent.
"""

from __future__ import annotations

import decimal
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# MONEY is NUMERIC(38,4): ISO 4217 minor units go to 4 (CLF, the Chilean
# Unidad de Fomento), so 4 is the smallest scale that loses no currency.
_PG_TYPES: Mapping[str, str] = {
    "NUMERIC": "NUMERIC",
    "MONEY": "NUMERIC(38,4)",
    "BOOLEAN": "BOOLEAN",
}

# Bare types: ClickHouse's create_table wraps every column in Nullable().
#
# The two engines do NOT have the same numeric ceiling, and the same
# source column can therefore round differently depending on which one it
# is cloned to. Postgres NUMERIC without a precision is unbounded (up to
# 131072 digits before the point, 16383 after); ClickHouse has no
# unbounded decimal, so NUMERIC pins Decimal(38,9) — 38 significant
# digits, 9 after the point. A value needing more than 9 decimal places
# (a unit price at 12dp, a scientific measurement), or more integer digits
# than the 29 that Decimal(38,9) leaves, fails the cast gate on ClickHouse
# and lands as NULL plus an error row while Postgres stores it exactly
# (`coerce` checks the target column, ADR-020). Nothing is ever rounded or
# truncated to fit. MONEY is (38,4) on both, so it is identical across
# engines by construction.
#
# ponytail: 38,9 is ClickHouse's widest Decimal that still fits its
# 128-bit backing type. Decimal256 goes to 76 digits if a real column
# ever needs it — at roughly double the storage and slower arithmetic,
# which is not worth paying for every numeric column on the chance one
# needs it.
_CH_TYPES: Mapping[str, str] = {
    "NUMERIC": "Decimal(38,9)",
    "MONEY": "Decimal(38,4)",
    "BOOLEAN": "Bool",
}

_ENGINE_TYPES: Mapping[str, Mapping[str, str]] = {
    "postgres": _PG_TYPES,
    "clickhouse": _CH_TYPES,
}

_DECIMAL_TYPES = frozenset({"NUMERIC", "MONEY"})
_PRECISION_SCALE = re.compile(r"\((\d+),\s*(\d+)\)")
# PostgreSQL's documented NUMERIC ceilings: a finite Decimal past either
# still aborts the INSERT, typmod or not.
# ponytail: "up to 131072 digits before the decimal point" (PG docs, 8.1.2);
# moved into the column map if Postgres ever raises it.
_PG_UNBOUNDED_INTEGER_DIGITS = 131072
# ponytail: "up to 16383 digits after the decimal point" (PG docs, 8.1.2).
_PG_MAX_FRACTION_DIGITS = 16383
_TRUE = "true"
_FALSE = "false"


def sql_type(semantic_type: str, engine: str) -> str | None:
    """The native column type for this semantic type, or None when it
    should stay text (which is every type not listed above)."""
    return _ENGINE_TYPES.get(engine, {}).get(semantic_type)


def is_typed(semantic_type: str) -> bool:
    return semantic_type in _PG_TYPES


def coerce(
    semantic_type: str, value: object, engine: str = "postgres"
) -> tuple[object | None, str | None]:
    """Cast a normalized `display` value for a natively-typed column of
    this engine.

    Returns `(cast_value, error)`. On failure the value is None and the
    caller writes NULL plus an error-report row — never a raw string into
    a typed column, never a number wider than the column (the INSERT
    would abort the chunk), and never an exception.
    """
    if value is None:
        return None, None

    try:
        text = str(value).strip()
    except ValueError:  # an int past the str() digit limit
        return None, "value is too long to read as a number; stored as NULL"
    if not text:
        return None, None

    if semantic_type == "BOOLEAN":
        return _coerce_boolean(text)
    if semantic_type in _DECIMAL_TYPES:
        return _coerce_decimal(text, sql_type(semantic_type, engine) or "", engine)
    return value, None


def _coerce_boolean(text: str) -> tuple[object | None, str | None]:
    if text == _TRUE:
        return True, None
    if text == _FALSE:
        return False, None
    return None, f"value {text!r} is not a boolean; stored as NULL"


def _coerce_decimal(text: str, column_type: str, engine: str) -> tuple[object | None, str | None]:
    try:
        number = decimal.Decimal(text)
    except (decimal.InvalidOperation, ValueError):
        return None, f"value {text!r} is not a number; stored as NULL"
    # NaN and +/-Infinity are valid Decimals and valid Postgres NUMERIC,
    # but they poison SUM/AVG — the whole reason for typing this column —
    # and ClickHouse Decimal rejects them outright.
    if not number.is_finite():
        return None, f"value {text!r} is not a finite number; stored as NULL"
    # Postgres parses the literal before the typmod rounds it, so even
    # `0e-16384` into NUMERIC(38,4) overflows.
    exponent = number.as_tuple().exponent
    too_fine = (
        engine == "postgres" and isinstance(exponent, int) and exponent < -_PG_MAX_FRACTION_DIGITS
    )
    if too_fine or not _fits(number, column_type):
        return None, f"value {text!r} does not fit {column_type}; stored as NULL"
    return number, None


def _fits(number: decimal.Decimal, column_type: str) -> bool:
    """Whether the column holds `number` EXACTLY. A value with more
    fraction digits than the scale is refused rather than left to the
    database, because the engines disagree about what to do with it:
    Postgres rounds half-up and ClickHouse truncates (measured live,
    `12.34565` -> `12.3457` vs `12.3456`, and `0.00005` -> `0.0001` vs `0`),
    and either way the stored number is not the source's. Trailing zeros
    past the scale are not a loss and fit. The value itself is returned
    unchanged: nothing here rounds, nothing here invents precision."""
    if number.is_zero():
        return True  # `0e999` has a huge exponent and no integer digit
    match = _PRECISION_SCALE.search(column_type)
    if match is None:
        return number.adjusted() < _PG_UNBOUNDED_INTEGER_DIGITS
    precision, scale = int(match[1]), int(match[2])
    if number.adjusted() >= precision - scale:
        return False
    # Exact at the scale: every digit past it is zero. Read off the digit
    # tuple, so no Decimal context (and no context precision) is involved.
    _, digits, exponent = number.as_tuple()
    excess = -int(exponent) - scale
    return excess <= 0 or not any(digits[-excess:])
