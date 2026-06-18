"""``POST /v1/oauth/{provider}/{discover,token}`` — backend → gateway OAuth.

Per locked decision D-c6 (ADR-0014-pure): 100% of third-party OAuth egress
stays at the one audited gateway boundary. The FastAPI backend drives the MCP
OAuth flow but does NOT make the discovery / token HTTP calls itself — it asks
the gateway to make them via these two egress-guarded endpoints.

Gated by the gateway-key dependency exactly like the tool routes — this
triggers credentialed egress, a privileged operation like admin. The
egress audit row (counts-only) is written inside the ``Router`` methods; this
layer only maps errors to the ``GatewayError`` envelope.

NOTE: these endpoints carry credentials in the request BODY (the api builds the
token form). They are NOT the ``X-LQ-AI-User-Token`` header path — no per-user
token header is read here. No body value (``code`` / ``refresh_token`` /
``code_verifier`` / ``client_id``) and no AS-response token value is ever
logged or echoed into an error message.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.dependencies import make_require_gateway_key
from app.providers.tool.oauth_passthrough import OAuthPassthroughError
from app.router import Router, ToolEgressRefused, synthesize_request_id

require_gateway_key = make_require_gateway_key()

router = APIRouter(prefix="/v1", tags=["oauth"], dependencies=[Depends(require_gateway_key)])


class OAuthTokenRequest(BaseModel):
    """Body for a token exchange.

    ``token_endpoint`` is the discovered AS token endpoint (validated against
    the provider allowlist inside the gateway before the call). ``form`` is the
    OAuth token-request form for the ``authorization_code`` or ``refresh_token``
    grant — it carries the user's secret material and is NEVER logged.
    """

    token_endpoint: str = Field(min_length=1)
    form: dict[str, str] = Field(default_factory=dict)


def _router(request: Request) -> Router:
    pre_built: Router | None = getattr(request.app.state, "router", None)
    if pre_built is None:
        raise RuntimeError("gateway router not initialized")
    return pre_built


def _request_id(request: Request) -> str:
    for name in ("x-request-id", "x-correlation-id"):
        value = request.headers.get(name)
        if value:
            return synthesize_request_id(value)
    return synthesize_request_id(None)


def _error(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


@router.post("/oauth/{provider}/discover")
async def discover_oauth(provider: str, request: Request) -> JSONResponse:
    """Perform MCP OAuth discovery (RFC 9728 → RFC 8414 / OIDC) for ``provider``.

    Returns the merged authorization-server metadata. The request body is
    ignored (discovery takes no secret input). A refused egress (unknown /
    non-oauth provider, or an un-allowlisted discovered AS host) maps to 403;
    a network / parse failure maps to 502 with a generic message.
    """
    gw_router = _router(request)
    request_id = _request_id(request)
    try:
        metadata = await gw_router.route_oauth_discover(provider, request_id=request_id)
    except ToolEgressRefused as exc:
        return _error(403, "egress_refused", exc.reason)
    except OAuthPassthroughError:
        # The helper's message is already generic (no creds); use a fixed
        # envelope message so nothing cause-derived leaks even by accident.
        return _error(502, "oauth_discovery_failed", "OAuth discovery failed for provider")
    return JSONResponse(content=metadata)


@router.post("/oauth/{provider}/token")
async def token_oauth(provider: str, body: OAuthTokenRequest, request: Request) -> JSONResponse:
    """Proxy a token-endpoint form-POST and relay the AS response verbatim.

    Used for both the ``authorization_code`` and ``refresh_token`` grants. The
    AS status and body are relayed faithfully — a 2xx token response OR a 4xx
    OAuth error (e.g. ``invalid_grant``) — so the api/authlib parses both. A
    refused egress maps to 403; a network failure to 502.
    """
    gw_router = _router(request)
    request_id = _request_id(request)
    try:
        status_code, as_body = await gw_router.route_oauth_token(
            provider,
            token_endpoint=body.token_endpoint,
            form=body.form,
            request_id=request_id,
        )
    except ToolEgressRefused as exc:
        return _error(403, "egress_refused", exc.reason)
    except OAuthPassthroughError:
        return _error(502, "oauth_token_failed", "OAuth token exchange failed for provider")
    return JSONResponse(status_code=status_code, content=as_body)
