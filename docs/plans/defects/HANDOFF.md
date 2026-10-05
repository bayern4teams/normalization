# Defects D1-D12 handoff — the only memory that survives a session

Overwrite this file at every commit. A fresh session reads it first, then
[the plan](../DEFECTS_IMPLEMENTATION_PLAN.md). Git is the memory; a session's context is not.

**Lock:** 2026-10-05T06:23:28Z · **Autonomy:** unattended-through-phase-5 · **Last heartbeat:** 2026-10-05T06:23:28Z

(Lock/heartbeat protocol: plan §7. A session sets `Lock: <ISO time>`, pushes it, and refreshes it at
every commit; a lock older than 75 min is stale. `Autonomy` is `off`, `dryrun` (a tick only records
what works and exits) or `unattended-through-phase-N` (authorises the supervisor to chain phases).
Only the user changes it.)

**Branch:** `feat/defects-fixes` · **Current phase:** 0 (not started; `Next action` below)

| item | phase | state | commit | lead verdict |
|---|---|---|---|---|
| D1 | 1 | todo | | |
| D12 | 1 | todo | | |
| D7 | 1 | todo | | |
| D8 | 1 | todo | | |
| D9 | 1 | todo | | |
| D5 | 2 | todo | | |
| D3 | 2 | todo | | |
| D10 | 2 | todo | | |
| D11 | 2 | todo | | |
| D6 | 3 | todo | | |
| D2 | 3 | todo | | |
| D4 | 3 | todo | | |

States: `todo` · `in-progress` · `accepted-cloud` (lead accepted, cloud-verifiable parts proven)
· `unverified-live` (accepted but needs the real environment — see LOCAL_VERIFY.md) · `blocked`.

## Locked file-ownership table (Phase 0)
(filled by Phase 0 from `graphify affected`)

## Lane plan
(filled by Phase 0)

## Next action
Phase 0, step 1 (plan §8). The branch holds only the kit; no feature code yet. (Runs only while `Autonomy` is `unattended-through-phase-N`.)

## Notifications
(append `[PHASE n DONE]`, `[BLOCKED]`, `[Defects D1-D12 COMPLETE]` entries here; the same prefixes go in commit messages)

## Open escalations (worker/verifier results that passed only written tests or one case)
none
