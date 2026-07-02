"""``POST /v1/tools/{provider}/{tool}`` — backend → gateway tool-call transport.

Exposes the PR1 :meth:`Router.route_tool_call` egress path over HTTP so the
FastAPI backend can invoke tool-providers (CourtListener, MCP) WITHOUT calling
third parties directly (ADR 0014). Gated by the gateway-key dependency — this
triggers credentialed egress + cost, a privileged operation like admin.
The audit row is written inside ``route_tool_call``; this layer only maps
errors to the ``GatewayError`` envelope."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.dependencies import make_require_gateway_key
from app.providers.tool.base import (
    ToolProviderAuthError,
    ToolProviderError,
    ToolProviderHTTPError,
    ToolProviderInvalidRequestError,
    ToolProviderNetworkError,
)
from app.router import Router, ToolEgressRefused, synthesize_request_id

require_gateway_key = make_require_gateway_key()

router = APIRouter(prefix="/v1", tags=["tools"], dependencies=[Depends(require_gateway_key)])


class ToolCallRequest(BaseModel):
    """Body for a tool-call. ``args`` is the tool's own argument object."""

    args: dict[str, Any] = Field(default_factory=dict)
    max_allowed_tier: int | None = Field(default=None, ge=1, le=5)


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


_USER_TOKEN_HEADER = "X-LQ-AI-User-Token"


def _user_token(request: Request) -> str | None:
    """Per-user MCP token (auth: oauth). A header, NOT a query param/body —
    query strings land in access logs; this must not. Never logged."""
    return request.headers.get(_USER_TOKEN_HEADER)


def _error(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


@router.get("/tools/{provider}")
async def list_provider_tools(provider: str, request: Request) -> JSONResponse:
    """Return the live ``list_tools()`` for a configured tool provider.

    The per-user OAuth token for ``auth: oauth`` MCP servers is supplied via
    the ``X-LQ-AI-User-Token`` request header (PR4c supplies it). Using a
    header instead of a query parameter ensures the token is never written to
    uvicorn access logs. For ``none`` / ``bearer`` providers the token is
    ignored and **never logged**.
    """
    user_token = _user_token(request)
    gw_router = _router(request)
    adapter = gw_router._tool_adapters.get(provider)
    if adapter is None:
        return _error(404, "unknown_provider", f"tool provider {provider!r} not found")
    try:
        specs = await adapter.list_tools(user_token=user_token)
    except ToolProviderError as exc:
        return _error(502, "tool_provider_unavailable", exc.message, exc.details)
    return JSONResponse(
        content={
            "provider": provider,
            "tools": [
                {
                    "name": s.name,
                    "description": s.description,
                    "parameters": s.parameters,
                    "read_only": s.read_only,
                    "destructive": s.destructive,
                    "requires_confirmation": s.requires_confirmation,
                }
                for s in specs
            ],
        }
    )


@router.post("/tools/{provider}/{tool}")
async def call_tool(
    provider: str, tool: str, body: ToolCallRequest, request: Request
) -> JSONResponse:
    gw_router = _router(request)
    request_id = _request_id(request)
    user_token = _user_token(request)
    try:
        result = await gw_router.route_tool_call(
            provider,
            tool,
            body.args,
            request_id=request_id,
            max_allowed_tier=body.max_allowed_tier,
            user_token=user_token,
        )
    except ToolEgressRefused as exc:
        return _error(403, "egress_refused", exc.reason)
    except ToolProviderAuthError:
        return _error(
            502, "tool_provider_unavailable", "tool provider rejected gateway credentials"
        )
    except ToolProviderInvalidRequestError as exc:
        return _error(400, "invalid_request", exc.message, exc.details)
    except ToolProviderHTTPError as exc:
        code = 429 if exc.upstream_status == 429 else 502
        return _error(code, "tool_provider_unavailable", exc.message, exc.details)
    except ToolProviderNetworkError as exc:
        return _error(502, "tool_provider_unavailable", exc.message)
    except ToolProviderError as exc:
        return _error(400, exc.code, exc.message, exc.details)
    return JSONResponse(
        content={
            "provider": result.provider,
            "tool": result.tool,
            "payload": result.payload,
            "tier": result.tier,
        }
    )
