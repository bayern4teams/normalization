"""PART1 D3.3: Marquez stored the column-lineage facet but its graph and UI
stayed empty, because the events carried no `schema` dataset facet: Marquez
builds a dataset's fields from that facet, and column lineage only links
fields it knows. Every input and output now carries one (OpenLineage
SchemaDatasetFacet 1-2-0). Uses the D3 acceptance harness; fails on main.
"""

from __future__ import annotations

from typing import Any

# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
import pytest
from tests.unit.test_lineage_d3_acceptance import (  # noqa: F401 - fixtures
    COLUMNS,
    FACET_PREFIX,
    TABLE_A,
    TABLE_B,
    _Env,
    _secret_key,
    _Spec,
    assert_valid,
    env,
    facets_of,
    spec,
)

pytestmark = pytest.mark.unit


def _schema_names(dataset: dict[str, Any]) -> list[str]:
    return [f["name"] for f in facets_of(dataset)["schema"]["fields"]]


# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
def test_inputs_and_outputs_carry_their_fields(env: _Env, spec: _Spec) -> None:  # noqa: F811
    job_id = env.new_job()
    env.run(job_id)
    events = env.lineage(job_id)
    assert events
    for event in events:
        table = TABLE_A if event["job"]["name"].endswith(TABLE_A) else TABLE_B
        (source,) = event["inputs"]
        (output,) = event["outputs"]
        assert _schema_names(source) == COLUMNS[table]
        lineage = facets_of(output)["columnLineage"]["fields"]
        # every column the lineage facet names is a field of the output
        assert set(lineage) <= set(_schema_names(output))
        assert set(COLUMNS[table]) <= set(_schema_names(output))
        facet = facets_of(source)["schema"]
        assert facet["_schemaURL"] == f"{FACET_PREFIX}1-2-0/SchemaDatasetFacet.json"
        assert {f.get("type") for f in facet["fields"]} == {"text"}
        # untyped fields are stored once per event by Marquez (found live)
        assert all(f.get("type") for f in facets_of(output)["schema"]["fields"])
    assert_valid(spec, events)


# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
def test_input_fields_name_the_dataset_not_its_facets(env: _Env) -> None:  # noqa: F811
    job_id = env.new_job()
    env.run(job_id)
    for event in env.lineage(job_id):
        for column in facets_of(event["outputs"][0])["columnLineage"]["fields"].values():
            for field in column["inputFields"]:
                assert "facets" not in field
