# Normalization Engine Architecture

Status: living document. Last updated: M0 (2026-08-17); §13
(DB-clone-and-normalize) added 2026-09-15 — §§1-12 still describe the
`Source.txt`-scoped M0-era system shape and were not re-audited for this
pass (that content is unaffected by §13's addition).

Satisfies `Source.txt` §126. This is the canonical description of the
system's shape; per-domain rationale lives in `docs/adr/`, and the
section-by-section requirement mapping lives in
`docs/traceability-matrix.md`.

## 1. Position in the platform

```
RAW USER DATABASES
        ↓
NORMALIZATION ENGINE        ← this repository
        ↓
DATA DISCOVERY / ENTITY CONTEXT ENGINE     (separate project, not built here)
        ↓
ENTITY-SCOPED CANONICAL DATASET
        ↓
SPLINK                                      (not built here)
```

This engine's job stops at producing normalized, traced, versioned
derivatives of raw values plus diagnostics useful to what comes next. It
performs no schema discovery, no key/relationship discovery, no entity
extraction, no graph construction, no canonical dataset construction, and no
record linkage. §112/§113 draw the line explicitly: normalization is not
entity resolution. A CI check (part of every gate from M1 onward) greps the
dependency tree and source tree for Splink and record-linkage primitives and
fails the build if any are found.

## 2. Design principle: five distinct value types, never collapsed

Per §0 and §2, every normalized field distinguishes:

1. **Raw value** (`original`) — byte-preserved, never overwritten.
2. **Repaired value** (`repaired`) — post encoding/mojibake repair, only
   populated when repair was evidence-gated and actually applied.
3. **Canonical semantic value** (`display`) — human-readable, safe
   canonical form.
4. **Search/comparison normalization** (`comparison`, `search`) — designed
   for equality/fuzzy matching and lookup respectively; deliberately lossy
   in ways `display` is not.
5. **Optional lossy/transliterated value** (`ascii`) — explicitly marked
   `LOSSY`, never substituted for the Unicode representation.
6. **Derived structured components** (`structured`) — parsed fields
   (name components, address components, phone components, etc).

No universal `normalize_string(value)` function exists anywhere in the
codebase (§100). The only entrypoint is:

```python
normalize(value, semantic_type, context, profile) -> NormalizedValue
```

## 3. Repository layout

```
normalization/
├── .github/workflows/         ci-fast.yml, ci-full.yml, gate.yml, drift.yml, release.yml
├── docs/
│   ├── normalization-architecture.md          (this file)
│   ├── normalization-tool-evaluation.md
│   ├── normalization-rules.md                 (populated from M2 onward)
│   ├── normalization-data-contract.md         (populated in M1)
│   ├── normalization-testing.md               (populated from M2 onward)
│   ├── normalization-performance.md           (populated in M8)
│   ├── dependency-inventory.md
│   ├── traceability-matrix.md
│   ├── adr/                                   ADR-001 … ADR-016
│   └── verification/                          M0 … M8 signed verification packs
├── packages/
│   ├── normcore/       domain model, contracts, enums, context, trace, env fingerprint
│   ├── normalizers/    the Normalizer adapters (§99)
│   ├── normdict/       versioned dictionary subsystem (§58, §59)
│   ├── normexec/       Polars/DuckDB batch engine, distinct-value planner, cache
│   ├── normio/         read-only source connectors + sidecar store writer;
│   │                   also write-capable destination connectors for the
│   │                   DB-clone-and-normalize feature (§13) — a
│   │                   deliberately separate class family, not part of
│   │                   the read-only `SourceConnector` Protocol
│   ├── normanalysis/   profiling, impact, collision, reversibility, A/B
│   ├── normapi/        FastAPI application (§98)
│   └── normcli/        batch/ops entrypoints, gate/pack generation
├── services/libpostal/  Dockerfile, batch HTTP wrapper, pinned+checksummed model data
├── ui/                  React + TypeScript + Vite (from M7)
├── data/dictionaries/   versioned, checksummed dictionary payloads
├── tests/                unit, golden, property, contract, integration, e2e, bench
├── scripts/              env_fingerprint.py, check_signoff.py, check_licenses.py, license_policy.toml
├── spikes/               throwaway scripts proving risky integrations (M0)
└── compose.yaml
```

## 4. Domain model (§7)

All models are Pydantic v2 in `normcore`, mirrored as Arrow schemas for
columnar storage and JSON Schema for the API/UI contract. Full field lists
are in `docs/normalization-data-contract.md` (M1 deliverable); the entity
list is:

`NormalizationProfile`, `NormalizationRule`, `NormalizationPipeline`,
`NormalizationStep`, `FieldNormalizationConfig`, `NormalizedValue`,
`NormalizationResult`, `NormalizationTrace`, `NormalizationVersion`,
`NormalizationRun`, `NormalizationError`, `NormalizationWarning`,
`FieldSemanticType`.

Enums: `NormalizationStatus` (§67), `MissingKind` (§54), `QualityFlag`
(§114), `ErrorPolicy` (§69), `Reversibility` (§80).

## 5. The `Normalizer` interface (§99–§101)

```python
class Normalizer(Protocol):
    name: str
    supported_types: frozenset[FieldSemanticType]

    def can_handle(self, field_type, ctx: NormalizationContext) -> bool: ...
    def normalize(self, value: str | None, ctx) -> NormalizationResult: ...
    def normalize_batch(self, values: pa.Array, ctx) -> pa.StructArray: ...
    def validate(self, value, ctx) -> ValidationResult: ...
    def explain(self, result) -> Explanation: ...
    def version(self) -> ComponentVersion: ...
    def steps(self) -> Sequence[StepSpec]: ...
    def inverse(self, step_id: str, value: str) -> str | None: ...
```

Fourteen-plus adapters, one per semantic domain (§99): `GenericTextNormalizer`,
`UnicodeNormalizer`, `NameNormalizer`, `CompanyNormalizer`,
`AddressNormalizer`, `PhoneNormalizer`, `EmailNormalizer`, `DateNormalizer`,
`CountryNormalizer`, `IdentifierNormalizer`, `NumericNormalizer`,
`CurrencyNormalizer`, `UnitNormalizer`, `URLNormalizer`, plus
`LanguageNormalizer`, `ScriptNormalizer`, `BooleanNormalizer`,
`MissingValueNormalizer`. Each is independently testable and registered in a
lookup keyed by `FieldSemanticType`.

`NormalizationContext` (§101) carries: `field_name, semantic_type, country,
locale, language, script, source, table, entity_type, project, user_profile,
dictionary_set, default_region, error_policy, pii_visibility`, and computes
`context_hash` for cache keying.

## 6. Selected stack

See `docs/normalization-tool-evaluation.md` for the full evaluation; summary
in `docs/dependency-inventory.md`. Per-domain rationale is in the
correspondingly-named ADR (`docs/adr/ADR-001` through `ADR-016`).

## 7. Storage strategy (§8, §105, §106) — see ADR-013

Sources are read-only, always — the `SourceConnector` Protocol exposes no
write path at the interface level. Output is a Parquet + DuckDB sidecar
store, one Arrow struct column per normalized field, keyed to
`source_row_key`. Metadata (profiles, runs, dictionaries, collisions,
sign-offs) lives in PostgreSQL.

(§13's DB-clone-and-normalize feature introduces a second, deliberately
separate write-capable connector family for clone *destinations* — this
does not weaken the guarantee above: an origin is always addressed
through `SourceConnector`, never through a destination writer, and origin
credentials are never reused for a destination.)

## 8. Reproducibility: the environment fingerprint (`env_id`) — see ADR-014

`env_id = blake3(canonical_json({packages, source_hashes, icu_version,
unicode_version, cldr_version, libpostal_model_sha256,
phonenumbers_metadata_version, dictionaries, profile_version}))`, computed
by `normexec.env_fingerprint` (CLI: `scripts/env_fingerprint.py`).
`source_hashes` digests our own normalizing packages, so a change to a
normalizer invalidates the cache it would otherwise silently bypass.
Stamped on every `NormalizedValue`, `NormalizationRun`, and cache key. Two
runs are comparable iff their `env_id` matches. A nightly CI job
(`drift.yml`) detects upstream drift before anyone deliberately upgrades.

## 9. Performance architecture — see ADR-016

Polars + DuckDB + Arrow/Parquet, single-node. **Distinct-value-first**
execution: extract the distinct value set per column, normalize only that
set, join back via Arrow dictionary encoding. Two-tier cache (in-process LRU
+ DuckDB-backed persistent), keyed on
`(blake3(raw), profile_version, semantic_type, context_hash, env_id)` — raw
values never appear in cache keys. Database pushdown restricted to provably
safe exact-match operations (sentinel/missing-value detection) only.

## 10. The 8-milestone gate model

Delivery proceeds through 8 gated milestones (M0–M8), each covering a subset
of the 18 implementation phases named in §127. Every gate requires three
layers to pass: automated CI checks, liveness verification against the
running stack, and a human-reviewed, signed verification pack. See the
implementation plan's Part C for the full gate specification and Part D for
the milestone-by-milestone phase breakdown; `docs/traceability-matrix.md`
maps every one of the 137 numbered sections in the original specification to
its milestone, phase, module, and test location.

## 11. CI/CD

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci-fast.yml` | every push | lint, types, unit + fast golden subset (<3 min) |
| `ci-full.yml` | every PR | full matrix: unit, golden, property, contract, coverage, license gate, audit, secret scan, compose integration (<25 min) |
| `gate.yml` | manual dispatch / `milestone/*` branch | sign-off precondition, full `ci-full` scope, benchmarks, determinism replay, mutation testing (M8+), E2E, SBOM, verification pack generation (<90 min) |
| `drift.yml` | nightly | re-resolve deps to latest, run golden corpus, diff against expectations, open an issue on any change |
| `release.yml` | tag `milestone/M*` | build/sign images, publish release with pack + SBOM + baseline |

## 12. Security and PII posture (§123)

Traces store `blake3` hashes plus character-class masks, not raw values, by
default. Raw previews require an explicit, role-gated, audited PII-visibility
grant and are never written to logs, metrics, or default trace output. This
is enforced by a dedicated PII-leak test at every gate from M1 onward.

## 13. DB-clone-and-normalize (post-M8, not part of `Source.txt`)

A separately-scoped feature wiring the previously-unwired `normio`
package (confirmed zero `IMPORTS` edges into `normapi` before this work)
into a real capability: point the app at a real origin database, clone
its schema to a new destination on the same server, then
stream+normalize+populate it. Full decision record: the approved plan's
"Decisions already made" and `docs/adr/ADR-017-clone-normalize-engine-scope.md`.
Live progress + verification evidence: `TODO.md` and
`docs/verification/clone-normalize-verification-pack.md`. Step-by-step
how-to (repo demo containers or your own real database):
`docs/clone-e2e-guide.md`.

Scope: **Postgres and ClickHouse only**, both as origin and destination,
always the same engine. MySQL/Mongo/File are documentation-only
(ADR-017) — deferred, not built, until explicitly approved to continue.

Shape, in brief:

- **Origin is always read-only** — addressed via the existing
  `SourceConnector`/`PostgresConnector`/`ClickHouseConnector`, never a
  destination writer, and never the same credential as the destination.
- **Destination writers** (`normio.connectors.postgres_destination.PostgresDestination`,
  `.clickhouse_destination.ClickHouseDestination`) are a new, deliberately
  separate class family — `database_exists`, `create_table` (empty-schema
  DDL, replicating the origin's primary key on Postgres / `ORDER BY`+
  engine on ClickHouse), `bulk_insert` (chunked, checkpoint-aligned).
- **Two-phase execution**: Phase 1 (`normapi.clone_executor.verify_and_create_schema`)
  creates every table in the origin database completely empty, only
  after the app has verified the user ran `CREATE DATABASE` by hand — the
  app never issues it itself, and never requires admin rights. Phase 2
  (`start_phase2`) streams+normalizes+populates on a background thread,
  reusing the existing `DistinctValuePlanner`/`Dispatcher`/cache — no
  second normalization call path.
- **Failure handling**: a failed value keeps its original raw value in
  the destination cell (never blank, never skipped — `ErrorPolicy.RETURN_ORIGINAL`,
  no new fallback logic needed), with a full-detail, paginated error
  report (`normalization_clone_job_errors`, `GET /clone-jobs/{id}/errors`).
- **Resumable**: a crashed/restarted job resumes from its last committed
  `source_row_key` checkpoint rather than redoing a whole table — proven
  live against a real 20,000-row table and a genuine `docker compose
  restart api` mid-run (see the verification pack's §3.6).
- **Credentials at rest**: encrypted via `normapi.secrets` (Fernet,
  `NORM_SECRET_KEY`), decrypted only in memory at connect-time.

New Postgres tables (`normapi.pg_persistence`, same single-JSONB-blob
convention as `normalization_runs`): `normalization_connections`,
`normalization_clone_jobs`, `normalization_clone_job_errors`. New UI
pages: `ConnectionsPage`, `CloneJobNewPage`, `CloneJobDetailPage` (nav:
Connections, Clone).
