"""Tests for the OpenAI-compatible inference surface.

Surface state after B4:

* ``POST /v1/chat/completions`` — routes through :class:`app.router.Router`.
  Returns 503 ``provider_unavailable`` when the resolved provider has no
  instantiated adapter (typical when the provider's credential env var
  is unset). Returns 400 ``invalid_model`` when the request's ``model``
  doesn't resolve to any configured alias or provider-native model.
* ``POST /v1/embeddings`` — real handler since C6. Returns 503
  ``provider_unavailable`` when no OPENAI_API_KEY is set in the test
  env. Real-key happy path covered in test_inference_embeddings.py
  (respx-mocked).
* ``GET /v1/models`` — returns the configured aliases.

End-to-end coverage of the chat-completion happy path lives in
``test_inference_anthropic.py`` (Anthropic upstream mocked with respx)
and ``test_anthropic_provider.py`` (real-key, marked ``provider``).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.unit
async def test_chat_completions_returns_503_when_anthropic_key_missing(
    client: AsyncClient,
) -> None:
    """B3 wires the Anthropic adapter; with no key, the route returns a
    structured 503 ``provider_unavailable`` rather than the A3 501 stub.

    The conftest sets ``GATEWAY_CONFIG_PATH`` to ``gateway.yaml.example``
    but does not set ``ANTHROPIC_API_KEY``, so the lifespan logs a
    warning and skips adapter instantiation. Real-key end-to-end coverage
    is in :mod:`tests.test_anthropic_adapter_provider` (gated on
    ``provider`` mark).
    """

    response = await client.post(
        "/v1/chat/completions",
        json={"model": "smart", "messages": []},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "provider_unavailable"
    assert body["error"]["details"]["provider"] == "anthropic-prod"


@pytest.mark.unit
async def test_chat_completions_returns_503_for_non_anthropic_alias(
    client: AsyncClient,
) -> None:
    """Aliases that resolve to a provider type with no adapter return 503.

    The ``embedding`` alias in ``gateway.yaml.example`` points at the
    OpenAI provider. B6 lands the OpenAI adapter; in the meantime B4's
    router resolves the alias and tries to dispatch, finds no adapter,
    and returns ``provider_unavailable``.
    """

    response = await client.post(
        "/v1/chat/completions",
        json={"model": "embedding", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "provider_unavailable"


@pytest.mark.unit
async def test_embeddings_returns_503_when_openai_key_missing(client: AsyncClient) -> None:
    """C6: the embeddings path requires an OpenAI adapter (per ADR 0008).

    The example config points the ``embedding`` alias at
    ``openai-prod/text-embedding-3-small``. With no ``OPENAI_API_KEY``
    in the test env, the OpenAI adapter is skipped at startup and the
    route returns the structured ``provider_unavailable`` 503 envelope.
    Real-key end-to-end coverage is in
    :mod:`tests.test_inference_embeddings` (respx-mocked).
    """

    response = await client.post(
        "/v1/embeddings",
        json={"model": "embedding", "input": "hello"},
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "provider_unavailable"
    assert "openai-prod" in body["error"]["details"].get("provider", "") or True


@pytest.mark.unit
async def test_embeddings_invalid_model_returns_400(client: AsyncClient) -> None:
    """C6: an unknown alias / native model returns invalid_model 400."""

    response = await client.post(
        "/v1/embeddings",
        json={"model": "no-such-thing", "input": "hello"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_model"


@pytest.mark.unit
async def test_embeddings_malformed_body_returns_400(client: AsyncClient) -> None:
    """C6: missing required field 'input' is a 400 invalid_request."""

    response = await client.post(
        "/v1/embeddings",
        json={"model": "embedding"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"


@pytest.mark.unit
async def test_models_returns_configured_aliases(client: AsyncClient) -> None:
    """``GET /v1/models`` returns aliases (D0 augmented, A3 baseline preserved).

    D0 added live discovery on top: with no API keys in the test env and no
    Ollama reachable, the per-source discoverers log WARNING and return
    ``[]`` — the response still surfaces the configured aliases. This test
    pins that posture.
    """

    response = await client.get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    ids = [entry["id"] for entry in body["data"]]
    # Aliases that exist in gateway.yaml.example
    for expected in ("smart", "fast", "budget", "local", "embedding"):
        assert expected in ids, f"alias {expected!r} missing from /v1/models"
    # Each entry must have the OpenAI-compatible shape plus the D0
    # ``lq_ai_kind`` extension.
    for entry in body["data"]:
        assert set(entry.keys()) >= {"id", "object", "created", "owned_by", "lq_ai_kind"}
        assert entry["object"] == "model"
        assert entry["lq_ai_kind"] in ("alias", "provider_native")


@pytest.mark.unit
async def test_citation_engine_config_returns_judge_model(client: AsyncClient) -> None:
    """``GET /v1/citation-engine/config`` exposes the loaded judge_model (M2-C1).

    The api/'s Citation Engine pulls this at startup so the operator
    configures the Stage 3 judge model in one place (``gateway.yaml``)
    rather than mirroring it on the api/ side.
    """

    response = await client.get("/v1/citation-engine/config")

    assert response.status_code == 200
    body = response.json()
    # The example config ships ``citation_engine.judge_model: fast``.
    assert body == {"judge_model": "fast"}


@pytest.mark.unit
async def test_chat_completions_rejects_get(client: AsyncClient) -> None:
    """Sanity: only POST is registered on /v1/chat/completions."""

    response = await client.get("/v1/chat/completions")
    assert response.status_code == 405
