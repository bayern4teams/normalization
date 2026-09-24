"""Native destination column types, and the pre-insert cast that makes
them safe.

Every semantic type maps to TEXT by default, and that is deliberate (see
the long note on `SEMANTIC_TYPE_TO_PG_TYPE`): decision #8 puts a failed
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
_TRUE = "true"
_FALSE = "false"


def sql_type(semantic_type: str, engine: str) -> str | None:
    """The native column type for this semantic type, or None when it
    should stay text (which is every type not listed above)."""
    return _ENGINE_TYPES.get(engine, {}).get(semantic_type)


def is_typed(semantic_type: str) -> bool:
    return semantic_type in _PG_TYPES


def coerce(semantic_type: str, value: object) -> tuple[object | None, str | None]:
    """Cast a normalized `display` value for a natively-typed column.

    Returns `(cast_value, error)`. On failure the value is None and the
    caller writes NULL plus an error-report row — never a raw string into
    a typed column, and never an exception that would abort the chunk.
    """
    if value is None:
        return None, None

    text = str(value).strip()
    if not text:
        return None, None

    if semantic_type == "BOOLEAN":
        return _coerce_boolean(text)
    if semantic_type in _DECIMAL_TYPES:
        return _coerce_decimal(text)
    return value, None


def _coerce_boolean(text: str) -> tuple[object | None, str | None]:
    if text == _TRUE:
        return True, None
    if text == _FALSE:
        return False, None
    return None, f"value {text!r} is not a boolean; stored as NULL"


def _coerce_decimal(text: str) -> tuple[object | None, str | None]:
    try:
        number = decimal.Decimal(text)
    except (decimal.InvalidOperation, ValueError):
        return None, f"value {text!r} is not a number; stored as NULL"
    # NaN and +/-Infinity are valid Decimals and valid Postgres NUMERIC,
    # but they poison SUM/AVG — the whole reason for typing this column —
    # and ClickHouse Decimal rejects them outright.
    if not number.is_finite():
        return None, f"value {text!r} is not a finite number; stored as NULL"
    return number, None
