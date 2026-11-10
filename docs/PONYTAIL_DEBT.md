# Ponytail debt ledger

Generated 2026-10-21 by `/ponytail-debt` on `chore/ponytail` (HEAD 8e96aed), ponytail 5.3.2.
Marker list regenerated from the code 2026-11-10 (D24; orchestrator 2026-11-09, "P3: my decision is yes").
Replaces the archived ledger at `docs/archive/plans/defects/PONYTAIL_DEBT.md` (4.9.0-era, defect-plan scope).

One row per `ponytail:` or `shortcut:` comment in shipped source (`packages/`, `scripts/`, `ui/src/`).
The same words inside string literals in `tests/` are test input for the marker checks, not debt.
`no-trigger` marks a marker that names no upgrade path or revisit trigger — those are the ones that silently rot (C5 spirit).

## packages/normalizers/src/normalizers/_bmpm.py

- `packages/normalizers/src/normalizers/_bmpm.py:69` — ponytail: upstream treats bracket-less contexts as literals, so e.g. `(а|е|о|и|у)` never fires; 4/131 Cyrillic names lose alternatives. Upgrade path: follow upstream if Commons Codec fixes it; re-vendor the rule files.

## packages/normalizers/src/normalizers/date.py

- `packages/normalizers/src/normalizers/date.py:170` — ponytail: compact digits (`03032024`) are not split into components, the parser is trusted; split by length if one is found inventing.

## packages/normalizers/src/normalizers/identifier.py

- `packages/normalizers/src/normalizers/identifier.py:73` — ponytail: English title words only; a module whose title says neither is not found (-> unverifiable). Ceiling: personal tax ids and VAT ids of one country are both matched, so such a country has several candidates and is unverifiable. `[no-trigger]`
- `packages/normalizers/src/normalizers/identifier.py:82` — ponytail: hand map of four legacy modules; drop it once stdnum itself names "the" tax id per country (deferred alternative).
- `packages/normalizers/src/normalizers/identifier.py:166` — ponytail: a country whose single title-matched module is a narrower id (AU TFN not ABN, UA RNTRC, LI PEID, ZA TIN) is still "classified"; the sibling rule below turns a number another module accepts into unverifiable, at the cost of running every sibling on a rejection. "EU" is a stdnum package, not an ISO country (multi-candidate, so harmless). Upgrade: a per-country tax-id choice from an authoritative source if one appears.

## packages/normalizers/src/normalizers/money.py

- `packages/normalizers/src/normalizers/money.py:71` — ponytail: short scale only, and no single letters. "M"/"B"/"K"/"T" are every bit as common in financial data, and are left out deliberately — "M" is the CLDR currency symbol for the Lesotho loti, so "10.5M" was resolving to 10.5 LSL, wrong in both halves at once. A single letter next to a number cannot be told from a currency symbol without asking the column, so it stays AMBIGUOUS. Long-scale locales are the other ceiling: German "Milliarde" is 10^9 and German "Billion" is 10^12, so only English words are listed and anything else is refused rather than guessed. Upgrade path for both: require ctx.locale and key this table by it.

## packages/normalizers/src/normalizers/name.py

- `packages/normalizers/src/normalizers/name.py:127` — _BEIDER_MORSE_MAX_CHARS = 255  # ponytail: measured bound, see _language_aware_codes `[no-trigger]`
- `packages/normalizers/src/normalizers/name.py:136` — ponytail: Beider-Morse output and time grow super-linearly with length (measured: 255 chars ~15 ms / ~25 KB of codes, 7k chars 3.8 s / 2.4 MB, identical to Commons Codec), so a longer value, which is no name, gets no beider_morse key. Upgrade path: encode per token with a total budget.

## packages/normalizers/src/normalizers/phone.py

- `packages/normalizers/src/normalizers/phone.py:105` — ponytail: a regionless `tel:+<cc>...` URI is accepted only when it carries an extension (the form this module emits as `comparison`, so the output re-parses to itself). Without one it stays AMBIGUOUS, as before D10, to keep extension-free output byte-identical to `main`. Upgrade: drop this guard to accept every explicit-country `tel:` URI. It judges libphonenumber's own parse, before the ext re-read below.

## packages/normalizers/src/normalizers/url.py

- `packages/normalizers/src/normalizers/url.py:126` — ponytail: the PSL snapshot is the one bundled in the pinned package; a newer suffix is unknown (-> None, never guessed) until the dependency is bumped, which moves env_id. Upgrade path: a scheduled dependency bump, never a fetch.

## packages/normanalysis/src/normanalysis/calibration.py

- `packages/normanalysis/src/normanalysis/calibration.py:36` — ponytail: 5% is the conventional significance level; every noise bound below is derived from it (Hoeffding / McDiarmid), so changing the level is this one line. `[no-trigger]`
- `packages/normanalysis/src/normanalysis/calibration.py:39` — ponytail: ten equal-width bins is the textbook reliability-diagram default (Guo et al. 2017); with little data per semantic type, pass fewer bins (ece_tolerance shows the noise either way). `[no-trigger]`

## packages/normanalysis/src/normanalysis/disguised_missing.py

- `packages/normanalysis/src/normanalysis/disguised_missing.py:47` — ponytail: ceiling, every distinct value is validated once, and a failing value can cost 10-400 ms in DateNormalizer (100k distinct failing dates = hours). Upgrade path: validate a sample of distinct values, or fix the date slow path.
- `packages/normanalysis/src/normanalysis/disguised_missing.py:51` — ponytail: numeric magic numbers (-999, 9999) are out of reach here. A bare number is a valid number to every validator, so telling a magic number from data needs a column-level model of the numeric distribution. The upgrade path is `ptype` (column type inference with missing/anomalous classes) once it supports pandas 3 / greenery 4 (feasibility gate: `docs/archive/plans/defects/FINAL_REPORT.md`, F6).
- `packages/normanalysis/src/normanalysis/disguised_missing.py:147` — ponytail: the table's size is the bound; a frequency model (ptype) is the upgrade path.

## packages/normanalysis/src/normanalysis/gold.py

- `packages/normanalysis/src/normanalysis/gold.py:447` — ponytail: a bare host states no scheme, so the truth is both readings. url.py assumes https and flags it (a documented policy); under "never invent" that is a miss, and this kind is where it shows. Drop the kind to score only the policy-neutral cases. `[no-trigger]`
- `packages/normanalysis/src/normanalysis/gold.py:465` — ponytail: seven CLDR locales' names per country; more locales mean more coverage, no new code. `[no-trigger]`

## packages/normapi/src/normapi/clone_executor.py

- `packages/normapi/src/normapi/clone_executor.py:142` — ponytail: a two-branch if/else, not a DestinationConnector Protocol — this is the only call site that ever touches destination writers, and it already knows the engine from the saved connection. Add a Protocol only when a 3rd engine (MySQL) makes this a three-way branch.
- `packages/normapi/src/normapi/clone_executor.py:1167` — ponytail: threading.Thread, not Celery/RQ — no task-queue dependency exists in this codebase and none is justified for 2 engines / one deployment. A crashed process loses the in-flight thread, but the job resumes from its last committed chunk (checkpointed every chunk-commit), so correctness survives; only "auto-restart on crash" doesn't. Upgrade to a real task queue only if this needs to survive across multiple app replicas.
- `packages/normapi/src/normapi/clone_executor.py:1805` — ponytail: a fixed bound on distinct values kept; a spillable counter if a column's report must cover more.
- `packages/normapi/src/normapi/clone_executor.py:2552` — ponytail: re-stream-and-skip, not a pushdown filter (no per-row filter param on read_table today) — correct, but re-reads already-processed rows on resume. Add pushdown filtering if resumed jobs on very large tables get costly.
- `packages/normapi/src/normapi/clone_executor.py:2697` — ponytail: one extra read of these columns, a pushdown SELECT DISTINCT if it costs
- `packages/normapi/src/normapi/clone_executor.py:2843` — ponytail: a crash between the two leaves that run without a COMPLETE; write both in one transaction if that ever matters.

## packages/normapi/src/normapi/lineage.py

- `packages/normapi/src/normapi/lineage.py:44` — ponytail: a fixed 5 s per POST, so a hanging collector delays a table by at most two timeouts. Make it configurable if a real collector needs more.

## packages/normapi/src/normapi/pg_persistence.py

- `packages/normapi/src/normapi/pg_persistence.py:975` — ponytail: whole-context load; switch to a keyed IN-lookup per chunk if an agent decider ever produces millions of verdicts.

## packages/normapi/src/normapi/schemas.py

- `packages/normapi/src/normapi/schemas.py:293` — ponytail: stored inside normalization_clone_jobs.data's JSON blob, not a separate table — consumed exactly twice (Phase 1 DDL, Phase 2 normalization) by the job that owns it. Promote to its own table only if "reuse this column config across jobs" becomes a real requirement.

## packages/normapi/src/normapi/secrets.py

- `packages/normapi/src/normapi/secrets.py:7` — ponytail: one key, no rotation/versioning — add key-versioning only if rotation becomes a real requirement.

## packages/normcore/src/normcore/multivalue.py

- `packages/normcore/src/normcore/multivalue.py:21` — ponytail: bracket-delimited only. Postgres `{a,b}` array literals would need their own escaping-aware parser; add one when a source actually ships them rather than guessing at the quoting rules now.

## packages/normexec/src/normexec/cache.py

- `packages/normexec/src/normexec/cache.py:122` — ponytail: one hardcoded number, not an env var — 512MB is a small fraction of the smallest container this runs in (4g) and the LRU tier above is what absorbs hot lookups anyway. Make it configurable only if a deployment actually needs a different cache/normalizer memory split.

## packages/normio/src/normio/connectors/clickhouse_destination.py

- `packages/normio/src/normio/connectors/clickhouse_destination.py:211` — ponytail: the driver takes a name that starts and ends with a quote character as already quoted (a column literally named `"x"`); pass column_type_names with pre-quoted names if one turns up.

## packages/normio/src/normio/connectors/postgres_destination.py

- `packages/normio/src/normio/connectors/postgres_destination.py:207` — ponytail: tables with no primary key get no such guard — a crash after a chunk commits and before its checkpoint commits replays it on resume, so those rows are written twice. Add a synthetic dedup key (e.g. persisting source_row_key) if resumed jobs on PK-less tables become a real requirement.

## packages/normio/src/normio/storage_types.py

- `packages/normio/src/normio/storage_types.py:66` — ponytail: 38,9 is ClickHouse's widest Decimal that still fits its 128-bit backing type. Decimal256 goes to 76 digits if a real column ever needs it — at roughly double the storage and slower arithmetic, which is not worth paying for every numeric column on the chance one needs it.
- `packages/normio/src/normio/storage_types.py:86` — ponytail: "up to 131072 digits before the decimal point" (PG docs, 8.1.2); moved into the column map if Postgres ever raises it.
- `packages/normio/src/normio/storage_types.py:89` — ponytail: "up to 16383 digits after the decimal point" (PG docs, 8.1.2). `[no-trigger]`
- `packages/normio/src/normio/storage_types.py:97` — ponytail: ClickHouse Date32's documented range ("1900-01-01 to 2299-12-31"); Postgres DATE spans 4713 BC to 5874897 AD, wider than any Python date. `[no-trigger]`

## ui/src/lib/reviewJobs.ts

- `ui/src/lib/reviewJobs.ts:3` — ponytail: a fixed 2 s poll while a job runs, carried over from the old clone-job page. Upgrade path: server push, if polling cost ever matters.

## ui/src/lib/reviewQueue.ts

- `ui/src/lib/reviewQueue.ts:7` — ponytail: verdicts are append-only with no revoke route (ADR-018), so undo exists only while nothing has been sent; 5 s is a judgement, not a measured value. Upgrade path: a revoking verdict in the API, then no hold is needed.
- `ui/src/lib/reviewQueue.ts:99` — ponytail: verdicts are append-only and the API has no revoke route, so only a decision still held back can be undone. Upgrade path: a revoking verdict.

## ui/src/pages/ReviewPage.tsx

- `ui/src/pages/ReviewPage.tsx:16` — shortcut: kept in memory, so a refusal after a real tab close is never shown (the page is gone); upgrade path: store it in sessionStorage if decisions are lost that way.

---

**39 markers, 8 with no trigger.**

## Decision log (F4)

- 2026-10-21, audit on `chore/ponytail`: findings reported to user; applied/skipped choices recorded here as they happen (see Step 3 report).
- 2026-10-21, user chose: "Apply 1, 2, 3, 5, 6, 7 + turn #4 into a documented keep".
  - APPLIED #1: dropped `pydantic-settings`, `xxhash`, `structlog`, `asyncpg`, `alembic` (root `pyproject.toml`) — zero import/string refs; TECHNICAL_IMPLEMENTATION.md + uv.lock updated same commit.
  - APPLIED #2: dropped `cleanco` (root + `packages/normalizers`) — `company.py` docstring states it is deliberately not called; docs updated.
  - APPLIED #3: removed `"Source.txt"` from mutmut `also_copy` — file deleted in 8ee6e48.
  - KEPT #4 (not deleted, documented): `python-dateutil` + `rapidfuzz` are `env_id` fingerprint inputs (`normexec.env_fingerprint`); removal shifts env_id (ADR-014). `ponytail:` comments added at both declaration sites so later audits do not re-flag.
  - APPLIED #5: reason comments added to all 13 bare `type: ignore` (C5); each reason verified against the code (run.py's verified with a mypy probe file).
  - APPLIED #6: deleted local leftover `scripts/ground_truth/` (only `__pycache__`, 0 tracked files).
  - APPLIED #7: added `scripts/check_declared_deps.py` + `.github/workflows/dep-check.yml` (M4 CI check; deliberately outside ci-fast's four-command contract).
- Skipped by decision: removing `rapidfuzz`/`python-dateutil` (finding #4 removal option) — user's words above.
- 2026-10-21, PRE-MERGE CORRECTION (user, their words): "dropping cleanco changes env_id. It is still in FINGERPRINTED_PACKAGES ... Restore cleanco as a declared dependency with the same 'KEEP, fingerprint input' note."
  - #2 partially reverted: `cleanco` restored in root `pyproject.toml` with the fingerprint keep-note (it stays out of `packages/normalizers`, which neither imports nor fingerprints it).
  - Root cause of the miss: `env_fingerprint.py` DID appear in the "unused" grep; it was misread as a capability probe instead of `FINGERPRINTED_PACKAGES` — the very list that makes a never-imported package load-bearing (ADR-014). Recorded in docs/LESSONS.md (J14).
  - K4 guard added: `test_every_fingerprinted_package_is_a_declared_dependency` (shown failing on the broken state first, L3).

## Assertion-less tests (L4), found 2026-10-24

User decision 2026-10-24: "Guard blocks on touch, and list all 27 in docs/PONYTAIL_DEBT.md (file, test name, why it has no assertion) so the next prompt 3 audit reviews them." The count by `scripts/check_test_assertions.py` is 29, not 27 (a miscount in the earlier report; same rule). `scripts/check_test_assertions.py` fails only when one of these changes code. Prompt 3's audit decides: add an assertion, or record why none fits (C5).

| file | test | why it has no assertion |
|---|---|---|
| `tests/bench/test_execution_caching_benchmark.py` | `test_bench_execute_run_10000_rows_100_distinct_no_cache` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_execution_caching_benchmark.py` | `test_bench_execute_run_10000_rows_100_distinct_with_cache_cold` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_execution_caching_benchmark.py` | `test_bench_execute_run_10000_rows_100_distinct_with_cache_warm` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_generic_text_benchmark.py` | `test_bench_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_generic_text_benchmark.py` | `test_bench_normalize_mixed_batch_of_1000` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_identity_normalizers_benchmark.py` | `test_bench_name_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_identity_normalizers_benchmark.py` | `test_bench_company_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_identity_normalizers_benchmark.py` | `test_bench_phone_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_identity_normalizers_benchmark.py` | `test_bench_email_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m4_normalizers_benchmark.py` | `test_bench_date_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m4_normalizers_benchmark.py` | `test_bench_country_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m4_normalizers_benchmark.py` | `test_bench_language_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m4_normalizers_benchmark.py` | `test_bench_script_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m5_normalizers_benchmark.py` | `test_bench_identifier_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m5_normalizers_benchmark.py` | `test_bench_uuid_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m5_normalizers_benchmark.py` | `test_bench_numeric_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m5_normalizers_benchmark.py` | `test_bench_currency_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m5_normalizers_benchmark.py` | `test_bench_unit_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m5_normalizers_benchmark.py` | `test_bench_boolean_normalize_single_value` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m6_analysis_benchmark.py` | `test_bench_compute_impact_1000_values` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m6_analysis_benchmark.py` | `test_bench_find_collisions_1000_values` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m6_analysis_benchmark.py` | `test_bench_compare_runs_1000_values` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/bench/test_m6_analysis_benchmark.py` | `test_bench_profile_field_1000_values` | pytest-benchmark timing: `benchmark(...)` runs the call and records time; no outcome is checked |
| `tests/unit/test_confident_wrong.py` | `test_norway_never_raises` | "never raises" smoke: passes if `_norm` does not raise; the outcome (status/value) is not checked |
| `tests/unit/test_confident_wrong.py` | `test_unknown_locale_never_raises` | "never raises" smoke: passes if `_norm` does not raise; the outcome (status/value) is not checked |
| `tests/unit/test_connector_schema.py` | `test_tables_present_is_simply_allowed` | passes if `_require_tables` does not raise; "allowed" is not asserted |
| `tests/unit/test_followups.py` | `test_enough_space_passes` | passes if `check_spool_space` does not raise |
| `tests/unit/test_name_d11_acceptance.py` | `test_report_must_fix_pairs` | prints a report by design (docstring: "Reported, not asserted") |
| `tests/unit/test_robustness.py` | `test_an_abandoned_read_stops_and_cleans_up` | closes a generator; the claimed clean-up is not asserted |
