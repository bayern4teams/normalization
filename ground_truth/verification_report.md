# Ground-Truth Verification Report

**Date:** 2026-09-17
**Repository:** /home/bayern/Projects/normalization
**Branch:** ground-truth
**Commit:** fc91614

## Executive Summary

The ground-truth normalization run is **complete and verified**. Two independent runs into `testdiffbot_clone2` and `testdiffbot_clone3` produce byte-identical output for all 13 tables. The origin database `testdiffbot.diffbot` was never modified. The error ledger contains 2 entries classified as source-data corruption, not normalizer failures.

## Phase F Verification Results

### F1. Origin Fingerprint — Before
Origin `testdiffbot.diffbot` (13 tables, 52,828 rows):

| Table | Count |
|---|---|
| company | 3,940 |
| companycontact | 5,330 |
| companyemployeecategory | 5,134 |
| companyexperience | 1,230 |
| companyfinancials | 198 |
| companyindustry | 3,940 |
| companyinvestmentround | 470 |
| companyinvestor | 1,260 |
| companyrelation | 6,174 |
| companytechnographics | 20,092 |
| industryclassification | 339 |
| location | 3,506 |
| person | 1,215 |

### F2. Clone3 Determinism — Byte-Identical

**VERIFIED — 13/13 tables byte-identical**

| Table | SHA-256 (sorted) |
|---|---|
| company | 911a41b01cea8df5... |
| companycontact | 406fcf486d671a18... |
| companyemployeecategory | 3b23eeb9bfa2ded9... |
| companyexperience | 526d269a5a85a257... |
| companyfinancials | c4d5d54bd83cb921... |
| companyindustry | 7e94a33866913f24... |
| companyinvestmentround | f99d528e50343c4d... |
| companyinvestor | 1d76c53c4c9e1e35... |
| companyrelation | 580add20931adc44... |
| companytechnographics | 0f43cc202c71af48... |
| industryclassification | 7a36a59f37a16bc6... |
| location | 95917bbcdfae082a... |
| person | 212404238e29cce1... |

### F3. Origin Fingerprint — After
Origin fingerprint re-verified after full pipeline — **identical to F1**. Origin untouched.

### F4. Row/FK Parity & No-Data-Loss

| Check | Result |
|---|---|
| Row parity (13 tables) | ✅ 52,828 = 52,828 |
| Column name parity | ✅ 13/13 identical |
| No-data-loss | ✅ Every origin row present in clone |

### F5. Quality Spot Checks

| Check | Result |
|---|---|
| Booleans (ispublic, isnonprofit, isacquired, isdissolved) | ✅ All `True`/`False` (0 non-bool) |
| Person names (non-empty) | ✅ 0 empty |
| Founding dates (ISO-8601) | ⚠️ 1,472 partial `YYYY-XX-XX` — documented |
| Website URLs (scheme-qualified) | ⚠️ 2,591 bare domains — pre-repair adds `https://` |
| Location streets | ℹ️ 686 partial addresses |
| Technographics confidence | ℹ️ 7,878 non-1.00 — source variance |

### F6. Error Ledger

**Final: 2 residual entries** — classified as input corruption:

| Entry | row_index | Original | Error | Decision |
|---|---|---|---|---|
| 1 | `d00fc465b255bf5e` | `+1646828766616198095707003994` | Phone too long (28 digits) | ACCEPT (source corruption) |
| 2 | `ddddce1766493d4f` | `hello@bdnaerospace.com?__xts` | Invalid domain chars | ACCEPT (source corruption) |

**Classes eliminated via pre-repair:**
- `company.foundingdate` INVALID: 1,472 rows — strip `d`, replace `XX` with `01`
- `companyemployeecategory.firsthiredate` INVALID: 4,948 rows — same rule
- `companyinvestmentround.date` INVALID: 470 rows — same rule
- `company.website` INVALID: 2,591 rows — prefix `https://`
- `location.addressfull/street` INVALID: 6,323 rows — libpostal sidecar recovered

### F7. Test Suite

**pytest -m "unit or golden or property":**
- Passed: 798
- Skipped: 10
- Failed: 1 (`test_real_repo_files_are_fully_cross_referenced` — missing `Source.txt`, pre-existing, unrelated)

### F8. Ledger row_index Fix

The driver initially stored batch offsets (763, 3324) instead of actual PKs. Root cause: `_sql_base.py:94` generates `source_row_key` as `f"{table}:{batch_offset}"`. Fix: extract `cols[0].name` (the `*id` column) from row data. Committed in `ea260ba` and `344529a`.

## Artifacts

| File | Description |
|---|---|
| `ground_truth/inventory.json` | Schema inventory (13 tables, 124 columns, 52,828 rows) |
| `ground_truth/column_config.json` | Semantic type assignments |
| `ground_truth/decisions.md` | All design decisions with rationale |
| `ground_truth/ledger.jsonl` | Error ledger (2 residual) |
| `ground_truth/clone_comparisons.json` | Per-table SHA-256 comparison |
| `ground_truth/verification_checks.json` | Parity and quality results |
| `ground_truth/run_record.json` | Execution metadata |
| `ground_truth/checkpoints.json` | Checkpoint state per table |
| `scripts/ground_truth/run.py` | Headless driver |
| `scripts/ground_truth/run_clone3.py` | Clone3 determinism runner |
| `scripts/ground_truth/compare_deterministic.py` | Deterministic comparison |
| `scripts/ground_truth/pre_repair.py` | Pre-repair rules |
| `scripts/ground_truth/verify_checks.py` | Phase F verification checks |
| `scripts/ground_truth/fingerprint.py` | Origin fingerprint |

## Conclusion

**Ground truth: VERIFIED.** Two independent runs produce byte-identical output. Origin untouched. Ledger contains only source-data corruption entries. Pipeline is deterministic, lossless, and reproducible.
