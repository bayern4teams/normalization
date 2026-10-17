# Part 1 traceability: `docs/improvement-report.md` Part 1, row by row

Built 2026-10-14 on main at 002eda0 (D1-D12, fix/robustness, fix/followups merged); closed
2026-10-17 on the five branches of this session. One row per thing Part 1 asks for: each defect's
fix, each acceptance statement the plan derived from it, and each "before" measurement. Strict
reading: deferred, "library function nothing calls", "only fakes" and "partial" were gaps.

Status values: `done-live` (built, proven on a real database or service with direct SQL or the
service's own API, evidence linked), `done` (a measurement or a code property with no live
component), `decision` (open, needs the user: listed in PART1_COMPLETE.md), `descoped` (by user
decision, quoted). Evidence: `docs/benchmarks/REPORT.md` (REPORT), section §11 unless stated.

Branches (merge in this order; the last three are stacked): `fix/confident-wrong` (B1),
`fix/verdict-identity` (B2), `fix/lineage-and-dates` (B3), `fix/calibration-coverage` (B4,
on B3), `fix/ci-gates` (B5, on B4).

## D1: AMBIGUOUS has an exit path

| # | Part 1 asks | implemented | evidence | status |
|---|---|---|---|---|
| D1.1 | review-queue store | `adjudication.py`, `pg_persistence.py` (a2b5e59) | REPORT §3 | done-live |
| D1.2 | verdict re-enters the pipeline | resolve stage (a2b5e59) | §11.3: Postgres and ClickHouse, 5/5 cells decided | done-live |
| D1.3 | never asked twice (was F-VERDICT-SCOPE) | `source_identity`, `migrate_sources`, ADR-018 amended (B2) | §11.3: verdict survives delete + re-add on both engines; startup migration 2,696 -> 2,488 rows, 0 left | done-live |
| D1.4 | decided_by / decided_at / rationale / confidence | verdicts table | REPORT §3 | done-live |
| D1.5 | queue counts once | `reset_queue_counts` on a ClickHouse restart (B2) | §11.3: live kill-and-resume 10,000 (main: 13,333) | done-live |
| D1.6 | NUL / non-UTF-8 in the queue | d682b51 | REPORT §9; §11.10 rerun `d1_nul` | done-live |
| D1.7 | round trip on Postgres and on the user's data | — | §11.3 (Postgres and ClickHouse) | done-live (public); own DB: descoped (user, 2026-10-17: "No, skip Step 6") |

## D2: confidence is decorative

| # | Part 1 asks | implemented | evidence | status |
|---|---|---|---|---|
| D2.1 | reliability per stated confidence | `calibration.py` (a3851ca) | REPORT §5; §11.8 | done-live |
| D2.2 | Chow's rule as the abstain/emit threshold | risk-controlled threshold per type, `calibrated_abstention` opt-in (B4, ADR-019 amended) | §11.8: committed table; opted-in live clone | done-live |
| D2.3 | the guarantee (conformal, step 3) | Learn-then-Test risk control, exact binomial bound (B4) | simulation test (violations <= delta); §11.8 held-out | done-live |
| D2.4 | risk-coverage, not accuracy | `risk_coverage`, AURC | REPORT §5 | done-live |
| D2.5 | "when it says 0.85, how often is it right?" | every clone reports answers below the type's threshold and the bins' expected wrong (B4) | §11.8 | done-live |
| D2.6 | before: 61 / 28 / 14 / 3 sites, 0 calibration code | PHASE0; 63 sites now (no literal tuned) | `test_calibration_acceptance.py` | done |

## D3: provenance stops at the process boundary

| # | Part 1 asks | implemented | evidence | status |
|---|---|---|---|---|
| D3.1 | OpenLineage events at job boundaries | `lineage.py` (a000eae) | REPORT §3 | done-live |
| D3.2 | column-lineage facet answers "which source columns" | facet incl. companions | REPORT §3 | done-live |
| D3.3 | a queryable lineage graph (Marquez) | typed SchemaDatasetFacet on inputs and outputs (B3) | §11.4: `/api/v1/column-lineage` returns the companion -> source edges (was 0 nodes) | done-live |
| D3.4 | the same on ClickHouse | same | §11.4: d1src.prices amount -> amount_currency, phone -> phone_code | done-live |

## D4: disguised missing data

| # | Part 1 asks | implemented | evidence | status |
|---|---|---|---|---|
| D4.1 | a first-class outcome reporting which cells | detector wired into Phase 2 on exact counts (B3, ADR-021) | §11.6: Norway `Ingen` 7, `Facebook` 11 ...; 6/6 counts equal GROUP BY | done-live |
| D4.2 | output lands in MissingKind | `confirmed_missing` -> MISSING (UNKNOWN_VALUE), NULL cell, original in the error row (B3) | §11.6: confirmed run | done-live |
| D4.3 | keep type_detection's negative controls | untouched; the dispatcher reuses the same control (B1) | `test_confident_wrong.py` | done |
| D4.4 | the `-999` example | an in-range number is valid; calling it missing by frequency would be a guess (ADR-021 limit); a person can confirm it per column | — | descoped (user, 2026-10-17: "Known limit, descope") |

## D5: destination columns are all TEXT

| # | Part 1 asks | implemented | evidence | status |
|---|---|---|---|---|
| D5.1 | pre-insert cast gate | `storage_types.coerce` | §11.5: 30 probes, every accepted value stored, rejected NULL | done-live |
| D5.2 | typed destination columns | NUMERIC, MONEY, BOOLEAN | REPORT §9; §11.10 reruns | done-live |
| D5.3 | DATE / DATETIME typed (decided 2026-10-06) | `<col>__from` / `<col>__to` (B3, ADR-020 amended) | §11.5: both engines, partial dates as ranges, Date32 range refused with an error row | done-live |
| D5.4 | NUL never kills a chunk | metadata (d682b51); a clone cannot carry NUL into a Postgres column (Postgres sources hold none, cross-engine refused); text siblings disclose the drop (B1) | §11.2; §11.10 `d1_nul` | done-live |

## D6: the gold corpus measures regression, not accuracy

| # | Part 1 asks | implemented | evidence | status |
|---|---|---|---|---|
| D6.1 | BART injects errors | BART 354f503 built and run (H2: its Postgres driver predates PG 12) | §11.8: 201 injected cells on raha.hospital; scored and used held out | done-live |
| D6.2 | Raha's six datasets | loader, scripts | REPORT §4; §11.8 | done-live |
| D6.3 | the corpus's own ambiguity rate (kappa / alpha) | `kappa_sample.py`, `kappa_score.py` | §11.12: kappa 0.830, alpha 0.831; 12/60 disputed, all among values the engine refused; 0 disputed answers | done-live |
| D6.4 | AMBIGUOUS is a correct gold label | 5-class scorer | §11.2: seeded 149/31/0/0/0 (was 142/21/11/6/0) | done-live |
| D6.5 | the CSV loader can score context-needing types | `country` / `locale` columns or `--country` / `--locale` (B4) | §11.8 | done-live |

## D7: the stdnum registry

| # | Part 1 asks | implemented | evidence | status |
|---|---|---|---|---|
| D7.1 | registry from python-stdnum | 7bd631b | REPORT §3 | done-live |
| D7.2 | tri-state valid / invalid / unverifiable | UNKNOWN + `verification` | REPORT §3 | done-live |
| D7.3 | a real register validates (Norway) | valid under a module the chosen one imports (B4) | §11.7: 1,177,617 / 1,177,617 VALID (was 0); France 500,000 unchanged; 0 INVALID | done-live |
| D7.4 | Colombia | `co.nit`'s title has no English tax word; no authoritative translation source; stays unverifiable, never a guess | — | descoped (user, 2026-10-17: "Keep unverifiable") |

## D8-D12

| # | Part 1 asks | implemented | evidence | status |
|---|---|---|---|---|
| D8.1 | TAX_ID verifiable, CODE canonical-only | 7bd631b | §11.9: same numbers, 5 corrupted: TAX_ID 5 INVALID, CODE 0 | done-live |
| D9.1 | registrable domain from the PSL | e5c2e83 | §11.9: 199 of 200 real hosts agree with an independent PSL computation, 0 disagree | done-live |
| D10.1 | RFC 3966 when an extension exists | af96af1 | §11.9: 7/7 planted extensions in the code column as tel: URIs | done-live |
| D10.2 | E.164 stored with the region | `<col>_region` (B4); companions only for answers (B4); INVALID keeps its original (B1) | §11.9: region 7/7 = libphonenumber; invalid numbers no companions | done-live |
| D11.1 | language-aware phonetics | af96af1 | §11.9: real names, non-Latin get DM/BMPM only | done-live |
| D12.1 | NEEDS_REVIEW has a meaning | verdict re-normalizes differently | §11.9: 205 cells NEEDS_REVIEW | done-live |

## Confident-wrong findings (B1 unless stated)

| # | finding | evidence | status |
|---|---|---|---|
| N1 | DATETIME dropped a stated time | §11.2 | done-live |
| N2 | HHMM read as a year | §11.2 | done-live |
| N3 | https assumed for a bare host | §11.2: 34,853 real bare hosts now AMBIGUOUS | done-live |
| N4 | M/d/y hand table | §11.2 | done-live |
| N5 | `NA` in COUNTRY read as missing | §11.2 | done-live |
| N6 | NUL into TEXT columns | see D5.4 | done-live |
| N7 | PHONE / CURRENCY never INVALID; `¥`/`£` hand table | §11.2: 364 real state codes in a CURRENCY column INVALID | done-live |
| N8 | one-pass idempotency; silent text repair | properties in `test_confident_wrong.py` | done |
| N9 | `05/05/2024` refused | §11.2 | done-live |
| N10 | `24/03` read as year 24 | §11.2 | done-live |
| N11 | NUMERIC/MONEY raised for country NO; first-language guess | §11.2: 307 MONEY values that raised now parse | done-live |
| N12 | held-out date findings (no_NO, stated order, time digits) | §11.2 | done-live |
| N13 | INVALID phone rewritten, its key in the code column | §11.9 | done-live |

## Workflows, environment, "before" numbers, verified-as-sound

| # | item | status |
|---|---|---|
| W1 | gate.yml / release.yml cut to commands that exist; ratchet 0 (B5) | done |
| W2 | drift.yml stays off (decision of 2026-10-13, REPORT §10.5) | descoped: "disable the drift schedule rather than build it" |
| E1 | normbench ClickHouse 25.12 + memory worker, 6 GB (decision 2026-10-14) | done-live |
| E2 | TPC-H SF10 rerun | done-live (§11.10) |
| B1-B6 | Part 1's before measurements | done (PHASE0, recorded) |
| S | "verified as sound, do not touch" | done: unchanged in intent; resume changed shape in REPORT §10.2 deliberately |
