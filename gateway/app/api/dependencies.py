"""FastAPI dependencies shared across gateway routes (D0.5).

Today the only dependency lives here is :func:`require_gateway_key`, the
shared-secret check used by the admin write endpoints. The same secret
is already used by the C2 backend client when fetching skills; D0.5
extends it to the admin alias-CRUD surface so the backend (which holds
the secret in B5+) is the only entity that can mutate
``gateway.yaml``.

Why no separate "admin key": the brief is explicit. The backend's
``is_admin`` gate is the user-level authorization layer; the gateway's
shared secret is the service-to-service authentication layer. Adding a
third secret would expand the secret surface without strengthening the
threat model — a compromised backend already speaks the gateway-key
protocol, and a compromised gateway is the operator's bigger problem.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Awaitable, Callable

from fastapi import Header, HTTPException, Request, status

from app.config import GatewayConfig
from app.secrets import resolve_secret

logger = logging.getLogger(__name__)


GATEWAY_KEY_HEADER = "X-LQ-AI-Gateway-Key"
"""Shared-secret header that the backend sends on every gateway call."""


def _resolve_required_key(config: GatewayConfig) -> str | None:
    """Return the expected shared-secret value, or None if disabled.

    Pulls the env-var name from ``gateway_auth.api_key_env`` (default
    ``LQ_AI_GATEWAY_KEY``) and reads the value via
    :func:`app.secrets.resolve_secret`, so ``NAME_FILE`` delivery works.
    A conflicting or unreadable file source raises (fail closed) rather
    than silently disabling auth. Returns None when
    ``gateway_auth.enabled`` is False (auth disabled — typical only for
    local dev with the env var unset) or when the secret resolves empty.

    The empty-string case is treated as "auth disabled" rather than
    "any key matches" — silently accepting unauthenticated writes
    would be the worst possible posture.
    """

    if not config.gateway_auth.enabled:
        return None
    env_name = config.gateway_auth.api_key_env or "LQ_AI_GATEWAY_KEY"
    expected = resolve_secret(env_name)
    if not expected:
        return None
    return expected


def make_require_gateway_key() -> Callable[..., Awaitable[None]]:
    """Build a FastAPI dependency that gates a route on the gateway key.

    Returns a callable suitable for ``Depends(...)``. Reads the live
    config snapshot off the request's app state on every call so that
    if an operator changes the gateway-auth settings via the admin
    surface, future calls immediately pick up the new policy.

    Behavior:

    * Auth disabled in config → request passes through (logged at INFO
      once per process).
    * Header missing or wrong → 401 with ``GatewayError`` envelope.
    * Header matches via :func:`hmac.compare_digest` → request proceeds.
    """

    async def _require_gateway_key(
        request: Request,
        x_lq_ai_gateway_key: str | None = Header(default=None, alias=GATEWAY_KEY_HEADER),
    ) -> None:
        holder = getattr(request.app.state, "config_holder", None)
        if holder is not None:
            config: GatewayConfig = holder.current()
        else:
            config = request.app.state.config
        expected = _resolve_required_key(config)
        if expected is None:
            return
        if x_lq_ai_gateway_key is None or not hmac.compare_digest(x_lq_ai_gateway_key, expected):
            # Don't echo the (mis)matched value or the configured one;
            # operators see *that* it failed, not what was sent.
            logger.warning("rejecting admin request: gateway-key header missing or invalid")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": {
                        "code": "unauthorized",
                        "message": "X-LQ-AI-Gateway-Key header missing or invalid",
                        "details": {},
                    }
                },
            )

    return _require_gateway_key


__all__ = ["GATEWAY_KEY_HEADER", "make_require_gateway_key"]
