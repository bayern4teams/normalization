# Defects D1-D12 handoff — the only memory that survives a session

Overwrite this file at every commit. A fresh session reads it first, then
[the plan](../DEFECTS_IMPLEMENTATION_PLAN.md). Git is the memory; a session's context is not.

**Lock:** 2026-10-05T14:16:54Z · **Autonomy:** unattended-through-phase-5 · **Last heartbeat:** 2026-10-05T14:16:54Z

(Lock/heartbeat protocol: plan §7. A session sets `Lock: <ISO time>`, pushes it, and refreshes it at
every commit; a lock older than 75 min is stale. `Autonomy` is `off`, `dryrun` (a tick only records
what works and exits) or `unattended-through-phase-N` (authorises the supervisor to chain phases).
Only the user changes it.)

**Branch:** `feat/defects-fixes` · **Current phase:** 1

| item | phase | state | commit | lead verdict |
|---|---|---|---|---|
| D1 | 1 | unverified-live | this commit | ACCEPT after round 2: verifier REJECTed blank verdict (NULLs cell) and lone-surrogate queue crash; both fixed, 52 acceptance tests green; Postgres DDL/ON CONFLICT live-only |
| D12 | 1 | accepted-cloud | this commit | ACCEPT: kept, one producer (verdict re-normalizes differently -> NEEDS_REVIEW), tested in test_adjudication_acceptance.py; severity order unchanged |
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
Phase 1. Lane A (lead): D1 implemented as WIP (a2b5e59, ADR-018); verifier `D1` (derive+attack) writes
`tests/unit/test_adjudication_acceptance.py`, `.handoff/D1.verdict.md`; lead then decides. D12: kept with one
producer (ADR-018: adjudicated value that re-normalizes differently -> NEEDS_REVIEW); date.py note and data
contract updated. Lane B: D7 derive -> worker -> attack, then D8. Lane C: D9 derive -> worker -> attack.
Deviation (one line, plan §3.2/§4): D1 code was written before its derive verifier ran because both subagent
slots were on Phase 0 fixtures; the D1 verifier was told to write tests from the spec before reading the code.

## Notifications
(append `[PHASE n DONE]`, `[BLOCKED]`, `[Defects D1-D12 COMPLETE]` entries here; the same prefixes go in commit messages)
- [PHASE 0 DONE] 2026-10-05: baseline, re-verification, ownership, fixtures + BEFORE numbers (PHASE0_REPORT.md §4).
  Gate: ruff/format/mypy clean, CI pytest 1319 passed / 12 skipped, `ci-fast` green on 5a93696, ponytail-review: lean.

## Open escalations (worker/verifier results that passed only written tests or one case)
- **Outside D1-D12, for the user (Phase 0 fixtures):** (a) `03/2024` normalizes to `2024-03-03` — a day is
  invented from a month-year (violates "precision is preserved, never invented"); (b) `NA` in a COUNTRY column
  is read as NOT_APPLICABLE by the `missing-values.common` dictionary (40/40 Namibia rows), the never-guess
  defect D4's acceptance names; D4 only reports and will not change it; (c) `05/05/2024` abstains though both
  readings are the same date (over-abstain); (d) `\x00` passes into TEXT columns for 22 untyped types and
  Postgres rejects NUL. None is fixed in this plan (scope); each needs the user's go-ahead.
