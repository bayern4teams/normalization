# Launch guide — Defects D1-D12 (Reza-Sh83/normalization)

Do these in order. Each step says what to check and what to send back.

## 0. Preconditions
`git pull --ff-only` on `feat/defects-fixes`; CI on `feat/defects-fixes` is green.

## 1. Put the kit on `main` (needs the user's explicit OK)
A routine always clones `main` and skills/agents/`.mcp.json`/`scripts/cloud_setup.sh` load at session
start, so they must be on `main`. The kit is: `docs/plans/DEFECTS_IMPLEMENTATION_PLAN.md`, `docs/plans/defects/` (HANDOFF, LOCAL_VERIFY,
SUPERVISOR, LAUNCH), `.claude/agents/defects-worker.md`, `.claude/agents/defects-verifier.md`,
`.claude/skills/ponytail*` (+ license), `scripts/cloud_setup.sh`, `scripts/refresh_graphs.py`,
`tests/unit/test_refresh_graphs.py`, and the pointer lines in `AGENTS.md`/`CLAUDE.md` and `README.md`.
(`.mcp.json` already carries `codebase-memory-mcp`; it is unchanged.) It contains no feature code.
```bash
git checkout main && git merge --ff-only feat/defects-fixes && git push origin main && git checkout feat/defects-fixes
```
(If `main` has moved and a fast-forward is impossible, stop and ask.)

## 2. Cloud environment
claude.ai/code -> create a NEW environment `defects-env` (so other cloud work is unaffected),
Network access Full, and paste `phase-kit/templates/environment_setup.sh` (verbatim) as its setup script.

## 3. Routine (create it in the claude.ai Routines UI, not from inside a session)
| Field | Value |
|---|---|
| Repository | Reza-Sh83/normalization |
| Environment | `defects-env` |
| Model / effort | Opus 5.5, high |
| Trigger | every hour (cron `0 * * * *`) |
| Connector | GitHub |
| Instructions | the pointer below |

```
You are the Defects D1-D12 supervisor tick. Run: git fetch origin feat/defects-fixes, then read
docs/plans/defects/SUPERVISOR.md with: git show origin/feat/defects-fixes:docs/plans/defects/SUPERVISOR.md
Follow the LAST fenced block in that file exactly. Do nothing else.
```
If the UI offers a push-permission option, allow pushes to non-`claude/` branches.

## 4. Dry run
```bash
sed -i 's/\*\*Autonomy:\*\* off/**Autonomy:** dryrun/' docs/plans/defects/HANDOFF.md
git add docs/plans/defects/HANDOFF.md && git commit -m "handoff: Autonomy dryrun" && git push origin feat/defects-fixes
```
Run the routine once (run-now), wait a few minutes, then:
```bash
git pull --ff-only && tail -1 .handoff/supervisor_dryrun.txt
```
All must be yes: setup log ends cleanly and the three graph tools are on PATH at session start, the six
Ponytail skills load, codebase-memory MCP tools present (or its CLI works), `git push` and `gh run list`
work. Send the line back if anything fails; the line also records the setup log.

## 5. Go live
```bash
git pull --ff-only
sed -i 's/\*\*Autonomy:\*\* dryrun/**Autonomy:** unattended-through-phase-5/' docs/plans/defects/HANDOFF.md
git add docs/plans/defects/HANDOFF.md && git commit -m "handoff: unattended" && git push origin feat/defects-fixes
```
Do not work on `feat/defects-fixes` locally while it runs.

## 6. Watch
```bash
git fetch origin && git log --oneline origin/feat/defects-fixes | head -8
git show origin/feat/defects-fixes:docs/plans/defects/HANDOFF.md | sed -n 1,10p
```
Healthy: a recent `Lock:` and commits per item. `[PHASE n DONE]` = a phase finished. Act only on
`[BLOCKED]`. Silence after a limit stop is normal; the next hourly tick resumes after the reset.

## Stop switch
Set `Autonomy: off` in HANDOFF.md, push, and disable the routine.
