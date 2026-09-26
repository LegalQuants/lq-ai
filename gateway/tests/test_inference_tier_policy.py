"""Enforcement of the operator ``tier_policy`` block (pen-test finding gateway#F2).

The tier_policy block (allowed_tiers_global, default_minimum_tier,
privileged_minimum_tier) was loaded but never enforced on any request path.
It is now applied in the chat-completions handler:

* default/privileged minimum tier folds into the effective tier floor;
* allowed_tiers_global rejects a routed tier outside the allow-set.

Under PRD §1.5.2: lower tier number = stronger security.
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

from app.api import admin_router, inference_router
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
from app.tier_floor import TierFloor, apply_policy_floor

GW_KEY = "test-gateway-key-tier-policy"
HDR = {"X-LQ-AI-Gateway-Key": GW_KEY}

BASE_CONFIG: dict[str, Any] = {
    "gateway_auth": {"enabled": True, "api_key_env": "LQ_AI_GATEWAY_KEY"},
    "providers": [
        {
            "name": "p3",
            "type": "anthropic",
            "base_url": "https://p3.example",
            "api_key_env": "P3_KEY",
            "tier": 3,
            "models": ["m3"],
        },
        {
            "name": "p4",
            "type": "openai",
            "base_url": "https://p4.example",
            "api_key_env": "P4_KEY",
            "tier": 4,
            "models": ["m4"],
        },
        {
            "name": "p5",
            "type": "openai",
            "base_url": "https://p5.example",
            "api_key_env": "P5_KEY",
            "tier": 5,
            "models": ["m5"],
        },
    ],
    "model_aliases": {
        "a3": {"primary": {"provider": "p3", "model": "m3"}},
        "a4": {"primary": {"provider": "p4", "model": "m4"}},
        "a5": {"primary": {"provider": "p5", "model": "m5"}},
    },
    "tier_policy": {
        "allowed_tiers_global": [1, 2, 3, 4],
        "default_minimum_tier": 4,
        "privileged_minimum_tier": 3,
    },
}


class FakeAdapter(ProviderAdapter):
    def __init__(self, name: str) -> None:
        self.name = name

    async def chat_completion(
        self, request: ChatCompletionRequest, *, model: str, stream: bool
    ) -> ChatCompletionResponse:
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


def _build_app(cfg: dict[str, Any], cfg_path: Path) -> FastAPI:
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    config = load_config(cfg_path)
    holder = MutableConfigHolder(config, config_path=cfg_path)
    adapters = {"p3": FakeAdapter("p3"), "p4": FakeAdapter("p4"), "p5": FakeAdapter("p5")}
    app = FastAPI()
    app.state.config = config
    app.state.config_holder = holder
    app.state.adapters = adapters
    app.state.retired_adapters = []
    app.state.tool_adapters = {}
    app.state.routing_log = RecordingRoutingLogWriter()
    app.state.router = Router(config=config, adapters=adapters, config_provider=holder.current)
    app.include_router(inference_router)
    app.include_router(admin_router)

    @app.exception_handler(LQAIError)
    async def _h(_r: Any, exc: LQAIError) -> JSONResponse:
        return JSONResponse(status_code=exc.effective_http_status, content=exc.to_envelope())

    return app


@pytest_asyncio.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", GW_KEY)
    app = _build_app(BASE_CONFIG, tmp_path / "gateway.yaml")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=HDR) as c:
        yield c


@pytest_asyncio.fixture
async def gap_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """Client whose policy floor admits all tiers but whose allow-set has a gap,
    so allowed_tiers_global is exercised independently of the floor."""
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", GW_KEY)
    cfg = {
        **BASE_CONFIG,
        "tier_policy": {
            "allowed_tiers_global": [1, 2, 3, 4],
            "default_minimum_tier": 5,
            "privileged_minimum_tier": 5,
        },
    }
    app = _build_app(cfg, tmp_path / "gateway.yaml")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=HDR) as c:
        yield c


def _chat(model: str, **extra: Any) -> dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": "hi"}], **extra}


@pytest.mark.integration
async def test_default_minimum_tier_allows_tier4(client: AsyncClient) -> None:
    """Non-privileged request to a Tier-4 alias passes (default_minimum_tier=4)."""
    r = await client.post("/v1/chat/completions", json=_chat("a4"))
    assert r.status_code == 200, r.text


@pytest.mark.integration
async def test_privileged_minimum_tier_refuses_tier4(client: AsyncClient) -> None:
    """Privileged request to a Tier-4 alias is refused (privileged_minimum_tier=3)."""
    r = await client.post("/v1/chat/completions", json=_chat("a4", lq_ai_privileged=True))
    assert r.status_code == 403
    body = r.json()
    assert body["error"]["code"] == "tier_below_minimum"
    assert body["error"]["details"]["required_tier"] == 3
    assert body["error"]["details"]["source"] == "tier_policy:privileged"


@pytest.mark.integration
async def test_privileged_allows_tier3(client: AsyncClient) -> None:
    """Privileged request to a Tier-3 alias passes (3 <= privileged floor 3)."""
    r = await client.post("/v1/chat/completions", json=_chat("a3", lq_ai_privileged=True))
    assert r.status_code == 200, r.text


@pytest.mark.integration
async def test_tier5_refused_by_default_floor(client: AsyncClient) -> None:
    """Tier 5 is blocked: default_minimum_tier=4 catches it as tier_below_minimum
    before the allow-list check (both refuse it; the floor fires first)."""
    r = await client.post("/v1/chat/completions", json=_chat("a5"))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "tier_below_minimum"


@pytest.mark.integration
async def test_allowed_tiers_global_blocks_within_floor_tier(gap_client: AsyncClient) -> None:
    """With the floor admitting all tiers, a routed tier outside the allow-set is
    refused as tier_disallowed_globally."""
    r = await gap_client.post("/v1/chat/completions", json=_chat("a5"))
    assert r.status_code == 403
    body = r.json()
    assert body["error"]["code"] == "tier_disallowed_globally"
    assert body["error"]["details"]["resolved_tier"] == 5
    assert body["error"]["details"]["allowed_tiers"] == [1, 2, 3, 4]


@pytest.mark.integration
async def test_request_floor_still_overrides_policy(client: AsyncClient) -> None:
    """A stricter request floor still wins over the policy default."""
    r = await client.post("/v1/chat/completions", json=_chat("a4", minimum_inference_tier=3))
    assert r.status_code == 403
    assert r.json()["error"]["details"]["source"] == "request"


@pytest.mark.unit
def test_apply_policy_floor_semantics() -> None:
    # No resolved floor: policy applies.
    f = apply_policy_floor(
        None, default_minimum_tier=4, privileged_minimum_tier=3, privileged=False
    )
    assert f.value == 4 and f.source == "tier_policy:default"
    f = apply_policy_floor(None, default_minimum_tier=4, privileged_minimum_tier=3, privileged=True)
    assert f.value == 3 and f.source == "tier_policy:privileged"
    # Stricter resolved floor is kept (source preserved).
    strict = TierFloor(value=2, source="skill:x")
    f = apply_policy_floor(
        strict, default_minimum_tier=4, privileged_minimum_tier=3, privileged=False
    )
    assert f.value == 2 and f.source == "skill:x"
    # Weaker resolved floor is overridden by the stricter policy floor.
    weak = TierFloor(value=5, source="request")
    f = apply_policy_floor(
        weak, default_minimum_tier=4, privileged_minimum_tier=3, privileged=False
    )
    assert f.value == 4 and f.source == "tier_policy:default"
