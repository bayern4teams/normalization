# Launch guide — round 2 (bayern4teams/normalization)

Do these in order. Each step says what to check.

## 0. Preconditions

`git pull --ff-only` on `feat/round2-fixes`; `ci-fast` on `feat/round2-fixes` is green; the open
questions in the plan's §11 are answered.

## 1. Put the kit on `main` (needs the owner's "merge it")

A routine always clones `main`, and skills, agents, `.mcp.json`, `.claude/settings.json` and
`scripts/cloud_setup.sh` load at session start, so they must be on `main`. The fast-forward carries
the round 2 report (`docs/improvement-report.md`, `docs/research/resources/_raw-*`), this plan and
`docs/plans/round2/`, `.claude/agents/round2-*.md`, the graph-tool pins (`scripts/refresh_graphs.py`,
`scripts/cloud_setup.sh`, `scripts/cloud_environment_setup.sh`), the quiet cloud start and
`DO_NOT_TRACK` (`.claude/settings.json`, `.githooks/post-commit`). It carries no feature code.

```bash
git checkout main && git merge --ff-only feat/round2-fixes && git push origin main && git checkout feat/round2-fixes
```

If `main` has moved and a fast-forward is impossible, stop and ask.

## 2. Cloud environment

claude.ai/code → create a NEW environment `round2-env`, Network access Full, environment variable
`DO_NOT_TRACK=1`, and paste the whole of `scripts/cloud_environment_setup.sh` as its setup script.

## 3. Routine (create it in the claude.ai Routines UI, not from inside a session)

| Field | Value |
|---|---|
| Repository | bayern4teams/normalization |
| Environment | `round2-env` |
| Model / effort | Opus 5.5, high |
| Trigger | every hour (cron `0 * * * *`) |
| Connector | GitHub |
| Instructions | the gate prompt below |

```text
You are the round 2 supervisor tick. Your first and only command before deciding is:
git fetch -q origin feat/round2-fixes && git show origin/feat/round2-fixes:docs/plans/round2/STATUS && date -u +%Y-%m-%dT%H:%M:%SZ
End the session at once, with no other tool call and the one-word reply "idle", unless all three
hold: autonomy is dryrun or unattended-through-phase-5; next is work; lock is none or more than 75
minutes before the printed time. Otherwise run:
git show origin/feat/round2-fixes:docs/plans/round2/SUPERVISOR.md
and follow the LAST fenced block in it exactly. Do nothing else.
```

If the UI offers a push-permission option, allow pushes to non-`claude/` branches.

## 4. Dry run

```bash
sed -i 's/^autonomy=off /autonomy=dryrun /' docs/plans/round2/STATUS
git add docs/plans/round2/STATUS && git commit -m "STATUS: autonomy dryrun" -m "Docs: none, run state only" && git push origin feat/round2-fixes
```

Run the routine once (run now), wait about 15 minutes, then:

```bash
git pull --ff-only && tail -1 .handoff/supervisor_dryrun.txt
```

All must hold: the setup log ends cleanly; the three graph tools are on PATH at their pinned
versions; no graph refresh ran at session start; `CLAUDE_CODE_REMOTE` is `true`; `DO_NOT_TRACK` is
`1`; the six ponytail skills load; codebase-memory MCP tools are present (or its CLI works);
`git push` and `gh run list` work. The line also says whether `npm ci` and the Playwright browser
install worked. The tick sets `next=blocked`, so later ticks stay idle.

## 5. Go live

```bash
git pull --ff-only
sed -i 's/^autonomy=dryrun next=blocked /autonomy=unattended-through-phase-5 next=work /' docs/plans/round2/STATUS
git add docs/plans/round2/STATUS && git commit -m "STATUS: unattended through phase 5" -m "Docs: none, run state only" && git push origin feat/round2-fixes
```

Do not work on `feat/round2-fixes` locally while it runs.

## 6. Watch

```bash
git fetch -q origin && git show origin/feat/round2-fixes:docs/plans/round2/STATUS
git log --oneline origin/feat/round2-fixes | head -8
```

Healthy: a recent `lock=` and commits per step. `[PHASE n DONE]` means a phase finished. Silence
after a limit stop is normal; the next hourly tick resumes after the reset.

## 7. Answer a block

`next=blocked` and a `[BLOCKED]` line under Notifications in `HANDOFF.md`: write your answer under
"Owner answers", set `next=work` in `STATUS`, commit (with a `Docs:` line) and push.

## 8. After `[ROUND2 COMPLETE]`

The rest runs locally since 2026-10-29: [LOCAL_RUN.md](LOCAL_RUN.md) is the guide for the local agent. Run `LOCAL_VERIFY.md` on your machine, review its "Test changes to review" section, then decide the
merge.

## Stop switch

Set `autonomy=off` in `STATUS`, push, and disable the routine.
