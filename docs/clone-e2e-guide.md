# DB-Clone-and-Normalize: Running It End to End

A practical, step-by-step walkthrough for actually running the
DB-clone-and-normalize feature against a real database — your own, or the
repo's demo containers. For the feature's design/decisions see
`docs/adr/ADR-017-clone-normalize-engine-scope.md` and
`docs/normalization-architecture.md` §13; for evidence that it works, see
`docs/verification/clone-normalize-verification-pack.md`.

## 0. Prerequisites

- `docker` + `docker compose`.
- A Postgres or ClickHouse server you want to clone from — either the
  repo's own demo containers (see §1a) or a real server you control (§1b).
  **Postgres and ClickHouse only**, and origin+destination must be the
  same engine (decision at the top of the plan) — MySQL/Mongo/File are
  documentation-only (ADR-017).

## 1. Start the app

```bash
docker compose up -d postgres libpostal api
```

This is the app's own metadata store (`postgres`, port 5535 on the host),
the libpostal sidecar, and the API (`api`, port 8080). You do **not** need
the `demo-*` services unless you're using them as your origin (§1a).

Check it came up healthy:

```bash
docker compose ps --format '{{.Names}}\t{{.Status}}'
curl -s http://localhost:8080/health
```

Then start the UI:

```bash
cd ui && npm run dev
```

Open `http://localhost:5173`.

`NORM_SECRET_KEY` (encrypts saved connection passwords at rest) is
already set to a fixed dev-only value in `compose.yaml`, same convention
as its plaintext `POSTGRES_PASSWORD` — generate and set a real one via
`.env`/your deployment's secrets for anything beyond local dev:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 1a. Using the repo's demo containers as your origin

```bash
docker compose up -d demo-postgres demo-clickhouse
```

Seeded with `readonly_user`/`readonly_pass` (origin) and
`writable_user`/`writable_pass` (destination) — see
`tests/integration/fixtures/`. **Host/port matter here**: use
`localhost:5434` (Postgres) / `localhost:8124` (ClickHouse) if the API is
running on your host (`uv run uvicorn normapi.main:app`); use the
in-network service name and internal port —
`demo-postgres:5432` / `demo-clickhouse:8123` — if the API is running in
the `api` container, since "localhost" inside that container means the
container itself, not the host. This exact mismatch is a real gap the
live verification pass hit and documented
(`docs/verification/clone-normalize-verification-pack.md` §3.2).

### 1b. Using your own real database

Decision #2 requires **two separate credentials** on the same server —
origin stays strictly read-only forever, destination is a distinct
write-capable login, never reused. Run against your real server (adjust
names):

```sql
-- Origin: read-only
CREATE ROLE norm_readonly WITH LOGIN PASSWORD 'a-real-password';
GRANT CONNECT ON DATABASE your_origin_db TO norm_readonly;
GRANT USAGE ON SCHEMA public TO norm_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO norm_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO norm_readonly;

-- Destination: write-capable, same server. CREATEDB lets it own (and
-- fully control) whatever database it creates — no further grants needed.
CREATE ROLE norm_writable WITH LOGIN PASSWORD 'a-different-real-password' CREATEDB;
```

No `CREATE ROLE` rights on a managed instance (RDS, Cloud SQL, ...)? Use
an existing read-only user for origin, and any user with `CREATEDB` or
schema-owner rights for destination.

Use whatever host/port the `api` container can actually reach — a
public/VPC address, or the Docker host's address if your database runs
on the same machine outside Docker (not `localhost`, which inside a
container means the container itself). Quick reachability check from
inside the running container:

```bash
docker exec normalization-api-1 python3 -c "
import psycopg
psycopg.connect('postgresql://norm_readonly:a-real-password@YOUR_HOST:5432/your_origin_db')
print('reachable')
"
```

## 2. Save both connections

`Connections` in the nav → fill in engine/host/port/username/password →
**Save connection**, once for the read-only origin credential, once for
the write-capable destination credential. The database is *not* part of
a saved connection (decision #13) — it's picked fresh on the next screen.

## 3. Create the clone job

`Clone` in the nav:

1. **Source connection** → the read-only one. **Source database** →
   picked from a live, server-queried dropdown (decision #1 — never a
   network port scan).
2. **Destination connection** → the write-capable one. **Destination
   database** → a *new* name you choose (e.g. `your_origin_db_clone`) —
   you'll create it yourself in the next step.
3. Every table in the source database is listed automatically and will
   be cloned (decision #3 — no per-table opt-out at this screen). Expand
   any table and set a semantic type on the columns you want normalized;
   leave the rest as passthrough (copied through untouched, original
   type preserved).
4. **Create clone job.**

## 4. Run `CREATE DATABASE` by hand

You land on the job's detail page, status `PENDING_DB_CREATE`, showing
the exact command:

```sql
CREATE DATABASE your_origin_db_clone;
```

The app never issues this itself (decision #6 — no admin/`CREATE
DATABASE` rights required by the app). Run it yourself against the
destination server (`psql`, your usual client, whatever you have), using
either credential — the destination role owns whatever it creates.

## 5. Verify → Start → watch it finish

- **Verify database exists + create empty tables** — checks the database
  now exists, then runs Phase 1 DDL: every table created completely
  empty, primary key replicated on Postgres / `ORDER BY`+engine
  replicated on ClickHouse (decision #11). Status becomes `SCHEMA_READY`.
- **Start clone** — Phase 2: streams, normalizes, and populates every
  row, chunked and checkpointed. The page polls automatically every 2s
  until it reaches `COMPLETED` (or `FAILED`, with `error` set).

If the app restarts mid-run, the job is left `RUNNING` but orphaned —
click **Start** again on the same job and it resumes from its last
committed chunk instead of redoing the whole table (decision #10; proven
at 20,000-row scale in the verification pack).

## 6. Check the results

- **Errors** section on the same page: any value that failed to
  normalize kept its **original** raw value in the clone (never blank,
  never skipped — decision #8) and is listed here with full detail
  (table, field, row, error, safe preview), paginated.
- Diff origin vs. destination directly to confirm normalized-in-place
  values, untouched passthrough columns, and — most importantly — that
  the origin is byte-for-byte unchanged:

```bash
psql "postgresql://norm_readonly:...@YOUR_HOST:5432/your_origin_db" \
  -c "SELECT * FROM your_table ORDER BY id LIMIT 20;"
psql "postgresql://norm_writable:...@YOUR_HOST:5432/your_origin_db_clone" \
  -c "SELECT * FROM your_table ORDER BY id LIMIT 20;"
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| Discovery/clone-job routes 503 | `NORM_PG_DSN` isn't configured for the `api` process — the clone feature needs the app's own metadata Postgres (decisions #10's resumability requires durable storage, no in-memory fallback exists for this feature) |
| `connection failed` / `Connection refused` from the API | Wrong host for where the API actually runs — `localhost` inside the `api` container means the container, not your host or another container; use the Docker network service name or the machine's real address (§1a/§1b above) |
| `CREATE DATABASE` step never appears / Verify fails with "does not exist yet" | You haven't run the `CREATE DATABASE` command shown on the job page yet, or ran it against the wrong server/credential |
| A ClickHouse `CREATE TABLE` fails with `ILLEGAL_COLUMN`/nullable sorting key | Shouldn't happen — this was a real bug found and fixed during verification (`ORDER BY` columns are never wrapped in `Nullable`); if you hit it, you're likely on an unpatched checkout |
| Encrypt/decrypt errors on a saved connection | `NORM_SECRET_KEY` changed or is unset since that connection was saved — the key must stay stable for the life of every saved connection |
