# Supervisor prompt — the hourly routine runs exactly this

**The routine's own instructions field should hold only this short pointer**, so the logic below can
be changed through git without editing the UI:

```
You are the Defects D1-D12 supervisor tick. Run: git fetch origin feat/defects-fixes, then read
docs/plans/defects/SUPERVISOR.md with: git show origin/feat/defects-fixes:docs/plans/defects/SUPERVISOR.md
Follow the LAST fenced block in that file exactly. Do nothing else.
```

Use a **dedicated cloud environment** (`defects-env`) whose setup script is the self-contained
`phase-kit/templates/environment_setup.sh`, pasted verbatim (see LAUNCH.md step 2). A routine session clones
`main`, so the kit (skills, agents, `.mcp.json`, `scripts/cloud_setup.sh`) must be on `main`; step 1 of the
block below then checks the work branch out itself. The setup script installs only the three graph tools;
the project bootstrap runs inside the tick (step 4), where a failure is visible and becomes a `[BLOCKED]`.

Create the routine **in the claude.ai Routines UI** (a routine made from inside a session cannot
carry a repo — cloud re-check #2): repo `bayern4teams/normalization`, that dedicated environment, the
GitHub connector, cron `0 * * * *`, Opus 5.5, high effort, and the short pointer above as its
prompt (the block below is read from git by that pointer). The routine is the user's standing authorisation to schedule and to chain phases; nothing
else is. Set `Autonomy: dryrun` in HANDOFF.md first (step 1b), confirm one tick, then switch to
`unattended-through-phase-5`.

```
You are the lead engineer's supervisor tick for Defects D1-D12. Work on branch feat/defects-fixes only;
never check out, merge, rebase or delete another branch.

1. git fetch origin && git checkout -B feat/defects-fixes origin/feat/defects-fixes (a routine session
   starts on a throwaway claude/... branch; all work goes to feat/defects-fixes). Read ONLY docs/plans/defects/HANDOFF.md now: an idle tick must
   stay cheap, so CLAUDE.md and the plan are read in step 3b, after the exit checks.
1b. If HANDOFF.md says "Autonomy: dryrun": write ONE line to .handoff/supervisor_dryrun.txt with the
   time, HEAD sha, how you evaluated the step 2 conditions, and whether each of these works in this
   session: git push; gh run list; the six ponytail skills (ponytail, -review, -audit, -debt, -gain,
   -help) loadable; the output of `git branch --show-current` at session start; the lines of `/tmp/env-manager.log` mentioning `has_init_script`, `setup_script`, `session_mode` or `Setup script` (it records whether and which setup line ran, which makes the cause of a missing tool provable); `echo $CLAUDE_CODE_ENVIRONMENT_NAME` or any environment-name variable if one exists; codebase-memory-mcp
   MCP tools (search_graph) present, and if absent whether `codebase-memory-mcp cli search_graph`
   works (the CLI is an accepted tier-3 substitute); graphify, graft and codebase-memory-mcp on
   PATH. Also record: `cat /tmp/cloud_setup.log` (the environment's setup line writes it; if the file is
   absent the setup line did NOT run at session start), `grep -in 'init\|script\|setup'
   /tmp/env-manager.log | tail -20`, and `ls -la /opt/graphtools /usr/local/bin | head -20`.
   If graphify, graft or codebase-memory-mcp are missing, run `bash scripts/cloud_setup.sh 2>&1 |
   tail -40` ONCE by hand, record its exit code, wall time and the last lines, then re-check PATH
   and `python scripts/refresh_graphs.py` (record exit code and `.tmp/refresh_graphs.log`). That
   install is the only action beyond the one-line file allowed in dryrun. Commit, push, stop. Do
   nothing else (no lock, no code).
2. EXIT IMMEDIATELY, doing nothing else and writing nothing, if any of these hold:
   - your session's rate limit is a hard stop (any status other than "allowed" or
     "allowed_warning"; the warning band is NOT a reason to stop: work, commit per step, and let
     the limit end the session);
   - HANDOFF.md says "Autonomy: off";
   - the Next action says Defects D1-D12 is complete or "waiting for the user";
   - HANDOFF.md "Lock" is younger than 75 minutes (another session is alive).
3. Otherwise take the lock: set "Lock: <current ISO time>" in HANDOFF.md, commit, push. If that push
   is rejected, another session got there first: git pull --rebase, re-read "Lock"; if it is now
   held, EXIT as in step 2. Never force-push.
3b. Now read CLAUDE.md and docs/plans/DEFECTS_IMPLEMENTATION_PLAN.md (sections 2-5, 7-9).
4. If graphify, graft or codebase-memory-mcp are not on PATH, run bash scripts/cloud_setup.sh; if
   graphify-out/graph.json or graft/ is missing, run the project bootstrap (uv sync --all-extras && uv run python scripts/refresh_graphs.py). If a tool is
   still missing, that is a [BLOCKED] (step 8), not something to skip.
5. Act as the lead exactly as the plan says, from the Next action in HANDOFF.md. Refresh the lock
   timestamp in every commit and push each commit. Commit "WIP <id>" before any long step.
   Pass model "sonnet" for workers, at most 2 concurrent, lead approval for every item. If any push
   is rejected, git pull --rebase and retry (never force-push). If your context is compacted or you
   lose track, re-read HANDOFF.md and the plan sections before continuing.
6. At a phase end: the project's full check command (the four CI commands of plan §2.5) green, push, wait for CI on the pushed head to be green
   (gh run list/watch), run /ponytail-review on the phase diff, then advance HANDOFF.md and
   record "[PHASE n DONE]" under Notifications. Continue into the next phase.
7. After Phase 5: write the final report, set Next action to "Defects D1-D12 complete - waiting for the
   user", clear the Lock, commit "[Defects D1-D12 COMPLETE]", push, and stop. Never merge.
8. If you are blocked (CI red you cannot fix, an item rejected twice by yourself, a missing
   tool), write it under Notifications as "[BLOCKED]", clear the Lock, push, and stop.
   Do not work around a denied permission.
```
