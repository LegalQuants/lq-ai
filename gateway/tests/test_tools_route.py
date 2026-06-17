import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.tools import router as tools_router
from app.config import GatewayConfig
from app.providers.tool.echo import EchoToolAdapter
from app.router import Router
from app.tool_egress_log import RecordingToolEgressLogWriter


def _make_app(monkeypatch, *, writer=None):
    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "echo-test",
                    "type": "echo",
                    "base_url": "https://example.test",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                }
            ]
        }
    )
    adapter = EchoToolAdapter.from_config(cfg.tool_providers[0])
    router_obj = Router(
        config=cfg,
        adapters={},
        tool_adapters={"echo-test": adapter},
        tool_egress_log=writer or RecordingToolEgressLogWriter(),
    )
    app = FastAPI()
    app.state.config = cfg
    app.state.router = router_obj
    app.include_router(tools_router)
    return app, adapter


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.unit
async def test_tool_call_happy_path(monkeypatch) -> None:
    app, adapter = _make_app(monkeypatch)
    try:
        async with _client(app) as c:
            resp = await c.post("/v1/tools/echo-test/echo", json={"args": {"msg": "hi"}})
    finally:
        await adapter.aclose()
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "echo-test"
    assert body["tool"] == "echo"
    assert body["payload"] == {"echoed": {"msg": "hi"}}
    assert body["tier"] == 4


@pytest.mark.unit
async def test_tool_call_unknown_provider_403(monkeypatch) -> None:
    app, adapter = _make_app(monkeypatch)
    try:
        async with _client(app) as c:
            resp = await c.post("/v1/tools/missing/echo", json={"args": {}})
    finally:
        await adapter.aclose()
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "egress_refused"


@pytest.mark.unit
async def test_tool_call_tier_ceiling_403(monkeypatch) -> None:
    app, adapter = _make_app(monkeypatch)
    try:
        async with _client(app) as c:
            resp = await c.post(
                "/v1/tools/echo-test/echo", json={"args": {}, "max_allowed_tier": 3}
            )
    finally:
        await adapter.aclose()
    assert resp.status_code == 403


@pytest.mark.unit
async def test_tool_call_unknown_tool_400(monkeypatch) -> None:
    app, adapter = _make_app(monkeypatch)
    try:
        async with _client(app) as c:
            resp = await c.post("/v1/tools/echo-test/nope", json={"args": {}})
    finally:
        await adapter.aclose()
    assert resp.status_code == 400


@pytest.mark.unit
async def test_tool_call_requires_gateway_key_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", "secret-key")
    app, adapter = _make_app(monkeypatch)
    try:
        async with _client(app) as c:
            missing = await c.post("/v1/tools/echo-test/echo", json={"args": {}})
            ok = await c.post(
                "/v1/tools/echo-test/echo",
                json={"args": {"msg": "hi"}},
                headers={"X-LQ-AI-Gateway-Key": "secret-key"},
            )
    finally:
        await adapter.aclose()
    assert missing.status_code == 401
    assert ok.status_code == 200


@pytest.mark.unit
async def test_tools_route_registered_on_app(gateway_app) -> None:
    paths = gateway_app.openapi()["paths"]
    assert "/v1/tools/{provider}/{tool}" in paths
    assert "post" in paths["/v1/tools/{provider}/{tool}"]


# ---------------------------------------------------------------------------
# user_token transport test (PR4a Task 5)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_tool_call_forwards_user_token_to_route_tool_call(monkeypatch) -> None:
    """user_token in the JSON body is forwarded to Router.route_tool_call."""
    captured: dict[str, object] = {}

    async def _fake_route_tool_call(
        provider_name: str,
        tool: str,
        args: dict[str, object],
        *,
        request_id: str,
        max_allowed_tier: int | None = None,
        user_token: str | None = None,
    ) -> object:
        captured["user_token"] = user_token
        from app.router import ToolCallRoutedResult

        return ToolCallRoutedResult(provider=provider_name, tool=tool, payload={"ok": True}, tier=2)

    app, adapter = _make_app(monkeypatch)
    app.state.router.route_tool_call = _fake_route_tool_call  # type: ignore[method-assign]

    try:
        async with _client(app) as c:
            resp = await c.post(
                "/v1/tools/echo-test/echo",
                json={"args": {"q": "x"}, "user_token": "t"},
            )
    finally:
        await adapter.aclose()

    assert resp.status_code == 200
    assert captured["user_token"] == "t"
