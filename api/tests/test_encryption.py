"""Unit tests for the api-side bridge-secret encryptor (M3-D1)."""

from __future__ import annotations

import pytest

from app.security.encryption import (
    BRIDGE_MASTER_KEY_ENV,
    BridgeEncryptionError,
    BridgeMasterKeyMissing,
    BridgeTokenEncryptor,
    generate_master_key,
)


@pytest.mark.unit
def test_generate_master_key_is_fernet_compatible() -> None:
    key = generate_master_key()
    enc = BridgeTokenEncryptor(master_key=key)
    ciphertext = enc.encrypt("xoxb-fake")
    assert enc.decrypt(ciphertext) == "xoxb-fake"


@pytest.mark.unit
def test_encrypt_emits_distinct_ciphertexts_for_same_plaintext() -> None:
    enc = BridgeTokenEncryptor(master_key=generate_master_key())
    a = enc.encrypt("xoxb-fake")
    b = enc.encrypt("xoxb-fake")
    assert a != b


@pytest.mark.unit
def test_encrypt_rejects_empty_plaintext() -> None:
    enc = BridgeTokenEncryptor(master_key=generate_master_key())
    with pytest.raises(ValueError):
        enc.encrypt("")


@pytest.mark.unit
def test_encrypt_without_master_key_raises_missing() -> None:
    enc = BridgeTokenEncryptor(master_key=None)
    with pytest.raises(BridgeMasterKeyMissing):
        enc.encrypt("xoxb-fake")


@pytest.mark.unit
def test_decrypt_with_wrong_master_key_raises_encryption_error() -> None:
    enc_a = BridgeTokenEncryptor(master_key=generate_master_key())
    enc_b = BridgeTokenEncryptor(master_key=generate_master_key())
    ciphertext = enc_a.encrypt("xoxb-fake")
    with pytest.raises(BridgeEncryptionError):
        enc_b.decrypt(ciphertext)


@pytest.mark.unit
def test_malformed_master_key_raises_missing() -> None:
    enc = BridgeTokenEncryptor(master_key="not-a-real-fernet-key")
    with pytest.raises(BridgeMasterKeyMissing):
        enc.encrypt("xoxb-fake")


@pytest.mark.unit
def test_from_environ_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    key = generate_master_key()
    monkeypatch.setenv(BRIDGE_MASTER_KEY_ENV, key)
    enc = BridgeTokenEncryptor.from_environ()
    assert enc.master_key == key


@pytest.mark.unit
def test_from_environ_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BRIDGE_MASTER_KEY_ENV, raising=False)
    enc = BridgeTokenEncryptor.from_environ()
    assert enc.master_key is None
