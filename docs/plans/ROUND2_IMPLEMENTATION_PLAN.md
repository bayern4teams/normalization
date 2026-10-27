# Round 2 implementation plan — D13-D15 and U1, cloud, multi-agent, lead-approved

**Source of truth for *what* to build:** [`docs/improvement-report.md`](../improvement-report.md),
"Part 1, round 2 (2026-10-25)": items D13, D14, D15 and U1, the owner decisions R1-R25, the research
in Part 2 "Round 2", and Phase 5 of "Recommended sequence". This plan says *how* to build it. Where
the two disagree on substance, the report wins; where the code contradicts either, the code wins and
the difference goes in the handoff file.

**Scope:** D15, D14, D13 and U1, each to the depth the report states, plus the ADR work the report
proposes for them (§9). Out of scope (owner decision Q9, 2026-10-27, "i agree"): the bugs held out at
the round 1 close-out (`docs/archive/plans/defects/HANDOFF.md`, "LOCAL CLOSE-OUT"), round 1's open
escalations, the zizmor CI task (R2), Part 3 of the report, throughput work.

**Branch:** `feat/round2-fixes`, cut from `docs/improvement-round-2` (which is `main` plus the round 2
report). Every agent works there and nowhere else (§2.1). `main` moves only by the owner's "merge it".

**Live state lives in git, never in a session:**
[round2/STATUS](round2/STATUS) (one line: autonomy, next, lock),
[round2/HANDOFF.md](round2/HANDOFF.md) (item table, in-flight work, next action, notifications) and
[round2/LOCAL_VERIFY.md](round2/LOCAL_VERIFY.md) (what the cloud could not prove).

This plan is the round 1 kit
([archived plan](../archive/plans/DEFECTS_IMPLEMENTATION_PLAN.md), built from
`/home/bayern/Projects/phase-kit`), adapted. What changed from round 1, and why, is in §12.

---

## 1. Launch (the owner does this once; exact strings are in `round2/LAUNCH.md`)

The work runs unattended through an hourly **supervisor routine** (§7). The owner puts the kit on
`main`, creates the cloud environment `round2-env`, creates the routine in the claude.ai Routines UI,
runs one `dryrun` tick, then sets `autonomy=unattended-through-phase-5` in `round2/STATUS`. The owner
never creates worker sessions: the lead creates every subagent itself.

## 2. Operating rules — every agent, every phase

`AGENTS.md` is the contract; this section names what bites in this round. The lead copies the
relevant rules into every brief; a worker that was not told a rule is the lead's failure.

2.1 **One branch.** `feat/round2-fixes` only. Never check out another branch, merge, rebase onto
another branch, delete a branch or force-push. Lanes own disjoint files (§3.3), so one working tree is
safe.

2.2 **Tool order, stop at the first tier that answers** (AGENTS.md E1 and §4): graphify → graft →
codebase-memory-mcp → raw source. Missing graphs: `uv run python scripts/refresh_graphs.py`, never a
silent drop to grep. **Never** the LLM paths: `graphify extract --mode deep`, `graphify label`,
`graft build --deep`. The graph tools are pinned (§2.8).

2.3 **Ponytail, all six commands, used for real.** `/ponytail` full for every change;
`/ponytail-review` on every phase diff before the phase closes; `/ponytail-audit`, `/ponytail-debt`
and `/ponytail-gain` once in Phase 5. Deliberate corners carry a `ponytail:` comment naming the limit
and the upgrade path.

2.4 **General, authoritative, never guessed.** Nothing is tuned to a test database; authoritative
data (CLDR through Babel, ISO through pycountry, the Python `ipaddress` tables) beats a hand-written
table; an undecidable input is `AMBIGUOUS`, never a plausible answer. Every item's acceptance includes:

- *the question*: would the authoritative source, or a count over the data at runtime, produce this
  value? A number or list that neither produces needs a named source or a `ponytail:` comment;
- *the grep*, run by the verifier over the item's added lines (`git diff main -- packages tests ui`):
  no hand-typed list of language codes, country codes or address ranges that duplicates CLDR,
  pycountry or `ipaddress`; no threshold literal without a derivation; nothing copied from a fixture
  into production code;
- *a never-guess case*: one test where the input is undecidable and the item returns `AMBIGUOUS` or
  refuses.

2.5 **Mechanically enforced rules stay enforced.**

- The four `ci-fast` commands (AGENTS.md §5) pass before any push of non-WIP work. `stub-check`
  (C4: no `TODO`/`FIXME` in added lines), `docs-note` (J13: every commit that changes source carries
  a `Docs:` line, WIP commits included) and `dep-check` (M4) run in CI too.
- Tests in batches, memory capped: `( ulimit -v 16777216; uv run pytest <2-4 files> -q )`. The only
  full run is the phase-gate run of the CI pytest command.
- Every exception (a suppression, a skip, a removed test, a dropped CI leg) carries reason, the
  owner's approval and a review date next to it (C5).
- A new dependency is pinned and needs a yes; the yeses for this round are in §2.10. The licence gate
  (`uv run python scripts/check_licenses.py`) runs after any Python dependency change.
- A change that can move a normalizer's answer moves `env_id` by itself (ADR-014); a new package that
  can change an answer goes into `FINGERPRINTED_PACKAGES`.
- `tests/unit/test_no_llm_in_core.py` and the read-only source guarantee (ADR-013) stay green. D14
  makes that guarantee unconditional.

2.6 **Known traps for this round.** Read the named code before touching the area.

- *Shared large files*: `normapi/clone_executor.py`, `normapi/routes.py`, `normapi/schemas.py` and
  `normapi/app.py` are touched by D15, D14, D13 and U1. Only the lead edits them, one item at a time.
- *The test client's address*: Starlette's `TestClient` reports the peer as `testclient`, which is
  not an IP address. D15's caller check will refuse it. Give the test client an allowed address; that
  is a test change under §2.9.
- *Never `is_private`* (report D15, fix 7): its list changed across versions, and it calls
  documentation and benchmark ranges private (measured 2026-10-27: `2001:db8::1` and `198.18.0.1`
  are `True` on 3.12.13, 3.13.15 and 3.14.7). The allowed set is built from explicit
  `ipaddress.ip_network` values named by their RFCs, and a test with a fixed table of addresses
  guards it.
- *Docker publishing bypasses ufw* (report D15): a compose port without a host address listens on
  every interface whatever the firewall says.
- *Partial UI*: `ui/` keeps building after every commit of Phase 4 (`npm run build`), so that the
  served UI is never broken on the branch.
- *The report cites code read on 2026-10-25*: re-read the lines before editing; Phase 0 records every
  drift.

2.7 **Completed is not evidence.** A job finishing `completed` proves nothing. The acceptance check is
written *before* the implementation, by the verifier (§4), never fitted afterwards.

2.8 **Environment.** Python **3.12** (owner decisions Q6 and Q-A, 2026-10-27; `requires-python` unchanged), everything through `uv run`.
`uv sync --all-extras` needs `libicu-dev` and `pkg-config` (installed by `scripts/cloud_setup.sh`).
Node and npm for `ui/`. Graph tools, pinned in the cloud and locally (Q10, 2026-10-27): graphifyy
0.9.96, `@nanonets/graft` 0.26.0 (the `graft` command; Trail's learnings are not adopted, Q10a),
codebase-memory-mcp 0.12.1. The pins live in `scripts/refresh_graphs.py::PINS`; a unit test keeps both
setup scripts equal to it, and the refresh script warns when an installed version differs.
`DO_NOT_TRACK=1` is set for every session and hook (Q13). No Postgres, ClickHouse, libpostal or
Docker in the cloud (§6).

2.9 **Test changes** (AGENTS.md L1, with the owner's decisions of 2026-10-27).

- **Pre-approved (Q3 "a", Q14 "i agree"):**
  - D13: `tests/property/test_idempotency_determinism.py::test_language_ga_script_input_converges_in_one_pass`
    moves from checking `display` to checking `comparison` (report R11).
  - D14: the in-place tests are deleted with the feature: `tests/unit/test_in_place_clone.py` and
    the in-place cases in the files the report lists under D14.
  - U1: the Playwright tests of the pages U1 drops (R19) are deleted with those pages.
  - Each such commit carries a `C5:` line: what was removed, "owner approval 2026-10-27", review date
    2027-01-27.
- **Any other test the round's decisions break (Q15 "b", 2026-10-27):** the lead may change only
  *how* a test reaches the code (for example an allowed address for the test client, or a new
  fixture setting). Never an expected value, an assertion, a skip, an xfail or a deletion. Each change:
  1. is its own commit, prefixed `TEST-CHANGE:`, with a `C5:` line giving the reason;
  2. is checked by the verifier: the test must still fail on the old behaviour exactly as it did
     before the change, or the change is rejected;
  3. is listed in `LOCAL_VERIFY.md`, "Test changes to review" (file, commit, reason).
  Anything beyond that is `[BLOCKED]` (§7).

2.10 **Owner decisions for this plan** (asked and answered 2026-10-27; quotes are the owner's words).

| # | Decision | Owner's words |
|---|---|---|
| Q1 | Work branch from the round 2 report branch; `main` moves once, by fast-forward | "do recommendation" |
| Q2 | The kit goes on `main` by one fast-forward after "merge it" | "i agree" |
| Q3 | Pre-approve the D13 and D14 test changes of §2.9 | "a" |
| Q4 | Run all five phases unattended; no UI screenshots by agents (replaces R25); local-only checks are tagged and listed for the owner | "it should implement all phases"; "agents doesn't need present UI screenshot" |
| Q5 | U1 replaces `ui/` in place | "i agree" |
| Q6, Q-A | Run everything on Python 3.12; `requires-python` stays `>=3.12,<3.14`; `ci-full` keeps its 3.13 leg | "keep requires-python >=3.12,<3.14, run everything on 3.12, keep the ci-full 3.13 leg" |
| Q7 | New dependencies `@mantine/core` and `@mantine/hooks`, pinned to the release current at build time; anything else is `[BLOCKED]` | "i agree" |
| Q8 | New cloud environment `round2-env` | "i agree" |
| Q9 | Held-out bugs, round 1 escalations and zizmor are out of scope | "i agree" |
| Q10 | Newest graph tools, pinned in the cloud and locally; keep `graft`, no Trail learnings; warn on a version mismatch | "update all graph tools all of them to new one and pin to new one. cloud and local"; 10a and 10b "i agree" |
| Q11 | Opus 5.5 lead, Sonnet 5.5 workers, at most 2 at a time; Haiku 5.5 where it fits | "i agree. also it could use Haiku 5.5 too if needed" |
| Q12 | Plan files in `docs/plans/round2/`, archived with a pointer at the end | "i agree" |
| Q13 | `DO_NOT_TRACK=1` in the cloud and locally | "i agree" |
| Q14 | Delete the tests of the dropped UI pages | "i agree" |
| Q15 | Other test changes under the four conditions of §2.9 | "Yes: Q15 is b with your four conditions" |
| Q16 | Add the lost-work lesson to the phase-kit | "i agree" |
| A | Idle ticks: one-line status check, quiet session start in the cloud; hourly | "1 + 2"; "i start them and go back and watch them maybe a day later" |
| B | Lost-work rules of §7.3 | "1. i agree 2. i agree 3. its my lesson from another projects" |
| Q-B | The API port binds the host's private LAN address from `.env`; the API refuses callers outside the private ranges; libpostal and the databases bind `127.0.0.1` | "i agree" |
| Q-C | The cloud session runs every CI workflow's checks itself (§8, "The CI run") | "tell cloud agent to run every Ci and test on its cloud" |

## 3. Roles, routing, concurrency

### 3.1 Roles

| role | model / effort | does |
|---|---|---|
| **Lead** (the routine session) | Opus 5.5, high | designs; does the shared-file and security-sensitive work itself; writes briefs; reviews and approves or rejects *every* result; owns `STATUS`, `HANDOFF.md`, phase gates and notifications |
| **round2-worker** (`.claude/agents/round2-worker.md`) | Sonnet 5.5, high | implements one small task inside named files; commits its own WIP checkpoints (§7.3) |
| **round2-verifier** (`.claude/agents/round2-verifier.md`) | Sonnet 5.5, high | *derive*: acceptance checks from the report before implementation; *attack*: tries to break the result; read-only on `packages/*/src` and `ui/src` |
| **Haiku 5.5** (any agent file, `model: "haiku"` at spawn) | Haiku 5.5 | lookups and mechanical edits only (AGENTS.md I2): finding every caller, renaming, deleting the D14 test cases the lead listed. Never derive, attack or an approval |

The lead **always passes `model` at spawn** and treats a worker's effort as unverified (round 1: a
worker reported low effort).

### 3.2 Routing table

The lead may deviate **only** with a one-line reason in `HANDOFF.md`.

| goes to **lead (Opus)** | goes to **Sonnet worker** |
|---|---|
| everything in `clone_executor.py`, `routes.py`, `schemas.py`, `app.py`, `main.py` | work in one small or new file with a fully specified fix |
| D15's caller check, `Host` check and address pinning; U1's raw-value review route; the ADRs; every approval; the phase-end reviews | D15's address-classification module and its table test; compose, `.env.example` and Python pin; D14's test and doc removals; D13's `language.py` changes and the second-pass property tests; U1's screens |
| an item a worker fails review twice | first attempt at medium-risk work (the lead reviews the diff line by line) |

### 3.3 Concurrency and conflict avoidance

- **At most 2 concurrent subagents** (AGENTS.md I3). No new subagent starts once the rate-limit status
  is `allowed_warning` (§7.3).
- **A lane is a set of files.** Two lanes never share a file. Phase 0 locks the ownership table with
  `graphify affected` and `graft callers --depth all` and writes it into `HANDOFF.md`.
- Everything in a shared large file is **one serial chain** run by the lead.

## 4. The lead approval protocol (nothing advances without it)

For every item, in this order:

1. **Derive.** A `round2-verifier` (*derive*) writes acceptance checks from the report's "Verified
   state" and "Fix" text only, including a negative case that fails on the old behaviour and the §2.4
   grep. They are committed at once, parked as `.handoff/<id>.test_*.py` (outside `testpaths`, so CI
   stays green) with `.handoff/<id>.acceptance.md`. The implementer has not influenced them.
2. **Implement.** The lead or a worker (per §3.2) implements against a brief that names: the report
   section, owned files, the acceptance file, the rules of §2, what "done" means (§5), and "report what
   you could NOT verify". The parked tests move into `tests/` with the implementation.
3. **Attack.** A `round2-verifier` (*attack*) runs the checks and tries to break the result. Verdict
   file `.handoff/<id>.verdict.md`: ACCEPT / REJECT with evidence, plus the unverified list.
4. **Lead decides.** The lead reads the report, the verdict *and the diff*. Reject when the result
   passes only the written tests or the report's one example, contains a fixture literal, widens
   scope, or leaves an old failure reproducible. Corrections go to the same agent by `SendMessage`.
   At most two rounds, then the lead takes over.
5. **Record.** Commit `<id>: <what> — <evidence>`; update `HANDOFF.md` (`accepted-cloud` or
   `unverified-live`); add a `LOCAL_VERIFY.md` entry for anything the cloud could not prove.

Agents write full reports to files and return at most 10 lines, so the lead's context holds verdicts,
not essays.

## 5. Definition of done — per item

- [ ] Acceptance checks pass, **and** the negative case fails on the pre-change code (shown against
  the parent commit).
- [ ] The check stages the touched files affect are green; at phase end the four CI commands are green.
- [ ] §2.4 grep clean; §2.5 guards clean; no lint or type baseline growth.
- [ ] Every test that needs the real environment carries the `integration` marker (Docker, Postgres,
  ClickHouse) or the `e2e` marker (the UI against the running stack), and has a `LOCAL_VERIFY.md`
  entry with its exact command.
- [ ] The docs the change affects are updated in the same commit (J7, J13).
- [ ] `HANDOFF.md` row updated; the lead's verdict recorded. No self-certification by a worker.

## 6. What the cloud can and cannot verify

**Can:** the four `ci-fast` commands; the licence gate; every normalizer DB-free; the address
classification and the caller and `Host` checks through the app with a test client; DSN building with
`psycopg.conninfo.make_conninfo`; `compose.yaml` read as YAML (every published port has a host address: `127.0.0.1`, or the `.env` LAN address for the API, Q-B);
the UI's `npm ci`, `npm run build` and `npm run lint`; Playwright, if its browsers install in the
container (the dry-run tick records whether they do).

**Cannot:** real Docker port binding and the Docker Engine version, a LAN caller, real DNS answers
with several addresses, libpq `hostaddr` pinning against a real Postgres, whether clickhouse-connect
can connect to a fixed address on a real server, `pytest -m integration`, and the UI against the
running stack. These become `unverified-live` with a `LOCAL_VERIFY.md` entry.

**Rules for the split:**

- An item is fully implemented even when its live check is deferred; it is marked `unverified-live`,
  never `accepted-cloud`, and never silently "done".
- Synthetic tests are evidence of mechanism. The report's measured "before" values go into
  `LOCAL_VERIFY.md` as what the owner must see change.
- Pre-existing red, out of scope: the nightly `drift` workflow (round 1 plan §6). A phase gate means
  `ci-fast` green.

## 7. Sessions, limits, supervisor, notifications

### 7.1 The status file and the idle tick

`round2/STATUS` is one line, the only home of these three values:

```text
autonomy=<off|dryrun|unattended-through-phase-5> next=<work|blocked|complete> lock=<none|ISO time>
```

The routine's own prompt (in `round2/LAUNCH.md`) reads only this line and the current time with one
command, and ends the tick at once unless `autonomy` allows work, `next=work`, and the lock is `none`
or older than 75 minutes. An idle tick therefore reads one line and makes one tool call: it never
reads `SUPERVISOR.md`, `HANDOFF.md` or the plan. Only the owner changes `autonomy`. The session-start
hooks stay quiet in the cloud (`CLAUDE_CODE_REMOTE=true`): no graph refresh and no graft notices
before the gate; a working tick refreshes the graphs itself (SUPERVISOR step 4). The dry-run tick
confirms that the cloud sets that variable.

### 7.2 Supervisor

A scheduled routine (cron `0 * * * *`, created in the claude.ai Routines UI with the repo and the
GitHub connector) starts a fresh session. When the gate passes it follows the last fenced block of
[round2/SUPERVISOR.md](round2/SUPERVISOR.md): take the lock, act as **lead** from the Next action in
`HANDOFF.md`, chain phases through Phase 5, never merge. Phases chain only through the phase gate
(§8), including a green CI run on the pushed head.

### 7.3 Never lose work to a session limit

A limit can end a session while subagents are working; the container is then gone. So:

1. **Agents commit their own checkpoints.** A worker commits and pushes `WIP <id>: <step>` after each
   finished file or test, with only its own paths (`git commit -m "..." -- <paths>`), a `Docs:` line,
   and no pull or rebase (only this session pushes the branch while it holds the lock). On
   `index.lock`, wait and retry. A WIP commit is not acceptance.
2. **Small briefs.** One file and its tests per brief, so a lost agent loses one small piece at most.
3. **A progress file per item.** `.handoff/<id>.progress.md` (done steps, next step, open questions)
   is committed with every WIP. A new session resumes from it, never from scratch.
4. **Derived tests are committed when written** (§4 step 1).
5. **Record before spawning.** Before starting an agent, the lead writes the agent's task and files
   under "In flight" in `HANDOFF.md`, commits and pushes. A new session reads "In flight", `git log`
   and the progress files, and finishes or re-briefs each entry deliberately, recording which.
6. **No new agents in the warning band.** Once the rate-limit status is `allowed_warning`, the lead
   starts no new subagent; it lets running ones finish, commits, updates `HANDOFF.md` and pushes. The
   warning band is still not a reason to stop the lead's own committed work.

### 7.4 Limits, blocks, notifications

- The cloud shows no usage percentage: work until the limit stops the session; nothing is lost
  because every step is committed.
- **Blocked** (CI red that cannot be fixed, an item rejected twice by the lead, a missing tool, a
  decision only the owner can make, a dependency outside §2.10): write `[BLOCKED]` with the question
  under Notifications in `HANDOFF.md`, set `next=blocked lock=none`, push, stop. The owner answers
  under "Owner answers" and sets `next=work`. The owner checks back about a day later, so a block
  costs a day: ask only what §2 does not already decide.
- Cloud push notifications do not reach the owner. The record is `HANDOFF.md` plus commit prefixes:
  `[PHASE n DONE]`, `[BLOCKED]`, `[ROUND2 COMPLETE]`.

## 8. Phases

### Hard ordering (report R24 and "Recommended sequence", Phase 5)

```text
D15 ──► D14 ──► D13 ──► U1     (U1 is served by the API that D15 guards; D14 first so U1 never offers in-place)
```

Within a phase, worker lanes on separate files run beside the lead's serial chain.

### Phases

- **Phase 0, baseline and ownership (lead; no feature code).**
  1. Run the four CI commands; record each stage's result and time in `round2/PHASE0_REPORT.md`. Check
     `gh run list` for `ci-fast` on the branch.
  2. Re-verify every item's "Verified state" against the source, per item: *confirmed / differs (how) /
     over-claims*. Also record: the CLDR territory-to-language data that Babel 2.18 exposes (for D13's
     row evidence); whether clickhouse-connect can connect to a fixed IP while keeping the host name
     (D15); whether `safe_preview` masks the candidate readings in the queue `detail` (U1); which
     existing tests set `in_place` (D14); which Playwright specs cover the dropped pages (U1).
  3. Lock the file-ownership table and lane plan in `HANDOFF.md`.
  4. Seed `LOCAL_VERIFY.md` with the report's "before" values. Commit, continue. If `ci-fast` is red
     at the branch point for a new reason, that is `[BLOCKED]`.

- **Phase 1, D15: local network only.**

  | lane | owner | files |
  |---|---|---|
  | A (serial) | lead | `docs/adr/ADR-022-*.md`, `normapi/app.py`, `normapi/main.py`, `normapi/schemas.py`, `normapi/routes.py`, `normapi/clone_executor.py` (the two builders, the DSN) |
  | B | worker | the new address-policy module in `normapi` and its unit test with a fixed address table |
  | C | worker | `compose.yaml`, `.env.example`, `Dockerfile` |

- **Phase 2, D14: remove in-place mode.**

  | lane | owner | files |
  |---|---|---|
  | A (serial) | lead | ADR-013 and ADR-017 amendments, `schemas.py`, `clone_executor.py`, `routes.py`, both `*_destination.py` (`swap_table`) |
  | B | worker (Haiku for the listed deletions) | the in-place tests listed in the report, `tests/integration/fixtures/postgres-init/01-init.sql` (if nothing else uses the login), the in-place text in README.md, ARCHITECTURE.md, GLOSSARY.md |

- **Phase 3, D13: LANGUAGE.**

  | lane | owner | files |
  |---|---|---|
  | A (serial) | lead | ADR-010 amendment, row-evidence wiring in `clone_executor.py` |
  | B | worker | `normalizers/language.py`, `tests/unit/test_language_normalizer.py` (or the existing language test file) |
  | C | worker | `tests/property/` second-pass tests for country, currency, script, unit and language |

- **Phase 4, U1: the new UI.**

  | lane | owner | files |
  |---|---|---|
  | A (serial) | lead | `docs/adr/ADR-023-*.md`, serving the built UI and self-hosted docs assets from `app.py`, the raw-value review route in `routes.py`/`schemas.py` |
  | B | worker | `ui/package.json`, `ui/package-lock.json`, the app shell, Connections, New clone |
  | C | worker | Jobs, Review, Quality, `ui/e2e/` |

- **Phase 5, close (lead).** The CI run green; `/ponytail-review` over the whole branch diff,
  `/ponytail-audit`, `/ponytail-debt`, `/ponytail-gain`; every `HANDOFF.md` row has a lead verdict;
  `LOCAL_VERIFY.md` final; `.handoff/` folded into `round2/FINAL_REPORT.md` and purged; the report's
  round 2 status line updated (add, do not rewrite); `[ROUND2 COMPLETE]`. **Stop. Never merge.**

### The CI run (owner decision Q-C)

GitHub Actions is the second check, not the only one: since 2026-10-25 it has refused to start jobs
for a billing reason, and it may do so again. So the session runs the checks itself. The workflow files
are the one home of the commands; the session reads them and runs the `run:` steps of every job in
`ci-fast.yml`, `stub-check.yml`, `docs-note.yml`, `guards.yml`, `dep-check.yml` and `docs.yml`, with
the base `main`, installing the pinned tools those steps install (Vale, lychee, gitleaks, actionlint,
the Mermaid renderer). Tests stay in memory-capped runs. It records each job's result in the phase's
`[PHASE n DONE]` note. Then it checks GitHub: a GitHub run that started and failed blocks the gate like
a local failure; a run GitHub refused to start (billing) is recorded and does not block.

### Phase gate (end of every phase)

All items accepted, or `unverified-live` with a `LOCAL_VERIFY.md` entry, or escalated → the four CI
commands green (Phase 4 also: `npm ci && npm run build && npm run lint` in `ui/`) → the CI run above
green in the session, and GitHub as it says (`drift` excluded) → `/ponytail-review` of the phase diff addressed → graphs
refreshed → `HANDOFF.md` updated → push → `[PHASE n DONE]` commit.

## 9. Per-item specification

The report holds each item's evidence and fix; this section adds only what the build needs. §2.4
applies to all.

**D15 — local network only** (report D15; decisions R9, R14-R17).

- ADR-022 first: network and database-address policy.
- *Allowed set*: loopback, RFC 1918, IPv6 unique local `fc00::/7`, built from `ipaddress` networks,
  plus ranges from a deployer setting (R14). `100.64.0.0/10` is refused unless that setting adds it.
- *Callers*: an ASGI middleware refuses a peer outside the allowed set; `X-Forwarded-For` is ignored
  (R17). `TrustedHostMiddleware` with an allowlist of host names (the DNS-rebinding defence).
- *Database targets*: strict literal parsing (decimal, octal and hex IPv4 forms refused, `::ffff:`
  unwrapped); a host name resolves and **every** address must be allowed (R15); the connection uses the
  checked address (libpq `hostaddr`; for ClickHouse, what Phase 0 found). Unix-socket paths and
  multi-host strings refused. Checked when a connection is saved and each time it is used.
- *DSN*: built with `psycopg.conninfo.make_conninfo`, never an f-string.
- *Ports* (Q-B): the API port binds the host's private LAN address, read from `.env`; libpostal and
  every database port bind `127.0.0.1`.
- *Secrets*: the committed `NORM_SECRET_KEY` leaves `compose.yaml`; compose reads it from `.env`;
  `.env.example` documents it.
- *Acceptance beyond tests passing*: a fixed table of addresses with their expected class, written
  from the RFCs (not from running the code); one refused caller, one refused `Host`, one refused
  target per refusal kind; a DSN round-trip for a password containing `@`, `/`, `,` and `?`.
- *Live*: Docker binding, a LAN caller, real DNS with several addresses, `hostaddr` on real Postgres,
  the ClickHouse connection.

**D14 — remove in-place mode** (report D14; decision R4).

- ADR-013 and ADR-017 amendments: the origin is always read-only; every clone writes a separate copy.
- Remove exactly what the report lists. The tests go under §2.9 (pre-approved, `C5:` line).
- *Acceptance*: a request with `in_place` is refused by the schema; no writer is ever built from a
  source connection (a test over `clone_executor`'s builders); `grep -rn in_place packages ui/src`
  returns nothing.
- *Live*: `pytest -m integration` on Postgres and ClickHouse after the removal.

**D13 — LANGUAGE** (report D13; decisions R11-R13).

- ADR-010 amendment: the code is the contract; `display` is never parsed again.
- A hyphen splits only a valid BCP 47 tag; otherwise the whole value is looked up as a name.
- A value that is both a code and a name is `AMBIGUOUS` unless row evidence (the row's country from
  the existing `_country_from_*` helpers and CLDR's languages for that territory) or column evidence
  (the column's own values, the way ADR-008 and ADR-011 do it) settles it.
- The second-pass property test runs for every code-based type (R13).
- *Acceptance*: the report's six-row table, each row with its expected outcome from the report's Fix
  text; the probe over all pycountry languages fed back from `comparison` changes 0; `Mon` with a
  Myanmar row is `mnw`, `Mon` with no evidence is `AMBIGUOUS`.

**U1 — the new UI** (report U1; decisions R5-R8, R10, R18-R23; Q4, Q5, Q7, Q14).

- ADR-023 first: UI scope and technology.
- React + Mantine (`@mantine/core`, `@mantine/hooks`, exact versions), replacing `ui/` in place. The
  existing API client and types carry over where they still fit.
- Five screens as the report's table lists. The review screen: one distinct value at a time, ordered
  by occurrences, single keys for accept, other value, keep ambiguous and undo, buttons too, no reading
  pre-selected.
- The built UI is served by the API (one port, no CORS); FastAPI's `/docs` assets are served locally.
  No CDN, no web fonts, no telemetry.
- The raw value appears only in the review route's response (R23); every other response, log, trace
  and error report stays masked (a test asserts this for each).
- No screenshots by agents (Q4).
- *Acceptance*: build and lint green; Playwright specs for each screen (in the cloud if the browsers
  install, else `e2e` and listed); a key-press handler test for each review key.
- *Live*: every screen against the running stack; the 0.1 s key and 1 s page budgets measured.

## 10. After the final phase

The agents never merge. The owner runs `round2/LOCAL_VERIFY.md` against the real environment, reviews
the "Test changes to review" section, then decides the merge. The plan files move to
`docs/archive/plans/` with a pointer (Q12, M3).

## 11. Open questions (answered before launch)

- **Q-A**, **Q-B** and **Q-C** are answered (§2.10). None is open.

## 12. Changes from round 1 and known limits

- **Idle cost** (§7.1): round 1's idle tick read the whole 144-line `HANDOFF.md`; this round reads one
  line, and the session-start hooks stay quiet in the cloud.
- **Lost work** (§7.3): round 1's workers did not commit; a limit stop lost their uncommitted files.
- **Rules added since round 1**: AGENTS.md v1.2.0 (C4, C5, J13, L1-L7, M1-M4) and the CI checks that
  enforce them. `CLAUDE.md` is the one line `@AGENTS.md`, so round 1's byte-identity rule is gone.
- Cloud evidence is mechanism-level; the network and stack behaviour is confirmed only locally.
- File ownership is inferred until Phase 0 locks it.
