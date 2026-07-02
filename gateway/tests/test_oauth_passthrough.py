"""Tests for the gateway OAuth passthrough (PR4c, ADR-0014-pure D-c6).

Covers the egress-guarded primitives, the governed ``Router`` methods (incl.
the counts-only audit), and the ``/v1/oauth/{provider}/...`` route module.

Security rubric (asserted below):
* every outbound URL passes the egress guard (https + allowlist + public IP);
* an un-allowlisted discovered AS host / http:// URL is REFUSED;
* the AS token response and the request form NEVER appear in an audit row.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.oauth import router as oauth_router
from app.config import GatewayConfig
from app.providers.tool.egress import EgressRefused
from app.providers.tool.oauth_passthrough import (
    OAuthPassthroughError,
    discover_oauth_metadata,
    exchange_oauth_token,
)
from app.router import Router, ToolEgressRefused
from app.tool_egress_log import RecordingToolEgressLogWriter

MCP_HOST = "mcp.example.test"
AS_HOST = "auth.example.test"
MCP_URL = f"https://{MCP_HOST}"
AS_BASE = f"https://{AS_HOST}"
TOKEN_ENDPOINT = f"{AS_BASE}/oauth/token"
AUTHORIZE_ENDPOINT = f"{AS_BASE}/oauth/authorize"

ALLOWLIST = [MCP_HOST, AS_HOST]

# Secret material the audit must NEVER contain.
SECRET_FORM = {
    "grant_type": "authorization_code",
    "code": "SECRET-AUTH-CODE-xyz",
    "code_verifier": "SECRET-PKCE-VERIFIER-abc",
    "client_id": "SECRET-CLIENT-ID-123",
    "redirect_uri": "https://app.example/callback",
}
SECRET_TOKEN_RESPONSE = {
    "access_token": "SECRET-ACCESS-TOKEN",
    "refresh_token": "SECRET-REFRESH-TOKEN",
    "token_type": "Bearer",
    "expires_in": 3600,
}


@pytest.fixture(autouse=True)
def _public_ips(monkeypatch):
    """Resolve every allowlisted host to a public IP so the guard passes."""
    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])


# ---------------------------------------------------------------------------
# Discovery primitive
# ---------------------------------------------------------------------------


def _prm_doc() -> dict:
    return {
        "resource": MCP_URL,
        "authorization_servers": [AS_BASE],
        "scopes_supported": ["read", "write"],
    }


def _as_doc() -> dict:
    return {
        "issuer": AS_BASE,
        "authorization_endpoint": AUTHORIZE_ENDPOINT,
        "token_endpoint": TOKEN_ENDPOINT,
        "authorization_response_iss_parameter_supported": True,
    }


@pytest.mark.unit
async def test_discover_happy_path() -> None:
    with respx.mock:
        respx.get(f"{MCP_URL}/.well-known/oauth-protected-resource").mock(
            return_value=httpx.Response(200, json=_prm_doc())
        )
        respx.get(f"{AS_BASE}/.well-known/oauth-authorization-server").mock(
            return_value=httpx.Response(200, json=_as_doc())
        )
        meta = await discover_oauth_metadata(server_url=MCP_URL, allowlist=ALLOWLIST)
    assert meta["authorization_endpoint"] == AUTHORIZE_ENDPOINT
    assert meta["token_endpoint"] == TOKEN_ENDPOINT
    assert meta["issuer"] == AS_BASE
    assert meta["resource"] == MCP_URL
    assert meta["scopes_supported"] == ["read", "write"]
    assert meta["authorization_response_iss_parameter_supported"] is True


@pytest.mark.unit
async def test_discover_oidc_fallback() -> None:
    with respx.mock:
        respx.get(f"{MCP_URL}/.well-known/oauth-protected-resource").mock(
            return_value=httpx.Response(200, json=_prm_doc())
        )
        # RFC 8414 metadata 404 → openid-configuration is consulted.
        respx.get(f"{AS_BASE}/.well-known/oauth-authorization-server").mock(
            return_value=httpx.Response(404)
        )
        oidc = respx.get(f"{AS_BASE}/.well-known/openid-configuration").mock(
            return_value=httpx.Response(200, json=_as_doc())
        )
        meta = await discover_oauth_metadata(server_url=MCP_URL, allowlist=ALLOWLIST)
    assert oidc.called
    assert meta["token_endpoint"] == TOKEN_ENDPOINT


@pytest.mark.unit
async def test_discover_refuses_unallowlisted_as_host() -> None:
    """AS host discovered at runtime is NOT in the allowlist → EgressRefused."""
    with respx.mock:
        respx.get(f"{MCP_URL}/.well-known/oauth-protected-resource").mock(
            return_value=httpx.Response(200, json=_prm_doc())
        )
        # allowlist omits AS_HOST.
        with pytest.raises(EgressRefused):
            await discover_oauth_metadata(server_url=MCP_URL, allowlist=[MCP_HOST])


@pytest.mark.unit
async def test_discover_refuses_http_scheme() -> None:
    """A non-https server_url is refused before any request is made."""
    with pytest.raises(EgressRefused):
        await discover_oauth_metadata(server_url=f"http://{MCP_HOST}", allowlist=["*", MCP_HOST])


@pytest.mark.unit
async def test_discover_refuses_http_as_url() -> None:
    """An http:// AS issuer in the PRM doc is refused (https enforcement)."""
    prm = _prm_doc()
    prm["authorization_servers"] = [f"http://{AS_HOST}"]
    with respx.mock:
        respx.get(f"{MCP_URL}/.well-known/oauth-protected-resource").mock(
            return_value=httpx.Response(200, json=prm)
        )
        with pytest.raises(EgressRefused):
            await discover_oauth_metadata(server_url=MCP_URL, allowlist=ALLOWLIST)


@pytest.mark.unit
async def test_discover_missing_authorization_servers_raises() -> None:
    with respx.mock:
        respx.get(f"{MCP_URL}/.well-known/oauth-protected-resource").mock(
            return_value=httpx.Response(200, json={"resource": MCP_URL})
        )
        with pytest.raises(OAuthPassthroughError):
            await discover_oauth_metadata(server_url=MCP_URL, allowlist=ALLOWLIST)


# ---------------------------------------------------------------------------
# Token primitive
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_token_happy_path() -> None:
    with respx.mock:
        route = respx.post(TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(200, json=SECRET_TOKEN_RESPONSE)
        )
        status, body = await exchange_oauth_token(
            token_endpoint=TOKEN_ENDPOINT, form=SECRET_FORM, allowlist=ALLOWLIST
        )
    assert status == 200
    assert body == SECRET_TOKEN_RESPONSE
    # Form-urlencoded, with the user's code in the body.
    sent = route.calls.last.request
    assert sent.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert b"SECRET-AUTH-CODE" in sent.content


@pytest.mark.unit
async def test_token_relays_oauth_error_verbatim() -> None:
    """A 400 invalid_grant is relayed as (400, {...}) — NOT swallowed into 502."""
    err = {"error": "invalid_grant", "error_description": "code expired"}
    with respx.mock:
        respx.post(TOKEN_ENDPOINT).mock(return_value=httpx.Response(400, json=err))
        status, body = await exchange_oauth_token(
            token_endpoint=TOKEN_ENDPOINT, form=SECRET_FORM, allowlist=ALLOWLIST
        )
    assert status == 400
    assert body == err


@pytest.mark.unit
async def test_token_refuses_unallowlisted_endpoint() -> None:
    with pytest.raises(EgressRefused):
        await exchange_oauth_token(
            token_endpoint="https://evil.example/token",
            form=SECRET_FORM,
            allowlist=ALLOWLIST,
        )


@pytest.mark.unit
async def test_token_non_json_raises_generic() -> None:
    with respx.mock:
        respx.post(TOKEN_ENDPOINT).mock(return_value=httpx.Response(200, text="not json"))
        with pytest.raises(OAuthPassthroughError) as ei:
            await exchange_oauth_token(
                token_endpoint=TOKEN_ENDPOINT, form=SECRET_FORM, allowlist=ALLOWLIST
            )
    # The form must not leak into the error message.
    assert "SECRET-AUTH-CODE" not in str(ei.value)
    assert "code_verifier" not in str(ei.value)


# ---------------------------------------------------------------------------
# Router governance + counts-only audit
# ---------------------------------------------------------------------------


def _cfg(*, auth: str = "oauth", type_: str = "mcp") -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "mcp-oauth",
                    "type": type_,
                    "base_url": MCP_URL,
                    "auth": auth,
                    "egress_tier": 4,
                    "allowlist": {"hosts": ALLOWLIST},
                }
            ]
        }
    )


def _router(writer: RecordingToolEgressLogWriter, **kw) -> Router:
    return Router(
        config=_cfg(**kw),
        adapters={},
        tool_adapters={},
        tool_egress_log=writer,
    )


def _no_creds_in_rows(writer: RecordingToolEgressLogWriter) -> None:
    """Assert no audit row carries any form value or token value anywhere."""
    forbidden = [
        "SECRET-AUTH-CODE-xyz",
        "SECRET-PKCE-VERIFIER-abc",
        "SECRET-CLIENT-ID-123",
        "SECRET-ACCESS-TOKEN",
        "SECRET-REFRESH-TOKEN",
    ]
    for row in writer.rows:
        blob = repr(row.__dict__)
        for secret in forbidden:
            assert secret not in blob, f"credential {secret!r} leaked into audit row"


@pytest.mark.unit
async def test_route_discover_writes_counts_only_row() -> None:
    writer = RecordingToolEgressLogWriter()
    gw = _router(writer)
    with respx.mock:
        respx.get(f"{MCP_URL}/.well-known/oauth-protected-resource").mock(
            return_value=httpx.Response(200, json=_prm_doc())
        )
        respx.get(f"{AS_BASE}/.well-known/oauth-authorization-server").mock(
            return_value=httpx.Response(200, json=_as_doc())
        )
        meta = await gw.route_oauth_discover("mcp-oauth", request_id="rid-1")
    assert meta["token_endpoint"] == TOKEN_ENDPOINT
    assert len(writer.rows) == 1
    row = writer.rows[0]
    assert row.refused is False
    assert row.tool == "oauth.discover"
    assert row.tier == 4
    assert row.bytes_in is not None and row.bytes_in > 0


@pytest.mark.unit
async def test_route_token_writes_counts_only_row_no_creds() -> None:
    writer = RecordingToolEgressLogWriter()
    gw = _router(writer)
    with respx.mock:
        respx.post(TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(200, json=SECRET_TOKEN_RESPONSE)
        )
        status, body = await gw.route_oauth_token(
            "mcp-oauth",
            token_endpoint=TOKEN_ENDPOINT,
            form=SECRET_FORM,
            request_id="rid-2",
        )
    assert status == 200
    assert body == SECRET_TOKEN_RESPONSE
    assert len(writer.rows) == 1
    row = writer.rows[0]
    assert row.refused is False
    assert row.tool == "oauth.token"
    assert row.bytes_out is not None and row.bytes_out > 0
    assert row.bytes_in is not None and row.bytes_in > 0
    _no_creds_in_rows(writer)


@pytest.mark.unit
async def test_route_discover_refusal_writes_refused_row() -> None:
    """Discovered AS host not allowlisted → ToolEgressRefused + refused row."""
    writer = RecordingToolEgressLogWriter()
    # provider allowlist omits AS_HOST.
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "mcp-oauth",
                    "type": "mcp",
                    "base_url": MCP_URL,
                    "auth": "oauth",
                    "egress_tier": 4,
                    "allowlist": {"hosts": [MCP_HOST]},
                }
            ]
        }
    )
    gw = Router(config=cfg, adapters={}, tool_adapters={}, tool_egress_log=writer)
    with respx.mock:
        respx.get(f"{MCP_URL}/.well-known/oauth-protected-resource").mock(
            return_value=httpx.Response(200, json=_prm_doc())
        )
        with pytest.raises(ToolEgressRefused):
            await gw.route_oauth_discover("mcp-oauth", request_id="rid-3")
    assert len(writer.rows) == 1
    assert writer.rows[0].refused is True
    assert writer.rows[0].refusal_reason.startswith("ssrf:")


@pytest.mark.unit
async def test_route_token_refusal_writes_refused_row_no_creds() -> None:
    writer = RecordingToolEgressLogWriter()
    gw = _router(writer)
    with pytest.raises(ToolEgressRefused):
        await gw.route_oauth_token(
            "mcp-oauth",
            token_endpoint="https://evil.example/token",
            form=SECRET_FORM,
            request_id="rid-4",
        )
    assert len(writer.rows) == 1
    assert writer.rows[0].refused is True
    _no_creds_in_rows(writer)


@pytest.mark.unit
async def test_route_unknown_provider_refused() -> None:
    writer = RecordingToolEgressLogWriter()
    gw = _router(writer)
    with pytest.raises(ToolEgressRefused):
        await gw.route_oauth_discover("nope", request_id="rid-5")
    assert writer.rows[0].refused is True
    assert writer.rows[0].tier == 0
    assert writer.rows[0].refusal_reason == "unknown oauth provider"


@pytest.mark.unit
async def test_route_non_oauth_provider_refused() -> None:
    """An MCP provider with auth != oauth is not an OAuth provider → refused."""
    writer = RecordingToolEgressLogWriter()
    gw = _router(writer, auth="none")
    with pytest.raises(ToolEgressRefused):
        await gw.route_oauth_token(
            "mcp-oauth",
            token_endpoint=TOKEN_ENDPOINT,
            form=SECRET_FORM,
            request_id="rid-6",
        )
    assert writer.rows[0].refused is True
    _no_creds_in_rows(writer)


# ---------------------------------------------------------------------------
# Route module (HTTP surface)
# ---------------------------------------------------------------------------


def _make_app(writer: RecordingToolEgressLogWriter, **kw) -> FastAPI:
    gw = _router(writer, **kw)
    app = FastAPI()
    app.state.config = gw.config
    app.state.router = gw
    app.include_router(oauth_router)
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.unit
async def test_route_discover_endpoint_200() -> None:
    writer = RecordingToolEgressLogWriter()
    app = _make_app(writer)
    with respx.mock:
        respx.get(f"{MCP_URL}/.well-known/oauth-protected-resource").mock(
            return_value=httpx.Response(200, json=_prm_doc())
        )
        respx.get(f"{AS_BASE}/.well-known/oauth-authorization-server").mock(
            return_value=httpx.Response(200, json=_as_doc())
        )
        async with _client(app) as c:
            resp = await c.post("/v1/oauth/mcp-oauth/discover", json={})
    assert resp.status_code == 200
    assert resp.json()["token_endpoint"] == TOKEN_ENDPOINT


@pytest.mark.unit
async def test_route_discover_endpoint_refused_403() -> None:
    writer = RecordingToolEgressLogWriter()
    app = _make_app(writer)
    async with _client(app) as c:
        resp = await c.post("/v1/oauth/nope/discover", json={})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "egress_refused"
    assert writer.rows[0].refused is True


@pytest.mark.unit
async def test_route_token_endpoint_relays_oauth_error_400() -> None:
    writer = RecordingToolEgressLogWriter()
    app = _make_app(writer)
    err = {"error": "invalid_grant"}
    with respx.mock:
        respx.post(TOKEN_ENDPOINT).mock(return_value=httpx.Response(400, json=err))
        async with _client(app) as c:
            resp = await c.post(
                "/v1/oauth/mcp-oauth/token",
                json={"token_endpoint": TOKEN_ENDPOINT, "form": SECRET_FORM},
            )
    assert resp.status_code == 400
    assert resp.json() == err
    _no_creds_in_rows(writer)


@pytest.mark.unit
async def test_route_token_endpoint_200_relays_token() -> None:
    writer = RecordingToolEgressLogWriter()
    app = _make_app(writer)
    with respx.mock:
        respx.post(TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(200, json=SECRET_TOKEN_RESPONSE)
        )
        async with _client(app) as c:
            resp = await c.post(
                "/v1/oauth/mcp-oauth/token",
                json={"token_endpoint": TOKEN_ENDPOINT, "form": SECRET_FORM},
            )
    assert resp.status_code == 200
    assert resp.json() == SECRET_TOKEN_RESPONSE
    _no_creds_in_rows(writer)


@pytest.mark.unit
async def test_route_token_endpoint_refused_403() -> None:
    writer = RecordingToolEgressLogWriter()
    app = _make_app(writer)
    async with _client(app) as c:
        resp = await c.post(
            "/v1/oauth/mcp-oauth/token",
            json={"token_endpoint": "https://evil.example/token", "form": SECRET_FORM},
        )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "egress_refused"
    _no_creds_in_rows(writer)


@pytest.mark.unit
async def test_routes_require_gateway_key_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", "secret-key")
    writer = RecordingToolEgressLogWriter()
    app = _make_app(writer)
    with respx.mock:
        respx.get(f"{MCP_URL}/.well-known/oauth-protected-resource").mock(
            return_value=httpx.Response(200, json=_prm_doc())
        )
        respx.get(f"{AS_BASE}/.well-known/oauth-authorization-server").mock(
            return_value=httpx.Response(200, json=_as_doc())
        )
        async with _client(app) as c:
            missing = await c.post("/v1/oauth/mcp-oauth/discover", json={})
            ok = await c.post(
                "/v1/oauth/mcp-oauth/discover",
                json={},
                headers={"X-LQ-AI-Gateway-Key": "secret-key"},
            )
            missing_tok = await c.post(
                "/v1/oauth/mcp-oauth/token",
                json={"token_endpoint": TOKEN_ENDPOINT, "form": SECRET_FORM},
            )
    assert missing.status_code == 401
    assert ok.status_code == 200
    assert missing_tok.status_code == 401


@pytest.mark.unit
async def test_routes_registered_on_app(gateway_app) -> None:
    paths = gateway_app.openapi()["paths"]
    assert "/v1/oauth/{provider}/discover" in paths
    assert "post" in paths["/v1/oauth/{provider}/discover"]
    assert "/v1/oauth/{provider}/token" in paths
    assert "post" in paths["/v1/oauth/{provider}/token"]
