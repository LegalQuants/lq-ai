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
    "MCP_MASTER_KEY_ENV",
    "BridgeEncryptionError",
    "BridgeMasterKeyMissing",
    "BridgeTokenEncryptor",
    "MCPEncryptionError",
    "MCPMasterKeyMissing",
    "MCPTokenEncryptor",
    "generate_master_key",
]


BRIDGE_MASTER_KEY_ENV = "LQ_AI_BRIDGE_MASTER_KEY"
"""Environment variable the api reads to bind its bridge master key.

Distinct from ``LQ_AI_GATEWAY_MASTER_KEY`` on purpose — see module
docstring."""

MCP_MASTER_KEY_ENV = "LQ_AI_MCP_MASTER_KEY"
"""Environment variable the api reads to bind its MCP OAuth token master key.

Distinct from :data:`BRIDGE_MASTER_KEY_ENV` on purpose — per-user MCP
OAuth tokens (gateway-routing blast radius) and bridge secrets (bot-token
blast radius) must live under separate master keys so a compromise of one
does not expose the other."""


class BridgeMasterKeyMissing(RuntimeError):
    """Raised when an encrypt/decrypt is requested without a master key."""


class BridgeEncryptionError(RuntimeError):
    """Raised when a ciphertext cannot be decrypted with the master key.

    Wrong master key vs corrupted/tampered ciphertext are indistinguishable
    by Fernet design (AEAD rejects both with the same error).
    """


class MCPMasterKeyMissing(RuntimeError):
    """Raised when an MCP encrypt/decrypt is requested without a master key."""


class MCPEncryptionError(RuntimeError):
    """Raised when an MCP ciphertext cannot be decrypted with the master key.

    Wrong master key vs corrupted/tampered ciphertext are indistinguishable
    by Fernet design (AEAD rejects both with the same error).
    """


def generate_master_key() -> str:
    """Generate a fresh urlsafe-base64 master key (32 bytes / 256 bits)."""

    return Fernet.generate_key().decode("ascii")


def _fernet_from(
    master_key: str | None,
    *,
    env_var: str = BRIDGE_MASTER_KEY_ENV,
    missing_exc: type[BridgeMasterKeyMissing | MCPMasterKeyMissing] = BridgeMasterKeyMissing,
) -> Fernet:
    """Construct a :class:`~cryptography.fernet.Fernet` from *master_key*.

    Parameters
    ----------
    master_key:
        The urlsafe-base64-encoded 32-byte master key (ASCII string or
        ``None`` when not yet configured).
    env_var:
        The environment-variable name referenced in error messages so
        operators know which key to fix.  Defaults to
        :data:`BRIDGE_MASTER_KEY_ENV` for backward compatibility.
    missing_exc:
        Exception class raised when *master_key* is absent or malformed.
        Defaults to :class:`BridgeMasterKeyMissing`; callers for other
        key namespaces (e.g. :class:`MCPTokenEncryptor`) pass their own
        subclass so the caller's ``except`` clause stays clean.
    """
    if not master_key:
        raise missing_exc(
            f"{env_var} is not set. Generate a master key with "
            f"`python -c 'from app.security.encryption import generate_master_key; "
            f"print(generate_master_key())'` and export it before starting the api."
        )
    try:
        return Fernet(master_key.encode("ascii") if isinstance(master_key, str) else master_key)
    except (ValueError, TypeError) as exc:
        raise missing_exc(
            f"{env_var} is malformed (must be urlsafe-base64 of 32 bytes): {exc}"
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


@dataclass
class MCPTokenEncryptor:
    """Encrypt and decrypt per-user MCP OAuth tokens at rest.

    Structurally identical to :class:`BridgeTokenEncryptor` but bound to
    :data:`MCP_MASTER_KEY_ENV` (``LQ_AI_MCP_MASTER_KEY``) — a dedicated
    master key so a compromise of the bridge key does not expose MCP tokens
    and vice versa (separate blast radii, per module docstring).

    Constructed once per request scope from :data:`MCP_MASTER_KEY_ENV`
    via :meth:`from_environ`; tests construct directly with their own
    master key to stay hermetic.

    Both :meth:`encrypt` and :meth:`decrypt` operate on ``bytes`` on the
    storage side (the column type is ``bytea`` so the ORM sees ``bytes``)
    and ``str`` on the plaintext side (OAuth tokens are ASCII).
    """

    master_key: str | None

    @classmethod
    def from_environ(cls) -> MCPTokenEncryptor:
        return cls(master_key=os.environ.get(MCP_MASTER_KEY_ENV) or None)

    def encrypt(self, plaintext: str) -> bytes:
        """Wrap ``plaintext`` and return the Fernet token as ``bytes``."""

        if not plaintext:
            raise ValueError("encrypt() requires a non-empty plaintext")
        fernet = _fernet_from(
            self.master_key,
            env_var=MCP_MASTER_KEY_ENV,
            missing_exc=MCPMasterKeyMissing,
        )
        return fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        """Unwrap ``ciphertext`` and return the plaintext string."""

        fernet = _fernet_from(
            self.master_key,
            env_var=MCP_MASTER_KEY_ENV,
            missing_exc=MCPMasterKeyMissing,
        )
        try:
            return fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise MCPEncryptionError(
                f"MCP ciphertext does not decrypt under {MCP_MASTER_KEY_ENV}. "
                f"Wrong master key, or the token was generated with a different one."
            ) from exc
