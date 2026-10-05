# Vendored OpenLineage specification (Apache License 2.0)

These JSON Schema files are copied unmodified from the OpenLineage project
(https://github.com/OpenLineage/OpenLineage, `spec/`), served at
https://openlineage.io/spec/. They are used only by
`tests/unit/test_lineage_d3_acceptance.py` to validate the lineage events
the engine emits.

- Pinned core spec: **2-0-2** (`OpenLineage-2-0-2.json`, `$id` https://openlineage.io/spec/2-0-2/OpenLineage.json)
- Pinned facet specs: the file names in `facets/` carry each facet's version
  (e.g. ColumnLineageDatasetFacet 1-2-0). Fetched 2026-10-05.
- License: Apache License, Version 2.0, copy in `LICENSE`. Copyright The
  OpenLineage Authors. The files are not modified, so no change notice applies.

To move to a newer spec, replace the files, keep this notice, and update the
pinned version in the test (`SPEC_VERSION`).
