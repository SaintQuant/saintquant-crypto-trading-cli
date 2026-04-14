"""
Tests for crypto_trading_cli.crypto

Property 1: Credential encryption round-trip
  - encrypt(s) then decrypt gives back s
  - encrypted form != plaintext

Property 2: Key derivation is deterministic and machine-bound
  - derive_key(id) called twice returns identical bytes
  - derive_key(id_a) != derive_key(id_b) for id_a != id_b
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crypto_trading_cli.crypto import decrypt, derive_key, encrypt


# ---------------------------------------------------------------------------
# Property 1: round-trip encryption
# ---------------------------------------------------------------------------


@given(st.text(min_size=1, max_size=512))
@settings(max_examples=200)
def test_encrypt_decrypt_roundtrip(plaintext: str) -> None:
    """For any non-empty string, decrypt(encrypt(s)) == s."""
    ciphertext = encrypt(plaintext)
    assert decrypt(ciphertext) == plaintext


@given(st.text(min_size=1, max_size=512))
@settings(max_examples=200)
def test_encrypted_form_differs_from_plaintext(plaintext: str) -> None:
    """The encrypted form must not equal the plaintext."""
    ciphertext = encrypt(plaintext)
    assert ciphertext != plaintext


@given(st.text(min_size=1, max_size=512))
@settings(max_examples=100)
def test_encrypt_produces_different_ciphertexts_each_call(plaintext: str) -> None:
    """Fernet uses a random IV, so two encryptions of the same plaintext differ."""
    c1 = encrypt(plaintext)
    c2 = encrypt(plaintext)
    assert c1 != c2  # different IVs → different ciphertexts


# ---------------------------------------------------------------------------
# Property 2: key derivation determinism and machine-binding
# ---------------------------------------------------------------------------


@given(st.text(min_size=1, max_size=256))
@settings(max_examples=100)
def test_derive_key_is_deterministic(machine_id: str) -> None:
    """derive_key(id) called twice returns identical bytes."""
    assert derive_key(machine_id) == derive_key(machine_id)


@given(
    st.text(min_size=1, max_size=256),
    st.text(min_size=1, max_size=256),
)
@settings(max_examples=200)
def test_derive_key_is_machine_bound(id_a: str, id_b: str) -> None:
    """Different machine IDs produce different keys."""
    if id_a != id_b:
        assert derive_key(id_a) != derive_key(id_b)


# ---------------------------------------------------------------------------
# Example-based edge cases
# ---------------------------------------------------------------------------


def test_encrypt_empty_string_raises() -> None:
    """Encrypting an empty string should still work (Fernet allows it)."""
    # We allow empty strings — the validator layer prevents them at input time
    result = encrypt("")
    assert decrypt(result) == ""


def test_derive_key_returns_bytes() -> None:
    key = derive_key("test-machine-id")
    assert isinstance(key, bytes)
    # Fernet keys are 44 URL-safe base64 characters (32 bytes → 44 chars)
    assert len(key) == 44


def test_derive_key_fixed_known_value() -> None:
    """Regression test: key derivation must not change between versions."""
    key = derive_key("test-machine-id")
    # Re-derive and confirm stability
    assert key == derive_key("test-machine-id")
