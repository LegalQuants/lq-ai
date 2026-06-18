"""Unit tests for GatewayClient OAuth passthrough helpers (PR4c/Task 4A).

Covers:
- list_mcp_oauth_config: filtering, field mapping, malformed-entry exclusion
- oauth_discover: happy path, gateway 403 envelope → raises
- oauth_token: (a) 200 token, (b) AS 400 string-error relayed without raising,
               (c) gateway 403 dict-envelope raises, (d) timeout

No FastAPI app or database needed — pure respx.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.gateway import GATEWAY_KEY_HEADER, GatewayClient
from app.errors import GatewayTimeout, InternalError

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-secret"


def _client() -> GatewayClient:
    return GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)


# ---------------------------------------------------------------------------
# list_mcp_oauth_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_mcp_oauth_config_returns_mcp_oauth_providers() -> None:
    """Only mcp+oauth entries are returned; others are excluded."""
    config = {
        "tool_providers": [
            # included: mcp + oauth, all fields present
            {
                "name": "acme-mcp",
                "type": "mcp",
                "auth": "oauth",
                "base_url": "https://acme.example/mcp",
                "oauth_client_id": "client-abc",
            },
            # excluded: mcp + bearer (not oauth)
            {
                "name": "mcp-bearer",
                "type": "mcp",
                "auth": "bearer",
                "base_url": "https://bearer.example/mcp",
                "oauth_client_id": "irrelevant",
            },
            # excluded: non-mcp provider
            {
                "name": "courtlistener-prod",
                "type": "http",
                "auth": "bearer",
                "base_url": "https://cl.example",
            },
            # included: second valid mcp+oauth
            {
                "name": "legal-mcp",
                "type": "mcp",
                "auth": "oauth",
                "base_url": "https://legal.example/mcp",
                "oauth_client_id": "client-xyz",
            },
        ]
    }
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        mock.get("/admin/v1/config").mock(return_value=httpx.Response(200, json=config))
        result = await _client().list_mcp_oauth_config()

    assert len(result) == 2
    assert result[0] == {
        "name": "acme-mcp",
        "server_url": "https://acme.example/mcp",
        "oauth_client_id": "client-abc",
    }
    assert result[1] == {
        "name": "legal-mcp",
        "server_url": "https://legal.example/mcp",
        "oauth_client_id": "client-xyz",
    }


@pytest.mark.asyncio
async def test_list_mcp_oauth_config_filters_malformed_entries() -> None:
    """Non-dict entries and entries missing required fields are silently dropped."""
    config = {
        "tool_providers": [
            # non-dict entry
            "not-a-dict",
            # missing oauth_client_id
            {
                "name": "partial-mcp",
                "type": "mcp",
                "auth": "oauth",
                "base_url": "https://partial.example/mcp",
            },
            # missing base_url
            {
                "name": "no-url-mcp",
                "type": "mcp",
                "auth": "oauth",
                "oauth_client_id": "cid",
            },
            # valid
            {
                "name": "good-mcp",
                "type": "mcp",
                "auth": "oauth",
                "base_url": "https://good.example/mcp",
                "oauth_client_id": "cid-good",
            },
        ]
    }
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        mock.get("/admin/v1/config").mock(return_value=httpx.Response(200, json=config))
        result = await _client().list_mcp_oauth_config()

    assert len(result) == 1
    assert result[0]["name"] == "good-mcp"


@pytest.mark.asyncio
async def test_list_mcp_oauth_config_empty_providers() -> None:
    """Returns empty list when tool_providers is absent."""
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        mock.get("/admin/v1/config").mock(return_value=httpx.Response(200, json={}))
        result = await _client().list_mcp_oauth_config()
    assert result == []


# ---------------------------------------------------------------------------
# oauth_discover
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_discover_happy_path() -> None:
    """Returns the metadata dict; POSTs to the correct path with gateway key."""
    metadata = {
        "authorization_endpoint": "https://as.example/auth",
        "token_endpoint": "https://as.example/token",
        "issuer": "https://as.example",
        "resource": "https://acme.example/mcp",
        "scopes_supported": ["read"],
        "authorization_response_iss_parameter_supported": True,
    }
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        route = mock.post("/v1/oauth/acme-mcp/discover").mock(
            return_value=httpx.Response(200, json=metadata)
        )
        result = await _client().oauth_discover("acme-mcp")

    assert route.called
    assert route.calls.last.request.headers[GATEWAY_KEY_HEADER] == GATEWAY_KEY
    assert result["authorization_endpoint"] == "https://as.example/auth"
    assert result["token_endpoint"] == "https://as.example/token"


@pytest.mark.asyncio
async def test_oauth_discover_gateway_error_raises() -> None:
    """Gateway 403 envelope (dict error) → raises InternalError (egress_refused is unmapped)."""
    body = {"error": {"code": "egress_refused", "message": "egress blocked", "details": {}}}
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        mock.post("/v1/oauth/acme-mcp/discover").mock(return_value=httpx.Response(403, json=body))
        with pytest.raises(InternalError):
            await _client().oauth_discover("acme-mcp")


# ---------------------------------------------------------------------------
# oauth_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_token_200_returns_token_body() -> None:
    """(a) 200 success: returns (200, token_body) without raising."""
    token_body = {
        "access_token": "tok-abc",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        route = mock.post("/v1/oauth/acme-mcp/token").mock(
            return_value=httpx.Response(200, json=token_body)
        )
        status, body = await _client().oauth_token(
            "acme-mcp",
            token_endpoint="https://as.example/token",
            form={"grant_type": "authorization_code", "code": "xyz"},
        )

    assert route.called
    assert status == 200
    assert body["access_token"] == "tok-abc"
    # Verify gateway key was sent
    assert route.calls.last.request.headers[GATEWAY_KEY_HEADER] == GATEWAY_KEY


@pytest.mark.asyncio
async def test_oauth_token_as_400_string_error_relayed_without_raising() -> None:
    """(b) AS 400 with RFC 6749 string error: returns (400, body) and does NOT raise."""
    as_error = {
        "error": "invalid_grant",
        "error_description": "Authorization code expired",
    }
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        mock.post("/v1/oauth/acme-mcp/token").mock(return_value=httpx.Response(400, json=as_error))
        status, body = await _client().oauth_token(
            "acme-mcp",
            token_endpoint="https://as.example/token",
            form={"grant_type": "authorization_code", "code": "expired-code"},
        )

    assert status == 400
    # The string-error discriminator: error is a str, not a dict → relayed as-is
    assert body["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_oauth_token_gateway_403_dict_envelope_raises() -> None:
    """(c) Gateway 403 with dict error envelope → raises InternalError (egress_refused is unmapped)."""
    body = {"error": {"code": "egress_refused", "message": "egress blocked", "details": {}}}
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        mock.post("/v1/oauth/acme-mcp/token").mock(return_value=httpx.Response(403, json=body))
        with pytest.raises(InternalError):
            await _client().oauth_token(
                "acme-mcp",
                token_endpoint="https://as.example/token",
                form={"grant_type": "authorization_code", "code": "xyz"},
            )


@pytest.mark.asyncio
async def test_oauth_token_timeout_raises_gateway_timeout() -> None:
    """(d) Timeout → GatewayTimeout."""
    with respx.mock(base_url=GATEWAY_BASE) as mock:
        mock.post("/v1/oauth/acme-mcp/token").mock(
            side_effect=httpx.ReadTimeout("timed out", request=None)
        )
        with pytest.raises(GatewayTimeout):
            await _client().oauth_token(
                "acme-mcp",
                token_endpoint="https://as.example/token",
                form={"grant_type": "authorization_code", "code": "xyz"},
            )
