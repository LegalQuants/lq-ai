"""Unit tests for the api-side MCP-token encryptor (PR4c).

Mirrors ``test_encryption.py`` for ``BridgeTokenEncryptor`` — same
structure, different class and env-var.  The two master keys must be
independent so a compromise of one does not expose the other (separate
blast radii per module docstring).
"""

from __future__ import annotations

import pytest

from app.security.encryption import (
    MCP_MASTER_KEY_ENV,
    MCPEncryptionError,
    MCPMasterKeyMissing,
    MCPTokenEncryptor,
    generate_master_key,
)


@pytest.mark.unit
def test_mcp_round_trip() -> None:
    key = generate_master_key()
    enc = MCPTokenEncryptor(master_key=key)
    ciphertext = enc.encrypt("ey.fake-oauth-token")
    assert enc.decrypt(ciphertext) == "ey.fake-oauth-token"


@pytest.mark.unit
def test_mcp_encrypt_emits_distinct_ciphertexts_for_same_plaintext() -> None:
    enc = MCPTokenEncryptor(master_key=generate_master_key())
    a = enc.encrypt("ey.fake-oauth-token")
    b = enc.encrypt("ey.fake-oauth-token")
    assert a != b


@pytest.mark.unit
def test_mcp_encrypt_rejects_empty_plaintext() -> None:
    enc = MCPTokenEncryptor(master_key=generate_master_key())
    with pytest.raises(ValueError):
        enc.encrypt("")


@pytest.mark.unit
def test_mcp_encrypt_without_master_key_raises_missing() -> None:
    enc = MCPTokenEncryptor(master_key=None)
    with pytest.raises(MCPMasterKeyMissing):
        enc.encrypt("ey.fake-oauth-token")


@pytest.mark.unit
def test_mcp_decrypt_with_wrong_master_key_raises_encryption_error() -> None:
    enc_a = MCPTokenEncryptor(master_key=generate_master_key())
    enc_b = MCPTokenEncryptor(master_key=generate_master_key())
    ciphertext = enc_a.encrypt("ey.fake-oauth-token")
    with pytest.raises(MCPEncryptionError):
        enc_b.decrypt(ciphertext)


@pytest.mark.unit
def test_mcp_malformed_master_key_raises_missing() -> None:
    enc = MCPTokenEncryptor(master_key="not-a-real-fernet-key")
    with pytest.raises(MCPMasterKeyMissing):
        enc.encrypt("ey.fake-oauth-token")


@pytest.mark.unit
def test_mcp_from_environ_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    key = generate_master_key()
    monkeypatch.setenv(MCP_MASTER_KEY_ENV, key)
    enc = MCPTokenEncryptor.from_environ()
    assert enc.master_key == key


@pytest.mark.unit
def test_mcp_from_environ_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MCP_MASTER_KEY_ENV, raising=False)
    enc = MCPTokenEncryptor.from_environ()
    assert enc.master_key is None


@pytest.mark.unit
def test_mcp_and_bridge_keys_are_independent() -> None:
    """A token encrypted under the MCP key must NOT decrypt under a Bridge key,
    and vice versa — the two namespaces must be strictly independent."""
    from app.security.encryption import BridgeEncryptionError, BridgeTokenEncryptor

    mcp_key = generate_master_key()
    bridge_key = generate_master_key()
    mcp_enc = MCPTokenEncryptor(master_key=mcp_key)
    bridge_enc = BridgeTokenEncryptor(master_key=bridge_key)

    # MCP ciphertext must NOT decrypt under the bridge key.
    mcp_ciphertext = mcp_enc.encrypt("ey.fake-oauth-token")
    with pytest.raises(BridgeEncryptionError):
        bridge_enc.decrypt(mcp_ciphertext)

    # Bridge ciphertext must NOT decrypt under the MCP key.
    bridge_ciphertext = bridge_enc.encrypt("ey.fake-oauth-token")
    with pytest.raises(MCPEncryptionError):
        mcp_enc.decrypt(bridge_ciphertext)
