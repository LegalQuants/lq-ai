"""Runtime provider-key service layer (BYOK hot-apply, Donna #7).

This module encapsulates the apply / revoke / list logic behind the
``/admin/v1/provider-keys`` admin endpoints (Task B). The endpoints stay
thin: they validate the request, resolve the master key, hold the
serialization lock, and delegate the mutation here. Keeping the logic in
a plain module (no FastAPI types in the signatures) makes it directly
unit-testable.

The three operations:

* :func:`list_provider_keys` — a read-only, secret-safe status snapshot of
  every configured provider. Never returns more than the last 4 characters
  of any key.
* :func:`apply_provider_key` — encrypt a plaintext key, persist it to
  ``gateway.yaml`` as ``api_key_encrypted`` (via
  :func:`app.config_writer.upsert_provider_key`, which writes + reloads),
  then **hot-apply** by rebuilding the provider's adapter and swapping it
  into the live registry with no restart.
* :func:`revoke_provider_key` — delete the runtime key (writes + reloads),
  then retire the live adapter. The provider subsequently routes 503.

Secret-handling invariants (this is the security boundary):

* No plaintext or ciphertext is ever logged or returned. ``last4`` is the
  only fragment of a key that escapes this module, and it is capped at 4
  characters and computed only for keys that are at least 4 long.
* The displaced adapter on a hot-swap is **moved** (popped from
  ``app.state.adapters``, appended to ``app.state.retired_adapters``) so it
  lives in exactly one collection — never double-held, never double-closed.
  In-flight requests keep their reference; shutdown closes the retired one.

Concurrency
-----------

The write → reload → swap sequence must not interleave across concurrent
key mutations: two callers reloading and swapping at once could leave the
live registry pointing at an adapter that doesn't match the on-disk config.
The endpoints serialize the whole mutation under
``app.state.provider_key_lock`` (an :class:`asyncio.Lock` installed in the
lifespan). The swap step here additionally pops-then-sets so a reader never
sees a half-applied state.

The SIGHUP-driven reload is intentionally **outside** this lock, and that is
safe: SIGHUP's ``reload_from_disk`` only swaps the in-memory config snapshot
(a GIL-atomic attribute set) and never touches ``app.state.adapters``. Because
the encrypted key is written to disk *before* any reload can re-read it, a
SIGHUP that lands mid-apply still reloads a config that already contains the
new key — the on-disk file is the single source of truth, so the two paths
cannot disagree.
"""

from __future__ import annotations

import logging
from typing import Protocol

from app.config import GatewayConfig
from app.config_holder import MutableConfigHolder
from app.config_writer import delete_provider_key, upsert_provider_key
from app.providers import ProviderAdapter
from app.secrets import MasterKeyMissing, ProviderKeyResolver, encrypt_value

logger = logging.getLogger(__name__)

__all__ = [
    "AppState",
    "apply_provider_key",
    "list_provider_keys",
    "provider_key_status",
    "revoke_provider_key",
]


class AppState(Protocol):
    """The subset of ``app.state`` this module reads and mutates.

    Declared as a :class:`~typing.Protocol` so the service layer stays
    decoupled from FastAPI's dynamically-typed ``State`` object while
    remaining checkable under ``mypy --strict``. The lifespan installs all
    three attributes; tests that exercise the service directly provide a
    small stand-in with the same shape.
    """

    adapters: dict[str, ProviderAdapter]
    retired_adapters: list[ProviderAdapter]


def _key_source(*, api_key_env: str | None, api_key_encrypted: str | None) -> str | None:
    """Classify a provider entry's key source: ``runtime`` / ``env`` / ``None``.

    ``runtime`` (encrypted-at-rest) wins when both are somehow present —
    matching the resolver's precedence — though the config validator
    forbids that combination upfront.
    """

    if api_key_encrypted:
        return "runtime"
    if api_key_env:
        return "env"
    return None


def _safe_last4(
    resolver: ProviderKeyResolver,
    *,
    provider_name: str,
    api_key_env: str | None,
    api_key_encrypted: str | None,
) -> str | None:
    """Return the last 4 chars of the resolved key, or ``None``.

    Wrapped in a broad ``try/except`` so a missing master key, a decrypt
    failure, or any resolver error degrades to ``None`` rather than
    breaking the list. NEVER returns more than 4 characters, and only
    returns a value when the resolved plaintext is at least 4 long.
    """

    try:
        plaintext = resolver.resolve(
            provider_name=provider_name,
            api_key_env=api_key_env,
            api_key_encrypted=api_key_encrypted,
        )
    except Exception:
        # Missing/malformed master key, decrypt error, etc. — the status
        # list must never break on a single bad entry, and we must never
        # surface the failure detail (it could leak ciphertext context).
        return None
    if len(plaintext) < 4:
        return None
    return plaintext[-4:]


def provider_key_status(
    *,
    name: str,
    provider_type: str,
    api_key_env: str | None,
    api_key_encrypted: str | None,
    adapters: dict[str, ProviderAdapter],
    resolver: ProviderKeyResolver,
) -> dict[str, object]:
    """Build the secret-safe status dict for one provider.

    Shape (the only wire shape these endpoints emit)::

        {provider, type, configured, last4, source}

    * ``configured`` is ``name in adapters`` — the adapter built means the
      key resolved and the provider is routable, which is the honest signal
      an operator wants. A keyless / unresolvable provider is ``False``.
    * ``last4`` is computed only when ``configured`` (so we never decrypt a
      key we couldn't build an adapter from) and is capped at 4 chars.
    * ``source`` reflects which key field is set on the config entry.
    """

    configured = name in adapters
    last4 = (
        _safe_last4(
            resolver,
            provider_name=name,
            api_key_env=api_key_env,
            api_key_encrypted=api_key_encrypted,
        )
        if configured
        else None
    )
    return {
        "provider": name,
        "type": provider_type,
        "configured": configured,
        "last4": last4,
        "source": _key_source(
            api_key_env=api_key_env,
            api_key_encrypted=api_key_encrypted,
        ),
    }


def list_provider_keys(
    config: GatewayConfig,
    adapters: dict[str, ProviderAdapter],
    resolver: ProviderKeyResolver,
) -> list[dict[str, object]]:
    """Return a secret-safe status row for every configured provider.

    Pure read: never writes, never raises (per-entry resolve failures
    degrade to ``last4=None``). Never includes a full key.
    """

    return [
        provider_key_status(
            name=provider.name,
            provider_type=provider.type,
            api_key_env=provider.api_key_env,
            api_key_encrypted=provider.api_key_encrypted,
            adapters=adapters,
            resolver=resolver,
        )
        for provider in config.providers
    ]


def _status_for_provider(
    *,
    holder: MutableConfigHolder,
    app_state: AppState,
    provider_name: str,
) -> dict[str, object]:
    """Recompute the single-provider status dict from the live config.

    Built with a fresh ``ProviderKeyResolver.from_environ()`` so the
    master key currently bound to the process is used to derive ``last4``.
    """

    config = holder.current()
    resolver = ProviderKeyResolver.from_environ()
    provider = config.provider_by_name(provider_name)
    if provider is None:
        # The provider vanished between the write and this read — should not
        # happen (upsert/delete operate on existing entries), but stay
        # honest rather than fabricate a row.
        return {
            "provider": provider_name,
            "type": None,
            "configured": False,
            "last4": None,
            "source": None,
        }
    return provider_key_status(
        name=provider.name,
        provider_type=provider.type,
        api_key_env=provider.api_key_env,
        api_key_encrypted=provider.api_key_encrypted,
        adapters=app_state.adapters,
        resolver=resolver,
    )


def _swap_in_adapter(
    *,
    app_state: AppState,
    provider_name: str,
    new_adapter: ProviderAdapter | None,
) -> None:
    """Install (or remove) the live adapter for ``provider_name``.

    MOVE semantics: pop the existing adapter first; if it differs from the
    incoming one, retire it (so shutdown closes it once). Then set the new
    adapter when there is one. When ``new_adapter`` is ``None`` (disabled /
    unsupported type / unresolvable key) the provider is left with no live
    adapter and routes 503.

    Synchronous and lock-free here by design — the caller holds
    ``app.state.provider_key_lock`` across the whole mutation, and we never
    ``await`` between the pop and the set, so no reader observes a torn
    state.
    """

    old = app_state.adapters.pop(provider_name, None)
    if old is not None and old is not new_adapter:
        # Never close in-place: in-flight requests may still hold ``old``.
        # Retire it; the lifespan closes retired adapters at shutdown.
        app_state.retired_adapters.append(old)
    if new_adapter is not None:
        app_state.adapters[provider_name] = new_adapter


async def apply_provider_key(
    *,
    holder: MutableConfigHolder,
    app_state: AppState,
    provider_name: str,
    plaintext: str,
    master_key: str | None,
) -> dict[str, object]:
    """Encrypt + persist a runtime key, then hot-apply the adapter.

    Steps:

    1. Encrypt ``plaintext`` with ``master_key`` (Fernet token).
    2. :func:`upsert_provider_key` — atomic ``gateway.yaml`` write that sets
       ``api_key_encrypted`` (and clears ``api_key_env``), then reloads with
       rollback. Raises :class:`~app.config_writer.ProviderKeyMutationError`
       on an unknown provider (404) / malformed config (500) / reload-
       validation failure.
    3. Hot-apply: read the post-reload :class:`~app.config.ProviderConfig`,
       rebuild its adapter via ``build_adapter`` (imported lazily to dodge
       the ``app.main`` import cycle), and swap it into the live registry.
       A ``None`` adapter (disabled / unsupported type) or a ``ValueError``
       (unresolvable key — should not happen since we just set the key)
       leaves the provider with no live adapter.

    Returns the provider's secret-safe status dict. Raises
    :class:`~app.secrets.MasterKeyMissing` if ``master_key`` is falsy — the
    caller should map that to 400 and is expected to check first; this guard
    is defense-in-depth so we never call ``encrypt_value`` with no key.
    """

    if not master_key:
        raise MasterKeyMissing("runtime key storage requires a master key to be set")

    encrypted_token = encrypt_value(plaintext, master_key=master_key)
    # Writes + reloads (with rollback). May raise ProviderKeyMutationError
    # (404 unknown provider, 500 malformed) which the caller maps to a
    # GatewayError envelope.
    upsert_provider_key(
        holder,
        provider_name=provider_name,
        encrypted_token=encrypted_token,
    )

    # Lazy import to avoid an import cycle: app.main imports the admin
    # router (which imports this module) at module load. Importing
    # build_adapter at call time breaks the cycle.
    from app.main import build_adapter

    provider = holder.current().provider_by_name(provider_name)
    new_adapter: ProviderAdapter | None
    if provider is None:
        # Should be unreachable — upsert_provider_key raises 404 first.
        new_adapter = None
    else:
        try:
            new_adapter = build_adapter(provider)
        except ValueError:
            # A supported, enabled provider whose key still won't resolve.
            # We just wrote the encrypted key, so this is unexpected; treat
            # it as "no live adapter" and surface configured=false rather
            # than crash. The error is not logged with any key material.
            logger.warning(
                "provider %r key applied but adapter build failed; provider has no live adapter",
                provider_name,
            )
            new_adapter = None

    _swap_in_adapter(
        app_state=app_state,
        provider_name=provider_name,
        new_adapter=new_adapter,
    )

    return _status_for_provider(
        holder=holder,
        app_state=app_state,
        provider_name=provider_name,
    )


async def revoke_provider_key(
    *,
    holder: MutableConfigHolder,
    app_state: AppState,
    provider_name: str,
) -> None:
    """Delete a provider's runtime key, then retire its live adapter.

    :func:`delete_provider_key` writes + reloads (raising
    :class:`~app.config_writer.ProviderKeyMutationError` 404 for an unknown
    provider, 409 when the provider has no runtime key to revoke). On
    success the provider's live adapter is popped and retired; the provider
    subsequently routes 503 (no adapter) — the documented revoke behavior.
    """

    delete_provider_key(holder, provider_name=provider_name)

    old = app_state.adapters.pop(provider_name, None)
    if old is not None:
        # Move into the retire list — never close in-place (in-flight
        # requests may hold it); shutdown closes it.
        app_state.retired_adapters.append(old)
