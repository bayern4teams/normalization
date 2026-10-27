# Round 2 handoff — the only memory that survives a session

Update this file at every commit. A working session reads [STATUS](STATUS) and this file first, then
[the plan](../ROUND2_IMPLEMENTATION_PLAN.md). Git is the memory; a session's context is not.

`STATUS` alone holds `autonomy`, `next` and `lock` (plan §7.1). Only the owner changes `autonomy`.
A session sets `lock=<ISO time>`, pushes it, and refreshes it with every commit; a lock older than 75
minutes is stale.

**Branch:** `feat/round2-fixes` · **Current phase:** 0 (baseline done; ownership locked; Phase 1 next)

| item | phase | state | commit | lead verdict |
|---|---|---|---|---|
| D15 | 1 | todo | | |
| D14 | 2 | todo | | |
| D13 | 3 | todo | | |
| U1 | 4 | todo | | |

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

(plan §7.3: before spawning an agent the lead adds one line here: agent, task, files, progress file,
time; it removes the line when the agent's result is recorded)

none

## Next action

Phase 1 (D15): ADR-022 first, then derive step (round2-verifier, model sonnet) for D15.

## Notifications

[DRYRUN DONE] 2026-10-27T15:03Z, see .handoff/supervisor_dryrun.txt

(append `[PHASE n DONE]`, `[BLOCKED]` and `[ROUND2 COMPLETE]` entries; the same prefixes go in commit
messages)

## Owner answers

(the owner answers a `[BLOCKED]` here, then sets `next=work` in STATUS)

## Open escalations

(results that passed only written tests or one case, and findings outside round 2's scope)

none
