# Round 2 handoff — the only memory that survives a session

Update this file at every commit. A working session reads [STATUS](STATUS) and this file first, then
[the plan](../ROUND2_IMPLEMENTATION_PLAN.md). Git is the memory; a session's context is not.

`STATUS` alone holds `autonomy`, `next` and `lock` (plan §7.1). Only the owner changes `autonomy`.
A session sets `lock=<ISO time>`, pushes it, and refreshes it with every commit; a lock older than 75
minutes is stale.

**Branch:** `feat/round2-fixes` · **Current phase:** 5 (Phases 1-4 done)

| item | phase | state | commit | lead verdict |
|---|---|---|---|---|
| D15 | 1 | unverified-live | see git log | Lead: verifier REJECTed (`.handoff/D15.verdict.md`: compose env not passed, 3 wiring points untested, `://` in a password, `[::1]` Host). Lead fixed all four plus `--no-proxy-headers`, with `tests/unit/test_address_policy_wiring.py`. Known and recorded: `Host: localhost:80@evil.com` accepted (LOCAL_VERIFY). Accepted by the lead on the diff; live checks in LOCAL_VERIFY. |
| D14 | 2 | unverified-live | see git log | Lead: verifier REJECTed (`.handoff/D14.verdict.md`): a stored legacy job could still write to its origin, a second connection to one server was not caught, stale text. Lead added `_require_separate_copy` (start, Phase 1, Phase 2) with `tests/unit/test_same_origin_guard.py`, fixed the text. Two host names for one server are not guessed equal (limit). |
| D13 | 3 | unverified-live | see git log | Lead: verifier REJECTed e93bc50 (`.handoff/D13.verdict.md`): `column_language_form` missing from the `context_hash` unset set (every hash moved), and free text like `Mon-Khmer` split as a BCP 47 variant. Lead fixed both (variants must be known to CLDR or digit-led; tests `test_language_free_text_hyphen.py`, fail before / pass after), built the AMBIGUOUS result from `_unresolved` (the pinned confidence-literal count stays), and added the missing assertions to `test_same_origin_guard.py`. Not re-attacked; end-to-end clone with row country and column form, resume and `env_id` movement are live checks. |
| U1 | 4 | unverified-live | see git log | Verifier REJECT (`.handoff/U1.verdict.md`): lead fixed the C5 guard, double POST on leave, list route leaking quality; the rest escalated (R23 gaps, /docs). Derive done (`.handoff/U1.acceptance.md`). Lead: review route `GET /adjudication/review[/{key}]` built, API-half test moved to `tests/unit/test_u1_review_route.py` (18 pass). Serving, screens, Playwright pending. |

States: `todo` · `in-progress` · `accepted-cloud` (lead accepted, cloud-verifiable parts proven) ·
`unverified-live` (accepted, needs the real environment: see LOCAL_VERIFY.md) · `blocked`.

## Locked file-ownership table (Phase 0)

Locked 2026-10-27 from source reading and the Phase 0 greps (graft is not installed in the cloud;
graphify graph built). Shared files are serial lead chains (plan §2.6).

| files | owner | phases |
|---|---|---|
| `normapi/{app,main,schemas,routes,clone_executor}.py` | lead only | 1-4 |
| `normio/connectors/{postgres,clickhouse}_destination.py` | lead | 2 |
| new address-policy module in `normapi` + `tests/unit/test_address_policy.py` | worker B | 1 |
| `compose.yaml`, `.env.example`, `packages/normapi/Dockerfile` | worker C | 1 |
| `normalizers/language.py` + its unit test; `tests/property/` | workers | 3 |
| `ui/**` | workers | 4 |

## Lane plan

See plan §8 phase tables; they stand unchanged.

## In flight

- 2026-11-01 §5.6 DONE (measured, no code change): restart of the native API on
  `norm_app_r2_zi1m` under `MemoryMax=3G` was **OOM-killed at 3.0 GB, t+27 s, before health**;
  linear ramp ~144 MB/s from t+2 s; never answered a request. Cause confirmed by measurement +
  code: `adjudication.py::migrate_sources` (called by `create_app`) runs
  `list_queue(limit=2**31)` — loads all 1,914,572 queue rows (2,302 MB of column data) into one
  Python list — and **0 of 1,914,572 rows need migration** (every stored source is already
  identity-form). graft `callers create_app --depth 2`: this is the only whole-table read in the
  start-up path. Fix options researched (paged batch loop — the pattern routes.py:1213 already
  uses — recommended; server-side cursor; SQL pre-filter; mark-done marker). Detail in FINAL_REPORT.
  Then §5.7 (UI walk + Playwright), §5.8, §5.9.
- 2026-11-01 §5.5 DONE (measured): native API on 8090 under MemoryMax=3G; Diffbot full clone
  COMPLETED (13/13 tables, 52,828/52,828 rows, phase2 40.2 s, 472 flagged error rows, all
  location.postalcode vs US; origin untouched, no `__normalizing`); ZoomInfo 100k COMPLETED
  (7/7 tables match with FINAL, 699,853 rows, phase2 67.1 s, 1,077 error rows); ZoomInfo 1M
  COMPLETED (7/7 tables match with FINAL, 5,999,042 rows, cgroup peak 1.61 GB < 3 GB cap, no
  OOM; the driver client was killed by a tool timeout but the job ran server-side to completion
  — resumed by re-fetching from the API). Review queue: diffbot 1,852 rows/2.8 MB; zi1m
  1,914,572 rows/2.7 GB — matches the 2026-10-28 baseline (1,852 / 1,914,502). CH query_log
  shows the clone connected from ::ffff:10.10.9.137. compose.yaml `network_mode: host` graft
  reverted (uncommitted change removed; clones use the native API per G3/G4). Now §5.6:
  restart on norm_app_r2_zi1m under the cap, measure start-up memory. Then §5.7, §5.8, §5.9.
- 2026-10-31 (laptop, single agent, LOCAL_RUN.md): reverting the previous session's uncommitted
  `network_mode: host` graft in compose.yaml (wrong path: G3/G4 send real-data clones to the native
  API; host networking breaks the `@postgres` service DNS and D15's binding). Then §5.5: native API
  on 8090 under `MemoryMax=3G`, jobs `norm_r2_out_diffbot` (full, `source_schema: diffbot`),
  `norm_r2_src_zi100k`→`norm_r2_out_zi100k`, `norm_r2_src_zi1m`→`norm_r2_out_zi1m`, each with its
  own `norm_app_r2_<run>` on diffbot-pg; measure per the 2026-10-28 report. Then §5.6 memory
  diagnosis, §5.7 UI walk (movies job; Playwright too), §5.8 worktree re-check, §5.9 close.
  Raw outputs: `reports/2026-10-29_round2_local/` (git-ignored).
- (lane B and C finished 2026-10-28, reports in .handoff/U1.lane{B,C}.report.md; lead wired, added GET /clone-jobs)
- (done) lane B (round2-worker, sonnet): `ui/src/{App,main}.tsx`, `app/`, shell/Nav, Connections, New clone, deleting the dropped pages/specs; progress `.handoff/U1.laneB.progress.md`.
- 2026-10-28 U1 lane C (round2-worker, sonnet): `ui/src/pages/{Jobs*,Review*,Quality*}`, `ui/src/lib/review*`, `ui/e2e/{jobs,review,quality}.spec.ts`; progress `.handoff/U1.laneC.progress.md`. The lead wires C's pages into the router.

## Next action

Since 2026-10-29 the rest of round 2 runs on the owner's laptop, one agent, no routine: follow
[LOCAL_RUN.md](LOCAL_RUN.md) (live checks first, then Phase 5). Phase 5 (close): `/ponytail-audit`, `/ponytail-debt`, `/ponytail-gain`, delete unused exports in `ui/src/api/{client,types}.ts`, fold `.handoff/` into `round2/FINAL_REPORT.md`, purge it, add the status line to the report, `[ROUND2 COMPLETE]`. Never merge.

## Notifications

[PHASE 4 DONE] 2026-10-28. U1 `unverified-live`. Verifier REJECTed once (`.handoff/U1.verdict.md`); the lead fixed the C5 guard, the double POST
on leave, the list route leaking `quality`, and `NORM_UI_DIR` in `.env.example`; /docs-local and three R23 gaps are escalated (Open escalations).
Gate in this session: ruff check, ruff format --check, mypy, check_c5_exceptions, check_test_assertions, check_no_stubs, check_docs_note,
check_root_files, check_gitignore_consistency, check_mermaid, deptry, gitleaks main..HEAD: pass; ui `npm ci`, build, lint: pass; Playwright 48 passed
(verifier); actionlint: installed, not run on the changed workflow output beyond the install check. pytest (unit or golden and not slow, capped): 3481
passed, 24 skipped, 1 xfailed, 3 failed before fixes: the known `test_groups_cost_is_linear_in_pairs` plus two U1 ones (an "in-place" comment in
NewClonePage, `NORM_UI_DIR` undocumented) fixed and re-run alone: pass. NOT run: Vale, lychee, zizmor, Docker jobs, GitHub run check.
/ponytail-review: the new UI is 2,468 lines against 4,114 before; open finding: unused exports in `ui/src/api/client.ts` and `types.ts` (deletable).

[BLOCKED] 2026-10-27 D13: step 4 failed. graphify-out/graph.json is missing and `uv sync --all-extras` fails in this session: first pyicu (no libicu-dev/pkg-config), then after `scripts/cloud_setup.sh` pyarrow 17.0.0 (uv picked Python 3.13; build needs pkg_resources). Question: should the routine environment pin Python 3.12 (e.g. `uv sync --python 3.12 --all-extras`) and install libicu-dev in its setup script, or should I continue without graphs? Set next=work after fixing.

[DRYRUN DONE] 2026-10-27T15:03Z, see .handoff/supervisor_dryrun.txt

[PHASE 1 DONE] 2026-10-27. D15 `unverified-live` (see LOCAL_VERIFY.md). Gate, run in this session:
ruff check, ruff format --check, mypy: pass. pytest (unit or golden and not slow, capped): 3385 passed, 24 skipped, 1 xfailed.
Guards: check_c5_exceptions, check_test_assertions, check_root_files, check_gitignore_consistency, check_no_stubs,
check_docs_note, deptry, actionlint, markdownlint-cli2, check_mermaid: pass. gitleaks on `main..HEAD`: no leaks.
NOT run: Vale, lychee (docs.yml `style` and `links` jobs), zizmor (needs the GitHub API: "couldn't list tags"), and
the ci-full / gate.yml integration, e2e and mutation jobs (no Docker). GitHub: every run on the branch ends in 2 s
with one job and no steps (e.g. ci-fast run 40536779521): treated as the known billing refusal, recorded, not a block.
/ponytail-review of the phase diff: lean, no findings. Graphs refreshed.
Pre-existing, not this branch: `gitleaks git .` over full history reports 3 hits on the old committed
NORM_SECRET_KEY (commits already on main: da81a25, ab0846a, 364cbd3). See Open escalations.

[PHASE 2 DONE] 2026-10-27. D14 `unverified-live`. Gate in this session: ruff, format, mypy, guards (c5, test-assertions,
no-stubs, root-files), deptry, actionlint, markdownlint, mermaid pass. pytest (unit or golden, capped): 3406 passed,
24 skipped, 1 xfailed, plus 2 failures: `test_verdict_identity` (a removed `write_target` kwarg, fixed in this phase) and
`test_calibration_attack.py::test_groups_cost_is_linear_in_pairs` (a 0.5 s wall-clock assertion; passes alone, fails in
the full run, unrelated to D13-D15, not skipped, see Open escalations). Vale, lychee, zizmor, Docker jobs not run; GitHub
runs end in 2 s without steps (billing refusal pattern). /ponytail-review: the removal only deletes code.

[PHASE 3 DONE] 2026-10-28. D13 `unverified-live`. Gate in this session: ruff check, ruff format --check, mypy, check_c5_exceptions,
check_test_assertions, check_no_stubs, check_docs_note, check_root_files, check_gitignore_consistency, check_mermaid, deptry, actionlint,
markdownlint-cli2 (changed files), gitleaks on `main..HEAD`: pass. pytest (unit or golden and not slow, capped): 3450 passed, 24 skipped,
1 xfailed, 1 failure `test_calibration_attack.py::test_groups_cost_is_linear_in_pairs` (the known wall-clock test, passes alone: 42 passed;
see Open escalations). NOT run: Vale, lychee, zizmor, Docker jobs. GitHub runs not checked this tick (billing-refusal pattern in Phases 1-2).
/ponytail-review of the phase diff: lean; the one addition (`_known_variants`) carries a `ponytail:` comment naming its limit.
Graphs built this session (cloud_setup on Python 3.12 worked).

(append `[PHASE n DONE]`, `[BLOCKED]` and `[ROUND2 COMPLETE]` entries; the same prefixes go in commit
messages)

## Owner answers

(the owner answers a `[BLOCKED]` here, then sets `next=work` in STATUS)

- 2026-10-28, to the D13 [BLOCKED] (graph build fails): owner: "Yes, fix it". Fixed in the setup, do not
  continue without graphs: `scripts/cloud_setup.sh` now exports `UV_PYTHON=3.12`, and SUPERVISOR step 4
  runs `cloud_setup.sh` whenever a tool or `graphify-out/graph.json` is missing. If `.venv` was already
  built on 3.13 in your session, `rm -rf .venv` first. Also: the D13 attack under "In flight" never wrote
  its verdict; run it again.

## Open escalations

- U1 R23, more: `GET /clone-jobs/{id}/errors` rows for column findings carry sample values in the unmasked `error` text
  (`clone_executor.py`, "e.g. ..."), and the Jobs screen shows that text. Pre-existing API behaviour; not changed. The list
  route `GET /clone-jobs` now omits `quality`. Owner decides how the findings text is masked.

- U1 R23 conflict, not changed: `GET /clone-jobs/{id}` and `/quality` carry raw `disguised_missing[].value`.
  D4's confirm step (`confirmed_missing`) needs those exact values, so masking them would break it. Owner decides
  (a separate review-style route for them, or accept the exception).

- U1 lead decisions on the verifier's open questions (2026-10-28, no owner answer; the owner may overrule):
  (1) the accept key takes the reading the person picks with number keys 1-9; nothing is pre-selected.
  (2) Verdicts are append-only, so "keep ambiguous" skips the value (nothing stored, it stays pending) and
  "undo" reverts the last decision only while it is unsent (a short hold before the POST). (3) R23 covers
  the review route only; `/preview`, `/field-test` and `/runs/{id}/values` still echo raw values: not changed,
  owner decides. (4) Only the five screens ship; Runs and Comparison pages go with the rest.
  (5) `/docs` and `/redoc` need Swagger assets; no allowed dependency supplies them (Q7 names only
  Mantine), so they are switched off and `/openapi.json` stays. The acceptance test is parked in `.handoff/U1.test_docs_local.md` (unmet, escalated): owner decides whether to add `swagger-ui-dist`.

(results that passed only written tests or one case, and findings outside round 2's scope)

- The `NORM_SECRET_KEY` that compose.yaml used to commit is in main's history and `gitleaks git .` flags it (guards.yml B6
  step is likely red on main too). Rotate it on any deployment that used it; whether to add a `.gitleaksignore` entry (a C5
  exception) is the owner's call. Not touched.
- D15: `Host: localhost:80@evil.com` is accepted by Starlette's TrustedHostMiddleware (it reads the part before the first `:`).
  Not exploitable without an allowed peer; listed in LOCAL_VERIFY.
- `tests/unit/test_calibration_attack.py::test_groups_cost_is_linear_in_pairs` asserts `< 0.5 s` wall time and fails under the
  full unit run (twice) while passing alone: a load-dependent test, pre-existing, not touched (L1). Owner decides how to fix it.
- Vale and lychee not run in the cloud (see [PHASE 1 DONE]).
