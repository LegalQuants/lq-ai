"""ADR 0027 gateway timeout defaults, operator overrides and connect cap."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import ValidationError

from app.clients.gateway import (
    DEFAULT_TIMEOUT_SECONDS,
    GatewayClient,
    close_gateway_client,
    get_gateway_client,
)
from app.config import Settings, get_settings
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
async def isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncIterator[None]:
    """Isolate cached clients/settings and avoid reading a developer's .env."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LQ_AI_GATEWAY_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("LQ_AI_GATEWAY_URL", "http://gateway.test")
    await close_gateway_client()
    get_settings.cache_clear()
    try:
        yield
    finally:
        await close_gateway_client()
        get_settings.cache_clear()


def test_default_timeout_matches_accepted_adr() -> None:
    """The API hop waits longer than the gateway's default 600-second budget."""
    assert get_settings().lq_ai_gateway_timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 900.0
    assert get_gateway_client().http_client.timeout.as_dict() == {
        "connect": 10.0,
        "read": 900.0,
        "write": 900.0,
        "pool": 900.0,
    }


@pytest.mark.parametrize("seconds", [1800.0, 12.5, 2.5])
def test_operator_timeout_reaches_factory(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """Long generation budgets do not lengthen connection establishment."""
    monkeypatch.setenv("LQ_AI_GATEWAY_TIMEOUT_SECONDS", str(seconds))
    assert get_gateway_client().http_client.timeout.as_dict() == {
        "connect": min(seconds, 10.0),
        "read": seconds,
        "write": seconds,
        "pool": seconds,
    }


@pytest.mark.parametrize("seconds", [12.5, 2.5])
async def test_explicit_constructor_timeout_wins(
    monkeypatch: pytest.MonkeyPatch, seconds: float
) -> None:
    """Direct construction retains its caller's budget and the connect cap."""
    monkeypatch.setenv("LQ_AI_GATEWAY_TIMEOUT_SECONDS", "1800")
    client = GatewayClient("http://gateway.test", "test-key", timeout=seconds)
    try:
        assert client.http_client.timeout.read == seconds
        assert client.http_client.timeout.connect == min(seconds, 10.0)
    finally:
        await client.aclose()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "invalid"])
def test_invalid_timeout_is_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Only positive finite durations are accepted as deployment settings."""
    monkeypatch.setenv("LQ_AI_GATEWAY_TIMEOUT_SECONDS", value)
    with pytest.raises(ValidationError, match="lq_ai_gateway_timeout_seconds"):
        Settings()


@pytest.mark.parametrize("stream", [False, True])
@respx.mock
async def test_request_transport_uses_configured_timeout(
    monkeypatch: pytest.MonkeyPatch, stream: bool
) -> None:
    """Streaming and ordinary calls carry the configured HTTP timeout legs."""
    monkeypatch.setenv("LQ_AI_GATEWAY_TIMEOUT_SECONDS", "1800")
    client = get_gateway_client()
    if stream:
        route = respx.post("http://gateway.test/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, text="data: [DONE]\n\n", headers={"content-type": "text/event-stream"}
            )
        )
        request = ChatCompletionRequest(
            model="smart", messages=[ChatCompletionMessage(role="user", content="hi")]
        )
        async for _ in client.chat_completion_stream(request):
            pass
    else:
        route = respx.get("http://gateway.test/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        await client.list_models()

    assert route.call_count == 1
    assert route.calls.last.request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 1800.0,
        "write": 1800.0,
        "pool": 1800.0,
    }


@respx.mock
async def test_health_probe_retains_short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The long inference budget does not delay the health endpoint."""
    monkeypatch.setenv("LQ_AI_GATEWAY_TIMEOUT_SECONDS", "1800")
    route = respx.get("http://gateway.test/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    assert await get_gateway_client().health_check()
    assert route.calls.last.request.extensions["timeout"] == {
        "connect": 5.0,
        "read": 5.0,
        "write": 5.0,
        "pool": 5.0,
    }
