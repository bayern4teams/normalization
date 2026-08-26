"""The self-write-refusal check — Source.txt decision 6 of the M13-M22
program (docs/plan/M13-M22-program-plan.md), M19.

Built and live-tested FIRST, before any other destination-writing code
in this package, per the user's own standing hard rule for this
milestone: "never configure or test the destination writer against a
connection identity matching the real source... build the self-write-
refusal (409 on identity match) FIRST, before any other destination-
writing code, so the safety check exists before the thing it guards
against does."

Two distinct refusals, matching the plan's own §M19 callout #3 ("the
refusal rule is too narrow — blocking only host+port+database equality
still permits writing into origin1 on the same server as origin2, the
realistic accident"):

1. Destination resolves to the EXACT same connection identity as the
   source (same kind+host+port+database) — always refused, no override
   possible. This is the literal self-write case decision 6's own "never
   never" emphasis names.
2. Destination is on the SAME server (host+port) as the source, just a
   different database — refused BY DEFAULT (the realistic accident:
   writing into `origin1` while reading from `origin2` on the same real
   ClickHouse server), unless the caller explicitly passes
   `i_understand_same_server=True`.

Pure functions, no I/O, no dependency on `normio`/`normapi` — this module
takes plain strings (identities already computed by whatever connection
registry the caller uses, e.g. `normapi.connections.connection_identity`)
so it can be unit- and live-tested in complete isolation from any real
connector or database, and so `normsink` never needs to depend on
`normapi` (the wrong dependency direction — `normapi` depends on
`normsink`, not the reverse).
"""

from __future__ import annotations


class SelfWriteRefusedError(RuntimeError):
    """Raised when a proposed destination would write normalized data
    back onto (or dangerously near) the real source it came from. Callers
    (normapi's routes) translate this into an HTTP 409 — this exception
    itself carries no HTTP concept, staying a plain library error."""


def server_identity(host: str, port: int) -> str:
    """A comparable identity for "this real server", independent of
    which database on it — host lowercased/stripped, exact port, no
    hashing needed since this is only ever compared for equality within
    one process, never persisted or exposed. Mirrors
    `normapi.connections.connection_identity`'s own host-normalization
    convention (`host.strip().lower()`) so "localhost" and "LOCALHOST "
    are correctly recognized as the same server."""
    return f"{host.strip().lower()}:{port}"


def assert_destination_is_not_the_source(
    *,
    source_identity: str,
    destination_identity: str,
    source_host: str,
    source_port: int,
    destination_host: str,
    destination_port: int,
    i_understand_same_server: bool = False,
) -> None:
    """Raises `SelfWriteRefusedError` if `destination` would write onto
    (or dangerously near) `source`. Call this BEFORE constructing any
    destination connector or issuing any write — the check must exist
    before the thing it guards against runs, not alongside it.

    `source_identity`/`destination_identity`: each connection's real,
    already-computed identity (kind+host+port+database) — an exact match
    means the destination IS the source, refused unconditionally.

    `i_understand_same_server`: the ONLY way to write to a different
    database on the same physical server as the source — never bypasses
    the exact-identity refusal above, only the same-server-different-
    database one.
    """
    if destination_identity == source_identity:
        msg = (
            "Refusing to write: the destination resolves to the exact same "
            "connection (same kind, host, port, and database) as the source. "
            "Normalized data is never written back onto the source it came from."
        )
        raise SelfWriteRefusedError(msg)

    destination_server = server_identity(destination_host, destination_port)
    source_server = server_identity(source_host, source_port)
    if destination_server == source_server and not i_understand_same_server:
        msg = (
            "Refusing to write: the destination is on the SAME server "
            f"({destination_server}) as the source, just a different database. "
            "This is refused by default since it is the realistic accident this "
            "check exists to catch — pass i_understand_same_server=True to "
            "proceed deliberately."
        )
        raise SelfWriteRefusedError(msg)
