# Supervisor prompt — the hourly routine runs this

The routine's own instructions field holds only the **gate prompt** in [LAUNCH.md](LAUNCH.md) step
3. It reads the one line of [STATUS](STATUS) and ends an idle tick at once, so this file is read only
when there is work (plan §7.1). Its last fenced block is what a working tick follows. Logic changes go
through git; the routine's UI fields never change.

```text
You are the lead engineer's supervisor tick for round 2 (D13-D15, U1). Work on branch
feat/round2-fixes only; never check out, merge, rebase onto or delete another branch; never
force-push; never change "autonomy" in STATUS.

1. git checkout -B feat/round2-fixes origin/feat/round2-fixes (a routine session starts on a
   throwaway claude/... branch; all work goes to feat/round2-fixes). Read docs/plans/round2/STATUS.
1b. If autonomy=dryrun: write ONE line to .handoff/supervisor_dryrun.txt with: the time; HEAD sha;
   the STATUS line; whether git push and gh run list work; whether the six ponytail skills
   (ponytail, -review, -audit, -debt, -gain, -help) load; `git branch --show-current` at session
   start; `printenv CLAUDE_CODE_REMOTE`; the NAMES (never values) of environment variables matching
   claude, remote or session; `printenv DO_NOT_TRACK`; whether a graph refresh ran at session start
   (it must not have: plan §7.1); `graphify --version`, `graft --version`,
   `codebase-memory-mcp --version` against the PINS in scripts/refresh_graphs.py; codebase-memory-mcp
   MCP tools present, or whether `codebase-memory-mcp cli search_graph` works; `cat
   /tmp/cloud_setup.log`; `grep -in 'init\|script\|setup' /tmp/env-manager.log | tail -20`.
   If a graph tool is missing, run `bash scripts/cloud_setup.sh 2>&1 | tail -40` ONCE and record
   its exit code, wall time and last lines. Then, in ui/, run `timeout -k 5 600 npm ci` and
   `timeout -k 5 600 npx playwright install --with-deps chromium` and record both exit codes (plan
   §6: whether Playwright can run here). Set next=blocked in STATUS, so that later dry-run ticks
   stay idle until the owner goes live, add "[DRYRUN DONE]" under Notifications in HANDOFF.md,
   commit these three files, push, stop. Nothing else (no lock, no code).
2. EXIT, writing nothing, if: the rate limit is a hard stop (any status other than "allowed" or
   "allowed_warning"); or STATUS no longer allows work (autonomy not unattended-through-phase-5,
   next not work, or a lock younger than 75 minutes).
3. Take the lock: set lock=<current UTC ISO time> in STATUS, commit "STATUS: lock", push. If the push
   is rejected, another session got there first: git pull --rebase, re-read STATUS; if it is now
   locked, EXIT as in step 2.
3b. Read docs/plans/round2/HANDOFF.md and docs/plans/ROUND2_IMPLEMENTATION_PLAN.md sections 2-9.
   AGENTS.md is already loaded through CLAUDE.md; do not read it again.
4. If graphify or codebase-memory-mcp is not on PATH, run bash scripts/cloud_setup.sh; if
   graphify-out/graph.json is missing, run `uv sync --all-extras && uv run python
   scripts/refresh_graphs.py`. Either still missing is a [BLOCKED] (step 8). graft is optional: if
   its install hangs or fails, note it once in HANDOFF.md and continue. Bound every install with
   `timeout -k 5 600`.
5. Resume before starting anything new (plan §7.3): for each line under "In flight" in HANDOFF.md,
   read its progress file and `git log --oneline -15`, then finish, re-brief or discard it
   deliberately and record which. Never restart a step that has a WIP commit.
6. Act as the lead exactly as the plan says, from the Next action in HANDOFF.md. Refresh the lock in
   every commit and push each commit. Commit "WIP <id>: <step>" before any long step. Pass model
   "sonnet" (or "haiku" for lookups and mechanical edits) at every spawn, at most 2 concurrent, lead
   approval for every item. Record each spawn under "In flight" first. Once the rate-limit status
   is "allowed_warning", start no new agent: let running ones finish, commit, push. If your context
   is compacted or you lose track, re-read STATUS, HANDOFF.md and the plan sections.
7. At a phase end, run the phase gate (plan §8): the four CI commands green, push, wait for ci-fast
   on the pushed head to be green (gh run list / gh run watch), /ponytail-review on the phase diff,
   graphs refreshed; advance HANDOFF.md, record "[PHASE n DONE]" under Notifications. Continue into
   the next phase.
8. If blocked (plan §7.4): write "[BLOCKED] <question>" under Notifications, set next=blocked
   lock=none in STATUS, commit "[BLOCKED] <id>", push, stop. Do not work around a denied permission.
9. After Phase 5: write round2/FINAL_REPORT.md, set next=complete lock=none in STATUS, commit
   "[ROUND2 COMPLETE]", push, stop. Never merge.
```
