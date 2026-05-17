"""Integration test for the chat-completions surface routing to Azure OpenAI.

Mirrors the shape of :mod:`tests.test_inference_anthropic`: runs the
real FastAPI app (lifespan + router + adapter) and mocks the upstream
Azure HTTPS layer with ``respx``. One end-to-end round-trip closes the
DE-267 acceptance criterion ("one Cypress E2E or gateway-integration
test exercises an end-to-end Azure call (mocked)").

Routes via the raw-passthrough alias syntax (``model:
"azure-openai/<deployment-id>"``) so the test is independent of which
aliases are or aren't defined in ``gateway.yaml.example``'s
``model_aliases`` block.
"""

from __future__ import annotations

import json
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

# Must match gateway.yaml.example's azure-openai provider entry.
AZURE_RESOURCE = "test-openai"
AZURE_API_VERSION = "2024-08-01-preview"
AZURE_DEPLOYMENT = "gpt-4o-prod"
AZURE_UPSTREAM_URL = (
    f"https://{AZURE_RESOURCE}.openai.azure.com"
    f"/openai/deployments/{AZURE_DEPLOYMENT}/chat/completions"
    f"?api-version={AZURE_API_VERSION}"
)


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def azure_app(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    """A gateway app whose lifespan saw ``AZURE_OPENAI_API_KEY``, so
    :class:`AzureOpenAIAdapter` instantiated and lives in
    ``app.state.adapters``."""

    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(EXAMPLE_CONFIG))
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", AZURE_RESOURCE)
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-test-key")

    from app.main import app

    async with _run_lifespan(app):
        yield app


@pytest_asyncio.fixture
async def azure_client(azure_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=azure_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.mark.integration
@respx.mock
async def test_chat_completions_routes_to_azure_via_passthrough(
    azure_client: AsyncClient,
) -> None:
    """End-to-end: a chat request with ``model: 'azure-openai/<deployment>'``
    routes through the gateway to the AzureOpenAIAdapter, posts to the
    Azure deployment-scoped URL with ``api-key`` auth, and returns an
    OpenAI-shaped response.

    Closes DE-267 acceptance criterion (one mocked end-to-end test).
    """

    upstream = respx.post(AZURE_UPSTREAM_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-azure-it-001",
                "object": "chat.completion",
                "created": 1715000000,
                "model": AZURE_DEPLOYMENT,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello from Azure OpenAI.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 6,
                    "total_tokens": 14,
                },
            },
        )
    )

    response = await azure_client.post(
        "/v1/chat/completions",
        json={
            "model": f"azure-openai/{AZURE_DEPLOYMENT}",
            "messages": [
                {"role": "system", "content": "Be brief."},
                {"role": "user", "content": "ping"},
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Hello from Azure OpenAI."
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["total_tokens"] == 14
    assert body["routed_provider"] == "azure-openai"

    # Upstream got the request with Azure auth + deployment-scoped URL.
    assert upstream.called
    sent_req = upstream.calls[-1].request
    assert sent_req.headers.get("api-key") == "az-test-key"
    # OpenAI's Bearer auth must not appear on Azure calls.
    assert "authorization" not in {k.lower() for k in sent_req.headers}
    sent_body = json.loads(sent_req.content)
    # ``model`` in the body is the deployment-id (Azure ignores it under
    # newer api-versions but accepts it; the OpenAI translation helper
    # sets it for wire-compat consistency across api-version vintages).
    assert sent_body["model"] == AZURE_DEPLOYMENT
    assert sent_body["messages"][-1] == {"role": "user", "content": "ping"}
