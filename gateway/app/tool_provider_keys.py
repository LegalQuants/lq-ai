"""Service layer for runtime tool-provider management (ADR 0014, Donna #3).

Mirrors ``provider_keys.py`` one layer down: it writes the ``tool_providers``
block via ``config_writer`` and hot-applies by rebuilding the tool adapter and
swapping it into ``app.state.tool_adapters`` in place. Because the Router holds
the SAME dict by reference, the swap is immediately live with no Router rebuild.

Secrets: status rows carry ``has_key: bool`` only — never the ciphertext or a
last4 (tool tokens are opaque; last4 would add leak surface for no UX gain).

``apply_tool_provider`` / ``remove_tool_provider_entry`` are ``async def`` to
match the provider-key path (``apply_provider_key`` / ``revoke_provider_key``
in ``provider_keys.py``): the admin endpoints ``await`` them directly under
``app.state.tool_provider_key_lock`` rather than routing through a threadpool.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import GatewayConfig
from app.config_writer import remove_tool_provider, upsert_tool_provider
from app.secrets import MASTER_KEY_ENV, encrypt_value
from app.tool_provider_defaults import TOOL_PROVIDER_DEFAULTS

logger = logging.getLogger(__name__)


def _source_of(entry: Any) -> str | None:
    if entry is None:
        return None
    if getattr(entry, "api_key_encrypted", None):
        return "runtime"
    if getattr(entry, "api_key_env", None):
        return "env"
    return None


def _status_row(
    *,
    provider_type: str,
    config: GatewayConfig,
    tool_adapters: dict[str, Any],
) -> dict[str, Any]:
    default = TOOL_PROVIDER_DEFAULTS[provider_type]
    entry = next(
        (tp for tp in config.tool_providers if tp.type == provider_type),
        None,
    )
    name = entry.name if entry is not None else default.name
    enabled = entry is not None and name in tool_adapters
    source = _source_of(entry)
    has_key = source is not None
    return {
        "type": provider_type,
        "name": name,
        "enabled": enabled,
        "has_key": has_key,
        "key_required": default.key_required,
        "egress_tier": entry.egress_tier if entry is not None else default.egress_tier,
        "source": source,
    }


def list_tool_provider_status(
    config: GatewayConfig,
    tool_adapters: dict[str, Any],
) -> list[dict[str, Any]]:
    """One secret-safe status row per registered authority type."""

    return [
        _status_row(provider_type=t, config=config, tool_adapters=tool_adapters)
        for t in TOOL_PROVIDER_DEFAULTS
    ]


def _swap_in_tool_adapter(
    *,
    app_state: Any,
    provider_name: str,
    new_adapter: Any | None,
) -> None:
    old = app_state.tool_adapters.pop(provider_name, None)
    if old is not None and old is not new_adapter:
        app_state.retired_tool_adapters.append(old)
    if new_adapter is not None:
        app_state.tool_adapters[provider_name] = new_adapter


async def apply_tool_provider(
    *,
    holder: Any,
    app_state: Any,
    provider_type: str,
    encrypted_token: str | None,
    enabled: bool,
) -> dict[str, Any]:
    """Write the entry + hot-apply the adapter; return the status row."""

    upsert_tool_provider(
        holder,
        provider_type=provider_type,
        encrypted_token=encrypted_token,
        enabled=enabled,
    )

    from app.main import build_tool_adapter  # lazy — break main<->admin cycle

    config = holder.current()
    entry = next((tp for tp in config.tool_providers if tp.type == provider_type), None)
    new_adapter = None
    if entry is not None:
        try:
            new_adapter = build_tool_adapter(entry)
        except Exception:  # never leak key material into the log
            logger.warning(
                "tool provider %r (%s) key applied but adapter build failed; "
                "provider has no live adapter",
                entry.name,
                provider_type,
            )
            new_adapter = None
        _swap_in_tool_adapter(
            app_state=app_state, provider_name=entry.name, new_adapter=new_adapter
        )

    return _status_row(
        provider_type=provider_type, config=config, tool_adapters=app_state.tool_adapters
    )


async def remove_tool_provider_entry(
    *,
    holder: Any,
    app_state: Any,
    provider_type: str,
) -> None:
    """Remove the entry + retire its live adapter."""

    config = holder.current()
    entry = next((tp for tp in config.tool_providers if tp.type == provider_type), None)
    remove_tool_provider(holder, provider_type=provider_type)  # 404/409 raise here
    if entry is not None:
        old = app_state.tool_adapters.pop(entry.name, None)
        if old is not None:
            app_state.retired_tool_adapters.append(old)


def encrypt_tool_provider_key(plaintext: str, *, master_key: str) -> str:
    """Thin wrapper over ``encrypt_value`` for symmetry with provider_keys."""

    return encrypt_value(plaintext, master_key=master_key)


__all__ = [
    "MASTER_KEY_ENV",
    "apply_tool_provider",
    "encrypt_tool_provider_key",
    "list_tool_provider_status",
    "remove_tool_provider_entry",
]
