# ADR-017: Connection Credentials

## Status
Accepted — 2026-08-26. Built and live-verified in M15
(`docs/verification/M15-verification-pack.md`, commit `7374055`).

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

## Decision (as built, M15)

- Credentials are accepted via `POST /normalization/connections` and
  `POST /normalization/connections/test`, and encrypted at rest in
  Postgres using **AES-256-GCM** (`packages/normapi/src/normapi/
  secrets.py`, via the `cryptography` package — chosen over Fernet
  because Fernet is itself a thin wrapper around AES-CBC+HMAC with no
  real advantage here, and `cryptography` is already the de facto
  standard, audited Python crypto library). The key comes from
  `NORM_SECRET_KEY` (base64, must decode to exactly 32 bytes). A fresh
  random 12-byte nonce is generated per `encrypt()` call
  (`secrets.token_bytes`); the stored value is `base64(nonce ||
  ciphertext+tag)`, one column, no separate nonce column needed.
- `normapi.app.create_app()` **refuses to boot** if `NORM_SECRET_KEY` is
  unset while real connection rows already exist in Postgres — a stale
  or missing key would otherwise make every existing connection silently
  unusable (`DecryptionError` on first real use) instead of a clear,
  immediate startup failure. Booting with no key when the table is
  genuinely empty is the normal "feature unused" case, not an error.
- No `GET` endpoint ever returns a password field — `ConnectionResponse`
  (`normapi/schemas.py`) has no password field in its schema at all
  (absent, not present-as-null), so no serialization path can leak it.
- `POST /connections` and `/connections/test` both live-probe the target
  database before persisting/reporting success; on failure the error
  message is scrubbed of the plaintext password before it's returned
  (`_scrub()` in `routes.py`, defense in depth against a driver-level
  exception that happens to embed a DSN).
- Live-verified (§3.3 of the M15 pack) that the plaintext password never
  appears in an HTTP response, a captured OTel span, or Python logging
  output across the full create-connection request cycle. Honest caveat
  recorded there too: this project's HTTP layer has no FastAPI
  auto-instrumentation wired in today, so the OTel-span check currently
  proves "nothing leaked into the spans that exist" — if FastAPI
  instrumentation is added in a later milestone, this check should be
  revisited for whether a new span attribute starts capturing request
  bodies.
- Connection identity for mapping/watermark keying (decision 4 of the
  M13-M22 program) is `blake3(kind|host|port|database)`
  (`normapi.connections.connection_identity`), independent of credentials
  and independent of the user-chosen alias.
- `packages/normapi/src/normapi/sources.py`'s module docstring was
  rewritten in M15 to state the real, current policy: file-configured
  sources stay eager (JSON, server-side only); DB-configured connections
  build lazily into a pool keyed by `(connection_id, database)`, with
  `refresh()` invalidating stale cached connectors after a credential
  change or deletion. Neither path accepts a raw DSN from a request body
  — DB-configured connections resolve through `ConnectionResolver`
  (Postgres + `CredentialCipher`), never a client-supplied connection
  string.
