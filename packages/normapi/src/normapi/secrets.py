"""Encryption at rest for connection credentials — M15 of the
M13-M22 program (docs/plan/M13-M22-program-plan.md), ADR-017.

AES-256-GCM via `cryptography` (the standard, audited Python library),
not a hand-rolled cipher. Each encrypted value is stored as one base64
string: `base64(nonce (12 bytes) || ciphertext+tag)`, so it fits in a
single Postgres `text` column with no separate nonce column needed. A
fresh random nonce is generated per `encrypt()` call — AES-GCM is only
safe to use this way (same key, many calls) if the nonce never repeats,
which `secrets.token_bytes` gives with overwhelming probability.
"""

from __future__ import annotations

import base64
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_LENGTH_BYTES = 32  # AES-256
_NONCE_LENGTH_BYTES = 12  # AES-GCM's standard, recommended nonce size


class SecretKeyError(RuntimeError):
    """Raised when NORM_SECRET_KEY is missing or malformed — always a
    startup-time failure, never a per-request one."""


class DecryptionError(RuntimeError):
    """Raised when a stored ciphertext fails to decrypt — a wrong key or
    tampered/corrupted data. Never includes the ciphertext or any partial
    plaintext in its message."""


def load_secret_key(raw: str | None) -> bytes:
    """Decodes and validates NORM_SECRET_KEY: must be base64 for exactly
    32 raw bytes (AES-256). Never logs or echoes the raw value on
    failure — only the length/format problem is described."""
    if raw is None or raw.strip() == "":
        msg = "NORM_SECRET_KEY is not set"
        raise SecretKeyError(msg)
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:
        msg = "NORM_SECRET_KEY is not valid base64"
        raise SecretKeyError(msg) from exc
    if len(key) != _KEY_LENGTH_BYTES:
        msg = (
            f"NORM_SECRET_KEY must decode to exactly {_KEY_LENGTH_BYTES} "
            f"bytes (AES-256), got {len(key)}"
        )
        raise SecretKeyError(msg)
    return key


def generate_secret_key() -> str:
    """For operator setup only (e.g. a one-off `uv run python -c
    "from normapi.secrets import generate_secret_key;
    print(generate_secret_key())"` when provisioning a new deployment) —
    never called by application code at request or startup time."""
    return base64.b64encode(AESGCM.generate_key(_KEY_LENGTH_BYTES * 8)).decode("ascii")


class CredentialCipher:
    """Holds one loaded key in memory; encrypts/decrypts individual
    credential strings (a connection's password) against it. Never logs,
    prints, or includes plaintext/ciphertext in any exception message."""

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_LENGTH_BYTES:
            msg = f"CredentialCipher requires a {_KEY_LENGTH_BYTES}-byte key, got {len(key)}"
            raise SecretKeyError(msg)
        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = secrets.token_bytes(_NONCE_LENGTH_BYTES)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, encoded: str) -> str:
        try:
            raw = base64.b64decode(encoded, validate=True)
            nonce, ciphertext = raw[:_NONCE_LENGTH_BYTES], raw[_NONCE_LENGTH_BYTES:]
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
        except (ValueError, InvalidTag) as exc:
            msg = "Failed to decrypt stored credential — wrong key or corrupted data"
            raise DecryptionError(msg) from exc
        return plaintext.decode("utf-8")
