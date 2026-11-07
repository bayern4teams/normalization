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
   - **Postgres: `source_schema`.** Every Postgres table lookup is
     relative to a schema, and the default is `public`. If your tables
     live in a named schema, set it — `GET
     /connections/{id}/databases/{db}/schemas` lists the ones that
     actually hold tables. One schema per job, so the clone's own table
     names stay unqualified: `diffbot.company` is cloned as `company` in
     the destination's `public`.
   - Leave it unset for ClickHouse, which has no layer between database
     and table.
   - **A job with no tables is rejected** (422) rather than created. It
     used to be created, create nothing in Phase 1, and report
     `COMPLETED` — the most expensive kind of wrong answer, because
     nothing said so. The error names the schemas that do hold tables;
     it does not pick one for you, even when there is only one candidate.
2. **Destination connection** → the write-capable one. **Destination
   database** → a *new* name you choose (e.g. `your_origin_db_clone`) —
   you'll create it yourself in the next step.
3. Every table in the source database is listed automatically and will
   be cloned (decision #3 — no per-table opt-out at this screen). Expand
   any table and set a semantic type on the columns you want normalized;
   leave the rest as passthrough (copied through untouched, original
   type preserved).
4. **Set country and locale** if you know them. Most normalizers refuse
   to guess without them and say so instead of picking: a postcode has no
   format to validate against, `1,234` could group or decimalise,
   `$948,000` likewise, and `12/05/1990` is never read as either MDY or
   DMY. Measured on a real 50,000-row source, adding `locale=en-US`
   recovered 16,200 revenue values that were otherwise stored as NULL —
   34.5% of the column. Leave them unset and every one of those refusals
   stands, which is correct but much less useful. They are never
   inferred: a wrong locale silently changes what a number *means*.

   A COUNTRY column fills this in per row by itself. Its resolved
   alpha-2 becomes the context for every other column of the **same
   row**, so a table holding both a country and a postcode validates
   each postcode against its own row's country — 66 different countries
   in one measured 50,000-row table, which no single job-level default
   could have covered. Two country columns in one row that disagree are
   reported and neither is used.
5. **Set an entity key** (`cross_table_entity_key`) if the same
   real-world thing appears in more than one table under one id — a
   company id, say. A COUNTRY column in *any* table carrying that id then
   supplies the country for every row of every *other* table sharing the
   entity, which is the case a within-row signal cannot reach: Phase 2
   streams one table at a time and never holds two, so a UK landline sat
   AMBIGUOUS next to a table that knew the company was in the UK.

   Measured on a real 41,805-company source, this took E.164 coverage of
   the phone column from **23.6% to 97.4%** — 30,827 numbers. It is
   declared, never guessed: `_version` and `created_at` appear in every
   table of both real sources this was built against, and a wrong join
   key propagates a *wrong* country, which is worse than none. Three
   guards, all measured on that run: an entity whose rows disagree about
   the country is dropped (7 of 179,810), a value the inferred country
   turns out not to fit keeps its no-country result and says so (128
   rows, 0.31%), and a value carrying its own country code is untouched.

   **A COUNTRY column is not the only thing that can name a country.** A
   PHONE that carries its own `+CC` and a POSTCODE only one country's
   format accepts both feed the same map:

   | signal | when it counts | measured |
   |---|---|---|
   | COUNTRY column | always — it *states* the country | 617 distinct values behind 1.76M rows |
   | PHONE | only when the number itself carries `+CC` | 247,469 of 1,021,941 (24.2%) |
   | POSTCODE | only when exactly one country's format fits | 18.9% of 20,000 distinct |

   On a real two-table source with **no country column at all**, those two
   gave 22,025 entities a country and took the phone column from 7,930 to
   10,005 parsed numbers — numbers resolved from a postcode two tables
   over. A stated country always wins over an implied one: without that,
   one `+1` number among a company's contacts silently dropped the `GB` its
   country column stated, because a company legitimately has numbers in
   more than one country.

   Deliberately *not* a signal: a URL's ccTLD. No authoritative source
   separates national from generic ccTLD use, so `.io` would resolve to the
   British Indian Ocean Territory, `.co` to Colombia (6,281 domains on one
   real source), `.me` to Montenegro and `.tv` to Tuvalu. The alternative
   is a hand-written exclusion list that grows one found example at a time.
6. **Create clone job.**

## 3a. Read the plan before anything is built

`GET /clone-jobs/{id}/plan` (`PATCH` the same path to change it).

**Detection only suggests (since fix/robustness, 2026-10-13).** A column is
normalized only when it has an explicit type. Applied to whole columns by
default, detection rewrote real data with no error row and no original kept:
French SIRENs became phone numbers (499,985 of 500,000), US state `al` became
`Albania`, marital status `S`/`M` became the currencies `SOS`/`LSL`. Detection
still runs at job creation, and every unconfigured column in the plan carries
a `suggestion`: the suggested type, the detector's `confidence`,
`validated_share` (the share of the sampled values that type's own validator
accepts under the job's country/locale) and `sampled`. To use one, copy the
type into `field_configs` (per column, via `PATCH` below). To apply every
confident suggestion, create the job with `"autodetect_field_types": true`;
the rest of this section describes that opt-in mode.

On the real 7-table source detection was measured against:

```
8 of 45 columns will be normalized, across 7 tables
Company.companyName      COMPANY_NAME  INFERRED
Company.website          URL           INFERRED
Location.CountryCode     COUNTRY       INFERRED   -> CountryCode_code
Location.Zip             POSTCODE      INFERRED
...
```

Eight of forty-five, every one of them guessed, and the two highest-value
columns in the database — `companyPhone` and `companyRevenue` — absent.
Nothing said so before; finding it out meant running the clone and
reading the result.

**Give the job a `country` and `locale` and the plan gets better on its
own.** Detection validates a sample of each column's real values, and it
now does so under the job's own context. Measured on that same source
(non-key textual columns, against a ground truth stated in
`tests/unit/test_type_detection_coverage.py`'s fixture):

| | recall | precision | columns applied |
|---|---|---|---|
| before | 58.3% | 100% | 7 |
| after, no `country`/`locale` | 75.0% | 100% | 9 |
| after, `country=US locale=en-US` | **83.3%** | **100%** | 10 |

Precision is the number that may not move. A false positive rewrites a
column; a false negative leaves it exactly as it arrived — so detection is
tuned to the second kind of mistake, and two columns are still deliberately
missed:

- A column literally named `name` is PERSON_NAME at 0.8, below the apply
  threshold. Raising it would also claim `Industry.name` and
  `Industry.displayName`, which are industry labels.
- `Street` is not matched as ADDRESS. There is no validator for ADDRESS, so
  it would be a pure name guess sent to libpostal.

**Two kinds of column are never inferred, by rule rather than by name:**

1. **Columns the source already types** (timestamp, numeric, boolean,
   uuid). The database already guarantees the format, and configuring one
   would downgrade it to text.
2. **Columns in the table's own key** (primary key, or ClickHouse's sorting
   key). Normalization is many-to-one — `GB`, `uk` and `Great Britain` all
   become `United Kingdom` — so applying it to a key merges rows that were
   distinct, and on a `ReplacingMergeTree` the merge is silent and
   permanent. Measured on a real source, detection mapped
   `PersonContact.freeMails` to EMAIL at 0.95 confidence, and `freeMails`
   is that table's entire sorting key.

Both read the source's structure, never column names — `_version` and
`created_at` are excluded because of their types. An explicit
`field_config` overrides either: the rules govern what is *guessed*.

Per column the plan gives the semantic type, whether it was `EXPLICIT` or
`INFERRED`, the native destination type it will get, and the companion
column it will gain. Unconfigured columns are listed too: *what is not
being normalized* is half of what a review is for. It is computed by the
same function Phase 1 executes, so it cannot describe something else, and
it touches only the source — the destination database need not exist yet.

`PATCH` applies only the fields you send, and `field_configs` merges per
table and per column, so fixing one column does not restate the other 44:

```json
{ "field_configs": {"Company": {"companyPhone": "PHONE",
                                "companyRevenue": "MONEY",
                                "companyName": null}},
  "locale": "en-US",
  "cross_table_entity_key": "companyID" }
```

An explicit `null` turns a column off (passthrough); omitting it leaves it
as planned. Amendable only while the job is `PENDING_DB_CREATE` — after
Phase 1 the destination's columns are what they are.

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

The clone has columns the origin did not:

| Column | Holds | For |
|---|---|---|
| `<col>_code` | the ISO alpha-2 / BCP-47 subtag / E.164 number | COUNTRY, LANGUAGE, PHONE |
| `<col>_currency` | the ISO 4217 code | MONEY |

Both exist because the original column keeps the *human* form
("United States", "+1 650-253-0000") and the machine key would otherwise
be computed and thrown away — which is how a column named `CountryCode`
ended up holding "United States" and joining against nothing.

`typed_destination_columns` is **on by default**: NUMERIC/MONEY/BOOLEAN
columns get a real SQL type, so `SUM`/`AVG` work without casting. A
value that will not cast becomes NULL, keeping its original in the error
report. Set `typed_destination_columns: false` to keep everything text.

- **Errors** section on the same page: any value that failed to
  normalize kept its **original** raw value in the clone (never blank,
  never skipped — decision #8) and is listed here with full detail
  (table, field, row, error, safe preview), paginated.
- Two entries there are *column*-level, not row-level, and carry
  `row_index = -1`:
  - `normalization emptied N% of this column` — every column whose
    non-empty values were emptied by more than
    `NORM_CLONE_NULL_RATE_REPORT` (5% by default). This is the one thing
    that makes typed columns safe to leave on: without it, a column that
    arrived 34.5% NULL looked exactly like a column that was merely
    sparse at source. Set `max_new_null_rate` on the job to FAIL rather
    than report.
  - `N% of this column is not a <TYPE> ... it may be mapped to the wrong
    semantic type` — the column's values are not what it was mapped to.
    Measured on a real source, a column mapped to COUNTRY held Wikidata
    *descriptions* ("Country located primarily in North America") and came
    back 99.2% INVALID: one fact about the mapping, previously readable
    only by reading 3,478 per-row findings. AMBIGUOUS never counts — a
    POSTCODE column with no country is 100% AMBIGUOUS and perfectly well
    typed — and a column needs at least 20 values before it is accused,
    so small lookup tables are never flagged.
  - `country conflict: X says .., Y says ..` — two country columns in one
    row that contradict each other.
  - `cross-table entity map on '<key>': N entities with one country, M
    dropped for disagreeing` — one row per job, recorded even when nothing
    went wrong, because a map that silently supplied nothing (wrong key
    column, no COUNTRY column in a table carrying it) and a map that
    worked look identical from the destination.
  - `N of M normalized values in this column change again when normalized a
    second time ... not converging` — the idempotency gate. §71 requires
    `normalize(normalize(x)) == normalize(x)`, so this finding has **no
    threshold**: one value that will not settle is a defect. Each chunk
    feeds back up to `NORM_CLONE_IDEMPOTENCY_SAMPLE` (50) of the column's
    distinct *changed* outputs; a value equal to its input is a fixed point
    by inspection and costs nothing. Reported, never repaired — silently
    applying the second answer would make the destination depend on how
    many times the pipeline ran.
- **The count is this job's.** `GET /clone-jobs/{id}/errors` returns
  `X-Total-Count` scoped by `job_id`. The table holds every job's rows: on
  one real run the job had produced **16,201** of the table's
  **4,758,656**, and a page of 100 cannot tell you which number you are
  looking at.

### `GET /clone-jobs/{id}/quality` — what each column achieved

The error report says what went wrong. This says what happened, per column,
and its categories sum to the column's own value count:

```
Company.companyPhone     values=45,887   PARSED=45,843  INVALID=44
Company.companyRevenue   values=46,956   NORMALIZED=46,956    emptied=0
Company.companyName      values=50,000   UNCHANGED=48,416  NORMALIZED=1,584
Location.Zip             values=40,155   NORMALIZED=39,780  INVALID=375
```

Every member of `NormalizationStatus` is counted, so `UNCHANGED` — a value
that was already clean — is visible rather than missing. The same source
run **without** `locale=en-US` for comparison:

```
Company.companyPhone     values=45,887   AMBIGUOUS=42,788  PARSED=3,055
Company.companyRevenue   values=46,956   AMBIGUOUS=16,200  NORMALIZED=30,756   emptied=34.5%
```

That is the same data, the same code, and one missing field on the job.
AMBIGUOUS is not a failure — it is the normalizer refusing to guess — but a
column that is 93% AMBIGUOUS is telling you it is missing context.

A table appears in the report as it completes, so a long job's numbers are
readable while it runs. Kept off `GET /clone-jobs/{id}` on purpose: the UI
polls that every two seconds and this is a row per configured column.
- Diff origin vs. destination directly to confirm normalized
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
| `POST /clone-jobs` returns 422 "No tables to clone" | The database (or the schema, on Postgres) holds no tables the connection can see. The detail names the schemas that do — set `source_schema`. Wrong database and missing SELECT grants land here too |
| Discovery/clone-job routes 503 | `NORM_PG_DSN` isn't configured for the `api` process — the clone feature needs the app's own metadata Postgres (decisions #10's resumability requires durable storage, no in-memory fallback exists for this feature) |
| `connection failed` / `Connection refused` from the API | Wrong host for where the API actually runs — `localhost` inside the `api` container means the container, not your host or another container; use the Docker network service name or the machine's real address (§1a/§1b above) |
| `CREATE DATABASE` step never appears / Verify fails with "does not exist yet" | You haven't run the `CREATE DATABASE` command shown on the job page yet, or ran it against the wrong server/credential |
| A ClickHouse `CREATE TABLE` fails with `ILLEGAL_COLUMN`/nullable sorting key | Shouldn't happen — this was a real bug found and fixed during verification (`ORDER BY` columns are never wrapped in `Nullable`); if you hit it, you're likely on an unpatched checkout |
| Encrypt/decrypt errors on a saved connection | `NORM_SECRET_KEY` changed or is unset since that connection was saved — the key must stay stable for the life of every saved connection |
