"""Symmetric-encryption helper for at-rest secrets owned by ``api/``.

The first caller is M3-D1's ``slack_workspaces`` table, where bot tokens
are persisted encrypted under a master key the operator supplies via
:envvar:`LQ_AI_BRIDGE_MASTER_KEY`. The intent is to mirror the gateway's
:mod:`gateway.app.secrets` ADR-0011 pattern (Fernet authenticated
encryption + urlsafe-base64 master key) without sharing the key
material between services — Slack bot tokens (bot-impersonation blast
radius) and provider API keys (inference-routing blast radius) live in
different threat models, so they get different master keys.

Operators generate the master key once with :func:`generate_master_key`
and store it however they store other small high-value secrets — a
password manager, a hardware token, a secrets vault. The key is read
from the environment at adapter construction time and held in memory;
nothing in this module persists it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

__all__ = [
    "BRIDGE_MASTER_KEY_ENV",
    "BridgeEncryptionError",
    "BridgeMasterKeyMissing",
    "BridgeTokenEncryptor",
    "generate_master_key",
]


BRIDGE_MASTER_KEY_ENV = "LQ_AI_BRIDGE_MASTER_KEY"
"""Environment variable the api reads to bind its bridge master key.

Distinct from ``LQ_AI_GATEWAY_MASTER_KEY`` on purpose — see module
docstring."""


class BridgeMasterKeyMissing(RuntimeError):
    """Raised when an encrypt/decrypt is requested without a master key."""


class BridgeEncryptionError(RuntimeError):
    """Raised when a ciphertext cannot be decrypted with the master key.

    Wrong master key vs corrupted/tampered ciphertext are indistinguishable
    by Fernet design (AEAD rejects both with the same error).
    """


def generate_master_key() -> str:
    """Generate a fresh urlsafe-base64 master key (32 bytes / 256 bits)."""

    return Fernet.generate_key().decode("ascii")


def _fernet_from(master_key: str | None) -> Fernet:
    if not master_key:
        raise BridgeMasterKeyMissing(
            f"{BRIDGE_MASTER_KEY_ENV} is not set. Generate a master key with "
            f"`python -c 'from app.security.encryption import generate_master_key; "
            f"print(generate_master_key())'` and export it before starting the api."
        )
    try:
        return Fernet(master_key.encode("ascii") if isinstance(master_key, str) else master_key)
    except (ValueError, TypeError) as exc:
        raise BridgeMasterKeyMissing(
            f"{BRIDGE_MASTER_KEY_ENV} is malformed (must be urlsafe-base64 of 32 bytes): {exc}"
        ) from exc


@dataclass
class BridgeTokenEncryptor:
    """Encrypt and decrypt bridge-issued secrets (e.g., Slack bot tokens).

    Constructed once per request scope from :data:`BRIDGE_MASTER_KEY_ENV`
    via :meth:`from_environ`; tests construct directly with their own
    master key to stay hermetic.

    Both :meth:`encrypt` and :meth:`decrypt` operate on ``bytes`` on the
    storage side (the column type is ``bytea`` so the ORM sees ``bytes``)
    and ``str`` on the plaintext side (Slack bot tokens are ASCII).
    """

    master_key: str | None

    @classmethod
    def from_environ(cls) -> BridgeTokenEncryptor:
        return cls(master_key=os.environ.get(BRIDGE_MASTER_KEY_ENV) or None)

    def encrypt(self, plaintext: str) -> bytes:
        """Wrap ``plaintext`` and return the Fernet token as ``bytes``."""

        if not plaintext:
            raise ValueError("encrypt() requires a non-empty plaintext")
        fernet = _fernet_from(self.master_key)
        return fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        """Unwrap ``ciphertext`` and return the plaintext string."""

        fernet = _fernet_from(self.master_key)
        try:
            return fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise BridgeEncryptionError(
                f"bridge ciphertext does not decrypt under {BRIDGE_MASTER_KEY_ENV}. "
                f"Wrong master key, or the token was generated with a different one."
            ) from exc
