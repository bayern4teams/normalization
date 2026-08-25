# ADR-017: Connection Credentials (Stub)

## Status
Draft — 2026-08-26. Placeholder created during M13 ledger catch-up;
the real decision is made and this ADR filled in during M15.

## Context

ADR-013 established that `SourceConnector` implementations never accept
DSNs/credentials from a client request — `packages/normapi/src/normapi/
sources.py`'s module docstring states this explicitly: connections are
server-side config only, read from `NORM_SOURCES_CONFIG_PATH`, a JSON file
populated at process startup. That was a deliberate trust boundary, not an
oversight.

The M13–M22 program (`docs/plan/M13-M22-program-plan.md`) requires reversing
this: users enter host/port/username/password directly into the UI to
connect a database interactively. This ADR exists to record *why* that
reversal is acceptable and *what compensating controls* replace the boundary
being removed — not to silently contradict ADR-013 without an on-the-record
decision.

## Decision (to be filled in M15)

Placeholder scope, confirmed with the user during M13-M22 planning:

- Credentials are accepted via `POST /normalization/connections` and
  encrypted at rest in Postgres using a key from `NORM_SECRET_KEY`
  (AES-GCM or Fernet — final choice made in M15).
- No `GET` endpoint ever returns a password field, not even masked —
  the field is absent from the response schema entirely.
- `POST /normalization/connections/test` — the one endpoint that must
  necessarily receive a plaintext password in its request body — gets
  explicit span-attribute and access-log scrubbing (M12 wired real OTel
  spans into the live app; this route needs a redaction rule same as the
  general "never log a raw normalized value" pattern §123 already covers
  for PII).
- `packages/normapi/src/normapi/sources.py`'s module docstring is rewritten
  in M15 to state the real, current policy — this repo's convention is
  disclosed boundaries, not silently stale claims.

This ADR is Draft, not Accepted, until M15 actually ships and the real
implementation (module, migration, live-verified encryption round-trip) can
be cited here as evidence, matching every other ADR's pattern of documenting
a decision that is actually built, not merely intended.
