# Part 1 complete

Part 1 of `docs/improvement-report.md` (defects D1-D12, the confident-wrong findings, the
workflows and the "before" measurements) is implemented on six branches from main at 002eda0.
Row by row: [`PART1_TRACEABILITY.md`](PART1_TRACEABILITY.md). Measurements:
`docs/benchmarks/REPORT.md` §11. Nothing is merged until the user says "merge it".

## Matrix

59 rows: **51 done-live** (built, proven on a real database or service by direct SQL or the
service's own API), **5 done** (a measurement or a code property with no live part),
**3 descoped by the user**, **0 open**.

## Branches, in merge order

| # | branch | what | stacked on |
|---|---|---|---|
| B1 | `fix/confident-wrong` | guesses shown as answers: CLDR date order, stated times, HHMM, bare hosts, `NA`, INVALID phones and currencies, CLDR shared symbols, every official locale a reading, disclosed text repair, year-only is no date evidence | main |
| B2 | `fix/verdict-identity` | a verdict is keyed to the source, not the connection id; startup migration; queue counts once on a ClickHouse resume | main |
| B3 | `fix/lineage-and-dates` | typed Marquez schema facets (column graph); `<col>__from` / `<col>__to` typed date bounds; disguised nulls reported with exact counts, applied only when confirmed | main |
| B4 | `fix/calibration-coverage` | Norway VALID under the base module; risk-controlled thresholds and the committed table, opt-in abstention; `<col>_region`; companions only for answers; gold CSV context | B3 |
| B5 | `fix/ci-gates` | gate.yml / release.yml cut to commands that exist; ratchet 0; REPORT §11, traceability, D6.3 | B4 |
| C1 | `fix/column-evidence` | a column's own values state its day/month order and decimal mark (ADR-008, ADR-011 amendments); merges B1 and B2 in (B2 also changed `adjudication.py`; resolved there) | B5 + B1 + B2 |

C1 contains all five earlier branches, so the six merges below apply without conflicts.

## Before and after (direct SQL; REPORT §11)

| measure | before | after |
|---|---|---|
| seeded gold corpus (correct / abstain / wrong-confident / over-abstain / wrong-status) | 142 / 21 / 11 / 6 / 0 | 149 / 31 / 0 / 0 / 0 |
| Norway register, VALID | 0 / 1,177,617 | 1,177,617 / 1,177,617 |
| a verdict after the connection is deleted and re-added | orphaned | applied, 5/5 cells (Postgres and ClickHouse) |
| ClickHouse kill-and-resume, queue occurrences for 10,000 ambiguous rows | 13,333 | 10,000 |
| Marquez column-lineage graph | 0 nodes | companion -> source edges on both engines |
| real bare hosts answered as https | 34,853 | 0 (AMBIGUOUS, both schemes listed) |
| rayyan dates refused, a column proving M/D/Y | 320 | 0 (39 intact right; 281 Raha year-first corruptions, same as `country=US`) |
| movies_1 counts refused, a column proving `.` | 5,494 | 0; 8,632 / 8,632 right on three columns |
| benchmark reruns | §7 failures | 16 / 16 COMPLETED, row counts equal, incl. TPC-H SF10 86,586,082 rows |
| two people labelling 60 values (D6.3) | — | kappa 0.830, alpha 0.831; 12 disputed, all among values the engine refused |

## User decisions

- 2026-10-14: ClickHouse 25.12 in the override; verdict key = source locator; D2 built, opt-in;
  D7 = chosen module plus its base module; BART, SF10 and Marquez runs approved.
- 2026-10-17: Step 6 on the user's own database: "No, skip Step 6". Colombia (D7.4): "Keep
  unverifiable". `-999` (D4.4): "Known limit, descope". D6.3 labelled by two people from a CSV.
- 2026-10-17: column evidence: "Build now, default on". 2026-10-18, after seeing the rayyan
  corruptions resolved: "Keep default on".

## Honest limits

- Calibrated abstention does not transfer across error generators (BART, leave-one-dataset-out,
  REPORT §11.8), so it stays opt-in; for some types the committed table has no passing threshold.
- Disguised nulls are candidates (damaged zips appear beside true nulls); nothing is applied
  without a person's confirmation. `-999` is an in-range number and stays a value.
- Column evidence assumes the year is the last part; a corrupted cell that is wrong under any
  reading is written exactly as a correct stated locale would write it. A person's verdict wins.
- The column-evidence pre-pass is one extra read of a table's DATE/NUMERIC/MONEY columns.
- Colombia's NIT stays unverifiable: no authoritative source names it a tax number in English.

## Merge commands (only after "merge it")

One per branch, in this order:

```bash
git checkout main && git pull --ff-only && git merge --no-ff fix/confident-wrong && git push origin main
```
```bash
git checkout main && git pull --ff-only && git merge --no-ff fix/verdict-identity && git push origin main
```
```bash
git checkout main && git pull --ff-only && git merge --no-ff fix/lineage-and-dates && git push origin main
```
```bash
git checkout main && git pull --ff-only && git merge --no-ff fix/calibration-coverage && git push origin main
```
```bash
git checkout main && git pull --ff-only && git merge --no-ff fix/ci-gates && git push origin main
```
```bash
git checkout main && git pull --ff-only && git merge --no-ff fix/column-evidence && git push origin main
```
