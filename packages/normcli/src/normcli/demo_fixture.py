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

Only these two names are recognized today — `run_cmd.py` raises a clear
error for anything else. A general profile-file-loading format was
explicitly out of scope for the throughput program this module was built
for; extending this resolver is the natural next step if more named
profiles/sources are needed later.
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


class UnknownProfileError(ValueError):
    pass


class UnknownSourceError(ValueError):
    pass


def resolve_profile(name: str) -> NormalizationProfile:
    if name != "demo":
        msg = f"Unknown profile {name!r} — only 'demo' is defined today (see demo_fixture.py)"
        raise UnknownProfileError(msg)
    return DEMO_PROFILE


def resolve_source_dsn(name: str) -> str:
    if name != DEMO_SOURCE_ID:
        msg = f"Unknown source {name!r} — only 'demo_pg' is defined today (see demo_fixture.py)"
        raise UnknownSourceError(msg)
    return os.environ.get(DEMO_PG_DSN_ENV_VAR, _DEFAULT_DEMO_PG_DSN)
