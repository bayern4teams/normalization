"""Credential-at-rest encryption for saved connections (decision #12).

Nothing in this repo did encryption before this feature (checked, zero
hits) — `cryptography`'s `Fernet` is a justified new dependency, not scope
creep. One key from one env var (`NORM_SECRET_KEY`), decrypted only in
memory at connect-time; never held decrypted anywhere else.
# ponytail: one key, no rotation/versioning — add key-versioning only if
# rotation becomes a real requirement.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet


class SecretKeyNotConfiguredError(RuntimeError):
    """Raised when NORM_SECRET_KEY is unset — saved connections cannot be
    encrypted/decrypted without it, so this fails loudly rather than
    storing plaintext credentials or crashing on a bare KeyError."""


def _fernet() -> Fernet:
    # Re-read the env var on every call rather than caching the Fernet
    # instance — encrypt/decrypt are called at write-time and
    # read-time-of-use only (never in a hot loop), so there is no real
    # cost to this, and it keeps key rotation/testing (swap the env var,
    # no cached-stale-key surprise) simple.
    key = os.environ.get("NORM_SECRET_KEY")
    if not key:
        msg = "NORM_SECRET_KEY is not set — required to store/read saved connection credentials."
        raise SecretKeyNotConfiguredError(msg)
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
