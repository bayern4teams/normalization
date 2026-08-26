"""Connection registry domain model — M15 of the M13-M22 program
(docs/plan/M13-M22-program-plan.md), ADR-017.

A `ConnectionRecord` is one user-registered source database: enough to
reconnect (kind/host/port/username/database) plus an AES-GCM-encrypted
password (see normapi.secrets). Persistence lives in
`PostgresMetadataStore` (postgres_store.py), mirroring how profiles/runs/
collision decisions are already stored there — this module holds the pure
value objects and the one piece of real domain logic that doesn't belong
to persistence: `connection_identity()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import blake3
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from normapi.secrets import CredentialCipher

DEFAULT_PORTS: dict[str, int] = {
    "clickhouse": 8123,
    "postgres": 5432,
    "mysql": 3306,
    "mongo": 27017,
}

CONNECTION_KINDS = frozenset(DEFAULT_PORTS)


class UnknownConnectionKindError(ValueError):
    """Raised for a `kind` outside DEFAULT_PORTS — a 422 at the API
    boundary, not a 500."""


class ConnectionNotFoundError(LookupError):
    """Raised when a request references a connection id the registry
    doesn't have — a client-facing 404."""


def connection_identity(kind: str, host: str, port: int, database: str) -> str:
    """A stable identity for "this real database", independent of
    whatever alias a user gives the connection. Decision 4 of the
    M13-M22 program: column mappings (M16), the incremental watermark
    (M20), and the M19 destination self-write-refusal are all keyed by
    this — re-adding the same server under a new alias reuses saved
    config automatically, and a destination pointed at the real source
    server+database is caught by identity, not by name.

    `host` is lowercased and both `host`/`database` are stripped before
    hashing so "localhost" and "LOCALHOST " don't silently resolve to two
    different identities for what is really the same server.
    """
    canonical = f"{kind}|{host.strip().lower()}|{port}|{database.strip()}"
    return blake3.blake3(canonical.encode("utf-8")).hexdigest()


class ConnectionRecord(BaseModel):
    """The persisted shape — includes `encrypted_password`. Never handed
    directly to an API response; `normapi.schemas.ConnectionResponse` has
    no password field at all (absent, not null)."""

    model_config = ConfigDict(frozen=True)

    id: str
    alias: str
    kind: str
    host: str
    port: int
    username: str
    encrypted_password: str
    database: str
    identity: str
    created_at: str
    updated_at: str


@runtime_checkable
class ConnectionLookup(Protocol):
    """The one method `ConnectionResolver` needs from a metadata store —
    a structural Protocol rather than importing `PostgresMetadataStore`
    directly, since that module imports `ConnectionRecord` from here and
    a direct import back would be circular."""

    def get_connection(self, connection_id: str) -> ConnectionRecord | None: ...


@dataclass(frozen=True, slots=True)
class ResolvedConnection:
    """A connection's real, decrypted credentials — held only for the
    duration of building a live connector, never logged, never returned
    from any API response."""

    kind: str
    host: str
    port: int
    username: str
    password: str
    database: str


class ConnectionResolver:
    """Combines a Postgres-stored `ConnectionRecord` with the process's
    `CredentialCipher` to hand back real, decrypted credentials — the
    only place a stored password is ever decrypted."""

    def __init__(self, store: ConnectionLookup, cipher: CredentialCipher) -> None:
        self._store = store
        self._cipher = cipher

    def resolve(self, connection_id: str) -> ResolvedConnection:
        record = self._store.get_connection(connection_id)
        if record is None:
            raise ConnectionNotFoundError(connection_id)
        return ResolvedConnection(
            kind=record.kind,
            host=record.host,
            port=record.port,
            username=record.username,
            password=self._cipher.decrypt(record.encrypted_password),
            database=record.database,
        )

    def encrypt(self, plaintext_password: str) -> str:
        """The routes layer never touches a bare `CredentialCipher` —
        both directions of the encrypt/decrypt boundary go through this
        one object."""
        return self._cipher.encrypt(plaintext_password)
