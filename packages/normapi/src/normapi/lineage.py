"""OpenLineage run events at clone-job boundaries (D3).

One run per (clone job, table): `START` before the table is read, then
`COMPLETE` once it is checkpointed as done, or `FAIL`. The output dataset
carries a `columnLineage` facet mapping every destination column, the
`_currency`/`_code` companions included, to the source column it came from
and to what was applied to it (normalizer, semantic type, profile version).

Events are plain dicts (no `openlineage-python` dependency), stored in the
metadata database first (audit, Q13) and then, only if
`NORM_OPENLINEAGE_URL` is set, POSTed there. Forwarding is best effort: it
never fails the job.

Nothing secret goes in: a dataset namespace is `engine://host:port`, never
the username or password, and a `FAIL` carries no message (an exception
text can echo a DSN; the job's own `error` field already holds it).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from normapi.pg_persistence import PgPersistence
    from normcore import FieldSemanticType, NormalizationProfile, NormalizerRegistry

logger = logging.getLogger(__name__)

_SPEC_VERSION = "2-0-2"
_SCHEMA_URL = f"https://openlineage.io/spec/{_SPEC_VERSION}/OpenLineage.json#/$defs/RunEvent"
_COLUMN_LINEAGE_URL = "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json"
_PRODUCER = "https://github.com/bayern4teams/normalization"
_JOB_NAMESPACE = "normalization"
# ponytail: a fixed 5 s per POST, so a hanging collector delays a table by
# at most two timeouts. Make it configurable if a real collector needs more.
_FORWARD_TIMEOUT_SECONDS = 5
FORWARD_URL_ENV = "NORM_OPENLINEAGE_URL"


def _dataset(
    connection: Mapping[str, Any], database: str, schema: str | None, table: str
) -> dict[str, str]:
    # Only engine, host and port: a connection also holds the username and
    # the encrypted password, and neither belongs in an event.
    namespace = f"{connection['engine']}://{connection['host']}:{connection['port']}"
    return {"namespace": namespace, "name": ".".join(p for p in (database, schema, table) if p)}


@dataclass
class TableRun:
    """The lineage of one table of one clone job. `emit` stores, then forwards."""

    persistence: PgPersistence
    job_id: str
    table: str
    source: dict[str, str]
    destination: dict[str, Any]
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def emit(self, event_type: str) -> None:
        event = {
            "eventType": event_type,
            "eventTime": dt.datetime.now(dt.UTC).isoformat(),
            "producer": _PRODUCER,
            "schemaURL": _SCHEMA_URL,
            "run": {"runId": self.run_id},
            "job": {"namespace": _JOB_NAMESPACE, "name": f"clone-job/{self.job_id}/{self.table}"},
            "inputs": [self.source],
            "outputs": [self.destination],
        }
        self.persistence.save_lineage_event(self.job_id, self.table, event)
        _forward(event)


def table_run(
    persistence: PgPersistence,
    *,
    job: Mapping[str, Any],
    job_id: str,
    table: str,
    source_connection: Mapping[str, Any],
    destination_connection: Mapping[str, Any],
    source_columns: list[str],
    semantic_types: Mapping[str, FieldSemanticType],
    registry: NormalizerRegistry,
    profile: NormalizationProfile,
) -> TableRun:
    """A new run (a fresh `runId`: a resumed table is a new attempt) with its
    column lineage computed from the job's recorded plan, never from rows."""
    source = _dataset(source_connection, job["source_database"], job.get("source_schema"), table)
    destination: dict[str, Any] = _dataset(
        destination_connection, job["destination_database"], None, table
    )

    def entry(column: str) -> dict[str, Any]:
        semantic_type = semantic_types.get(column)
        transformation = (
            {
                "type": "DIRECT",
                "subtype": "TRANSFORMATION",
                "description": (
                    f"{registry.require(semantic_type).name} "
                    f"{semantic_type.value} profile_version {profile.version}"
                ),
            }
            if semantic_type is not None
            # Not configured: copied as is, and nothing is claimed about it.
            else {"type": "DIRECT", "subtype": "IDENTITY"}
        )
        return {"inputFields": [{**source, "field": column, "transformations": [transformation]}]}

    fields = {column: entry(column) for column in source_columns}
    plan = job.get("destination_plan", {}).get(table, {})
    for key in ("currency_columns", "code_columns"):
        for base, companion in plan.get(key, {}).items():
            fields[companion] = entry(base)
    destination["facets"] = {
        "columnLineage": {
            "_producer": _PRODUCER,
            "_schemaURL": _COLUMN_LINEAGE_URL,
            "fields": fields,
        }
    }
    return TableRun(persistence, job_id, table, source, destination)


def _forward(event: dict[str, Any]) -> None:
    url = os.environ.get(FORWARD_URL_ENV)
    if not url:
        return
    if not url.startswith(("http://", "https://")):
        logger.warning("%s is not an http(s) URL; lineage not forwarded", FORWARD_URL_ENV)
        return
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(event).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_FORWARD_TIMEOUT_SECONDS):
            pass
    # Anything at all, malformed URL included: forwarding never fails the job.
    except Exception as exc:
        logger.warning("lineage forwarding failed: %s", type(exc).__name__)
