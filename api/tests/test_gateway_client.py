"""Unit tests for the api/ GatewayClient (B5).

The gateway side is mocked with respx; these tests pin the HTTP wire
shape, the error-translation rules, and the streaming envelope parsing.

Coverage targets:

* Non-streaming success: tier surfaced from body and from header.
* Non-streaming gateway 5xx → :class:`GatewayUnreachable` (operator-
  facing 503; user does not see 5xx detail).
* Non-streaming gateway timeout → :class:`GatewayTimeout`.
* Non-streaming gateway 401 → :class:`GatewayUnreachable` with operator
  log (the user must not see "wrong gateway key").
* Non-streaming gateway 4xx with structured body → mapped LQAIError
  subclass (provider_unavailable, invalid_model, etc.).
* Non-streaming gateway 4xx with malformed body → :class:`GatewayInvalidResponse`.
* Streaming happy path.
* Streaming mid-stream error frame.
* Streaming pre-frame error (status >= 400 before any data:).
* Embeddings 501 surfaces correctly.

These are unit tests; they don't need the FastAPI app or the database.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from app.clients.gateway import GATEWAY_KEY_HEADER, GatewayClient
from app.errors import (
    GatewayInvalidResponse,
    GatewayTimeout,
    GatewayUnreachable,
    InternalError,
    InvalidModel,
    ProviderUnavailable,
    RateLimited,
    Unauthorized,
)
from app.schemas.gateway import (
    ChatCompletionMessage,
    ChatCompletionRequest,
)

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-shared-secret"


def _request() -> ChatCompletionRequest:
    """Canonical request used across tests."""

    return ChatCompletionRequest(
        model="smart",
        messages=[ChatCompletionMessage(role="user", content="hello")],
    )


def _success_payload(tier: int = 3, content: str = "hi back") -> dict[str, object]:
    """Build a happy-path /v1/chat/completions response body."""

    return {
        "id": "chatcmpl-abc",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "claude-sonnet-4-6",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "routed_inference_tier": tier,
        "routed_provider": "anthropic-prod",
        "cost_estimate": 0.0001,
    }


@pytest.fixture
async def client() -> AsyncIterator[GatewayClient]:
    """Build a fresh client per test; close it on teardown."""

    c = GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)
    try:
        yield c
    finally:
        await c.aclose()


# --- Non-streaming: success --------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_chat_completion_success_returns_parsed_response(
    client: GatewayClient,
) -> None:
    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(tier=3))
    )

    result = await client.chat_completion(_request())

    assert route.called
    assert result.id == "chatcmpl-abc"
    assert result.choices[0].message.content == "hi back"
    assert result.routed_inference_tier == 3
    assert result.routed_provider == "anthropic-prod"


@pytest.mark.unit
@respx.mock
async def test_chat_completion_sends_gateway_key_header(client: GatewayClient) -> None:
    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )

    await client.chat_completion(_request())

    sent = route.calls[0].request
    assert sent.headers.get(GATEWAY_KEY_HEADER) == GATEWAY_KEY


@pytest.mark.unit
@respx.mock
async def test_chat_completion_forwards_request_id_header(client: GatewayClient) -> None:
    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )

    await client.chat_completion(_request(), request_id="req-xyz")

    sent = route.calls[0].request
    assert sent.headers.get("X-Request-Id") == "req-xyz"


@pytest.mark.unit
@respx.mock
async def test_chat_completion_backfills_tier_from_header_when_body_missing(
    client: GatewayClient,
) -> None:
    """If the body somehow lacks the tier annotation, fall back to the header.

    The current gateway always sets both; this is forward-compat
    belt-and-suspenders, but the logic should be exercised.
    """
    payload = _success_payload(tier=3)
    payload.pop("routed_inference_tier")
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json=payload,
            headers={"X-LQ-AI-Routed-Inference-Tier": "4"},
        )
    )

    result = await client.chat_completion(_request())

    assert result.routed_inference_tier == 4


@pytest.mark.unit
@respx.mock
async def test_chat_completion_overrides_stream_flag_to_false(client: GatewayClient) -> None:
    """The non-streaming method must not send stream=True even if the request had it."""
    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    req = _request()
    req.stream = True  # type: ignore[misc]

    await client.chat_completion(req)

    body = route.calls[0].request.read().decode()
    assert '"stream":false' in body or '"stream": false' in body


# --- Non-streaming: error translation ---------------------------------------


@pytest.mark.unit
@respx.mock
async def test_chat_completion_5xx_without_structured_body_raises_gateway_unreachable(
    client: GatewayClient,
) -> None:
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(500, content=b"internal server error")
    )

    with pytest.raises(GatewayUnreachable) as exc_info:
        await client.chat_completion(_request())

    assert "unexpected server error" in exc_info.value.message.lower()
    assert exc_info.value.details.get("status_code") == 500


@pytest.mark.unit
@respx.mock
async def test_chat_completion_401_raises_gateway_unreachable_not_unauthorized(
    client: GatewayClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """401 from the gateway = backend's auth header was rejected. The user
    must see "service unavailable", not "your gateway key is wrong"."""
    import logging as _logging

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": {"code": "unauthorized", "message": "x"}})
    )

    # pytest's logging plugin can disable loggers between tests; re-enable
    # so the WARNING our handler emits actually reaches caplog. (See the
    # same workaround in test_admin_bootstrap.py.)
    gw_log = _logging.getLogger("app.clients.gateway")
    prior_disabled = gw_log.disabled
    gw_log.disabled = False
    try:
        with (
            caplog.at_level("WARNING", logger="app.clients.gateway"),
            pytest.raises(GatewayUnreachable) as exc_info,
        ):
            await client.chat_completion(_request())
    finally:
        gw_log.disabled = prior_disabled

    assert exc_info.value.effective_http_status == 503
    # The operator-facing log must mention the gateway-key configuration so
    # the misconfiguration is debuggable.
    assert any("gateway-key" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.unit
@respx.mock
async def test_chat_completion_provider_unavailable_maps_to_provider_unavailable(
    client: GatewayClient,
) -> None:
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            502,
            json={
                "error": {
                    "code": "provider_unavailable",
                    "message": "anthropic returned 503",
                    "details": {"upstream_status": 503},
                }
            },
        )
    )

    with pytest.raises(ProviderUnavailable) as exc_info:
        await client.chat_completion(_request())

    assert "anthropic" in exc_info.value.message.lower()
    # The mapper preserves the gateway code in details for operator forensics.
    assert exc_info.value.details.get("gateway_code") == "provider_unavailable"


@pytest.mark.unit
@respx.mock
async def test_chat_completion_invalid_model_maps_to_invalid_model(
    client: GatewayClient,
) -> None:
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            400,
            json={"error": {"code": "invalid_model", "message": "no such alias"}},
        )
    )

    with pytest.raises(InvalidModel):
        await client.chat_completion(_request())


@pytest.mark.unit
@respx.mock
async def test_chat_completion_rate_limit_maps_to_rate_limited(client: GatewayClient) -> None:
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            429,
            json={"error": {"code": "rate_limit_exceeded", "message": "slow down"}},
        )
    )

    with pytest.raises(RateLimited):
        await client.chat_completion(_request())


@pytest.mark.unit
@respx.mock
async def test_chat_completion_unknown_code_maps_to_internal_error(
    client: GatewayClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging as _logging

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            418,
            json={"error": {"code": "totally-made-up", "message": "nope"}},
        )
    )

    gw_log = _logging.getLogger("app.clients.gateway")
    prior_disabled = gw_log.disabled
    gw_log.disabled = False
    try:
        with (
            caplog.at_level("WARNING", logger="app.clients.gateway"),
            pytest.raises(InternalError),
        ):
            await client.chat_completion(_request())
    finally:
        gw_log.disabled = prior_disabled

    # Drift surface: log carries the unknown code so operators can tell.
    assert any("unknown error code" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.unit
@respx.mock
async def test_chat_completion_malformed_error_body_raises_gateway_invalid_response(
    client: GatewayClient,
) -> None:
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(400, content=b"<html>not what you expected</html>")
    )

    with pytest.raises(GatewayInvalidResponse):
        await client.chat_completion(_request())


@pytest.mark.unit
@respx.mock
async def test_chat_completion_invalid_request_maps_to_validation_error(
    client: GatewayClient,
) -> None:
    """Gateway invalid_request → backend ValidationError (400)."""
    from app.errors import ValidationError

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            400,
            json={"error": {"code": "invalid_request", "message": "bad shape"}},
        )
    )

    with pytest.raises(ValidationError):
        await client.chat_completion(_request())


@pytest.mark.unit
@respx.mock
async def test_chat_completion_unauthorized_from_provider_propagates_to_unauthorized(
    client: GatewayClient,
) -> None:
    """A 502 with code=unauthorized (provider auth) is not the gateway-key 401.

    The gateway returns 502 (not 401) when it's the provider's auth that
    failed; we propagate this distinct from the gateway-key 401 case.
    """
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            502,
            json={"error": {"code": "unauthorized", "message": "anthropic rejected key"}},
        )
    )

    with pytest.raises(Unauthorized):
        await client.chat_completion(_request())


@pytest.mark.unit
async def test_chat_completion_timeout_raises_gateway_timeout(
    client: GatewayClient,
) -> None:
    """Use respx to simulate a timeout."""

    with respx.mock(base_url=GATEWAY_BASE) as router:
        router.post("/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("timeout"))

        with pytest.raises(GatewayTimeout) as exc_info:
            await client.chat_completion(_request())

    assert exc_info.value.effective_http_status == 504


@pytest.mark.unit
async def test_chat_completion_network_error_raises_gateway_unreachable(
    client: GatewayClient,
) -> None:
    with respx.mock(base_url=GATEWAY_BASE) as router:
        router.post("/v1/chat/completions").mock(side_effect=httpx.ConnectError("conn refused"))

        with pytest.raises(GatewayUnreachable) as exc_info:
            await client.chat_completion(_request())

    assert exc_info.value.effective_http_status == 503


@pytest.mark.unit
@respx.mock
async def test_chat_completion_non_json_success_raises_invalid_response(
    client: GatewayClient,
) -> None:
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=b"<html>not json</html>")
    )

    with pytest.raises(GatewayInvalidResponse):
        await client.chat_completion(_request())


@pytest.mark.unit
@respx.mock
async def test_chat_completion_schema_violation_raises_invalid_response(
    client: GatewayClient,
) -> None:
    """Body parses as JSON but doesn't fit ChatCompletionResponse schema."""
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )

    with pytest.raises(GatewayInvalidResponse):
        await client.chat_completion(_request())


# --- Streaming ---------------------------------------------------------------


def _sse_frame(payload: str) -> str:
    return f"data: {payload}\n\n"


def _sse_chunk_payload(content: str = "delta", tier: int = 3) -> dict[str, object]:
    return {
        "id": "chatcmpl-stream",
        "object": "chat.completion.chunk",
        "created": 1_700_000_000,
        "model": "claude-sonnet-4-6",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": None,
            }
        ],
        "routed_inference_tier": tier,
        "routed_provider": "anthropic-prod",
    }


@pytest.mark.unit
@respx.mock
async def test_chat_completion_stream_yields_chunks_then_done(
    client: GatewayClient,
) -> None:
    import json as _json

    body = (
        _sse_frame(_json.dumps(_sse_chunk_payload("hi ")))
        + _sse_frame(_json.dumps(_sse_chunk_payload("there")))
        + "data: [DONE]\n\n"
    )
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )

    received: list[str] = []
    async for chunk in client.chat_completion_stream(_request()):
        for choice in chunk.choices:
            if choice.delta.content:
                received.append(choice.delta.content)
        assert chunk.routed_inference_tier == 3

    assert "".join(received) == "hi there"


@pytest.mark.unit
@respx.mock
async def test_chat_completion_stream_mid_stream_error_raises_mapped_lqai_error(
    client: GatewayClient,
) -> None:
    import json as _json

    error_frame = {
        "error": {
            "code": "provider_unavailable",
            "message": "upstream went down mid-stream",
            "details": {"upstream_status": 502},
        }
    }
    body = (
        _sse_frame(_json.dumps(_sse_chunk_payload("partial ")))
        + _sse_frame(_json.dumps(error_frame))
        + "data: [DONE]\n\n"
    )
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )

    received: list[str] = []
    with pytest.raises(ProviderUnavailable) as exc_info:
        async for chunk in client.chat_completion_stream(_request()):
            for choice in chunk.choices:
                if choice.delta.content:
                    received.append(choice.delta.content)

    assert received == ["partial "]
    assert exc_info.value.details.get("gateway_code") == "provider_unavailable"


@pytest.mark.unit
@respx.mock
async def test_chat_completion_stream_pre_frame_error_uses_status_path(
    client: GatewayClient,
) -> None:
    """If the gateway returns 4xx/5xx before any SSE frame, use the same
    error-translation rules as the non-streaming path."""
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            400, json={"error": {"code": "invalid_model", "message": "no such"}}
        )
    )

    with pytest.raises(InvalidModel):
        async for _ in client.chat_completion_stream(_request()):
            pass


@pytest.mark.unit
@respx.mock
async def test_chat_completion_stream_malformed_chunk_raises_invalid_response(
    client: GatewayClient,
) -> None:
    body = "data: not-json\n\n" + "data: [DONE]\n\n"
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )

    with pytest.raises(GatewayInvalidResponse):
        async for _ in client.chat_completion_stream(_request()):
            pass


@pytest.mark.unit
async def test_chat_completion_stream_timeout_raises_gateway_timeout(
    client: GatewayClient,
) -> None:
    with respx.mock(base_url=GATEWAY_BASE) as router:
        router.post("/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("timeout"))

        with pytest.raises(GatewayTimeout):
            async for _ in client.chat_completion_stream(_request()):
                pass


# --- Health check ------------------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_health_check_true_when_gateway_returns_200(client: GatewayClient) -> None:
    respx.get(f"{GATEWAY_BASE}/health").mock(return_value=httpx.Response(200, json={}))

    assert await client.health_check() is True


@pytest.mark.unit
@respx.mock
async def test_health_check_false_when_gateway_errors(client: GatewayClient) -> None:
    respx.get(f"{GATEWAY_BASE}/health").mock(side_effect=httpx.ConnectError("nope"))

    assert await client.health_check() is False


# --- Embeddings (B6 — currently 501) -----------------------------------------


@pytest.mark.unit
@respx.mock
async def test_embeddings_501_propagates_as_internal_error(client: GatewayClient) -> None:
    """The gateway's /v1/embeddings is a 501 stub until B6.

    The client method exists so the future KB / RAG layer can compile
    against a stable signature. Today, the 501 with code=not_implemented
    surfaces as InternalError per the gateway-code map.
    """
    respx.post(f"{GATEWAY_BASE}/v1/embeddings").mock(
        return_value=httpx.Response(
            501,
            json={"error": {"code": "not_implemented", "message": "B6 territory"}},
        )
    )

    with pytest.raises(InternalError):
        await client.embeddings(model="text-embedding-3-large", input_="hello")


# --- Lifecycle ---------------------------------------------------------------


@pytest.mark.unit
async def test_aclose_does_not_raise() -> None:
    c = GatewayClient(base_url=GATEWAY_BASE, gateway_key="x")
    await c.aclose()
    # Idempotent — calling again should not blow up.
    await c.aclose()


# --- D0: list_models ---------------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_list_models_forwards_payload_verbatim(client: GatewayClient) -> None:
    """The proxy returns the gateway's body unchanged."""

    payload = {
        "object": "list",
        "data": [
            {
                "id": "smart",
                "object": "model",
                "created": 0,
                "owned_by": "lq-ai-gateway",
                "lq_ai_kind": "alias",
            },
            {
                "id": "ollama-local/llama3.1:8b",
                "object": "model",
                "created": 0,
                "owned_by": "ollama-local",
                "lq_ai_kind": "provider_native",
                "routed_inference_tier": 1,
                "provider_type": "ollama",
            },
        ],
    }
    respx.get(f"{GATEWAY_BASE}/v1/models").mock(return_value=httpx.Response(200, json=payload))

    result = await client.list_models()
    assert result == payload


@pytest.mark.unit
@respx.mock
async def test_list_models_401_raises_gateway_unreachable(client: GatewayClient) -> None:
    """Gateway 401 must NOT leak through as Unauthorized — it's an operator
    misconfiguration that the user must not see."""

    respx.get(f"{GATEWAY_BASE}/v1/models").mock(
        return_value=httpx.Response(
            401, json={"error": {"code": "unauthorized", "message": "bad key"}}
        )
    )

    with pytest.raises(GatewayUnreachable):
        await client.list_models()


@pytest.mark.unit
@respx.mock
async def test_list_models_5xx_raises_gateway_unreachable(client: GatewayClient) -> None:
    respx.get(f"{GATEWAY_BASE}/v1/models").mock(return_value=httpx.Response(503, text="oops"))
    with pytest.raises(GatewayUnreachable):
        await client.list_models()


@pytest.mark.unit
@respx.mock
async def test_list_models_timeout_raises_gateway_timeout(client: GatewayClient) -> None:
    respx.get(f"{GATEWAY_BASE}/v1/models").mock(side_effect=httpx.TimeoutException("slow"))
    with pytest.raises(GatewayTimeout):
        await client.list_models()


@pytest.mark.unit
@respx.mock
async def test_list_models_sends_gateway_key_header(client: GatewayClient) -> None:
    route = respx.get(f"{GATEWAY_BASE}/v1/models").mock(
        return_value=httpx.Response(200, json={"object": "list", "data": []})
    )
    await client.list_models()
    request = route.calls.last.request
    assert request.headers.get(GATEWAY_KEY_HEADER) == GATEWAY_KEY


# ---------------------------------------------------------------------------
# Citation Engine judge-model fetch (M2-C1).
#
# The api/ pulls the judge-model alias from the gateway over
# GET /v1/citation-engine/config once per process and caches it.
# Failure modes (network, non-200, malformed body) fall back silently
# to the configured default — a missing config endpoint must not crash
# the Citation Engine; Stage 3 just runs against the fallback model.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_judge_model_fetched_from_gateway(client: GatewayClient) -> None:
    """Happy path: the gateway-configured alias propagates back."""

    respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        return_value=httpx.Response(200, json={"judge_model": "fast"})
    )

    judge = await client.get_citation_engine_judge_model()

    assert judge == "fast"


@pytest.mark.unit
@respx.mock
async def test_judge_model_caches_for_process(client: GatewayClient) -> None:
    """Second call doesn't re-hit the gateway."""

    route = respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        return_value=httpx.Response(200, json={"judge_model": "smart"})
    )

    first = await client.get_citation_engine_judge_model()
    second = await client.get_citation_engine_judge_model()

    assert first == "smart"
    assert second == "smart"
    assert route.call_count == 1


@pytest.mark.unit
@respx.mock
async def test_judge_model_falls_back_on_network_error(client: GatewayClient) -> None:
    """A transport failure returns the fallback, not an exception."""

    respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    judge = await client.get_citation_engine_judge_model(fallback="budget")

    assert judge == "budget"


@pytest.mark.unit
@respx.mock
async def test_judge_model_falls_back_on_500(client: GatewayClient) -> None:
    """Gateway 500 returns the fallback (the Citation Engine must keep working)."""

    respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        return_value=httpx.Response(500, text="oops")
    )

    judge = await client.get_citation_engine_judge_model(fallback="fast")

    assert judge == "fast"


@pytest.mark.unit
@respx.mock
async def test_judge_model_falls_back_on_malformed_body(client: GatewayClient) -> None:
    """A 200 with a missing ``judge_model`` key returns the fallback."""

    respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        return_value=httpx.Response(200, json={"other_field": "value"})
    )

    judge = await client.get_citation_engine_judge_model(fallback="fast")

    assert judge == "fast"


@pytest.mark.unit
@respx.mock
async def test_judge_model_failed_fetch_not_cached(client: GatewayClient) -> None:
    """A failed fetch doesn't poison the cache — the next call retries."""

    # First call fails.
    route_failed = respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        return_value=httpx.Response(500, text="oops")
    )
    judge1 = await client.get_citation_engine_judge_model(fallback="fast")
    assert judge1 == "fast"
    assert route_failed.call_count == 1

    # Replace with a 200 and call again — should retry, not return cached fallback.
    respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        return_value=httpx.Response(200, json={"judge_model": "smart"})
    )
    judge2 = await client.get_citation_engine_judge_model(fallback="fast")
    assert judge2 == "smart"


# ---------------------------------------------------------------------------
# Citation Engine ensemble-config fetch (M2-D1).
#
# The api/ pulls the Stage 4 ensemble config from the gateway over the
# same GET /v1/citation-engine/config endpoint and caches it. Failure
# modes (network, non-200, missing block, empty judge_models) return
# None so Stage 4 silently disables — the cascade falls back to Stage 3.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_ensemble_config_fetched_from_gateway(client: GatewayClient) -> None:
    """Happy path: full ensemble block parses into :class:`EnsembleConfig`."""

    respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        return_value=httpx.Response(
            200,
            json={
                "judge_model": "fast",
                "ensemble_verification": {
                    "default_enabled": True,
                    "judge_models": ["fast", "smart"],
                    "aggregation_rule": "strict",
                    "max_cost_per_message_usd": 0.10,
                    "envelope_tier": 4,
                },
            },
        )
    )

    cfg = await client.get_citation_engine_ensemble_config()

    assert cfg is not None
    assert cfg.default_enabled is True
    assert cfg.judge_models == ("fast", "smart")
    assert cfg.aggregation_rule == "strict"
    assert cfg.max_cost_per_message_usd == 0.10
    assert cfg.envelope_tier == 4


@pytest.mark.unit
@respx.mock
async def test_ensemble_config_caches_for_process(client: GatewayClient) -> None:
    """Second call doesn't re-hit the gateway."""

    route = respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        return_value=httpx.Response(
            200,
            json={
                "judge_model": "fast",
                "ensemble_verification": {
                    "default_enabled": False,
                    "judge_models": ["fast"],
                    "aggregation_rule": "strict",
                    "max_cost_per_message_usd": 0.05,
                    "envelope_tier": 3,
                },
            },
        )
    )

    first = await client.get_citation_engine_ensemble_config()
    second = await client.get_citation_engine_ensemble_config()

    assert first is not None
    assert second is not None
    assert first == second
    assert route.call_count == 1


@pytest.mark.unit
@respx.mock
async def test_ensemble_config_none_when_judge_models_empty(
    client: GatewayClient,
) -> None:
    """An empty ``judge_models`` list disables Stage 4 entirely."""

    respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        return_value=httpx.Response(
            200,
            json={
                "judge_model": "fast",
                "ensemble_verification": {
                    "default_enabled": True,
                    "judge_models": [],
                    "aggregation_rule": "strict",
                    "max_cost_per_message_usd": 0.05,
                    "envelope_tier": None,
                },
            },
        )
    )

    cfg = await client.get_citation_engine_ensemble_config()

    assert cfg is None


@pytest.mark.unit
@respx.mock
async def test_ensemble_config_none_when_block_missing(client: GatewayClient) -> None:
    """Older gateway with no ``ensemble_verification`` block → None."""

    respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        return_value=httpx.Response(200, json={"judge_model": "fast"})
    )

    cfg = await client.get_citation_engine_ensemble_config()

    assert cfg is None


@pytest.mark.unit
@respx.mock
async def test_ensemble_config_none_on_network_error(client: GatewayClient) -> None:
    """Transport failure returns None (Stage 4 silently disabled)."""

    respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    cfg = await client.get_citation_engine_ensemble_config()

    assert cfg is None


@pytest.mark.unit
@respx.mock
async def test_ensemble_config_failed_fetch_is_cached(client: GatewayClient) -> None:
    """A failed fetch caches the None sentinel — no re-poll storm.

    Distinct from the judge_model behavior (which retries on failure)
    because the ensemble config is a stickier misconfiguration: a
    deployment without ensemble configured stays that way until
    operator-driven gateway restart, and we don't want every chat
    send to re-hit the endpoint just to confirm.
    """

    route = respx.get(f"{GATEWAY_BASE}/v1/citation-engine/config").mock(
        return_value=httpx.Response(500, text="oops")
    )

    cfg1 = await client.get_citation_engine_ensemble_config()
    cfg2 = await client.get_citation_engine_ensemble_config()

    assert cfg1 is None
    assert cfg2 is None
    assert route.call_count == 1


# Suppress the "task pending" warning that respx can emit on cancellation.
@pytest.fixture(autouse=True)
def _suppress_pending_task_warnings() -> None:
    asyncio.get_event_loop_policy()
