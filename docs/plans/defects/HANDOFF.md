# Defects D1-D12 handoff — the only memory that survives a session

Overwrite this file at every commit. A fresh session reads it first, then
[the plan](../DEFECTS_IMPLEMENTATION_PLAN.md). Git is the memory; a session's context is not.

**Lock:** 2026-10-05T09:20:45Z · **Autonomy:** unattended-through-phase-5 · **Last heartbeat:** 2026-10-05T09:20:45Z

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
Derived 2026-10-05 from `graphify affected <file>` and `graft callers <sym> --depth all` (shared symbols:
`_apply_column`, `_normalize_chunk` → only `clone_executor.py`; `make_cache_key` → `clone_executor.py`,
`normexec/planner.py`, `normexec/cache.py`, `normapi/store.py`; all normalizers are registered in one place,
`normapi/app.py:150-169` `_build_registry`-style block, `registry.register(IdentifierNormalizer())` at :162).

| file | owner (item) | note |
|---|---|---|
| `normapi/clone_executor.py`, `pg_persistence.py`, `routes.py`, `schemas.py`, `normapi/adjudication.py` (new), `normapi/lineage.py` (new) | lead: D1 → D5 → D3 (serial) | shared large files |
| `normcore/enums.py`, `normcore/dispatch.py`, `tests/unit/test_dispatch.py` | lead: D1/D12 | severity tuple; D7 must NOT add a status (plan §9 D7) |
| `normio/storage_types.py`, `normio/connectors/*_destination.py` | lead: D5 | |
| `normalizers/identifier.py`, `tests/unit/test_identifier_normalizer.py` | lane B: D7 → D8 | |
| `normapi/app.py` (registration only) | lane B: D8 | **flag:** only D8 needs it (a `CODE` normalizer registration); lead serialises if D1 needs it |
| `normalizers/url.py`, `tests/unit/test_url_normalizer.py` | lane C: D9 | |
| `normalizers/phone.py`, `tests/unit/test_phone_normalizer.py` | phase 2 lane B: D10 | |
| `normalizers/name.py`, `normalizers/_bmpm.py` (new) + data | phase 2 lane C: D11 | |
| `pyproject.toml`, `uv.lock`, `normexec/env_fingerprint.py`, `tests/unit/test_env_fingerprint.py` | D9 (ph 1) → D11 (ph 2) → D4 (ph 3) | **flag:** three items, three phases; never concurrent |
| `normanalysis/gold.py`, `tests/gold/`, `normcli/cli.py` | D6 → D2 (ph 3, serial) | `cli.py` shared by D6 and D2 |
| `normanalysis/disguised_missing.py` (new), `normanalysis/type_detection.py` (hook) | D4 (ph 3) | `type_detection` feeds `clone_executor`/`routes` — hook must not change column results |
| `tests/unit/test_clone_*.py`, `tests/golden/` | lead | **flag:** normalizer output changes (D8, D9, D10, D11) can move clone/golden expectations; a worker that needs one asks the lead |
| `tests/defects/` | verifier (Phase 0 fixtures) | read-only to workers |
| `docs/adr/ADR-018..020`, `docs/` | lead | |

## Lane plan
- Phase 1: lane A lead D1 → D12; lane B worker D7 → D8 (`identifier.py`, `app.py`); lane C worker D9
  (`url.py`, deps). At most 2 subagents at once: D7 and D9 workers run while the lead does D1.
- Phase 2: lane A lead D5 → D3; lane B worker D10; lane C worker D11.
- Phase 3: worker D6 → lead D2; worker D4.

## Next action
Phase 0, step 4 (plan §8): two verifiers (P0-A scorer + phase-1 fixtures, P0-B phase-2/3 fixtures) build `tests/defects/`; then step 5 and the phase-0 gate. Steps 1-3 done (PHASE0_REPORT.md). Tick 09:17Z found the 06:26Z lock stale with steps 1-3 committed and no uncommitted work; resumed from step 4. graft was missing at start; `cloud_setup.sh` restored it (rc 0, 121 s).

## Notifications
(append `[PHASE n DONE]`, `[BLOCKED]`, `[Defects D1-D12 COMPLETE]` entries here; the same prefixes go in commit messages)

## Open escalations (worker/verifier results that passed only written tests or one case)
none
