"""Pure in-process unit coverage for the DB-clone-and-normalize feature's
non-DB logic: `normapi.secrets` encrypt/decrypt round-trip (decision #12,
required as this module's `assert`-based self-check for non-trivial
security-adjacent logic) and the FieldSemanticType -> native-type lookup
tables (decision #11's type mapping — every semantic type must map on
both engines, checked here rather than only being discovered by a DDL
failure against a real database).
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from normcore import FieldSemanticType
from normio.connectors.clickhouse_destination import PASSTHROUGH_CH_TYPE, SEMANTIC_TYPE_TO_CH_TYPE
from normio.connectors.postgres_destination import PASSTHROUGH_PG_TYPE, SEMANTIC_TYPE_TO_PG_TYPE

from normapi import secrets


@pytest.fixture
def secret_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("NORM_SECRET_KEY", key)
    return key


@pytest.mark.unit
def test_encrypt_decrypt_round_trips(secret_key: str) -> None:
    plaintext = "correct horse battery staple"
    ciphertext = secrets.encrypt(plaintext)
    assert ciphertext != plaintext
    assert secrets.decrypt(ciphertext) == plaintext


@pytest.mark.unit
def test_decrypt_fails_with_wrong_key(secret_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    ciphertext = secrets.encrypt("some-password")
    monkeypatch.setenv("NORM_SECRET_KEY", Fernet.generate_key().decode())
    with pytest.raises(Exception):  # noqa: B017 - cryptography.fernet.InvalidToken
        secrets.decrypt(ciphertext)


@pytest.mark.unit
def test_encrypt_requires_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NORM_SECRET_KEY", raising=False)
    with pytest.raises(secrets.SecretKeyNotConfiguredError):
        secrets.encrypt("x")


@pytest.mark.unit
def test_every_semantic_type_has_a_postgres_type() -> None:
    missing = [t for t in FieldSemanticType if t.value not in SEMANTIC_TYPE_TO_PG_TYPE]
    assert not missing, f"Missing Postgres type mapping for: {missing}"
    assert PASSTHROUGH_PG_TYPE  # passthrough fallback is non-empty


@pytest.mark.unit
def test_every_semantic_type_has_a_clickhouse_type() -> None:
    missing = [t for t in FieldSemanticType if t.value not in SEMANTIC_TYPE_TO_CH_TYPE]
    assert not missing, f"Missing ClickHouse type mapping for: {missing}"
    assert PASSTHROUGH_CH_TYPE
