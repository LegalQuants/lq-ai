"""Unit tests for GatewayClient.discover_tools (PR4b/WS2).

Pins the HTTP wire shape for GET /v1/tools/{provider}, the user-token header
forwarding, and the error-translation path (404 unknown_provider → LQAIError).
No FastAPI app or database needed — pure respx.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.gateway import GATEWAY_KEY_HEADER, GatewayClient

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-secret"


def _client() -> GatewayClient:
    return GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)


@pytest.mark.asyncio
async def test_discover_tools_happy_path() -> None:
    payload = {
        "provider": "acme-mcp",
        "tools": [
            {
                "name": "read_doc",
                "description": "reads",
                "parameters": {"type": "object"},
                "read_only": True,
                "destructive": False,
                "requires_confirmation": False,
            },
        ],
    }
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        route = mock.get("/v1/tools/acme-mcp").mock(return_value=httpx.Response(200, json=payload))
        out = await _client().discover_tools("acme-mcp")
    assert out["provider"] == "acme-mcp"
    assert out["tools"][0]["name"] == "read_doc"
    assert route.calls.last.request.headers[GATEWAY_KEY_HEADER] == GATEWAY_KEY


@pytest.mark.asyncio
async def test_discover_tools_sends_user_token_header() -> None:
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        route = mock.get("/v1/tools/acme-mcp").mock(
            return_value=httpx.Response(200, json={"provider": "acme-mcp", "tools": []})
        )
        await _client().discover_tools("acme-mcp", user_token="user-tok")
    assert route.calls.last.request.headers["X-LQ-AI-User-Token"] == "user-tok"


@pytest.mark.asyncio
async def test_discover_tools_unknown_provider_raises() -> None:
    from app.errors import LQAIError

    body = {"error": {"code": "unknown_provider", "message": "nope", "details": {}}}
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        mock.get("/v1/tools/nope").mock(return_value=httpx.Response(404, json=body))
        with pytest.raises(LQAIError):
            await _client().discover_tools("nope")
