# Phase 4 — re-measure: BEFORE (Phase 0) next to AFTER (Phases 1-3)

Measured 2026-10-06 on `feat/defects-fixes` after `[PHASE 3 DONE]` (79b95f9), with the Phase 0 scripts
unchanged (`tests/defects/measure_phase1_before.py`, `measure_phase23_before.py`; BEFORE output in
`.handoff/before_phase1.txt`, `.handoff/before_phase23.txt`, AFTER in `.tmp/after_phase*.txt`, regenerable) plus
the D6 harness and the D2 report. Synthetic, planted ground truth: these numbers are evidence of mechanism, not
proof that the live numbers moved (plan §6). The live values are in `LOCAL_VERIFY.md`.

## Per item

| item | measure | BEFORE | AFTER | note |
|---|---|---|---|---|
| D1 | planted ambiguous values that reach an adjudication queue | 0 of 16 (no queue in `packages/`) | queue exists; all 16 abstain (correct-abstain 16, wrong-confident 0) | live: Postgres queue, LOCAL_VERIFY |
| D12 | NEEDS_REVIEW producers in `packages/` src | 0 | 1 (re-normalized verdict differs) | bar PASS |
| D7 | stdnum countries reachable for TAX_ID | 4 (US, GB, DE, FR) | 65 of 85 | the 20 left are unverifiable by design (several or no English "tax"/"vat" title) |
| D7 | unlisted country (AE) | NORMALIZED / VALID (a guess) | NORMALIZED / UNKNOWN, `verification: unverifiable` | never-guess bar PASS |
| D7 | 6 fixture countries: valid / one-digit twin | valid 6 correct; twin 6 wrong-confident | valid 5 correct, twin 5 correct; CO abstains on both | CO: stdnum's `co.nit` title says "Número De Identificación Tributaria", no English term -> unverifiable: the recorded `ponytail:` ceiling, an abstention, not a guess. 3 Phase 0 bars stay FAIL for this reason only |
| D8 | TAX_ID and CODE on one string give the same verdict | 2 of 3 pairs identical | 0 of 3 | CODE is canonical-only (`validation_status` UNKNOWN), as accepted; the old bars expected CODE VALID, so 2 stay FAIL by design |
| D9 | PSL triple (registrable domain, suffix, subdomain) in `structured` | 0 of 10 | 10 of 10 | |
| D10 | base number == base + `x45` in `comparison` (defect) | 10 of 10 regions | 0 of 10 | |
| D10 | `x45` == `x46` in `comparison` (defect) | 10 of 10 | 0 of 10 | |
| D10 | `structured["rfc3966"]` present | 0 of 40 | 40 of 40 | `search` still the extension-free E.164 (10/10) |
| D11 | non-Latin inputs carrying Anglo-centric keys (Soundex/NYSIIS/Metaphone/MRA) | 17 of 17 | 0 of 17; 17/17 `phonetic_status=not_applicable`; 7 carry Double Metaphone/Beider-Morse only | |
| D11 | cross-script same-name pairs sharing a key | 13 of 18 (accidental: Soundex of transliteration) | 0 of 18 | intended: no key is better than a coincidental one; Latin pairs unchanged (12 of 13) |
| D11 | different-name pairs colliding | 0 of 10 | 0 of 10 | |
| D5 | oversize finite values reaching INSERT (end to end, both engines) | NUMERIC 5, MONEY 4 | 0 and 0 | the script's coerce-level "clickhouse" rows call `coerce` without `engine` (Postgres bounds); with `engine="clickhouse"` every oversize value is a cast failure (checked) |
| D5 | DATE/DATETIME partial dates kept | TEXT, unchanged | TEXT, unchanged | ADR-020 |
| D3 | OpenLineage events per clone job / table | none | START/COMPLETE/FAIL per job and table with columnLineage, stored and served | Marquez live-only |
| D4 | planted 3% sentinels reported at cell level | no detector | `N/A` 150, `unknown` 100, `-` 50 exact | |
| D4 | Namibia `NA` (40), clean dates, 300 one-off junk, `-999` | n/a | none reported | `-999` is the ptype ceiling |
| D6 | data corpus files / accuracy number | 0 / none | seeded corpus (6 families); seed 0, n 30: correct 142, correct-abstain 21, wrong-confident 11, over-abstain 6, wrong-status 0; without the bare-host URL kind wrong-confident is 1 | the 11: 10 bare-host URLs (url.py assumes https), 1 `ee-GH` date (hand M/d table); the 6 over-abstains are day == month dates |
| D2 | calibration code | 0 | seed-0 corpus at cost ratio 5: ECE 0.072 (calibrated tolerance 0.326), AURC 0.003, Chow threshold 0.85, overconfident bin [0.8, 0.9) | the flagged bin is the URL https assumption (stated ~0.82, observed 0.31) |

## Phase 0 bars still unmet, and why

`measure_phase1_before.py` reports 5 unmet bars (8 before). Each was checked against the accepted design:

- D7 "6 fixture countries reachable", "twins INVALID in all 6", "valid numbers stay clean": CO only (see above).
- D8 "verdict differs exactly where a check digit is wrong", "no wrong-confident": CODE now never claims a
  verdict (UNKNOWN), so CODE vs TAX_ID differ on every pair and the old "CODE VALID" truth reads as over-abstain.
  The scorer finds no wrong-confident in D8 (3 correct, 3 over-abstain).

None is a guess, and none hides an old failure mode.

## Findings outside D1-D12 that the new measurements surfaced

Recorded under "Open escalations" in `HANDOFF.md`: (h) url.py's https assumption, (i) the date normalizer's
`_MDY_COUNTRIES = {"US"}` hand table versus 34 M/d/y CLDR locales, (j) PHONE/CURRENCY validators answer AMBIGUOUS
for junk, (k) the DateNormalizer slow path, (l) a lone surrogate segfaults ciso8601 via `date.py`.
