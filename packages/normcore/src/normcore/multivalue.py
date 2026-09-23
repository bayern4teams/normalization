"""List-shaped values — one column, many values per cell.

Real sources put lists in text columns: `['a@b.com', 'c@d.com']` (a Python
repr that leaked out of an ETL step) and `["Organization", "Corporation"]`
(JSON). Handing the whole cell to
a single-value normalizer fails every row — a 35M-row source produced 4.3M
identical "invalid email" errors from exactly one such column, which says
nothing about the data and buries every real error.

This is deliberately conservative: a value only counts as a list when it is
delimited AND parses cleanly AND yields scalars. Prose that merely contains
a bracket is never split. Nothing here is specific to any source database
or column name — the shape of the value is the only signal used.
"""

from __future__ import annotations

import ast
import json

# ponytail: bracket-delimited only. Postgres `{a,b}` array literals would
# need their own escaping-aware parser; add one when a source actually
# ships them rather than guessing at the quoting rules now.
_DELIMITERS = (("[", "]"),)

_SCALAR_TYPES = (str, int, float, bool, type(None))


def split(value: str) -> tuple[list[str | None], str] | None:
    """`(elements, style)`, or None when `value` is not a list.

    `style` is fed back to `join` so the normalized value keeps the shape
    it arrived in — rewriting a Python repr as JSON (or vice versa) would
    be an unrequested change to data that was not the field's problem.
    """
    stripped = value.strip()
    if len(stripped) < 2:
        return None
    if not any(stripped.startswith(o) and stripped.endswith(c) for o, c in _DELIMITERS):
        return None

    for style, parse in (("json", json.loads), ("python", ast.literal_eval)):
        try:
            parsed = parse(stripped)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
        if not isinstance(parsed, (list, tuple, set)):
            continue
        elements = list(parsed)
        # An empty list is a real answer ('this cell holds no values'), not a
        # malformed one — rejecting it here would send `[]` to the single-value
        # normalizer, which can only call it invalid.
        if not all(isinstance(e, _SCALAR_TYPES) for e in elements):
            continue
        return [None if e is None else str(e) for e in elements], style

    return None


def join(elements: list[str | None], style: str) -> str:
    if style == "json":
        return json.dumps(elements, ensure_ascii=False)
    return repr([None if e is None else str(e) for e in elements])
