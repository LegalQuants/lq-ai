"""Encrypted-at-rest secret resolution for ``gateway.yaml`` (ADR 0011).

Provider keys can live in ``gateway.yaml`` in one of two forms:

1. ``api_key_env: ANTHROPIC_API_KEY`` — the environment-variable path
   (existing; keys come from the host environment / .env file). The
   gateway resolves the key by looking up that env var at adapter
   build time.
2. ``api_key_encrypted: gAAAAAB...`` — the encrypted-at-rest path
   (new in ADR 0011). The value is a Fernet-wrapped ciphertext that
   the gateway decrypts using a master key supplied by the operator
   via :envvar:`LQ_AI_GATEWAY_MASTER_KEY`. Decryption happens
   in-memory at adapter build time; the plaintext key never lands on
   disk after the operator runs the encryption helper.

Both paths can coexist — different providers in the same
``gateway.yaml`` can pick whichever fits their threat model.

The master key is a urlsafe-base64 32-byte value generated once by
the operator (e.g., via :func:`generate_master_key`). The operator
stores it however they store other small high-value secrets — a
password manager, a hardware token, a one-line entry in their
secrets vault. The gateway never persists it.

File-mounted delivery (#590, GW-06):

Every secret ``NAME`` may alternatively be supplied via ``NAME_FILE``,
whose value is a filesystem path to a file containing the secret
(Docker Swarm/K8s secret mounts, Vault agent templates, systemd
``LoadCredential=``). Setting both ``NAME`` and ``NAME_FILE`` is a
configuration error — :class:`SecretSourceConflict` is raised rather
than silently preferring one source. File values are stripped of
surrounding whitespace (secret managers commonly append a trailing
newline); an empty-after-strip file raises :class:`SecretFileError`.
World/group-readable files log a warning (expected ``0400``/``0600``)
but still load, so sloppy dev mounts do not hard-fail. Secret values
never appear in log messages or exceptions — only the variable name
and path.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

__all__ = [
    "MASTER_KEY_ENV",
    "DecryptError",
    "MasterKeyMissing",
    "ProviderKeyResolver",
    "SecretFileError",
    "SecretSourceConflict",
    "encrypt_value",
    "generate_master_key",
    "resolve_secret",
]


MASTER_KEY_ENV = "LQ_AI_GATEWAY_MASTER_KEY"
"""Environment variable name the gateway reads to bind its master key."""


class MasterKeyMissing(RuntimeError):
    """Raised when ``api_key_encrypted`` is used but no master key is set."""


class DecryptError(RuntimeError):
    """Raised when an encrypted token cannot be decrypted with the master key.

    The two common causes — wrong master key vs corrupted/tampered
    ciphertext — are indistinguishable by Fernet design (authenticated
    encryption rejects both with the same error). The message names the
    provider so the operator can find the offending entry.
    """


class SecretSourceConflict(RuntimeError):
    """Raised when both ``NAME`` and ``NAME_FILE`` are set.

    The operator must choose one delivery path; the gateway refuses to
    guess so a stale env value can never silently shadow a rotated file
    (or vice versa). The message names the variable only, never values.
    """


class SecretFileError(RuntimeError):
    """Raised when a ``NAME_FILE`` path is missing, unreadable, or empty.

    The message names the variable and path only — never the file
    contents — so it is safe to surface in startup logs.
    """


def _read_secret_file(*, var_name: str, path_str: str) -> str:
    """Read and strip a file-mounted secret.

    Raises :class:`SecretFileError` for missing paths, directories,
    read failures, and empty-after-strip contents. Logs a warning when
    the file is group/world-readable (expected ``0400``/``0600``) but
    still loads it.
    """

    path = Path(path_str)
    if not path.exists() or not path.is_file():
        raise SecretFileError(
            f"{var_name}_FILE points at {path_str!r}, which is missing or not a regular file."
        )
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise SecretFileError(
            f"cannot stat secret file for {var_name}_FILE at {path_str!r}: {exc.strerror or exc}"
        ) from exc
    if mode & 0o077:
        logger.warning(
            "secret file for %s at %r is group/world-accessible (mode %o); "
            "expected 0400 or 0600 owned by the service user",
            var_name,
            path_str,
            mode & 0o777,
        )
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SecretFileError(
            f"cannot read secret file for {var_name}_FILE at {path_str!r}: {exc.strerror or exc}"
        ) from exc
    value = raw.strip()
    if not value:
        raise SecretFileError(f"secret file for {var_name}_FILE at {path_str!r} is empty.")
    return value


def resolve_secret(var_name: str, env: dict[str, str] | None = None) -> str | None:
    """Resolve one secret from ``NAME`` or ``NAME_FILE``.

    Returns the secret value, or ``None`` when neither source is set.
    Raises :class:`SecretSourceConflict` when both are set and
    :class:`SecretFileError` when the file source cannot be read.
    ``env`` defaults to :data:`os.environ`; tests pass an explicit dict
    to stay hermetic.
    """

    source = env if env is not None else dict(os.environ)
    direct = source.get(var_name)
    file_path = source.get(f"{var_name}_FILE")
    direct_set = bool(direct)
    file_set = bool(file_path and file_path.strip())
    if direct_set and file_set:
        raise SecretSourceConflict(
            f"{var_name} and {var_name}_FILE are both set; choose one delivery path."
        )
    if file_set:
        assert file_path is not None
        return _read_secret_file(var_name=var_name, path_str=file_path.strip())
    return direct or None


def generate_master_key() -> str:
    """Generate a fresh urlsafe-base64 master key (32 bytes / 256 bits).

    Used by the encryption CLI helper. The returned string is what the
    operator stores as ``LQ_AI_GATEWAY_MASTER_KEY``.
    """

    return Fernet.generate_key().decode("ascii")


def encrypt_value(plaintext: str, *, master_key: str) -> str:
    """Wrap ``plaintext`` with the master key; return a Fernet token string.

    The returned token is what the operator pastes into ``gateway.yaml``
    under ``api_key_encrypted:``. Each call generates a fresh random
    nonce, so encrypting the same plaintext twice produces different
    tokens — which is correct for AEAD safety, even though it makes
    naive yaml-diff noisy.
    """

    if not plaintext:
        raise ValueError("encrypt_value() requires a non-empty plaintext")
    fernet = _fernet_from(master_key)
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def _fernet_from(master_key: str) -> Fernet:
    """Build a :class:`Fernet` from a master-key string, with a friendly error.

    The ``cryptography`` library raises a generic ``ValueError`` for
    misshapen keys; this wrapper reformats it as a :class:`MasterKeyMissing`
    with the env var name so operators know what to fix.
    """

    if not master_key:
        raise MasterKeyMissing(
            f"{MASTER_KEY_ENV} is not set. Generate a master key with "
            f"`python -m gateway.cli generate-master-key` and export it "
            f"(or mount it via {MASTER_KEY_ENV}_FILE) before starting the gateway."
        )
    try:
        return Fernet(master_key.encode("ascii") if isinstance(master_key, str) else master_key)
    except (ValueError, TypeError) as exc:
        raise MasterKeyMissing(
            f"{MASTER_KEY_ENV} is malformed (must be urlsafe-base64 of 32 bytes): {exc}"
        ) from exc


@dataclass
class ProviderKeyResolver:
    """Resolve provider API keys from gateway.yaml + environment + master key.

    The caller — typically each adapter's ``from_provider_config`` —
    asks the resolver for a single provider's key. The resolver tries
    the encrypted-at-rest path first (when the provider entry has
    ``api_key_encrypted``), then falls back to the env-var path
    (``api_key_env``), then returns ``""`` for providers that
    legitimately have no key (e.g., local Ollama).

    Storing the master key on the resolver instance lets adapters
    fetch it once at gateway lifespan startup and pass the resolver
    through; we don't re-read :envvar:`LQ_AI_GATEWAY_MASTER_KEY` on
    every key lookup. That also keeps tests hermetic — they can
    construct a resolver with their own master key + env mapping.
    """

    master_key: str | None
    """Operator-supplied master key, or ``None`` when no encrypted
    keys are in use. Encrypted-key lookups will raise
    :class:`MasterKeyMissing` when ``master_key`` is ``None``."""

    env: dict[str, str]
    """Snapshot of the environment used for ``api_key_env`` lookups.
    Defaults to :data:`os.environ` via :meth:`from_environ`."""

    @classmethod
    def from_environ(cls) -> ProviderKeyResolver:
        """Build a resolver from process environment.

        The master key is taken from :envvar:`LQ_AI_GATEWAY_MASTER_KEY`
        or ``LQ_AI_GATEWAY_MASTER_KEY_FILE``; :data:`None` when unset
        (which is fine when no provider uses the encrypted path).
        A conflicting or unreadable file source raises immediately so
        the gateway refuses to start rather than running half-configured.
        """

        return cls(
            master_key=resolve_secret(MASTER_KEY_ENV),
            env=dict(os.environ),
        )

    @classmethod
    def from_env_dict(cls, env: dict[str, str]) -> ProviderKeyResolver:
        """Build a resolver from an explicit env mapping (adapters/tests).

        Mirrors :meth:`from_environ` but reads ``MASTER_KEY_ENV`` via
        :func:`resolve_secret` against the supplied mapping so
        ``*_FILE`` delivery works when adapters pass ``env=`` explicitly.
        """

        return cls(
            master_key=resolve_secret(MASTER_KEY_ENV, env),
            env=dict(env),
        )

    def resolve(
        self,
        *,
        provider_name: str,
        api_key_env: str | None,
        api_key_encrypted: str | None,
    ) -> str:
        """Return the resolved plaintext key for one provider entry.

        Precedence:

        1. ``api_key_encrypted`` set → decrypt with the master key.
           Raises :class:`MasterKeyMissing` if the master key is unset
           or malformed; raises :class:`DecryptError` if the ciphertext
           doesn't decrypt under the configured master key.
        2. ``api_key_env`` set → look up that env var or its ``_FILE``
           sibling (``ANTHROPIC_API_KEY`` / ``ANTHROPIC_API_KEY_FILE``);
           ``""`` if unset. A missing/unreadable/empty file degrades to
           ``""`` with a warning so the provider is skipped like any
           other missing key; setting both ``NAME`` and ``NAME_FILE``
           raises :class:`SecretSourceConflict` (ambiguous — fail, never
           guess). The env-only form is preserved for backward
           compatibility per ADR 0011.
        3. Both unset → ``""`` (legitimately keyless provider).

        Mixing both ``api_key_encrypted`` and ``api_key_env`` on a
        single provider entry is a configuration error: the resolver
        prefers the encrypted path silently in that case, but the
        config loader's validator should refuse it upfront.
        """

        if api_key_encrypted:
            fernet = _fernet_from(self.master_key or "")
            try:
                return fernet.decrypt(api_key_encrypted.encode("ascii")).decode("utf-8")
            except InvalidToken as exc:
                raise DecryptError(
                    f"Provider {provider_name!r}: api_key_encrypted does not "
                    f"decrypt under {MASTER_KEY_ENV}. Wrong master key, or the "
                    f"token was generated with a different one."
                ) from exc
        if api_key_env:
            try:
                return resolve_secret(api_key_env, self.env) or ""
            except SecretFileError as exc:
                logger.warning(
                    "skipping provider %r: %s",
                    provider_name,
                    exc,
                )
                return ""
        return ""


def _is_constant_time_equal(a: str, b: str) -> bool:
    """Constant-time string equality (re-export of secrets.compare_digest).

    Not used by the resolver itself, but exposed here so callers that
    compare resolved keys (e.g., the gateway-key check on inbound
    requests) can avoid timing leaks without importing :mod:`secrets`
    everywhere.
    """

    return secrets.compare_digest(a, b)
