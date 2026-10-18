# Benchmark report: `feat/defects-fixes` on public data

Local close-out of Defects D1-D12, 2026-10-12. Benchmarks are **held out**: no normalizer, dictionary,
threshold or heuristic was changed to move a number here. One regression found by these runs (a bug in
this branch's own date fix) was fixed with the user's go-ahead (ef60e8a). Every other failure is
recorded below with a reproducer and left for the user to decide. Every pass/fail was confirmed
independently of the application's own success message: by direct SQL on the destination or the
metadata database, Marquez's own API, ClickHouse's `system.query_log`, or a library that does not go
through the app (python-stdnum).

**Headline.** The D1-D12 checks mostly hold on real data (table in §3). The serious problems are
outside D1-D12 and were found by running real sources end to end:

- **Autodetect silently corrupts whole columns.** It is on by default. French SIRENs became phone
  numbers in 499,985 of 500,000 rows. US state `al` became `Albania`. Marital status `S`/`M` became
  the currencies `SOS`/`LSL`.
- **Two classes of real source cannot be cloned at all.**
  - Column names with `.`, spaces or `-` break every Postgres destination (Norway, GLEIF).
  - Any ClickHouse table whose chunks take more than 30 s to normalize loses its source stream
    (OnTime, 2/2 runs).

## 1. Environment

| item | value |
|---|---|
| host | 13th Gen Intel i5-13600K, 16 vCPU, 27 GB RAM, 476 MB swap, VMware guest, Linux 7.1.5 (Kali) |
| caps | each job: systemd scope `MemoryMax=6G`, no swap, plus `ulimit -v 16 GB`, `MALLOC_ARENA_MAX=2`; containers capped with `docker update` (ClickHouse 4 GB, each Postgres 2 GB, libpostal 3 GB) |
| code | `feat/defects-fixes` at ef60e8a (benchmarks), Python 3.12.13, uv 0.12.17 |
| libraries | duckdb 1.5.5, pyarrow 17.0.0, polars 1.43.2, SQLAlchemy 2.0.52, psycopg 3.3.4, clickhouse-connect 0.15.1, phonenumbers 8.13.55, python-stdnum 1.20, dateparser 1.4.2, FastAPI 0.141.1 |
| services | isolated compose project `normbench` (compose.yaml plus a local override), fresh volumes; the user's `normalization_pg_data` volume and the user's other stacks were never touched |
| metadata and destination | PostgreSQL 16.15 (:5535) |
| sources | PostgreSQL 16.15 (:5436); PostgreSQL 18.6 for Pagila (:5438) |
| other services | ClickHouse 24.9.3.128 (:8124); libpostal (existing image); Marquez 0.51.1 |
| test ports | moved off the user's ports: `TEST_PG_PORT=5436`, `TEST_MONGO_PORT=27019` |
| integration suite | `pytest -m integration`: **24 passed, 0 failed, 0 skipped** |
| CI gate | the four ci-fast commands under the cap: 2852 passed / 21 skipped / 4 xfailed; ci-fast green on ef60e8a (run 38228089061) |

Session incident (07:04:59 local): the desktop session ended mid-run, and the user reported an OOM.
- **What the logs show:** the kernel logged no OOM kill and there was no reboot. Xorg terminated
  normally (`Server terminated successfully`) after the xfce session manager disconnected. libwnck
  assertion failures are logged just before that.
- **Memory at the time:** our ClickHouse stayed at 0.9-1.3 GB resident through the window. The two
  benchmark jobs then running are about 0.4-0.9 GB each.
- **Verdict:** the logs do not prove memory exhaustion. The caps above were added afterwards anyway,
  plus a watchdog that stops benchmark jobs below 3.5 GB available. Two jobs died with the session and
  were re-run.

## 2. Datasets

All files are under `$BENCH_DIR/datasets/` (outside the repo since 2026-10-18; `data/benchmarks/` before), each with a SOURCE.md giving URL, UTC download
time, licence and sha256. MANIFEST-AC.md and MANIFEST-D.md list every file. Every size matched the
published or expected size. Only SIRENE (sha1) and the Luxembourg file (md5) publish checksums, and both
matched.

| tier | dataset | rows loaded | licence | used for |
|---|---|---|---|---|
| A | Raha: hospital, flights, beers, rayyan, movies_1, tax (dirty + clean) | 1,000 / 2,376 / 2,410 / 1,000 / 7,390 / 200,000 | Apache-2.0 (repo) | accuracy, D2, D6 |
| A | DeepMatcher (Leipzig): DBLP-ACM, DBLP-Scholar, Amazon-Google, Abt-Buy, dirty DBLP-ACM / DBLP-Scholar | tableA/B as loaded | "Creative Commons" per Leipzig page (variant not named) | match-key agreement (§4) |
| B | Pagila (PG18 schema) | 51,805 rentals | PostgreSQL License | multi-table clone |
| B | Chinook v1.4.5 | 11 tables | MIT-style | multi-table clone, D3 |
| C | NYC TLC yellow 2024-01 | 2,964,624 | none stated | throughput |
| C | UK Price Paid 2024 | 931,453 | OGL v3 | throughput, POSTCODE/DATETIME |
| C | OnTime 2022 (ClickHouse public S3) | 1,598,468 | none stated (BTS) | ClickHouse scale |
| C | TPC-H SF1, SF10 (DuckDB `tpch` v1.5.5) | 8,661,245 / 86,586,082 | TPC EULA; results not comparable to TPC-H results | throughput |
| D | Norway Enhetsregisteret 2026-10-12 | 1,177,617 | NLOD 2.0 | D7 |
| D | France SIRENE StockUniteLegale 2026-10-01 (fixed-seed sample, 42) | 500,000 of 30,148,401 | Licence Ouverte 2.0 | D7 |
| D | GLEIF LEI golden copy 2026-10-12 | 3,458,719 | CC0 | COUNTRY, D4 |
| D | Luxembourg BD-Adresses (attribute table) | 179,684 | CC0 | ADDRESS/POSTCODE |

All CSV sources were loaded **verbatim as TEXT** (empty fields as `''`), with a `_bench_row` position
column. Row counts were checked against the files with the csv module, duckdb, or the DBF header. Two
random rows per table were compared value by value. The Luxembourg check reused the loader's own DBF
reader, so it cannot catch a bug in that reader.

## 3. LOCAL_VERIFY results (unverified-live items)

| item | result | evidence |
|---|---|---|
| D1 Postgres DDL / upsert | **pass** | `ensure_schema` created the queue (PK `key`), verdicts (PK `key, decided_at`) and lineage tables. A real Chinook clone queued 18 AMBIGUOUS entries; same-key rows merged (`occurrences 2`) |
| D1 round trip | **pass** | ClickHouse source `1,234` (MONEY, no locale): run 1 gave NULL plus 2 error rows. `POST .../verdicts "1234.00 USD"` returned 201 (a blank verdict was refused, 422). Run 2 with the same connections: the cells became `1234` / `USD` and the job had 0 error rows |
| D1 NUL in the queue | **fail** | AMBIGUOUS `1,234\x00` made the error-row INSERT raise `PostgreSQL text fields cannot contain NUL`; the job FAILED and all 3 error rows of that batch were lost, the queue was not written, and the destination rows were already in |
| D2 calibration | **ran; see §5** | seeded corpus: threshold 0.90 at R = 20 and R = 100. Raha erroneous cells: ECE 0.276 against a 0.046 tolerance, abstain on everything; the stated-1.0 bins are observed at 0.782 |
| D3 Postgres DDL / ON CONFLICT | **pass** | `normalization_lineage_events` PK `(run_id, event_type)` + index `job_id`; START/COMPLETE/FAIL rows stored for every run |
| D3 Marquez | **partial** | Marquez 0.51.1 has the job (latest run COMPLETED), the right input and output datasets, and a column-lineage facet for all 5 destination columns, companions included (`phone_code` from `phone`, `total_currency` from `total`). But `/api/v1/column-lineage` returns 0 nodes and the dataset has no fields: the events carry no schema facet, so Marquez's column-lineage graph and its UI stay empty |
| D3 `get_columns` | **pass** | Chinook: for 11/11 tables the facet fields equal the destination columns (information_schema). ClickHouse: same. Source→destination column delta = companion columns only |
| D4 live | **pass, with limitations** | `N/A` ×1005 reported with its exact GROUP BY count. Namibia `NA` (GLEIF 109, Brreg 1) is not reported. Limitations in §7 |
| D5 overflow on ClickHouse | **pass** | 6/6 rows committed. `1e999`, `1e40`, a 41-digit NUMERIC and a 41-digit MONEY each became NULL plus an error row keeping the original; job COMPLETED |
| D5 gate vs. real columns | **pass for "never aborts", fail for "ClickHouse rounds"** | (a) ClickHouse **truncates** (server-side too): `12.34565`→`12.3456`, `0.00005`→`0`, `0.0000000005`→`0`, with no error row. Postgres rounds half-up (`12.3457`, `0.0001`). (b) A 131072-digit integer inserts on Postgres; `1e131072` never reaches the INSERT. (c) Fractions beyond the scale: neither engine aborts. Same input, different stored value per engine |
| D6 seeded baseline | **pass** | `generate --seed 0 --n 30`: 142 / 21 / 11 / 6 / 0, identical to the cloud; 10 of 11 wrong-confident are the bare-host URL guess |
| D6 Raha | **ran; see §4** | literal command: measures formatting, and its CSV loader takes no context. Canonical truth: 2,253 confident misses of 98,194 erroneous cells; 3 of them are an engine bug, the rest are undetectable by syntax or a repair candidate |
| D7 registry numbers | **pass on the rule; coverage gap** | 0 INVALID of 1,677,617 register numbers. SIREN: 500,000/500,000 VALID. Norway: 1,177,617/1,177,617 **UNKNOWN** and 0 VALID, though python-stdnum `no.orgnr` validates every one |
| D10/D11 persistence (optional) | **not applicable as written** | A clone stores `display` plus the `<col>_code` companion (E.164 comparison key). No clone persists the `structured` dict, so neither `rfc3966` nor the phonetic keys reach a destination. This design predates the branch; the LOCAL_VERIFY expectation was wrong |

## 4. Tier A accuracy (Raha)

**Method.** The column → type map was fixed from the headers before any scoring:
`docs/benchmarks/scripts/raha_accuracy.py`. US datasets got context country US, locale en-US. `flights` has
only times of day and there is no TIME type, so it was not scored. Dirty and clean are aligned by
position: Raha's clean.csv renames the columns but keeps their order.

Two methods were run:

1. **Canonical truth (the headline).** The truth for a cell is the engine's reading of the *clean* value in
   the same context. Only **erroneous cells** (dirty ≠ clean) are informative. On an unchanged cell the
   truth and the answer come from the same input, so they agree by construction.
   - Erroneous cells are split into:
     - **corrected**: the answer equals the truth;
     - **flagged**: AMBIGUOUS, INVALID or another non-value, so the error is detected but not repaired;
     - **missing-in-source**: the dirty cell is empty and the engine emits nothing rather than invent a
       value;
     - **equal as number**: NUMERIC, equal by value but not as a comparison key (`7.0` vs `7`);
     - **missed**: a confident answer that differs from the truth.
   - A clean value the engine cannot read at all is a **coverage gap**, counted separately.
2. **Literal** (LOCAL_VERIFY's D6 command, `normcli gold score <dirty,clean csv> --semantic-type T`).
   - It compares the engine's comparison key with the *raw* clean string, and its CSV loader passes no
     context.
   - So it mostly measures formatting: `Y` vs `true`, title case vs lowercase, `USA` vs
     `United States`. Without a country, PHONE and POSTCODE abstain on every cell.
   - Totals per column are in the raw results. Examples: `tax.has_child` 200,000 wrong-confident (all
     `Y`/`N` vs `true`/`false`); `hospital.phone` 1,000 over-abstain (no country).
   - It is not a usable accuracy measure on Raha. The CSV loader cannot take a country or locale, which
     is a gap in D6 itself.

**Canonical-truth results (ef60e8a):**

| dataset.column | type | cells | erroneous scored | corrected | flagged | missing-in-source | equal as number | missed (confident wrong) | clean values unreadable (coverage gap) |
|---|---|---|---|---|---|---|---|---|---|
| hospital.name | COMPANY_NAME | 1,000 | 24 | 0 | 0 | 0 | 0 | 24 | 0 |
| hospital.address_1 | ADDRESS | 1,000 | 0 | 0 | 0 | 0 | 0 | 0 | 1,000 |
| hospital.zip | POSTCODE | 1,000 | 30 | 0 | 30 | 0 | 0 | 0 | 0 |
| hospital.phone | PHONE | 1,000 | 34 | 0 | 31 | 0 | 0 | 3 | 0 |
| hospital.emergency_service | BOOLEAN | 1,000 | 27 | 0 | 27 | 0 | 0 | 0 | 0 |
| hospital.score | NUMERIC | 1,000 | 0 | 0 | 0 | 0 | 0 | 0 | 1,000 |
| hospital.sample | NUMERIC | 1,000 | 0 | 0 | 0 | 0 | 0 | 0 | 1,000 |
| beers.ounces (truth not comparable: clean drops unit) | QUANTITY | 2,410 | 2,410 | 0 | 294 | 0 | 0 | 2,116 | 0 |
| beers.abv | NUMERIC | 2,410 | 693 | 0 | 693 | 0 | 0 | 0 | 0 |
| beers.ibu | NUMERIC | 2,410 | 1,005 | 1,005 | 0 | 0 | 0 | 0 | 0 |
| beers.brewery_name | COMPANY_NAME | 2,410 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| rayyan.article_language | LANGUAGE | 1,000 | 0 | 0 | 0 | 0 | 0 | 0 | 12 |
| rayyan.article_jcreated_at | DATE | 1,000 | 722 | 0 | 0 | 0 | 0 | 722 | 0 |
| rayyan.article_jvolumn | NUMERIC | 1,000 | 22 | 0 | 0 | 22 | 0 | 0 | 0 |
| rayyan.article_jissue | NUMERIC | 1,000 | 53 | 0 | 0 | 53 | 0 | 0 | 0 |
| movies_1.year | DATE | 7,390 | 190 | 0 | 190 | 0 | 0 | 0 | 0 |
| movies_1.release_date | DATE | 7,390 | 0 | 0 | 0 | 0 | 0 | 0 | 7,262 |
| movies_1.country | COUNTRY | 7,390 | 0 | 0 | 0 | 0 | 0 | 0 | 1,553 |
| movies_1.duration | QUANTITY | 7,390 | 187 | 2 | 105 | 80 | 0 | 0 | 0 |
| movies_1.rating_value | NUMERIC | 7,390 | 856 | 0 | 165 | 22 | 669 | 0 | 0 |
| movies_1.rating_count | NUMERIC | 7,390 | 5,505 | 5,505 | 0 | 0 | 0 | 0 | 0 |
| tax.f_name | GIVEN_NAME | 200,000 | 272 | 0 | 0 | 0 | 0 | 272 | 0 |
| tax.l_name | FAMILY_NAME | 200,000 | 694 | 0 | 0 | 0 | 0 | 694 | 0 |
| tax.zip | POSTCODE | 200,000 | 338 | 0 | 0 | 0 | 0 | 338 | 30,973 |
| tax.has_child | BOOLEAN | 200,000 | 200 | 0 | 0 | 0 | 0 | 200 | 0 |
| tax.salary | NUMERIC | 200,000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| tax.rate | NUMERIC | 200,000 | 87,342 | 0 | 0 | 0 | 87,342 | 0 | 187 |
| **total (excl. ounces)** | | | 98,194 | 6,512 | 1,241 | 177 | 88,011 | 2,253 | |

**Reading the misses.** Of the 98,194 scored erroneous cells (excluding `ounces`), 2,253 got a confident
wrong answer. They break down into four kinds:

| kind | cells | where | detectable? |
|---|---|---|---|
| well-formed wrong values | 1,260 | permuted dates in `rayyan.article_jcreated_at` (722), the substituted valid zip `01907` in `tax.zip` (338), flipped `has_child` (200) | not by any syntax normalizer |
| doubled apostrophes, an SQL-escaping artifact | 966 | `Jun''ichi`, `O''Boyle` in `tax.f_name` / `tax.l_name` | passed through unchanged; a repair candidate, not a bug |
| typos | 24 | hospital names (`medxcal`) | not by syntax |
| F-PHONE-VANITY | 3 | hospital phones | yes: the only engine bug among the misses |

The other outcomes:
- **Flagged: 1,241 cells.** Mostly `x`-corrupted zip and phone digits, `0.05%` in `abv`, and the injected
  `yes`/`no` variants.
- **Corrected: 6,512 cells.** For example, `379,998` read as 379998, and `N/A` read as missing on both sides.
- **Equal as number: 88,011 cells**, nearly all `tax.rate` `0.0` vs `0`. These are format differences, not
  data errors.

**Coverage gaps (clean values the engine cannot read):**
- `hospital.address_1`: 1,000 of 1,000. ADDRESS needs libpostal context the scorer does not give.
- `hospital.score` / `sample`: `100%` and `empty`; NUMERIC has no percent.
- `movies_1.release_date`: 7,262 of 7,390, all of the form `8 September 1960 (USA)`. The parenthetical
  makes them INVALID. This column cost about 7.4 ms per value.
- `movies_1.country`: 1,553 multi-valued values such as `USA,UK`.
- `tax.zip`: 30,973 clean values that lost their leading zero (a ground-truth defect).

**Entity-matching keys (DeepMatcher, all labelled pairs, both sides non-empty;
`docs/benchmarks/scripts/em_keys.py`):**

| column | match pairs agreeing (raw → comparison key) | non-match pairs colliding (raw → comparison key) |
|---|---|---|
| Amazon-Google `manufacturer` (COMPANY_NAME) | 140/208 (67.3%) → 143/208 (68.8%) | 204/892 (22.9%) → 213/892 (23.9%) |
| DBLP-ACM `year` (DATE), structured and dirty | identical to raw on every pair | identical to raw on every pair |

On these sets, normalization adds about 1.5 points of match agreement for one extra point of collisions.

## 5. D2 calibration (cost ratio R = 20 as decided; R = 100 as sensitivity)

`uv run python -m normcli calibrate <corpus> --cost-ratio R`. Chow's rule emits an answer only when its
confidence is at least the threshold t.

| corpus | confident answers | ECE (tolerance) | threshold at R = 20 | threshold at R = 100 | flagged bins |
|---|---|---|---|---|---|
| D6 seeded (`--seed 0 --n 30`) | 153 | 0.072 (0.326) | **0.90** | **0.90** | [0.8, 0.9): URL bare host, stated 0.82, observed 0.31 |
| Raha, erroneous cells only | 7,760 | 0.276 (0.046) | **abstain on everything** | **abstain on everything** | [0.9, 1.0]: stated 1.000, observed 0.782; [0.8, 0.9): DATE, stated 0.85, observed 0.000 |

What the Raha corpus covers:
- **What is in it:** only cells with an injected error, from `docs/benchmarks/scripts/raha_calibration_corpus.py`.
- **What is left out:** cells with a missing side, `ounces`, and equal-as-number cells. Unchanged cells
  are left out because scoring them would be circular.

How to read it:
- **What it measures:** how confidence behaves when the input is wrong but well-formed, not the
  engine's calibration on typical data.
- **The LOCAL_VERIFY question** (which literal `1.0` sites sit in a flagged bin): BOOLEAN, COMPANY_NAME,
  GIVEN_NAME, FAMILY_NAME, PHONE and POSTCODE all answer at a stated 1.000 and land in the flagged
  [0.9, 1.0] bin. These are the flipped Y/N, the doubled apostrophes, the substituted zip and the vanity
  phone above.
- **NUMERIC:** 5,505 answers, ECE 0.000.
- **Effect of the threshold:** nothing is wired to dispatch (as decided). At R = 20, a threshold taken
  from this corpus would suppress every answer.

## 6. Throughput and type coverage (tiers B, C, D)

Every completed run's destination row count was checked by direct SQL and equals the source in every
table. Autodetect was on, as in a default job.

| run | engine | rows | normalized cols / all | phase 2 s | rows/s | peak RSS MB (driver / workers) | error rows | status |
|---|---|---|---|---|---|---|---|---|
| NYC taxi 2024-01 | CH→CH | 2,964,624 | 1/19 | 47.97 | 61,802 | 396 / 0 | 0 | COMPLETED |
| TPC-H SF1 | CH→CH | 8,661,245 | 1/61 | 97.54 | 88,797 | 461 / 0 | 0 | COMPLETED |
| UK Price Paid 2024 | PG→PG | 931,453 | 4/17 | 99.57 | 9,355 | 406 / 391 | 0 | COMPLETED |
| SIRENE sample | PG→PG | 500,000 | 3/11 | 50.88 | 9,827 | 410 / 397 | 15 | COMPLETED (column corrupted, §7) |
| Luxembourg addresses | PG→PG | 179,684 | 0/14 | 6.10 | 29,456 | 410 / 0 | 0 | COMPLETED |
| Raha (6 tables) | PG→PG | 214,176 | 11/87 | 21.40 | 10,008 | 418 / 0 | 2,582 | COMPLETED |
| Chinook | PG→PG | 11 tables | 9 detected | 3.03 | – | 404 / 0 | – | COMPLETED |
| OnTime 2022 | CH→CH | 1,598,468 | – | 710 | – | 441 / 410 | – | **FAILED** (stream timeout, 2/2) |
| Norway Brreg | PG→PG | 1,177,617 | – | – | – | – | – | **FAILED** (dotted column names) |
| GLEIF | PG→PG | 3,458,719 | – | – | – | – | – | **FAILED** (dotted column names) |
| Pagila (PG18) | PG→PG | – | – | – | – | – | – | **FAILED** in Phase 1 (`ARRAY`, `DOMAIN` DDL) |
| TPC-H SF10 | CH→CH | 86,586,082 | 1/61 | 1,093.16 | 79,207 | 465 / 0 | 0 | COMPLETED |

Throughput is about 60-90 k rows/s when nearly every column passes through, and about 9-10 k rows/s once
3-11 columns per table are normalized. Memory stayed far under the cap in every run (≤ 461 MB per
process). Peak RSS is flat from SF1 to SF10 (461 → 465 MB for ten times the rows), so memory does not grow
with data size. The caps never fired. The host is shared: during SF10, one of the user's own ClickHouse
servers was using about 60% CPU, so the timings carry that noise. SF10 completes despite F-CH-STREAM only
because almost nothing in it is normalized, so each chunk finishes well inside the 30 s window.

## 7. Findings for the user

Each finding has a reproducer. None is fixed (held-out rule), except F-YEAR00.

### Bugs (wrong output, data loss, or a job that cannot complete)
1. **F-AUTODETECT (severe, default on).** Inferred types are applied to whole columns, confidently,
   with no error rows and no original kept.

   | column | inferred as | result |
   |---|---|---|
   | `ref_france.unite_legale.siren` | PHONE | 499,985 of 500,000 SIRENs written as `+33 9 33 94 21 12` |
   | `raha.hospital.state` (US states) | COUNTRY | `al` → `Albania` (954 rows); one value → `Åland Islands` (10) |
   | `raha.tax.marital_status` | CURRENCY | `S` → `SOS`, `M` → `LSL` (200,000 rows) |

   Coverage misses on the same runs: TPC-H `c_phone`, dates and prices; Luxembourg `code_posta` and
   `rue`; the NYC money columns; Chinook `NUMERIC(10,2)` money. Repro:
   `clone_bench.py --engine postgres --src-db ref_france --dst-db x --country FR --locale fr-FR`, then
   `SELECT siren FROM unite_legale LIMIT 5` on the destination.
2. **F-PG-COLNAME.** The Postgres destination builds `:{column}` bind parameters from raw names
   (`postgres_destination.py:166`).
   - The INSERT fails for names with `.`, a space, `-`, `:` or `%`.
   - The DDL fails for `"`: names are quoted but not escaped, which is also an injection path, since
     the names come from source metadata.
   - The Norway (`organisasjonsform.kode`) and GLEIF (`Entity.LegalName`) clones fail outright.
   - The ClickHouse writer accepts all of these, but fails on a backtick.
   - Repro: `docs/benchmarks/scripts/colname_probe.py`.
3. **F-CH-STREAM.** A ClickHouse source is one streaming `SELECT * ... FORMAT ArrowStream`. While a chunk
   is being normalized the socket is not read, and the server's 30 s HTTP send timeout drops the stream.
   - Run 1 broke after 155,648 of 1,598,468 rows, and the client reported `IncompleteRead` only after
     710 s.
   - Run 2 broke after 296,478 rows.
   - Evidence: `system.query_log` (exception 1002 / 209 `SOCKET_TIMEOUT`).
   - Any wide or slow ClickHouse table can hit this.
4. **F-DECIMAL-SOURCE.** A normalized type (MONEY) on a typed numeric source column fails the whole job:
   `'decimal.Decimal' object has no attribute 'encode'` at `normexec/cache.py:45` (`make_cache_key`).
   Repro: Chinook with `{"invoice":{"total":"MONEY"}}`.
5. **F-CH-BADUTF8.** One ClickHouse `String` holding invalid UTF-8 (`ED A0 80`) fails the whole job:
   `'utf-8' codec can't decode byte 0xed`. Repro table `d1src_badutf8.prices`.
6. **F-NUL-QUEUE** (the D1 NUL check above). A NUL in an AMBIGUOUS value fails the job and drops the
   batch's error rows.
7. **F-PAGILA-DDL.** Phase 1 renders `text[]` as a bare `ARRAY` and the `year` domain as `DOMAIN`, so
   `CREATE TABLE film` is a syntax error. pgvector's `vector` is also unrecognised.
8. **F-PHONE-VANITY.** A corrupted `3342938xxx` becomes the confident `+13342938999`: letters are read as
   keypad digits, so damaged digits turn into a guessed number. Found in Raha hospital.
9. **F-YEAR00** (regression from this branch's e0f7ed8; **fixed** in ef60e8a with the user's go-ahead).
   `12/31/00`, `1/00` and `1/1/00` (with country US) had become INVALID. After the fix, 0 diffs against
   the pre-e0f7ed8 normalizer on 11,564 distinct real date values × 2 contexts.

### Design findings and expected limitations
- **F-VERDICT-SCOPE.** A verdict's key includes the saved connection id. Re-adding a connection, for
  example after a password rotation, silently orphans every verdict made under it.
- **F-CH-TRUNC** (D5 above). ClickHouse truncates excess fraction digits where Postgres rounds; neither
  writes an error row.
- **D7 Norway.** 0% VALID on a full national register: the chosen Norwegian module is not the
  organisation-number one.
- **D3.** Lineage events carry no schema facet, so Marquez's column-lineage graph is empty.
- **D4.**
  - `''` is reported for COUNTRY and DATE but not for URL, EMAIL, PHONE or NUMERIC. Brreg alone has
    1,063,494 empty `hjemmeside` values that go unreported.
  - The sentinel `empty` (×167, not in the missing-value table) is not reported.
  - Valid-looking placeholders (`1900-01-01` ×3,408 in SIRENE) are invisible by design.
  - `XK` (Kosovo, ×47) is reported as a non-conforming candidate.
- **Performance (finding k, measured).** Free-text dates that miss the fast paths
  (`8 September 1960 (USA)`) cost 10-430 ms each.
- **Undetectable by a syntax normalizer:**
  - well-formed wrong values (permuted dates, `N`↔`Y`, a substituted valid zip);
  - typos inside names (`medxcal`).
- **Ground-truth issues in Raha:**
  - `tax.zip` clean values drop leading zeros (the dirty `02909` is the correct one);
  - `rayyan.jvolumn` uses `-1` for missing;
  - `beers.ounces` clean values drop the unit, so that column was not scored.
- **Doubled apostrophes** (`O''Boyle`, `Jun''ichi`), an SQL-escaping artifact, pass through the name
  normalizers unchanged (966 Raha tax cells). Folding them would be a repair, so it is a candidate,
  not a bug.
- **D6 CSV loader context.** The dirty/clean CSV loader takes no country or locale, so on real data
  PHONE and POSTCODE abstain on every cell. The literal D6 command therefore cannot score context-needing
  types.
- **Confidence on well-formed wrong input.** Answers at a stated 1.0 were observed right only 78% of the
  time on Raha's erroneous cells (§5), and permuted dates at 0.85 were never right.
- **NUMERIC comparison key.** `7.0` and `7` give different comparison keys though they are the same
  number. Whether the key should be value-canonical is a design question.

### Test and documentation findings (Steps 2-3 of the close-out)
- **75 unmarked tests.** They live in `tests/unit` but carry no `unit` marker, so ci-fast never selects
  them. Files: `test_date_precision.py` 22, `test_multivalue.py` 16, `test_unit_normalizer_hostile.py` 14,
  `test_clone_field_autodetect.py` 10, `test_clone_perf_paths.py` 9, `test_clickhouse_read_order.py` 4.
  All 75 pass today.
- **Two D2 acceptance tests depend on a clean working tree.** They assert
  `git diff HEAD -- packages/<pkg>` is empty, so they fail for anyone with uncommitted edits.
- **`normcli` is not a console script.** LOCAL_VERIFY.md and README write `normcli ...`; the working form is
  `uv run python -m normcli ...`. (`uv run normalizer` resolves to charset-normalizer's CLI.)
- **`24/03` → `2024-03`.** `24` is read as a two-digit year, though "24 March, no year" is just as possible.
  This predates the branch and was not touched.

## 8. Reproduction

- **Scripts:** in `docs/benchmarks/scripts/` (all against the isolated `normbench` stack, with test
  credentials from the project's fixtures):
  - `clone_bench.py`: one clone end to end through the API; records timing, RSS, plan, quality,
    lineage.
  - `d5_gate_probe.py`: the D5 gate against the real typed columns.
  - `d7_registry_check.py`: the app's verdict against python-stdnum.
  - `d4_live.py`: GROUP BY → detector.
  - `raha_accuracy.py`: the Raha canonical-truth scorer.
- **Setup:** the compose override and the loaders lived under `.tmp/`, a local scratch area that is not
  committed. Since 2026-10-18 the stack, datasets and working files live in `$BENCH_DIR` (outside the
  repo: `compose.yaml`, `config/`, `datasets/`, `work/`); the scripts read it from the `BENCH_DIR`
  environment variable, and their small field configs are in `docs/benchmarks/configs/`.
- **Raw results:** they stay local because they hold dataset values. This report quotes only counts and
  short examples.

## 9. fix/robustness: the §7 bugs fixed and re-measured (2026-10-13)

Branch `fix/robustness` from main at dcb739e. Each bug got a reproducer first
(`tests/unit/test_robustness.py`, committed as strict xfail and run against main's
code; live counterparts in `tests/integration/test_robustness_live.py` against
the normbench Postgres 16 and ClickHouse 24.9), one root-cause fix in the shared
place, then the benchmark that found it, rerun with the same arguments as in §6
(held out: no normalizer, dictionary or threshold was changed to move a number).
Every pass below was decided by direct SQL on source, destination and metadata
database, not by the job status.

### Step 1: starting point
D1 NUL and D5 ClickHouse truncation were NOT fixed on main (both reproduced, below);
ci-fast was green on main (run 38364358452); the normbench stack was up.

### Reproduces on main?

| bug | reproduces on main | fix commit |
|---|---|---|
| D1 NUL in an AMBIGUOUS value fails the job, loses the batch's error rows | yes | d682b51 |
| D5 ClickHouse truncates / Postgres rounds excess fraction digits silently | yes | dd957b2 |
| F-AUTODETECT applied to whole columns by default | yes | 792a9cc |
| F-PG-COLNAME (`.`, space, `-`, `:`, `%`, `"`; backtick on ClickHouse) | yes | ed9c141 |
| F-CH-STREAM (server drops the stream after 30 s of not reading) | yes, live: IncompleteRead after 57,344 of 400,000 rows | f7bc88f |
| F-DECIMAL-SOURCE | yes | 4be3fa7 |
| F-CH-BADUTF8 | yes | 4be3fa7 |
| F-PAGILA-DDL (`ARRAY`, `DOMAIN`, unknown extension types) | yes, live | 9a51bd8 |
| F-PAGILA-UUID (new: PG18 uuid values have no Arrow type; hidden behind the DDL bug) | yes | 645019f |
| F-PHONE-VANITY (`xxx` -> `999`) | yes | b4836b1 |
| 75 unit tests never selected by ci-fast | yes | 75cdc9f |

### What changed
- **D1 NUL.** `PgPersistence` stores a value containing U+0000 as its JSON string
  literal (`json.loads` gives back the exact value) and says so where it is stored:
  the error text, or `detail.original_encoding = "json"` in the queue. All other
  values are stored unchanged.
- **D5.** The cast gate refuses any non-zero value with more fraction digits than the
  column's scale: NULL plus an error row, the same as overflow, on both engines.
  Trailing zeros still fit, and unbounded Postgres NUMERIC keeps every digit. Two D5
  acceptance tests encoded the opposite ("a tiny value is never rejected", meaning it
  was stored as 0) and were updated.
- **Autodetect (decision taken: default OFF).** Detection still runs. The job stores
  `suggested_field_types` and the plan shows a `suggestion` for every unconfigured
  column: type, detector confidence, `validated_share` (the share of sampled values
  the type's own validator accepts under the job's country and locale) and the
  sample size. Nothing is written unless the column is opted in: per column by giving
  it the type (in the request or with `PATCH .../plan`), or per job with
  `autodetect_field_types: true`, which is the old behaviour and keeps the old gate.
  No new threshold was introduced.
- **Identifiers.** There is one `quote_identifier` per engine, used by the DDL,
  insert, swap and drop paths, the ClickHouse source read and the sorting-key
  parse. Postgres binds are positional.
  - ClickHouse reports the sorting key with names already backquoted (`` `a.b` ``);
    the old comma split then re-wrapped them.
  - The driver leaves a table name containing `.` unquoted, so the destination
    insert now passes a pre-quoted `db.table`.
  - `CREATE DATABASE "x"` with `""` escaping was checked live on both engines.
- **ClickHouse stream.** `read_table` drains the server stream on a thread into
  zstd Arrow files under `$TMPDIR`, one per block, each deleted once read back.
  The server never waits on normalization, memory stays at one block, and the
  single SELECT keeps its snapshot. Ceiling (noted in the code): disk holds the
  drained but unread part, at most the table compressed.
- **Decimal, UTF-8 and UUID.**
  - Normalizers receive the value's text (Decimal, timestamp, int).
  - A ClickHouse String column with invalid UTF-8 arrives as binary for that block.
    In a normalized column those bytes are not normalized: the cell keeps them
    (NULL in a typed column) and an error row shows them backslash-escaped.
  - A value Arrow cannot type (uuid) is read as its text, and Postgres casts it back.
- **Pagila DDL.** Postgres `get_columns` uses `format_type`.
  - A domain becomes its base type, so the CHECK is not copied.
  - Any non-built-in type (enum, citext, vector, arrays of those) becomes `text`.
  - Values are preserved; the constraint is not.
- **Phone.** `phonenumbers.is_alpha_number` (libphonenumber's own keypad-conversion
  condition) leads to AMBIGUOUS with the original kept. Vanity numbers
  (`1-800-FLOWERS`) are AMBIGUOUS too, because the two cannot be told apart. The D10
  byte-identical test exempts exactly the alpha inputs.
- **CI.**
  - `tests/unit/conftest.py` marks every test under `tests/unit` as `unit` by
    location. All 75 tests pass; the slowest takes 1.3 s, so none needed `slow`.
  - Running them pushed ci-fast past its 5-minute job timeout (main already took
    4m22s), so the timeout is now 10 minutes. No test was skipped to fit. Green
    run: 38399297104, 3m09s.

### Reruns (same arguments as §6, autodetect opted in as it was then; caps as in §1)

| run | before (§6/§3) | after | phase 2 s | independent check |
|---|---|---|---|---|
| D1 NUL (CH `d1src`, MONEY+PHONE) | FAILED, batch's error rows lost | COMPLETED | 1.0 | 4/4 rows; the NUL row's error row stored as `"1,234\u0000"`, `json.loads` gives the exact original; 4 queue entries, NUL ones marked `original_encoding: json` |
| D5 on ClickHouse (`d5src`) | `12.34565`→`12.3456`, `0.00005`→`0`, no error row | COMPLETED | 1.0 | 6/6 rows; row 1 `12.5`; rows 2-6 NULL in both columns, each with an error row keeping the original |
| D5 on Postgres (twin `rb_d5src`) | rounded half-up silently | COMPLETED | 1.0 | 6/6; MONEY identical to ClickHouse (only row 1 stored); unbounded NUMERIC keeps every digit (`1e999` as 1,000 digits, `0.0000000005`) |
| bad UTF-8 (CH `d1src_badutf8`) | FAILED | COMPLETED | 1.0 | typed MONEY cell NULL + "not valid UTF-8" error; text PHONE cell byte-identical (`…EDA080`, hex compared) |
| SIRENE, product default (autodetect off) | 499,985 SIRENs written as phones | COMPLETED | 15.6 | 500,000/500,000; `siren` differs in 0 rows (joined on `_bench_row`); the plan suggests PHONE (confidence 0.90, 95% of 200 sampled values validate) and writes nothing |
| Norway Brreg | FAILED (dotted names) | COMPLETED | 96.2 | 1,177,617 both sides; 9 dotted columns; 0 differing rows in the 2 compared dotted passthrough columns |
| GLEIF | FAILED (dotted names) | COMPLETED | 595.2 | 3,458,719 both sides; 15 dotted columns; md5 over every `Entity.LegalName`/`Entity.LegalAddress.City` value identical |
| Pagila (PG18) | FAILED in Phase 1 (DDL) | COMPLETED (after the uuid fix; first rerun FAILED on F-PAGILA-UUID) | 13.2 | 71/71 tables, every row count equal (173,270 rows); its 7 views are not cloned (clones copy tables) |
| TPC-H SF1 | COMPLETED, 97.5 s | COMPLETED | 106.6 | every table's count equal; `sum(c_acctbal)` and `sum(l_extendedprice)` equal |
| OnTime 2022 | FAILED at 155,648 / 296,478 rows (stream timeout) | **FAILED, new cause** at 1,407,955 rows | 14,687 | stream: no timeout; whole result spooled (≤ 160 MB on disk, then shrinking). Committed rows: 1,407,955, all distinct and all present in the source (hash anti-join, 0 missing) |
| TPC-H SF10 | COMPLETED | not rerun (needs your go-ahead: ~20 min, 86M rows) | – | – |

### Remaining failures (minimal reproducers)
- **F-CH-INSERT-OOM (new).** OnTime FAILED after 4 h on one 2,000-row INSERT:
  `MEMORY_LIMIT_EXCEEDED`, "Memory limit (total) exceeded … maximum: 3.60 GiB". The
  INSERT itself used 4.7 MB; the server was at its cap, which is the benchmark's
  4 GB `docker update` limit. Every 2,000-row insert is a new part of a 109-column
  MergeTree: 859 parts, 166 merges, each merge peaking at ~600 MB. ClickHouse's
  own `MemoryTracking` metric read 50-98 GiB the whole time, so its accounting
  drifted. The job is FAILED and cannot be resumed through the API (only
  SCHEMA_READY/RUNNING can be claimed). Reproducer: §6's OnTime run with
  ClickHouse capped at 4 GB. Not fixed. Candidates are larger insert blocks for
  ClickHouse destinations or resume-from-FAILED; both are design changes for you
  to decide.
- **OnTime throughput.** About 95 rows/s with WheelsOn as DATETIME and
  ArrivalDelayGroups as MONEY. The pre-fix run did ~220 rows/s before it died.
  Profiling detection shows dateparser costs 0.1-0.2 s per value that misses the
  date fast paths (§7 "finding k"); this run also shared the CPU with test runs.
  The cause of the 2x gap is not verified.

### Logged, not fixed (as asked)
- **F-VERDICT-SCOPE.** A verdict key includes the saved connection id, so a
  re-added connection orphans its verdicts. Unchanged.
- **Norway tax IDs never VALID.** 1,177,617 UNKNOWN (§3 D7): the chosen module is
  not `no.orgnr`. Unchanged.
- **Scheduled `drift` workflow.** It fails daily (exit 2, a drift-report artifact)
  since at least 2026-10-09 on main. Not investigated.
- **Detection cost.** Each sampled non-date value costs 0.1-0.2 s in dateparser
  through the DATE/DATETIME validators, at job creation. A related observation:
  relaxed name matching suggests PHONE (confidence 0.27, 0% validating) for
  SIRENE's `…UniteLegale` columns ("uni**teLe**gale"). Shown, never applied.
- **`33429381O23`** (a letter O among the digits) is still read with the O
  dropped. libphonenumber drops fewer than three letters without converting
  them, and is_alpha_number does not fire. Not reported in the data; noted.

### CI and memory
The four ci-fast commands, run exactly as CI runs them under `ulimit -v 16 GB`:
ruff, ruff format and mypy are clean; pytest gives 2,961 passed, 22 skipped and
4 xfailed in 131 s (before: 2,852 passed). On GitHub, run 38399297104 is green
(3m09s). Integration (Postgres/ClickHouse files only; Mongo/MySQL are not in
normbench): `test_clone_pipeline.py` + `test_robustness_live.py` give 17 passed.

## 10. fix/followups: what §9 left, fixed and re-measured (2026-10-13/14)

Branch `fix/followups` from main at 152d685. ci-fast was green on main (run
38406488647); the normbench stack was up; `/tmp` had 149 MB free, so every
spool went to `.tmp/spool` on `/home` (50 GB free). Each item got a reproducer
first (`tests/unit/test_followups.py`, run on main's code:
24 of 41 failed, the other 17 are guards that must keep passing; live ones in
`tests/integration/test_followups_live.py`), then one root-cause fix, then the
benchmark that exposed it, rerun with §6's arguments as a check (held out: no
normalizer, dictionary or threshold was tuned to it). Every verdict below is
from direct SQL on source, destination and metadata database. Two decisions
were asked and taken: resume from the last committed block (item 2), and
disable the drift schedule rather than build it (item 5). Two of my own first
fixes were wrong and are corrected below (items 1 and 2), each found by a
rerun, not by a test.

### Results

| item | before | after | commits |
|---|---|---|---|
| 1 ClickHouse insert memory | OnTime FAILED after 4 h, server at its 4 GB cap | OnTime COMPLETED (A3): every merge vertical, peak 16 MiB; each INSERT ≤ 4.8 MiB | 130dc96 (supersedes afb36f4) |
| 2 resume a FAILED job | `/start` refused FAILED; 4 h of rows lost | FAILED and killed jobs resume through the API; exact on both engines (counts below) | b4de4bb, 4e10264, e22b8eb |
| 3 spool free space | the spool could fill `/tmp` silently | refused before any row is read: OnTime with TMPDIR unset is FAILED after 1.03 s, naming table, bytes, directory and TMPDIR | a564afc |
| 4 `33429381O23` | the O dropped: confident `+1 334-293-8123` | AMBIGUOUS, original kept; PHONE, DATE/DATETIME and MONEY checked by a property test | 2188d95 |
| 5 drift workflow | red daily since at least 2026-10-09 | no schedule; header says what is missing; a test checks every self-triggered workflow | 14e852b |
| 6 OnTime throughput | ~95 rows/s | 13,114 rows/s end to end (A3), cause profiled first | e6e5b0a |
| 7 OnTime end to end | FAILED | COMPLETED, row-for-row equal (below) | – |

### 1. ClickHouse insert memory: the merge algorithm, not the insert size
- **First fix, wrong.** I sized inserts at the server's
  `vertical_merge_algorithm_min_rows_to_activate` (131,072 rows), on the theory
  that merges of tiny parts were the cost. OnTime then FAILED after 74 s, not
  4 h: `query_log` shows one 131,072-row INSERT of 110 columns using 611 MiB.
- **Measured.** 262 parts of 2,000 OnTime rows into two tables. ClickHouse
  defaults: 44 horizontal merges, peak 562 MiB, average 497 MiB. With
  `vertical_merge_algorithm_min_rows_to_activate = 0`: 48 vertical merges, peak
  14 MiB. A 2,000-row INSERT uses about 5 MB.
- **Fix (decision asked).** Phase 1 creates MergeTree destination tables with
  that setting; inserts stay at 2,000 rows, as on Postgres. In A3: 800 INSERTs,
  max 4.80 MiB each; 139 vertical merges, peak 16.16 MiB; 13 horizontal, peak
  23.07 MiB; at most 11 active parts.

### 2. Resume: exact only where the source order is
- **The claim.** FAILED is now claimable like a crashed RUNNING job, and the
  stale error is cleared.
- **First fix, wrong.** I relied on a ClickHouse dedup token per block (b4de4bb).
  Two real kill-and-resume runs then found that the problem is the read order,
  not replays:
  - **Postgres (UK Price Paid, no PK).** The resumed clone had 931,453 rows but
    only 525,453 distinct: 406,000 rows twice and 406,000 never, exactly the
    rows committed before the kill. The SQL read had no ORDER BY, and Postgres
    let the new sequential scan join the killed job's scan, still running
    mid-table (`synchronize_seqscans`; the table is 164 MB, over a quarter of
    `shared_buffers`). Tables with a PK could lose rows the same way:
    ON CONFLICT stops duplicates, not gaps.
    - Fix 4e10264: order by the PK, else `ctid`.
    - Reproducer: with a second connection holding a scan half-way, the read
      returned row 167,536 first; now row 0.
  - **ClickHouse (OnTime, no sorting key, 2 parts).** The resumed clone had
    1,598,468 rows, 1,580,515 distinct: 17,953 twice and 17,953 never.
    - The same `LIMIT 1000 OFFSET 700000` read three times returned three
      different row sets.
    - A non-unique sorting key has the same ties.
    - `max_threads = 1` would make the order stable, but a `readonly = 1`
      profile (ours, and the usual read-only account) cannot set it.
    - A total `ORDER BY _part, _part_offset` ran the server out of memory in a
      full sort.
    - Fix e22b8eb: an unfinished ClickHouse table starts over on resume. It is
      truncated, its error rows are deleted (their `row_index` named the old
      order's rows) and its checkpoint is reset; finished tables are skipped.
      The token and window were removed: nothing is replayed, and a token
      reused after a TRUNCATE could have made ClickHouse drop the new blocks.
- **Proofs (direct SQL).**

  | run | kill | result |
  |---|---|---|
  | live test, ClickHouse, 3-part no-key source | child dies right after block 2 commits | 30,000 rows, 30,000 distinct, 10,000 error rows (before e22b8eb: 20,000 distinct) |
  | live test, Postgres with PK | same | 30,000 / 30,000 / 10,000 |
  | C2: UK Price Paid, PG→PG, no PK | SIGKILL of the cgroup at 418,000 rows (69 s) | resume COMPLETED in 58.96 s; 931,453 rows, 931,453 distinct `transaction_id`, as the source |
  | B4: OnTime, CH→CH | FAILED by itself at 374,000 rows (ClickHouse memory, below) | resumed through the API: COMPLETED in 120.31 s; 1,598,468 rows; multiset hash over the 107 passthrough columns equal to the source's; 0 error rows |
  | B5: OnTime, CH→CH | meant to SIGKILL at ≥ 500,000 rows | did not get there: FAILED by itself at 280,000 rows, 2 min after a fresh ClickHouse restart (server memory, below); not repeated. The no-cleanup kill on ClickHouse is the live test above |

- **Ceilings (noted in code).**
  - A Postgres table without a PK, killed in the moment between a block's
    commit and its checkpoint commit, writes that block twice.
  - A restarted ClickHouse table's rows are counted a second time in the
    adjudication queue's occurrences.

### 3. Spool free space
The estimate is the largest pending table's compressed size on the server
(`system.tables.total_bytes`); the spool holds one table at a time. The spool
was measured by writing it exactly as `_spooled` does:

| table | total_bytes | spool (zstd Arrow) | spool / total_bytes |
|---|---|---|---|
| ontime.ontime_2022 | 172,978,631 | 169,021,728 | 0.977 |
| nyc_taxi.yellow_2024_01 | 104,424,190 | 74,325,246 | 0.712 |
| tpch_sf1.lineitem | 304,638,300 | 242,800,662 | 0.797 |
| tpch_sf1.orders | 64,620,870 | 53,740,274 | 0.832 |

No factor is applied. On the live run the estimate (172,978,631 bytes) exceeded
the 170,592,256 bytes free, while the real spool (169.0 MB) would just have
fit: 2% conservative on OnTime.

### 4. Silent letter drops: one cause, three places
The shared cause: each normalizer trusted a lenient parser that drops what it
cannot place. A sweep inserting characters into good values found letter drops
in exactly three types.

| type | what dropped the letter | guard |
|---|---|---|
| PHONE | libphonenumber drops fewer than three letters | a letter run whose deletion leaves the parse unchanged was not read: AMBIGUOUS |
| DATE/DATETIME | dateparser's all-locale detection: `1O/15/2024` → 2024-01-15 (Polish skip word `o`); `l2:34:56` → 02:34:56 (Estonian `L`, Saturday) | a letter run glued to a digit that reads as digits under Unicode TR39 (O, I, l), or only filler words in the detected language with one glued to a digit |
| MONEY | CURRENCY scans for a code anywhere (`1234.56O USD` → USD) | several words must be a whole currency name |

- **Property test.** For every digit-bearing type, a TR39 digit look-alike
  inserted anywhere in a good value never gives back the same confident answer.
  The letters are derived from ICU, not listed.
- **Held-out check.** main (152d685) against this branch on real distinct values:
  - DATE: 11,483 values, 0 changed;
  - DATETIME: 789, 0 changed;
  - MONEY: 308, 0 changed;
  - PHONE: 197,629 values, 12 changed, all x-damaged Raha hospital phones
    (`2058x8x122`), INVALID → AMBIGUOUS. None was a confident answer before.
- **Also closed.** The D10 strict-xfail residual: with two extension markers
  the first was merged into the number; it is now refused, for the same reason.
- **Two D10/D2 tests updated, each with a comment.**
  - The byte-identical PHONE corpus now allows exactly the moves toward
    AMBIGUOUS-with-original for inputs with letters: two of 1,014.
  - The D2 confidence-literal count goes 61 → 62: the new refusal's `0.0`.

### 5. drift and the other workflows
- **drift.yml.** It could never pass. Three pieces were never built:
  - the pytest option `--golden-report`;
  - `normcli drift-diff`;
  - `tests/golden/expectations/`.

  The cron trigger is removed (manual dispatch kept).
- **The other workflows.** A new test checks every workflow that runs on its own
  (schedule, push, pull request): each normcli command it calls and pytest
  option it passes must exist. That found five more missing commands, held in
  the test as a ratchet: `gate.yml` (milestone pushes; `bench-compare`, `run`,
  `diff`, `sbom`, `gate`) and `release.yml` (milestone tags; `sbom`).

### 6. OnTime throughput: profiled first
- **Profile.** cProfile, in one process, on the first 4,000 OnTime rows, with
  the job's own configs (WheelsOn DATETIME, ArrivalDelayGroups MONEY,
  US/en-US):
  - 299 s in total, all of it in dateparser;
  - 1,873 DATETIME normalize calls caused 385,838 per-locale parse attempts
    (about 103 locales per value, 0.16 s per value);
  - inside dateparser, `regex._compile` was called 20.9M times (131 s
    cumulative) and `strptime` 4.6M times (213 s).
- **Cause.** WheelsOn has 1,441 distinct values in 1.6M rows, but the planner
  dedups only within a 2,000-row chunk (about 937 distinct), so each value was
  paid for about 800 times. The executor's own ponytail note named this upgrade.
- **Fix.** Results are remembered across the job's chunks, per (type, context,
  profile), up to one read batch of distinct values per key.
- **Measured.**
  - 40,000 rows in 213 s in one process (188 rows/s, from 13).
  - End to end, OnTime phase 2 took 121.89 s for 1,598,468 rows, which is
    13,114 rows/s.
- **The "2× slower" claim in §9 does not hold.** The pre-fix run with the same
  configs committed 73,728 rows in 710 s, which is 104 rows/s.
- **Latent bug the memo exposed (fixed).** `NormalizationContext.context_hash`
  is a cached property, and pydantic's `model_copy` copied the cache. So a copy
  with another country kept its parent's hash, and the no-country retry of a
  cross-table country was served the country's result.
- **Remaining candidates (not done).**
  - Restrict dateparser to the job's locale language when one is given. That
    is a semantic change, for you to decide.
  - Build `DateDataParser` once per settings: `dateparser.parse` builds one per
    call.
  - `regex`'s compile cache thrashing inside dateparser is upstream.

### 7. OnTime end to end (A3; caps as in §1: job 6 GB cgroup, ClickHouse 4 GB)

| measure | value |
|---|---|
| status | COMPLETED |
| rows (direct SQL) | source 1,598,468; destination 1,598,468 |
| identity | sum and uniqExact of cityHash64 over the 107 passthrough columns: equal, all distinct |
| normalized columns | NULL exactly where the source has `''` (64,255 / 67,083); 0 error rows |
| phase 2 / wall | 121.89 s / 186 s |
| throughput | 13,114 rows/s (§9: ~95) |
| peak RSS | 531 MB API process, 475 MB workers |
| ClickHouse | 800 INSERTs ≤ 4.80 MiB; merges vertical ≤ 16.16 MiB; ≤ 11 active parts; container cgroup peak 2.61 GiB |

The full run took 3 minutes, so it was run in full (no slice). TPC-H SF10 was
not rerun.

### The ClickHouse server itself (environment, not fixed)
These failures were the server's, not the job's.
- **What happened.**
  - A2 FAILED: its source SELECT (324 MiB) was killed by the total limit,
    which ClickHouse wrote into the HTTP stream mid-body. The Arrow reader then
    parsed `Code` as a length: "Expected to read 1701080899 metadata bytes"
    (1701080899 = 0x65646F43).
  - B2 resume and B4 FAILED on 5 MB inserts.
- **ClickHouse 24.9 counts its container's page cache against its own
  limit.** The idle cgroup was at 3.35 GiB:

  | part of the cgroup | size |
  |---|---|
  | anonymous memory (the server's own) | 1.30 GiB |
  | page cache | 1.00 GiB |
  | kernel | 0.14 GiB |

  The server refuses allocations at 3.6 GiB, so the kernel never gets the
  pressure that would reclaim the cache.
- **Its own tracker drifts upward.** `MemoryTracking` read 4.6-6.9 GiB, and
  earlier 99-278 GB, while resident memory was 1.5-1.8 GiB. One failure said
  "would use 3.60 GiB, current RSS 1.53 GiB".
- **Workaround used (asked, approved).** `docker restart` of the normbench
  ClickHouse, keeping volumes and the 4 GB cap. A3 and the B4 resume each ran
  right after a restart.
- **Flaky test.** `test_robustness_live.py` failed once on this tracker while
  generating test data; it passed on rerun.

### Remaining failures (minimal reproducers)
New, found here, and fixed afterwards on your request (each one's reproducer
is in `tests/unit/test_followups.py`; on real values neither changed anything
against main: DATE 11,483 and QUANTITY 32 distinct values × 2 contexts):
- **QUANTITY crashes** (d10169d). pint's unit parser raised `AssertionError`
  (41 fuzzed inputs, e.g. `12# kg`, `12 kg*`) and `tokenize.TokenError` on any
  quote (125, e.g. `12" kg`) out of the normalizer, failing the job. Both are
  now caught and the value is INVALID. The reproducer fuzzes every printable
  character at every position.
- **Precision invented** (a4d079f). `15 Z 2024` gave 2024-<today's month>-15:
  any word counted as the month, so dateparser's time-zone `Z` did. Now only
  the parsed month's name in the detected language counts (dateparser's locale
  data); `15 Z 2024` is INVALID, while `15 März 2024` and `March 2024` are
  unchanged.

New, found here, not fixed:
- **Time dropped.** DATETIME `3pm March 15 2024` → `2024-03-15`.
- **Times read as years.** OnTime WheelsOn (HHMM) typed DATETIME, as opted in
  in §9: `2220` normalizes as the year 2220. Precision is kept, the meaning is
  not.
- **Missing commands.** gate.yml and release.yml call five normcli commands
  that do not exist (item 5).

### Logged, not fixed (as asked)
- **F-VERDICT-SCOPE.** A verdict key includes the connection id. Unchanged.
- **Norway tax IDs never VALID.** The module is not `no.orgnr`. Unchanged.
- **TPC-H SF10.** Not rerun (about 20 min, 86M rows); needs your go-ahead.

### CI and memory
The four ci-fast commands, run exactly as CI runs them under `ulimit -v 16 GB`:
- **Static checks.** ruff, ruff format and mypy are clean.
- **pytest.** 3,005 passed, 22 skipped and 3 xfailed in 118 s (§9: 2,961 passed).
  - One test changed engine: the ADR-018 "a resume never counts twice"
    harness now runs as Postgres, where blocks are skipped.
- **Integration.** Postgres/ClickHouse files only; Mongo/MySQL are not in
  normbench. `test_followups_live.py`, `test_robustness_live.py` and
  `test_clone_pipeline.py`: 21 passed.

## 11. Part 1 complete: every gap closed and re-measured (2026-10-14/17)

Five branches from main at 002eda0 (`fix/followups` merged), in merge order: `fix/confident-wrong`
(B1), `fix/verdict-identity` (B2), `fix/lineage-and-dates` (B3), `fix/calibration-coverage` (B4,
stacked on B3), `fix/ci-gates` (B5, stacked on B4). The row-by-row record is
`docs/archive/plans/defects/PART1_TRACEABILITY.md`. Each fix: a reproducer that fails on main, one root
fix in the shared place, a held-out check on real data. Every verdict below is direct SQL (or the
service's own API: Marquez), never a job status.

### 11.1 Environment
- normbench as in §1, except ClickHouse: 25.12 (image already local) with
  `memory_worker_use_cgroup` and `memory_worker_correct_memory_tracker`, capped at 6 GB, override
  only (`compose.yaml` keeps 24.9). Before: `MemoryTracking` read 43.6 GiB at 1.0 GiB resident
  memory on 24.9; after a start, 573 MiB. No ClickHouse memory failure in this section.
- The machine restarted on 2026-10-15; the stack was started again with its volumes.

### 11.2 Guesses shown as answers (B1)
Reproducers: `tests/unit/test_confident_wrong.py` (124 cases, two properties). Held out: main and
B1 on the same real distinct values (Raha, Brreg, SIRENE, GLEIF) through the full dispatcher in
7 contexts (none, US, GB, NO, FR, en-US, fr-FR).

| finding | before (main) | after | real values moved |
|---|---|---|---|
| N4 M/d/y from a hand table `{US}` | `10/7/2026` ee-GH -> 07-10 | CLDR per locale; per country the order all official languages agree on | — |
| N9 equal day and month | `05/05/2024` AMBIGUOUS | 2024-05-05 | 45 (`1/1/00` ...) AMBIGUOUS -> PARSED |
| N1 time dropped | `3pm March 15 2024` -> 2024-03-15 | 2024-03-15T15:00:00 | 35 DATETIME keep their time |
| N2 HHMM as a year | DATETIME `2220` -> the year 2220 | AMBIGUOUS (ISO 8601 reads both) | 4-digit DATETIME values that are a valid hhmm |
| N10 day-month or month-year | `24/03` -> 2024-03 | AMBIGUOUS | — |
| N12 found by the held-out run | no_NO counted as a disagreeing language; `1/13/01` under D/M/Y read as 2013-01-01; `11/30 10:30 p.m.` read as 2030-11 | Babel-less languages skipped; a numeric value must read in the stated order (else INVALID); a time's digits are no day or month | 248 DATE (`1/13/xx` under GB/NO/FR) PARSED -> INVALID, the main answer was wrong; `11/30 <time>` -> AMBIGUOUS |
| N3 https assumed | `example.com` -> https://example.com, 0.8 | AMBIGUOUS, both schemes as candidates, host and registrable domain still reported | 34,853 Brreg websites NORMALIZED -> AMBIGUOUS |
| N5 `NA` | COUNTRY `NA` -> missing | AMBIGUOUS (Namibia or missing) when a discriminating type reads the token | 7 |
| N7 never INVALID | PHONE `TBD`, CURRENCY `TBD` AMBIGUOUS; `¥` -> JPY, `£` -> GBP (hand table) | INVALID; a CLDR-shared symbol (11, generated) AMBIGUOUS, resolved by the country's tender | 364 US state codes in a CURRENCY column AMBIGUOUS -> INVALID |
| N11 locale | NUMERIC/MONEY country=NO raised UnknownLocaleError (job failed); a country = its first language | every official locale Babel has is a reading; disagreement AMBIGUOUS | 307 MONEY values under NO raised -> parse |
| N8 one pass; silent repair | `-\x00` -> `-` -> missing on pass 2; names applied ftfy silently (`ß\x85` -> an NKo digit) | tokens judged on visible text; REPAIRED with flags for every text sibling | 0 failures on the sweep (1,128 values x 8 types) |
| N13 (found live, §11.9) | an INVALID phone's cell held a rewrite (`334774x601` -> `+47 334774 ext. 601`), no error row | original kept, no comparison key, an error | — |

The seeded gold corpus (`gold generate --seed 0 --n 30`): 142 / 21 / 11 / 6 / 0 before, **149 /
31 / 0 / 0 / 0** after (correct / correct-abstain / wrong-confident / over-abstain / wrong-status);
seeds 0-2 at n 200: 0 wrong-confident, 0 over-abstain.

### 11.3 D1: a verdict survives a re-added connection (B2)
- Key: `context.source` is `engine://host:port/database[/schema]`, not the connection id
  (ADR-018 amended).
- Live (`docs/benchmarks/scripts/d1_identity_roundtrip.py`), Postgres and ClickHouse: job 1 on
  connection A queues `03/04/2024` (occurrences 5); verdict `2024-04-03`; A deleted; the same
  server saved again (B, a new id); job 2 on B: 5/5 cells `2024-04-03`, the clean date unchanged,
  1 queue row (occurrences 5). Before: the verdict was orphaned.
- Startup migration on the normbench metadata database: 2,696 legacy queue rows re-keyed to
  2,488 (208 merged: several connection ids of one source); 0 left; both earlier verdicts kept and
  copied. The first live run found the merge case (a primary-key violation, rolled back); fixed.
- D1.5 live (`tests/integration/test_verdict_identity_live.py`): ClickHouse, 3 parts, no key,
  child killed after block 2, resumed: 10,000 occurrences for 10,000 ambiguous rows. Main's code
  on the same test: 13,333.

### 11.4 D3: the Marquez column graph (B3)
The events now carry a SchemaDatasetFacet on inputs and outputs, every field typed (the source's
native type; the destination's type as Phase 1 wrote it). Marquez 0.51.1,
`/api/v1/column-lineage`:

| engine | destination field | graph |
|---|---|---|
| Postgres (Chinook) | invoice.total_currency | <- chinook.invoice.total |
| Postgres (Chinook) | customer.phone_code | <- chinook.customer.phone |
| ClickHouse (d1src) | prices.amount_currency | <- d1src.prices.amount |
| ClickHouse (d1src) | prices.phone_code | <- d1src.prices.phone |

Before: 0 nodes. Found live: an untyped field is stored once per event (NULL never equals NULL),
and the node lookup then fails with "Multiple values for optional". Marquez's `dataset_fields`
now hold one row per field (e.g. prices 5 of 5).

### 11.5 D5: typed bounds beside DATE (B3), the gate
- `d__from` / `d__to` (Postgres `date`, ClickHouse `Nullable(Date32)`), direct SQL:
  `1990` -> 1990-01-01..1990-12-31; `1990-03` -> ..-31; `2024-02-29` twice; `199X` ->
  1990-01-01..1999-12-31; AMBIGUOUS and INVALID NULL; `1850-06-01` a date on Postgres, NULL plus
  one error row on ClickHouse (Date32 starts 1900).
- Gate probe (`d5_gate_probe.py`) on the combined branches: 30 probes, every accepted value stored,
  every rejected one NULL, no aborted INSERT.

### 11.6 D4: disguised nulls in a clone (B3, ADR-021)
- Exact counts from Phase 2, checked against `GROUP BY` on the source: Raha hospital.zip
  `3563x` 2, `3x640` 2, `3xx94` 2; Norway Brreg (1.18M rows): websites `Facebook` 7, `facebook` 4,
  `Ingen` 4, `ingen` 3 (Norwegian "none"); emails `tho@kvale.no;post@kvale.no` 5, one more pair 2.
  6 of 6 and 3 of 3 equal to GROUP BY. They are candidates: damaged zips and two-address cells
  are reported beside true disguised nulls, which is why nothing is applied unconfirmed.
- Confirmation: see §11.8a.

### 11.7 D7: Norway (B4)
A number valid under a module the chosen one is built on (it imports it: no.mva -> no.orgnr, and
nine other countries) is VALID, `verified_by` names the module.
`d7_registry_check.py`: Norway **1,177,617 / 1,177,617 VALID** (was 0); France 500,000 / 500,000
unchanged; 0 INVALID of 1,677,617.

### 11.8 D2 and D6: calibration and its limits (B4)
- Corpora with truth the engine does not decide: seeded D6 corpus (seeds 0-4, n 200: 6,000 cases),
  Raha erroneous cells (9,001), BART-injected raha.hospital cells (BART 354f503, 201 injected
  cells, 85 scorable). BART: 8 correct, 1 correct-abstain, 24 wrong-confident (transposed digits:
  valid, wrong numbers), 52 wrong-status (a removed zip digit: INVALID where the truth is a zip).
- Committed table (`normapi/data/calibration.json`, 15,086 cases, R = 20, delta 5%, exact
  binomial bound): threshold 1.0 for COUNTRY, EMAIL, URL; 0.9 for DATE, NUMERIC; **none** (abstain
  on everything when opted in) for BOOLEAN, COMPANY_NAME, GIVEN_NAME, FAMILY_NAME, PHONE, POSTCODE,
  QUANTITY.
- Held out, the honest result: confidence does not separate well-formed wrong input.
  - BART, fit on seeded + Raha only: PHONE emitted 32, wrong 24 (75%); the PHONE threshold
    learnt on Raha's letter-damaged phones (refused there) does not cover transposed digits.
  - Leave one Raha dataset out: hospital, rayyan, tax 100% wrong among emitted (their own error
    kinds are missing from the fit); movies_1 0%.
  - So the guarantee holds where the errors resemble the calibration corpus (exchangeability);
    across error generators it does not. This is why abstention is opt-in per job.
- Opted-in live clone: §11.8a.
- D6.5: the CSV loader takes `country` / `locale` per row or from `--country` / `--locale`.

### 11.9 D8-D12 live (`docs/benchmarks/scripts/d8_d12_live.py`, combined branches)
Real Brreg numbers and websites, Raha phones, a clone under country NO, direct SQL:
- D8: the same 205 numbers, 5 with a corrupted check digit: TAX_ID statuses INVALID 5, NORMALIZED
  200; CODE NORMALIZED 205.
- D9: 199 of 200 real hosts' registrable domain equals an independent PSL computation, 0 differ
  (1 has no host).
- D10: 7 planted extensions, 7 code values `tel:+1-...;ext=12`, region 7/7 equal to libphonenumber.
  The first run found N13 and a companion defect: an INVALID number's comparison key went into
  the code and region columns (on main too, for the code column). Fixed: companions only for
  answers (B4), an INVALID phone keeps its original (B1).
- D11: Cyrillic and Arabic names carry Double Metaphone and Beider-Morse keys and no Soundex.
- D12: a verdict whose decided value now normalizes differently: 205 cells NEEDS_REVIEW, value
  the decided one.

### 11.8a Opt-in and confirmation, live (combined branches, direct SQL)
- D2, `calibrated_abstention: true` on Raha tax (`f_name` GIVEN_NAME, `zip` POSTCODE, US): both
  types have no passing threshold in the committed table, so every answer is held: 200,000 /
  200,000 AMBIGUOUS in each column, 49,062 queue rows with 400,000 occurrences. That is the
  documented consequence of opting in for those types, and the reason it is off by default. The
  first version also reported "200,000 expected wrong": accuracy from erroneous cells applied to an
  ordinary column; removed.
- D4, `confirmed_missing` `Ingen` / `ingen` on Brreg `hjemmeside`: 7 source rows, 0 left in the
  destination, 7 error rows keeping the original, and nothing reported for them afterwards.

### 11.10 Every benchmark that exposed a bug, rerun (combined branches)
`docs/benchmarks/scripts/part1_reruns.sh`, the arguments of §6/§9 (autodetect opted in where it
was then), each job in its own cgroup (6 GB, no swap, `ulimit -v` 16 GB), one at a time, on
ClickHouse 25.12 (§11.1). Row counts are direct SQL on source and destination for every table
(`count(*)` / `count()`), not the job's numbers.

| run | engine | tables | rows (source = destination) | phase 2 s | error rows | peak RSS MB (driver / workers) | before |
|---|---|---|---|---|---|---|---|
| d1_nul | CH | 1 | 4 | 1.0 | 4 | 364 / 0 | §3 FAILED, §9 COMPLETED |
| ch_badutf8 | CH | 1 | 1 | 1.0 | 2 | 360 / 0 | §7 FAILED |
| d5_ch | CH | 1 | 6 | 1.0 | 12 | 362 / 0 | §3 truncated silently |
| d5_pg | PG | 1 | 6 | 1.0 | 6 | 327 / 0 | §3 rounded silently |
| chinook | PG | 11 | 15,607 | 2.0 | 32 | 411 / 0 | §7 F-DECIMAL-SOURCE |
| raha | PG | 6 | 214,176 | 132.6 | 3,494 | 438 / 0 | §6 21.4 s (different autodetect mapping) |
| uk_price_paid | PG | 1 | 931,453 | 120.7 | 0 | 423 / 400 | §6 99.6 s |
| france (SIRENE, default) | PG | 1 | 500,000 | 15.3 | 0 | 408 / 0 | §7 F-AUTODETECT |
| luxembourg | PG | 1 | 179,684 | 13.2 | 0 | 415 / 0 | §6 6.1 s |
| pagila (PG18) | PG | 71 | 173,270 | 11.3 | 66 | 400 / 0 | §7 FAILED in Phase 1 |
| norway (Brreg) | PG | 1 | 1,177,617 | 147.5 | 1,180,524 | 767 / 767 | §7 FAILED (dotted names); see below |
| gleif | PG | 1 | 3,458,719 | 894.0 | 115,015 | 1660 / 0 | §7 FAILED; §9 595 s |
| nyc_taxi | CH | 1 | 2,964,624 | 51.3 | 0 | 738 / 0 | §6 48.0 s |
| tpch_sf1 | CH | 8 | 8,661,245 | 110.4 | 0 | 748 / 0 | §6 97.5 s |
| ontime | CH | 1 | 1,598,468 | 252.8 | 2,476,121 | 767 / 767 | §7 FAILED (stream), §9 FAILED (memory) |
| **tpch_sf10** | CH | 8 | **86,586,082** | 1,143.1 | 0 | 754 / 0 | §6 1,093 s; not rerun since |

All 16 COMPLETED; every table's source and destination row counts are equal. Error rows on
ontime, gleif and norway come from autodetect's column mappings, which are opt-in (§9) and
reported, not applied unasked.

**Norway was 10,614 s on the first rerun.** Profiled: autodetect now suggested Brreg's 4-digit
postnummer as DATE (years), and the clone spent 3 h parsing postcodes. On main only luck hid it:
DATE and DATETIME both accepted the sample and tied, so detection fell back to FREE_TEXT; N2
rightly makes `0150` an hhmm too, so DATE won alone. Fix (B1): a value read only as a year is no
value-only evidence that a column holds dates (a named column is still found by its name).
Rerun on the fixed branches: 147.5 s, postnummer passthrough, 1,177,617 rows both sides.

### 11.11 CI and memory
- The four ci-fast commands under `ulimit -v 16 GB` on each branch and on the merge of all five
  (scratch worktree, the merge order above, no conflicts): ruff, ruff format and mypy clean;
  pytest on the merge 3,184+ passed, 22 skipped, 1 xfailed. GitHub ci-fast green on every pushed
  head (run ids in PART1_COMPLETE.md).
- The workflow ratchet is at zero missing commands; a test path a workflow names must exist.

### 11.12 D6.3: the corpus's own ambiguity rate (two people, 2026-10-17)
`kappa_sample.py` drew 60 real values (Raha, Brreg): 30 the engine refuses, 30 it answers; two
people labelled independently; `kappa_score.py`:
- Cohen's kappa 0.830, Krippendorff's alpha 0.831.
- 12 of 60 (20%) read differently or marked "can't tell": all 12 among the values the engine
  refused; 0 of the 30 the engine answered were disputed.
- The 12: seven `m/1/yy`-shaped dates (one person read month first throughout, the other day
  first), `NA` (Namibia or can't tell), a two-token name, a bare host's scheme. Each person was
  consistent with their own reading of a column: a column states its date order through values
  like `6/21/10`. On rayyan.article_jcreated_at 38 values prove M/D/Y, 0 prove D/M/Y, 320 are
  refused today. That is the next change (user decision: column evidence, default on), after
  Part 1.

### 11.13 Column evidence for the day/month order (`fix/column-evidence`, ADR-008 amended)

Live, `docs/benchmarks/scripts/column_evidence_live.py`: Raha `rayyan.article_jcreated_at`
(1,000 real cells) copied to a fresh source, cloned as DATE with no country, read back by SQL.

| | before (five branches) | after |
|---|---|---|
| job evidence | — | `{"DMY": 0, "MDY": 38, "order": "MDY"}` |
| ambiguous cells refused (original kept) | 320 | 0 |
| resolved, not in the proven order | — | 0 |
| queue rows / occurrences | 179 / 320 | 0 / 0 |
| rows source = destination | 1,000 = 1,000 | 1,000 = 1,000 |

Scored against Raha's clean file (same rows by `id`): of the 320 resolved cells, the 39 that Raha
left intact are all right; the other 281 are cells Raha corrupted by writing the year first
(`12/1/06` for `1/6/12`), wrong under either day/month reading. No value in the column proves a
year-first order (every corrupted year is 01-15, at most 31), so nothing in the data can tell
them apart. Stating `country=US` on the same cells gives the identical 39 right / 281 wrong: the
column's evidence answers exactly what a correct stated locale answers. The clean column proves
M/D/Y too (85 values, 0 against). Before, these 281 corrupted cells went to the review queue as
AMBIGUOUS; with the column's order they are written as dates (confidence 0.85, the stated-order
confidence) with `column_evidence` recorded on each value.

A person's verdict wins over the column (unit test fails without the fix); a context without a
column order hashes exactly as on main (pinned in `test_column_evidence.py`), so no stored verdict
key or cache key moves. CI set on the branch: 3,197 passed.

User decision 2026-10-18, shown these numbers: "Keep default on".

**Decimal mark (ADR-011 amendment, same rule).** Live, `column_evidence_live.py --type NUMERIC`:
Raha `movies_1.rating_count` (7,390 real cells), text destination.

| | before (five branches) | after |
|---|---|---|
| job evidence | — | `{".": 11, ",": 0, "mark": "."}` |
| ambiguous cells refused | 5,494 | 0 |
| resolved, not in the proven mark | — | 0 |
| queue rows / occurrences | 5,150 / 5,494 | 0 / 0 |
| rows source = destination | 7,390 = 7,390 | 7,390 = 7,390 |

Scored against Raha's clean files (same row positions), every previously refused cell in the
three real NUMERIC columns whose values prove a mark: `movies_1.rating_count` 5,494 / 5,494 right
(`1,234` is the count 1234), `beers.abv` 1,266 / 1,266, `tax.rate` 1,872 / 1,872; 0 wrong. A
scan of every text column on the source stack found no other column with ambiguous numbers and
a proof; text columns (names, addresses) are never typed NUMERIC. CI set on the branch after both
rules: 3,227 passed.
