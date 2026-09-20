# Ground Truth via Agents — Full Execution Guide

**Mission:** completely normalize and standardize every row in every table
and column of the origin database, producing a byte-reproducible ground
truth, executed **without the app/UI/API** — a headless agent run reusing
the repo's deterministic engine.

**Contract (agreed):**
- Agent = brain: decides semantic types per column, profiles data, reviews
  the error ledger, fixes dictionaries/config, iterates until the ledger is
  **empty**.
- Engine = hands: every value byte is produced by the repo's normalizers
  (`normcore.Dispatcher` + `normalizers` + `normexec.DistinctValuePlanner`).
  Re-running with the same config yields byte-identical output — that is
  what makes it ground truth.
- Origin is **absolutely read-only**. No admin rights, ever. Two independent
  read-only layers (grants + `postgresql_readonly` session) stay in force.
- Keys/FKs are **passthrough byte-identical** (referential integrity).
- Destination: **`testdiffbot_clone2`** (new, per your decision;
  `testdiffbot_clone` stays untouched as the old raw copy).
- libpostal sidecar runs for ADDRESS columns.

---

## 0. Environment facts (verified live, 2026-09-16)

| Item | Value |
|---|---|
| Server | `localhost:5433` (docker `now_postgres`, PG18) |
| Origin | db `testdiffbot`, schema `diffbot` — **13 tables, 42,718 rows** |
| Origin login (read-only) | `norm_readonly` / supersecret — grants SELECT only; write attempts fail with `permission denied for schema diffbot` (verified) |
| Destination login (write) | `norm_writable` / supersecret2 — owns `testdiffbot_clone*`, holds `CREATEDB` |
| Destination | db `testdiffbot_clone2`, schema `public` (exists; holds 13 leftover tables from a prior attempt — dropped in Step 1) |
| Row counts | company 3,940 · companycontact 5,330 · companyemployeecategory 5,134 · companyexperience 1,230 · companyfinancials 198 · companyindustry 3,940 · companyinvestmentround 470 · companyinvestor 1,260 · companyrelation 6,174 · companytechnographics 20,092 · industryclassification 339 · location 3,506 · person 1,215 |
| libpostal sidecar | `docker compose up -d libpostal` (URL from `compose.yaml`, default `http://libpostal:8080` / `localhost` port per compose) |
| Engine entry | `uv run python …` from repo root; registry built exactly as `packages/normapi/src/normapi/app.py:150-169` (Passthrough first, real adapters win after) |

### ⚠️ Operational pitfalls (learned this session — follow them)
1. **Never inline DB passwords in shell commands.** The agent harness
   redacts secret-looking literals mid-command (a literal `…` got spliced
   into the password, causing bogus "auth failed"). Put credentials in
   `.env.groundtruth` (git-ignored, `chmod 600`) and `source` it.
2. Normalized columns are created as **TEXT** in the destination — this is
   a deliberate engine invariant (`postgres_destination.py`: a failed
   value must always be able to store its ORIGINAL raw string; per-row
   column typing doesn't exist in SQL). Do not "fix" types to DATE/INT.
3. `created_at`/`_version`/native `bigint`/`integer` columns stay
   passthrough with their **native origin type** — never coerce them.
4. `ErrorPolicy.RETURN_ORIGINAL`: a failed value keeps its original and
   files a ledger row. The engine **never guesses** — ambiguity
   (`d1989-12-11`, bare `03/04/2024`) is an input to the iteration loop,
   not an error to hide.

---

## 1. Phase 0 — Safety rails & credentials setup

1. Create `.env.groundtruth` (git-ignored):
   ```
   GT_ORIGIN_DSN=postgresql://norm_readonly:<ORIG>@localhost:5433/testdiffbot
   GT_DEST_DSN=postgresql://norm_writable:<WRIT>@localhost:5433/testdiffbot_clone2
   GT_ORIGIN_SCHEMA=diffbot
   GT_DEST_DB=testdiffbot_clone2
   LIBPOSTAL_URL=<from compose.yaml>
   ```
2. Prove the rails before touching anything:
   ```bash
   set -a; source .env.groundtruth; set +a
   psql "$GT_ORIGIN_DSN" -Atc "select count(*) from diffbot.company"   # → 3940
   psql "$GT_ORIGIN_DSN" -c "create table diffbot._probe(x int)"       # MUST fail: permission denied
   psql "$GT_DEST_DSN"   -Atc "select current_user"                    # → norm_writable
   ```
   If the probe write succeeds, **STOP** — grants are wrong, fix them before proceeding.
3. **Origin fingerprint (pre-run), saved for the final integrity proof:**
   ```bash
   psql "$GT_ORIGIN_DSN" -Atc "
     select md5(string_agg(t, '|' order by t)) from (
       select table_name || ':' || count(*) || ':' ||
              coalesce(md5(string_agg(t.*::text, ',' order by t.*::text)),'-') t
       from information_schema.columns ic, lateral (select * from diffbot.||ic.table_name t) 
       where ic.table_schema='diffbot' group by ic.table_name) s" -- per-table; exact script in Phase E
   ```
   (The real script iterates the 13 tables and stores `{table: (count, md5)}`
   to `ground_truth/origin_fingerprint_before.json`.)
4. Start sidecar: `docker compose up -d libpostal` and health-check it.

## 2. Phase A — Full inventory (agent reads everything, writes `ground_truth/inventory.json`)

For every one of the 13 tables via the read-only connection:
- columns + native types (information_schema), primary keys, row counts.
- per text column: null count, empty-string count, distinct count, min/max
  length, and 25 sample values.
- cross-table FK census: `companyid`/`personid`/`investmentid`/
  `classificationid` referent existence counts (integrity baseline to
  re-verify after the run).
- special lookups: `select distinct contacttype from diffbot.companycontact`
  (drives contactstring typing), `select distinct relationtype`,
  `types`, `sourcecategory` cardinalities.

Gate: `inventory.json` covers 13/13 tables and all ~120 columns; total rows
== 42,718.

## 3. Phase B — Column semantic typing (agent decides; engine executes)

For every column, the agent assigns one of the 24 `FieldSemanticType`s
(or `PASSTHROUGH`), grounded in Phase A samples, seeded from this table
(refine per evidence; every decision recorded with a reason in
`ground_truth/column_config.json` → `{table: {column: semantic_type}}`):

| Table | Column → type |
|---|---|
| **company** | companyid PASS · entityname COMPANY_NAME · fullname COMPANY_NAME · sourcecategory CODE · description/summary/alldescriptions/motto/descriptors FREE_TEXT · types CODE · website URL · logo URL · foundingdate DATE · totalinvestment PASS(bigint) · totalinvestmentcurrency CURRENCY · ispublic/isnonprofit/isacquired/isdissolved BOOLEAN · ceoname/foundername PERSON_NAME · metadata_confidence CODE · explicit_origins PASS · created_at PASS(ts) · _version PASS(int) |
| **person** | personid PASS · name PERSON_NAME · summary FREE_TEXT · role CODE · types CODE · confidence CODE · created_at/_version PASS |
| **companycontact** | contactid PASS · contactstring **EMAIL or PHONE per contacttype** (split by contacttype groups; unknown type → FREE_TEXT) · contacttype CODE · confidence CODE · companyid PASS |
| **companyemployeecategory** | empcatid PASS · category CODE · firsthiredate DATE · confidence CODE · companyid PASS |
| **companyexperience** | companyid/personid PASS · personname PERSON_NAME · role CODE · confidence CODE · types CODE |
| **companyfinancials** | financialid PASS · year PASS(int) · amount PASS(bigint) · currency CURRENCY · iscurrent BOOLEAN · confidence CODE · companyid PASS |
| **companyindustry** | both ids PASS |
| **companyinvestmentround** | investmentid PASS · date DATE · amount PASS(bigint) · currency CURRENCY · confidence CODE · explicit_origin PASS · companyid PASS |
| **companyinvestor** | investmentid PASS · investorcompanyid PASS · surfaceform COMPANY_NAME · summary FREE_TEXT · types CODE · confidence CODE |
| **companyrelation** | companyid/relatedcompanyid PASS · surfaceform COMPANY_NAME · summary FREE_TEXT · types CODE · relationtype CODE · confidence CODE · explicit_origin PASS |
| **companytechnographics** | techid PASS · technologyname FREE_TEXT · technologytype CODE · categories CODE · confidence CODE · companyid PASS |
| **industryclassification** | classificationid PASS · name FREE_TEXT · isprimary BOOLEAN · confidence CODE |
| **location** | locationid PASS · street ADDRESS · addressfull ADDRESS · city FREE_TEXT · region CODE · postalcode POSTCODE · country COUNTRY · latitude/longitude PASS(text — see note) · precision CODE · isprimary/iscurrent BOOLEAN · companyid PASS |

Notes:
- **All `*id` PKs and FKs → PASS** (approved): byte-identical guarantees the
  clone's referential graph equals the origin's, and origin↔clone row
  matching stays trivial.
- `confidence`/`sourcecategory`/`types` as CODE: enum-ish; if profiling
  shows numeric content, switch to passthrough CODE only (never coerce
  numbers stored as text unless the ledger demands it and ambiguity is
  resolved by locale evidence).
- `latitude/longitude`: NUMERIC is tempting but `1,234`-style values are
  locale-ambiguous; engine would file AMBIGUOUS. Default PASS; revisit
  with the ledger.
- Every type string must be a real `FieldSemanticType` member
  (`normcore/enums.py:81-107`) or absent (= passthrough).

Gate: `column_config.json` has an entry (type or explicit `null`) for
**every** column; `uv run` script validates all type names against the enum
and fails on unknowns.

## 4. Phase C — Destination build (schema clone)

Driver script `scripts/ground_truth/run.py` (new; argparse; import-only
reuse of repo packages — `normapi.clone_executor` building blocks,
`normcore`, `normexec`, `normio`):

1. As `norm_writable`: `DROP TABLE IF EXISTS` the 13 leftover tables in
   `testdiffbot_clone2.public` (owned by that role — no admin needed;
   database itself already exists, so no CREATE DATABASE).
2. For each of the 13 tables: read origin columns/PK through
   `PostgresConnector`; `create_table` in `testdiffbot_clone2.public`
   with `semantic_types` from `column_config.json` — normalized columns
   become **TEXT** (engine mapping), passthrough columns keep native type
   (`timestamp`, `bigint`, `integer`, `text`), PK replicated.
3. Assert: 13/13 tables, column-name lists identical to origin per table.

## 5. Phase D — Stream, normalize, populate (the engine run)

Same architecture as `clone_executor._run_phase2`, rebuilt as a foreground
CLI run (single process, no threads needed at 42.7k rows — minutes, not
hours):

1. Dispatcher built exactly like `app.py:150-169` (Passthrough first, then
   the 18 real normalizers; AddressNormalizer bound to the running
   libpostal URL). `env_id` = `scripts/env_fingerprint.py` output, pinned
   into the run record for reproducibility.
2. `DistinctValuePlanner(dispatcher, None)` — no persistent cache tier
   (measured anti-benefit on high-cardinality data, clone_executor.py:258-274).
3. Per table: stream chunks of `ROW_CHUNK_SIZE=2000`; per configured
   column: `distinct_value_results(...)` with
   `ErrorPolicy.RETURN_ORIGINAL`, write `result.display` back; `None`
   stays `None`; failed values keep original + ledger entry
   `{table, row_index, field, original, error}` appended to
   `ground_truth/ledger.jsonl` (and mirrored to a
   `public._norm_errors` table for SQL inspection).
4. Checkpoint every chunk (`{table: max_offset}` →
   `ground_truth/checkpoints.json`); resume skips ≤ checkpoint; insert
   uses `ON CONFLICT (pk) DO NOTHING` so resume never duplicates.
5. `source_row_key` is driver-internal only — never a destination column.

Gate: status COMPLETED; `sum(rows_done)` == 42,718; per-table clone counts
== origin counts.

## 6. Phase E — Ledger iteration until EMPTY (agent judgment loop)

```
while ledger not empty:
  1. group ledger by (table, field, error-class) with counts + examples
  2. classify each class:
     a. wrong semantic type on column  → fix column_config.json
     b. dictionary gap (honorific, legal suffix, country alias,
        missing-value sentinel)        → add via CustomDictionaryStore
        (data/dictionaries/custom/, versioned file, entry + reason)
     c. genuine ambiguity (locale-dependent date, bare "$",
        "1,234")                       → set ctx.country/locale/default_region
        per table/column from evidence, or accept CODE/passthrough
     d. upstream source rot (e.g. 'd1989-12-11')  → normalize is right to
        flag; add a documented pre-repair rule ONLY if the repair is
        provably safe (e.g. leading-stray-letter before ISO date);
        otherwise the class stays and the "empty ledger" gate for that
        column is re-scoped explicitly in decisions.md (never silently)
  3. apply fix → rebuild affected tables in destination
     (drop table, re-run Phase D for just those tables)
  4. append decision + before/after counts to ground_truth/decisions.md
```

Exit gate: `_norm_errors` empty (or every surviving class carries an
explicit re-scoping decision with evidence), and zero `AMBIGUOUS`/
`INVALID` statuses left unexplained.

## 7. Phase F — Verification suite (proof, not eyeballing)

All run through the read-only origin + writable destination, results to
`ground_truth/verification_report.md`:

1. **Origin untouched:** re-fingerprint (Phase 0.3) → byte-identical to
   `origin_fingerprint_before.json`. (Strongest safety proof.)
2. **Completeness:** per-table `count(*)` equal; column lists equal.
3. **Referential integrity:** clone's FK census (companyid→company etc.)
   equals origin's exact join cardinalities (keys are passthrough, so any
   mismatch means a pipeline bug — must be 0).
4. **No data loss:** every clone non-normalized column byte-equal origin
   (sample 1000 rows/table + full-text md5 on passthrough columns);
   normalized columns: `count(original ∉ {display, original})` == 0 per
   ledger contract.
5. **Idempotency/determinism:** re-run the driver a second time into
   `testdiffbot_clone3` (same config, same env_id); `md5` dump of every
   clone3 table == clone2 tables → byte-identical = ground truth holds.
   (Engine property; proven pattern: `tests/integration/test_byte_identical_replay.py`.)
6. **Quality spot checks:** foundingdate all ISO-8601 or ledgered;
   website all scheme-qualified URLs; ispublic ∈ {true,false}; emails
   valid; phones E.164; country ISO-3166 alpha-2; addresses parsed.
7. **Repo gates:** `uv run pytest -m "unit or golden or property"` green
   (confirms custom dictionary additions broke no engine behavior).

## 8. Deliverables (final state)

```
ground_truth/
  inventory.json          column_config.json      decisions.md
  ledger.jsonl (final: empty or fully-adjudicated)
  checkpoints.json        verification_report.md
  origin_fingerprint_before.json / _after.json
testdiffbot_clone2.public  ← 13 tables, fully normalized, TEXT
                             normalized columns, PKs replicated
```
Plus `scripts/ground_truth/run.py` + README section, committed on a new
branch (current dirty files committed first on `main` as clean logical
commits, per your workflow).

## 9. Hard rules (agent must never violate)

- Origin: SELECT only; never DDL/DML; the two-layer read-only stays on.
- No admin credentials in the driver; only the two role DSNs.
- No LLM inside the value-transform path (engine determinism; §129 rule).
- Never edit `testdiffbot_clone` (the old copy) — it's the "before" evidence.
- Every config/dictionary change is recorded in `decisions.md` with the
  ledger class it resolves.
