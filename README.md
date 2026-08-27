# Normalization Engine

Data Normalization & Standardization Engine for the Entity Resolution platform.

Sits **before** the Data Discovery & Entity Context Engine, and long before Splink:

```
RAW USER DATABASES → NORMALIZATION ENGINE (this repo) → DATA DISCOVERY → ENTITY-SCOPED CANONICAL DATASET → SPLINK
```

This repository implements normalization only. It does not implement schema discovery,
key discovery, entity extraction, canonical dataset construction, or Splink.

## Status

M0 through M22 are complete — 20+ real semantic-domain normalizers, a connection
registry with encrypted credentials, real streaming multi-column runs against
million-row+ sources, a destination writer, incremental sync, and a 3-step
product UI (Connect / Explore / Report), all wired to a live API. See:

- [`docs/traceability-matrix.md`](docs/traceability-matrix.md) — spec section → implementation mapping
- [`docs/verification/`](docs/verification/) — every milestone's gate pack (Layer 1/2 evidence; Layer 3 human sign-off is left blank by design until reviewed)
- [`docs/plan/M13-M22-program-plan.md`](docs/plan/M13-M22-program-plan.md) — the product-pipeline program that produced the current UI
- [`docs/adr/`](docs/adr/) — architecture decision records

## Quick start (Docker — the one command)

**Requirements:** Docker Desktop (or another Docker + Compose v2 engine).

```bash
cp .env.example .env
uv run python -c "from normapi.secrets import generate_secret_key; print(generate_secret_key())"
```

Paste that key into `.env` as `NORM_SECRET_KEY=...` (encrypts saved database
credentials at rest — without it the app still boots, but the Connect step
below will fail). No other setup is required.

```bash
docker compose up -d
```

Open **http://localhost:8090**. That's the whole app — the API itself is also
reachable directly at `http://localhost:8080` if you need it (e.g. `curl
http://localhost:8080/health`), but the UI proxies everything it needs through
its own origin.

Check everything came up healthy:

```bash
docker compose ps
```

To stop everything (data persists in Docker volumes across restarts):

```bash
docker compose down
```

## Using it

The app is a 3-step flow: **Connect → Explore → Report**.

### 1. Connect

Pick a database kind (ClickHouse, Postgres, MySQL, or MongoDB), enter
host/port/username/password/database, and click **Test connection**. On
success you'll see the real list of databases on that server — click **Save
connection and continue**.

> **Connecting to a database on your own machine (not another Docker
> container):** use `host.docker.internal` as the host, not `localhost`.
> From inside the `api` container, `localhost` means the container itself,
> not your machine — this is the single most common first-run gotcha.
> If the database is another container on this same `compose.yaml` stack,
> use its service name instead (e.g. `postgres`).

Saved connections and their credentials are encrypted at rest and reused —
you don't need to re-enter them next time.

### 2. Explore

Pick a database, then a table. You'll see every real column with a few real
sample values next to it. For each column you want normalized, choose what
kind of data it is (person name, company name, phone, email, address, date,
country, etc.) from the dropdown. You can browse multiple tables in a row —
selections accumulate, so you can map columns across several tables before
starting.

Click **Start normalization** once you've mapped at least one column.

### 3. Report

Watch live progress as the run processes your data, then see real per-column
results: rows processed, how many values changed vs. stayed the same,
warnings/errors, potential collisions (two different original values that
normalized to the same thing), and how "lossy" the transformation was. A
browser notification fires the moment the run finishes, even if you've
switched tabs (allow notifications when prompted to get this).

Each column's report links to an "advanced view" with the full detail (exact
before/after values, why a particular value was flagged, etc.) — see below.

### Re-running the same source

Runs are incremental by default: re-mapping and re-running the same table
only processes rows that are new since the last run (tracked per real
`created_at` timestamp). This means a second run over unchanged data will
correctly show 0 new rows — that's expected, not a bug. There's currently no
button in the UI to force a full re-run; if you need one, ask in the
API directly (`mode: "full_resync"` on the run-start request) or file it as
a gap — it's a known, disclosed missing piece (see `docs/verification/
M20-verification-pack.md` and `M21-verification-pack.md`).

### Advanced / legacy tabs

The 3-step flow is the default view. Click **expert** or **admin** (top
right) to reveal 11 additional tabs — Profiles, Fields, Rules, Runs,
Warnings, Collisions, Dictionaries, Quality, Settings, and more — the
original engine-level UI, still fully live, useful for deep inspection,
A/B comparing two runs, managing normalization profiles/rules directly, or
reviewing collisions one at a time. Your mode choice is remembered in the
browser.

## Development (without Docker)

Requires [`uv`](https://docs.astral.sh/uv/) and Node.js.

```bash
uv sync --all-extras
uv run ruff check .
uv run mypy packages
uv run pytest -m "unit or golden or property or contract"
```

Start just the backing services, then run the API and UI directly for faster
iteration (hot reload on both):

```bash
docker compose up -d postgres libpostal
uv run python -m normapi.main          # API on :8080
cd ui && npm install && npm run dev    # UI dev server on :5173
```

Live integration tests need the demo source containers too:

```bash
docker compose up -d demo-postgres demo-mysql demo-mongo demo-clickhouse
uv run pytest -m "not bench"
```

UI end-to-end tests (Playwright, against a real running API):

```bash
cd ui && npx playwright test
```

## Non-goals

- No schema/key/relationship discovery
- No entity extraction or graph construction
- No Splink, no probabilistic linkage, no record matching
- No mutation of source systems — this engine is strictly read-only against sources
