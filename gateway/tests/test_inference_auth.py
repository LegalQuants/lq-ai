"""Regression tests for the inference router's gateway-key auth gate (GW-01).

The inference router (``/v1/chat/completions``, ``/v1/embeddings``,
``/v1/models``, ``/v1/citation-engine/config``) must enforce the
``X-LQ-AI-Gateway-Key`` shared secret when one is configured, matching the
admin/tools/oauth routers and the auth already declared in
``docs/api/gateway-openapi.yaml``. Prior to the fix the router was mounted with
no ``dependencies=[Depends(require_gateway_key)]``, so these endpoints accepted
unauthenticated requests. Refs #288.

These tests mount only the inference router on a bare app (the lightweight
``_make_app`` idiom from ``test_tools_route.py``) so the auth gate is exercised
in isolation, without the full gateway lifespan. The auth dependency runs before
the path operation, so a 401 never reaches the handler and no router/adapter
wiring is needed; the positive (authenticated) path is covered by the existing
inference tests.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.inference import router as inference_router
from app.config import GatewayConfig


def _make_app() -> FastAPI:
    app = FastAPI()
    # gateway_auth.enabled defaults to True; with LQ_AI_GATEWAY_KEY set in the
    # environment the gate resolves a non-empty expected key and enforces it.
    app.state.config = GatewayConfig.model_validate({})
    app.include_router(inference_router)
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.unit
async def test_chat_completions_requires_gateway_key_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /v1/chat/completions is 401 without a valid X-LQ-AI-Gateway-Key."""

    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", "expected-key-value")
    app = _make_app()
    async with _client(app) as c:
        missing = await c.post("/v1/chat/completions", json={"model": "smart", "messages": []})
        wrong = await c.post(
            "/v1/chat/completions",
            json={"model": "smart", "messages": []},
            headers={"X-LQ-AI-Gateway-Key": "nope"},
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401


@pytest.mark.unit
async def test_embeddings_requires_gateway_key_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /v1/embeddings is 401 without a valid X-LQ-AI-Gateway-Key."""

    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", "expected-key-value")
    app = _make_app()
    async with _client(app) as c:
        missing = await c.post("/v1/embeddings", json={"model": "embedding", "input": "hello"})
    assert missing.status_code == 401
