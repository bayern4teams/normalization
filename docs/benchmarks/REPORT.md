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

All files are under `data/benchmarks/` (git-ignored), each with a SOURCE.md giving URL, UTC download
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
  committed.
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
