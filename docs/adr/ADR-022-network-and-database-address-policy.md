# ADR-022: Network and Database-Address Policy — Local Network Only

## Status
Accepted — 2026-10-27. Implements `docs/improvement-report.md` D15 (owner decisions R9, R14-R17,
Q-B). Built in Phase 1 of round 2.

## Context

The API holds database passwords and can read and write databases. It listened on `0.0.0.0`,
every compose port bound every interface (Docker publishing bypasses a ufw rule), no code checked
the caller or the `Host` header, any database host was accepted, the Postgres DSN was an f-string,
and `compose.yaml` carried a fixed `NORM_SECRET_KEY`. A page in the owner's browser can also reach
a local service through DNS rebinding, which a source-address check does not stop.

## Decision

**One allowed set.** Loopback, RFC 1918, IPv6 unique local `fc00::/7`. Built from explicit
`ipaddress.ip_network` values named by their RFCs, never from `is_private`: its list changed
across Python versions and it calls documentation and benchmark ranges private. `100.64.0.0/10`
is refused unless the deployer setting adds it. A test with a fixed table of addresses, written
from the RFCs, guards the set.

**Callers.** An ASGI middleware refuses a peer outside the allowed set. `X-Forwarded-For` is
ignored: there is no proxy (R17). `TrustedHostMiddleware` checks the `Host` header against an
allowlist of host names, which is the DNS-rebinding defence.

**Database targets.** Literal addresses are parsed strictly (decimal, octal and hex IPv4 forms
refused, `::ffff:` unwrapped). A host name resolves, and every address must be allowed (R15). The
connection uses the checked address (libpq `hostaddr`; ClickHouse: the checked address as `host`
with the name in `server_host_name`). Unix-socket paths and multi-host strings are refused. The
check runs when a connection is saved and each time it is used. The Postgres DSN is built with
`psycopg.conninfo.make_conninfo`, never an f-string.

**Ports (Q-B).** The API port binds the host's private LAN address from `.env`. libpostal and
every database port bind `127.0.0.1`.

**Secrets.** `NORM_SECRET_KEY` leaves `compose.yaml`; compose reads it from an uncommitted `.env`.

## Limits

- Outbound internet is out of scope (R9): `NORM_OPENLINEAGE_URL` stays as it is.
- Pinning on ClickHouse is not proven against a real server; it is a local check
  (`docs/plans/round2/LOCAL_VERIFY.md`).
- Docker Engine before 28.0 and 28.3.3 leaked loopback-published ports to neighbouring hosts; the
  stack needs a current engine.

## Consequences

Callers outside the local network get a refusal. The Starlette test client reports its peer as
`testclient`, so tests give it an allowed address.
