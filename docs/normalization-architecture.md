# Normalization Engine Architecture (moved)

The architecture now lives in two files, each owning its topics:

- [ARCHITECTURE.md](../ARCHITECTURE.md): system context, deployment, data
  flow, clone workflow, data contract, guarantees, security, performance.
- [TECHNICAL_IMPLEMENTATION.md](../TECHNICAL_IMPLEMENTATION.md): package map,
  the `Normalizer` interface, module rules, algorithms, tests and CI.

This file stays as the target of the `Source.txt` §126 mapping in
[traceability-matrix.md](traceability-matrix.md). Per-domain rationale is in
[docs/adr/](adr/). The earlier text of this file, written at M0 and extended
for the clone feature, is in the git history before the commit that moved it.

The first version said the engine writes a Parquet and DuckDB sidecar store
for normalized output. The API and the clone path do not use the sidecar store
today; see [ARCHITECTURE.md](../ARCHITECTURE.md).
