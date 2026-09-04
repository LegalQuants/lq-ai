"""Unit tests for the JSONB payload envelope (DE-358 item 5).

Covers :func:`app.security.encryption.encrypt_payload_envelope` and
:func:`app.security.encryption.decrypt_payload_envelope` — the shared
code path both ``chat_pending_tool_call`` payload columns
(``tool_call_args`` / ``resume_state``) go through.  Mirrors the
structure of ``test_mcp_encryption.py``.
"""

from __future__ import annotations

import json

import pytest

from app.security.encryption import (
    MCP_MASTER_KEY_ENV,
    PAYLOAD_ENVELOPE_MARKER,
    MCPEncryptionError,
    MCPMasterKeyMissing,
    MCPTokenEncryptor,
    decrypt_payload_envelope,
    encrypt_payload_envelope,
    generate_master_key,
)

_PAYLOAD = {"doc_id": "abc123", "reason": "remove outdated", "nested": {"n": 1}}


@pytest.mark.unit
def test_envelope_round_trip() -> None:
    enc = MCPTokenEncryptor(master_key=generate_master_key())
    stored = encrypt_payload_envelope(_PAYLOAD, encryptor=enc)
    assert decrypt_payload_envelope(stored, encryptor=enc) == _PAYLOAD


@pytest.mark.unit
def test_envelope_shape_holds_ciphertext_not_plaintext() -> None:
    """The stored dict carries the marker + a Fernet token and none of the
    plaintext keys or values."""
    enc = MCPTokenEncryptor(master_key=generate_master_key())
    stored = encrypt_payload_envelope(_PAYLOAD, encryptor=enc)
    assert stored[PAYLOAD_ENVELOPE_MARKER] == 1
    assert isinstance(stored["token"], str) and stored["token"]
    assert set(stored) == {PAYLOAD_ENVELOPE_MARKER, "token"}
    serialized = json.dumps(stored)
    assert "abc123" not in serialized
    assert "doc_id" not in serialized
    assert "remove outdated" not in serialized


@pytest.mark.unit
def test_envelope_round_trip_via_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production call shape: no injected encryptor, key from the env."""
    monkeypatch.setenv(MCP_MASTER_KEY_ENV, generate_master_key())
    stored = encrypt_payload_envelope(_PAYLOAD)
    assert decrypt_payload_envelope(stored) == _PAYLOAD


@pytest.mark.unit
def test_encrypt_without_master_key_raises_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist path fails closed — no key, no envelope, no plaintext write."""
    monkeypatch.delenv(MCP_MASTER_KEY_ENV, raising=False)
    with pytest.raises(MCPMasterKeyMissing):
        encrypt_payload_envelope(_PAYLOAD)


@pytest.mark.unit
def test_decrypt_envelope_without_master_key_raises_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = encrypt_payload_envelope(
        _PAYLOAD, encryptor=MCPTokenEncryptor(master_key=generate_master_key())
    )
    monkeypatch.delenv(MCP_MASTER_KEY_ENV, raising=False)
    with pytest.raises(MCPMasterKeyMissing):
        decrypt_payload_envelope(stored)


@pytest.mark.unit
def test_legacy_plaintext_payload_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dict without the marker is a legacy plaintext row — returned as-is,
    and no key is required to read it (transition fallback)."""
    monkeypatch.delenv(MCP_MASTER_KEY_ENV, raising=False)
    legacy = {"doc_id": "abc123"}
    out = decrypt_payload_envelope(legacy)
    assert out == legacy
    assert out is not legacy  # defensive copy


@pytest.mark.unit
def test_tampered_token_raises_encryption_error_without_payload_leak() -> None:
    key = generate_master_key()
    enc = MCPTokenEncryptor(master_key=key)
    wrong = MCPTokenEncryptor(master_key=generate_master_key())
    stored = encrypt_payload_envelope(_PAYLOAD, encryptor=wrong)
    with pytest.raises(MCPEncryptionError) as excinfo:
        decrypt_payload_envelope(stored, encryptor=enc)
    message = str(excinfo.value)
    assert "abc123" not in message
    assert stored["token"] not in message


@pytest.mark.unit
def test_malformed_envelope_missing_token_raises_encryption_error() -> None:
    enc = MCPTokenEncryptor(master_key=generate_master_key())
    with pytest.raises(MCPEncryptionError):
        decrypt_payload_envelope({PAYLOAD_ENVELOPE_MARKER: 1}, encryptor=enc)
    with pytest.raises(MCPEncryptionError):
        decrypt_payload_envelope({PAYLOAD_ENVELOPE_MARKER: 1, "token": 42}, encryptor=enc)  # type: ignore[dict-item]
    with pytest.raises(MCPEncryptionError):
        decrypt_payload_envelope({PAYLOAD_ENVELOPE_MARKER: 1, "token": "café"}, encryptor=enc)


@pytest.mark.unit
def test_non_object_decrypted_json_raises_encryption_error() -> None:
    """A token that decrypts to a JSON array/scalar is rejected — the columns
    are dict-shaped by contract."""
    enc = MCPTokenEncryptor(master_key=generate_master_key())
    token = enc.encrypt(json.dumps(["not", "a", "dict"])).decode("ascii")
    with pytest.raises(MCPEncryptionError):
        decrypt_payload_envelope({PAYLOAD_ENVELOPE_MARKER: 1, "token": token}, encryptor=enc)
    garbage_token = enc.encrypt("not-json").decode("ascii")
    with pytest.raises(MCPEncryptionError):
        decrypt_payload_envelope(
            {PAYLOAD_ENVELOPE_MARKER: 1, "token": garbage_token}, encryptor=enc
        )
