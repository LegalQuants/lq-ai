"""Integration tests for the B4 router on the chat-completions surface.

These tests run through the real FastAPI app (lifespan + router +
adapter) but mock the upstream Anthropic HTTP layer with ``respx`` and
inject a :class:`RecordingRoutingLogWriter` so we can assert the row
the router constructed without spinning up Postgres.

What's covered here, in addition to the B3 coverage in
``test_inference_anthropic.py``:

* Tier annotation appears in BOTH the response header
  (``X-LQ-AI-Routed-Inference-Tier``) and the body's
  ``routed_inference_tier`` field.
* The cost estimate is populated when ``cost_tracking.rates`` has a
  matching entry.
* The ``inference_routing_log`` row carries the correct fields on
  success, failure, and unresolved-model paths.
* Streaming responses also carry the tier (header + chunk body).
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

from app.config_revision import REVISION_HEADER, configuration_revision
from app.routing_log import RecordingRoutingLogWriter

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def app_with_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[FastAPI, RecordingRoutingLogWriter]]:
    """Gateway ``app`` with the routing-log writer swapped for a recorder.

    The lifespan runs as normal so the Anthropic adapter is instantiated;
    we then replace ``app.state.routing_log`` with a
    :class:`RecordingRoutingLogWriter` for the duration of the test.
    """

    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(EXAMPLE_CONFIG))
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", "test-openai")
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake")
    # Force NullRoutingLogWriter at startup; we override below.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from app.main import app

    async with _run_lifespan(app):
        recorder = RecordingRoutingLogWriter()
        app.state.routing_log = recorder
        try:
            yield app, recorder
        finally:
            pass


@pytest_asyncio.fixture
async def client_with_recorder(
    app_with_recorder: tuple[FastAPI, RecordingRoutingLogWriter],
) -> AsyncIterator[tuple[AsyncClient, RecordingRoutingLogWriter]]:
    app, recorder = app_with_recorder
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client, recorder


# --- Tier annotation: header + body ----------------------------------------


@pytest.mark.integration
@respx.mock
@pytest.mark.parametrize("requested_model", ["smart", "anthropic-prod/claude-opus-4-7"])
async def test_response_carries_tier_in_header_and_body(
    client_with_recorder: tuple[AsyncClient, RecordingRoutingLogWriter],
    requested_model: str,
) -> None:
    """Both surfaces (header + body field) carry ``routed_inference_tier``."""

    client, _recorder = client_with_recorder
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_b4_001",
                "model": "provider-version-label",
                "content": [{"type": "text", "text": "hi"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )
    )

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": requested_model,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    # Header surface.
    assert response.headers["X-LQ-AI-Routed-Inference-Tier"] == "4"
    assert response.headers["X-LQ-AI-Routed-Provider"] == "anthropic-prod"
    # Body surface.
    body = response.json()
    assert body["routed_inference_tier"] == 4
    assert body["routed_provider"] == "anthropic-prod"
    assert body["routed_model"] == "claude-opus-4-7"
    assert body["model"] == "provider-version-label"


# --- inference_routing_log writes ------------------------------------------


@pytest.mark.parametrize("revision", ["current", "0" * 64, "bad"])
@respx.mock
async def test_checked_inference_revision_and_header_isolation(client_with_recorder, revision):
    client, _ = client_with_recorder
    config = (await client.get("/admin/v1/config")).json()
    expected = config["configuration_revision"]
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "checked",
                "model": "provider-version",
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )
    )
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "anthropic-prod/claude-opus-4-7",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={REVISION_HEADER: expected if revision == "current" else revision},
    )
    if revision == "current":
        assert response.status_code == 200
        assert response.headers[REVISION_HEADER] == expected
        assert REVISION_HEADER not in route.calls[0].request.headers
        assert expected not in route.calls[0].request.content.decode()
    else:
        assert response.status_code == 412 and not route.called


@respx.mock
@pytest.mark.parametrize("setting", ["base_url", "api_key_env"])
async def test_checked_inference_refuses_fresh_config_with_obsolete_adapter(
    app_with_recorder, setting
):
    app, _ = app_with_recorder
    holder = app.state.config_holder
    old_revision = configuration_revision(holder.current())
    updated = holder.current().model_copy(deep=True)
    provider = updated.provider_by_name("anthropic-prod")
    assert provider is not None
    if setting == "base_url":
        provider.base_url = "https://replacement.example"
    else:
        provider.api_key_env = "REPLACEMENT_ANTHROPIC_KEY"
    holder.replace(updated)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        revision = (await client.get("/admin/v1/config")).json()["configuration_revision"]
        assert revision != old_revision
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "anthropic-prod/claude-opus-4-7",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={REVISION_HEADER: revision},
        )
    assert response.status_code == 412
    assert not respx.calls


@pytest.mark.parametrize("mode", ["alias", "shadowing_alias", "stream"])
@respx.mock
async def test_checked_inference_requires_unambiguous_nonstreaming_route(app_with_recorder, mode):
    app, _ = app_with_recorder
    holder = app.state.config_holder
    config = holder.current().model_copy(deep=True)
    direct = "anthropic-prod/claude-opus-4-7"
    if mode == "shadowing_alias":
        config.model_aliases[direct] = config.model_aliases["fast"]
        holder.replace(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "smart" if mode == "alias" else direct,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": mode == "stream",
            },
            headers={REVISION_HEADER: configuration_revision(config)},
        )
    assert response.status_code == 412
    assert not respx.calls


@respx.mock
async def test_checked_inference_keeps_snapshot_during_hot_swap(app_with_recorder, monkeypatch):
    app, _recorder = app_with_recorder
    holder = app.state.config_holder
    expected = configuration_revision(holder.current())
    live_router = app.state.router
    original = dict(live_router.adapters)

    async def swap_during_assembly(*args, **kwargs):
        new = holder.current().model_copy(deep=True)
        new.cost_tracking.rates.clear()
        new.model_aliases["anthropic-prod/claude-opus-4-7"] = new.model_aliases["fast"]
        holder.replace(new)
        live_router.adapters.clear()
        return []

    monkeypatch.setattr("app.api.inference._apply_skill_prompt_assembly", swap_during_assembly)
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "pinned",
                "model": "provider-version",
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        )
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic-prod/claude-opus-4-7",
                    "messages": [{"role": "user", "content": "hi"}],
                    "lq_ai_skills": ["fixture"],
                },
                headers={REVISION_HEADER: expected},
            )
            assert response.status_code == 200, response.text
            assert response.headers[REVISION_HEADER] == expected
            assert response.json()["routed_model"] == "claude-opus-4-7"
            assert response.json()["cost_estimate"] > 0
            assert json.loads(route.calls[0].request.content)["model"] == "claude-opus-4-7"
            assert len(route.calls) == 1
            rejected = await client.post(
                "/v1/chat/completions",
                json={"model": "anthropic-prod/claude-opus-4-7", "messages": []},
                headers={REVISION_HEADER: expected},
            )
            assert rejected.status_code == 412 and len(route.calls) == 1
    finally:
        live_router.adapters.update(original)


@pytest.mark.integration
@respx.mock
async def test_routing_log_row_written_on_success(
    client_with_recorder: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """Successful request writes one row with tier + provider + tokens + cost."""

    client, recorder = client_with_recorder
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_b4_002",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1000, "output_tokens": 500},
            },
        )
    )

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200

    assert len(recorder.rows) == 1
    row = recorder.rows[0]
    assert row.requested_model == "smart"
    assert row.routed_provider == "anthropic-prod"
    assert row.routed_model == "claude-opus-4-7"
    assert row.routed_inference_tier == 4
    assert row.tokens_in == 1000
    assert row.tokens_out == 500
    # gateway.yaml.example defines a cost rate for this pair, so the row
    # carries a non-NULL cost_estimate.
    assert row.cost_estimate is not None
    # 15.00 * 1k/1M + 75.00 * 500/1M = 0.015 + 0.0375 = 0.0525
    assert float(row.cost_estimate) == pytest.approx(0.0525)
    assert row.refused is False
    assert row.refusal_reason is None
    assert row.request_id is not None  # synthesized when caller didn't supply
    assert row.latency_ms is not None and row.latency_ms >= 0


@pytest.mark.integration
@respx.mock
async def test_routing_log_row_written_on_provider_failure(
    client_with_recorder: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """A 5xx upstream still produces a routing-log row with the tier."""

    client, recorder = client_with_recorder
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            503,
            json={
                "type": "error",
                "error": {"type": "service_unavailable", "message": "down"},
            },
        )
    )

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    # 5xx is fallback-eligible, but smart's fallback in gateway.yaml.example
    # is vertex-anthropic which has no instantiated adapter (no key), so the
    # router exhausts candidates and re-raises the last ProviderHTTPError.
    assert response.status_code == 502  # gateway maps non-429 5xx to 502

    assert len(recorder.rows) == 1
    row = recorder.rows[0]
    assert row.routed_provider == "anthropic-prod"
    assert row.routed_inference_tier == 4
    assert row.refusal_reason is not None
    assert "upstream_error" in row.refusal_reason


@pytest.mark.integration
async def test_routing_log_row_written_for_unresolved_model(
    client_with_recorder: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """A model that doesn't resolve still gets a row (with sentinels + reason)."""

    client, recorder = client_with_recorder
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "no-such-model",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_model"

    assert len(recorder.rows) == 1
    row = recorder.rows[0]
    assert row.requested_model == "no-such-model"
    assert row.routed_provider == "<unresolved>"
    assert row.routed_model == "<unresolved>"
    assert row.routed_inference_tier == 1
    assert row.refused is True
    assert "invalid_model" in (row.refusal_reason or "")


@pytest.mark.integration
@respx.mock
async def test_routing_log_carries_caller_supplied_request_id(
    client_with_recorder: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """``X-Request-Id`` from the caller is preserved into the audit row."""

    client, recorder = client_with_recorder
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_b4_003",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )
    )

    await client.post(
        "/v1/chat/completions",
        headers={"X-Request-Id": "req_caller_supplied"},
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert recorder.rows[0].request_id == "req_caller_supplied"


# --- Streaming carries the tier --------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_streaming_response_carries_tier(
    client_with_recorder: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """Streaming surfaces the tier in BOTH the header and every chunk."""

    client, recorder = client_with_recorder
    sse_body = (
        "event: message_start\n"
        'data: {"type":"message_start","message":{"id":"msg_strm","model":"claude-opus-4-7","usage":{"input_tokens":3,"output_tokens":0}}}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}\n\n'
        "event: message_delta\n"
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}\n\n'
        "event: message_stop\n"
        'data: {"type":"message_stop"}\n\n'
    )
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200, text=sse_body, headers={"content-type": "text/event-stream"}
        )
    )

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["X-LQ-AI-Routed-Inference-Tier"] == "4"

    # Parse the SSE body.
    text = response.text
    frames = [line for line in text.split("\n\n") if line.strip()]
    data_frames = [f.removeprefix("data: ") for f in frames if f.startswith("data: ")]
    parsed_chunks = [json.loads(f) for f in data_frames if f.strip() != "[DONE]"]
    # Every chunk carries the tier.
    for chunk in parsed_chunks:
        assert chunk["routed_inference_tier"] == 4
        assert chunk["routed_provider"] == "anthropic-prod"

    # Routing-log row written at end of stream.
    assert len(recorder.rows) == 1
    row = recorder.rows[0]
    assert row.routed_inference_tier == 4
    assert row.routed_provider == "anthropic-prod"
    assert row.tokens_in == 3
    assert row.tokens_out == 1


# --- M2-E2: purpose column ---------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_routing_log_purpose_defaults_to_chat(
    client_with_recorder: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """M2-E2: a regular chat-send writes ``purpose='chat'`` on the routing log."""

    client, recorder = client_with_recorder
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_purpose_chat",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )
    )

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200
    assert len(recorder.rows) == 1
    assert recorder.rows[0].purpose == "chat"


@pytest.mark.integration
@respx.mock
async def test_routing_log_purpose_judge_paraphrase_propagates(
    client_with_recorder: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """M2-E2: ``lq_ai_purpose='judge_paraphrase'`` on the request lands on the row.

    Citation Engine Stage 3/4 sets this so api/-side cost calibration
    can filter routing-log rows down to judge traffic only.
    """

    client, recorder = client_with_recorder
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_purpose_judge",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": '{"verdict":"yes"}'}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 800, "output_tokens": 50},
            },
        )
    )

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "judge this"}],
            "lq_ai_purpose": "judge_paraphrase",
        },
    )
    assert response.status_code == 200
    assert len(recorder.rows) == 1
    assert recorder.rows[0].purpose == "judge_paraphrase"


@pytest.mark.integration
@respx.mock
async def test_routing_log_purpose_unknown_value_sanitizes_to_chat(
    client_with_recorder: tuple[AsyncClient, RecordingRoutingLogWriter],
) -> None:
    """M2-E2: an unknown ``lq_ai_purpose`` value falls back to ``'chat'``.

    Defensive: the column is ``varchar(32)`` and downstream code expects
    one of the known values. An arbitrary caller can't pollute the
    column with free-form strings.
    """

    client, recorder = client_with_recorder
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_purpose_unknown",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 3, "output_tokens": 1},
            },
        )
    )

    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "smart",
            "messages": [{"role": "user", "content": "hi"}],
            "lq_ai_purpose": "evil_attacker_string",
        },
    )
    assert response.status_code == 200
    assert len(recorder.rows) == 1
    assert recorder.rows[0].purpose == "chat"
