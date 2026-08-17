# ADR-013: Normalization Storage Strategy

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §8 and §105–§107 mandate that source systems are never mutated
— normalization must operate read-only, sidecar, staging, or derived-view
style — and that the logical distinction between original, display,
comparison, search, ascii, and structured views is preserved even if exact
physical column names differ from the spec's illustrative examples.

The project must support five source types (PostgreSQL, MySQL, MongoDB,
ClickHouse, flat files) with fundamentally different native storage models
(row-relational, document, columnar-analytical, flat), while producing one
consistent output contract.

## Decision

- **Sources are read-only, always.** Every connector opens sessions with
  read-only credentials; integration tests assert that a deliberate write
  attempt against each connector fails. No connector implementation may
  expose a write path, even an unused one — this is enforced at the
  interface level (`SourceConnector` has no `write`/`update`/`delete`
  method at all, not merely an unimplemented one).
- **Output is a sidecar store**: Arrow-backed Parquet datasets, partitioned
  by `(source_id, table, run_id)`, cataloged in DuckDB. Each normalized
  field becomes one Arrow **struct column**
  (`first_name__nrm: STRUCT<original, display, comparison, search, ascii,
  structured, status, validation_status, confidence, flags, warnings,
  trace, lossiness, profile_version, env_id>`), keyed to `source_row_key`.
  This satisfies §106's logical-distinction requirement without forcing
  the spec's illustrative flat column names.
- **Metadata (profiles, runs, dictionaries, collisions, impact reports,
  sign-off records) lives in PostgreSQL** — relational, transactional,
  well-suited to versioned/audited entities, distinct from the bulk
  columnar normalized-value data.
- **Source connectors normalize to a common intermediate shape** before
  the sidecar write: every connector (SQL, document, columnar, file)
  produces an Arrow RecordBatch stream with a stable `source_row_key`,
  regardless of the source's native model. MongoDB's nested/semi-structured
  documents are flattened at the connector boundary using a documented,
  reversible key-path convention (`address.city` → column
  `address__city`), never silently dropped.
- **No physical mutation path exists anywhere in the codebase** for source
  systems — verified by a CI grep/AST check that no connector module
  imports a write-capable driver method against a source DSN.

## Consequences

- The struct-column design means downstream consumers (Data Discovery
  Engine) get one Arrow schema per normalized field that already carries
  the full multi-view contract — no separate join required to reassemble
  original + display + comparison.
- MongoDB flattening is a lossy-in-shape (not lossy-in-value) operation
  that must itself be traced and documented — the flattening convention is
  part of `docs/normalization-data-contract.md`, and round-trippable back
  to nested form is a stated design goal, not a hard guarantee.
- ClickHouse and DuckDB both being columnar simplifies the ClickHouse
  connector (native Arrow-friendly bulk export) relative to the
  row-oriented PostgreSQL/MySQL connectors.

## Revisit triggers

- A source system requires genuinely bidirectional sync in a later phase
  of the platform (explicitly out of scope for this project; would require
  a new ADR and almost certainly a new component, not a change to this one).
- MongoDB flattening convention proves lossy in practice for a real nested
  schema — extend the convention, document the extension, and add golden
  cases before the ambiguity causes a downstream misinterpretation.
