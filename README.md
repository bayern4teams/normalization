# Normalization Engine

Data Normalization & Standardization Engine for the Entity Resolution platform.

Sits **before** the Data Discovery & Entity Context Engine, and long before Splink:

```
RAW USER DATABASES → NORMALIZATION ENGINE (this repo) → DATA DISCOVERY → ENTITY-SCOPED CANONICAL DATASET → SPLINK
```

This repository implements normalization only. It does not implement schema discovery,
key discovery, entity extraction, canonical dataset construction, or Splink.

## Status

All 8 gated milestones (M0–M8) of the original `Source.txt` implementation
plan are complete — engine, dictionaries, batch execution, analysis, API,
and UI. See:

- [`docs/normalization-architecture.md`](docs/normalization-architecture.md) — system design
- [`docs/normalization-tool-evaluation.md`](docs/normalization-tool-evaluation.md) — library evaluation matrix
- [`docs/dependency-inventory.md`](docs/dependency-inventory.md) — license-audited dependency list
- [`docs/adr/`](docs/adr/) — architecture decision records
- [`docs/improvement-report.md`](docs/improvement-report.md) — verified defects D1-D12, research, architecture; implemented per [`docs/plans/DEFECTS_IMPLEMENTATION_PLAN.md`](docs/plans/DEFECTS_IMPLEMENTATION_PLAN.md)
- [`docs/traceability-matrix.md`](docs/traceability-matrix.md) — spec section → implementation mapping
- [`docs/verification/`](docs/verification/) — signed milestone gate packs

The full implementation plan (8 gated milestones, 18 phases) lives in the planning
document that produced this repository; `docs/traceability-matrix.md` is the
canonical live mapping going forward.

### DB-clone-and-normalize

A second, separately-scoped feature (not part of `Source.txt`, not in the
milestone/traceability system above): point the app at a real origin
database — Postgres or ClickHouse, strictly read-only, never modified —
and have it build a schema-cloned, normalized-in-place destination next
to it on the same server, driven from the UI (`Connections`/`Clone` nav
items), as a background/pollable job with crash-resume. No admin/`CREATE
DATABASE` rights are required by the app itself.

- [`docs/clone-e2e-guide.md`](docs/clone-e2e-guide.md) — step-by-step: run
  it against the repo's demo containers or your own real database
- [`docs/adr/ADR-017-clone-normalize-engine-scope.md`](docs/adr/ADR-017-clone-normalize-engine-scope.md) — why MySQL/Mongo/File are documentation-only for now
- [`docs/verification/clone-normalize-verification-pack.md`](docs/verification/clone-normalize-verification-pack.md) — evidence it works

Requires `NORM_SECRET_KEY` (see `.env.example`) to encrypt saved
connection passwords at rest.

## Development

Requires [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --all-extras
uv run ruff check .
uv run mypy packages
uv run pytest -m "unit or golden or property or contract"
```

```bash
docker compose up -d
docker compose ps
```

## Non-goals

- No schema/key/relationship discovery
- No entity extraction or graph construction
- No Splink, no probabilistic linkage, no record matching
- No mutation of source systems — this engine is strictly read-only against sources
