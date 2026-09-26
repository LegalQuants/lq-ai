"""Regression tests for D1 tier-floor enforcement across the fallback chain.

Pen-test 2026-09-25 finding gateway#F1 (HIGH): the tier floor was checked
only against the primary candidate (``candidates[0]``). When the primary
failed (network error, or no adapter at startup) the router re-resolved and
fell through to a weaker-tier fallback *without re-checking the floor*, so a
privileged request could land on a lower-assurance provider with HTTP 200.

The fix enforces the floor on every dispatch target: candidates weaker than
the floor are dropped before the walk, on both the non-streaming router path
(``Router.chat_completion(..., floor=...)``) and the streaming path
(``_stream_with_fallback`` iterates the pre-filtered candidate list).

These tests assert the FIXED behaviour: a floor-violating fallback is never
dispatched. The control test proves the floor still fires on the primary.

Under PRD §1.5.2: lower tier number = stronger security;
``minimum_inference_tier=N`` requires the routed tier to be ``<= N``.
"""

from __future__ import annotations

import json
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
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ProviderAdapter,
    ProviderHealth,
    ProviderNetworkError,
    ProviderUnsupportedError,
)
from app.router import Router
from app.routing_log import RecordingRoutingLogWriter

GW_KEY = "test-gateway-key-tier-floor-fallback"
HDR = {"X-LQ-AI-Gateway-Key": GW_KEY}

# "strong" is Tier 2, "weak" is Tier 4. Alias "smart" is primary=strong with a
# fallback to weak. A request with minimum_inference_tier=2 must be served by
# strong or refused — it must NEVER be served by weak.
BASE_CONFIG: dict[str, Any] = {
    "gateway_auth": {"enabled": True, "api_key_env": "LQ_AI_GATEWAY_KEY"},
    "providers": [
        {
            "name": "strong",
            "type": "anthropic",
            "base_url": "https://strong.example",
            "api_key_env": "STRONG_KEY",
            "tier": 2,
            "models": ["m-strong"],
        },
        {
            "name": "weak",
            "type": "openai",
            "base_url": "https://weak.example",
            "api_key_env": "WEAK_KEY",
            "tier": 4,
            "models": ["m-weak"],
        },
    ],
    "model_aliases": {
        "smart": {
            "primary": {"provider": "strong", "model": "m-strong"},
            "fallback": [{"provider": "weak", "model": "m-weak"}],
        }
    },
}


class FakeAdapter(ProviderAdapter):
    def __init__(self, name: str, *, raises: Exception | None = None) -> None:
        self.name = name
        self._raises = raises
        self.calls: list[tuple[str, bool]] = []

    async def chat_completion(
        self, request: ChatCompletionRequest, *, model: str, stream: bool
    ) -> ChatCompletionResponse | AsyncIterator[ChatCompletionChunk]:
        self.calls.append((model, stream))
        if self._raises is not None:
            raise self._raises
        if stream:

            async def gen() -> AsyncIterator[ChatCompletionChunk]:
                yield ChatCompletionChunk(
                    id="c1",
                    created=1,
                    model=model,
                    choices=[
                        ChatCompletionChunkChoice(
                            delta=ChatCompletionDelta(role="assistant", content="hello"),
                            finish_reason="stop",
                        )
                    ],
                    usage=ChatCompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )

            return gen()
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


def _write_cfg(tmp_path: Path, cfg: dict[str, Any]) -> Path:
    p = tmp_path / "gateway.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return p


def _app(
    cfg_path: Path, adapters: dict[str, ProviderAdapter]
) -> tuple[FastAPI, RecordingRoutingLogWriter]:
    config = load_config(cfg_path)
    holder = MutableConfigHolder(config, config_path=cfg_path)
    app = FastAPI()
    app.state.config = config
    app.state.config_holder = holder
    app.state.adapters = adapters
    app.state.retired_adapters = []
    app.state.tool_adapters = {}
    recorder = RecordingRoutingLogWriter()
    app.state.routing_log = recorder
    app.state.router = Router(config=config, adapters=adapters, config_provider=holder.current)
    app.include_router(inference_router)
    app.include_router(admin_router)

    @app.exception_handler(LQAIError)
    async def _h(_r: Any, exc: LQAIError) -> JSONResponse:
        return JSONResponse(status_code=exc.effective_http_status, content=exc.to_envelope())

    return app, recorder


@pytest_asyncio.fixture
async def client_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", GW_KEY)
    made: list[AsyncClient] = []

    async def make(cfg: dict[str, Any], adapters: dict[str, ProviderAdapter]):
        path = _write_cfg(tmp_path, cfg)
        app, recorder = _app(path, adapters)
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=HDR)
        made.append(c)
        return c, recorder, path

    yield make
    for c in made:
        await c.aclose()


def _chat(model: str, **extra: Any) -> dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": "hi"}], **extra}


@pytest.mark.integration
async def test_primary_failure_does_not_downgrade_to_weaker_fallback(client_factory) -> None:
    """Primary (tier 2) fails; the tier-4 fallback must NOT be dispatched."""

    strong = FakeAdapter("strong", raises=ProviderNetworkError("upstream down", details={}))
    weak = FakeAdapter("weak")
    c, rec, _ = await client_factory(BASE_CONFIG, {"strong": strong, "weak": weak})

    r = await c.post("/v1/chat/completions", json=_chat("smart", minimum_inference_tier=2))

    # The only floor-eligible candidate (strong) failed with a network error;
    # the weaker fallback is filtered out, so the request errors rather than
    # silently downgrading.
    assert r.status_code == 503
    # The prompt never left for the weaker provider.
    assert weak.calls == []
    # No routing-log row records a tier-4 dispatch.
    assert all(row.routed_inference_tier != 4 for row in rec.rows)


@pytest.mark.integration
async def test_missing_primary_adapter_does_not_downgrade(client_factory) -> None:
    """Primary has no adapter (e.g. key unset at startup); no downgrade to weak."""

    weak = FakeAdapter("weak")
    c, _rec, _ = await client_factory(BASE_CONFIG, {"weak": weak})

    r = await c.post("/v1/chat/completions", json=_chat("smart", minimum_inference_tier=2))

    assert r.status_code != 200
    body = r.json()
    assert body.get("routed_inference_tier") != 4
    assert body.get("routed_provider") != "weak"
    assert weak.calls == []


@pytest.mark.integration
async def test_streaming_missing_primary_adapter_does_not_downgrade(client_factory) -> None:
    """Streaming path must not emit a tier-4 frame when only weak has an adapter."""

    weak = FakeAdapter("weak")
    c, _rec, _ = await client_factory(BASE_CONFIG, {"weak": weak})

    r = await c.post(
        "/v1/chat/completions",
        json=_chat("smart", minimum_inference_tier=2, stream=True),
    )

    assert r.status_code == 503
    # The advertised tier is the eligible primary (2), never the dropped tier-4.
    assert r.headers.get("X-LQ-AI-Routed-Inference-Tier") != "4"
    frames = [ln for ln in r.text.split("\n") if ln.startswith("data: ") and "[DONE]" not in ln]
    for frame in frames:
        payload = json.loads(frame[6:])
        assert payload.get("routed_inference_tier") != 4
    assert weak.calls == []


@pytest.mark.integration
async def test_control_floor_still_refuses_when_primary_is_weak(client_factory) -> None:
    """Sanity: the floor still fires on the primary itself (403)."""

    weak = FakeAdapter("weak")
    c, _rec, _ = await client_factory(BASE_CONFIG, {"weak": weak})

    r = await c.post("/v1/chat/completions", json=_chat("weak/m-weak", minimum_inference_tier=2))

    assert r.status_code == 403
    assert r.json()["error"]["code"] == "tier_below_minimum"
    assert weak.calls == []


@pytest.mark.integration
async def test_eligible_fallback_still_used_when_within_floor(client_factory) -> None:
    """Guard against over-blocking: a fallback that satisfies the floor is still used."""

    # floor=4 admits both tiers; primary fails, weak (tier 4) is a valid fallback.
    strong = FakeAdapter("strong", raises=ProviderNetworkError("upstream down", details={}))
    weak = FakeAdapter("weak")
    c, _rec, _ = await client_factory(BASE_CONFIG, {"strong": strong, "weak": weak})

    r = await c.post("/v1/chat/completions", json=_chat("smart", minimum_inference_tier=4))

    assert r.status_code == 200
    body = r.json()
    assert body["routed_provider"] == "weak"
    assert body["routed_inference_tier"] == 4
    assert weak.calls == [("m-weak", False)]
