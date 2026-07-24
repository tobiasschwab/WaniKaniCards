"""Tests für crypto.py – Verschlüsselung ruhender Secrets (Fernet)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from shiori import crypto


@pytest.fixture
def master_key(monkeypatch):
    key = crypto.generate_master_key()
    monkeypatch.setenv("WKCARDS_SECRET_KEY", key)
    return key


def test_encrypt_decrypt_roundtrip(master_key):
    ciphertext = crypto.encrypt_secret("mein-geheimer-token")
    assert ciphertext != "mein-geheimer-token"
    assert crypto.decrypt_secret(ciphertext) == "mein-geheimer-token"


def test_encrypt_none_or_empty_returns_none(master_key):
    assert crypto.encrypt_secret(None) is None
    assert crypto.encrypt_secret("") is None


def test_decrypt_none_or_empty_returns_none(master_key):
    assert crypto.decrypt_secret(None) is None
    assert crypto.decrypt_secret("") is None


def test_decrypt_garbage_returns_none_instead_of_raising(master_key):
    assert crypto.decrypt_secret("not-a-valid-fernet-token") is None


def test_decrypt_with_rotated_key_returns_none(monkeypatch):
    monkeypatch.setenv("WKCARDS_SECRET_KEY", crypto.generate_master_key())
    ciphertext = crypto.encrypt_secret("geheim")
    monkeypatch.setenv("WKCARDS_SECRET_KEY", crypto.generate_master_key())
    assert crypto.decrypt_secret(ciphertext) is None


def test_missing_master_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("WKCARDS_SECRET_KEY", raising=False)
    with pytest.raises(crypto.SecretCryptoError):
        crypto.encrypt_secret("x")


def test_invalid_master_key_format_raises_clear_error(monkeypatch):
    monkeypatch.setenv("WKCARDS_SECRET_KEY", "not-base64-not-32-bytes")
    with pytest.raises(crypto.SecretCryptoError):
        crypto.encrypt_secret("x")


def test_generate_master_key_is_usable_immediately():
    key = crypto.generate_master_key()
    assert isinstance(key, str) and len(key) > 0
