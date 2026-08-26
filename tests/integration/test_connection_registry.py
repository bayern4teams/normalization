"""Integration tests for M15's connection registry — real Postgres
(compose.yaml's `postgres` service, port 5535) AND real source databases:
the actual target ClickHouse at localhost:8190 (origin2, per the M13-M22
plan's own verify-live step) for the successful-connection path, and the
demo-clickhouse container (port 8124) for the wrong-password path so no
real credential is deliberately mistyped against the production target.

Four things are proven, not assumed:
1. POST /connections against the real target succeeds and persists.
2. No response body, at any point, ever contains the plaintext password
   — not GET /connections, not the POST /connections response, not a
   400 error detail, not a captured OTel span, not a log line.
3. The stored `encrypted_password` column is real ciphertext, verified by
   direct psycopg query bypassing the API entirely.
4. A SECOND, independent app (same NORM_PG_DSN + NORM_SECRET_KEY) can
   still decrypt and resolve the connection — the actual "restart"
   behavior, not simulated by re-reading the same in-process object.

Requires: docker compose up -d postgres demo-clickhouse
"""

from __future__ import annotations

import logging
import os
import re

import psycopg
import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app
from normapi.secrets import generate_secret_key

_PG_DSN = os.environ.get(
    "TEST_METADATA_PG_DSN", "postgresql://normalization:normalization@localhost:5535/normalization"
)
_REAL_CLICKHOUSE_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")
_DEMO_CLICKHOUSE_PORT = 8124


def _skip_if_pg_unreachable() -> None:
    try:
        conn = psycopg.connect(_PG_DSN, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"metadata postgres not reachable at {_PG_DSN}: {exc}")
    else:
        conn.close()


@pytest.fixture
def secret_key() -> str:
    return generate_secret_key()


@pytest.mark.integration
class TestConnectionRegistryLiveAgainstRealClickHouse:
    def test_post_connections_against_the_real_target_succeeds_and_never_leaks_the_password(
        self, secret_key: str
    ) -> None:
        _skip_if_pg_unreachable()
        app = create_app(postgres_dsn=_PG_DSN, secret_key=secret_key)
        client = TestClient(app)
        password = "pass"  # the real sources.json credential for origin2

        response = client.post(
            "/normalization/connections",
            json={
                "alias": "m15-live-verify",
                "kind": "clickhouse",
                "host": _REAL_CLICKHOUSE_HOST,
                "port": 8190,
                "username": "default",
                "password": password,
                "database": "origin2",
            },
        )

        assert response.status_code == 201, response.text
        assert password not in response.text
        body = response.json()
        assert "password" not in body
        connection_id = body["id"]
        assert body["identity"]  # a real 64-char blake3 hex, not empty

        list_response = client.get("/normalization/connections")
        assert password not in list_response.text
        assert "password" not in list_response.json()[0]

        # Real ciphertext, verified by a direct query bypassing the API.
        with psycopg.connect(_PG_DSN) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT encrypted_password FROM connections WHERE id = %s", (connection_id,)
            )
            row = cur.fetchone()
        assert row is not None
        (stored,) = row
        assert password not in stored
        assert stored != password

        # Every captured OTel span, across the whole request — proves the
        # plaintext password never reached span-attribute instrumentation.
        for span in app.state.telemetry_handles.span_exporter.get_finished_spans():
            assert password not in repr(span.attributes)
            assert password not in (span.name or "")

        # Cleanup — delete the connection this test created so repeated
        # runs don't accumulate rows (not load-bearing for the assertions
        # above, just hygiene for a real shared Postgres instance).
        client.delete(f"/normalization/connections/{connection_id}")

    def test_restart_simulation_a_second_independent_app_resolves_the_connection(
        self, secret_key: str
    ) -> None:
        """The actual load-bearing 'survives a restart' claim: NOT that
        the metadata row is still listed (trivially true for any
        Postgres-backed table), but that a brand-new process — a fresh
        CredentialCipher built from the same NORM_SECRET_KEY, a fresh
        Postgres connection — can still DECRYPT the stored password and
        build a real, working connector from it."""
        _skip_if_pg_unreachable()
        app_a = create_app(postgres_dsn=_PG_DSN, secret_key=secret_key)
        client_a = TestClient(app_a)
        password = "pass"

        create_response = client_a.post(
            "/normalization/connections",
            json={
                "alias": "m15-restart-verify",
                "kind": "clickhouse",
                "host": _REAL_CLICKHOUSE_HOST,
                "port": 8190,
                "username": "default",
                "password": password,
                "database": "origin2",
            },
        )
        assert create_response.status_code == 201, create_response.text
        connection_id = create_response.json()["id"]

        # A brand-new app object = a brand-new process would look
        # identical from the outside: fresh Postgres connection, fresh
        # CredentialCipher, nothing shared in-process with app_a.
        app_b = create_app(postgres_dsn=_PG_DSN, secret_key=secret_key)
        assert app_b.state.connection_resolver is not None
        resolved = app_b.state.connection_resolver.resolve(connection_id)
        assert resolved.password == password
        assert resolved.host == _REAL_CLICKHOUSE_HOST
        assert resolved.database == "origin2"

        # And the resolved credentials actually work — a real connector
        # built from them can list the real origin2 tables.
        connector = app_b.state.source_registry.get_by_connection(connection_id, "origin2")
        tables = connector.list_tables()
        assert "Person" in tables

        TestClient(app_b).delete(f"/normalization/connections/{connection_id}")


@pytest.mark.integration
class TestConnectionRegistryWrongPassword:
    def test_wrong_password_test_endpoint_returns_ok_false_without_persisting(
        self, secret_key: str
    ) -> None:
        """Against the demo-clickhouse container (port 8124, its own
        readonly_user/readonly_pass), not the real production target —
        a deliberately wrong credential has no reason to touch real data.
        """
        _skip_if_pg_unreachable()
        app = create_app(postgres_dsn=_PG_DSN, secret_key=secret_key)
        client = TestClient(app)
        wrong_password = "definitely-not-the-real-password"

        response = client.post(
            "/normalization/connections/test",
            json={
                "kind": "clickhouse",
                "host": _REAL_CLICKHOUSE_HOST,
                "port": _DEMO_CLICKHOUSE_PORT,
                "username": "readonly_user",
                "password": wrong_password,
                "database": "default",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert wrong_password not in response.text

    def test_wrong_password_post_connections_returns_400_and_persists_nothing(
        self, secret_key: str
    ) -> None:
        _skip_if_pg_unreachable()
        app = create_app(postgres_dsn=_PG_DSN, secret_key=secret_key)
        client = TestClient(app)
        wrong_password = "definitely-not-the-real-password-either"

        before = {c["id"] for c in client.get("/normalization/connections").json()}

        response = client.post(
            "/normalization/connections",
            json={
                "alias": "should-not-be-saved",
                "kind": "clickhouse",
                "host": _REAL_CLICKHOUSE_HOST,
                "port": _DEMO_CLICKHOUSE_PORT,
                "username": "readonly_user",
                "password": wrong_password,
                "database": "default",
            },
        )

        assert response.status_code == 400
        assert wrong_password not in response.text

        after = {c["id"] for c in client.get("/normalization/connections").json()}
        assert after == before  # nothing new was persisted


@pytest.mark.integration
class TestSecretKeyRefuseToBoot:
    def test_boots_fine_with_no_key_when_no_connections_exist_yet(self) -> None:
        """A fresh/unused connections table + no NORM_SECRET_KEY is a
        valid, common state (the feature is simply unused) — must NOT be
        treated as an error."""
        _skip_if_pg_unreachable()
        with psycopg.connect(_PG_DSN) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM connections")
            row = cur.fetchone()
        assert row is not None
        (count,) = row
        if count > 0:
            pytest.skip("connections table is non-empty; this test only applies to a clean table")
        app = create_app(postgres_dsn=_PG_DSN, secret_key=None)
        assert app.state.connection_resolver is None

    def test_refuses_to_boot_when_connections_exist_but_key_is_missing(
        self, secret_key: str
    ) -> None:
        _skip_if_pg_unreachable()
        app = create_app(postgres_dsn=_PG_DSN, secret_key=secret_key)
        client = TestClient(app)
        create_response = client.post(
            "/normalization/connections",
            json={
                "alias": "m15-refuse-to-boot-verify",
                "kind": "clickhouse",
                "host": _REAL_CLICKHOUSE_HOST,
                "port": 8190,
                "username": "default",
                "password": "pass",
                "database": "origin2",
            },
        )
        assert create_response.status_code == 201
        connection_id = create_response.json()["id"]

        try:
            with pytest.raises(Exception, match="NORM_SECRET_KEY is not set"):
                create_app(postgres_dsn=_PG_DSN, secret_key=None)
        finally:
            client.delete(f"/normalization/connections/{connection_id}")


@pytest.mark.integration
def test_no_logging_output_ever_contains_a_plaintext_password(
    caplog: pytest.LogCaptureFixture, secret_key: str
) -> None:
    _skip_if_pg_unreachable()
    caplog.set_level(logging.DEBUG)
    app = create_app(postgres_dsn=_PG_DSN, secret_key=secret_key)
    client = TestClient(app)
    password = "pass"  # the real origin2 credential — must NOT reach any log line

    response = client.post(
        "/normalization/connections",
        json={
            "alias": "m15-log-scrub-verify",
            "kind": "clickhouse",
            "host": _REAL_CLICKHOUSE_HOST,
            "port": 8190,
            "username": "default",
            "password": password,
            "database": "origin2",
        },
    )
    assert response.status_code == 201, response.text
    connection_id = response.json()["id"]
    client.delete(f"/normalization/connections/{connection_id}")

    # Word-boundary match, not a bare substring: the real credential here
    # ("pass") is also an English word fragment ("password", "bypass")
    # that legitimately appears in unrelated log/library output — a bare
    # `password in message` check would false-positive on those. This
    # still catches the real leak shape: the value appearing standalone,
    # quoted, or after "=" (e.g. `password=pass`, `'pass'`).
    leak_pattern = re.compile(rf"(?<![A-Za-z]){re.escape(password)}(?![A-Za-z])")
    for record in caplog.records:
        assert not leak_pattern.search(record.getMessage())
