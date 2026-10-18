# Defects D1-D12 — final report

Branch `feat/defects-fixes`, plan `docs/archive/plans/DEFECTS_IMPLEMENTATION_PLAN.md`, report `docs/improvement-report.md`
Part 1. Written 2026-10-06 at the end of Phase 5. **Nothing is merged: the user verifies locally and merges.**

## Outcome

All twelve items are implemented and decided by the lead after an independent verifier wrote the acceptance checks
*before* each implementation and attacked the result *after* it. Five are fully proven in the cloud
(`accepted-cloud`: D8, D9, D10, D11, D12). Seven are implemented, but part of their proof needs the real
environment (`unverified-live`: D1, D3, D5 need Postgres, ClickHouse or Marquez; D2, D4, D6 need the user's own
labelled data, a real table, or BART/Raha). `LOCAL_VERIFY.md` lists every live check with its exact command and the
expected numbers. Each phase gate ran the four `ci-fast` commands and passed on the pushed head:
- Phase 0: 5a93696
- Phase 1: cde8c30
- Phase 2: a09ff1c
- Phase 3: c75e24d
- Phase 4: a820488

The final unit + fast-golden run had 2809 passed, 23 skipped and 6 xfailed. The 6 xfails are strict and each
names a pre-existing normalizer finding (below).

Where the report and the code differed, the code won and the plan's §8 "Pre-findings" (F1-F7) records why:
- **F1:** D5's cast gate already existed; D5 proved it adversarially and closed its precision hole.
- **F2:** D10's extension was already kept in `display`.
- **F3:** decision B's verdict key (ADR-018).
- **F4:** the `confidence=` counts.
- **F6:** `ptype`. It failed its feasibility gate (`greenery.lego` and `DataFrame.applymap` are gone in current
  releases, and it pulls a 311 MB stack), so D4 is a native detector.

## Per item (lead verdicts, verbatim from HANDOFF.md)

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

Before and after numbers on planted ground truth: `PHASE4_REPORT.md`. The Phase 0 bars still unmet are D7's
Colombia and D8's `CODE -> UNKNOWN`. Both come from accepted design, not a guess, and are explained there.

## Decisions for the user

1. **Merge** `feat/defects-fixes` after the live checks in `LOCAL_VERIFY.md` (environment: `docker compose up -d
   postgres libpostal` plus a ClickHouse server).
2. **D4 wiring.** `normanalysis.disguised_missing.detect_disguised_missing` is a library function with no caller
   outside tests (Phase 5 audit). The plan asked for the detector, and a `type_detection` hook only if needed. Wiring
   it into profiling or the UI is a follow-up, left out to keep the scope.
3. **D2 cost ratio.** `normcli calibrate` refuses to run without `--cost-ratio`. The ratio (the cost of a wrong value
   over the cost of an abstention) is the user's to state (Q16, ADR-019).
4. **DATE stays TEXT** (ADR-020; partial dates). Flagged in Phase 2, unchanged.
5. **The findings below.** Each needs a go-ahead, because it is outside D1-D12.

## Decisions taken (user, 2026-10-06, local close-out)

- **Test memory cap (not a D item):** the capped CI command failed (1129 leaked DuckDB worker threads, 21.5 GB of
  address space). Root cause and fix chosen by the user: `NormalizationCache` connects with DuckDB `threads=1`
  (9bc9370), not `MALLOC_ARENA_MAX=2`; the command in CLAUDE.md is unchanged. Under the cap: 79 threads, 8.7 GB peak.
- **D2 cost ratio:** R = 20 (emit only at >= 95.2% observed accuracy; Q16). Benchmarks also report R = 100 as a
  sensitivity column. Still a report/benchmark parameter only; nothing in dispatch uses it.
- **D4 wiring:** later, in the Part 3 architecture plan. Stays a library function on this branch.
- **DATE storage (ADR-020):** keep the TEXT column and add typed companion bounds `<col>__from` / `<col>__to`
  (first and last day of the stated period; equal for a full date), built in a follow-up plan that updates ADR-020
  and D5. Not on this branch.
- **Findings, fix now on this branch (TDD, separate commits):** (l) lone-surrogate segfault in ciso8601 via
  `date.py`; (a) `03/2024` -> `2024-03-03`; COMPANY_NAME/PERSON_NAME property idempotency.
- **Fix 2 widened (user):** the root fix for every invented date component, not only `03/2024` (e0f7ed8). The
  benchmarks found its year-`00` regression, and the user approved fixing it (ef60e8a).
- **Benchmarks (user):**
  - downloads approved as listed in REPORT.md §2; CTU skipped;
  - Marquez 0.51.1 image pull approved for D3(b);
  - an isolated `normbench` stack on fresh volumes, so the user's `normalization_pg_data` was never mounted;
  - Step 7 (a copy of the user's own database) skipped.
- **Findings, deferred to a follow-up plan:** (b) `NA` in COUNTRY read as NOT_APPLICABLE (central dispatcher change,
  every type); (d) `\x00` in TEXT columns (destination-writer policy: strip vs NULL + error row); (h) `url.py` https
  guess at 0.8; (i) date M/d/y hand table (derive from CLDR).

## Local close-out results (2026-10-12)

The live checks ran on public data in an isolated docker stack, with results in `LOCAL_VERIFY.md` and the full
evidence in `docs/benchmarks/REPORT.md`. Step 7 (a copy of the user's own database) was skipped by the user.

| item | final state | live result |
|---|---|---|
| D1 | verified-live, 1 check failed | Postgres DDL and upsert pass; the round trip (queue → verdict → re-run changes the cell and clears its error rows) passes. **NUL in an AMBIGUOUS value fails the job** and loses that batch's error rows |
| D2 | verified-live | seeded corpus: threshold 0.90 at R = 20 and R = 100. Raha erroneous cells: ECE 0.276 against a 0.046 tolerance, abstain on everything; answers at a stated 1.0 are observed right 78% of the time |
| D3 | verified-live, Marquez partial | Postgres table and keys pass; `get_columns` and facets match 11/11 tables. Marquez stores the column-lineage facet, but its graph is empty (no schema facet) |
| D4 | verified-live | `N/A` found with its exact counts; Namibia `NA` not reported; limitations: `''` in some types, `empty`, `1900-01-01` |
| D5 | verified-live, ClickHouse truncates | overflow pass (NULL + error row, the chunk commits); the gate never lets an abort through. ClickHouse truncates where Postgres rounds, silently |
| D6 | verified-live | seeded baseline reproduced 142/21/11/6/0. The Raha literal command measures formatting, and its CSV loader takes no context |
| D7 | verified-live | 0 INVALID of 1,677,617 register numbers. Norway: 0 VALID (all UNKNOWN), a coverage gap |
| D8-D12 | accepted-cloud | D10/D11 persistence: not applicable, because a clone never persists the `structured` dict |

New findings outside D1-D12, not fixed (held out, for the user): REPORT.md §7.

## Findings outside D1-D12 (open escalations, verbatim from HANDOFF.md)

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
  fails (Hypothesis finds soft hyphen `\xad` -> `''` -> None, so pass 2 differs). Phase 4: `[PERSON_NAME]` fails the same way
  (`'\x7f'` -> `''` -> None); reproduced with the pre-D11 `name.py` (805190b), so not caused by D11. Every other
  semantic type converges, and determinism/display-fixed-point/never-raises pass. It fails with this branch's Phase 1 changes
  stashed too, no name/company normalizer is touched here, and `ci-fast` does not select `-m property`, so it does not
  block the gate. (e) D9 verifier: a unicode IDN with a trailing dot (`https://例え.jp.`) abstains with "not valid IDNA",
  because `_normalize_host` IDNA-encodes the empty last label; this predates D9. (f) D10: a regionless `tel:+<cc>`
  URI without an extension stays AMBIGUOUS though it states its country (kept for byte-identity with the pre-D10
  output; a 2-line `ponytail:` guard in phone.py). (g) D11: Мухаммед / Muhammad / Mohammed / محمد share no key under
  faithful BMPM or Double Metaphone; not forced (a hand rule would violate the no-hand-table rule).

## Phase 5 reviews

- **`/ponytail-review` of the whole branch (`git diff origin/main...HEAD -- packages`, vendored BMPM data excluded):**
  6 findings, about -37 lines. None taken:
  - `krippendorff_alpha(level=)` and calibration's custom bin edges are part of the verifier's acceptance contract;
  - `phone.py`'s `_URI_EXT_NAME` derives "ext" from libphonenumber because D10's §2.4 grep bans the literal;
  - reusing D4's `_defaults()` in `gold.py` would build a whole registry just to read one word table;
  - the two identifier shrinks are 1-2 lines on an accepted, named table.
  The per-phase reviews had already removed the cuts that were worth it (Phase 2: an unbounded BMPM cache, a
  one-line `_unquote`; Phase 3: `dataclasses.asdict`).
- **`/ponytail-audit` (with graphify god-nodes and grep; the graft/graphify MCP servers did not connect, the CLIs ran):**
  - **On this branch:** `disguised_missing` has no non-test caller (decision 2 above).
  - **Pre-existing, not touched here (about -250 lines possible, for a later clean-up):**
    - `normalize_batch` on about 20 normalizers, called only by tests;
    - `normio/sidecar_store.py` `write_batch`/`read_run`, test-only;
    - `text_ops.detect_encoding_confidence`, `pg_persistence.list_clone_jobs` and seven test-only accessors
      (`rules.enabled_steps`/`config_for`, `models.is_lossy`, `invariant_sampler.is_clean`, `cache.hit_ratio`,
      `run.cache_hit_ratio`, `storage_types.is_typed`);
    - the unused `_StdnumModule.compact` Protocol member.
- **`/ponytail-debt`:** `PONYTAIL_DEBT.md`, 33 markers (22 added by D1-D12), 3 with no trigger.
- **`/ponytail-gain`:** published benchmark medians only. No per-repo savings number is claimed, because the unbuilt
  version was never written.

## Appendix — verifier verdicts (folded from `.handoff/`, which is purged)

The acceptance contracts, worker reports and verdicts stay in git history (`git log -- .handoff/`). The verdicts
follow verbatim.

### D1.verdict.md

### D1 verdict: REJECT (two small fixes; everything else ACCEPT)

Evidence: `tests/unit/test_adjudication_acceptance.py` 49 passed, 3 xfailed (strict). Existing clone, pii, routes, agent-docs,
scorer tests (172) pass unchanged. ruff check + format clean on the test file. §2.4 grep clean. Pool path (2 spawn workers)
verified by ad hoc script: identical result to serial.

#### ACCEPT (verified, beyond the worker's own tests)
Accept (1)-(8), NEEDS_REVIEW producer, typed MONEY + companion column, derived-country group, NULL/"" cells, resume (both
crash shapes), no raw value in any API body. Spec observation: DATE and PHONE refusals have no error row on main (`errors == []`),
only MONEY does; the "error row" half of Accept (1) is only meaningful on MONEY.

#### REJECT reasons (xfail strict in the test file; remove the marker when fixed)
1. **Whitespace-only decided value is accepted (201) and silently NULLs the cell forever.** `POST .../verdicts` with
   `decided_value=" "` (also `\t`, NBSP) re-normalizes to NORMALIZED with `display=None`, passes CLEAN_STATUSES; every later run emits NULL
   for that value with no error row and no quality count (empty-string kind is uncounted). One API call destroys a value; violates Q16.
   Fix: in `post_adjudication_verdict`, refuse when `result.display is None` (decided value must normalize to a value).
2. **Regression vs main: a lone surrogate in an AMBIGUOUS PHONE (or any type with no error row) fails the whole chunk.** Repro:
   `{"p": "<ambiguous phone>\ud800"}` completes on main (`adjudication=None`) but the queue upsert raises `UnicodeEncodeError`
   in `save_clone_job_and_enqueue`. (MONEY/INVALID with a surrogate already crash on main via the error-row insert, so this is
   a known class, but this path is new.) Fix: do not queue (or sanitize) a value that is not valid UTF-8, as `normcore.pii.content_hash` already
   uses `surrogatepass` deliberately.

#### Notes (not blockers)
- Pre-existing, not D1: DATE `03/2024` -> `2024-03-03` (invents a day; fixture `prec-month-year`, xfail in my test). Decided value of 5000 digits makes
  dateparser raise `ValueError`, so POST returns 500 not 422 (normalizer bug, route could catch).
- Verdicts are read once per job (`_verdicts_for` cache): a verdict posted mid-job applies next run. Matches ADR wording.
- POST on a queue row of an older profile version returns 409 (undocumented in ADR; reasonable).
- Rationale text is stored and echoed unmasked; a human pasting the raw value there defeats masking (policy, not code).

#### implemented, unverified (needs live data)
- Real Postgres DDL for the two tables and `INSERT ... AS q ... ON CONFLICT (key) DO UPDATE` with the `CASE` on `q.last_job_id` (only SQLite run).
- Postgres rejects lone surrogates and NUL in text: queue `original` with NUL (AMBIGUOUS phone/money containing `\x00`) untested on PG.
- Concurrent jobs upserting the same key; `ORDER BY decided_at` on a real timestamp type; phone/date/money producers on a real clone (LOCAL_VERIFY).

### D2.verdict.md

### D2 attack verdict (commit a3851ca): REJECT round 1 (math ACCEPT; 3 small input-validation defects, one-line fixes)

Run: acceptance 62/62 green, attack `tests/unit/test_calibration_attack.py` 37 pass + 5 strict xfail (ruff clean, 2 s of Monte Carlo inside, rest here). Only the worker's 62 tests were not enough: 7 of 12 mutants of `calibration.py` survived them (no McDiarmid term, McDiarmid/3, no Bonferroni, delta .05 -> .5, Chow tie to the lowest threshold, no abstain-all baseline, AURC without tie spreading). The attack file kills all 7.

#### Math (verified, no defect)
- ECE = (1/n) sum|S_b|; E|S_b| <= sqrt(n_b)/2 (Var of sum c(1-c) <= n_b/4), Cauchy-Schwarz over bins gives sqrt(bins/n)/2. Correct.
- McDiarmid 2/n: replacing one pair that stays in a bin changes S_b by up to 2 (two terms in [-1,1]); one that moves bins changes two S_b by up to 1 each. Both <= 2, so ECE differences <= 2/n and t = sqrt(2 ln(1/d)/n). The "2/n" is right in both cases.
- Hoeffding flag: under "accuracy >= stated" with independent Bernoulli(c_i), P(sum(ok-c) <= -n g) <= exp(-2 n g^2); Bonferroni over k bins (empty bins counted: conservative). Correct. Boundary pinned: n=100 at 0.95 flagged at gap .17 (78/100), not at .15; bins=1 flags gap .16, bins=10 does not.
- Monte Carlo, 400 runs x {uniform, all 0.99, two spikes 0.5/0.99, U[.8,1], U[0,.2], {0,1} extremes, 70% 1.0 mix} x n in {20,50,200,1000,5000}: ECE > tolerance in 0/400 everywhere; any bin flagged on a calibrated predictor <= 0.5% of runs (per-bin <= 0.05%). Valid but very conservative: tolerance is ~4x the real calibrated ECE (n=1000: tol .127, real mean .031 / max .051), and a predictor over-confident by 0.1 everywhere has ECE .10 < tol .127. So "ECE under tolerance" cannot certify calibration; the bin flags carry the power.
- Power (stated 0.95, one bin): flagged >= 50% of runs at gap .24 (n=50), .16 (100), .12 (200), .08 (500), .06 (1000), .03 (5000); matches sqrt(ln 200 / 2n). n=20 cannot flag even 0.99 vs 0.80. Hoeffding ignores the small variance near 0.99, so spiky-high engines are under-powered (honest, never false-positive).
- Chow vs exact-Fraction brute force: 6000 cases (ties, ratios 0.1..1e9, all-right, all-wrong, abstain-all = inf, n=1) 0 mismatches in cost and in tie-break; monotone in ratio 0/2000 violations; report turns inf into `threshold: null, abstain_on_everything: true` (allow_nan=False passes).
- AURC vs exact average over all tie permutations (n<=6, 120 cases) equal to 1e-12; empty -> ([], None); single pair ok.

#### Confirmed defects (strict xfail in the attack file)
1. `chow_threshold(pairs, math.inf)` and `normcli calibrate --cost-ratio inf` accepted (`not inf > 0` is False). inf*0 = NaN so no cost compares: returns inf (abstain on everything) when the correct optimum is t=0.8 on the toy; CLI exits 0 and writes `"cost_ratio": Infinity` (not JSON). Fix: `math.isfinite` check beside `> 0` (library) and in `_run_calibrate`.
2. NaN bin edge `bins=(0, nan, 1)` passes `_edges` (`nan >= x` False); returns a nan-bounded bin. Fix: `math.isfinite`/`a < b` form.
3. bool confidence accepted as 0.0/1.0 (`reliability([(True, 0.8)])`): a swapped (correct, confidence) tuple is silently scored. Fix: reject `bool` in `_check`.
Minor, not xfailed: `bins=True` means 1 bin; group labels of mixed type or None raise a bare TypeError from `sorted`; an unwritable `--out-md` leaves a written `--out-json` behind (rc 2); an empty corpus exits 0 with an empty report; `ece_tolerance` prints a vacuous "stays under 2.326" at tiny n.
4. Perf ceiling (xfail, ponytail-grade): groups use one pass per label, O(n x groups): 1e5 labels over 1e5 pairs = 21 s; 1e6 pairs with 10 groups is fine. ADR allows a source id as group key, so bucket once if that is ever used.

#### Other checks (pass)
- Speed at 1e6 pairs: reliability .4 s, +10 groups 1.2 s, chow .9 s, risk_coverage 1.4 s, full report 3.6 s (all-tied 1e6: .4 s).
- `pair_types` aligned with `pairs` over a shuffled corpus with None-confidence and AMBIGUOUS answers interleaved; grouped ECE equals the ECE of each type's own pairs; group of one case ok; length mismatch (short and long) ValueError.
- CLI: no/NaN/neg/zero/bad `--cost-ratio` exits non-zero with no files; missing corpus, directory as corpus or as --out, CSV with and without `--semantic-type` handled; CLI passes no `bins`, so its default is the library's `_BINS` (checked: 10 identical edges).
- §2.4: AST scan, only literals 0.05 and 10, both with `ponytail:` comments; `git diff a833cee HEAD -- packages` touches only calibration.py, gold.py (+2 lines), cli.py; normalizers/normcore/normapi/normexec/normio untouched; `confidence=` still 19 files / 61 sites; no module outside normcli references calibration.
- Report claim on `gold generate --seed 0 --n 30` (180 cases, 153 pairs): TRUE. Flagged bin [0.8, 0.9) has 16 pairs, accuracy .3125; 10 are URL at 0.8 and all 10 are `url/bare-host` AMBIGUOUS truths where the engine emitted https:// (wrong-confident); 6 are DATE at 0.85 (5 right). The URL group alone has ECE .267 and is the only group flagged. Caveat: this is a corpus designed to contain bare-host ambiguity, so it shows the instrument works, not the engine's production calibration.

#### Implemented, unverified (needs live data)
- Real-engine reliability on the user's labelled data (LOCAL_VERIFY): whether the 28 literal `1.0` sites are honest.
- The Hoeffding/ECE bounds assume independent pairs; a corpus with near-duplicate cases (injector families) violates that and the bounds are then optimistic. The ADR does not state this assumption.
- Per-group flags are family-wise 5% per group, not across groups (many types x bins multiplies tests; observed rate still <= 0.5% because Hoeffding is conservative).
- ADR text says ECE bound uses "n answers"; true only for pooled pairs, not per group (no per-group tolerance is reported).

To ACCEPT: fix 1-3, then `pytest tests/unit/test_calibration_attack.py` will XPASS-fail those three markers; remove them.

### D3.verdict.md

### D3 verdict (attack): REJECT (two small, cheap fixes; everything else holds)

Commit a000eae. Original 36 acceptance cases: 36 pass. test_clone_* (71) + test_in_place_clone/test_normapi/test_clone_routes/secrets (45): pass.
Negative case: same test file against a scratch copy of the parent (a000eae~1, PYTHONPATH to its src, no stash): 46 failed, 8 passed (4 guards + 4 attack cases that are vacuous there).
Added attack tests (18, class names TestAttack*) to tests/unit/test_lineage_d3_acceptance.py: 13 pass, 5 FAIL on a000eae (below). ruff/format/mypy clean on the test file.

#### Blocking
1. A lineage-store error at COMPLETE strands a finished table with no COMPLETE forever (Q13 hard requirement).
   COMPLETE is emitted after _save_progress. If save_lineage_event raises there, the job goes FAILED with the table already in tables_completed; on retry the table is skipped, so its START never gets a terminal event. Same hole after a crash between checkpoint and COMPLETE (the ponytail note accepts the crash case; the plain DB-blip case is not a crash and is reachable).
   Repro: test_a_store_failure_at_COMPLETE_must_not_strand_a_finished_table_without_COMPLETE, test_a_crash_between_checkpoint_and_COMPLETE_is_repaired_on_resume.
   Fix, cheap: on resume, for a table in tables_completed whose last START has no terminal event, emit COMPLETE with that START's runId (list_lineage_events already has the data). Or write checkpoint + COMPLETE in one transaction.
2. A failing FAIL-store hides the real cause: emit("FAIL") sits in the except block, so its exception replaces the original one and job["error"] = "metadata db down", not "disk full". test_a_failed_store_of_FAIL_does_not_hide_the_original_error. Fix: wrap the FAIL emit (try/except, log) so `raise` re-raises the original; or keep fail-closed but chain the message.

#### Decision: should a lineage-write failure fail the job?
Yes, for START and COMPLETE/FAIL stores: audit is a hard requirement (Q13), so fail closed (confirmed: test_if_the_store_cannot_write_the_job_fails_closed passes, job FAILED with the DB error). Forwarding stays best effort. The one exception is the FAIL emit (finding 2): the job is already failing, so losing the FAIL row must not replace the real error.

#### Non-blocking findings (tests included where marked)
- Hanging endpoint: bounded but long. 5 s timeout x 2 events = measured 10.05 s per table with a never-answering socket, synchronous on the job thread (100 tables = ~17 min). Passes <15 s. Consider async/queue or one short timeout. A server that answers headers then trickles the body costs 0 s (body not read); slow-header trickle not tested.
- Failure before the first table (entity-map error) and source.get_columns raising: no run exists, so no START/FAIL; the job is FAILED but lineage is empty or lacks that table (pinned by two passing characterisation tests). Cheap fix: build the run inside the try, or emit job-level FAIL. Your call; the contract did not require it.
- Companion of a base column the source lacks (destination_plan names `gone`, source has no `gone`): facet claims inputField `gone`, a nonexistent source column (test_a_companion_of_a_vanished_base_column_is_not_claimed FAILS). Needs drift between phase 1 and 2, so low likelihood. A plain configured-but-vanished column makes the executor fail the table, which yields START+FAIL (passes).
- Ordering: list_lineage_events orders by (event_time, table_name) with no tie-break; two events with identical eventTime come back COMPLETE-before-START if the physical order is that way (test_identical_event_times_... FAILS when forced). Add `CASE event_type WHEN 'START' THEN 0 ELSE 1 END` as the last key, or order by a sequence column.
- In-place: output dataset name is the final table, not the staging name (pass). In real in-place the source and destination datasets are identical; Marquez shows a self-loop (unverified).
- Typed destination: runs and validates (pass); the cast to a native type is not described as a transformation (the description names only the normalizer). Not wrong, incomplete.
- Dotted names: `db.schema.table` joins with "." so database "a.b" + table "c" equals database "a" + table "b.c". Unambiguous only by convention (OpenLineage's own).

#### Held up (pass)
Dots/quotes/unicode/`;--` in table and column names: valid events, round-trip, spec-valid. source_schema in the input name only. file:// FILE:// ftp:// never opened. Userinfo URL `http://u:pw@host/`: not in logs (only the exception type is logged), not in payloads, no Authorization header. Resume emits no second COMPLETE. §2.4: acceptance grep clean on lineage.py; its one constant (5 s) carries a ponytail: note; 155 added lines. No dependency change (pyproject.toml/uv.lock untouched by a000eae).

#### Implemented, unverified
Real PostgreSQL DDL and ON CONFLICT DO NOTHING (SQLite only here); Marquez ingestion and its column-lineage UI; real connector get_columns shapes (ClickHouse/Postgres); behaviour behind a corporate HTTP proxy (NO_PROXY was set for local tests; urllib honours HTTP_PROXY otherwise).

### D4.verdict.md

### D4 verdict (attack): REJECT (narrow, 3 fixes) -- commit d60375c, `normanalysis/disguised_missing.py`

#### Passed
- Worker/acceptance: 38/38; type_detection + coverage tests 69 passed together (snapshot unchanged; type_detection.py untouched, `git status` clean apart from my test file).
- My `tests/unit/test_disguised_missing_attack.py`: 30 passed, 4 xfail(strict) = confirmed defects. Run: `( ulimit -v 16777216; uv run pytest tests/unit/test_disguised_missing_attack.py -q )` (~20 s).
- Recall: EMAIL, PHONE (all libphonenumber example numbers), COUNTRY (all pycountry alpha-2), CURRENCY, URL, DATE, DATETIME, POSTCODE(US): 12 sentinels (`N/A n/a NULL none ? -- TBD #N/A nan unknown null -`) planted at count 4 / 1-5% -> all reported with exact counts, 0 valid values reported. `0000-00-00`, `""`, whitespace reported for DATE/DATETIME.
- Precision: all 249 ISO alpha-2 incl. NA (Namibia), NO/IN/IS/ID/TO; year-only, `2020-05`, `April 2020`; all example phones; NUMERIC `0`/`-1`/`-999` (documented ceiling); count-1 junk in a 1e9-row column -> []. 49/51 reported, 50/50 and 51/49 -> [].
- Hint mapping = Dispatcher lookup (`strip().casefold()` into missing-values.common): `" none "`->NULL, `Unknown`->UNKNOWN_VALUE, `?`->UNKNOWN_VALUE. Non-str keys, <=0 counts, 1e18 counts, garbage country/locale, 17 hostile strings x 15 types: no exception. Input unmutated, order-independent.
- §2.4 grep: no hand sentinel list, no threshold literals (only structural `0`/`1`, and "97%" in a docstring example). Never-guess: NA/Namibia, year-only, partial dates not reported.

#### Defects (REJECT reasons)
1. FALSE REPORT, never-guess: `03/04/2020` (DateNormalizer status AMBIGUOUS without locale; VALID/PARSED with country US or DE) is reported as a disguised-missing candidate, count 4, hint None. `validate().is_valid` conflates AMBIGUOUS with INVALID. Fix: treat a normalize status of AMBIGUOUS (or any "needs context") as not-missing; xfail `test_ambiguous_date_is_not_reported_as_missing`.
2. "recur as a small set" (plan §9 D4) is not implemented: no cap, 300 distinct `junk value N` x2 beside valid dates are all reported (`recurs` is the literal `count > 1`, independent of column size; in 1e9 rows any twice-seen typo "recurs"). Worker admits this. Need a derived bound (e.g. failing distinct vs failing cells, or distinct failing <= distinct valid) or an explicit lead waiver. xfail `test_many_distinct_recurring_invalid_values_not_all_reported`.
3. Over-claim: values with hint None (`2020-13-45`, `john@@x`, `zz-top`, `EU`/`XK`/`AN` in COUNTRY, national phones without a region: `(201) 555-0123` x6) are returned as `DisguisedMissing`. The docstring says hint is "not a verdict" but never says hint=None means "non-conforming, NOT known to be missing". Rename/field (`is_sentinel`) or say so in the docstring and report.
#### Findings for the lead (not blocking)
- Performance: detector validates every distinct value. DateNormalizer.validate on FAILING values costs 11 ms (junk) to 150 ms (digit strings) to 430 ms (`1900-01-01#0`) -> 100k distinct failing DATE values = 20 min to 12 h. Valid values 0.1 ms. EMAIL/PHONE/URL/COUNTRY ~1-10 s per 100k. xfail `test_failing_dates_validate_fast` (40 digit strings must be < 1 s; takes ~6 s).
- Pre-existing, reachable: a lone-surrogate key (`"\ud800"`) SEGFAULTS the interpreter in ciso8601 (`date.py:502 _try_iso_fast_path`). xfail (subprocess) `test_lone_surrogate_key_does_not_crash_process`. Fix belongs in date.py, or filter unencodable keys in the detector.
- Validator-accepts-sentinel blind spots (silent, by design): `NA` valid for DATE/DATETIME and COUNTRY, `TBD`/`nan`/`NA` valid LANGUAGE codes, `0` valid BOOLEAN, `""`/whitespace valid for UUID, NUMERIC/MONEY/QUANTITY `0 -1 -999 9999`. Dispatcher maps `na` -> NOT_APPLICABLE BEFORE validation, so a Namibia column is mis-nulled by the existing pipeline regardless of D4.
- A sentinel seen once (`N/A` x1 in a 1M-row DATE column) is never reported even though the dictionary names it; consistent with the plan, flag if unwanted.
- `""`, whitespace, `#N/A`, `nan`, `TBD`, em dash get hint None (not in the dictionary; MissingKind.EMPTY_STRING exists but is unused).
- National-format values are region-relative: same column reports them without a region, not with `country=US` (test passes, documents it). Lowercase type name `"date"` raises ValueError (documented).

#### Implemented, unverified (needs live data)
- Comparison with a real `SELECT value, count(*) GROUP BY` (LOCAL_VERIFY); behaviour at >=1e6 distinct values on a real DATE column; PHONE/POSTCODE with real per-row country contexts; ptype upgrade path.

### D5.verdict.md

### D5 verdict (attack, commit 24d2e9b): REJECT (one reproducible gap; everything else holds)

#### Evidence
- Run: acceptance + test_typed_destinations: 571 passed / 6 skipped on the worker's commit (before my additions).
- Negative case: the old `storage_types.py` (24d2e9b^) swapped into the module namespace: 89 acceptance cases fail, the new end-to-end engine test fails. The gate really did not exist before.
- 20,047 fuzz inputs (random digit strings, signs, exponents, -0, +1e3, sNaN, 1e-999999999, 9e999999999, half-up carry at the boundary, 5000-digit strings) x {postgres,clickhouse} x {NUMERIC,MONEY}: coerce never raised, and its fit verdict agrees with an exact-arithmetic ROUND_HALF_UP oracle for every bounded column (the only "mismatches" were zeros with exponent >= 400 in my oracle, which the gate correctly accepts).
- Every caller: `_normalize_table` -> `_normalize_chunk` -> `_apply_column` -> `_apply_value` -> `coerce` passes `engine=source_engine`; resume and in-place both go through `_normalize_table`. Only `tests/defects/measure_phase23_before.py` (a measurement script) omits it. New end-to-end test spies on the real coerce during a real `_normalize_table` pass: engine arrives on both engines.
- Real PostgreSQL 16.14 (scratch instance, psycopg 3, Decimal bound as parameter), 2 x ~20,000 values: no gate-rejected value is accepted by PG (0 over-rejection); the 131072-digit ceiling is exact (1e131071 and 12e131070 insert, 1e131072 does not).
- §2.4: added lines carry no un-noted literal >= 10 (131072 has a ponytail note naming the source); grep test green. DATE decision ("keep TEXT", partial EDTF, flagged "for the user's decision") is recorded in docs/adr/ADR-020-typed-destination.md lines 52-65. No stale "every column TEXT" claim remains (the 38-significant-digits comment was reworded; postgres/clickhouse destination comments already correct).

#### The defect (REJECT reason): the gate accepts values the real Postgres column rejects
Postgres NUMERIC stores at most 16383 digits AFTER the point. A Decimal with exponent < -16383 passes `_fits` (it is tiny, so `adjusted()` is negative and quantize rounds it to 0) but INSERT fails with `value overflows numeric format`, on both unbounded NUMERIC and NUMERIC(38,4), aborting the chunk and its error rows: the exact D5 failure class.
Reproduced on PG 16.14: `1e-16384`, `5e-16384`, `0.5e-16383`, `12345e-16387`, `-1.5e-20000`, `0e-16384`, `1e-999999999`, `0e-999999999` (NUMERIC and MONEY) all gate-accepted, all INSERT-rejected. `1e-16383` and `0e-16383` fit and must stay accepted. The worker's own storage_types comment already states "16383 after". Fix is the same shape as the 131072 ceiling: reject when `number.as_tuple().exponent < -16383` on postgres, with a `ponytail:` note naming the PG docs (the §2.4 grep will otherwise flag the literal).
Tests (fail now, in tests/unit/test_typed_destination_d5_acceptance.py): `TestPostgresScaleCeiling` (16 fail, 4 guard cases pass). Not asserted for ClickHouse (unverified).

#### Implemented, unverified (no ClickHouse available; no live clone run)
- Real ClickHouse INSERT of anything the gate accepts: Decimal(38,9)/(38,4) rounding vs truncation of excess fraction digits, huge-exponent tiny values (`1e-999999999`), `0e999999999`.
- A full clone through the API against real databases (LOCAL_VERIFY D5 overflow): count(*) vs /errors.
- Design nit, not a rejection: `engine` defaults to "postgres" in `_apply_value/_apply_column/_normalize_chunk`; a future caller that omits it on a ClickHouse job silently gets the unbounded-Postgres limit. A required parameter would make that impossible. The plan uses dest_conn["engine"] while the cast uses source_conn["engine"]; equal only because Phase 1 refuses cross-engine clones.

### D6.verdict.md

### D6 verdict (attack): REJECT (small, specific fixes; everything else holds)

Commit 7b61834 (gold.py + normcli gold). Attack tests: `tests/unit/test_gold_attack.py` (91 pass, 11 xfail strict = 11 confirmed defects, ruff/mypy clean).
Batch: `( ulimit -v 16777216; uv run pytest tests/unit/test_gold_attack.py tests/unit/test_gold_acceptance.py -q )` -> 149 pass, 11 xfail, 1 FAIL.
The 1 FAIL is a harness artifact, not a gold.py bug: `TestSection24Grep::test_added_lines_hold_no_corpus_value` asserts gold.py is in `git diff HEAD` or untracked; gold.py is now committed, so the scan misses it. I ran the same `_violations` over gold.py's full text against all 757 banned literals: 0 hits (point 7 clean).

#### Why REJECT
1. WRONG LABEL (the worst class): COUNTRY `code`/`code-lower` emits `NA`/`na` with truth NORMALIZED `NA` (Namibia). `NA` is the canonical missing-value token (pandas default NaN); the text states no country. The real engine answers NORMALIZED with value None (seed 1: 1 wrong-confident of 3000). A careful engine that abstains would be scored over-abstain. Truth should be AMBIGUOUS (Namibia or missing) or the case excluded. xfail: `test_no_country_case_collides_with_a_missing_value_token`.
2. `classify`: INVALID/FAILED/PARTIAL/NEEDS_REVIEW on an AMBIGUOUS truth are credited `correct-abstain` (tests/defects/scorer.py calls them wrong-status; report says "mirrors"). A crash (FAILED) or a confident "invalid" on `1,234` earns credit. xfail x2.
3. Loader: UTF-8 BOM CSV -> `KeyError('dirty')` (Excel export; use `utf-8-sig`); BOM JSONL -> JSONDecodeError; `dump_cases` writes raw U+2028/U+2029/U+0085 (`ensure_ascii=False`) and `load_cases` uses `str.splitlines()`, so such an input cannot round-trip (JSONDecodeError; use `split("\n")`); a short CSV row loads as PARSED with `expected_value=None`, and `GoldCase` accepts a clean truth with no value, so a value-less clean answer scores "correct". xfail x6.
4. `gold generate --out` into a missing dir: uncaught traceback rc 1 (score exits 2 cleanly). xfail x1. Minor.

#### Evidence per point
1. Labels (14,400 cases, seeds 0-9, independent derivations): PHONE parsed == libphonenumber E.164 + valid (0 bad); region-removed strings: none start with `+`, `parse(.., None)` always raises, 229 distinct strings, 228 valid in >=2 regions (one, BY `8 0152 45-09-11`, valid only in BY; still names no country, label kept; 13 start `00`/`011`, an IDD prefix that names no country by itself). DATE locale: Babel `parse_date(format="short")` == truth on every case (0 bad); swap-ambiguous parts <=12 and different, candidates exact (0 bad); decided/same-day/year-only (0 bad). NUMERIC locale: `parse_decimal(strict)` == truth (0 bad); us-both/eu-both/repeated/plain/lone-group by an independent rule (0 bad). COUNTRY: no NORMALIZED label's text means two codes in ANY CLDR locale (the 7-locale meaning map misses nothing; the AMBIGUOUS country path is never produced, 0 shared names, so it is "implemented, unverified"). EMAIL/URL: RFC 5321/3986 (0 bad).
   Contested, not a defect (lead to decide): swap-ambiguous uses sep from `/-.`; CLDR short patterns put M/d/y only with `/` (34 locales), never with `.` or `-`, so 2/3 of that kind is "ambiguous" only by the never-guess rule. The engine also abstains, so no engine is punished today; a DMY-from-dots engine would be.
2. classify on all 9 statuses x {right, wrong, None} x truths {PARSED, AMBIGUOUS, INVALID, FAILED}: total, 4 classes only; clean+None is wrong-confident; unknown status string raises ValueError; pairs = clean answers with confidence only. Gaps above (2).
3. Loader: empty/blank files, CRLF, bad status/type/context key, missing/extra keys all raise (TypeError for missing/extra keys, not a friendly ValueError); semantic_type never guessed; semicolon CSV -> KeyError. Not validated: candidates as a string splits into chars; input None/int accepted.
4. Determinism: sha256 of `generate_corpus(7,40)` identical under PYTHONHASHSEED 0/1/random/31337 in separate processes; each family at n=10 is the exact prefix of n=40 (no cross-shift); seeds 1/-1/2 differ; seed 2**70 and n=0 fine. PASS.
5. kappa/alpha: 3000 random cases vs independent confusion-matrix kappa and pair-enumeration alpha (with missing data): 0 diff; NaN where undefined (empty, 1 coder, all missing, no variation); ragged/unequal raises. Note: a float NaN label is a category, not missing (`alpha([[1,0,1],[1,1,nan]])` = -0.11 vs None = 0.0; `cohen_kappa([nan,1],[nan,1])` = 0.0); contract says None = missing, so not asserted.
6. CLI: generate writes exactly `dump_cases(generate_corpus(..))`; score on JSONL (36 cases) prints the 4 classes, rc 0; score on CSV with `--semantic-type` rc 0, without -> rc 2 with message; missing/malformed file rc 2; empty corpus prints zeros rc 0 silently; rc is 0 even with wrong-confident > 0 (no gate by design). CSV BOM -> rc 2 (defect 3).
7. Grep: clean (above). Undeclared deps: normanalysis/pyproject does not list babel/phonenumbers/pycountry (root pyproject does for the latter two).
8. Real engine reproduced exactly: 142/21/11/6 on `generate_corpus(0,30)`. Classification:
   - over-abstain 6 (DATE same-day-month, e.g. `08.08.2014`): label TRUE (both readings give 2014-08-08); REAL engine finding (harmless conservatism; `_is_ambiguous_numeric_date` ignores a==b). At seed 1 n=200: 40.
   - wrong-confident 1 (DATE locale ee-GH `10/7/2026`): label TRUE (CLDR `M/d/yy` -> 2026-10-07; engine says 07-10 at 0.85). REAL engine finding: `date.py` `_MDY_COUNTRIES = {"US"}` hand table; CLDR has 34 M/d/y locales (also seen: en-VI, ceb-PH, en-BI, ak-GH, or-IN; 5 of ~40 locale cases at n=200). Violates "authoritative data over hand table".
   - wrong-confident 10 (URL bare host): label per lead policy; 10/11 of the wrong-confident at n=30, 66/72 at n=200. It dominates the wrong-confident rate; any headline number should be quoted with and without `url/bare-host`.
   - extra at wider n: COUNTRY `na` (bad label + engine returns NORMALIZED/None, a real engine/D4 finding).
   - PHONE, NUMERIC, EMAIL, COUNTRY(other): 0 misses (seed 5, n=150), so those corpora do not yet discriminate; passes only prove the harness.

#### Implemented, unverified
- BART output and the six Raha datasets (JVM/Postgres/downloads) through the CSV loader; Raha's two-file layout needs a manual merge.
- COUNTRY AMBIGUOUS branch (no shared name exists in the 7 locales + ISO codes, never exercised).
- Calibration `pairs` measure the harness, not real-data calibration (D2 needs a real corpus).
- Reproduction of Artstein & Poesio / Krippendorff published values rests on the acceptance tests; I confirmed the formulas by independent computation, not the papers.

#### Minimal fix list to flip to ACCEPT
(1) NA/`na` country label -> AMBIGUOUS or exclude; (2) INVALID/FAILED/PARTIAL/NEEDS_REVIEW on AMBIGUOUS truth -> not `correct-abstain` (or document and test the choice); (3) `encoding="utf-8-sig"` for both loaders, split on `"\n"` not `splitlines()`, reject CSV rows with a missing `clean` cell and clean truths with no value; (4) catch OSError in `gold generate`. Then remove the matching xfail markers (strict, they will XPASS). Also repair the acceptance test's gold.py-in-scan guard now that the file is committed.

### D7.verdict.md

### D7 + D8 verdict (attack) - ACCEPT (functional), one non-functional DoD fix required before close

#### Evidence
- Acceptance + unit: tests/unit/test_identifier_d7_d8_acceptance.py + test_identifier_normalizer.py: 60 passed, 0 skipped (-rs).
  The Round-2 failing probe test was already loosened (accepts UNKNOWN "valid under another ..."). Also m5 corpus + dispatch + idempotency: 65 pass.
- Negative on old code (47df753 identifier.py injected via pytest plugin, working tree untouched): 21 failed / 39 passed
  (16 acceptance incl. unlisted country VALID->UNKNOWN, PT/GR twin VALID!=INVALID, TAX_ID==CODE; 5 new unit tests incl. sibling ones).
- Classification judged by hand: printed the chosen/candidate module title for all 86 stdnum packages: 65 classified, 6 multi (AT ES EU FI IN IT),
  15 none. Every chosen module is a tax/VAT id; no non-tax module selected. EU is the only non-ISO package (multi -> unverifiable).
- Never-guess: 300 random numbers x 65 classified countries: 0 inconsistent outputs (VALID<->check_digit_valid True, INVALID<->normalization INVALID,
  UNKNOWN always verification=unverifiable); INVALID still reachable in every classified country (not collapsed to UNKNOWN).
- Sibling rule: for every country x non-chosen sibling with a findable number (69 cases, raw and stdnum-formatted, lowercase cc) result is UNKNOWN, never INVALID.
- Odd input (emoji, Arabic-Indic digits, 80 and 20000 chars, NUL, ZWSP, empty, fullwidth) x 86 countries + us/Gb/" de"/ZZ/XX/"" x 3 types:
  no crash, never "validator raised"; CODE always UNKNOWN with no check/valid key; IDENTIFIER always VALID (unchanged); unlisted/blank country -> UNKNOWN.
- 2.4 grep: only hits are the 4 legacy-map lines (commented). Fixture literals absent from packages/. No new threshold literal.
- ruff check/format, mypy packages/normalizers: clean.

#### Findings (not blockers for behaviour)
1. DoD item unmet: only ONE ponytail: marker exists (identifier.py:72). The "Deferred alternative" for _LEGACY_TAX_ID_MODULE (line 81) is
   not prefixed `ponytail:`, so /ponytail-debt will not harvest it; the worker's report ceilings (narrow chosen module: AU TFN, UA RNTRC, LI PEID, ZA TIN;
   EU not an ISO country; sibling rule is "never confident INVALID" and costs N is_valid calls per invalid value) are not in code. Fix = comments only.
2. Legacy four changed vs plan "byte-identical": old-vs-new diff over 1260 US/GB/DE/FR inputs: 217 differ, ALL INVALID/0.3 -> UNKNOWN with reason
   "valid under another <CC> identifier" (US 11, GB 20, DE 184, FR 2); VALID outputs, IDENTIFIER, and every other field identical. Lead-directed Round 2;
   must be listed in HANDOFF.md expectations-moved (DE is large: de siblings such as idnr accept ~30% of random 9-11 digit strings).
3. Unrelated red: tests/property/test_idempotency_determinism.py::...[COMPANY_NAME] fails ('\xad' -> '' -> None); name normalizer is not in this diff.
   Worker reported 17 pass; not reproduced as caused by D7/D8. Unverified whether it is pre-existing on 47df753 or from another lane.

#### Implemented, unverified
- Real-world valid numbers for most new countries (tests use stdnum's own calc_check_digit twins; alphanumeric siblings not exercised by brute force: 26 sibling pairs had no findable number).
- The "validator raised" path (only monkeypatched; no stdnum 1.20 input triggers it).
- ctx.country formats other than ISO-2 (alpha-3, names, "UK") fall to UNKNOWN, safe but untested upstream.

### D9.verdict.md

### D9 verdict (attack): ACCEPT

Diff: `git diff 47df753` over url.py, normexec/env_fingerprint.py, normalizers/pyproject.toml, uv.lock, dependency-inventory.md, 2 unit test files.

#### Evidence
- Acceptance + unit (batched, ulimit 16 GB): test_url_psl_acceptance + test_url_normalizer + test_env_fingerprint = 99 passed. tests/golden/test_m4_corpus.py + tests/property/test_idempotency_determinism.py = 39 passed, 2 skipped.
- Negative on old code: pre-change url.py (`git show 47df753:...` loaded via a scratchpad pytest plugin, tree untouched) -> 33 failed / 52 passed on psl_acceptance + url_normalizer (all missing-key failures; the 52 passes are the byte-identical snapshot guards, which must stay green).
- Independent attack (new, `tests/unit/test_url_psl_attack.py`, 62 passed with the acceptance file): my own PSL algorithm (parses the bundled .dat; wildcard, `!` exception, ICANN vs PRIVATE) cross-checks registrable_domain / public_suffix / is_private_suffix on >15000 hosts (every rule x 3 depths). Zero disagreements. Mutation (`_PSL_ICANN = _PSL`) makes it fail, so it is not vacuous.
- Probed by hand: `*.ck`/`!www.ck` (a.b.ck -> b.ck, www.ck -> ck, a.ck is a suffix -> None), kobe.jp wildcard/exception, github.io / blogspot / s3.amazonaws private=True, bare `github.io` private=True but domain None, bare `co.uk` None, IPv4/IPv6/bracketed/::ffff: None+reason, `127.1`, `2130706433`, `0x7f.1` None, `a.example.invalid`/`.test`/`.local` None, `a..co.uk` None, uppercase/mixed IDN == A-label form, `a.co.uk.` -> a.co.uk, userinfo/port/backslash ignored, empty/`http://`/garbage -> existing paths (structured `{}`), invalid never gains the keys.
- Network: sockets/getaddrinfo patched BEFORE importing normalizers.url, then a call -> answers, no attempt; only `publicsuffixlist` loaded (no `.update`, no requests/ssl/urllib3/httpx).
- FINGERPRINTED_PACKAGES contains "publicsuffixlist" (test_env_fingerprint covers it). Only additive keys (acceptance snapshot x14 green).
- 2.4 grep over added lines: no co.uk/github.io/notatld/TLD literals, no suffix list literal, no `.dat`, no fixture string in packages/ (only hits are the PSL VERSION date and "RFC 3986" in the docstring). Suffix data comes from the library.
- ruff check ., ruff format --check ., mypy packages: clean (after my test file lint fix).
- Licence: `check_licenses.py` exits non-zero ONLY on BLOCKING psycopg + psycopg-binary (LGPL-3.0-only). Pre-existing: `psycopg[binary]` is in pyproject.toml, packages/normio and packages/normapi at 47df753 and the diff does not touch those or scripts/license_policy.toml. publicsuffixlist (MPL-2.0) is a non-blocking "needs human review" warning, same class as already-warned certifi / hypothesis / pathspec (MPL).

#### Findings (non-blocking, lead's call)
1. Ceiling: no `ponytail:` comment in url.py. The report's D9 section has no Ceiling text; the stale-snapshot ceiling (a PSL update moves env_id and can change registrable domains) is in the docstring and the inventory row, not a `ponytail:` marker. Plan 5 allows "item note".
2. `http://a b.com/` (host with a space) -> registrable_domain `a b.com`. Host validity is pre-existing, not D9, but the PSL result is not abstaining on a non-hostname.
3. Unicode IDN with trailing dot (`https://例え.jp.`) -> None, reason "host is not valid IDNA" (inherited idn_ok), while `a.co.uk.` answers. Conservative (never a wrong answer) but inconsistent and the reason is misleading. `1.2.3.4.` gets "suffix not in PSL" rather than "IP address".
4. Pre-existing, not D9: `https://a.co.uk:abc/` raises ValueError in `parts.port` (url.py line 203 at 47df753 too).

#### Implemented, unverified
- Real-data live corpus: none required (Live: none). PSL freshness vs the latest list not checked (no network by design). MPL-2.0 sign-off is a human decision. Full ci-fast pytest not run (batches only).

### D10.verdict.md

### D10 verdict (attack): ACCEPT (with logged residuals)

Diff attacked: `git diff main -- packages/normalizers/src/normalizers/phone.py tests/unit/test_phone_normalizer.py` (worker diff is now committed as f3988fa; pre-change = main).

#### Evidence
- Batches (ulimit 16 GB): d10_acceptance + test_phone_normalizer 149 passed; property idempotency + golden identity corpus 49 passed, 1 failed = known COMPANY_NAME only;
  clone_context_and_drift + overview_quality + adjudication_acceptance 100 passed, 1 xfailed; normcore_profile/profile_suggestion/type_detection/typed_destinations 141 passed; defects/test_scorer 29 passed.
  tests/integration/test_clone_pipeline.py: 12 errors = Postgres at 127.0.0.1:5535 refused (environment, unverified).
- Negative case: main's phone.py loaded in place of the module: 95 of the d10 + phone-normalizer tests FAIL (comparison bare E.164, batch, fixed point, new TestExtensions tests); new code passes all.
- Differential fuzz new vs main, 4548 inputs x 4 contexts (none, US, default GB, GB+US; random punctuation/ext/tel: strings, 00/011, fullwidth plus, phone-context, isub, over-long/non-digit ext, `x45 x46`):
  0 diffs for any input without an extension (status, validation, display, comparison, search, structured minus rfc3966, confidence all identical);
  with a region, only `comparison` differs (status/validation never changes);
  regionless changes (813) are all AMBIGUOUS -> PARSED/INVALID and every one contains an explicit "+" (`tel:+`, `(+44)`, fullwidth plus, `TEL:+`); no input without a plus or fullwidth plus is accepted. `00 44..`, `011 44..`, national `tel:`, `tel:...;phone-context=` w/o plus, bare `x45`/`ext. 45`/`;ext=45`/`#45` stay AMBIGUOUS with no comparison.
- Fixed point: 12740 generated cases (every libphonenumber region, intl+national, 13 suffix spellings, 2 contexts) -> re-normalizing `comparison` under (none, US, JP) returns identical comparison+search; `search` == e164 always (extension-free). Baseline test (1014 inputs) byte-identical.
- Bad extensions (23 digits, `ext=abc`, `ext=`, duplicate `ext=`) are never VALID.
- Section 2.4 grep over added lines: no tables, no extension-prefix/phone literals (hits are the docstring and the `"rfc3966"` key). `ponytail:` ceiling comment present (the regionless ext-free tel: guard, with upgrade path). ruff + mypy packages clean. Added tests/unit/test_phone_d10_attack.py (21 pass, 3 strict xfail), ruff clean.

#### Residuals (all pre-existing on main, libphonenumber behaviour; not regressions, lead to log)
1. `tel:+14155552671;isub=123;ext=5` and `tel:555-1234;phone-context=+1-415;ext=9` (ext BEFORE-not-first order): confident VALID, extension silently dropped, comparison bare E.164 -> two such numbers with different ext still compare equal (the D10 defect shape survives on this input form). Canonical `;ext=5;isub=..` order works.
2. `+43 1 234567890x45 x46` (two markers): VALID, the first extension is merged into the number (`+43123456789045`, ext 46). Confident-wrong merge for variable-length numbers; main identical. Not caught by the "x45 x46 not merged" acceptance, which only tested a fixed-length base.
3. Non-ASCII-digit extensions (Arabic-Indic, fullwidth) are kept verbatim: `x12` vs `x<arabic 12>` give different comparisons, and the URI carries non-ASCII digits (RFC 3966 wants ASCII). Safe direction (false-unequal), fixed-point holds. Root fix would be normalize_digits_only on the extension.
4. Lead-accepted: regionless ext-free `tel:+<cc>...` stays AMBIGUOUS (over-abstain; ponytail-marked).

Implemented, unverified (needs live data/DB): Postgres/clone persistence of the new `structured["rfc3966"]` key (integration tests need the DB); real-corpus phone columns.

### D11.verdict.md

### D11 verdict (attack, 2026-10-05): ACCEPT, with one medium finding (F1) for the lead

#### Evidence
- Capped batch `test_name_d11_acceptance + test_name_normalizer + test_env_fingerprint`: 338 passed, 1 skipped (the licence test, see below);
  `tests/property/test_idempotency_determinism.py`: 17 passed. After my test fix: acceptance 292 passed (with D11_COMMONS_CODEC_JAR set), 291+1 skip without.
- Negative on old code (git archive 805190b packages -> scratch, PYTHONPATH first): 181 failed / 109 passed / 1 skipped
  (legacy keys leak on non-Latin, no status/script, no double_metaphone/beider_morse, count 124 = 124). The 109 passes are the guards.
- Counts reproduced: 170 same-name pairs share a key NOW 143 vs old any-key 124 vs Soundex 119 (BM alone 132); cross-script 58 vs 56;
  22 different-name pairs never share. Pairs for the plan headline: Мухаммед/Muhammad|Mohammed|Mohammad|محمد all False (disclosed by worker; Елена/Yelena True).
  The headline is NOT met; only the count bar is. Not forced = correct under never-guess.

#### (1) Licence test fixed (tests/unit/test_name_d11_acceptance.py, only file I edited)
- Old test skipped (looked only at untracked files). Now: checks cached+untracked rule data; LICENSE/NOTICE above it; permissive text, no GPL/LGPL;
  every gen_*.txt has its own Apache-2.0 header; NOTICE carries a 64-hex source sha256. Plus new `test_vendored_rule_files_match_the_upstream_jar`
  (skips unless D11_COMMONS_CODEC_JAR is set).
- I fetched commons-codec-1.17.1.jar and -sources.jar from Maven Central: jar sha256 == the one in NOTICE. All 63 gen_* files are byte-identical to the jar
  (cmp), LICENSE identical to META-INF/LICENSE.txt, NOTICE head identical to META-INF/NOTICE.txt. gen_name_prefixes.txt is the only non-jar file: its 14 entries
  equal NAME_PREFIXES[GENERIC] in PhoneticEngine.java of the sources jar (verified, same order). Not a hand-written growing table.
- Wheel built (`uv build`): contains all 64 data files + LICENSE + NOTICE.

#### (2) Plumbing
- Dispatcher (`normcore.Dispatcher.normalize`) x PERSON/GIVEN/FAMILY_NAME x 9 inputs: `phonetic_status`/`script`/`phonetic` present on the returned NormalizedValue.structured,
  model_dump(mode="json") serialises; no key containing "lang" is ever emitted. PERSON_NAME: 2-token = AMBIGUOUS and carries no phonetic (as before); single token carries none (as before).
- env_id: scratch copy of packages, editing gen_rules_cyrillic.txt changes `collect_source_hashes()["normalizers"]`, restoring returns it. Hash cost 0.03 s.
- Output deterministic across PYTHONHASHSEED 0/1/2 (identical digest over 4000 names x 3 semantic types) and idempotent (normalize(display) == value, 0 failures).

#### (3) Robustness (deadline-guarded; no exceptions anywhere)
Empty-after-cleaning, marks only, ZWJ/ZWNJ (Latin, Persian, Arabic), NFD Cyrillic, digits+Cyrillic, NUL, noncharacter, emoji, fullwidth, Turkish İSTANBUL/ISPARTA, d', hyphen-only,
apostrophe-only, "de ", van der, de la: all fine. Latin/Cyrillic homoglyph mixes (`Smіth`, `Мухаммеd`) -> not_applicable, script `Cyrillic+Latin`, no key (never-guess holds; matching is lost, by design).
Beider-Morse is NOT exponential (20-phoneme cap, 114 alternatives for 100 Latin tokens, 400 for 30 Cyrillic tokens), BUT:
**F1 (medium, unfixed)**: cost is super-linear in field length and the structured output is huge, with no length guard anywhere (grep: no max_len in normcore/normio/normapi).
  one-token Arabic 4k chars 0.9 s, 20k chars 18 s, 80k chars >20 s; one-token Latin 7k chars 3.8 s and 2.4 MB of `beider_morse` strings, 35k chars >20 s;
  1000 Cyrillic tokens 4 s / 3 MB. Realistic names: 0.42 ms/name (5000 synthetic), 10 ms at 85 chars, 35 ms at 170 chars. Old code: microseconds. A pasted paragraph in a name column
  costs seconds per distinct value and MBs in the result. Recommend a root-cause guard in `_language_aware_codes` (e.g. compute BM per whitespace token, or abstain above a documented length with
  `phonetic_status` set), chosen by the lead; I did not fit one.

#### Independent differential vs the Java reference (beyond the worker's 131 names)
Built a Java harness on the real 1.17.1 jar (BeiderMorseEncoder GENERIC/APPROX/concat/20): 7250 inputs (1264 surnames from many origins, Cyrillic incl. Ukrainian/Serbian letters, Arabic/Persian
with spaces, Greek, Hebrew, d'/de la/van der/von/da/di prefixes, hyphens, İ, 7000 random Latin/Cyrillic/Arabic/multi-token strings): 0 Java errors, 0 raw-string diffs.
(Java iterates NAME_PREFIXES in HashSet order; "de la Cruz" matched anyway; a different JDK could in principle differ - unverified.)

#### (4) Different-name collisions beyond the 22 planted (counts, no thresholds)
1264 distinct surnames (US/Polish/German/Italian/French/Russian/Arabic/Indian/Japanese/Greek/Swedish/Irish/Vietnamese/Chinese romanisations; hand-listed in scratch, 798,216 pairs):
Soundex 1060, old any-legacy 1320, double_metaphone 1037, beider_morse 411, NEW any-key 1785 (+465 pairs over old any-key). 226 of 411 BM collisions are not Soundex collisions.
Samples of distinct names sharing a BM code: Hunt/Cheung, Jean/Zhang, Khan/Chan, Harris/Hara, Rossi/Roche, Johnson/Hansson, Mason/Mattsson, Bui/Wei, Lee/Le. Consumers must not treat any-key sharing as identity.

#### (5) Section 2.4 and licence gate
- No container literal of >=6 strings, no 4-string rule tuples, no fixture literal in name.py/_bmpm.py; only non-ASCII is one Cyrillic example in a ponytail comment. `ponytail:` CJK ceiling is in `_phonetic_fields`.
- `scripts/check_licenses.py`: only the pre-existing psycopg/psycopg-binary LGPL violations; `phonetics` 1.0.5 is MIT (sdist only, 9 KB, last release 2018). abydos absent from pyproject/uv.lock.

#### Could NOT verify / implemented, unverified
- Live API/run: env_id moving in a real server and Parquet/Arrow storage of list-valued `phonetic` (I checked JSON dump + dispatcher only; normalize_batch emits no structured column).
- Legal provenance of BMPM rules beyond the ASF headers (upstream descends from Beider/Morse's GPL-era BMPM); NOTICE aggregation/dependency-inventory not mine to edit.
- Mutation test of the new licence test (cannot edit packages/*/src, so I did not delete a LICENSE to see it fail).
- `phonetics` Double Metaphone correctness vs a reference (not compared; Cyrillic/Arabic DM runs on the lossy anyascii form).
- BM internal language guess narrows rules (e.g. Polish letters -> Polish rules); never reported, but it is a guess that shapes the keys: a design note for the lead, not a defect against the contract.
- Full suite not run (batches only).
