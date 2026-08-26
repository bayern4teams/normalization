# Milestone M15 Verification Pack — Connection Registry With Encrypted Credentials

Status: **All Layer 1/2 checks complete and passing, including the hard security rule this milestone's own risk assessment named. Ready for your Layer 3 review and sign-off.**

M15 is the second implementation milestone of the M13-M22 product-pipeline
program (`docs/plan/M13-M22-program-plan.md`), built under the user's
standing overnight authorization. Scope: a Postgres-backed connection
registry so a user can register a real database (host/port/username/
password) through the API instead of a hand-edited JSON file, with the
password encrypted at rest and never returned by any read.

This milestone carries a **hard, non-negotiable rule** (agreed with the
user before the unattended run started, recorded in project memory):
*never let a plaintext credential reach a log line, span attribute, or
any committed file.* §3.3 below is the live proof this held.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `normapi/secrets.py` — AES-256-GCM `CredentialCipher`, `NORM_SECRET_KEY` loading/validation | ✅ Done (`7374055`) |
| `normapi/connections.py` — `ConnectionRecord`, `DEFAULT_PORTS`, `connection_identity()` (blake3), `ConnectionResolver` | ✅ Done (`7374055`) |
| `normapi/migrations.py` — versioned migration runner + `schema_migrations` table (first real migration, not another `CREATE TABLE IF NOT EXISTS`) | ✅ Done (`7374055`) |
| `postgres_store.py` — connections CRUD wired through the migration runner | ✅ Done (`7374055`) |
| `POST/GET/PATCH/DELETE /connections`, `POST /connections/test`, `GET /connection-kinds` | ✅ Done (`7374055`) |
| `sources.py` hybrid registry — DB-configured connections build lazily, pooled by `(connection_id, database)`, with `refresh()` | ✅ Done (`7374055`) |
| Refuse-to-boot when connection rows exist but `NORM_SECRET_KEY` is unset | ✅ Done (`7374055`) |
| `POST /connections`/`/connections/test` never leak the plaintext password (response, logs, or OTel spans) | ✅ Done, live-verified (`7374055`) |
| ADR-017 filled in with the real, built decision | ✅ Done, this pack |
| Gate G15 verification | ✅ Done, this pack |

## 2. Layer 1 — Automated verification results

Run fresh, in this session, against `main` at commit `7374055`:

```
uv run ruff check .             -> All checks passed!
uv run ruff format --check .    -> 212 files already formatted
uv run mypy packages            -> Success: no issues found in 89 source files
uv run mypy packages tests      -> Success: no issues found in 159 source files
uv run python -m normcli check-traceability
  -> PASSED - all 138 Source.txt sections present in the matrix
uv run pytest -m "unit or golden or property or contract" -q
  -> 992 passed, 12 skipped, 92 deselected, 1 warning in 320.71s
uv run python scripts/check_licenses.py
  -> License check passed: 143 packages inspected, 0 violations, 23 warnings
```

(The combined `mypy packages tests` run supersedes a separate `mypy tests`
invocation this session — same real check, one command instead of two,
disclosed here so the command list matches what was actually typed.)

992 passed (up from M14's 967 — the 25 new tests in `test_secrets.py`
(17) and `test_connections.py` (8)). 92 deselected (up from 85 — the 7
new `test_connection_registry.py` integration tests). One new license
warning versus M14: `cffi` (a real transitive dependency of
`cryptography`) reports `MIT-0`, a real MIT variant not in the allow-list
string-for-string — not a violation (`cryptography` and `pycparser`
themselves both matched the allow-list cleanly), disclosed rather than
silently absorbed into the pre-existing warning count.

### 2.1 Integration suite — run live against real containers

```
docker compose ps
  -> postgres, demo-postgres, demo-mysql, demo-mongo, demo-clickhouse all healthy
     (started this run at 3 AM; were not running when the overnight job began)

uv run pytest tests/integration/test_connection_registry.py -q
  -> 7 passed in 58.07s

uv run pytest tests/integration -q -k "not postgres_store and not connection_registry"
  -> 39 passed, 5 skipped, 24 deselected, 1 warning in 81.22s

uv run pytest tests/integration/test_postgres_store_integration.py -q
  -> 17 passed in 10.96s (re-run from M14, confirming no regression)
```

No pre-existing integration test regressed. The 5 skipped are the same
pre-existing self-skipping tests M9-M14's packs already document
(services not relevant to this run).

## 3. Layer 2 — Live verification

All seven `test_connection_registry.py` tests ran against the **real**
target ClickHouse (`localhost:8190`, database `origin2` — the actual
production connection this whole program exists to serve) and the real
metadata Postgres (port 5535), not a demo/mock:

### 3.1 `POST /connections` against the real target succeeds and persists

`POST /normalization/connections` with `{clickhouse, localhost, 8190,
default, "pass", origin2}` → **201**, response body contains a real
64-character blake3 hex `identity` and no `password` field at all (the
field is absent from `ConnectionResponse`'s schema, not present-as-null
— confirmed via `"password" not in body`). `GET /connections` afterward
also has no password anywhere in the JSON. Matches the plan's own
verify-live expectation exactly.

### 3.2 Real ciphertext, verified by a direct query bypassing the API

`psycopg.connect(...).execute("SELECT encrypted_password FROM
connections WHERE id = %s", ...)` — the stored value is neither equal to
nor contains the plaintext `"pass"`. This is a real base64-encoded
`nonce || AES-GCM-ciphertext` string, read directly from Postgres, not
inferred from API behavior.

### 3.3 The hard rule: password never reaches a response, span, or log — proven, not assumed

Three independent checks, each against the real create-connection request:

1. **HTTP responses**: `password not in response.text` checked on the
   `POST /connections` response, the `GET /connections` list response,
   and (separately) the `POST /connections/test` response and the 400
   error body for a wrong-password `POST /connections` — all pass.
2. **OTel spans**: `app.state.telemetry_handles.span_exporter.
   get_finished_spans()` — every captured span's `attributes` repr and
   `name` checked for the plaintext password; none found. (Honest
   context: this project's HTTP layer has no FastAPI auto-instrumentation
   wired in — confirmed by grep, no `opentelemetry-instrumentation-fastapi`
   anywhere in the tree — so no span is actually created for these routes
   at all today. The assertion is real and passes, but it currently
   proves "nothing leaked into the spans that exist," not "a request
   span was scrubbed of a real hazard." If FastAPI instrumentation is
   ever added in a later milestone, this same test would need to be
   re-examined for whether a new span attribute captures request bodies.)
3. **Python logging**: `caplog` captured at `DEBUG` across the full
   `POST /connections` request/response cycle; every record's message
   checked with a word-boundary regex for the real password value
   (`"pass"`) — not a bare substring check, since the real credential
   here happens to be a fragment of the common English word "password"
   itself (`pytest`'s own `httpcore`/`asyncio` debug logging is verbose
   and would false-positive on a naive substring match). Zero matches.

### 3.4 Restart simulation — a second, independent process actually resolves and connects

Not simulated by re-reading the same in-process object: a **second**
`create_app(postgres_dsn=..., secret_key=...)` call (a fresh
`CredentialCipher`, a fresh Postgres connection, nothing shared with the
first app) successfully calls `connection_resolver.resolve(connection_id)`
and gets back the real plaintext password, then builds a real
`ClickHouseConnector` from those decrypted credentials and calls
`list_tables()` against the actual `origin2` database — `"Person"` is in
the result. This is the load-bearing proof behind "restart the API →
connection still resolves," not just that the metadata row is still
listed.

### 3.5 Wrong password is rejected structurally, nothing persisted

- `POST /connections/test` with a deliberately wrong password (against
  the **demo**-clickhouse container, port 8124 — not the real production
  target, since a deliberately wrong credential has no reason to touch
  real data) → `200 {"ok": false, ...}`, password absent from the
  response.
- `POST /connections` with a wrong password (also against demo-clickhouse)
  → **400**, password absent from the response body, and `GET
  /connections` before/after shows the connection set is unchanged — a
  bad credential is never written to Postgres, matching the plan's
  "wrong password → structured 400 with no credential echoed" verify-live
  bullet exactly.

### 3.6 Refuse-to-boot rule

A connection is created against the real target, then a second
`create_app()` call with `secret_key=None` against the **same** Postgres
(which now has a real connection row) raises `SecretKeyError` with a
message naming the real problem — confirmed via `pytest.raises(...,
match="NORM_SECRET_KEY is not set")`. Booting with no key when the
`connections` table is genuinely empty is separately confirmed to succeed
normally (`connection_resolver is None`, not an error) — the refusal is
conditioned on real data existing, not on the env var alone.

## 4. Design notes and honest disclosures

1. **`POST /connections` and `/connections/test` both live-probe the
   target** (`list_tables()`, plus `list_databases()` when the connector
   is `CatalogConnector`-capable) before persisting or reporting success
   — a design decision beyond what the plan's bullet list spelled out
   verbatim, made because "POST → 201" and "wrong password → 400" only
   make sense together if creation itself validates connectivity; a
   registry that blindly persists unreachable credentials would defeat
   the point of a "Test" button existing at all.
2. **`build_connector_from_parts`** (in `sources.py`, exported for
   `routes.py`'s probe helper) constructs Postgres/MySQL/Mongo DSNs by
   percent-encoding username/password before interpolation — a real
   correctness fix made proactively (not found as a bug, avoided by
   design): an unescaped `@`, `:`, or `/` in a password would otherwise
   corrupt the DSN or be mis-parsed as a different URL component.
3. **Mongo is included in `DEFAULT_PORTS`/`CONNECTION_KINDS`** (the plan
   lists it) but `MongoConnector` has no `CatalogConnector`/
   `StreamingSourceConnector` support (M14 explicitly scoped catalog work
   to ClickHouse/Postgres/MySQL) — a Mongo connection can be created and
   probed (`list_tables()` still works), but `list_databases()` in the
   test-connection response will always be empty for it. Disclosed, not
   silently inconsistent.
4. **No singular `GET /connections/{id}`** was built — the plan's route
   list didn't call for one, and nothing in M15's own scope needed it
   (list + PATCH/DELETE by id sufficed for every verify-live requirement).
   Flagged here in case M16's catalog routes want one.
5. **This schema is the first to go through `migrations.py`'s real
   runner** rather than `CREATE TABLE IF NOT EXISTS` — `profiles`/`runs`/
   `collision_decisions` (M9/M11) were deliberately left untouched on
   their original mechanism, since they have no pending schema change;
   retrofitting them onto the migration runner with no actual migration
   to run would be motion without a real reason.

## 5. Disclosed scope boundaries carried forward

Unchanged by M15: async execution is still one background thread per
run (M11); the double-start race disclosed since M11 is still present;
`GET /overview`/`GET /quality` are still unbounded (M18's job); the
persistent DuckDB cache tier is still off by default (`NORM_CACHE_PATH`
still defaults to `:memory:`, still not set in `compose.yaml` — M17's
job); `env_id`/persistence/collision workflow/UI catch-up are all real
and unaffected by this milestone.

## Human Sign-off

milestone: M15
verdict:
reviewer:
date:
env_id:
commit: 7374055
conditions: []
notes: |
