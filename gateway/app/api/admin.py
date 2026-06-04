"""Admin endpoints under ``/admin/v1/...`` (PRD §4.5; D0.5).

Surface (current):

* ``GET    /admin/v1/config``                 — sanitized current config (D0.5)
* ``GET    /admin/v1/aliases``                — list configured aliases (D0.5)
* ``GET    /admin/v1/aliases/{name}``         — single-alias detail (D0.5)
* ``POST   /admin/v1/aliases``                — create alias (D0.5)
* ``PATCH  /admin/v1/aliases/{name}``         — update alias (D0.5)
* ``DELETE /admin/v1/aliases/{name}``         — remove alias (D0.5)
* ``GET    /admin/v1/tier-config``            — tier policy block (A3)
* ``GET    /admin/v1/providers/health``       — 501 stub
* ``GET    /admin/v1/usage``                  — 501 stub
* ``GET    /admin/v1/anonymization-config``   — loaded anonymization block (M2)

Auth: every endpoint here is gated by
:func:`app.api.dependencies.make_require_gateway_key` — the same shared
secret the backend already holds. Per ADR 0010, the user-level
``is_admin`` check is the **backend's** responsibility (the gateway
has no concept of users); requests that arrive at the gateway have
already passed the backend's admin gate.

Hot-reload semantics: write endpoints (POST/PATCH/DELETE) update the
on-disk YAML atomically, then trigger a re-read through
:meth:`MutableConfigHolder.reload_from_disk`. If the new config fails
Pydantic validation the holder retains the prior snapshot and the
endpoint returns 422 with a structured error; the file write is
rolled back to the prior bytes on a best-effort basis.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import make_require_gateway_key
from app.config import GatewayConfig, ModelAliasConfig
from app.config_holder import ConfigReloadError, MutableConfigHolder
from app.config_writer import (
    AliasMutationError,
    ProviderKeyMutationError,
    delete_alias,
    update_tier_policy,
    upsert_alias,
)
from app.provider_keys import apply_provider_key, list_provider_keys, revoke_provider_key
from app.router import derive_routed_inference_tier
from app.secrets import MASTER_KEY_ENV, ProviderKeyResolver

require_gateway_key = make_require_gateway_key()

router = APIRouter(
    prefix="/admin/v1",
    tags=["admin"],
    dependencies=[Depends(require_gateway_key)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(request: Request) -> GatewayConfig:
    """Read the live config snapshot off ``app.state``."""

    holder: MutableConfigHolder | None = getattr(request.app.state, "config_holder", None)
    if holder is not None:
        return holder.current()
    return request.app.state.config  # type: ignore[no-any-return]


def _holder(request: Request) -> MutableConfigHolder:
    """Pull the :class:`MutableConfigHolder` off ``app.state`` (write paths)."""

    holder: MutableConfigHolder | None = getattr(request.app.state, "config_holder", None)
    if holder is None:
        # Tests may bypass lifespan; they should install the holder via a
        # fixture before exercising the write endpoints.
        raise RuntimeError(
            "gateway config holder not installed on app.state; "
            "the admin write endpoints require a lifespan-built app"
        )
    return holder


def _gateway_error(
    *,
    code: str,
    message: str,
    http_status: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Render the canonical ``GatewayError`` envelope."""

    return JSONResponse(
        status_code=http_status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
    )


def _not_implemented(*, message: str, next_task: str) -> JSONResponse:
    return _gateway_error(
        code="not_implemented",
        message=message,
        http_status=status.HTTP_501_NOT_IMPLEMENTED,
        details={"next_task": next_task},
    )


def _alias_to_payload(name: str, alias: ModelAliasConfig) -> dict[str, Any]:
    """Render a single alias as the admin-API JSON shape.

    Wire shape (matches the OpenAPI sketch, see the docs/api/ update
    that lands with D0.5):

    .. code-block:: json

        {
          "name": "smart",
          "provider": "anthropic-prod",
          "model": "claude-opus-4-7",
          "fallback": [{"provider": "...", "model": "..."}]
        }
    """

    return {
        "name": name,
        "provider": alias.primary.provider,
        "model": alias.primary.model,
        "fallback": [{"provider": fb.provider, "model": fb.model} for fb in alias.fallback],
    }


def _sanitized_config_payload(config: GatewayConfig) -> dict[str, Any]:
    """Build the GET /admin/v1/config payload — secrets stripped.

    What we expose: provider entries (without sensitive fields like
    ``api_key_env`` *values* — only the variable *name* is safe to
    show), model_aliases, inference_tiers, tier_policy, cost_tracking
    rates, anonymization (M2 settings), gateway_auth (without the
    secret).

    What we strip: nothing today — the schema only stores env-var
    *names*, never values. We keep this helper as the single
    chokepoint so future fields that *do* hold secrets get scrubbed
    here in one place.
    """

    payload = config.model_dump(mode="json")
    # Defense-in-depth: the schema doesn't put real secrets in this
    # struct (env-var names only), but if a future field ever does,
    # stripping it here is the right place. Today this is a no-op.
    return payload


# ---------------------------------------------------------------------------
# Schemas (D0.5)
# ---------------------------------------------------------------------------


class _FallbackEntry(BaseModel):
    """One ``fallback`` list entry on an alias write."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class AliasCreateRequest(BaseModel):
    """``POST /admin/v1/aliases`` body (D0.5)."""

    name: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    fallback: list[_FallbackEntry] | None = None


class AliasUpdateRequest(BaseModel):
    """``PATCH /admin/v1/aliases/{name}`` body (D0.5)."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    fallback: list[_FallbackEntry] | None = None


class ProviderKeySetRequest(BaseModel):
    """``POST /admin/v1/provider-keys`` body (Donna #7).

    ``api_key`` is the plaintext provider key. It is encrypted with the
    gateway master key before it touches disk and is NEVER echoed back in
    any response. ``min_length=1`` rejects an empty key at the edge.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    api_key: str = Field(min_length=1)


class ProviderKeyRotateRequest(BaseModel):
    """``PATCH /admin/v1/provider-keys/{provider}`` body (Donna #7).

    Rotate the runtime key on an already-configured provider. Same
    secret-handling as :class:`ProviderKeySetRequest`; the provider comes
    from the path.
    """

    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Existing surface (A3)
# ---------------------------------------------------------------------------


@router.get("/providers/health")
async def providers_health(request: Request) -> JSONResponse:
    """Per-provider health probe — 501 until provider adapters land (B3+)."""

    return _not_implemented(
        message=(
            "Provider health probes are not yet implemented. Provider "
            "adapters land starting at B3 (Anthropic); this endpoint becomes "
            "real once an adapter has a health-probe contract to call."
        ),
        next_task="B3 — Anthropic provider adapter",
    )


@router.get("/usage")
async def usage(request: Request) -> JSONResponse:
    """Per-key/per-model usage and cost — 501 until cost tracking lands."""

    return _not_implemented(
        message=(
            "Usage and cost reporting are not yet implemented. The cost "
            "tracker is wired after the first provider adapter lands."
        ),
        next_task="post-B3 — cost tracker",
    )


@router.get("/tier-config")
async def get_tier_config(request: Request) -> dict[str, Any]:
    """Return the loaded ``tier_policy`` block from ``gateway.yaml``."""

    cfg = _config(request)
    return {"tier_policy": cfg.tier_policy.model_dump(mode="json")}


class TierPolicyPatch(BaseModel):
    """``PATCH /admin/v1/tier-config`` body (Wave B).

    All fields optional — only supplied keys are written to disk. The
    write is atomic + reloaded; if the merged config fails Pydantic
    re-validation (e.g., empty ``allowed_tiers_global``), the on-disk
    file is rolled back and the response is 422 with the validation
    error.
    """

    model_config = ConfigDict(extra="forbid")

    allowed_tiers_global: list[int] | None = Field(default=None)
    default_minimum_tier: int | None = Field(default=None, ge=1, le=5)
    privileged_minimum_tier: int | None = Field(default=None, ge=1, le=5)
    warn_on_tiers: list[int] | None = Field(default=None)


@router.patch("/tier-config", response_model=None)
async def patch_tier_config(
    request: Request, body: TierPolicyPatch
) -> dict[str, Any] | JSONResponse:
    """Update the operator's ``tier_policy`` block (Wave B).

    Partial update — only supplied fields move. Writes through to
    ``gateway.yaml`` atomically; the live config snapshot reloads on
    success. On validation failure the on-disk file rolls back.
    """

    holder = _holder(request)
    payload = body.model_dump(exclude_none=True)
    if not payload:
        return {"tier_policy": holder.current().tier_policy.model_dump(mode="json")}

    try:
        updated = update_tier_policy(holder, **payload)
    except AliasMutationError as exc:
        return _gateway_error(
            code="invalid_tier_policy",
            message=str(exc),
            http_status=exc.http_status,
        )
    return {"tier_policy": updated}


@router.get("/anonymization-config")
async def get_anonymization_config(request: Request) -> dict[str, Any]:
    """Return the loaded ``anonymization`` block from ``gateway.yaml``.

    The M2 middleware shipped and runs (pre/post pseudonymization wired in
    :mod:`app.main`; PRD §4.7), so this read surface exposes the live config
    instead of a 501. ``enabled`` and ``apply_at_tiers`` are typed; the
    remaining keys (``entity_types`` etc.) pass through under ``extra="allow"``
    and are echoed verbatim.
    """

    cfg = _config(request)
    return {"anonymization": cfg.anonymization.model_dump(mode="json")}


# ---------------------------------------------------------------------------
# D0.5: config + alias CRUD
# ---------------------------------------------------------------------------


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    """Return the live :class:`GatewayConfig` as JSON (sanitized).

    The payload is the Pydantic ``model_dump(mode="json")`` of the
    current snapshot. Secrets are not in the schema (env-var *names*
    are; *values* are never modeled), so the dump is safe to surface
    to admin clients. The endpoint is gated by the gateway-key check
    so anonymous reads never see provider names or alias maps.
    """

    config = _config(request)
    return _sanitized_config_payload(config)


@router.get("/aliases")
async def list_aliases(request: Request) -> dict[str, Any]:
    """List every configured model alias.

    Wire shape::

        {
            "object": "list",
            "data": [{"name": "smart", "provider": "...", "model": "...", "fallback": [...]}, ...],
        }

    Tier annotation is **not** included on this listing because an
    alias may resolve to multiple targets through fallback; the tier
    is observable on the response of an actual chat call. The web UI
    derives a hint by looking up the alias's primary provider in the
    config payload.
    """

    config = _config(request)
    return {
        "object": "list",
        "data": [_alias_to_payload(name, alias) for name, alias in config.model_aliases.items()],
    }


@router.get("/aliases/{name}", response_model=None)
async def get_alias(request: Request, name: str) -> dict[str, Any] | JSONResponse:
    """Return a single alias by name (404 if not configured)."""

    config = _config(request)
    alias = config.model_aliases.get(name)
    if alias is None:
        return _gateway_error(
            code="not_found",
            message=f"alias {name!r} not found",
            http_status=status.HTTP_404_NOT_FOUND,
            details={"alias": name},
        )
    payload = _alias_to_payload(name, alias)
    # Decoration: include the derived tier of the *primary* target so
    # the UI can render a tier badge without a second roundtrip. We
    # explicitly do not include fallback-chain tiers — the UI cares
    # about the typical-case routing decision.
    provider = config.provider_by_name(alias.primary.provider)
    if provider is not None and alias.primary.model:
        payload["primary_inference_tier"] = derive_routed_inference_tier(
            provider=provider,
            native_model=alias.primary.model,
            inference_tiers=config.inference_tiers,
        )
    return payload


@router.post("/aliases", status_code=status.HTTP_201_CREATED, response_model=None)
async def create_alias(
    request: Request,
    body: AliasCreateRequest,
) -> dict[str, Any] | JSONResponse:
    """Create a new alias. 409 if ``body.name`` is already configured."""

    holder = _holder(request)
    fallback_payload = (
        [{"provider": fb.provider, "model": fb.model} for fb in body.fallback]
        if body.fallback is not None
        else None
    )
    try:
        upsert_alias(
            holder,
            name=body.name,
            provider=body.provider,
            model=body.model,
            fallback=fallback_payload,
            create_only=True,
        )
    except AliasMutationError as exc:
        return _gateway_error(
            code=_alias_error_code(exc),
            message=str(exc),
            http_status=exc.http_status,
            details={"alias": body.name},
        )
    except ConfigReloadError as exc:
        return _gateway_error(
            code="invalid_request",
            message=str(exc),
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"alias": body.name},
        )
    config = holder.current()
    alias = config.model_aliases[body.name]
    return _alias_to_payload(body.name, alias)


@router.patch("/aliases/{name}", response_model=None)
async def update_alias(
    request: Request,
    name: str,
    body: AliasUpdateRequest,
) -> dict[str, Any] | JSONResponse:
    """Update an existing alias. 404 if not configured."""

    holder = _holder(request)
    fallback_payload = (
        [{"provider": fb.provider, "model": fb.model} for fb in body.fallback]
        if body.fallback is not None
        else None
    )
    try:
        upsert_alias(
            holder,
            name=name,
            provider=body.provider,
            model=body.model,
            fallback=fallback_payload,
            update_only=True,
        )
    except AliasMutationError as exc:
        return _gateway_error(
            code=_alias_error_code(exc),
            message=str(exc),
            http_status=exc.http_status,
            details={"alias": name},
        )
    except ConfigReloadError as exc:
        return _gateway_error(
            code="invalid_request",
            message=str(exc),
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"alias": name},
        )
    config = holder.current()
    alias = config.model_aliases[name]
    return _alias_to_payload(name, alias)


@router.delete("/aliases/{name}")
async def remove_alias(request: Request, name: str) -> JSONResponse:
    """Remove an alias. 404 if not configured."""

    holder = _holder(request)
    try:
        delete_alias(holder, name=name)
    except AliasMutationError as exc:
        return _gateway_error(
            code=_alias_error_code(exc),
            message=str(exc),
            http_status=exc.http_status,
            details={"alias": name},
        )
    except ConfigReloadError as exc:
        return _gateway_error(
            code="invalid_request",
            message=str(exc),
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"alias": name},
        )
    return JSONResponse(
        status_code=status.HTTP_204_NO_CONTENT,
        content=None,
    )


def _alias_error_code(exc: AliasMutationError) -> str:
    """Map an :class:`AliasMutationError` HTTP status to a gateway code."""

    if exc.http_status == status.HTTP_404_NOT_FOUND:
        return "not_found"
    if exc.http_status == status.HTTP_409_CONFLICT:
        return "conflict"
    if exc.http_status == status.HTTP_422_UNPROCESSABLE_ENTITY:
        return "invalid_request"
    return "internal_error"


# ---------------------------------------------------------------------------
# Donna #7: runtime provider-key management (BYOK hot-apply)
# ---------------------------------------------------------------------------


def _provider_key_error_code(exc: ProviderKeyMutationError) -> str:
    """Map a :class:`ProviderKeyMutationError` HTTP status to a gateway code.

    Parallel to :func:`_alias_error_code` — kept separate so the two
    surfaces don't accidentally share status semantics (provider-key delete
    uses 409 for "no runtime key to revoke", not the alias "conflict"
    meaning, but they render the same stable code).
    """

    if exc.http_status == status.HTTP_404_NOT_FOUND:
        return "not_found"
    if exc.http_status == status.HTTP_409_CONFLICT:
        return "conflict"
    if exc.http_status == status.HTTP_422_UNPROCESSABLE_ENTITY:
        return "invalid_request"
    return "internal_error"


def _resolved_master_key() -> str | None:
    """Return the bound gateway master key, or ``None`` if unset.

    Runtime (encrypted-at-rest) key storage is impossible without it; the
    write endpoints fail fast with 400 when it's absent rather than writing
    an unencryptable key.
    """

    return os.environ.get(MASTER_KEY_ENV) or None


@router.get("/provider-keys")
async def list_provider_keys_endpoint(request: Request) -> dict[str, Any]:
    """List the secret-safe key status of every configured provider.

    Each row is ``{provider, type, configured, last4, source}``. The
    response NEVER contains a full key — only the last 4 characters of a
    resolvable key, and only when the provider's adapter is built.
    """

    config = _config(request)
    rows = list_provider_keys(
        config,
        request.app.state.adapters,
        ProviderKeyResolver.from_environ(),
    )
    return {"provider_keys": rows}


async def _apply_provider_key_request(
    request: Request,
    *,
    provider_name: str,
    plaintext: str,
) -> dict[str, Any] | JSONResponse:
    """Shared apply path for the POST (set) and PATCH (rotate) endpoints.

    Both endpoints differ only in where ``provider_name`` comes from (POST
    reads it from the body, PATCH from the path). The work is identical:
    enforce the master-key precondition (400 when unset), hold the
    serialization lock, delegate to :func:`apply_provider_key`, and map the
    service-layer errors to the canonical ``GatewayError`` envelope.

    Returns the provider's secret-safe status dict on success, or a
    :class:`JSONResponse` error envelope on the precondition / mutation /
    reload failure paths.
    """

    master_key = _resolved_master_key()
    if not master_key:
        return _gateway_error(
            code="failed_precondition",
            message=(f"runtime key storage requires {MASTER_KEY_ENV} to be set"),
            http_status=status.HTTP_400_BAD_REQUEST,
            details={"provider": provider_name},
        )

    holder = _holder(request)
    async with request.app.state.provider_key_lock:
        try:
            return await apply_provider_key(
                holder=holder,
                app_state=request.app.state,
                provider_name=provider_name,
                plaintext=plaintext,
                master_key=master_key,
            )
        except ProviderKeyMutationError as exc:
            return _gateway_error(
                code=_provider_key_error_code(exc),
                message=str(exc),
                http_status=exc.http_status,
                details={"provider": provider_name},
            )
        except ConfigReloadError as exc:
            return _gateway_error(
                code="invalid_request",
                message=str(exc),
                http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"provider": provider_name},
            )


@router.post("/provider-keys", response_model=None)
async def set_provider_key(
    request: Request,
    body: ProviderKeySetRequest,
) -> dict[str, Any] | JSONResponse:
    """Set/replace a provider's runtime key and hot-apply it.

    Encrypts the key with the master key, persists ``api_key_encrypted`` to
    ``gateway.yaml``, reloads, and swaps the rebuilt adapter into the live
    registry — no restart. 400 if the master key is unset; 404 if the
    provider isn't configured. Returns the provider's status dict (no
    secret).
    """

    return await _apply_provider_key_request(
        request,
        provider_name=body.provider,
        plaintext=body.api_key,
    )


@router.patch("/provider-keys/{provider}", response_model=None)
async def rotate_provider_key(
    request: Request,
    provider: str,
    body: ProviderKeyRotateRequest,
) -> dict[str, Any] | JSONResponse:
    """Rotate the runtime key on an already-configured provider.

    Same mechanics as POST; the provider comes from the path. 404 if the
    provider isn't configured; 400 if the master key is unset.
    """

    return await _apply_provider_key_request(
        request,
        provider_name=provider,
        plaintext=body.api_key,
    )


@router.delete(
    "/provider-keys/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def revoke_provider_key_endpoint(
    request: Request,
    provider: str,
) -> Response:
    """Revoke a provider's runtime key and retire its live adapter.

    Deletes ``api_key_encrypted`` from ``gateway.yaml``, reloads, and pops
    the adapter from the live registry (it routes 503 afterward). 404 if
    the provider isn't configured; 409 if the provider has no runtime key
    to revoke (e.g., an env-sourced key, which the operator owns). 204 on
    success.

    Per the CLAUDE.md DELETE-204 recipe: ``response_class=Response`` plus an
    explicit empty ``Response`` return so the 204 carries a genuinely empty
    body. The error branch still returns a ``JSONResponse`` (a ``Response``
    subclass) carrying the ``GatewayError`` envelope — FastAPI honors the
    explicit return, so that is fine even with ``response_class=Response``.
    """

    holder = _holder(request)
    async with request.app.state.provider_key_lock:
        try:
            await revoke_provider_key(
                holder=holder,
                app_state=request.app.state,
                provider_name=provider,
            )
        except ProviderKeyMutationError as exc:
            return _gateway_error(
                code=_provider_key_error_code(exc),
                message=str(exc),
                http_status=exc.http_status,
                details={"provider": provider},
            )
        except ConfigReloadError as exc:
            return _gateway_error(
                code="invalid_request",
                message=str(exc),
                http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"provider": provider},
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
