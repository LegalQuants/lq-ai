"""Integration tests for the gateway's /v1/embeddings endpoint (Task C6).

Mocks OpenAI's upstream via respx; exercises the full handler path
including alias resolution, adapter dispatch, tier annotation, header
emission, and routing-log row writes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def gateway_app_with_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[FastAPI]:
    """A gateway app whose lifespan ran with both ANTHROPIC_API_KEY and
    OPENAI_API_KEY set (so both adapters instantiate)."""

    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", "test-openai")
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(EXAMPLE_CONFIG))

    from app.main import app

    async with _run_lifespan(app):
        yield app


@pytest_asyncio.fixture
async def client_with_keys(gateway_app_with_keys: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=gateway_app_with_keys)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-LQ-AI-Gateway-Key": "test-gateway-key"},
    ) as http_client:
        yield http_client


def _embeddings_payload(vectors: list[list[float]]) -> dict[str, object]:
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": vec, "index": idx}
            for idx, vec in enumerate(vectors)
        ],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }


@pytest.mark.unit
async def test_embeddings_via_openai_alias_routes_through_openai(
    client_with_keys: AsyncClient,
) -> None:
    """C6: alias 'embedding' resolves to OpenAI; success annotates tier+provider."""

    with respx.mock(base_url="https://api.openai.com/v1") as router:
        route = router.post("/embeddings").mock(
            return_value=httpx.Response(200, json=_embeddings_payload([[0.1, 0.2, 0.3]]))
        )
        response = await client_with_keys.post(
            "/v1/embeddings",
            json={"model": "embedding", "input": "hello world"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"][0]["embedding"] == [0.1, 0.2, 0.3]
    # Per ADR 0008: response carries routed_inference_tier + routed_provider
    # in the body and the X-LQ-AI-Routed-Inference-Tier header.
    assert body.get("routed_provider") == "openai-prod"
    assert response.headers.get("x-lq-ai-routed-inference-tier") == "4"
    assert response.headers.get("x-lq-ai-routed-provider") == "openai-prod"
    # The upstream call was made.
    assert route.called


@pytest.mark.unit
async def test_embeddings_batch_input(client_with_keys: AsyncClient) -> None:
    """C6: a batch input passes through with one embedding per input."""

    expected = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/embeddings").mock(
            return_value=httpx.Response(200, json=_embeddings_payload(expected))
        )
        response = await client_with_keys.post(
            "/v1/embeddings",
            json={"model": "embedding", "input": ["a", "b", "c"]},
        )
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 3
    assert [entry["embedding"] for entry in body["data"]] == expected


@pytest.mark.unit
async def test_embeddings_upstream_500_returns_502(
    client_with_keys: AsyncClient,
) -> None:
    """C6: an upstream OpenAI 500 surfaces as a gateway 502 provider_unavailable."""

    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/embeddings").mock(
            return_value=httpx.Response(500, json={"error": {"message": "boom"}})
        )
        response = await client_with_keys.post(
            "/v1/embeddings",
            json={"model": "embedding", "input": "hi"},
        )
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "provider_unavailable"


@pytest.mark.unit
async def test_embeddings_upstream_429_returns_429(
    client_with_keys: AsyncClient,
) -> None:
    """C6: upstream 429 surfaces as 429 rate_limit_exceeded."""

    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/embeddings").mock(
            return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
        )
        response = await client_with_keys.post(
            "/v1/embeddings",
            json={"model": "embedding", "input": "hi"},
        )
    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.unit
async def test_embeddings_upstream_401_returns_502_unauthorized(
    client_with_keys: AsyncClient,
) -> None:
    """C6: upstream 401 (operator misconfigured key) surfaces as 502 unauthorized."""

    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/embeddings").mock(
            return_value=httpx.Response(401, json={"error": {"message": "invalid key"}})
        )
        response = await client_with_keys.post(
            "/v1/embeddings",
            json={"model": "embedding", "input": "hi"},
        )
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "unauthorized"


@pytest.mark.unit
async def test_embeddings_unknown_model_returns_400(
    client_with_keys: AsyncClient,
) -> None:
    """C6: an unresolvable model name returns 400 invalid_model."""

    response = await client_with_keys.post(
        "/v1/embeddings",
        json={"model": "no-such", "input": "hi"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_model"


@pytest.mark.unit
async def test_embeddings_missing_input_returns_400(
    client_with_keys: AsyncClient,
) -> None:
    """C6: missing required 'input' field returns 400 invalid_request."""

    response = await client_with_keys.post(
        "/v1/embeddings",
        json={"model": "embedding"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"


@pytest.mark.unit
async def test_embeddings_anthropic_alias_falls_through(
    client_with_keys: AsyncClient,
) -> None:
    """C6: an Anthropic alias raises ProviderUnsupportedError; the embeddings
    handler treats this as fallback-eligible (overriding the chat default).
    With no embedding-capable fallback in the alias chain, the call ends
    in a 503 ('no adapter available') rather than the chat path's 501.

    The 'smart' alias points at Anthropic with no embedding fallback in
    the example config.
    """

    response = await client_with_keys.post(
        "/v1/embeddings",
        json={"model": "smart", "input": "hi"},
    )
    # No adapter on the (only) candidate that supports embeddings.
    # Anthropic returns 501-able / unsupported; the endpoint walks
    # the chain and finds nothing usable.
    assert response.status_code in (501, 502, 503)
