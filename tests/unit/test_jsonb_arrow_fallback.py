"""jsonb values must reach the destination as JSON, not as Python repr.

Found live: a clone of a `company` table with a `jsonb aliases` column
died on its first chunk with `invalid input syntax for type json`
(InvalidTextRepresentation) — the withheld-message job error the user
sees for it names nothing, because the insert itself failed, not a
value normalization. psycopg returns jsonb as parsed `dict`/`list`;
when Arrow cannot unify the column's shapes (null + array + object in
one column — the common case for a real-world optional jsonb), the
fallback printed `str(dict)`: single quotes, `True` — which is Python,
not JSON, and Postgres rejects for a jsonb column. Reproduced against
a live Postgres 16: `INSERT ... VALUES ('[''A'', ''B'']')` ->
`invalid input syntax for type json`.
"""

from __future__ import annotations

import json
import uuid

import pyarrow as pa
from normio.connectors._sql_base import _to_arrow


def test_mixed_shape_jsonb_column_falls_back_to_text() -> None:
    # The exact shape that made Arrow refuse the column: null, array, object.
    values = [None, ["A", "B"], {"other": True}]
    try:
        pa.array(values)
    except (pa.ArrowInvalid, pa.ArrowTypeError):
        pass  # pre-condition: this is what routes the column to the fallback
    else:  # pragma: no cover — only a pyarrow change could get here
        raise AssertionError("unified: this shape no longer exercises the fallback")
    array = _to_arrow(values)
    assert array.tolist() == [None, '["A", "B"]', '{"other": true}']


def test_every_fallback_text_for_containers_parses_as_json() -> None:
    values = [
        None,
        {"k": [1, 2], "t": True, "f": False, "n": None},
        {"unicode": "موبین"},
        [{"nested": 1}, 2.5, "text"],
    ]
    for text in _to_arrow(values).tolist():
        if text is not None:
            json.loads(text)  # must not raise


def test_non_container_fallbacks_keep_str() -> None:
    # uuid/inet/ranges rely on str() being the source's own rendering
    # (uuid.UUID was the reason the fallback exists at all).
    u = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert _to_arrow([None, u]).tolist() == [None, str(u)]


def test_unified_jsonb_column_is_untouched_by_the_fallback() -> None:
    # A column Arrow CAN type (all-objects) keeps Arrow's native struct:
    # the fix must not turn working columns into strings.
    array = _to_arrow([{"a": 1}, {"a": 2}])
    assert not pa.types.is_string(array.type) and not pa.types.is_large_string(array.type)
