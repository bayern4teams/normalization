"""Unit tests for M19's self-write-refusal check
(docs/plan/M13-M22-program-plan.md) — built and tested FIRST, before any
other destination-writing code in `normsink`, per the user's own standing
hard rule for this milestone.

Uses the REAL `normapi.connections.connection_identity` function (the
actual identity computation the live API will use) against the REAL
production source's real coordinates (`localhost:8190`, database
`origin2` — the exact values the user's hard rule names) to prove the
refusal fires for the literal scenario it exists to prevent. No real
connection is ever opened here — only identity strings are computed and
compared, which is exactly why this check can be fully proven before any
`DestinationConnector`/DDL/write code exists.
"""

from __future__ import annotations

import pytest
from normapi.connections import connection_identity

from normsink import SelfWriteRefusedError, assert_destination_is_not_the_source

_REAL_SOURCE_HOST = "localhost"
_REAL_SOURCE_PORT = 8190
_REAL_SOURCE_DATABASE = "origin2"


def _real_source_identity(database: str = _REAL_SOURCE_DATABASE) -> str:
    return connection_identity("clickhouse", _REAL_SOURCE_HOST, _REAL_SOURCE_PORT, database)


@pytest.mark.unit
class TestExactIdentityMatchIsAlwaysRefused:
    def test_the_real_source_cannot_be_its_own_destination(self) -> None:
        """The literal scenario the user's hard rule names: destination
        == source (localhost:8190/origin2), unconditionally refused."""
        identity = _real_source_identity()
        with pytest.raises(SelfWriteRefusedError, match="exact same connection"):
            assert_destination_is_not_the_source(
                source_identity=identity,
                destination_identity=identity,
                source_host=_REAL_SOURCE_HOST,
                source_port=_REAL_SOURCE_PORT,
                destination_host=_REAL_SOURCE_HOST,
                destination_port=_REAL_SOURCE_PORT,
            )

    def test_i_understand_same_server_does_not_bypass_an_exact_identity_match(self) -> None:
        """`i_understand_same_server` only ever overrides the SAME-SERVER
        refusal (a different database on the same host+port) — it must
        NEVER let a literal self-write through, no matter what the
        caller passes."""
        identity = _real_source_identity()
        with pytest.raises(SelfWriteRefusedError, match="exact same connection"):
            assert_destination_is_not_the_source(
                source_identity=identity,
                destination_identity=identity,
                source_host=_REAL_SOURCE_HOST,
                source_port=_REAL_SOURCE_PORT,
                destination_host=_REAL_SOURCE_HOST,
                destination_port=_REAL_SOURCE_PORT,
                i_understand_same_server=True,
            )

    def test_a_different_alias_pointed_at_the_same_real_database_is_still_refused(self) -> None:
        """Decision 4's own point: identity is keyed by host+port+database,
        never by a connection's user-facing alias — a SECOND connection
        record with a different id/alias but the SAME real coordinates
        resolves to the SAME identity, and is still refused."""
        source_identity = connection_identity(
            "clickhouse", _REAL_SOURCE_HOST, _REAL_SOURCE_PORT, _REAL_SOURCE_DATABASE
        )
        # A differently-cased/whitespace-padded host, same real server —
        # connection_identity's own normalization (lower/strip) means
        # this resolves to the identical identity, exactly as it would
        # for a real second connection record aliasing the same server.
        destination_identity = connection_identity(
            "clickhouse", " LOCALHOST ", _REAL_SOURCE_PORT, _REAL_SOURCE_DATABASE
        )
        assert source_identity == destination_identity
        with pytest.raises(SelfWriteRefusedError):
            assert_destination_is_not_the_source(
                source_identity=source_identity,
                destination_identity=destination_identity,
                source_host=_REAL_SOURCE_HOST,
                source_port=_REAL_SOURCE_PORT,
                destination_host="LOCALHOST",
                destination_port=_REAL_SOURCE_PORT,
            )


@pytest.mark.unit
class TestSameServerDifferentDatabaseIsRefusedByDefault:
    def test_origin1_as_destination_while_origin2_is_the_source_is_refused(self) -> None:
        """The plan's own callout #3: blocking only exact identity
        equality still permits writing into `origin1` while reading from
        `origin2` on the SAME real server — the realistic accident. Must
        be refused by default."""
        source_identity = _real_source_identity("origin2")
        destination_identity = _real_source_identity("origin1")
        assert source_identity != destination_identity  # different databases, real check
        with pytest.raises(SelfWriteRefusedError, match="SAME server"):
            assert_destination_is_not_the_source(
                source_identity=source_identity,
                destination_identity=destination_identity,
                source_host=_REAL_SOURCE_HOST,
                source_port=_REAL_SOURCE_PORT,
                destination_host=_REAL_SOURCE_HOST,
                destination_port=_REAL_SOURCE_PORT,
            )

    def test_i_understand_same_server_true_permits_it_deliberately(self) -> None:
        source_identity = _real_source_identity("origin2")
        destination_identity = _real_source_identity("origin1")
        assert_destination_is_not_the_source(
            source_identity=source_identity,
            destination_identity=destination_identity,
            source_host=_REAL_SOURCE_HOST,
            source_port=_REAL_SOURCE_PORT,
            destination_host=_REAL_SOURCE_HOST,
            destination_port=_REAL_SOURCE_PORT,
            i_understand_same_server=True,
        )  # does not raise


@pytest.mark.unit
class TestAGenuinelyDifferentServerIsAllowed:
    def test_a_different_host_and_a_different_database_passes_cleanly(self) -> None:
        """The real, intended-to-work case: a genuinely separate
        destination server. Must not raise."""
        source_identity = _real_source_identity("origin2")
        destination_identity = connection_identity(
            "clickhouse", "destination-host.internal", 8123, "origin2_norm"
        )
        assert_destination_is_not_the_source(
            source_identity=source_identity,
            destination_identity=destination_identity,
            source_host=_REAL_SOURCE_HOST,
            source_port=_REAL_SOURCE_PORT,
            destination_host="destination-host.internal",
            destination_port=8123,
        )  # does not raise

    def test_same_host_but_a_genuinely_different_port_is_allowed(self) -> None:
        """A different ClickHouse instance on the same machine (a common
        real dev-environment shape — a destination test container on the
        same host, a different port) is a genuinely different server,
        not the same-server case callout #3 is about."""
        source_identity = _real_source_identity("origin2")
        destination_identity = connection_identity(
            "clickhouse", _REAL_SOURCE_HOST, 8124, "origin2_norm"
        )
        assert_destination_is_not_the_source(
            source_identity=source_identity,
            destination_identity=destination_identity,
            source_host=_REAL_SOURCE_HOST,
            source_port=_REAL_SOURCE_PORT,
            destination_host=_REAL_SOURCE_HOST,
            destination_port=8124,
        )  # does not raise
