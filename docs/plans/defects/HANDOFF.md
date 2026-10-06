# Defects D1-D12 handoff — the only memory that survives a session

Overwrite this file at every commit. A fresh session reads it first, then
[the plan](../DEFECTS_IMPLEMENTATION_PLAN.md). Git is the memory; a session's context is not.

**Lock:** 2026-10-06T01:32:09Z · **Autonomy:** unattended-through-phase-5 · **Last heartbeat:** 2026-10-06T01:32:09Z

(Lock/heartbeat protocol: plan §7. A session sets `Lock: <ISO time>`, pushes it, and refreshes it at
every commit; a lock older than 75 min is stale. `Autonomy` is `off`, `dryrun` (a tick only records
what works and exits) or `unattended-through-phase-N` (authorises the supervisor to chain phases).
Only the user changes it.)

**Branch:** `feat/defects-fixes` · **Current phase:** 3

| item | phase | state | commit | lead verdict |
|---|---|---|---|---|
| D1 | 1 | unverified-live | this commit | ACCEPT after round 2: verifier REJECTed blank verdict (NULLs cell) and lone-surrogate queue crash; both fixed, 52 acceptance tests green; Postgres DDL/ON CONFLICT live-only |
| D12 | 1 | accepted-cloud | this commit | ACCEPT: kept, one producer (verdict re-normalizes differently -> NEEDS_REVIEW), tested in test_adjudication_acceptance.py; severity order unchanged |
| D7 | 1 | unverified-live | this commit | ACCEPT: verifier ACCEPT (60 acceptance+unit, 21 fail on 47df753; 86 stdnum pkgs hand-classified, no non-tax module chosen; 69 sibling-valid numbers UNKNOWN never INVALID); lead added the missing ponytail: ceilings; real numbers live-only |
| D8 | 1 | accepted-cloud | this commit | ACCEPT: CODE canonical-only, no check-digit keys, validation_status UNKNOWN; IDENTIFIER unchanged |
| D9 | 1 | accepted-cloud | this commit | ACCEPT: verifier ACCEPT (33 acceptance fail on 47df753; own PSL algorithm agrees on >15000 hosts; sockets blocked: no network); lead fixed `a b.com` getting a registrable domain (host char check + test) and added the ponytail: ceiling; MPL-2.0 accepted as a warning like certifi/hypothesis/pathspec |
| D5 | 2 | unverified-live | this commit | ACCEPT after round 2: verifier REJECTed (PG 16.14 scratch instance: >16383 fractional digits overflow even NUMERIC(38,4)); lead added that ceiling (ponytail: PG docs 8.1.2), made `engine` required in the executor (verifier nit), narrowed the derive guard "tiny never rejected" to ClickHouse on that evidence; 20k-input fuzz vs exact ROUND_HALF_UP oracle 0 diffs; 589 pass; real ClickHouse INSERT live-only. DATE stays TEXT, flagged for the user (ADR-020) |
| D3 | 2 | unverified-live | this commit | ACCEPT after round 2: verifier REJECTed (a store error or crash between checkpoint and COMPLETE stranded a run; a failing FAIL write masked the real error); lead fixed both (resume closes the open run with its runId; `TableRun.fail` logs instead of raising), plus START-first tie-break and no companion for a vanished base. 54/54 incl. 18 attack cases (46 fail on the parent). START/COMPLETE writes fail closed (Q13), forwarding best effort. Known: a hanging collector costs 2x5 s per table (ponytail:), no event for a failure before the first table. Postgres DDL + Marquez live-only |
| D10 | 2 | accepted-cloud | this commit | ACCEPT after round 2: verifier ACCEPT (95 tests fail on main; 4548 inputs x 4 contexts: 0 extension-free diffs; 12,740 fixed-point cases); lead rejected residuals (tel: ext dropped beside isub/phone-context; non-ASCII ext digits), worker fixed both, the verifier's strict xfails for them now pass; `x45 x46` is a ponytail: ceiling. Accepted over-abstain: regionless `tel:+<cc>` without ext stays AMBIGUOUS |
| D11 | 2 | accepted-cloud | this commit | ACCEPT after round 2: lead sent back the BMPM regex reading (faithful to Commons Codec, 131/131 vs jar); verifier ACCEPT (181 fail on 805190b; 0 diffs vs the Java encoder on 7250 inputs; gen_* files byte-identical to commons-codec 1.17.1; env_id moves on a rule edit; 143/170 pairs vs 124 any-key / 119 Soundex; 22 different-name pairs never collide). Verifier F1 (super-linear cost on long values) fixed by lead: no beider_morse beyond 255 chars (ponytail: measured bound) + test. Disclosed: distinct surnames share more codes (any-key 1785 vs 1320 of 798k pairs: Jean/Zhang, Khan/Chan); keys are match candidates, not identity |
| D6 | 3 | unverified-live | this commit | ACCEPT after round 2: verifier REJECTed (COUNTRY `NA` labelled Namibia though it is a missing token; INVALID/FAILED credited as abstention; BOM, U+2028 and short-row loader bugs; `--out` traceback); worker fixed all; lead: missing-value-table inputs get an AMBIGUOUS truth (general rule, no `NA` check), 5th class `wrong-status` mirrors tests/defects/scorer.py, no 2-digit year from `yyyy` patterns, §2.4 scan reads the D6 files whole (history-free). 14,400 labels re-derived independently: 0 wrong; κ/α vs independent code on 3000 cases; byte-identical across PYTHONHASHSEED. Real engine (seed 0, n 30): 142/21/11/6/0. BART/Raha live-only |
| D2 | 3 | unverified-live | this commit | ACCEPT after round 2 (lead implemented): verifier REJECTed 3 input gaps (cost ratio inf -> silent abstain-all + non-JSON `Infinity`; NaN bin edge; bool confidence) + O(n x groups) grouping; lead fixed all, 5 strict xfails flipped. Math held: calibrated predictor over tolerance 0/400 runs (7 laws, n 20..5000), bin false-flag <= 0.5%; Chow == exact brute force on 6000 cases incl. ties/abstain-all, monotone; AURC == average over all tie orders (1e-12); attack kills 7 mutants the acceptance missed. ADR-019 states independence, per-group 5% and that the tolerance (~4x real ECE) cannot certify calibration. 61 `confidence=` sites unchanged, not wired into dispatch. Real labelled data live-only |
| D4 | 3 | unverified-live | this commit | ACCEPT after round 2 (lead finished it): ptype failed the feasibility gate (greenery 4 / pandas 3 incompatible, 311 MB) -> native detector. Verifier REJECTed: AMBIGUOUS dates reported, no "small set" bound, hint-None over-claim. Worker applied the lead's first small-set rule (mean valid count), which broke recall on categorical columns (21 tests); lead replaced it: only definitive INVALID verdicts count; recurring failing values are candidates when no more numerous than the spellings in the missing-value table (17), else only table-named ones. Recall: 12 planted sentinels at 1-5% across 6 types, exact counts; Namibia NA, year-only dates, 0/-1 never reported; 300 recurring junk strings not reported; column-type snapshot identical, type_detection untouched. 4 strict xfails = pre-existing normalizer findings (j, k, l). Live GROUP BY compare live-only |

States: `todo` · `in-progress` · `accepted-cloud` (lead accepted, cloud-verifiable parts proven)
· `unverified-live` (accepted but needs the real environment — see LOCAL_VERIFY.md) · `blocked`.

## Locked file-ownership table (Phase 0)
Derived 2026-10-05 from `graphify affected <file>` and `graft callers <sym> --depth all` (shared symbols:
`_apply_column`, `_normalize_chunk` → only `clone_executor.py`; `make_cache_key` → `clone_executor.py`,
`normexec/planner.py`, `normexec/cache.py`, `normapi/store.py`; all normalizers are registered in one place,
`normapi/app.py:150-169` `_build_registry`-style block, `registry.register(IdentifierNormalizer())` at :162).

| file | owner (item) | note |
|---|---|---|
| `normapi/clone_executor.py`, `pg_persistence.py`, `routes.py`, `schemas.py`, `normapi/adjudication.py` (new), `normapi/lineage.py` (new) | lead: D1 → D5 → D3 (serial) | shared large files |
| `normcore/enums.py`, `normcore/dispatch.py`, `tests/unit/test_dispatch.py` | lead: D1/D12 | severity tuple; D7 must NOT add a status (plan §9 D7) |
| `normio/storage_types.py`, `normio/connectors/*_destination.py` | lead: D5 | |
| `normalizers/identifier.py`, `tests/unit/test_identifier_normalizer.py` | lane B: D7 → D8 | |
| `normapi/app.py` (registration only) | lane B: D8 | **flag:** only D8 needs it (a `CODE` normalizer registration); lead serialises if D1 needs it |
| `normalizers/url.py`, `tests/unit/test_url_normalizer.py` | lane C: D9 | |
| `normalizers/phone.py`, `tests/unit/test_phone_normalizer.py` | phase 2 lane B: D10 | |
| `normalizers/name.py`, `normalizers/_bmpm.py` (new) + data | phase 2 lane C: D11 | |
| `pyproject.toml`, `uv.lock`, `normexec/env_fingerprint.py`, `tests/unit/test_env_fingerprint.py` | D9 (ph 1) → D11 (ph 2) → D4 (ph 3) | **flag:** three items, three phases; never concurrent |
| `normanalysis/gold.py`, `tests/gold/`, `normcli/cli.py` | D6 → D2 (ph 3, serial) | `cli.py` shared by D6 and D2 |
| `normanalysis/disguised_missing.py` (new), `normanalysis/type_detection.py` (hook) | D4 (ph 3) | `type_detection` feeds `clone_executor`/`routes` — hook must not change column results |
| `tests/unit/test_clone_*.py`, `tests/golden/` | lead | **flag:** normalizer output changes (D8, D9, D10, D11) can move clone/golden expectations; a worker that needs one asks the lead |
| `tests/defects/` | verifier (Phase 0 fixtures) | read-only to workers |
| `docs/adr/ADR-018..020`, `docs/` | lead | |

## Lane plan
- Phase 1: lane A lead D1 → D12; lane B worker D7 → D8 (`identifier.py`, `app.py`); lane C worker D9
  (`url.py`, deps). At most 2 subagents at once: D7 and D9 workers run while the lead does D1.
- Phase 2: lane A lead D5 → D3; lane B worker D10; lane C worker D11.
- Phase 3: worker D6 → lead D2; worker D4.

## Next action
Phase 3. Lane A: D6 derive verifier -> worker (`normanalysis/gold.py`, `tests/gold/`, `normcli/cli.py`,
`tests/unit/test_gold_*.py`) -> attack -> lead line-by-line review; then lead D2 (needs D6's
`(stated confidence, correct)` pairs). Lane C: D4 feasibility gate (`ptype` install/licence/determinism) then
derive -> worker -> attack (`pyproject.toml`/`uv.lock`/`env_fingerprint.py` owned by D4 this phase).
Start with the D6 and D4 derive verifiers (2 slots). `cli.py` is shared by D6 and D2: serial.

## Notifications
(append `[PHASE n DONE]`, `[BLOCKED]`, `[Defects D1-D12 COMPLETE]` entries here; the same prefixes go in commit messages)
- [PHASE 0 DONE] 2026-10-05: baseline, re-verification, ownership, fixtures + BEFORE numbers (PHASE0_REPORT.md §4).
  Gate: ruff/format/mypy clean, CI pytest 1319 passed / 12 skipped, `ci-fast` green on 5a93696, ponytail-review: lean.
- [PHASE 1 DONE] 2026-10-05: D1, D12, D7, D8, D9 decided (D1, D7 unverified-live; D12, D8, D9 accepted-cloud).
  Gate: ruff/format/mypy clean, CI pytest 1477 passed / 12 skipped (also in a shallow clone), `ci-fast` green on
  cde8c30 (run 37325386403). `ci-fast` had been red since f48d6a8: the D9 literal test diffed against `main`, absent
  in CI's shallow checkout; made history-free. ponytail-review of `git diff e6fa923 -- packages`: 3 deliberate keeps
  (title-term tuple is the named source; `_save_progress` else-branch keeps the old write; optional `adjudication`
  param used by direct-call tests), net -4 lines possible, none taken.

- [PHASE 2 DONE] 2026-10-06: D5, D3 (unverified-live), D10, D11 (accepted-cloud) decided.
  Gate: ruff/format/mypy clean, CI pytest 2476 passed / 23 skipped / 2 xfailed, `ci-fast` green on a09ff1c
  (run 37393201033; same tree as 76ca1ce, whose run 37367530536 never got a runner). ponytail-review of the
  phase diff (`a42c3d2..76ca1ce -- packages`): dropped the unbounded per-name Beider-Morse cache, one-line `_unquote`.
  Graphs refreshed by `scripts/cloud_setup.sh` (graft was missing from PATH at tick start; the script installed it).

## Open escalations (worker/verifier results that passed only written tests or one case)
- **D4 normalizer findings, outside D1-D12, for the user:** (j) the PHONE and CURRENCY validators answer
  AMBIGUOUS (never INVALID) for any non-matching text such as `N/A` or `TBD`, so the never-guess D4 detector
  cannot report sentinels in those columns (strict xfails in `test_disguised_missing_attack.py`); with a
  region PHONE does say INVALID. (k) `DateNormalizer.validate` costs 10-430 ms per FAILING value (dateparser
  slow path): 100k distinct failing dates = hours (`ponytail:` ceiling in `disguised_missing.py`). (l) a
  lone-surrogate string (`"\ud800"`) SEGFAULTS the interpreter in ciso8601 via `date.py` `_try_iso_fast_path`;
  any path that hands such a string to the date normalizer (clone included) can kill the process.
- **D6 engine findings, outside D1-D12, for the user:** (h) `url.py` assumes `https` for a bare host at
  confidence 0.8: under "never guess" a stated-no-scheme input is AMBIGUOUS; it is 10 of the 11 wrong-confident
  cases on the seed-0 corpus (66 of 72 at n 200), so the gold numbers are quoted with and without that kind.
  (i) the date normalizer's day/month order comes from a hand table (`_MDY_COUNTRIES = {"US"}`) while CLDR has
  34 M/d/y locales: `ee-GH` short dates are read day-first (a confident wrong answer). (c) above (day == month
  abstains) shows up as all 6 over-abstains.
- **Outside D1-D12, for the user (Phase 0 fixtures):** (a) `03/2024` normalizes to `2024-03-03` — a day is
  invented from a month-year (violates "precision is preserved, never invented"); (b) `NA` in a COUNTRY column
  is read as NOT_APPLICABLE by the `missing-values.common` dictionary (40/40 Namibia rows), the never-guess
  defect D4's acceptance names; D4 only reports and will not change it; (c) `05/05/2024` abstains though both
  readings are the same date (over-abstain); (d) `\x00` passes into TEXT columns for 22 untyped types and
  Postgres rejects NUL. None is fixed in this plan (scope); each needs the user's go-ahead.
- **Outside D1-D12, for the user:** `tests/property/test_idempotency_determinism.py::test_every_semantic_type_converges_in_one_pass[COMPANY_NAME]`
  fails (Hypothesis finds soft hyphen `\xad` -> `''` -> None, so pass 2 differs). It fails with this branch's Phase 1 changes
  stashed too, no name/company normalizer is touched here, and `ci-fast` does not select `-m property`, so it does not
  block the gate. (e) D9 verifier: a unicode IDN with a trailing dot (`https://例え.jp.`) abstains with "not valid IDNA",
  because `_normalize_host` IDNA-encodes the empty last label; this predates D9. (f) D10: a regionless `tel:+<cc>`
  URI without an extension stays AMBIGUOUS though it states its country (kept for byte-identity with the pre-D10
  output; a 2-line `ponytail:` guard in phone.py). (g) D11: Мухаммед / Muhammad / Mohammed / محمد share no key under
  faithful BMPM or Double Metaphone; not forced (a hand rule would violate the no-hand-table rule).
