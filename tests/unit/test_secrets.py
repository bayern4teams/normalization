"""Unit tests for normapi.secrets (M15) — AES-GCM credential encryption
at rest. No database needed; pure crypto-primitive behavior."""

from __future__ import annotations

import base64

import pytest
from normapi.secrets import (
    CredentialCipher,
    DecryptionError,
    SecretKeyError,
    generate_secret_key,
    load_secret_key,
)


@pytest.mark.unit
class TestLoadSecretKey:
    def test_valid_key_decodes_to_32_bytes(self) -> None:
        key = load_secret_key(generate_secret_key())
        assert len(key) == 32

    def test_none_raises(self) -> None:
        with pytest.raises(SecretKeyError, match="not set"):
            load_secret_key(None)

    def test_empty_string_raises(self) -> None:
        with pytest.raises(SecretKeyError, match="not set"):
            load_secret_key("   ")

    def test_invalid_base64_raises(self) -> None:
        with pytest.raises(SecretKeyError, match="not valid base64"):
            load_secret_key("not-valid-base64-!!!")

    def test_wrong_length_raises(self) -> None:
        short_key = base64.b64encode(b"too short").decode("ascii")
        with pytest.raises(SecretKeyError, match=r"32.*bytes"):
            load_secret_key(short_key)


@pytest.mark.unit
class TestCredentialCipherRoundTrip:
    def test_encrypt_then_decrypt_returns_original(self) -> None:
        cipher = CredentialCipher(load_secret_key(generate_secret_key()))
        assert cipher.decrypt(cipher.encrypt("s3cret-p@ssw0rd")) == "s3cret-p@ssw0rd"

    def test_encrypt_never_returns_the_plaintext_verbatim(self) -> None:
        cipher = CredentialCipher(load_secret_key(generate_secret_key()))
        plaintext = "super-secret-password-value"
        ciphertext = cipher.encrypt(plaintext)
        assert plaintext not in ciphertext

    def test_two_encryptions_of_the_same_plaintext_differ(self) -> None:
        """A fresh random nonce per call — proves encrypt() isn't
        deterministic, which is what makes AES-GCM safe to reuse a key
        across many encrypt() calls."""
        cipher = CredentialCipher(load_secret_key(generate_secret_key()))
        first = cipher.encrypt("same-password")
        second = cipher.encrypt("same-password")
        assert first != second
        assert cipher.decrypt(first) == cipher.decrypt(second) == "same-password"

    def test_empty_string_round_trips(self) -> None:
        cipher = CredentialCipher(load_secret_key(generate_secret_key()))
        assert cipher.decrypt(cipher.encrypt("")) == ""

    def test_unicode_password_round_trips(self) -> None:
        cipher = CredentialCipher(load_secret_key(generate_secret_key()))
        assert cipher.decrypt(cipher.encrypt("pàsswörd123密码")) == "pàsswörd123密码"


@pytest.mark.unit
class TestCredentialCipherWrongKeyOrTamperedData:
    def test_decrypting_with_a_different_key_fails(self) -> None:
        cipher_a = CredentialCipher(load_secret_key(generate_secret_key()))
        cipher_b = CredentialCipher(load_secret_key(generate_secret_key()))
        ciphertext = cipher_a.encrypt("password")
        with pytest.raises(DecryptionError):
            cipher_b.decrypt(ciphertext)

    def test_tampered_ciphertext_fails_to_decrypt(self) -> None:
        """Proves this is AEAD (authenticated), not just confidential —
        a flipped byte in the ciphertext is DETECTED, not silently
        decrypted into garbage."""
        cipher = CredentialCipher(load_secret_key(generate_secret_key()))
        ciphertext = cipher.encrypt("password")
        raw = bytearray(base64.b64decode(ciphertext))
        raw[-1] ^= 0xFF  # flip the last byte (part of the GCM auth tag)
        tampered = base64.b64encode(bytes(raw)).decode("ascii")
        with pytest.raises(DecryptionError):
            cipher.decrypt(tampered)

    def test_garbage_input_fails_cleanly(self) -> None:
        cipher = CredentialCipher(load_secret_key(generate_secret_key()))
        with pytest.raises(DecryptionError):
            cipher.decrypt("not even valid base64 ciphertext !!!")


@pytest.mark.unit
class TestCredentialCipherConstruction:
    def test_wrong_length_key_rejected_at_construction(self) -> None:
        with pytest.raises(SecretKeyError):
            CredentialCipher(b"too-short")
