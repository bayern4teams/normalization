"""The `system.tables.sorting_key` parser, shared by the source
connector (which reports a table's key) and the destination connector
(which compares an existing table's key to the plan's). It lives here
rather than in either connector because those two modules import each
other already (`quote_identifier`), and a second cross-edge in the
other direction would be a genuine cycle."""

from __future__ import annotations

import contextlib


def _split_top_level(text: str) -> list[str]:
    """`text` cut at commas outside quotes and brackets; ValueError if unbalanced."""
    parts, start, depth, quote, i = [], 0, 0, "", 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == "\\":
                i += 1
            elif char == quote:
                quote = ""
        elif char in "`'\"":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
        if depth < 0:
            break
        i += 1
    if depth or quote:
        msg = f"Cannot parse sorting_key {text!r}: unbalanced quotes or brackets"
        raise ValueError(msg)
    parts.append(text[start:].strip())
    return parts


def split_sorting_key(text: str) -> list[str]:
    """The elements of `system.tables.sorting_key`, parsed by its syntax.

    26.8.2.7 reports `ORDER BY (id)` as `(id)` and `ORDER BY (a, b)` as
    `a, b`, so one outer pair of brackets is optional. `tuple()` means no key.
    """
    text = text.strip()
    if text in ("", "tuple()"):
        return []
    parts = _split_top_level(text)
    if len(parts) == 1 and text[0] == "(" and text[-1] == ")":
        with contextlib.suppress(ValueError):  # `(a) + (b)` is not one outer pair
            return _split_top_level(text[1:-1])
    return parts
