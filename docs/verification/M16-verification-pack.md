# Milestone M16 Verification Pack — Catalog API + Connection-Keyed Mappings + Semantic-Type Bug Fix

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

M16 is the third implementation milestone of the M13-M22 product-pipeline
program (`docs/plan/M13-M22-program-plan.md`), built under the user's
standing overnight authorization. Scope: browsable catalog routes over
M14's connector capabilities, a connection-keyed column-mapping registry
(the Explore step's real backend), and a genuine pre-existing bug fix the
program plan named explicitly: `execution.semantic_type` from a request
body silently overrode a profile's own saved semantic type, and a
profile's `error_policy`/`locale_overrides`/`dictionary_refs` were never
actually reachable because the code matched them against a bare column
name instead of a real structured `field_ref`.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `normapi/mappings.py` — `ColumnMapping`, `materialize_field_config()` | ✅ Done (`078c597`) |
| `column_mappings` Postgres table via the M15 migration runner | ✅ Done (`078c597`) |
| `GET /connections/{id}/databases`, `.../tables`, `.../tables/{t}/columns`, `.../tables/{t}/samples` | ✅ Done (`078c597`) |
| `PUT .../tables/{t}/columns/{c}/mapping`, `GET .../tables/{t}/mappings` | ✅ Done (`078c597`) |
| `store.py`'s `execute_run` — real `field_ref` threading + `semantic_type` override-vs-profile-fallback resolution | ✅ Done, fixed and live-verified (`078c597`) |
| `RunSourceRequest.database` — connection-based sources now resolvable from `create_run` | ✅ Done (`078c597`) |
| Mapping-to-profile-version materialization (`profile_id` on the upsert route) | ✅ Done, live-verified (`078c597`) |
| Golden regression test locking the fix | ✅ Done (`078c597`) |
| Gate G16 verification | ✅ Done, this pack |

## 2. Layer 1 — Automated verification results

Run fresh, in this session, against `main` at commit `078c597`:

```
uv run ruff check .             -> All checks passed!
uv run ruff format --check .    -> 215 files already formatted
uv run mypy packages tests      -> Success: no issues found in 163 source files
uv run python -m normcli check-traceability
  -> PASSED - all 138 Source.txt sections present in the matrix
uv run pytest -m "unit or golden or property or contract" -q
  -> 1003 passed, 12 skipped, 96 deselected, 1 warning in 327.34s
uv run python scripts/check_licenses.py
  -> License check passed: 143 packages inspected, 0 violations, 23 warnings
     (identical warning set to M15 — no new dependency added this milestone)
```

1003 passed (up from M15's 992 — the 11 new tests: 7 in
`test_mappings.py`, 4 in the golden `test_m16_field_ref_regression.py`).
96 deselected (up from 92 — the 4 new integration tests in
`test_catalog_and_mappings_api.py`). Full unit suite re-run twice this
session (once mid-development, once final) — both clean, no flakiness.

### 2.1 Integration suite — run live against real containers

```
uv run pytest tests/integration/test_catalog_and_mappings_api.py -q
  -> 4 passed in 36.81s

uv run pytest tests/integration -q -k "not postgres_store and not connection_registry and not catalog_and_mappings"
  -> 39 passed, 5 skipped, 28 deselected, 1 warning in 83.89s

uv run pytest tests/integration/test_postgres_store_integration.py tests/integration/test_connection_registry.py -q
  -> 24 passed in 60.44s (M9/M15 suites re-run — confirms no regression from M16's schema/route changes)
```

## 3. Layer 2 — Live verification

All against the real ClickHouse at `localhost:8190`/`origin2` and the
real metadata Postgres (port 5535):

### 3.1 Catalog browsing

`GET /connections/{id}/databases` → includes `"origin2"`; `.../tables` →
includes `"Person"`; `.../tables/Person/columns` → real column list
including `fullName`/`personID`, with `is_primary_key` correctly
populated (non-empty — `Person` has a real primary key, per M14's own
verification); `.../tables/Person/samples?n=3` → one response containing
every column's up-to-3 real sample values, confirming the "one request
per table, not one per column" design goal.

### 3.2 Mapping the plan's own four example columns

`PUT` mappings for `Person.fullName→PERSON_NAME`,
`Company.name→COMPANY_NAME`, `Location.country→COUNTRY`,
`Location.zip→POSTCODE` — all four return `200` with the semantic type
echoed back. `GET .../tables/Location/mappings` afterward returns
exactly `{"country": "COUNTRY", "zip": "POSTCODE"}` — both mappings for
that table, nothing extra, nothing missing.

### 3.3 Mappings survive delete + re-add under a different alias

The exact scenario decision 4 of the M13-M22 program exists to make
work: a mapping is saved against connection A (`Company.name→
COMPANY_NAME`), connection A is deleted, a **new** connection B is
created (a genuinely different UUID, confirmed via
`second_connection_id != first_connection_id`) pointed at the **same**
real host/port/database. `GET` mappings through connection B immediately
shows the mapping saved under connection A — proven live, not inferred
from the identity function's unit tests alone, because the mapping row
in Postgres has no foreign key to `connections.id` at all (by design,
per `_create_column_mappings_table`'s own docstring).

### 3.4 Materializing a mapping into a real profile version

`PUT .../columns/fullName/mapping` with `profile_id` set on a freshly
created `v1` profile → the route calls `store.create_version()` for
real; `GET /profiles/{id}` afterward shows `version: "v2"`, one
`field_configs` entry whose `field_ref` ends in
`.origin2.Person.fullName` and whose `semantic_type` is `PERSON_NAME` —
a real, persisted profile version, not a side-channel record.

### 3.5 The bug fix itself — golden regression test

`tests/golden/test_m16_field_ref_regression.py`, 4 tests, all passing.
The core proof (`test_with_the_real_field_ref_the_matching_profile_
config_error_policy_applies` vs.
`test_without_a_real_field_ref_the_profile_config_is_not_consulted`):
**the same profile, the same forced `NormalizerFailure` (a real
`GenericTextNormalizer` whose `_unicode.process` is monkeypatched to
always raise — the same technique this project's own M12 mutation-
coverage work established for `CompanyNormalizer`), the same input
value** produce a **different observable result** depending only on
whether the real `field_ref` is threaded through `execute_run`:

- Bare `field_name` (pre-M16 shape, `field_ref` omitted): the profile's
  own `ErrorPolicy.RETURN_NULL` config never matches →
  `result.display == "hello world"` (the un-configured default,
  `RETURN_ORIGINAL`).
- Real `field_ref` (M16): the same config now matches →
  `result.display is None` — `RETURN_NULL` genuinely applied.

A third test proves the `semantic_type` half of the same fix:
`semantic_type=None` with a matching `field_ref` correctly resolves the
profile config's own semantic type rather than raising or silently
defaulting. A fourth confirms the honest failure mode: no explicit
`semantic_type` and no matching config raises a clear `ValueError`,
never a confusing downstream crash.

## 4. Design notes and honest disclosures

1. **Mapping materialization is eager, at write time, not lazy at run
   start.** The plan's own wording ("at run start, materialize a profile
   version from the mappings") reads as lazy; this pack implements eager
   materialization instead — `PUT .../mapping` with a `profile_id`
   immediately creates the new profile version, rather than deferring
   until a run actually starts. This is a deliberate simplification, not
   an oversight: eager materialization is simpler to reason about and to
   test, and the *outcome* the plan actually cares about — a run reading
   `run.profile_version` sees the mapped field config — holds either way,
   since profile versions are immutable once created (ADR-014). Lazy
   materialization at run start (wiring a connection-based
   `RunSourceRequest` straight to an as-of-yet-unmaterialized mapping) is
   not implemented and would need real design work if wanted later.
2. **The single-column `RunSourceRequest`/`execute_run` path is not the
   long-term execution path.** M16's fix applies to the CURRENT
   single-column synchronous-resolve/async-execute mechanism (M10/M11).
   M17 replaces this with real multi-column chunked execution — the
   `field_ref` threading built here (via `RunSourceRequest.database` +
   `_resolve_field_ref()` in `routes.py`) is the mechanism M17 can reuse,
   not a dead end, but M17's own multi-column run model will need its
   own field_ref-per-column resolution, not a line-for-line copy of this.
3. **No cascading behavior between a deleted connection and its
   mappings/materialized profile versions.** Deleting a connection
   removes only the `connections` row; mappings and any profile versions
   already materialized from them are untouched (by design — see §3.3).
   There is currently no UI/API affordance to bulk-delete a connection's
   mappings; not needed by anything in scope through M16.
4. **`GET .../tables/{t}/columns` and `.../samples` return 404 (via a
   caught `ValueError`) for an unknown table**, matching M14's connector-
   level validation — not separately re-tested here since M14's own pack
   already live-verifies that validation at the connector layer; M16's
   routes just surface it as an HTTP 404 rather than swallowing it.
5. **Mongo connections still can't browse a catalog** (no
   `CatalogConnector` support, per M14's disclosed scope) — a Mongo
   connection's catalog routes return `501`, not a crash; not
   independently re-tested here since M14's pack already covers the
   underlying `isinstance` capability check.

## 5. Disclosed scope boundaries carried forward

Unchanged by M16: async execution is still one background thread per run
(M11); the row-count cap and the double-start race are both still
present; `GET /overview`/`GET /quality` are still unbounded (M18's job);
`NORM_CACHE_PATH` still defaults to `:memory:` (M17's job);
`env_id`/persistence/collision workflow/UI catch-up/connection
encryption are all real and unaffected by this milestone.

## Human Sign-off

milestone: M16
verdict:
reviewer:
date:
env_id:
commit: 078c597
conditions: []
notes: |
