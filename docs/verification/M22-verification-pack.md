# Milestone M22 Verification Pack — One-Command Startup

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

M22 is the ninth and final implementation milestone of the M13-M22
product-pipeline program (`docs/plan/M13-M22-program-plan.md`), built
under the user's standing overnight authorization. Its scope, per the
plan: `docker compose up -d` from a clean clone brings up the real UI
(built, served by nginx) alongside the real API, wired together, with no
manual setup beyond a `.env` — the actual "one command" the whole
program has been building toward.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `ui/Dockerfile` — real `vite build` (node builder) → nginx runtime | ✅ Done, live-verified |
| `ui/nginx.conf` — reverse-proxies `/normalization`/`/health` to `api`, serves the SPA | ✅ Done, live-verified |
| `compose.yaml` — new `ui` service; `NORM_SECRET_KEY`/`NORM_CACHE_PATH`/`NORM_SOURCES_CONFIG_PATH` wired into `api` | ✅ Done, live-verified |
| `.env.example` updated with the three new variables | ✅ Done |
| A real, previously-invisible concurrency bug found and fixed via this milestone's own live verification | ✅ Done |
| Gate G22 verification | ✅ Done, this pack |

## 2. Layer 1 — Automated verification results

Run fresh, in this session, against the M22 working diff:

```
uv run ruff check .             -> All checks passed!
uv run ruff format --check .    -> 243 files already formatted
uv run mypy packages tests      -> Success: no issues found in 184 source files
uv run python -m normcli check-traceability
  -> PASSED - all 138 Source.txt sections present in the matrix
uv run pytest -m "unit or golden or property or contract" -q
  -> 1027 passed, 10 skipped, 117 deselected, 1 warning in 109.81s
uv run python scripts/check_licenses.py
  -> License check passed: 144 packages inspected, 0 violations, 24 warnings
     (identical set to M19-M21 — M22 is Docker/compose wiring plus one
     backend concurrency fix using the stdlib, no new Python dependency)
```

1027 passed — unchanged from M21's close (M22 added no new Python
unit/golden tests; its own new test is a live integration test, §2.2).

### 2.1 Full non-bench regression sweep

```
uv run pytest -m "not bench" -q
  -> 1117 passed, 12 skipped, 26 deselected, 1 warning in 545.42s (0:09:05)
```

Genuinely clean this run — no transient timing failures, unlike
M18/M19/M20/M21's own packs (all of which disclosed one under heavy
concurrent Docker load). Up 2 from M21's 1115/1116 total (the new
concurrency regression test, §2.2).

### 2.2 New M22 test, run individually

```
uv run pytest tests/integration/test_catalog_and_streaming.py -v -k clickhouse
  -> 9 passed in 17.90s
```

`test_clickhouse_connector_survives_real_concurrent_calls_from_multiple_threads`
is the new regression test for the real bug this milestone found (§4) —
drives one `ClickHouseConnector` instance from 8 real threads × 10 rounds
against the real `demo-clickhouse` container, asserting zero exceptions.

## 3. Layer 2 — Live verification

Against the real ClickHouse at `localhost:8190` (`origin2`, read-only,
reached from inside the `api` container via `host.docker.internal`) and
a real `docker compose up -d` of this project's own stack — not a
simulation, not `npm run dev`/`python -m normapi.main` run manually like
every prior milestone's verification. `docker --version` 29.7.2, Docker
Compose v5.3.1.

### 3.1 Real build, real boot

```
docker compose build ui api
  -> Image normalization-api Built
  -> Image normalization-ui Built

docker compose up -d api ui
  -> Container normalization-api-1 Started, Healthy
  -> Container normalization-ui-1  Started, Healthy
```

`.env` created from `.env.example` with a real generated
`NORM_SECRET_KEY` (`uv run python -c "from normapi.secrets import
generate_secret_key; print(generate_secret_key())"`) — the one piece of
setup the plan's own verify criterion allows ("no manual setup beyond a
.env").

```
curl -sf http://localhost:8080/health          -> {"status":"ok"}
curl -sf http://localhost:8090/ -o /dev/null -w "%{http_code}"  -> 200
curl -s  http://localhost:8090/normalization/connection-kinds
  -> [{"kind":"clickhouse","default_port":8123}, ...]   # real API response,
     reached through nginx's reverse proxy at :8090, not :8080 directly
```

### 3.2 The full 3-step flow, driven live in a real browser against the containerized stack

Navigated to `http://localhost:8090` (not the dev server, not `localhost:8080`
directly) — real Connect page rendered, `GET /connection-kinds` round-
tripped through nginx. Filled real credentials pointed at the real
ClickHouse with **`host.docker.internal`** as the host (not `localhost` —
the plan's own named gotcha, §5) — **Test connection** returned
`Connected — 3 real database(s) visible. default, origin1, origin2`,
confirming the containerized `api` genuinely reaches the host machine's
real ClickHouse. **Save connection and continue** → Explore, real
database/table dropdowns populated from `origin2`. Selected `Industry`,
mapped `name`+`surfaceForm` → `FREE_TEXT` → **Start normalization** →
Report page, polled to `completed`:

```
Rows processed: 358 / ~179
Chunks committed: 2
Industry.name (FREE_TEXT)        — Rows 179, Changed/unchanged 0/179, Collisions 0
Industry.surfaceForm (FREE_TEXT) — Rows 179, Changed/unchanged 0/179, Collisions 0
```

(179 rows × 2 columns = 358 — a genuinely fresh watermark, since this
connection's identity — `host.docker.internal` — is a different
`connection_identity` hash than the `localhost`-keyed one M21's own
verification had already exhausted; a real, honest side effect of M20's
identity-keyed watermark, not special-cased for this test.)

## 4. A real bug found and fixed during this milestone's own live verification

**`ClickHouseConnector` is not thread-safe for concurrent calls sharing
one instance — a real, previously-invisible bug this milestone's
containerized deployment surfaced for the first time.**

`normapi.sources.SourceRegistry.get_by_connection` (M16) caches ONE
connector per `(connection_id, database)` and reuses it across every
subsequent HTTP request — a deliberate, correct design for avoiding
repeated reconnection overhead on repeated catalog browsing. `ExplorePage`
fires its `columns` and `samples` queries as two independent, genuinely
concurrent `useQuery` hooks the moment a table is selected. FastAPI
dispatches sync route handlers to a thread pool, so both requests can
land on different worker threads at the same instant, both calling into
the SAME pooled `ClickHouseConnector` — and `clickhouse_connect`'s
underlying HTTP client is not safe for that:

```
clickhouse_connect.driver.exceptions.ProgrammingError: Attempt to
execute concurrent queries within the same session. Please use a
separate client instance per thread/process.
```

Hit live: navigating Explore to `Industry` against the real containerized
stack returned a genuine `500 Internal Server Error` on
`GET .../tables/Industry/samples`, visible in `docker logs
normalization-api-1` with the full real traceback (`routes.py:625
sample_connection_table` → `clickhouse.py:77 list_columns` →
`clickhouse_connect`'s own exception). This is the exact same root cause
M18's own pack already found and fixed for `NormalizationCache`'s DuckDB
connection (`normexec/cache.py`) and `SidecarStore` (`normio/
sidecar_store.py`) — a shared client object, not safe under real
concurrent access — just never previously hit for `ClickHouseConnector`
because no prior milestone's live verification exercised the catalog-
browsing routes under genuine concurrent load (the manually-run dev
server across M15-M21's own verification apparently never raced two
requests against it closely enough).

**Fixed** the same shape M18 used: added a `threading.Lock` in
`packages/normio/src/normio/connectors/clickhouse.py`'s
`ClickHouseConnector.__init__`, guarding every real call into
`self._client` across all 9 methods that touch it (`list_tables`,
`list_databases`, `list_columns`, `table_spec`, `sample_rows`,
`sample_values`, `count_null`, `read_chunk`, `read_table`). No nested
lock acquisitions — every internal helper call (e.g. `table_spec`
calling `list_columns`) acquires and fully releases the lock before the
next call, so there's no deadlock risk from this connector's own
internal call graph. `read_table`'s lock is held for the full duration of
its generator's streaming iteration (correct: `clickhouse_connect`
genuinely cannot interleave two streams on one client either) — this
only matters for a pooled connector, since M17/M18/M19's real run-
execution paths already build a DEDICATED (non-pooled) connector per run,
unaffected by this lock's duration.

**Verified**: `ruff check`/`ruff format`/`mypy` clean on the changed file;
the real `api` Docker image was rebuilt and redeployed
(`docker compose build api && docker compose up -d api`); the exact same
live browser flow that previously 500'd rendered real columns and real
sample values cleanly on retry, no console/network errors; a new,
dedicated regression test (§2.2) drives the fix under real repeated
concurrent load against the real `demo-clickhouse` container, not just a
single lucky retry.

## 5. Design notes and disclosed scope decisions

1. **`host.docker.internal` is a real, disclosed prerequisite for
   connecting to a host-machine database from the containerized UI** —
   confirmed live (§3.2), matching the plan's own explicit callout. This
   is not something `compose.yaml` can paper over: the Connect form's
   `host` field is real user input, entered fresh for each real
   connection, and the correct value genuinely depends on where the
   target database actually runs (a container on the same compose
   network needs its service name; a database on the host machine needs
   `host.docker.internal` on Docker Desktop, or the host's real LAN
   IP/hostname elsewhere). No attempt was made to auto-detect or default
   this — it would be guessing at network topology the app cannot know.
2. **`NORM_SOURCES_CONFIG_PATH` is wired but left empty by default,
   deliberately** — the plan named mounting `sources.json`, but doing so
   unconditionally would make `docker compose up -d` from a genuinely
   clean clone crash at container startup the moment the env var pointed
   at a file that doesn't exist yet (`SourceRegistry.from_config_file`
   has no graceful missing-file path — by design, per its own docstring:
   fail loudly at startup, not on first use). Since M15/M21's Connect
   flow now fully supersedes the legacy file-based single-source path
   for the primary product experience, requiring `sources.json` to exist
   for a clean boot would be a regression relative to "no manual setup
   beyond a .env." The env var is real and wired (empty string resolves
   to `SourceRegistry({})`, a graceful no-op, confirmed by reading
   `app.py`'s own resolution logic); a user who wants the legacy path
   sets `NORM_SOURCES_CONFIG_PATH` in their own `.env` and adds a bind
   mount themselves (documented inline in `compose.yaml`).
3. **`NORM_CACHE_PATH` is explicitly set to `:memory:`**, not left
   unset — self-documenting the deliberate M17 finding (persistent
   DuckDB cache tier measured as a net loss at real ~8M-distinct-value
   scale) rather than letting a future reader wonder whether it was
   simply forgotten.
4. **The `ui` container has no direct access to `NORM_API_KEY`** — M11's
   lightweight auth is orthogonal to this milestone; if a deployment sets
   `NORM_API_KEY` on the `api` service, the UI's existing `ui/src/api/
   authStore.ts` (M12) already handles prompting for and sending it, same
   as the dev-server flow. Not exercised live in this milestone's own
   verification (no `NORM_API_KEY` set in the `.env` used above), matching
   every prior milestone's real ClickHouse-first scope discipline — this
   is disclosed as unexercised, not silently assumed to work.
5. **No CI wiring for the `ui` Docker build** — `.github/workflows/
   gate.yml`'s existing `e2e` job already builds/runs `docker compose up
   -d --build` for the API+demo services (per M7's own follow-up) but was
   not extended in this milestone to also build/verify the new `ui`
   service in CI. This is a real, disclosed gap: this pack's own Layer 2
   verification was done by hand, not by an automated gate. Recommended
   as a natural follow-up, not attempted here to keep this milestone's
   scope to what the plan actually named (the compose/Dockerfile wiring
   itself, not a CI pipeline change).

## 6. Disclosed scope boundaries carried forward

This is the final milestone of the M13-M22 program. Every prior
milestone's disclosed, deliberate scope decisions stand: M17's
sequential column processing and no-persistent-cache decision; M18's
`/overview`/`/quality`-only bounding; M19's ClickHouse-only destinations;
M20's watermark-only-catches-new-rows limitation (full resync is the only
correct answer for in-place updates); M21's read-only-degraded legacy
per-run pages for multi-column runs, and the Explore UI's own missing
mode/resync control (§5.1 of M21's pack, still open — a real UX gap:
today, from the deployed containerized UI, a user who wants to force a
resync still has no button for it).

## Human Sign-off

milestone: M22
verdict:
reviewer:
date:
env_id:
commit: 0dd13b0
conditions: []
notes: |
