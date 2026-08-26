"""Unit tests for normapi.connections (M15) — connection_identity() and
ConnectionResolver's encrypt/resolve orchestration. No database needed;
ConnectionResolver is tested against a fake in-memory ConnectionLookup."""

from __future__ import annotations

import pytest
from normapi.connections import (
    DEFAULT_PORTS,
    ConnectionNotFoundError,
    ConnectionRecord,
    ConnectionResolver,
    connection_identity,
)
from normapi.secrets import CredentialCipher, generate_secret_key, load_secret_key


@pytest.mark.unit
class TestConnectionIdentity:
    def test_same_inputs_produce_the_same_identity(self) -> None:
        a = connection_identity("clickhouse", "localhost", 8190, "origin2")
        b = connection_identity("clickhouse", "localhost", 8190, "origin2")
        assert a == b

    def test_different_database_produces_a_different_identity(self) -> None:
        a = connection_identity("clickhouse", "localhost", 8190, "origin1")
        b = connection_identity("clickhouse", "localhost", 8190, "origin2")
        assert a != b

    def test_different_port_produces_a_different_identity(self) -> None:
        a = connection_identity("clickhouse", "localhost", 8190, "origin2")
        b = connection_identity("clickhouse", "localhost", 8191, "origin2")
        assert a != b

    def test_different_kind_produces_a_different_identity(self) -> None:
        a = connection_identity("clickhouse", "localhost", 8190, "origin2")
        b = connection_identity("postgres", "localhost", 8190, "origin2")
        assert a != b

    def test_host_case_and_whitespace_are_normalized(self) -> None:
        """A re-added connection typed with different capitalization or
        stray whitespace must still resolve to the SAME real database —
        this is what lets re-adding a server under a new alias reuse
        saved column mappings (decision 4 of the M13-M22 program)."""
        a = connection_identity("clickhouse", "localhost", 8190, "origin2")
        b = connection_identity("clickhouse", " LOCALHOST ", 8190, "origin2")
        assert a == b

    def test_database_whitespace_is_normalized(self) -> None:
        a = connection_identity("clickhouse", "localhost", 8190, "origin2")
        b = connection_identity("clickhouse", "localhost", 8190, " origin2 ")
        assert a == b

    def test_returns_a_64_char_hex_string(self) -> None:
        """blake3's default digest is 32 bytes = 64 hex chars."""
        identity = connection_identity("clickhouse", "localhost", 8190, "origin2")
        assert len(identity) == 64
        int(identity, 16)  # raises ValueError if not valid hex


@pytest.mark.unit
def test_default_ports_cover_every_supported_kind() -> None:
    assert DEFAULT_PORTS == {
        "clickhouse": 8123,
        "postgres": 5432,
        "mysql": 3306,
        "mongo": 27017,
    }


class _FakeConnectionLookup:
    """A minimal ConnectionLookup — structural typing means this doesn't
    need to inherit from anything, matching Protocol's whole point."""

    def __init__(self, records: dict[str, ConnectionRecord]) -> None:
        self._records = records

    def get_connection(self, connection_id: str) -> ConnectionRecord | None:
        return self._records.get(connection_id)


def _record(*, id_: str, encrypted_password: str) -> ConnectionRecord:
    return ConnectionRecord(
        id=id_,
        alias="my-clickhouse",
        kind="clickhouse",
        host="localhost",
        port=8190,
        username="default",
        encrypted_password=encrypted_password,
        database="origin2",
        identity=connection_identity("clickhouse", "localhost", 8190, "origin2"),
        created_at="2026-08-26T03:00:00Z",
        updated_at="2026-08-26T03:00:00Z",
    )


@pytest.mark.unit
class TestConnectionResolver:
    def test_resolve_returns_the_real_decrypted_password(self) -> None:
        cipher = CredentialCipher(load_secret_key(generate_secret_key()))
        encrypted = cipher.encrypt("real-password")
        lookup = _FakeConnectionLookup(
            {"conn-1": _record(id_="conn-1", encrypted_password=encrypted)}
        )
        resolver = ConnectionResolver(lookup, cipher)

        resolved = resolver.resolve("conn-1")

        assert resolved.password == "real-password"
        assert resolved.kind == "clickhouse"
        assert resolved.host == "localhost"
        assert resolved.port == 8190
        assert resolved.database == "origin2"

    def test_resolve_unknown_connection_id_raises(self) -> None:
        cipher = CredentialCipher(load_secret_key(generate_secret_key()))
        resolver = ConnectionResolver(_FakeConnectionLookup({}), cipher)
        with pytest.raises(ConnectionNotFoundError):
            resolver.resolve("does-not-exist")

    def test_encrypt_then_resolve_round_trips_through_the_resolver_itself(self) -> None:
        cipher = CredentialCipher(load_secret_key(generate_secret_key()))
        resolver = ConnectionResolver(_FakeConnectionLookup({}), cipher)
        encrypted = resolver.encrypt("another-real-password")
        # Simulate what create_connection's route does: encrypt via the
        # resolver, persist the record, later resolve it back.
        lookup = _FakeConnectionLookup(
            {"conn-2": _record(id_="conn-2", encrypted_password=encrypted)}
        )
        resolver2 = ConnectionResolver(lookup, cipher)
        assert resolver2.resolve("conn-2").password == "another-real-password"
