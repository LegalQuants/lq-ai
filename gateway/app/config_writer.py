"""Atomic writes for ``gateway.yaml`` (D0.5).

The admin alias-CRUD endpoints (PATCH/POST/DELETE on ``/admin/v1/aliases/*``)
mutate the loaded gateway configuration. To keep the on-disk file the
single source of truth (per ADR 0010), every mutation:

1. Loads the **raw YAML** mapping from disk (so unrelated comments,
   ordering, and operator-specific keys we don't model are preserved).
2. Applies a small, surgical transformation to the ``model_aliases``
   block.
3. Writes the result to a sibling temp file and ``os.replace``-s it
   into place — atomic on POSIX (the rename is the commit point).
4. Asks the :class:`MutableConfigHolder` to reload from disk; if the
   reloaded config fails Pydantic validation, the holder rolls back
   the live snapshot and the route returns 422 with a structured
   error.

We deliberately use the raw YAML round-trip rather than re-emitting
``GatewayConfig.model_dump()``: comments and operator-specific extra
keys live in the file today, and Pydantic ``extra="allow"`` keeps
them in the model, but ``model_dump()`` does not preserve YAML-level
comments. Round-tripping the raw mapping preserves the example file's
extensive operator-facing comments.

Concurrency
-----------

The temp-and-rename pattern means concurrent writes are last-write-wins
without ever producing a torn file (every reader sees either the old
file or the new one). The :class:`MutableConfigHolder._lock` serializes
the in-process reload step, so the live snapshot also can't tear.

Operators who run more than one gateway replica against the *same*
mounted file would still get last-write-wins between replicas (the
file is the shared state) — that's documented in ADR 0010 as a known
limitation. Single-replica deployments (the M1 default) are unaffected.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from app.config_holder import ConfigReloadError, MutableConfigHolder
from app.tool_provider_defaults import TOOL_PROVIDER_DEFAULTS

logger = logging.getLogger(__name__)


class AliasMutationError(ValueError):
    """Raised when an alias mutation cannot be applied (404, 409, 422).

    Carries an HTTP-status hint via :attr:`http_status` so the route
    handler can map cleanly without parsing the message string.
    """

    def __init__(self, message: str, *, http_status: int) -> None:
        super().__init__(message)
        self.http_status = http_status


class ProviderKeyMutationError(ValueError):
    """Raised when a provider-key mutation cannot be applied (404, 409, 500).

    Sibling of :class:`AliasMutationError` for the runtime BYOK
    (Donna #7) provider-key endpoints. Carries an HTTP-status hint via
    :attr:`http_status` so the route handler (Task B) can map cleanly
    without parsing the message string. We keep this distinct from the
    alias-named error so the two surfaces don't accidentally share
    status semantics.
    """

    def __init__(self, message: str, *, http_status: int) -> None:
        super().__init__(message)
        self.http_status = http_status


def _read_yaml_mapping(config_path: Path) -> dict[str, Any]:
    """Read the YAML file as a plain dict (no env-var expansion).

    The on-disk file is the source of truth; we round-trip the raw
    structure so unrelated keys / operator overrides survive.
    """

    if not config_path.is_file():
        raise AliasMutationError(
            f"gateway config not found at {config_path}",
            http_status=500,
        )
    raw_text = config_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw_text)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise AliasMutationError(
            f"gateway config {config_path} is not a YAML mapping at the top level",
            http_status=500,
        )
    return parsed


def _atomic_write_yaml(config_path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` to ``config_path`` atomically.

    Uses :func:`tempfile.NamedTemporaryFile` in the same directory as
    the target so :func:`os.replace` is a same-filesystem rename
    (atomic on POSIX). On any failure mid-write the temp file is
    cleaned up and the original is untouched.
    """

    target_dir = config_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    # ``delete=False`` so the file persists after the `with` block — we
    # rename it onto config_path ourselves below, and the suppress-on-
    # failure block handles cleanup so we never leak temp files.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".tmp",
        prefix=f".{config_path.name}.",
        dir=str(target_dir),
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        # ``sort_keys=False`` preserves the operator's section ordering
        # (providers → model_aliases → inference_tiers → ...) so a diff
        # against the prior file is small and reviewable.
        yaml.safe_dump(
            data,
            tmp,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )
        tmp.flush()
        os.fsync(tmp.fileno())

    try:
        os.replace(tmp_path, config_path)
    except OSError:
        # Replace failed — clean up the orphaned temp file before
        # surfacing the error.
        with contextlib.suppress(OSError):  # pragma: no cover - cleanup best-effort
            tmp_path.unlink()
        raise


# --- Alias-shape helpers -----------------------------------------------------


def _validate_alias_payload(
    *,
    provider: str,
    model: str,
    fallback: list[dict[str, str]] | None,
    configured_provider_names: set[str],
) -> None:
    """Validate a write payload against the loaded provider list.

    Raises :class:`AliasMutationError` (422) for any malformation. The
    Pydantic re-validation that runs after the file write would catch
    most of these, but a tight pre-check produces clearer error
    messages for the operator.
    """

    if not isinstance(provider, str) or not provider.strip():
        raise AliasMutationError(
            "alias.provider must be a non-empty string",
            http_status=422,
        )
    if provider not in configured_provider_names:
        raise AliasMutationError(
            f"alias.provider {provider!r} is not a configured provider; "
            f"configured providers: {sorted(configured_provider_names)}",
            http_status=422,
        )
    if not isinstance(model, str) or not model.strip():
        raise AliasMutationError(
            "alias.model must be a non-empty string",
            http_status=422,
        )
    if fallback is None:
        return
    if not isinstance(fallback, list):
        raise AliasMutationError(
            "alias.fallback must be a list of {provider, model} entries",
            http_status=422,
        )
    for idx, entry in enumerate(fallback):
        if not isinstance(entry, dict):
            raise AliasMutationError(
                f"alias.fallback[{idx}] must be an object with provider+model",
                http_status=422,
            )
        fb_provider = entry.get("provider")
        fb_model = entry.get("model")
        if not isinstance(fb_provider, str) or not fb_provider.strip():
            raise AliasMutationError(
                f"alias.fallback[{idx}].provider must be a non-empty string",
                http_status=422,
            )
        if fb_provider not in configured_provider_names:
            raise AliasMutationError(
                f"alias.fallback[{idx}].provider {fb_provider!r} is not configured",
                http_status=422,
            )
        if not isinstance(fb_model, str) or not fb_model.strip():
            raise AliasMutationError(
                f"alias.fallback[{idx}].model must be a non-empty string",
                http_status=422,
            )


def _alias_to_yaml_block(
    *,
    provider: str,
    model: str,
    fallback: list[dict[str, str]] | None,
) -> dict[str, Any]:
    """Build the YAML representation of a single alias entry."""

    block: dict[str, Any] = {
        "primary": {"provider": provider, "model": model},
    }
    if fallback is not None:
        block["fallback"] = [
            {"provider": entry["provider"], "model": entry["model"]} for entry in fallback
        ]
    else:
        block["fallback"] = []
    return block


# --- Public mutation API -----------------------------------------------------


def upsert_alias(
    holder: MutableConfigHolder,
    *,
    name: str,
    provider: str,
    model: str,
    fallback: list[dict[str, str]] | None,
    create_only: bool = False,
    update_only: bool = False,
) -> None:
    """Write or modify an alias. Reload + validate; raise on failure.

    ``create_only=True`` raises 409 if the alias already exists (POST
    semantics). ``update_only=True`` raises 404 if the alias does not
    exist (PATCH semantics). The default (both False) is upsert.

    Validates the payload against the **current** in-memory config's
    provider list. After writing, triggers a hot-reload; if that fails
    validation the holder retains the prior snapshot and the file
    write is rolled back to the prior bytes (best-effort).
    """

    # Snapshot the current config for pre-write validation. We don't
    # hold any lock here — the holder's per-attribute read is atomic,
    # and any concurrent writer is serialized by the holder's lock
    # during the actual swap.
    current = holder.current()
    configured_providers = {p.name for p in current.providers}
    _validate_alias_payload(
        provider=provider,
        model=model,
        fallback=fallback,
        configured_provider_names=configured_providers,
    )

    # Read-modify-write the on-disk YAML.
    raw = _read_yaml_mapping(holder.config_path)
    aliases = raw.get("model_aliases")
    if aliases is None:
        aliases = {}
        raw["model_aliases"] = aliases
    if not isinstance(aliases, dict):
        raise AliasMutationError(
            "gateway.yaml model_aliases is malformed (expected a mapping)",
            http_status=500,
        )

    exists = name in aliases
    if create_only and exists:
        raise AliasMutationError(
            f"alias {name!r} already exists",
            http_status=409,
        )
    if update_only and not exists:
        raise AliasMutationError(
            f"alias {name!r} not found",
            http_status=404,
        )

    aliases[name] = _alias_to_yaml_block(
        provider=provider,
        model=model,
        fallback=fallback,
    )

    # Stash the old bytes for rollback.
    prior_bytes = holder.config_path.read_bytes()

    _atomic_write_yaml(holder.config_path, raw)

    try:
        holder.reload_from_disk()
    except ConfigReloadError:
        # Roll back the file so the on-disk state matches the in-memory
        # snapshot. The holder already reverted (or never advanced) the
        # in-process config; we just need the file to agree.
        holder.config_path.write_bytes(prior_bytes)
        raise


def delete_alias(
    holder: MutableConfigHolder,
    *,
    name: str,
) -> None:
    """Remove an alias. 404 if it does not exist; 409 if it's a tier default.

    We don't check tier defaults today — there is no concept of "this
    alias is the default for this tier" in the schema. A future D-phase
    task may add ``tier_policy.default_alias`` or similar; the 409
    branch is reserved for that future check (and a comment-only
    placeholder lives below so the contract documented in the OpenAPI
    sketch matches what the code can produce).
    """

    raw = _read_yaml_mapping(holder.config_path)
    aliases = raw.get("model_aliases")
    if not isinstance(aliases, dict) or name not in aliases:
        raise AliasMutationError(
            f"alias {name!r} not found",
            http_status=404,
        )

    # Reserved for a future "this alias is a tier default" check.
    # For now no schema field expresses that concept; a D1+ task that
    # introduces one should add a 409 here naming the tier(s) that
    # depend on this alias. Documented in ADR 0010.

    del aliases[name]

    prior_bytes = holder.config_path.read_bytes()
    _atomic_write_yaml(holder.config_path, raw)
    try:
        holder.reload_from_disk()
    except ConfigReloadError:
        holder.config_path.write_bytes(prior_bytes)
        raise


def update_tier_policy(
    holder: MutableConfigHolder,
    *,
    allowed_tiers_global: list[int] | None = None,
    default_minimum_tier: int | None = None,
    privileged_minimum_tier: int | None = None,
    warn_on_tiers: list[int] | None = None,
) -> dict[str, Any]:
    """Apply a partial update to ``tier_policy`` and reload.

    Wave B of the M1 backend gap-fill. Same temp-file + atomic-replace
    + reload-with-rollback pattern as ``upsert_alias`` — the only
    structural difference is that ``tier_policy`` is a single block
    rather than a keyed mapping, so the merge is field-wise rather
    than key-wise.

    Returns the new ``tier_policy`` block as a dict so the caller
    (the admin endpoint) can echo it back without re-reading the
    file.

    Raises :class:`AliasMutationError` with ``http_status=422`` if
    the merged payload fails Pydantic re-validation on reload (e.g.,
    an empty ``allowed_tiers_global`` list, a tier outside 1-5).
    """

    raw = _read_yaml_mapping(holder.config_path)
    tier_policy = raw.get("tier_policy")
    if not isinstance(tier_policy, dict):
        tier_policy = {}
        raw["tier_policy"] = tier_policy

    if allowed_tiers_global is not None:
        tier_policy["allowed_tiers_global"] = list(allowed_tiers_global)
    if default_minimum_tier is not None:
        tier_policy["default_minimum_tier"] = int(default_minimum_tier)
    if privileged_minimum_tier is not None:
        tier_policy["privileged_minimum_tier"] = int(privileged_minimum_tier)
    if warn_on_tiers is not None:
        tier_policy["warn_on_tiers"] = list(warn_on_tiers)

    prior_bytes = holder.config_path.read_bytes()
    _atomic_write_yaml(holder.config_path, raw)
    try:
        holder.reload_from_disk()
    except ConfigReloadError as exc:
        holder.config_path.write_bytes(prior_bytes)
        raise AliasMutationError(
            f"tier_policy update failed validation: {exc}",
            http_status=422,
        ) from exc

    return dict(holder.current().tier_policy.model_dump(mode="json"))


# --- Provider-key mutation API (runtime BYOK, Donna #7) ----------------------


def _find_provider_entry(
    raw: dict[str, Any],
    *,
    provider_name: str,
) -> dict[str, Any]:
    """Locate the ``providers:`` list entry whose ``name`` matches.

    ``providers`` is a YAML *list* of mappings (unlike ``model_aliases``,
    which is a keyed mapping). We round-trip the raw list so unrelated
    provider-specific keys (``base_url``, ``tier``, ``api_version``,
    operator extras) survive the write.

    Raises :class:`ProviderKeyMutationError` 500 when ``providers`` is
    missing or not a list (malformed config), and 404 when no entry
    matches ``provider_name``.
    """

    providers = raw.get("providers")
    if not isinstance(providers, list):
        raise ProviderKeyMutationError(
            "gateway.yaml providers is missing or malformed (expected a list)",
            http_status=500,
        )
    for entry in providers:
        if isinstance(entry, dict) and entry.get("name") == provider_name:
            return entry
    raise ProviderKeyMutationError(
        f"provider {provider_name!r} not found",
        http_status=404,
    )


def upsert_provider_key(
    holder: MutableConfigHolder,
    *,
    provider_name: str,
    encrypted_token: str,
) -> None:
    """Set a provider's runtime ``api_key_encrypted`` and reload.

    Scope: managing the key on an **existing** provider entry only.
    Adding a brand-new provider (with type/base_url/tier) is out of
    scope for this API — those land through the operator's edit of
    ``gateway.yaml`` directly.

    Setting a runtime key switches the entry's key source to the
    encrypted-at-rest path: we set ``api_key_encrypted`` and clear any
    ``api_key_env`` (the :class:`~app.config.ProviderConfig` validator
    refuses both, so the env key must be dropped). The reload then
    re-validates the whole file; on failure the file is rolled back to
    the prior bytes and :class:`ConfigReloadError` re-raised (the exact
    ``upsert_alias`` rollback pattern).

    Raises :class:`ProviderKeyMutationError` 404 if no provider matches
    ``provider_name`` (500 if the providers list is malformed, 422 if the
    encrypted token is empty).
    """

    if not encrypted_token:
        # ``encrypt_value`` already rejects empty plaintext, so a real
        # ciphertext is never empty — this just keeps the contract honest
        # if a route ever passes a malformed body and prevents an upsert
        # from silently producing a keyless provider.
        raise ProviderKeyMutationError(
            "encrypted_token must be non-empty",
            http_status=422,
        )

    raw = _read_yaml_mapping(holder.config_path)
    entry = _find_provider_entry(raw, provider_name=provider_name)

    entry["api_key_encrypted"] = encrypted_token
    # Source becomes runtime; the validator forbids both key sources.
    entry.pop("api_key_env", None)

    prior_bytes = holder.config_path.read_bytes()
    _atomic_write_yaml(holder.config_path, raw)
    try:
        holder.reload_from_disk()
    except ConfigReloadError:
        holder.config_path.write_bytes(prior_bytes)
        raise


def delete_provider_key(
    holder: MutableConfigHolder,
    *,
    provider_name: str,
) -> None:
    """Revoke a provider's runtime ``api_key_encrypted`` and reload.

    Only runtime (encrypted-at-rest) keys can be revoked through this
    API. An env-sourced key (``api_key_env``) is owned by the operator's
    environment, not the gateway file; attempting to revoke one raises
    409 (documented behavior). A now-keyless provider entry is still
    valid config — its adapter simply won't build, and Task B's
    hot-apply pops it from the live registry.

    Raises :class:`ProviderKeyMutationError` 404 if no provider matches,
    409 if the matched provider has no runtime key to revoke.
    """

    raw = _read_yaml_mapping(holder.config_path)
    entry = _find_provider_entry(raw, provider_name=provider_name)

    if "api_key_encrypted" not in entry:
        raise ProviderKeyMutationError(
            f"provider {provider_name!r} has no runtime key to revoke",
            http_status=409,
        )

    entry.pop("api_key_encrypted", None)

    prior_bytes = holder.config_path.read_bytes()
    _atomic_write_yaml(holder.config_path, raw)
    try:
        holder.reload_from_disk()
    except ConfigReloadError:
        holder.config_path.write_bytes(prior_bytes)
        raise


# --- Tool-provider mutation API (runtime authority sources, ADR 0014) --------


def _find_tool_provider_entry(
    raw: dict[str, Any],
    *,
    provider_type: str,
) -> dict[str, Any] | None:
    """Return the ``tool_providers`` entry for ``provider_type``, or None.

    Unlike ``_find_provider_entry`` (inference), absence is NOT an error:
    the runtime enable path CREATES the entry when it's missing. We match on
    ``type`` (the admin surface is keyed by type; the writer owns the name).

    Raises :class:`ProviderKeyMutationError` 500 only when ``tool_providers``
    is present but not a list (malformed config).
    """

    providers = raw.get("tool_providers")
    if providers is None:
        return None
    if not isinstance(providers, list):
        raise ProviderKeyMutationError(
            "gateway.yaml tool_providers is malformed (expected a list)",
            http_status=500,
        )
    for entry in providers:
        if isinstance(entry, dict) and entry.get("type") == provider_type:
            return entry
    return None


def _tool_provider_entry_from_default(provider_type: str) -> dict[str, Any]:
    """Build a fresh ``tool_providers`` YAML block from the gateway defaults."""

    d = TOOL_PROVIDER_DEFAULTS[provider_type]
    entry: dict[str, Any] = {
        "name": d.name,
        "type": d.type,
        "base_url": d.base_url,
        "egress_tier": d.egress_tier,
        "allowlist": {"hosts": list(d.allowlist_hosts)},
        "rate_limit": {"requests_per_minute": d.rate_limit_rpm},
        "anonymize_outbound": d.anonymize_outbound,
    }
    if d.user_agent:
        entry["user_agent"] = d.user_agent
    return entry


def upsert_tool_provider(
    holder: MutableConfigHolder,
    *,
    provider_type: str,
    encrypted_token: str | None,
    enabled: bool = True,
) -> None:
    """Create/enable a tool-provider entry and set/rotate its runtime key.

    ``provider_type`` must be a key in ``TOOL_PROVIDER_DEFAULTS`` (else 404).
    If the entry is absent it's created from the gateway defaults (SSRF-safe;
    the api never supplies base_url/allowlist). ``encrypted_token`` is the
    Fernet ciphertext (set/rotate); ``None`` leaves the key untouched on an
    existing entry, or creates a keyless entry when none exists.

    Setting a runtime key switches the source to encrypted-at-rest: we set
    ``api_key_encrypted`` and drop ``api_key_env`` (the validator forbids
    both). Reload re-validates the whole file; on failure the file rolls back
    to the prior bytes and :class:`ConfigReloadError` re-raises.
    """

    if provider_type not in TOOL_PROVIDER_DEFAULTS:
        raise ProviderKeyMutationError(
            f"unknown tool-provider type {provider_type!r}",
            http_status=404,
        )

    raw = _read_yaml_mapping(holder.config_path)
    tool_providers = raw.get("tool_providers")
    if tool_providers is None:
        tool_providers = []
        raw["tool_providers"] = tool_providers
    elif not isinstance(tool_providers, list):
        raise ProviderKeyMutationError(
            "gateway.yaml tool_providers is malformed (expected a list)",
            http_status=500,
        )

    entry = _find_tool_provider_entry(raw, provider_type=provider_type)
    if entry is None:
        entry = _tool_provider_entry_from_default(provider_type)
        tool_providers.append(entry)

    entry["enabled"] = enabled
    if encrypted_token is not None:
        entry["api_key_encrypted"] = encrypted_token
        entry.pop("api_key_env", None)

    prior_bytes = holder.config_path.read_bytes()
    _atomic_write_yaml(holder.config_path, raw)
    try:
        holder.reload_from_disk()
    except ConfigReloadError:
        holder.config_path.write_bytes(prior_bytes)
        raise


def remove_tool_provider(
    holder: MutableConfigHolder,
    *,
    provider_type: str,
) -> None:
    """Remove a runtime-owned tool-provider entry and reload.

    404 if no entry of that type exists. 409 if the matched entry is
    env-sourced (``api_key_env`` set) — the runtime API only removes entries
    it owns (runtime-keyed or keyless); an operator's env-configured entry is
    theirs to remove in ``gateway.yaml``.
    """

    raw = _read_yaml_mapping(holder.config_path)
    entry = _find_tool_provider_entry(raw, provider_type=provider_type)
    if entry is None:
        raise ProviderKeyMutationError(
            f"tool provider of type {provider_type!r} not found",
            http_status=404,
        )
    if entry.get("api_key_env"):
        raise ProviderKeyMutationError(
            f"tool provider {provider_type!r} is env-configured and not "
            "runtime-revocable; edit gateway.yaml to remove it",
            http_status=409,
        )

    providers = raw["tool_providers"]
    raw["tool_providers"] = [e for e in providers if e is not entry]

    prior_bytes = holder.config_path.read_bytes()
    _atomic_write_yaml(holder.config_path, raw)
    try:
        holder.reload_from_disk()
    except ConfigReloadError:
        holder.config_path.write_bytes(prior_bytes)
        raise


__all__ = [
    "AliasMutationError",
    "ProviderKeyMutationError",
    "delete_alias",
    "delete_provider_key",
    "remove_tool_provider",
    "update_tier_policy",
    "upsert_alias",
    "upsert_provider_key",
    "upsert_tool_provider",
]
