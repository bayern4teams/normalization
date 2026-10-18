# Defects D1-D12 implementation plan — cloud, multi-agent, lead-approved

**Source of truth for *what* to build:** `docs/improvement-report.md`, Part 1 of that report ("Defects and fixes to apply now", D1-D12) and its
ordering/dependency notes. This plan says *how* to build it. Where the two disagree on substance,
the report wins; where the code contradicts either, the code wins and the discrepancy goes in the
handoff file.

**Scope:** Fix the twelve verified defects D1-D12 of Part 1, each to the depth Part 1 states, plus the ADRs the report asks for first (ADR-018 abstention and adjudication, ADR-019 confidence calibration, ADR-020 typed destination). D1 includes the minimum storage and stage Part 3 §3.3-§3.5 draws for it (adjudication queue + verdict tables in the existing metadata Postgres, a resolve stage before dispatch, review endpoints) because Part 1's fix cannot exist without them. Out of scope: Part 3 beyond that minimum (the HITL console UI, the agent decider, conformal prediction sets and per-source `calibration_bins` wiring into the normalizers, a Marquez deployment, the full target diagram), Part 2 (research, no work), Part 4 (appendices), throughput work, schema normalization, and the nightly `drift` workflow (red on `main` for a pre-existing reason, §6).

**Branch:** `feat/defects-fixes`, created from `main`. Every agent works there and nowhere else (§2).

**Live state lives in two files, not in any session:**
[defects/HANDOFF.md](defects/HANDOFF.md) (status table, next action, escalations) and
[defects/LOCAL_VERIFY.md](defects/LOCAL_VERIFY.md) (what the cloud could not prove).

---

## 1. Launch (the user does this once; exact strings are in `defects/LAUNCH.md`)

The system runs unattended through an hourly **supervisor routine** (§7). The user: puts the kit on
`main`, creates a cloud environment with the kit's setup script, creates the routine in the
claude.ai Routines UI (repo + environment + GitHub connector + the short pointer prompt), runs one
`dryrun` tick, then sets `Autonomy: unattended-through-phase-N`. The user never creates worker
sessions: the lead creates every subagent itself.

## 2. Operating rules — every agent, every phase

These are CLAUDE.md's rules restated as the contract. The lead copies the relevant
ones into every worker brief; a worker that was not told a rule is the lead's failure.

2.1 **One branch.** `feat/defects-fixes` only. Never `git checkout` another branch,
merge, rebase, delete or force-push. Worktree isolation is not used: lanes own
disjoint files (§3.3), so one working tree is safe.

2.2 **Tool order, stop at the first tier that answers.** graphify
(`query` / `path` / `explain` / `affected` / `god-nodes`) → graft (`ask`,
`skeleton`) → codebase-memory-mcp (`search_graph`, `trace_path`, `get_code_snippet`,
`check_index_coverage` on every file relied on) → raw source. Missing graphs:
the project's graph refresh script (`uv run python scripts/refresh_graphs.py`), never a silent drop to grep. **Never** the
LLM paths: `graphify extract --mode deep`, `graphify label`, `graphify cluster-only`
without `--no-label`, `graft build --deep`. A graph that contradicts the code loses;
rebuild it. `affected "X"` returning nothing means the *graph* sees no caller —
confirm with grep before deleting anything.

2.3 **Ponytail, all six commands, used for real.**
- `/ponytail` full — the ladder: does it need to exist → already in this codebase →
  stdlib → native → installed dependency → one line → minimum code.
- Every non-trivial branch leaves **one** runnable check; deliberate corners carry a
  `ponytail:` comment naming the ceiling and the upgrade path (the report's own
  "Ceiling" / "Deferred alternative" text is the source for those comments).
- `/ponytail-review` on every phase's diff **before** the phase closes.
- `/ponytail-audit` once, in Phase 5, paired with graph tiers (graph finds the
  unreferenced, the audit decides whether it should exist).
- `/ponytail-debt` in Phase 5: the ledger of every deferral and its trigger.
- `/ponytail-gain` in Phase 5: measured effect, for the final report.
- `/ponytail-help` when unsure.

2.4 **General, authoritative, never guessed.** CLAUDE.md states it and the report repeats it for every item: nothing is tuned to a specific database; authoritative data (CLDR, ISO, GLEIF, python-stdnum, the Public Suffix List) beats a hand-written table that grows one found example at a time; an input that cannot be decided is `AMBIGUOUS` (or `unverifiable`), never a plausible answer; precision is preserved, never invented. Every item's acceptance therefore includes:
- *the question*: "would the authoritative source, or a count over the data at runtime, produce this value?" A number or list that neither produces needs a named source or a `ponytail:` comment giving its ceiling;
- *the grep*, run by the verifier over the item's added lines (`git diff main -- packages tests`): no dict/list literal of ISO country codes, TLD or public suffixes, phonetic rule rows, currency or language codes that duplicates an authoritative dataset already in the tree or the installed libraries; no threshold literal in non-test code without a derivation or a `ponytail:` note; no string or number copied from a test fixture into production code;
- *a never-guess case*: one test where the input is undecidable and the item returns `AMBIGUOUS`/`unverifiable`/abstains, and one where the source states less precision than the output type could hold and the output does not invent the rest.

2.5 **Mechanically enforced rules stay enforced.** From CLAUDE.md and CI:
- the four `ci-fast` commands (`ruff check`, `ruff format --check`, `mypy packages`, and `pytest -m "unit or (golden and not slow)"`) all pass before any push;
- **tests in batches, never the whole suite at once, memory capped** (`( ulimit -v 16777216; uv run pytest <2-4 files> -q )`); the only full run is the Phase-gate run of the CI command above, which is itself ~45 s and ~1.3k tests;
- `AGENTS.md` and `CLAUDE.md` are byte-identical (`tests/unit/test_agent_docs.py`): edit one, `cp` it over the other;
- licence gate: `uv run python scripts/check_licenses.py` after any dependency change; `scripts/license_policy.toml` denies GPL (so `abydos` is out) and tiers LGPL to unmodified dynamic use;
- every new package that can change a normalizer's answer goes into `FINGERPRINTED_PACKAGES` (`packages/normexec/src/normexec/env_fingerprint.py`, ADR-014); `normcore`, `normalizers` and `normio` source is already hashed into `env_id`, so a changed normalizer output moves `env_id` by itself;
- `tests/unit/test_no_llm_in_core.py`, `test_no_splink.py`, `test_post_commit_hook.py` and the read-only source guarantee (ADR-013: `SourceConnector` has no write method) must stay green; nothing here adds a write path to a source database;
- no LLM on the hot path (report decision K); the graph tools' LLM modes stay unused (§2.2).

2.6 **Known traps.** Read the named doc before touching the area.
- *`context_hash` never contains the value* (`normcore/context.py:54-74`, ADR-016). A verdict keyed only on it (report §3.5 decision B) would answer every value in a context with one human decision. *`env_id` hashes the whole `normalizers` source* (ADR-014): keyed on it, every normalizer edit (including this plan's) orphans every verdict. D1's key is therefore decided in ADR-018, §9 D1.
- *Decision #8* (`normio/connectors/postgres_destination.py:25-44`): a failed value's ORIGINAL string must always land in the cell, and a value a typed column cannot hold must never reach `INSERT` (it kills the chunk transaction). `normio/storage_types.py:coerce` already is that cast gate for NUMERIC/MONEY/BOOLEAN; DATE/DATETIME are untyped on purpose (partial dates).
- *Distinct-value planning* (ADR-016, `normexec/planner.py`): normalization runs once per distinct value per context and is cached by `make_cache_key`; a new stage that changes a result must be part of that key or the cache serves the old answer.
- *Resume skips rows client-side* from the last committed offset (`clone_executor.py:1882-1888`); anything written per chunk must be idempotent across a re-run chunk.
- *Clone runs on a daemon thread* (`clone_executor.py:902`); an exception there surfaces as a job state, not a stack trace. Test through the persistence layer, not by watching a thread.
- *ClickHouse and Postgres types differ* (`storage_types.py` notes on `Decimal(38,9)` vs unbounded `NUMERIC`); any destination change is checked on both engines' DDL builders.
- *The report cites `file:line` from 2026-09-30*: re-read the lines before editing; Phase 0 records every drift (§8).

2.7 **Completed is not evidence.** A run finishing `completed` proves nothing; the
only proof is an independent score. The scorer/acceptance check is written *before*
the implementation, by the verifier (§4), never fitted afterwards.

2.8 **Environment.** Python 3.12 (`requires-python >=3.12,<3.14`), everything through `uv run`. `uv sync --all-extras` needs `libicu-dev` and `pkg-config` for PyICU (the setup in `scripts/cloud_setup.sh` installs them). No Postgres, ClickHouse or libpostal sidecar in the cloud: `pytest -m integration` cannot run there (§6). Wall times measured locally on 2026-10-04: lint+format+mypy 6.5 s; the CI pytest command 46 s (1288 passed, 12 skipped, 140 deselected).

## 3. Roles, routing, concurrency

### 3.1 Roles

| role | model / effort | does |
|---|---|---|
| **Lead** (the launched session) | Opus 5.5, high | designs, does the complex and cross-cutting items itself, writes worker briefs, reviews and approves/rejects *every* result, owns commits, `HANDOFF.md`, phase gates, notifications |
| **defects-worker** (`docs/archive/agents/defects-worker.md`) | Sonnet 5.5, high | implements one item inside named files; reports to `.handoff/<id>.report.md` |
| **defects-verifier** (`docs/archive/agents/defects-verifier.md`) | Sonnet 5.5, high | *derive*: writes acceptance checks from the report before implementation; *attack*: tries to break the result afterwards; read-only on `src/` |

Measured in the reference project: the frontmatter `model` key is honoured but a worker's `effort` could not
be confirmed as high (one worker reported low). So: the lead **always passes `model: "sonnet"`
at spawn**, treats worker effort as unverified, and keeps judgement-heavy work (§3.2 lead column) itself.

### 3.2 Routing table — who gets what

The lead may deviate **only** with a one-line reason in `HANDOFF.md`.

| goes to **lead (Opus)** | goes to **Sonnet worker** |
|---|---|
| anything inside a shared large file (`packages/normapi/src/normapi/clone_executor.py` 2069 lines, `routes.py` 1116, `pg_persistence.py` 770) | work in one small file with a fully specified fix |
| D1 and D12 (the abstention path: the verdict key, the resolve stage, status semantics), D5 and D3 (both edit the executor after D1), D2 (statistics: the threshold and what the numbers may be claimed to mean), the ADRs, and the phase-end reviews | D7 then D8 (`identifier.py`), D9 (`url.py`), D10 (`phone.py`), D11 (`name.py` + one new module), D6's harness and error injectors (new files under `tests/gold/` and `normanalysis/`), D4's detector (new module) |
| gate/orchestration wiring, algorithmic work with subtle correctness | tests, fixtures, docs, report plumbing, applying a known pattern |
| items a worker fails review twice | first attempt at medium-risk items (lead reviews the diff line-by-line) |
| every approval decision | never an approval decision |

**Escalation rule:** a worker whose result is rejected twice is taken over by the lead.

### 3.3 Concurrency and conflict avoidance

- **At most 2 concurrent subagents.** The cloud usage window is small and parallel agents burn it
  fast; the cap is raised only by the user.
- **A lane = a set of files.** Two lanes never share a file. Phase 0 locks the real ownership table
  with `graphify affected` per item and writes it into `HANDOFF.md`; files the report does not name
  are inferred until then. A lane that needs a file it does not own asks the lead; the lead
  serialises it behind the owner.
- Everything touching a shared large file is **one serial chain** run by the lead. Independent
  work runs beside it, never inside it.

## 4. The lead approval protocol (nothing advances without it)

For every item, in this order:

1. **Derive.** Lead briefs a `defects-verifier` (*derive*): write acceptance checks from
   the report's Evidence + Fix text only — including a negative case that fails on the
   *old* behaviour and the §2.4 grep. Output: tests under `tests/` +
   `.handoff/<id>.acceptance.md`. The implementer has not influenced these.
2. **Implement.** Lead (or a worker, per §3.2) implements against the brief. The brief
   states: report sections, owned files, acceptance file, rules from §2, what "done"
   means (§5), and "report what you could NOT verify".
3. **Attack.** A `defects-verifier` (*attack*) runs the checks and tries to break the
   result. Verdict file: ACCEPT / REJECT with evidence, plus the unverified list.
4. **Lead decides.** The lead reads the worker report, the verdict *and the diff*.
   - **Reject** if it passes only the written tests, passes only the report's one
     example, contains a corpus literal, widens scope, or leaves any old failure
     mode reproducible. Send *specific* corrections to the same worker with
     `SendMessage` (it keeps its context). Max two rounds, then the lead takes over.
   - **Accept** only when it would survive the lead's own attempt to break it.
5. **Record.** Lead commits (`<id>: <what> — <evidence>`), updates `HANDOFF.md`
   (`accepted-cloud` or `unverified-live`), and adds a `LOCAL_VERIFY.md` entry for
   anything the cloud could not prove. If a result is wrong or evidence-thin, it goes
   under "Open escalations" in `HANDOFF.md` instead of being waved through.

Workers write full reports to files and return ≤10 lines, so the lead's context holds
verdicts, not essays.

## 5. Definition of done — per item

- [ ] Acceptance checks (derived by the verifier) pass, **and** the negative case fails
  on the pre-change code (shown by running it against `git stash` or the parent commit).
- [ ] The check stages (`ruff check`, `ruff format --check`, `mypy packages`, and the touched test files run in batches under `ulimit -v 16777216`) that the touched files affect are green; at
  phase end the four-command CI sequence of §2.5 is green (it is the one verification command).
- [ ] §2.4 literal grep clean; §2.5 guards clean; no lint/type baseline growth.
- [ ] The report's "Ceiling" for the item is recorded as a `ponytail:` comment or an
  item note; the "Deferred alternative" and its trigger are listed for `/ponytail-debt`.
- [ ] Graphs refreshed (`uv run python scripts/refresh_graphs.py`) after the commit.
- [ ] `HANDOFF.md` row updated; `LOCAL_VERIFY.md` entry added where applicable.
- [ ] Lead's explicit verdict recorded. No self-certification by a worker.

## 6. What the cloud can and cannot verify

**Can:** the whole `ci-fast` sequence (lint, format, mypy, unit + fast golden: ~1.3k tests in under a minute); the licence gate; a DB-free exercise of every normalizer and of the executor's per-chunk functions (`_apply_column`, `_normalize_chunk`) with fakes; the adjudication store against SQLAlchemy on an in-memory/temporary SQLite engine where the SQL is portable (the Postgres-specific DDL is string-checked and left to `unverified-live`); DDL builders for both engines as strings; synthetic fixtures with planted ground truth (injected dirty values with known clean values, ambiguous values with known candidate sets, disguised nulls at known cells) built by the verifier from the report's failure shapes.

**Cannot:** run against a real PostgreSQL or ClickHouse (`pytest -m integration`, `tests/integration/test_clone_pipeline.py`), the libpostal sidecar, the UI, a Marquez instance, or BART (a Java tool; the report's "highest-leverage" D6 source) and the Raha datasets (external downloads). The user rebuilds the real environment with `docker compose up -d postgres libpostal` (Postgres on host port 5535, see `compose.yaml`) and a ClickHouse server, as written in `defects/LOCAL_VERIFY.md`. The data of the user's own databases is never read by the cloud.

**Pre-existing red, out of scope:** the nightly `drift` workflow fails on `main` at "Diff against committed golden expectations" because `tests/golden/expectations/` does not exist (the report's D6 "no corpus files", seen from CI). The supervisor must not treat `drift` as a blocker of a phase gate; "every workflow" in the gate means `ci-fast` (and `ci-full` when it runs on the branch). D6 may give `drift` something to compare; fixing the workflow itself is not required.

**Rules for the split:**
- An item is fully implemented even when its live check is deferred; it is marked
  `unverified-live`, never `accepted-cloud`, and never silently "done".
- Synthetic tests are *evidence of mechanism*, not proof the live numbers moved. The report's live
  "before" figures go into `LOCAL_VERIFY.md` as the values the user must see change.
- Anything depending on an external model/endpoint is exercised with a stub that records calls; the
  live endpoint is `unverified-live`.
- Report counts, not rates, where the base rate is tiny; stratify where an aggregate hides a failure.

## 7. Sessions, limits, supervisor, notifications

**Target: unattended cloud runs, resumed by an hourly supervisor routine** (proven in the reference project; if a
dry-run tick fails, fall back to an attended session with the same protocol).

- **State is in git.** After every accepted item (and every `WIP <id>` step): commit, update
  `HANDOFF.md`, push. A new session needs only the plan + `HANDOFF.md`. Sessions are short-lived
  *slices*; nothing depends on a session's memory, so no compaction is needed.
- **Usage limit.** The cloud shows no usage percentage, so there is no 90 % rule there: work
  until the limit stops the session. Nothing is lost because everything is committed per
  step. If a usage percentage *is* readable (local `get_usage`), stop at ≥ 90 %: finish the
  commit, write `HANDOFF.md`, push.
- **Supervisor.** A scheduled cloud routine (cron `0 * * * *`, branch `feat/defects-fixes`)
  (created in the claude.ai Routines UI with the repo and GitHub connector — a routine made from
  inside a session has no repo) starts a fresh session whose prompt is
  [defects/SUPERVISOR.md](defects/SUPERVISOR.md). It exits
  at once when: the rate limit is a hard stop (`allowed_warning` is not one); `HANDOFF.md` says `Autonomy: off`; the next
  action is "done" or "waiting for the user"; or `Lock` is younger than 75 minutes (another
  session is alive). Otherwise it takes the lock and acts as **lead** for as long as it can.
  An idle tick costs almost nothing, so hourly resumes soon after each window reset.
- **Phases chain automatically** once the user sets `Autonomy: unattended-through-phase-5`:
  the phase gate (§8) must pass, including a green CI run on the pushed head, before
  `HANDOFF.md` advances to the next phase. After Phase 5 the supervisor stops and never merges.
- **Never lose an item.** Commit `WIP <id>` before any long operation. A session that finds
  uncommitted work or a stale lock inspects `git status`, finishes or discards it deliberately,
  and records which in `HANDOFF.md`.
- **Notifications.** Cloud push does not reach the user (confirmed). The record is
  `HANDOFF.md` + commits: every phase end, blocker and the final completion are written to its
  "Notifications" section, and a `[PHASE n DONE]` / `[BLOCKED]` / `[Defects D1-D12 COMPLETE]` commit
  message prefix makes them visible in GitHub. Try the push tool anyway; do not rely on it.
- **Cost discipline:** Sonnet for the mechanical work in §3.2; batch independent
  lookups; keep worker reports in files; do not re-read what the graphs already answered.

## 8. Phases

### Hard ordering (from the report, §Recommended sequence and the item texts)

```
D1 ──► D12            (D12 gives NEEDS_REVIEW a meaning under D1, or deletes it)
D1 ──► D5, D3         (D5 routes un-castable values to the same path; D3 and D5 edit the executor after D1)
D6 ──► D2             (calibration is impossible without labels)
D7 ──► D8             (same file; the split needs the registry)
D4, D9, D10, D11      independent of each other and of D1 (each owns one small file)
```

Shared large files (`clone_executor.py`, `pg_persistence.py`, `routes.py`) are edited only by the lead,
one item at a time, in the order D1, D5, D3. `pyproject.toml` / `uv.lock` /
`env_fingerprint.py` are touched by D9, D11 and possibly D4: those items are in different phases and
different lanes, so never concurrent.

### Pre-findings (made while writing this plan; Phase 0 re-verifies, §11)

The report is mostly right and its `file:line` citations held where checked, but these differ from the
code today. Acceptance below already targets what is actually true.

| # | report says | the code says | effect |
|---|---|---|---|
| F1 | D5: all 24 types map to TEXT; cast gate to be built | `normio/storage_types.py` is the pre-insert cast gate (`coerce`); NUMERIC, MONEY, BOOLEAN are typed natively and `typed_destination_columns` defaults to true (`clone_executor.py:399`, `_destination_plan`:550). Only DATE/DATETIME stay TEXT, deliberately (partial dates). The comment at `postgres_destination.py:25-44` is stale. | D5 shrinks to: prove the gate adversarially on both engines, fix the stale text, ADR-020, and one open decision about DATE (§9) |
| F2 | D10: extensions lost silently | extension is parsed into `structured["extension"]` (`phone.py:107`) and `display` (INTERNATIONAL format) keeps it; the loss is in `comparison`/`search` (E.164) and the missing RFC 3966 form | D10 targets the views that lose it |
| F3 | D1 / decision B: verdict keyed `(context_hash, profile_version, env_id)` | `context_hash` never contains the value (`normcore/context.py:54-74`, ADR-016); `env_id` hashes all of `normalizers` source (ADR-014) | the key in §9 D1 differs from the report on substance; the code wins, ADR-018 records it |
| F4 | D2: 61 `confidence=` sites, 28 literal 1.0 | a plain grep finds 61 sites and 31 `confidence=1.0` matches (some conditional) | Phase 0 counts with `ast` and records the figure; nothing is tuned to it |
| F5 | D12: `NEEDS_REVIEW` appears only in the enum and the severity order | confirmed (`enums.py:23`, `dispatch.py:309`) | none |
| F6 | D4: `MissingKind` exists to receive the output | confirmed (`normcore/enums.py:26`); `ptype` is not installed and its weight and licence are unknown | D4 starts with a feasibility gate |
| F7 | (baseline) CI | `ci-fast` green on `main`; local lint+format+mypy pass, pytest 1288 passed. The nightly `drift` workflow is red because `tests/golden/expectations/` does not exist | `drift` is out of scope (§6) |

### Phases

- **Phase 0, baseline and ownership (lead only; no feature code).**
  1. Run the four CI commands; record per-stage result and time in `defects/PHASE0_REPORT.md` (the
     figures in §2.8 are the expected ones; a difference is a finding). Check `gh run list` for `ci-fast` on
     `main` and the branch.
  2. Re-verify every D-item's "Verified state" against the source (read the cited lines; run the report's
     greps) and write the result per item: *confirmed / differs (how) / over-claims*. Count `confidence=`
     sites with `ast`, split literal vs expression. Read `normcore/pii.py`, `test_pii_masking.py`,
     ADR-013/014/016 and the `job_errors` writer for D1's PII rule (§9 D1).
  3. Lock the file-ownership table with `graphify affected` per item symbol and `graft callers --depth all`
     for each shared symbol (`_apply_column`, `_normalize_chunk`, `NormalizedValue` constructors, the
     registry that registers `IdentifierNormalizer` and `NameNormalizer`, `type_detection` entry points);
     write it and the lane plan into `defects/HANDOFF.md`. Flag any file two items need.
  4. A `defects-verifier` builds **synthetic fixtures** under `tests/defects/` with planted ground truth
     for each item's failure shape (listed in §9 as *Fixture*), plus the shared scorer proven both ways:
     an oracle passes; an injected confident-wrong value is named `wrong-confident`; an injected
     needless abstention is named `over-abstain`. Record **before** numbers on the current code (e.g.
     how many of N planted ambiguous values reach a queue today: 0; how many planted Cyrillic names
     share a phonetic key today) and note every place a report example already passes.
  5. Write `defects/LOCAL_VERIFY.md` entries for the report's live "before" values (already seeded in
     that file), commit, continue. If `ci-fast` is red on the branch point for a new reason, that is
     `[BLOCKED]`, not worked around.

- **Phase 1, the abstention path and identifiers.**

  | lane | owner | items | files |
  |---|---|---|---|
  | A (serial chain) | lead | D1, then D12 | `normapi/adjudication.py` (new), `pg_persistence.py`, `clone_executor.py`, `routes.py`, `schemas.py`, `normcore/enums.py`, `normcore/dispatch.py`, `docs/adr/ADR-018-*.md` |
  | B | worker 1 | D7, then D8 | `normalizers/identifier.py`, the registration site, `tests/unit/test_identifier_normalizer.py` + new tests |
  | C | worker 2 | D9 | `normalizers/url.py`, `pyproject.toml`, `uv.lock`, `normexec/env_fingerprint.py`, `tests/unit/test_url_normalizer.py` |

- **Phase 2, types, provenance, names, phones.**

  | lane | owner | items | files |
  |---|---|---|---|
  | A (serial chain) | lead | D5, then D3 | `normio/storage_types.py`, both `*_destination.py`, `clone_executor.py`, `normapi/lineage.py` (new), `pg_persistence.py`, `routes.py`, `docs/adr/ADR-020-*.md`, docs |
  | B | worker 1 | D10 | `normalizers/phone.py`, `tests/unit/test_phone_normalizer.py` |
  | C | worker 2 | D11 | `normalizers/name.py`, `normalizers/_bmpm.py` + rule data (new), `pyproject.toml`, `uv.lock`, `env_fingerprint.py`, `tests/unit/test_name_normalizer.py` |

- **Phase 3, measurement.**

  | lane | owner | items | files |
  |---|---|---|---|
  | A (serial) | worker 1, lead reviews line by line | D6 | `normanalysis/gold.py` (new), `normcli/cli.py`, `tests/gold/` (new), `tests/unit/test_gold_*.py` |
  | A (serial, after D6 accepted) | lead | D2 | `normanalysis/calibration.py` (new), `normcli/cli.py`, `docs/adr/ADR-019-*.md` |
  | C | worker 2 | D4 | `normanalysis/disguised_missing.py` (new), `normanalysis/type_detection.py` (hook only), `pyproject.toml` only if the feasibility gate passes `ptype` |

- **Phase 4, re-measure and harden (lead).** Run the D6 harness and the D2 report on the engine as it is
  after Phases 1-3 and record **after** numbers next to the Phase 0 **before** numbers in
  `defects/PHASE4_REPORT.md`; run the property idempotency tests for every normalizer a lane changed
  (`pytest -m property tests/property/test_idempotency.py`, in batches); update `docs/` for changed
  behaviour (data contract, ADR index, README, dependency inventory, `traceability-matrix` row); add a
  short "implementation status" note to `docs/improvement-report.md`'s status line pointing at the plan and
  at the F1-F7 corrections (the report is the user's document: add, do not rewrite).

- **Phase 5, integration and hand-over.** The four CI commands green; `/ponytail-review` over the whole
  branch diff, `/ponytail-audit`, `/ponytail-debt`, `/ponytail-gain`; every `HANDOFF.md` row has a lead
  verdict; finalise `LOCAL_VERIFY.md`; purge `.handoff/` after folding its verdicts into
  `defects/FINAL_REPORT.md`; `[Defects D1-D12 COMPLETE]`. **Stop. Never merge.** The user verifies locally
  and merges.

### Phase gate (end of every phase)

All items accepted or explicitly `unverified-live`/escalated → the four CI commands green → CI on the
pushed head green (`ci-fast`; `drift` excluded, §6) → `/ponytail-review` of the phase diff addressed →
graphs refreshed → `HANDOFF.md` updated → push → `[PHASE n DONE]` commit.

## 9. Per-item specification

Every block ends with *Never-guess* and *No-literals* reminders only where they bite; §2.4 applies to all.
Test file names are suggestions; new fixtures live under `tests/defects/` (Phase 0) and the item's own
test file.

**D1 — AMBIGUOUS has an exit path** (lead; report D1, §3.3-§3.5, decisions A-D, K). Write
`docs/adr/ADR-018-abstention-and-adjudication.md` first (format of ADR-001..017), then build:
- *Store.* Two tables in the existing metadata Postgres, added as `CREATE TABLE IF NOT EXISTS` blocks beside
  `normalization_clone_job_errors` (`pg_persistence.py:121-130` style, `normalization_` prefix):
  `normalization_adjudication_queue` (pending work: key, semantic type, original value, candidates and
  trace from the normalizer's `structured`/`trace`, first/last seen job, occurrence count) and
  `normalization_adjudication_verdicts` (append-only: key, decided value, `decided_by`, `decided_at`,
  `rationale`, `confidence` nullable, `env_id`, `profile_version`). `decided_by` is validated as
  `human:<id>` or `agent:<id>` from the first version (Q15): swapping the decider is a different string,
  not a migration. A verdict is never updated or deleted; a newer row for the same key wins.
- *Key.* `(semantic_type, content_hash(original), context_hash, profile_version)`. **Differs from the
  report's `(context_hash, profile_version, env_id)` (F3):** that key has no value in it and `env_id`
  moves on every normalizer edit. `env_id` is stored on the row and written into the applied value's trace,
  not matched on. ADR-018 states this and the reason. The occurrence count dedups: a million identical
  ambiguous values in one context are one queue row; the same value in two contexts (two countries) is two.
- *Resolve stage.* In `clone_executor` before dispatch, per column per chunk: one batched lookup for the
  chunk's distinct values (cost bounded by cardinality, ADR-016). A hit becomes the result **by
  re-normalizing the decided value through the dispatcher in the same context** and keeping `original` =
  the source string, with an `adjudication` `TraceStep` carrying decided_by/decided_at/rationale/env_id
  (provenance must not lie: report decision C). A verdict is accepted at `POST` time only if that
  re-normalization yields `NORMALIZED`/`PARSED`; otherwise 422 and nothing is stored.
- *Unresolved.* The first-run write path is unchanged byte for byte (original into the cell, error row as
  today); the value is additionally upserted into the queue, idempotently: a resumed, re-run chunk
  (`clone_executor.py:1882-1888`) must not change queue contents. Only `AMBIGUOUS` is queued (Q14);
  `INVALID` is not.
- *API.* In `routes.py`/`schemas.py`, following the existing naming of the clone-job error routes: list
  the queue (filters: semantic type, status; paged), get one entry, post a verdict. No UI (Part 3).
- *PII.* Queue rows hold exactly what `normalization_clone_job_errors` already holds for that value, and
  the API applies the same masking (`normcore/pii.py`); Phase 0 pins which that is.
- *Accept.* (1) Negative on `main`: with a verdict present, run the same chunk twice; on `main` both runs
  emit original + error row, on the branch the second run emits the adjudicated value and no error row for
  it, and every non-adjudicated cell of the first run is byte-identical to `main`. (2) 1000 identical
  ambiguous values -> 1 queue row, occurrences 1000. (3) Same value, two countries -> two rows; two values,
  one country -> two rows; a verdict for one answers none of the others. (4) `profile_version` change ->
  verdict not applied, old row still readable; `env_id` change alone -> still applied. (5) A verdict that
  re-normalizes to non-clean is refused, store unchanged. (6) An `agent:v3` verdict applies identically to
  a `human:alice` one. (7) Chunk resume leaves the queue unchanged. (8) Source connectors still have no write
  method; the existing clone tests and `test_pii_masking.py` pass unchanged.
  *Fixture:* planted ambiguous phones (no region), dates (`01/02/2024`), amounts (`1,234`) with known
  candidate sets.
  *Live:* phone, date and money are the three producers (`phone.py:209`, `date.py:575`, `money.py:183`);
  on a real clone, answer one queue entry via the API, run the job again, and compare the destination cell
  and the job's error rows with a direct query (LOCAL_VERIFY).

**D12 — NEEDS_REVIEW has defined semantics, or is gone** (lead, after D1; `enums.py:23`,
`dispatch.py:309`). Ladder: nothing produces it, so delete it unless ADR-018 gives it a real producer
inside this scope (the natural one: an `agent:` verdict whose stored `confidence` is below a stated bound
is applied as `NEEDS_REVIEW`, meaning "emitted, a human must confirm"). If kept, it has a producer, a test
that exercises it, and one line in the data contract; if deleted, the enum member, its severity slot, and
every mention in `docs/` and `ui/` are removed in one commit. *Accept:* a grep over `packages/`, `ui/`
and `docs/` shows either a producer plus test, or no remaining reference; the severity-order test
(`test_dispatch.py`) is updated deliberately; no other status moved. Record the choice in ADR-018.

**D7 — stdnum registry from the library, tri-state result** (worker 1, then D8; `identifier.py:68-73`,
report D7). Replace the four-entry `_STDNUM_REGISTRY` by a catalogue discovered from the installed
`python-stdnum` (its `get_cc_module` / package listing and its own formats index), so the set of countries
follows the library with no hand count. Which module is the *tax identifier* of a country must come from
stdnum's own data (module title/docstring terms, the exact term list kept in one constant with its source);
a country with zero or several matching modules yields `unverifiable` with the candidate module names in
`structured`, never the first match. The existing four keep today's modules (golden outputs byte-identical).
Result states are `valid` / `invalid` / `unverifiable`; prefer the existing `UNKNOWN` validation status
plus `structured["verification"] = "unverifiable"` and a reason over a new status value (the severity
tuple `dispatch.py:314` and the UI know five). No live lookups, ever (report Appendix F): "VIES down" is
not a state this offline code can see, so the state means "no offline validator applies". *Accept:*
a test enumerates stdnum at run time and asserts every classified country is reachable (no literal
count); for three countries outside US/GB/DE/FR a number built from the module's own check-digit
function validates and a one-digit change fails; an unlisted country returns `unverifiable`, not
`invalid`; with several candidate modules the outcome is `unverifiable` listing them; the term list is the only hand-written
table and is justified in a comment; golden/unit identifier tests pass unchanged. *Fixture:* planted
valid/invalid/unlisted numbers per the above. *Live:* none (offline).

**D8 — TAX_ID and CODE no longer share a normalizer** (worker 1, after D7; `identifier.py:92-94`). Split
by what each can honestly claim: `TAX_ID` is jurisdictional and verifiable (D7); `CODE` is only
canonicalized (digit folding, case, separators) and never reports a check-digit verdict; `IDENTIFIER`
keeps whatever Phase 0 shows it does today (do not widen). Update the registration, `can_handle` sets and the
cache-key reachability. *Accept:* the same string as `TAX_ID` (with a country) and as `CODE` yields different
`validation_status` where a check digit applies; `CODE` never contains a check-digit verdict; the
normalizer-per-semantic-type coverage test (24 of 25) still passes; every changed golden/unit expectation
is listed in `HANDOFF.md` with the reason; idempotency property test passes for both.

**D9 — registrable domain from the Public Suffix List** (worker 2; `url.py`). Compute
`registrable_domain`, `public_suffix` and `is_private_suffix` (ICANN vs PRIVATE section, so `x.github.io` is
distinguishable) into `structured`, additive; no existing key changes. Use a library that carries a
pinned snapshot and does **no network access by construction** (`tldextract` with its fetch URLs
disabled, or `publicsuffixlist`; whichever passes `check_licenses.py` and the offline test), add it to
`FINGERPRINTED_PACKAGES` so a PSL update moves `env_id`, and record the snapshot date. IP literals,
`localhost`, single labels and unlisted suffixes give `registrable_domain = None` with a reason, never "the
last two labels". IDN: compute on one declared form and test the other. State in the module docstring
which URL standard the module follows (report: WHATWG vs RFC 3986) without changing behaviour.
*Accept:* with sockets blocked the function works; `a.co.uk`, `b.a.co.uk`, `x.github.io`, `例え.jp`, an IP,
`localhost`, `foo.notatld` each give the correct, listed result; every existing url unit/golden test
passes byte-identically; `test_env_fingerprint.py` covers the new package. *Fixture:* the table above
plus a naive last-two-labels implementation that the cases must expose. *Live:* none.

**D10 — phone: extensions and the RFC 3966 form** (worker 1; `phone.py:62-135`). Read libphonenumber's
`FALSEHOODS.md` and `FAQ.md` first (notes in the item's report). Add `structured["rfc3966"]`; make
`comparison` the RFC 3966 form **only when an extension is present** (E.164 otherwise, unchanged bytes),
so two numbers that differ only by extension no longer compare equal and nothing else moves. E.164 stays
beside `region`/`country_code` (already in `structured`). `search` stays extension-free (a search for the
base line must find it). Idempotency: re-normalizing the emitted `comparison` returns the same. No-region
numbers stay `AMBIGUOUS`. *Accept:* `x45`, `ext. 45`, `;ext=45`, `#45` spellings give one `comparison`;
extension absent -> output byte-identical to `main` for the whole existing phone corpus; property
idempotency passes; invalid stays `INVALID`. *Fixture:* planted extension spellings with known truth.
*Live:* none.

**D11 — phonetics that fit the data** (worker 2, lead reviews line by line; `name.py:100-125`). Three
parts, in order. (1) Stop emitting Anglo-centric codes for names that are not: a name in a non-Latin script,
or whose transliteration source is `anyascii`, must not get Soundex/NYSIIS/Metaphone/MRC; it carries
`phonetic_status: "not_applicable"` with the script instead (today it gets confident noise). (2) Add
language-aware keys: Double Metaphone and Beider-Morse for Latin-script and Cyrillic/Arabic/Persian-origin
transliterated names. Phase 0 of the lane surveys permissive options (`phonetics`/`Metaphone`, a
permissive Python BMPM, a port of Apache Commons Codec's rule files, Apache-2.0, attribution kept) and
takes the first that passes `check_licenses.py`; `abydos` (GPL-3.0) is out. Rule data is data, versioned like
the other dictionaries or embedded with a NOTICE. (3) CJK: readings are polyphonic, so **no key is
emitted** (`not_applicable`), recorded as a `ponytail:` ceiling with the upgrade path (a pinyin/romaji
source and the language to read in). *Accept:* planted same-name pairs across spellings (`Мухаммед` /
`Muhammad` / `Mohammed`, `Юрий` / `Yuri` / `Yury`, `محمد` / `Mohammad`) share at least one key in
more pairs than the Soundex baseline recorded in Phase 0; planted different-name pairs never share a key;
no non-Latin input ever carries Soundex/NYSIIS/Metaphone/MRC; the old keys for Latin input are
byte-identical. Counts are reported, not rates. *Fixture:* the pairs, generated from `iuliia` schemes /
published transliteration tables, not from the repo's tests. *Live:* none.

**D5 — typed destination: prove, correct, record** (lead, after D1; F1). Do not rebuild the gate. (1)
Prove it: for each natively typed semantic type, on the Postgres and ClickHouse DDL builders, adversarial
strings (`d1989-12-11`, `NaN`, `1e999`, `1,234`, `\x00`, 10^40, `yes please`, empty, whitespace) pass
through `coerce` to `(None, error)` or a clean typed value, never raise, and never reach the INSERT
unconverted. (2) Correct the stale statements: header and `SEMANTIC_TYPE_TO_PG_TYPE` comment in
`postgres_destination.py`, the ClickHouse twin, README/data-contract lines that say every column is
TEXT. (3) `docs/adr/ADR-020-typed-destination.md` records the true state, why DATE/DATETIME stay TEXT
(EDTF partial values; precision is preserved, never invented), and that cast failures are `INVALID` with
the original string in an error row, not queued (Q14 queues only `AMBIGUOUS`). **Open decision, default
"keep TEXT":** a typed DATE column with the EDTF original in a companion column is the only design that
could add DATE; the lead implements it only if it loses no precision on a planted partial-date set, and
flags it in the hand-over for the user's approval either way. *Accept:* the adversarial test on both
engines; a grep shows no remaining "every value is TEXT" claim; the existing typed-destination tests
(`test_typed_destinations.py`) pass unchanged. *Live:* real Postgres/ClickHouse: a clone with planted bad
numeric/boolean values completes with typed columns and the bad values in error rows.

**D3 — OpenLineage events at job boundaries** (lead, after D5; report D3). New `normapi/lineage.py`.
Emit `START` / `COMPLETE` / `FAIL` run events per clone job and table with input dataset (source table),
output dataset (destination table) and a `columnLineage` output facet: per destination column, its
input field(s) and a transformation description (normalizer name, semantic type, `profile_version`);
companion columns (`__currency`, `__code`) map to their source column. Events are stored in a new
`normalization_lineage_events` table (durable, same metadata DB: audit is a hard requirement, Q13) and
optionally forwarded over HTTP when `NORM_OPENLINEAGE_URL` is set; a forwarding failure never fails the
job. Add `GET /clone-jobs/{job_id}/lineage`. Default: no new runtime dependency (events are plain dicts
validated in tests against the vendored spec JSON schema, pinned version, Apache-2.0 notice kept);
take `openlineage-python` instead only if it passes `check_licenses.py` and removes more code than it adds.
*Accept:* every destination column of a two-table fake job, including companions, appears in a
`columnLineage` facet; payloads validate against the vendored schema; **no connection secret or host
credential appears in any payload** (test with a connection holding a password); a resumed job does not
emit a second `COMPLETE`; the question "which source columns produced destination column X in job J" is
answered from stored events with no row scan. *Fixture:* a fake job over fake connectors. *Live:* send the
events to a Marquez instance (`docker run`), see the column lineage in its UI/API.

**D6 — a gold corpus that measures accuracy** (worker 1, lead reviews; report D6). New
`normanalysis/gold.py` and `tests/gold/`. (1) A case schema (semantic type, context, input, expected status,
expected value or candidate set) with a loader that also accepts any CSV with dirty/clean columns, so BART or
Raha output can be fed without new code. (2) A scorer with four outcome classes per case: correct,
correct-abstain, `wrong-confident` (catastrophic, Q16) and `over-abstain`; counts, plus the
`(stated confidence, correct)` pairs D2 consumes. (3) Seeded, deterministic injectors that turn a clean
value into a dirty one with known truth, for the types where truth is derivable without hand labels
(phone formats and region removal -> expected `AMBIGUOUS`, date day/month swaps where both <= 12 ->
`AMBIGUOUS`, thousands/decimal separators, email and URL case and scheme, country names via CLDR); seed
values come from authoritative data (libphonenumber example numbers, CLDR, Babel), never from `tests/`. (4)
`cohen_kappa` and `krippendorff_alpha` as small pure functions, checked against published reference values
(Artstein & Poesio). (5) A `normcli` subcommand to score a corpus. Existing golden tests are untouched.
*Accept:* the scorer is proven both ways (oracle -> all correct; injected wrong-confident and
over-abstain engines are caught and named); same seed -> byte-identical corpus; at least one injector
case where the engine today is wrong or abstains is reported as such (the corpus is not vacuous); κ and α
match the reference numbers; the §2.4 grep finds no corpus value in non-test code. *Live:* feed BART
output (Java, needs Postgres) and the six Raha datasets (LOCAL_VERIFY).

**D2 — measure confidence, then threshold it** (lead, after D6; report D2 steps 1, 2, 4). New
`normanalysis/calibration.py` and `docs/adr/ADR-019-confidence-calibration.md`. (1) Reliability: bin stated
confidence against correctness per semantic type (and per source id as a grouping key in the report only),
with counts per bin, expected calibration error and the bins where stated > observed. (2) Chow's rule: the
abstain/emit threshold from a **cost ratio that is a required, stated argument** (cost of a wrong value
over cost of an abstention; no default is hidden in code, Q16 gives the direction, not the number). (3)
Risk-coverage curve and area. Output is a JSON + Markdown report from the `normcli` subcommand. Not wired
into dispatch and no `confidence=` literal in any normalizer changes: measuring comes before tuning. Conformal
sets and persisted per-source `calibration_bins` are Part 3. *Accept:* a synthetic perfectly calibrated
predictor gives ECE within a tolerance derived from the sample size (not a magic number); an overconfident
one (stated 1.0, true 0.8) is flagged with the bin named; Chow's threshold equals the brute-force
minimum-cost threshold on a toy case; the command refuses to run without the cost ratio; the diff touches no
normalizer. *Live:* run on the user's labelled data; the report's before: 61 sites, 28 of them literal
`1.0` (F4), 0 calibration code.

**D4 — disguised missing data, at cell level** (worker 2, lead reviews; report D4). Feasibility gate first:
can `ptype` be installed under Python 3.12 in the cloud, does it pass `check_licenses.py`, is it
deterministic, and what does it pull in? If yes, wrap it as an optional analysis stage. If not, the
fallback (the report's own "complements, does not replace" stance) is a native detector in
`normanalysis/disguised_missing.py`: for a column with a detected type, report the distinct values that fail
that type's validator, recur as a small set, and match no valid parse, with counts and a `MissingKind` *hint*.
It never rewrites data. Numeric magic numbers (`-999`) are only reachable through `ptype`; the native path
states that ceiling in a `ponytail:` comment. Output is per distinct value with counts (not row lists: >1B
rows). The existing negative controls (`type_detection.py:58-68`) and every existing detection test stay
untouched and green. *Accept:* a planted column (97% dates, 3% `N/A`, `unknown`, `-`) reports the three
sentinels with exact counts; `NA` in a COUNTRY alpha-2 column (Namibia) is **not** reported; a column with no
sentinels reports nothing; column-type results are identical to `main` for the existing detection tests.
*Live:* run on a real table and compare with a direct `SELECT value, count(*) ... GROUP BY` (LOCAL_VERIFY).

## 10. After the final phase

The branch is **not merged by the agents.** The user runs `LOCAL_VERIFY.md` against the real
environment, then merges to `main` locally. Later parts of the report (Part 3's remainder: the HITL console, the agent decider, conformal sets and per-source calibration wired into dispatch, the Marquez deployment; the throughput phase) are planned afterwards, informed by the measured results and by what D1/D2/D3 turned out to need.

## 11. Known limits of this plan (stated, not hidden)

- Cloud-verifiable evidence is mechanism-level; the report's live numbers can only be confirmed
  locally, which is why `LOCAL_VERIFY.md` exists.
- Parallelism is limited by shared files and by the usage window; the larger saving is cost, from
  routing mechanical items to Sonnet.
- File ownership for items the report does not name is inferred until Phase 0.
- The report's claims were verified on 2026-09-30 and four of its twelve already differ from the code in detail (§8, "Pre-findings"). Phase 0 re-verifies all twelve; an item may shrink, never silently grow.
- D1's adjudication path is exercised end-to-end only on a synthetic store in the cloud; the real-Postgres run and the human review loop are `unverified-live`.
- D6 ships a Python injector and scorer; BART and Raha integration are `unverified-live` (they need a JVM, Postgres and downloads). Calibration numbers from synthetic gold measure the harness, not the engine on the user's data, until the user runs it there.
- The ER engine is undecided (report Q11), so D9's registrable domain and D11's phonetic keys are materialised as additive `structured` keys, not as consumer-shaped columns.
