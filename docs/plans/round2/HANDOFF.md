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

- round2-verifier (sonnet), D15 attack: runs `tests/unit/test_address_policy*.py`, tries to break it; verdict `.handoff/D15.verdict.md`; started 2026-10-27T15:41Z

## Next action

D15 implemented and wired (commits up to 'compose settings in CI, docs'): middleware, TrustedHost, builders check+pin, build_postgres_dsn, save-time check, CI env, docs. Full unit+golden run: only a flaky timing test (`test_groups_cost_is_linear_in_pairs`) failed under load, passes alone. Test changes: `tests/conftest.py` and `test_connector_schema.py` (TEST-CHANGE commits; add to LOCAL_VERIFY). Remaining: attack verdict, lead review of lane B/C diffs, LOCAL_VERIFY entries, add `NORM_ALLOWED_NETWORKS` test, ADR-014/env_id check, phase gate (full CI run, ponytail-review).

D15 lane B landed (25276ee + lint fix, lead review pending: `address_policy.py`, 114 tests pass; `NORM_ALLOWED_NETWORKS` has no test yet — add one). Parked `.handoff/D15.test_app_dsn_compose.py` fails ruff (E501 etc.); fix its lint when it moves to `tests/unit/` with the wiring. Lead now wires app.py/clone_executor.py/routes.py.

D15 derive done (9a60857, d0bd76f; 140 of 153 checks fail today as intended; run with `--import-mode=importlib`). Lane B module in flight. Lead then wires middleware, TrustedHost, builders, `build_postgres_dsn`, R14 setting (name to choose in ADR-022), per-use checks.

D15 lane C landed (d823ba8, WIP, lead review pending). Follow-ups for the lead: set `NORM_BIND_ADDR` and `NORM_SECRET_KEY` in `.github/workflows/ci-full.yml:151`, `gate.yml:115,195` and the compose-starting test fixtures (compose now fails without them); update README (~80, ~152) and ARCHITECTURE (~85, ~338, deployment text); check what reads `NORM_API_HOST` in `.env.example`. Then: derive result, address-policy module, middleware, builders.


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
