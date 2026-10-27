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

(no entries yet)

## Test changes to review

Plan §2.9: every test change outside the pre-approved list, each its own `TEST-CHANGE:` commit.
Review the diff of each and confirm the test still checks the same behaviour.

| file | commit | reason |
|---|---|---|

(none yet)
