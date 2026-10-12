import json as _json

import httpx
import pytest
import respx

from app.clients.gateway import GatewayClient
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

GW = "http://gw.test"


def _client() -> GatewayClient:
    return GatewayClient(base_url=GW, gateway_key="k")


@pytest.mark.asyncio
async def test_call_tool_happy_path() -> None:
    client = _client()
    payload = {
        "provider": "courtlistener-prod",
        "tool": "search_case_law",
        "payload": {"count": 0, "results": []},
        "tier": 4,
    }
    with respx.mock:
        route = respx.post(f"{GW}/v1/tools/courtlistener-prod/search_case_law").mock(
            return_value=httpx.Response(200, json=payload)
        )
        out = await client.call_tool("courtlistener-prod", "search_case_law", {"q": "x"})
    assert route.called
    assert route.calls.last.request.headers["X-LQ-AI-Gateway-Key"] == "k"
    assert _json.loads(route.calls.last.request.content)["args"] == {"q": "x"}
    assert out["payload"]["count"] == 0


@pytest.mark.asyncio
async def test_call_tool_forwards_max_allowed_tier() -> None:
    client = _client()
    with respx.mock:
        route = respx.post(f"{GW}/v1/tools/p/t").mock(
            return_value=httpx.Response(
                200, json={"provider": "p", "tool": "t", "payload": {}, "tier": 3}
            )
        )
        await client.call_tool("p", "t", {"a": 1}, max_allowed_tier=3)
    body = _json.loads(route.calls.last.request.content)
    assert body["max_allowed_tier"] == 3


@pytest.mark.asyncio
async def test_call_tool_maps_gateway_4xx_envelope() -> None:
    # A structured gateway 4xx envelope must be parsed + mapped via
    # _raise_for_gateway_error (same path as the other client methods).
    from app.errors import ValidationError  # adjust if map_gateway_error_code differs

    client = _client()
    with respx.mock:
        respx.post(f"{GW}/v1/tools/courtlistener-prod/verify_citations").mock(
            return_value=httpx.Response(
                400,
                json={"error": {"code": "invalid_request", "message": "bad", "details": {}}},
            )
        )
        with pytest.raises(ValidationError):
            await client.call_tool("courtlistener-prod", "verify_citations", {"text": ""})


def test_api_chat_request_carries_tools() -> None:
    req = ChatCompletionRequest(
        model="smart",
        messages=[ChatCompletionMessage(role="user", content="hi")],
        tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
        tool_choice="auto",
    )
    assert req.tools[0]["function"]["name"] == "x"  # type: ignore[index]
    assert req.tool_choice == "auto"


@pytest.mark.asyncio
async def test_call_tool_sets_user_token_header() -> None:
    captured: dict[str, str | None] = {}

    def _cap(request: httpx.Request) -> httpx.Response:
        captured["hdr"] = request.headers.get("X-LQ-AI-User-Token")
        return httpx.Response(200, json={"provider": "p", "tool": "t", "payload": {}, "tier": 1})

    client = _client()
    with respx.mock:
        respx.post(f"{GW}/v1/tools/p/t").mock(side_effect=_cap)
        await client.call_tool("p", "t", {"a": 1}, user_token="secret-tok")
    assert captured["hdr"] == "secret-tok"


@pytest.mark.asyncio
async def test_call_tool_omits_user_token_header_when_none() -> None:
    captured: dict[str, str | None] = {}

    def _cap(request: httpx.Request) -> httpx.Response:
        captured["hdr"] = request.headers.get("X-LQ-AI-User-Token")
        return httpx.Response(200, json={"provider": "p", "tool": "t", "payload": {}, "tier": 1})

    client = _client()
    with respx.mock:
        respx.post(f"{GW}/v1/tools/p/t").mock(side_effect=_cap)
        await client.call_tool("p", "t", {"a": 1})
    assert captured["hdr"] is None
