"""The `--profile demo` / `--source demo_pg` names `.github/workflows/gate.yml`'s
`determinism-replay` job has invoked since M13-M22 was drafted
(`normcli run --profile demo --source demo_pg --out ./out/run1`), but
which never resolved to anything: there is no file/directory-based
profile-loading mechanism anywhere in the codebase, and "demo_pg" was
purely a string gate.yml happened to pass, never a name any Python code
looked up (confirmed by the 2026-08-29 throughput R&D pass's research
agent — see its report). This module is the real, first definition of
both names, deliberately hardcoded to match the two things they already
denote elsewhere in the repo:

- "demo" mirrors the existing hardcoded-profile precedent
  (`tests/integration/fixtures/run_passthrough_demo.py`'s `FIXED_PROFILE`,
  `tests/integration/test_stream_column.py`'s `_profile()`) — a fixed,
  non-time-based `NormalizationProfile`, here covering `demo-postgres`'s
  real `customers` table (`tests/integration/fixtures/postgres-init/01-init.sql`).
- "demo_pg" resolves to the `demo-postgres` compose service
  (`compose.yaml`'s `profiles: ["integration"]` service, port 5434,
  database `source_demo`, the genuinely-restricted `readonly_user` role
  provisioned by that same init script).

A second pair, "origin1_companies" / "origin1_pg" (Phase 3 item 4 of the
throughput/memory program, 2026-08-29), was added specifically because
the 3-row demo table above is too small to exercise anything about
process-pool parallelism (Phase 3 item 1) — pool calibration samples up
to `200 * workers` values, so 3 rows can never leave the pool's
"undecided" first-chunk calibration branch. "origin1_pg" is a REAL
3,940-row dataset (`companies`, mirrored from the same live ClickHouse
`origin1` database this program's `origin2` measurements came from, via
a real Postgres database at `localhost:55201/testorigin1`), with two
pool-eligible semantic types (`COMPANY_NAME` at ~721µs/value,
`PERSON_NAME` at ~1241µs/value — both above the ~200µs break-even) —
large enough for a real calibration decision and real concurrent
batches, small enough to run in seconds.

Extending this resolver for a second named pair, as this addition does,
is exactly what the module's own original docstring anticipated: "a
general profile-file-loading format was explicitly out of scope... this
resolver is the natural next step if more named profiles/sources are
needed later." Not a general loader still — just two more hardcoded
names, same shape as the first pair.
"""

from __future__ import annotations

import os

from normcore import FieldNormalizationConfig, FieldSemanticType, NormalizationProfile

# Matches compose.yaml's demo-postgres service (port 5434, db source_demo)
# and tests/integration/fixtures/postgres-init/01-init.sql's readonly_user
# grant — overridable for a non-default port/host without editing code.
DEMO_PG_DSN_ENV_VAR = "NORM_DEMO_PG_DSN"
_DEFAULT_DEMO_PG_DSN = "postgresql://readonly_user:readonly_pass@localhost:5434/source_demo"

DEMO_SOURCE_ID = "demo_pg"
DEMO_TABLE = "customers"

DEMO_PROFILE = NormalizationProfile(
    id="demo",
    name="demo",
    version="v1",
    # Fixed, not datetime.now() — same reproducibility requirement as
    # run_passthrough_demo.py's FIXED_PROFILE (ADR-014: same input + same
    # profile + same env_id must produce the same output; a profile whose
    # own timestamp changes every construction would defeat that before
    # normalization even starts).
    created_at="2026-01-01T00:00:00Z",
    updated_at="2026-01-01T00:00:00Z",
    created_by="normcli",
    field_configs=(
        FieldNormalizationConfig(
            field_ref=f"{DEMO_SOURCE_ID}.{DEMO_TABLE}.first_name",
            semantic_type=FieldSemanticType.GIVEN_NAME,
        ),
        FieldNormalizationConfig(
            field_ref=f"{DEMO_SOURCE_ID}.{DEMO_TABLE}.last_name",
            semantic_type=FieldSemanticType.FAMILY_NAME,
        ),
        FieldNormalizationConfig(
            field_ref=f"{DEMO_SOURCE_ID}.{DEMO_TABLE}.email",
            semantic_type=FieldSemanticType.EMAIL,
        ),
    ),
)

# Phase 3 item 4: a real ~3,940-row Postgres table, large enough to
# exercise process-pool calibration for real — see this module's
# docstring. Overridable the same way DEMO_PG_DSN_ENV_VAR is, for a
# non-default host/port without editing code.
ORIGIN1_PG_DSN_ENV_VAR = "NORM_ORIGIN1_PG_DSN"
_DEFAULT_ORIGIN1_PG_DSN = "postgresql://postgres:pass@localhost:55201/testorigin1"

ORIGIN1_SOURCE_ID = "origin1_pg"
ORIGIN1_TABLE = "companies"

ORIGIN1_PROFILE = NormalizationProfile(
    id="origin1-companies",
    name="origin1-companies",
    version="v1",
    created_at="2026-01-01T00:00:00Z",
    updated_at="2026-01-01T00:00:00Z",
    created_by="normcli",
    field_configs=(
        # 2,679 distinct of 3,940 rows — well above the pool's ~200µs
        # break-even for COMPANY_NAME (~721µs/value measured, Phase 3
        # item 1's live verification).
        FieldNormalizationConfig(
            field_ref=f"{ORIGIN1_SOURCE_ID}.{ORIGIN1_TABLE}.entity_name",
            semantic_type=FieldSemanticType.COMPANY_NAME,
        ),
        # Sparse (197 of 3,940 non-null) but real — PERSON_NAME is the
        # program's most expensive commonly-pooled type (~1241µs/value),
        # and a sparse column is itself a real shape worth proving
        # determinism against (most values null, computed once via
        # `Dispatcher.normalize(None, ...)`, never touching the pool at
        # all — see `DistinctValuePlanner.normalize_values`).
        FieldNormalizationConfig(
            field_ref=f"{ORIGIN1_SOURCE_ID}.{ORIGIN1_TABLE}.ceo_name",
            semantic_type=FieldSemanticType.PERSON_NAME,
        ),
    ),
)


class UnknownProfileError(ValueError):
    pass


class UnknownSourceError(ValueError):
    pass


_PROFILES = {"demo": DEMO_PROFILE, "origin1-companies": ORIGIN1_PROFILE}
_SOURCE_DSN_ENV_VARS = {
    DEMO_SOURCE_ID: (DEMO_PG_DSN_ENV_VAR, _DEFAULT_DEMO_PG_DSN),
    ORIGIN1_SOURCE_ID: (ORIGIN1_PG_DSN_ENV_VAR, _DEFAULT_ORIGIN1_PG_DSN),
}


def resolve_profile(name: str) -> NormalizationProfile:
    profile = _PROFILES.get(name)
    if profile is None:
        msg = (
            f"Unknown profile {name!r} — only {sorted(_PROFILES)} are defined today "
            "(see demo_fixture.py)"
        )
        raise UnknownProfileError(msg)
    return profile


def resolve_source_dsn(name: str) -> str:
    entry = _SOURCE_DSN_ENV_VARS.get(name)
    if entry is None:
        msg = (
            f"Unknown source {name!r} — only {sorted(_SOURCE_DSN_ENV_VARS)} are defined today "
            "(see demo_fixture.py)"
        )
        raise UnknownSourceError(msg)
    env_var, default_dsn = entry
    return os.environ.get(env_var, default_dsn)
