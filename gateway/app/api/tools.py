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


def _error(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


@router.post("/tools/{provider}/{tool}")
async def call_tool(
    provider: str, tool: str, body: ToolCallRequest, request: Request
) -> JSONResponse:
    gw_router = _router(request)
    request_id = _request_id(request)
    try:
        result = await gw_router.route_tool_call(
            provider,
            tool,
            body.args,
            request_id=request_id,
            max_allowed_tier=body.max_allowed_tier,
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
