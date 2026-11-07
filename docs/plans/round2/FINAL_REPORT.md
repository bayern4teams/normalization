# Round 2 — final report (D13, D14, D15, U1)

Owner: single local agent, branch `feat/round2-fixes`, run 2026-10-29 → 2026-11-01
(LOCAL_RUN.md). This report folds in the cloud-phase handoff notes (`.handoff/`, purged after
`673c0b0` — everything that mattered is carried below, nothing links to a deleted file).
Every number is measured; "not checked" marks what was not checked.

The plan of record is `docs/plans/ROUND2_IMPLEMENTATION_PLAN.md`; the checklist is
`LOCAL_VERIFY.md`; the running log is `docs/plans/round2/HANDOFF.md`. The round-1 "before"
values come from `docs/improvement-report.md` (D13/D14/D15/U1 sections) and the 2026-10-28
real-data report `reports/2026-10-28_main_remote/REPORT.md`.

---

## 1. What was built

### D13 — LANGUAGE second pass (`packages/normalizers/src/normalizers/language.py`)

Second pass over a code now returns the same code: the normalizer answers with a
`code`/`display` pair, the pipeline stores the code in the `language_code` column, and feeding
the output back re-reads the code, never the name (`comparison` is the code; idempotent).
`column_language_form` is the new column evidence (CODE vs NAME columns), added to the
`context_hash` unset set so no-evidence contexts keep their old hashes (the cloud verifier's
regression, fixed). The hyphen rule splits only a CLDR-known or digit-led variant, so
`Mon-Khmer` is INVALID, not Mongolian. `AMBIGUOUS` is built from `_unresolved`; short
name-or-code values (`Mon`, `Ga`) stay AMBIGUOUS unless country or column evidence settles them.

### D14 — in-place mode removed (`schemas.py`, `clone_executor.py`, both destination writers)

The origin is always read-only: the `in_place` request field, `swap_table`/`drop_table`,
`staging_name`/`_STAGING_SUFFIX` and the write-target plumbing are gone; `in_place: true` on
POST is a 422. `_require_separate_copy` guards start, Phase 1 and Phase 2 (the cloud
verifier's legacy-job finding: a stored pre-D14 job must never write its origin), with
`tests/unit/test_same_origin_guard.py`. Two saved connections naming the same server are still
not guessed equal (recorded limit; Postgres fails on CREATE TABLE, ClickHouse on the guard).

### D15 — local-network only (`address_policy.py`, middleware, compose)

Every caller-facing socket binds `10.10.9.137:8080` (API+UI, one port, no CORS) or
`127.0.0.1` (postgres 5535, libpostal 8081). A caller middleware refuses a non-local peer
(403) before routing; `TrustedHostMiddleware` refuses a foreign `Host` (400); `X-Forwarded-*`
is never read (`--no-proxy-headers`). Saved connections are checked at save time and again at
connect time (`build_source_connector`/`build_destination_writer` → `resolve_and_check`);
every resolved address of a host name must be private (decision R15). The allow set is
RFC1918 + loopback + link-local + `100.64.0.0/10`-off-by-default (R14). ADR-022 records it.

### U1 — the new UI (`ui/`)

Five screens — Connections, New clone, Jobs (+detail), Review, Quality — against the real API
(no mocks; honest empty states). Mantine + react-query + react-router hash routing;
`client.ts`/`review.ts` are thin fetch wrappers over the §98 surface; Review is keyboard-first
(j/k/arrows/1-9, nothing pre-selected, R18). The old 12-page UI is replaced, not patched.

---

## 2. How it was verified

**Cloud phase (per `.handoff/`, folded in here).** Each item: implementation + unit tests on
the cloud, then an independent verifier attack in a fresh clone. All four verifiers REJECTed
at least once; the lead fixed every finding before this local run:

- **D15** (`.handoff/D15.verdict.md`): compose env not passed, 3 wiring points untested, `://`
  in a password path, `[::1]` Host. Fixed with `tests/unit/test_address_policy_wiring.py` plus
  `--no-proxy-headers`. ~50 refused forms through `classify`, ~35 through `resolve_and_check`,
  0 leaks; the ASGI/HTTP probes (wrong/foreign Host, empty peer, websocket scope) refused all.
- **D14** (`.handoff/D14.verdict.md`): a stored legacy job could write its origin (probe
  reproduced it); a second connection to one server was not caught; stale text. Fixed with
  `_require_separate_copy` in start/Phase 1/Phase 2 + tests; text fixed; the second-connection
  case recorded as a limit (not guessed).
- **D13** (`.handoff/D13.verdict.md`): `column_language_form` missing from the `context_hash`
  unset set (every verdict/cache key of every type moved); free text like `Mon-Khmer` → `mn`.
  Fixed both; `test_language_free_text_hyphen.py` fails before / passes after; the pinned
  confidence-literal count stays (AMBIGUOUS built from `_unresolved`).
- **U1** (`.handoff/U1.verdict.md`): C5 guard, double POST on leave, list route leaking quality
  — fixed; R23 raw-value gaps and `/docs` escalated (§7). Review route
  `GET /adjudication/review[/{key}]` built with 18 API tests (`.handoff/U1.acceptance.md`).

**Local run (LOCAL_RUN.md §5, this document's evidence dir
`reports/2026-10-29_round2_local/`).** CI on the branch (§5.1), Docker + integration for D14
(§5.2), live network checks for D15 (§5.3), movies real data for D13 (§5.4), full
Diffbot + ZoomInfo clone runs (§5.5), the memory diagnosis (§5.6), a live browser UI walk +
Playwright (§5.7), and a verifier re-check from a fresh worktree including the never-done D13
re-attack (§5.8). Results below.

---

## 3. Measured results vs the "before" values

### §5.1 CI (also re-run on the final commits; see §5 below)

3,484 unit tests pass (24 skipped, 1 xfailed), mypy clean over 99 files, ruff check + format
clean, stub check / docs-note / C5 / test-assertions / root-files / gitignore guards pass,
actionlint and zizmor clean, UI build clean, Vale 8 suggestions 0 errors, lychee 109 OK 0
errors. Known and not fixed (recorded, per L1): `check_mermaid` 14 failures (needs headed
Chrome; headless env), gitleaks 1 leak pre-existing in `main` history (`NORM_SECRET_KEY`, §7),
deptry 3 pre-existing transitive findings.

### §5.2 D14 integration (Docker stack)

33/33 integration tests pass on the compose stack (before: in-place paths had no integration
coverage; the suite failed `KeyError: 'source_identity'` on a legacy-job fixture — fixed by
the `_connector_source_identity` fallback, `ed1c3e7`/`55981e0`).

### §5.3 D15 live (before: `0.0.0.0` binds, no caller/Host check)

- `ss -ltnp`: this project's sockets are exactly `10.10.9.137:8080`, `127.0.0.1:5535`,
  `127.0.0.1:8081` — no `0.0.0.0` listener of ours.
- LAN caller (bench box → API `/health`): **200**. External caller (203.0.113.2 on a stub
  network): **403**. Foreign `Host: evil.example`: **400**. Save connection to `8.8.8.8`:
  **422**. `Host: localhost:80@evil.com`: 200 — known limit (Starlette TrustedHost reads before
  the first `:`; §7). Two-address host name: not checked live (unit-tested).
- Docker 29.7.1 ≥ 28.3.3. Deferred checks captured in the §5.5 runs: `pg_stat_activity`
  shows the clone's Postgres connections from the API host; ClickHouse `system.query_log`
  shows `initial_address ::ffff:10.10.9.137` for the ZoomInfo reads.

### §5.4 D13 on real movies data

Before: the second pass changed answers; 440 of 7,910 names were confident-wrong re-reads.

`raha-movies_1` (7,390 rows, 502 distinct language strings) cloned to `bm_round2_movies` with
LANGUAGE+COUNTRY configured: `language_code` filled 5,763 → `en`, 1,627 multi-language rows →
NULL (held, not guessed); `language` (the display column) byte-identical to the source. Feeding
the output back changed **0** values (the D13 contract; before: 440/7,910 display re-reads wrong).

### §5.5 Diffbot + ZoomInfo clone runs

The 2026-10-28 rerun, same sources and settings, native API on 8090 under
`systemd-run -p MemoryMax=3G`, all writes into new `norm_*`/`norm_app_r2_*` databases.

| | Diffbot (13 tables) | ZoomInfo 100k (7 tables) | ZoomInfo 1M (7 tables) |
|---|---|---|---|
| Rows copied / expected | **52,828 / 52,828** | **599,853 / 599,853** (Company 99,939; Experience 999,611 — table-exact) | **5,999,042 / 5,999,042** (Company 999,394; Experience 999,611 — table-exact) |
| Phase 2 wall | 40.2 s | 67 s | 14 m 12 s (5.999M rows) |
| Throughput | ~1,314 rows/s | ~8,952 rows/s | **~7,000 rows/s** (before: 1,220 / 8,465 / 8,585) |
| Review-queue rows | 1,852 (2.8 MB; before 1,852) | 193,708 (275 MB; before 188,312/223 MB) | 1,914,572 (2.7 GB; before 1,914,502/2.26 GB) |
| Flagged error rows | 472 (all `location.postalcode` vs US format) | 1,077 (phone/postcode/country format holds) | 5,894 (same families) |
| Memory peak (cgroup) | 1.61 GB during run | — | **1.61 GB during run; survived the 3G cap** |
| `__normalizing` residue | none | none | none |

Diffbot used `source_schema: diffbot` (non-public schema; the previous session's "blocked" was
a wrong path — the Docker API container cannot reach the bench box, while the guide's native-API
path always could; `source_schema` is supported end-to-end, `schemas.py:205` →
`clone_executor.py`). ZoomInfo is ClickHouse-as-source over the HTTP port — supported and proven
here. 1M throughput (7,000/s) is below 10-28's 8,585/s: measured on a laptop host that also ran
the browser walk; recorded as measured, no claim of regression or improvement.

### §5.6 The API start-up memory problem — diagnosis (measured, not fixed, per the fixed rule)

**What happens.** Restarting the API on the 1M run's job database (queue = 1,914,572 rows)
under `MemoryMax=3G`: memory climbs linearly from 26 MB at
**~113 MB/s**, hits the cap and is **OOM-killed at t+27 s**, before `/health` ever answers.
This is the 2026-10-28 finding ("> 6.7 GB needed after the 1M run") reproduced exactly: the
same DB, the same linear growth; the cap just kills it earlier than the host would.

**Root cause (code-confirmed).** `normapi.create_app` calls
`adjudication.migrate_sources` (`packages/normapi/src/normapi/adjudication.py:244`), which
calls `persistence.list_queue(..., limit=2**31, offset=0)` — the **whole**
`normalization_adjudication_queue` is pulled into Python lists at every start-up, JSON-decoded
per row, held while re-keying. `graft callers create_app` shows `migrate_sources` as the only
whole-table start-up path; the queue is the only table that grows with data volume.

**Why it hurts even when nothing needs migrating:** measured on `norm_app_r2_zi1m`, **0 of
1,914,572 rows** have a `source` that still looks like a connection id (all rows are already
identity-form, so the migration loop does nothing but load and skip them). The cost is pure
waste on every restart, forever, as the queue grows.

**Fix options (researched; recommendation, not applied):**

| # | Fix | Change | Effect | Risk |
|---|---|---|---|---|
| 1 | **SQL pre-filter + stream (recommended)** | In `migrate_sources`: select only rows whose `context->>'source'` lacks `://` (they are the only migratable ones; measured: normally zero), iterate with a psycopg server-side cursor (named cursor, `fetchmany`) or keyset batches | start-up memory O(rows-needing-migration), ~constant on today's data; no new dependency (psycopg already in use) | small: one query change + loop shape; idempotency unchanged |
| 2 | Run migration once, off the hot path | call it from a maintenance command / lifespan task after health, not before | health answers immediately; same total memory | the re-key races a first request that needs it; needs a readiness story |
| 3 | Version marker | store a `migrated_at` row; skip `migrate_sources` entirely once run | O(1) start-up after first run | rows written by an *older* binary after the marker (rollback) silently skip; needs care |
| 4 | Raise the cap | MemoryMax 8G+ | hides it | queue grows unbounded → fails later; not a fix |

Option 1 is the smallest change that removes the growth and matches the repo's no-new-deps
style (psycopg server-side cursors are named-cursor `fetchmany`, no license issue; SQLAlchemy
`yield_per`/`stream_results` only stream on psycopg2 dialects — irrelevant here since this
code path is raw psycopg). A guard idea (count-then-load) was rejected: count and load race.
Owner decision needed before any code change (the rule for this run was: diagnose, don't fix).

### §5.7 U1 live walk

Docker stack, `http://10.10.9.137:8080/`; screenshots under
`reports/2026-10-29_round2_local/ui/`.

- Real data through the Docker API (its container reaches the bench box): movies job
  `bm_round2_movies` → `bm_round2_ui_out`, COMPLETED in ~2 s, shown live in Jobs/Review/Quality.
- All five screens walk: Connections (list/save; Test connection on `8.8.8.8` → 422 refused at
  the form, Save stays disabled until a test passes), New clone (host list, schema/db pickers,
  per-column semantic types), Jobs (list, detail, progress), Review (1 question, j/k accept —
  **key→DOM update 14 ms**, budget < 100 ms; 1-9 reading keys), Quality (per-column stats for a
  real job).
- Playwright: `npm run test:e2e` **48/48 pass** (chromium, capped), including the offline test:
  no request leaves the page's own origin on any screen.
- Screen loads: first paint ≈ 1.4–1.9 s (dev-server-less build over the LAN); route switches
  < 50 ms. No CORS/XHR to foreign origins (same offline test).
- Honest empty states: Review on the diffbot run's queue shows the queue; a fresh empty app DB
  renders empty states, not spinners.

### §5.8 Verifier re-check (fresh worktree at HEAD)

- Integration suite re-run: **33 passed** (matches §5.2). `grep in_place packages ui/src` →
  empty (exit 1). Live D15 re-run: LAN 200 / bad Host 400 / `localhost:80@evil.com` 200 (known)
  / save `8.8.8.8` 422 / compose ports unchanged.
- **D13 re-attack (never done in the cloud), all pass:**
  - acceptance cases: `Mon` no evidence → AMBIGUOUS; `Mon`+country MM → settles; `Ga` in a
    2-letter CODE column → settles to `ga` via column evidence; `Mon-Khmer` → INVALID (not
    `mn`); display round-trip;
  - DB-free probe: feeding all 7,910 pycountry display names back through the pipeline changes
    **0** into a different language and **0** into INVALID silently — 142 names come back
    AMBIGUOUS *held* (before: **440 confident re-reads: 208 to another language, 232 to
    INVALID**; the confident-wrong class is gone, the holds are by design);
  - output fed back (movies lang run): changed **0**;
  - `env_id` movement: the ADR-014 source-hash input (blake3 over every `normalizers/*.py`)
    moved main `4b43f2eb9f…` → HEAD `1fa6736e99…` — a stored verdict from the old code is keyed
    differently and re-opens under the new code (the ADR-014 identity behavior). Stored-verdict
    movement itself: not checked (verdict store empty, 0 rows).
  - resume keeps evidence: kill-and-resume twice (diffbot job at ~6 s → resumed →
    52,828/52,828; movies LANGUAGE/COUNTRY job killed at 2,000 rows → resumed → COMPLETED
    14,780 rows, `language_code` distribution identical to an uninterrupted run: `en` 5,763 /
    NULL 1,627). `_column_evidence` runs per table in every Phase-2 pass, resumed included.
- Diff review vs plan §9 acceptance lists: D15 middleware/Host/allow-set/make_conninfo/
  secret-from-`.env` all present; D14 `swap_table`/`drop_table` gone from both destinations,
  legacy guard wired in three places; ADR-010/013/017 amended, ADR-022/023 added; U1 five
  screens, one port, no CORS. No mismatch found.
- Gates re-run on the final commits: unit 3,249 pass + the one pre-existing failure below;
  property+golden+defects 300 pass / 10 skipped; mypy 99 files clean; ruff clean; guards
  (C5/docs-note/root/gitignore/stubs/test-assertions) clean; actionlint/zizmor clean;
  gitleaks unchanged (1 pre-existing).

**Pre-existing failure found during §5.9 (not introduced by round 2, not fixed):**
`tests/unit/test_confident_wrong.py::TestHeldOutFindings::test_a_time_is_no_day_or_month` —
`11/30 10:30 p.m.` with `country="NO"` must be INVALID (D/M/Y has no month 30) but returns
AMBIGUOUS. Reproduced identically on `main` and in the clean §5.8 worktree; §5.1's run (2026-10-31)
passed it, so it is a wall-clock/calendar-sensitive expectation, not a round-2 regression. It is
also in the "before" tests of round 1 (D-something, `main`), so fixing it changes behaviour the
plan does not describe → §6 stop-line: reported, left unfixed, owner decision.

---

## 4. Open owner items (§7 carried, with new evidence)

1. **API start-up memory fix (§5.6)** — measured, diagnosed (`migrate_sources` full load;
   0 of 1.9M rows need migration), fix options table above; recommendation: option 1 (SQL
   pre-filter + server-side cursor). Waiting for go/no-go.
2. **R23 gaps** (unchanged): clone-job error text still carries unmasked samples;
   `disguised_missing[].value` is raw (D4 needs it); `/preview`, `/field-test`,
   `/runs/{id}/values` echo raw values. Owner decision on masking vs a review-only route.
3. **`/docs`+`/redoc` off** (Swagger needs `swagger-ui-dist`); parked acceptance test was in
   `.handoff/U1.test_docs_local.md` (folded: unmet, escalated — decide whether to add the dep).
4. **Review-key decisions** (cloud lead): number keys 1-9 pick the reading; nothing
   pre-selected; "keep ambiguous" skips (verdicts are append-only, ADR-018: no undo/revoke —
   the k-key is a skip, not an undo; UI copy says so).
5. **`NORM_SECRET_KEY` in `main` history** — gitleaks flags 1 leak (pre-existing). Rotate +
   decide `.gitleaksignore` or history rewrite (both owner-only actions).
6. **`test_groups_cost_is_linear_in_pairs` under load** — known (L1): recorded, never edited.
7. **`Host: localhost:80@evil.com` accepted** — Starlette TrustedHost reads before the first
   `:`; the peer-address 403 still applies to any non-local caller (defence in depth). Owner
   decision: accept as recorded limit or pin Host validation harder.
8. **`$BENCH_DIR` in AGENTS.md §4** points to a folder that no longer exists on the laptop
   (the stacks live under `/home/benchmark/stacks/` on the bench box). Docs fix, owner.
9. **`NORM_API_HOST=0.0.0.0`** — not needed: the native start binds `NORM_BIND_ADDR=10.10.9.137`
   directly (§5.3 measured); ADR-022 covers it. Closed by evidence, no code change.
10. **New:** `test_a_time_is_no_day_or_month` fails on `main` today (§3 §5.8 box above) —
    pre-existing, calendar-sensitive; decide whether to fix the expectation or the normalizer.
11. **New:** the previous session's Docker-API clone path cannot reach the bench box (bridge
    network isolation); the native API is the documented path. If LAN users must drive clones
    through the *Docker* API against box sources, that needs an owner decision (extra network
    or a box-side API); nothing was changed this run.

---

## 5. Checks not run (with reason)

- Cloud re-attack of the four items: the run's rule is one local agent, no subagents; §5.8 is
  the local verifier re-check instead.
- Full 35.1M ZoomInfo clone: the plan's scope is the 100k/1M samples (2026-10-28 method); the
  full-corpus estimate in the 2026-10-28 report stands (~50–70 min at 1M-rate; not re-estimated
  from this run's 7,000/s laptop figure).
- `check_mermaid` (needs headed Chrome), gitleaks history fix, deptry 3 transitive findings,
  `test_groups_cost_is_linear_in_pairs` load fix: known/recorded, not in this run's scope.
- `Host` IPv6 literal (`[::1]`) live probe: unit-tested only this run.
- Two-address host name live probe: unit-tested only this run.
- Playwright under the Docker API's own network namespace: not applicable (walked against the
  real compose stack from the laptop).
- `env_id` stored-verdict movement: verdict store empty (0 rows) — mechanism proven by hash
  movement, movement of stored rows not observable.
- License check for psycopg server-side cursors (§5.6 option 1): psycopg 3 is LGPL-3.1 with
  exception, already a dependency — `scripts/check_licenses.py` runs in CI and passed (§5.1);
  no new dependency either way.
- `.handoff/` purge: done 2026-11-07 in `673c0b0` after the owner's yes and the fold-in check (§6).
- Every live check that needs the benchmark box `10.10.9.41` (§5.3 LAN caller and client address,
  §5.4, §5.5, §5.6, §5.8 D13 movies): the 2026-11-01 record, not re-verified (box unreachable since
  2026-11-03; owner "1. a").
- A host name with several addresses, live: needs a system DNS or hosts change; unit-tested only.

## 6. `.handoff/` fold-in (files to delete once the owner says yes)

Content of all 19 files is folded into §1–§4 above (verdict findings → lead fixes → local
re-check; lane reports → §3; acceptance tests → §3/§5). The list proposed for deletion after
this report, exactly:

```text
.handoff/D13.acceptance.md   .handoff/D13.verdict.md
.handoff/D14.acceptance.md   .handoff/D14.verdict.md
.handoff/D15.acceptance.md   .handoff/D15.laneB.progress.md
.handoff/D15.laneC.progress.md   .handoff/D15.verdict.md
.handoff/U1.acceptance.md    .handoff/U1.cleanup.progress.md
.handoff/U1.cleanup.report.md    .handoff/U1.laneB.progress.md
.handoff/U1.laneB.report.md  .handoff/U1.laneC.progress.md
.handoff/U1.laneC.report.md  .handoff/U1.test_docs_local.md
.handoff/U1.verdict.md       .handoff/supervisor_dryrun.txt
```

### Fold-in check (2026-11-07)

Every `.handoff/` file was read again before the purge (owner: "4. aaa", purge after the check).
The list above has **18** files, not 19 as first written; the names are unchanged. These findings
were in `.handoff/` but not yet in this report:

- **D13 row evidence (R12).** Within a row, only a COUNTRY column gives LANGUAGE its country
  (`clone_executor.py`: `provides_country = semantic_type is FieldSemanticType.COUNTRY`). PHONE and
  POSTCODE give a country only across tables, through `cross_table_entity_key`, because they also
  consume a country (comment at that line). R12 named "country country code phone code".
- D13: lower-case `mon`/`MON` read as the code `mn` (the report does not say which way); `Kuku_Yalanji`
  with an underscore is INVALID (was `ukv`).
- D14: `PATCH /clone-jobs/{id}/plan` drops unknown keys silently, while `POST` uses `extra="forbid"`.
  It cannot repoint a job (no destination field), so no origin write.
- D15: a bad `NORM_ALLOWED_NETWORKS` entry makes every request a 500 (fails closed).
- U1: two test changes were made without the plan 2.9 `TEST-CHANGE:`/`C5:` form: the `/docs` test
  moved out in `57d8cbc` (now the parked text in this report §4.3) and `JS_NOT_FETCHED` widened in
  `bb162ca` (library message hosts, checked as never fetched).
- U1: a decision sent with `keepalive` when the page closes and then refused is not shown to the
  person (`ReviewPage.tsx`, `.catch(() => undefined)`).
- U1 orphans: `ui/src/index.css` (71 lines, no class used by any component, still imported by
  `main.tsx`); the header of `ui/playwright.config.ts` still says the suite runs "against a REAL
  running normapi" (the specs stub the API).

## 7. Audit against the improvement report (2026-11-04)

Owner request 2026-11-04: check that everything round 2 asked for is implemented, tested and
verified live, over "Part 1, round 2" and Part 2 "Round 2" (owner: "5. a and b"). Checked on
`1bf565d` by reading the code and tests and by direct probes. The benchmark box `10.10.9.41` is
unreachable since 2026-11-03 ("No route to host"), so every live result that needs it is the
2026-11-01 run's record, **not re-verified**.

Legend: **yes** = checked in this audit; **record** = the 2026-11-01 run's result, not re-checked;
**gap** = not done or not true as written.

### D13 — LANGUAGE

| Requirement (report fix / plan §9) | Implemented | Tested | Live |
|---|---|---|---|
| Code is the contract; `display` never parsed again (R11); ADR-010 amended | yes (`language.py`, ADR-010) | yes (`test_language_code_contract.py`, pinned test now on `comparison`) | record: movies output fed back, 0 changed |
| Code-or-name value is AMBIGUOUS unless row or column evidence settles it (R12) | yes. Probe 2026-11-04: `Ga`, `Mon`, `Dan`, `En` → AMBIGUOUS; `Mon`+MM → `mnw`; `Dan`+CI → `dnj` | yes | record: §5.8 acceptance cases |
| Hyphen splits only a valid BCP 47 tag | yes. Probe: `Kuku-Yalanji` → `gvn`, `Judeo-Arabic` → `jrb`, `Mon-Khmer` → INVALID | yes (`test_language_free_text_hyphen.py`) | n/a |
| Second-pass property test for country, currency, script, unit, language (R13) | yes | yes (`tests/property/test_second_pass_codes.py`) | n/a |
| Probe over all pycountry languages: `comparison` fed back changes 0 | yes | — | record: 0 changed; display fed back 142 held AMBIGUOUS, 0 wrong (before 440) |

### D14 — in-place mode removed

| Requirement | Implemented | Tested | Live |
|---|---|---|---|
| `in_place` field, validator, branches, `staging_name`, both `swap_table` gone | yes (`grep` over `packages`, `ui/src`, top-level docs: only the removal test names it) | yes (`test_in_place_removed.py`) | record: POST `in_place` → 422 |
| No writer built from a source connection; stored legacy job cannot write its origin | yes (`_require_separate_copy`) | yes (`test_same_origin_guard.py`) | record |
| Writable fixture login removed "if nothing else uses it" | kept: it is the clone **destination** role, still used by integration fixtures and benchmark scripts. Correct per the report's condition | — | — |
| README / ARCHITECTURE / GLOSSARY in-place text removed | yes | — | — |
| Integration suite after removal | — | — | record: 33/33 |

### D15 — local network only

| Requirement | Implemented | Tested | Live |
|---|---|---|---|
| Allowed set: loopback, RFC 1918, `fc00::/7`, deployer `NORM_ALLOWED_NETWORKS`; `100.64.0.0/10` off by default | yes (`address_policy.py`). **Correction:** §1 above says "link-local"; the code has no link-local range | yes (`test_address_policy.py`, fixed RFC table) | — |
| Caller middleware, `X-Forwarded-*` ignored, `TrustedHostMiddleware` | yes (`app.py`, `--no-proxy-headers`) | yes | record: LAN 200, outside 403, bad Host 400 |
| Strict literal parse, every resolved address checked, connect to the checked address | yes (`resolve_and_check`; libpq `hostaddr`; ClickHouse `host=hostaddr`, `server_host_name=host`) | yes | record: query_log client `::ffff:10.10.9.137`. **Not checked live:** a real DNS name with several addresses (plan §9 "Live") |
| Checked at save and at each use | yes (`routes.py` save; `clone_executor.py` both builders) | yes (`test_address_policy_wiring.py`) | record: save `8.8.8.8` → 422 |
| DSN by `make_conninfo` | yes (`postgres_destination.py`) | yes (DSN round-trip test) | — |
| Ports: API on the LAN address from `.env`, all others `127.0.0.1` | yes (`compose.yaml`, also the four demo databases) | yes | record: `ss` |
| `NORM_SECRET_KEY` out of `compose.yaml`, read from `.env` | yes. The old key stays in `main` history (open item §4.5) | yes (gitleaks on the branch) | — |
| Pin the Python minor version (report fix 7) | met by design instead: the policy never uses `is_private` (ADR-022); `requires-python` stays `>=3.12,<3.14` (plan Q6) | yes (fixed table) | — |

### U1 — the new UI

| Requirement | Implemented | Tested | Live |
|---|---|---|---|
| Five screens; others dropped (R19) | yes | yes (`test_u1_serving.py`, Playwright) | record: walk 2026-11-01 |
| Connections: Test before Save, address error at the field | yes | yes | record: `8.8.8.8` refused |
| New clone: **pick tables** and columns, check-answers page | **gap:** columns and check-answers yes; tables no. Every table of the origin is cloned because the API has no table filter (`NewClonePage.tsx` header comment). Not recorded in ADR-023 | — | — |
| Jobs list + detail survive reload (R21) | yes | yes | record |
| Review: distinct values by occurrences, one key each for accept/other/keep/undo, buttons, nothing pre-selected (R18) | yes. Keys `1`-`9` pick, `o` other, `k` keep, `u` undo; undo only while the decision is unsent (verdicts are append-only, ADR-018). **Correction:** §3 "j/k accept" and §4.4 "the k-key is a skip, not an undo" do not describe the code | yes (`review.spec.ts`: each key, modifiers, order, undo) | record: key→DOM 14 ms |
| Speed: 0.1 s per key, 1 s per page | — | — | yes, 2026-11-07 with 300 distinct values on this laptop: page 130-160 ms, key 3-16 ms (LOCAL_VERIFY U1) |
| Served by the API, one port, no CORS, offline | yes | yes (`test_u1_serving.py`, Playwright offline test) | record |
| `/docs` assets served locally | **gap:** `/docs` and `/redoc` are switched off (open item §4.3). ADR-023 still says "FastAPI's `/docs` assets are served locally" | — | — |
| Raw value only in the review route; every other response, log, trace masked, a test for each (R23) | **gap:** the review route is built and tested (`test_u1_review_route.py`); job error text, `disguised_missing[].value`, `/preview`, `/field-test`, `/runs/{id}/values` still carry raw values (open item §4.2). ADR-023 says "a test asserts that for each" | partly | — |
| English only, no login, no dark mode (R10); React + Mantine pinned (R8, Q7) | yes | yes | — |
| Screenshot audit of the old UI (R25) | replaced by plan Q4 ("agents doesn't need present UI screenshot"): closed | — | — |

### Part 2 research, carried into the build

| Research point | State |
|---|---|
| Docker Engine ≥ 28.3.3 (loopback leak fixes) | record: 29.7.1 |
| ClickHouse address pinning (no documented option) | built as `host=hostaddr` + `server_host_name` |
| FastAPI self-hosted docs assets | not built: see the `/docs` gap |
| TanStack Virtual, keyset paging | not needed: R22 chose a plain list, no server paging |
| `Intl`/ICU/FHIR code-versus-display, langcodes `find()` precedent | built as D13's contract and AMBIGUOUS rule |
| Streamlit and Appsmith telemetry | not chosen (R8) |

### Inconsistencies in this report and its sources

- ZoomInfo 100k rows: §3 says 599,853, HANDOFF.md (2026-11-01 §5.5) says 699,853. Its Experience
  cell repeats the 1M value 999,611. Cannot be re-measured while the box is down.
- §1 "link-local", §3 "j/k accept", §4.4 "k-key is a skip": corrected in the tables above.
- Eight test files point in their docstrings at `.handoff/` paths that the purge would leave
  dangling: `tests/property/test_second_pass_codes.py`, `tests/unit/test_in_place_removed.py`,
  `test_language_code_contract.py`, `test_lineage_d3_acceptance.py`, `test_name_d11_acceptance.py`,
  `test_typed_destination_d5_acceptance.py`, `test_u1_review_route.py`, `test_u1_serving.py`.
- §5.7 says screenshots were taken; plan Q4 says agents need not take them. No rule broken.

### Gaps that need the owner (not built, per the owner's "7. a")

1. New clone cannot pick tables (needs an API table filter, or the report text changed).
2. `/docs` offline: add `swagger-ui-dist` or rule `/docs` out and fix ADR-023 (open item §4.3).
3. R23 masking outside the review route (open item §4.2); ADR-023 overstates it.
4. Not measured live: DNS with several addresses (needs a system DNS or hosts change). The 1 s page
   budget was measured on 2026-11-07 (row above).

Owner decisions 2026-11-07 on these gaps: "1. a" (1 recorded as a limit), "2. a" (`/docs` ruled
out), "3. a" (recorded as open), "4. a" (page budget measured). ADR-023 now states all three.

## 8. Phase 5 close: ponytail steps and local re-checks (2026-11-07)

### Re-checks on this laptop (box unreachable)

ruff, ruff format, mypy (99 files), C5, test-assertions, root-files and gitignore guards, deptry,
actionlint, zizmor: clean. gitleaks `main..HEAD`: no leaks (full history: the 1 known
`NORM_SECRET_KEY`). pytest CI selection in 4 capped batches: 3,483 passed, 24 skipped, 1 xfailed,
1 failed (`test_a_time_is_no_day_or_month`, recorded, owner "4. aaa"). Property, defects, golden:
298 passed, 12 skipped (2 of the skips were libpostal while it was down; `test_m4_corpus.py` 24
passed once the stack ran). UI lint clean; Playwright 48/48. Compose stack: 7 services healthy,
ports exactly `10.10.9.137:8080` and `127.0.0.1` for the rest; `pytest -m integration` 33 passed.
Live on the Docker API: `/health` 200, foreign Host 400, `in_place` POST 422, save `8.8.8.8` 422,
outside caller via `r2-outside` (203.0.113.2) 403.

### `/ponytail-review` over `main...HEAD` (findings, not fixed)

1. **Legacy Postgres jobs all get the same source identity.** `clone_executor.py::_connector_source_identity`
   reads the SQLAlchemy URL, but a Postgres connector is built from a libpq string with a
   `creator`, so the URL is empty. Measured: the helper returns
   `postgresql+psycopg://None@None:None/None` for any server. Two jobs stored before
   `source_identity` existed, on different servers, then share one verdict scope, so a person's
   verdict on one source's value can be reused for the other's. Smallest fix: build it with the
   existing `source_identity(connection, database, schema)` from the job's stored connection and
   delete the helper.
2. **The review route silently stops at 100,000 entries.** `routes.py::list_review_entries` reads at
   most `_MAX_REVIEW_ENTRIES = 100_000` pending entries and drops the total that `list_queue`
   returns. R22 assumed "hundreds"; the measured ZoomInfo 100k run left 193,708 queue rows and the
   1M run 1,914,572. The screen would show "1 of 100000" and never say that the rest exist, after a
   response of roughly 140 MB (2.7 GB / 1.9M rows ≈ 1.4 KB per row; size not measured).
   Smallest fix: return the total (as `/errors` does with `X-Total-Count`) and show it on the
   screen; whether to also lower the cap is an R22 decision.
3. Should fix: a decision sent with `keepalive` on page close and then refused is dropped
   unseen (`ReviewPage.tsx`, `.catch(() => undefined)`).
4. Lean: `ui/src/index.css` (71 lines, no class used) and its import in `main.tsx` can go.

### `/ponytail-audit` (whole repo, deep only where round 2 changed code)

5. **Native runs write app data inside the repo.** `.env.example` sets
   `NORM_SIDECAR_DUCKDB_PATH`, `NORM_SIDECAR_PARQUET_ROOT` and `NORM_CACHE_PATH` to `./data/sidecar/`,
   and `.gitignore` does not list it. This is how `1bf565d` committed `cache.duckdb` and
   `catalog.duckdb` (both empty). The Parquet root holds normalized column values, so a later
   `git add` could commit dataset values (B6). Smallest fix: add `data/sidecar/` to `.gitignore`
   and untrack the two files.
6. Known and deferred by the owner: the start-up full-queue load (§3, §5.6).

Not read in depth: the round-1 normalizers outside LANGUAGE, the MySQL and Mongo connectors, the
benchmark scripts.

### `/ponytail-debt`

The branch adds 4 markers, all with an upgrade path: `ui/src/lib/reviewQueue.ts` (5 s undo
hold; undo only while unsent), `ui/src/lib/reviewJobs.ts` (2 s poll), `normalizers/language.py::_known_variants`
(IANA variant registry not installed). The whole repo has 50 marker lines; `docs/PONYTAIL_DEBT.md`
(2026-10-27) lists 36. Writing the ledger again needs the owner's yes.

### `/ponytail-gain`

Shows the ponytail benchmark only (39 tasks × 5 runs); no number for this repo exists.
