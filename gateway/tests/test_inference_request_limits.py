"""Request-size ceiling enforcement (pen-test finding gateway#F6).

request_validation (max_max_tokens, max_messages_per_request,
max_total_request_chars) was loaded but enforced on no request path, allowing
unbounded per-request provider spend. The chat-completions handler now rejects
over-limit requests with HTTP 400 before dispatch.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api import inference_router
from app.config_holder import MutableConfigHolder
from app.config_loader import load_config
from app.errors import LQAIError
from app.providers import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ProviderAdapter,
    ProviderHealth,
    ProviderUnsupportedError,
)
from app.router import Router
from app.routing_log import RecordingRoutingLogWriter

GW_KEY = "test-gateway-key-req-limits"
HDR = {"X-LQ-AI-Gateway-Key": GW_KEY}

CONFIG: dict[str, Any] = {
    "gateway_auth": {"enabled": True, "api_key_env": "LQ_AI_GATEWAY_KEY"},
    "providers": [
        {
            "name": "p",
            "type": "anthropic",
            "base_url": "https://p.example",
            "api_key_env": "P_KEY",
            "tier": 2,
            "models": ["m"],
        },
    ],
    "model_aliases": {"a": {"primary": {"provider": "p", "model": "m"}}},
    "request_validation": {
        "max_max_tokens": 100,
        "max_messages_per_request": 3,
        "max_total_request_chars": 50,
    },
}


class FakeAdapter(ProviderAdapter):
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    async def chat_completion(
        self, request: ChatCompletionRequest, *, model: str, stream: bool
    ) -> ChatCompletionResponse:
        self.calls += 1
        return ChatCompletionResponse(
            id="r1",
            created=1,
            model=model,
            choices=[
                ChatCompletionChoice(
                    message=ChatCompletionMessage(role="assistant", content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    async def embeddings(self, request: Any, *, model: str) -> Any:
        raise ProviderUnsupportedError("n/a", details={"model": model})

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, reachable=True)

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture
async def ctx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[AsyncClient, FakeAdapter]]:
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", GW_KEY)
    cfg_path = tmp_path / "gateway.yaml"
    cfg_path.write_text(yaml.safe_dump(CONFIG, sort_keys=False), encoding="utf-8")
    config = load_config(cfg_path)
    holder = MutableConfigHolder(config, config_path=cfg_path)
    adapter = FakeAdapter("p")
    app = FastAPI()
    app.state.config = config
    app.state.config_holder = holder
    app.state.adapters = {"p": adapter}
    app.state.retired_adapters = []
    app.state.tool_adapters = {}
    app.state.routing_log = RecordingRoutingLogWriter()
    app.state.router = Router(
        config=config, adapters={"p": adapter}, config_provider=holder.current
    )
    app.include_router(inference_router)

    @app.exception_handler(LQAIError)
    async def _h(_r: Any, exc: LQAIError) -> JSONResponse:
        return JSONResponse(status_code=exc.effective_http_status, content=exc.to_envelope())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=HDR) as c:
        yield c, adapter


@pytest.mark.integration
async def test_within_limits_passes(ctx: tuple[AsyncClient, FakeAdapter]) -> None:
    c, adapter = ctx
    r = await c.post(
        "/v1/chat/completions",
        json={"model": "a", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50},
    )
    assert r.status_code == 200, r.text
    assert adapter.calls == 1


@pytest.mark.integration
async def test_max_tokens_over_limit_refused(ctx: tuple[AsyncClient, FakeAdapter]) -> None:
    c, adapter = ctx
    r = await c.post(
        "/v1/chat/completions",
        json={"model": "a", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 999},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_request"
    assert adapter.calls == 0  # never dispatched


@pytest.mark.integration
async def test_too_many_messages_refused(ctx: tuple[AsyncClient, FakeAdapter]) -> None:
    c, adapter = ctx
    msgs = [{"role": "user", "content": "x"} for _ in range(4)]  # limit is 3
    r = await c.post("/v1/chat/completions", json={"model": "a", "messages": msgs})
    assert r.status_code == 400
    assert r.json()["error"]["details"]["limit"] == 3
    assert adapter.calls == 0


@pytest.mark.integration
async def test_too_many_chars_refused(ctx: tuple[AsyncClient, FakeAdapter]) -> None:
    c, adapter = ctx
    r = await c.post(
        "/v1/chat/completions",
        json={"model": "a", "messages": [{"role": "user", "content": "y" * 200}]},  # limit 50
    )
    assert r.status_code == 400
    assert r.json()["error"]["details"]["limit"] == 50
    assert adapter.calls == 0
