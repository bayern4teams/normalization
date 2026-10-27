# Round 2 handoff — the only memory that survives a session

Update this file at every commit. A working session reads [STATUS](STATUS) and this file first, then
[the plan](../ROUND2_IMPLEMENTATION_PLAN.md). Git is the memory; a session's context is not.

`STATUS` alone holds `autonomy`, `next` and `lock` (plan §7.1). Only the owner changes `autonomy`.
A session sets `lock=<ISO time>`, pushes it, and refreshes it with every commit; a lock older than 75
minutes is stale.

**Branch:** `feat/round2-fixes` · **Current phase:** 2 (Phase 1 done)

| item | phase | state | commit | lead verdict |
|---|---|---|---|---|
| D15 | 1 | unverified-live | see git log | Lead: verifier REJECTed (`.handoff/D15.verdict.md`: compose env not passed, 3 wiring points untested, `://` in a password, `[::1]` Host). Lead fixed all four plus `--no-proxy-headers`, with `tests/unit/test_address_policy_wiring.py`. Known and recorded: `Host: localhost:80@evil.com` accepted (LOCAL_VERIFY). Accepted by the lead on the diff; live checks in LOCAL_VERIFY. |
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

- round2-verifier (sonnet), D14 derive: `.handoff/D14.test_*.py`, `.handoff/D14.acceptance.md`; progress `.handoff/D14.progress.md`; started 2026-10-27T16:04Z

## Next action

Phase 2 (D14, remove in-place mode): ADR-013 and ADR-017 amendments first, then derive step (round2-verifier, model sonnet) for D14, then lanes per plan §8. Remember §2.9: deleted tests need a `C5:` line (owner approval 2026-10-27, review 2027-01-27).

## Notifications

[DRYRUN DONE] 2026-10-27T15:03Z, see .handoff/supervisor_dryrun.txt

[PHASE 1 DONE] 2026-10-27. D15 `unverified-live` (see LOCAL_VERIFY.md). Gate, run in this session:
ruff check, ruff format --check, mypy: pass. pytest (unit or golden and not slow, capped): 3385 passed, 24 skipped, 1 xfailed.
Guards: check_c5_exceptions, check_test_assertions, check_root_files, check_gitignore_consistency, check_no_stubs,
check_docs_note, deptry, actionlint, markdownlint-cli2, check_mermaid: pass. gitleaks on `main..HEAD`: no leaks.
NOT run: Vale, lychee (docs.yml `style` and `links` jobs), zizmor (needs the GitHub API: "couldn't list tags"), and
the ci-full / gate.yml integration, e2e and mutation jobs (no Docker). GitHub: every run on the branch ends in 2 s
with one job and no steps (e.g. ci-fast run 40536779521): treated as the known billing refusal, recorded, not a block.
/ponytail-review of the phase diff: lean, no findings. Graphs refreshed.
Pre-existing, not this branch: `gitleaks git .` over full history reports 3 hits on the old committed
NORM_SECRET_KEY (commits already on main: da81a25, ab0846a, 364cbd3). See Open escalations.

(append `[PHASE n DONE]`, `[BLOCKED]` and `[ROUND2 COMPLETE]` entries; the same prefixes go in commit
messages)

## Owner answers

(the owner answers a `[BLOCKED]` here, then sets `next=work` in STATUS)

## Open escalations

(results that passed only written tests or one case, and findings outside round 2's scope)

- The `NORM_SECRET_KEY` that compose.yaml used to commit is in main's history and `gitleaks git .` flags it (guards.yml B6
  step is likely red on main too). Rotate it on any deployment that used it; whether to add a `.gitleaksignore` entry (a C5
  exception) is the owner's call. Not touched.
- D15: `Host: localhost:80@evil.com` is accepted by Starlette's TrustedHostMiddleware (it reads the part before the first `:`).
  Not exploitable without an allowed peer; listed in LOCAL_VERIFY.
- Vale and lychee not run in the cloud (see [PHASE 1 DONE]).
