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
from normio.connectors.clickhouse_destination import PASSTHROUGH_CH_TYPE, SEMANTIC_TYPE_TO_CH_TYPE
from normio.connectors.postgres_destination import PASSTHROUGH_PG_TYPE, SEMANTIC_TYPE_TO_PG_TYPE

from normapi import secrets
from normcore import FieldSemanticType


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
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
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


@pytest.mark.unit
def test_every_configured_column_type_is_text_compatible() -> None:
    """Regression for a real bug found running this feature against messy
    real-world data: a failed value's ORIGINAL raw string (decision #8's
    fallback) must always be insertable into a configured column's
    destination type — and there is no per-row column typing in SQL, so
    the type is fixed at CREATE TABLE time, before any row's success/
    failure is known. A native DATE/NUMERIC/UUID/BOOLEAN column rejects a
    raw fallback string that isn't already well-formed for that type
    (e.g. a source "d1989-12-11" DateNormalizer correctly flags INVALID
    and falls back to — verbatim — a value no DATE column accepts),
    crashing the whole insert (and therefore the whole job, and even the
    error-report row for that exact value, which never got written).
    Every mapped type must therefore be text-compatible on both engines."""
    non_text_pg = {t: v for t, v in SEMANTIC_TYPE_TO_PG_TYPE.items() if v != "TEXT"}
    assert not non_text_pg, (
        f"Non-text Postgres types would reject decision #8's fallback: {non_text_pg}"
    )
    non_text_ch = {t: v for t, v in SEMANTIC_TYPE_TO_CH_TYPE.items() if v != "String"}
    assert not non_text_ch, (
        f"Non-text ClickHouse types would reject decision #8's fallback: {non_text_ch}"
    )
