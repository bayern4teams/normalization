"""MongoConnector — Source.txt §105.

MongoDB is document-oriented; ADR-013's flattening convention applies
here: nested keys are joined with `__` (e.g. `{"address": {"city": "..."}}`
becomes column `address__city`), documented in
docs/normalization-data-contract.md. `_id` becomes `source_row_key`
directly (MongoDB already guarantees per-collection uniqueness for it).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyarrow as pa
from pymongo import MongoClient
from pymongo.read_preferences import ReadPreference

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


def _flatten(doc: dict[str, Any], *, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in doc.items():
        flat_key = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, prefix=f"{flat_key}__"))
        else:
            flat[flat_key] = value
    return flat


class MongoConnector:
    def __init__(self, source_id: str, uri: str, database: str) -> None:
        self.source_id = source_id
        # secondaryPreferred + a read-only-provisioned URI user together
        # are this connector's two independent enforcement layers, mirroring
        # the SQL connectors' approach (interface shape + DB-level grants).
        self._client: MongoClient[dict[str, Any]] = MongoClient(
            uri, read_preference=ReadPreference.SECONDARY_PREFERRED
        )
        self._db = self._client[database]

    def list_tables(self) -> Sequence[str]:
        return sorted(self._db.list_collection_names())

    def read_table(
        self,
        table: str,
        *,
        columns: Sequence[str] | None = None,
        batch_size: int = 100_000,
    ) -> Iterator[pa.RecordBatch]:
        collection = self._db[table]
        projection = dict.fromkeys(columns, 1) if columns else None
        cursor = collection.find({}, projection=projection, batch_size=batch_size)

        buffer: list[dict[str, Any]] = []
        row_offset = 0
        for doc in cursor:
            flat = _flatten(doc)
            flat["source_row_key"] = str(flat.pop("_id"))
            buffer.append(flat)
            if len(buffer) >= batch_size:
                yield _docs_to_batch(buffer)
                row_offset += len(buffer)
                buffer = []
        if buffer:
            yield _docs_to_batch(buffer)

    def close(self) -> None:
        self._client.close()


def _docs_to_batch(docs: list[dict[str, Any]]) -> pa.RecordBatch:
    all_keys: list[str] = []
    seen = set()
    for doc in docs:
        for key in doc:
            if key not in seen:
                seen.add(key)
                all_keys.append(key)

    columns_data: dict[str, list[Any]] = {key: [] for key in all_keys}
    for doc in docs:
        for key in all_keys:
            columns_data[key].append(doc.get(key))

    arrays = [pa.array(columns_data[key]) for key in all_keys]
    return pa.RecordBatch.from_arrays(arrays, names=all_keys)
