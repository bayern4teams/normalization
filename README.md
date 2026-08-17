# Normalization Engine

Data Normalization & Standardization Engine for the Entity Resolution platform.

Sits **before** the Data Discovery & Entity Context Engine, and long before Splink:

```
RAW USER DATABASES → NORMALIZATION ENGINE (this repo) → DATA DISCOVERY → ENTITY-SCOPED CANONICAL DATASET → SPLINK
```

This repository implements normalization only. It does not implement schema discovery,
key discovery, entity extraction, canonical dataset construction, or Splink.

## Status

Milestone **M0 — Research, evaluation, and decisions** in progress. See:

- [`docs/normalization-architecture.md`](docs/normalization-architecture.md) — system design
- [`docs/normalization-tool-evaluation.md`](docs/normalization-tool-evaluation.md) — library evaluation matrix
- [`docs/dependency-inventory.md`](docs/dependency-inventory.md) — license-audited dependency list
- [`docs/adr/`](docs/adr/) — architecture decision records
- [`docs/traceability-matrix.md`](docs/traceability-matrix.md) — spec section → implementation mapping
- [`docs/verification/`](docs/verification/) — signed milestone gate packs

The full implementation plan (8 gated milestones, 18 phases) lives in the planning
document that produced this repository; `docs/traceability-matrix.md` is the
canonical live mapping going forward.

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
