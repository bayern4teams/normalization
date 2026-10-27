# Local verification checklist — what the cloud could not prove

Everything here is **implemented, unverified** until the owner runs it locally. Confirm each entry
with an independent check (a direct query, `ss -ltnp`, a curl from another machine), never the
application's own success message.

## Restore the environment first

```bash
git checkout feat/round2-fixes && git pull --ff-only
uv sync --all-extras                       # Python 3.12; PyICU needs libicu-dev + pkg-config
cp .env.example .env                       # then set NORM_SECRET_KEY (D15 removed it from compose.yaml)
docker version --format '{{.Server.Version}}'   # must be 28.3.3 or newer (report D15)
docker compose up -d postgres libpostal    # metadata and destination Postgres on host port 5535
( ulimit -v 16777216; uv run pytest -m integration -q )
( cd ui && npm ci && npx playwright install chromium && npm run test:e2e )
```

Use a copy of a real database; the sources are read-only (ADR-013, unconditional after D14).

## The report's "before" values (the owner must see these change)

| item | before (from the report) | where |
|---|---|---|
| D15 | the API listens on `0.0.0.0`; every compose port has no host address; any database host is accepted; the Postgres DSN is an f-string; `NORM_SECRET_KEY` is committed in `compose.yaml` | report D15, "Verified state" |
| D14 | `in_place` drops the original table after the swap on Postgres and ClickHouse | report D14, "Verified state" |
| D13 | feeding `display` back changes 440 of 7,910 pycountry languages (208 to another language, 232 to INVALID); feeding `comparison` back changes 0 | report D13, "Measured" |
| U1 | no page shows the review queue; 18 page files, 13 navigation items | report U1, "Verified state" |

## Per-item entries (added by the lead when it accepts an item)

```text
### <id> — <title>
- Why the cloud could not verify: <no Docker / no LAN / no database / no running stack>
- Command: <exact command>
- Independent check: <query / ss / curl from another host / file to compare>
- Expected evidence: <from the report, or "any value > X because ...">
- Result (filled in locally):
```

### D15 — local network only
- Why the cloud could not verify: no Docker, no LAN, no real Postgres or ClickHouse.
- Command: set `NORM_BIND_ADDR` (LAN address) and `NORM_SECRET_KEY` in `.env`; `docker compose up -d`; then
  `ss -ltnp` on the host; `curl http://$NORM_BIND_ADDR:8080/health` from a second LAN machine; the same
  from a machine outside the private ranges (or with a public `Host`) must be refused; save a connection to
  a public host (must answer 422); save one to a host name with two addresses, one public (must answer 422).
- Independent check: `ss -ltnp` shows only `$NORM_BIND_ADDR:8080` and `127.0.0.1:*` for every other port;
  `docker version` server >= 28.3.3; the Postgres log shows the connection came from the checked address
  (libpq `hostaddr`); for ClickHouse, `system.query_log` shows the client connected (the driver was given the
  IP with `server_host_name`; never tried against a real server).
- Expected evidence: no port on `0.0.0.0`; LAN caller answered; outside caller refused with 403; bad Host 400.
- Also: `Host: localhost:80@evil.com` is accepted (the allowlist reads the part before the first `:`); an
  IPv6 `Host` (`[::1]`) is not allowed.
- Result (filled in locally):

### D14 — remove in-place mode
- Why the cloud could not verify: no Postgres or ClickHouse.
- Command: `( ulimit -v 16777216; uv run pytest -m integration -q )` against the compose stack; `grep -rn in_place packages ui/src`.
- Independent check: after a clone, `SELECT count(*)` of the origin tables is unchanged and its tables carry no `__normalizing` suffix.
- Expected evidence: integration suite green; a `POST /normalization/clone-jobs` with `in_place` answers 422.
- Limit: two saved connections to one server under different host names (`localhost` and `127.0.0.1`) are not guessed to be one origin; the guard compares engine, host and port as saved.
- Note: a job stored before this change with `in_place: true` is not migrated; delete such rows from the metadata database if any exist.
- Result (filled in locally):

## Test changes to review

Plan §2.9: every test change outside the pre-approved list, each its own `TEST-CHANGE:` commit.
Review the diff of each and confirm the test still checks the same behaviour.

| file | commit | reason |
|---|---|---|

| `tests/conftest.py` (new) | WIP D15 commit "TEST-CHANGE: loopback peer and localhost host for every TestClient" | Starlette's default peer `testclient` and host `testserver` are refused by ADR-022 |
| `tests/unit/test_connector_schema.py` | WIP D15 commit "TEST-CHANGE: use a literal local address as the connection host" | host `h` does not resolve; assertions unchanged |
| `tests/unit/test_address_policy.py` | WIP D15 commit "lint-clean the moved address-policy test" | formatting and a top-level import only |
