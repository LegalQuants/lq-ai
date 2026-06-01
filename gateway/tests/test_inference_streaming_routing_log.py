"""Regression: streamed chat completions must persist an inference_routing_log row.

The success path of :func:`_stream_openai_sse` used to write its routing-log
row *after* yielding ``data: [DONE]\\n\\n``. The api-side consumer
(``GatewayClient.chat_completion_stream`` -> ``_iter_sse_chunks``) stops
iterating the moment it sees ``[DONE]`` and closes the ``async with
client.stream(...)`` context. Closing that context cancels this async
generator — it throws ``GeneratorExit`` into the generator while it is
suspended at the ``yield b"data: [DONE]\\n\\n"`` — so any ``await`` placed
*after* that yield never runs. Result: every streamed turn (i.e. all real UI
traffic) persisted zero routing-log rows, blanking the M2 receipts /
anonymization transparency surfaces.

This test reproduces that early-close cancellation precisely: it consumes the
generator with ``async for`` and ``break``\\s the instant it sees the
``[DONE]`` frame, then calls ``gen.aclose()`` (which throws ``GeneratorExit``
exactly like the real consumer's stream-context exit). It then asserts exactly
one routing-log row was persisted with the expected token / tier / provider /
anonymization fields.

DO NOT "simplify" this into a full-drain test (e.g. ``[f async for f in gen]``
or reading ``response.text``). Draining the generator to completion runs the
post-``[DONE]`` code and hides the bug — that is exactly why the pre-existing
``test_chat_completions_streams_sse_frames`` did not catch it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.api.inference import _stream_openai_sse
from app.config import CostRateEntry, GatewayConfig, ProviderConfig
from app.providers.openai_schema import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatCompletionRequest,
    ChatCompletionUsage,
)
from app.router import ResolvedTarget
from app.routing_log import RecordingRoutingLogWriter


def _config() -> GatewayConfig:
    """Minimal config; ``_stream_openai_sse`` only reads ``cost_tracking.rates``."""

    provider = ProviderConfig(
        name="anthropic-prod",
        type="anthropic",
        base_url="https://anthropic-prod.example.com",
        api_key_env="ANTHROPIC_PROD_API_KEY",
        tier=4,
        models=["claude-opus-4-7"],
    )
    raw = {
        "providers": [provider.model_dump(exclude_none=True)],
        "model_aliases": {},
        "cost_tracking": {
            "rates": {
                "anthropic-prod/claude-opus-4-7": CostRateEntry(
                    input_per_mtok=10.0,
                    output_per_mtok=30.0,
                ).model_dump(exclude_none=True),
            },
        },
    }
    return GatewayConfig.model_validate(raw)


def _target(config: GatewayConfig) -> ResolvedTarget:
    return ResolvedTarget(
        provider=config.providers[0],
        native_model="claude-opus-4-7",
        routed_inference_tier=4,
        role="primary",
    )


def _chunks() -> AsyncIterator[ChatCompletionChunk]:
    """Two chunks; the final one carries the usage block (like OpenAI/Anthropic)."""

    async def gen() -> AsyncIterator[ChatCompletionChunk]:
        yield ChatCompletionChunk(
            id="chunk-1",
            created=1_700_000_000,
            model="claude-opus-4-7",
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionDelta(role="assistant", content="Hello"),
                )
            ],
        )
        yield ChatCompletionChunk(
            id="chunk-2",
            created=1_700_000_001,
            model="claude-opus-4-7",
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionDelta(content=" world"),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=11,
                completion_tokens=5,
                total_tokens=16,
            ),
        )

    return gen()


@pytest.mark.asyncio
async def test_stream_persists_routing_log_on_consumer_early_close() -> None:
    """A streamed success turn persists exactly one routing-log row.

    Reproduces the real consumer's early close: break on ``[DONE]`` then
    ``aclose()`` the generator. Before the fix this asserted ``rows == 0``
    (the write lived after ``[DONE]`` and never ran); after the fix the
    write precedes ``[DONE]`` so exactly one row persists.
    """

    config = _config()
    target = _target(config)
    recorder = RecordingRoutingLogWriter()
    chat_request = ChatCompletionRequest(
        model="smart",
        messages=[{"role": "user", "content": "hi"}],  # type: ignore[list-item]
        stream=True,
    )

    gen = _stream_openai_sse(
        _chunks(),
        target=target,
        config=config,
        chat_request=chat_request,
        log_writer=recorder,
        request_id="req-stream-test",
    )

    saw_done = False
    try:
        async for frame in gen:
            if frame == b"data: [DONE]\n\n":
                # Mirror the api-side consumer: stop the instant [DONE]
                # arrives, then close the stream context.
                saw_done = True
                break
    finally:
        # Closing the stream context throws GeneratorExit into the suspended
        # generator — exactly what the real network consumer does.
        await gen.aclose()

    assert saw_done, "stream never emitted a [DONE] frame"

    assert len(recorder.rows) == 1, (
        f"expected exactly one routing-log row, got {len(recorder.rows)} "
        "(the success-path write must precede the [DONE] yield)"
    )
    row = recorder.rows[0]
    assert row.tokens_in == 11
    assert row.tokens_out == 5
    assert row.routed_inference_tier == 4
    assert row.routed_provider == "anthropic-prod"
    assert row.routed_model == "claude-opus-4-7"
    assert row.anonymization_applied is False
    assert row.request_id == "req-stream-test"


@pytest.mark.asyncio
async def test_stream_persists_routing_log_with_anonymization_flag() -> None:
    """anonymization_applied is True when an anon_mapper is supplied.

    Note: passing ``anon_mapper`` without ``anonymizer`` skips the
    rehydrator (no tail flush) but still records ``anonymization_applied``
    from ``anon_mapper is not None`` — which is the field the receipts
    surface reads.
    """

    config = _config()
    target = _target(config)
    recorder = RecordingRoutingLogWriter()
    chat_request = ChatCompletionRequest(
        model="smart",
        messages=[{"role": "user", "content": "hi"}],  # type: ignore[list-item]
        stream=True,
    )

    class _Mapper:
        pass

    gen = _stream_openai_sse(
        _chunks(),
        target=target,
        config=config,
        chat_request=chat_request,
        log_writer=recorder,
        request_id="req-stream-anon",
        anon_mapper=_Mapper(),  # type: ignore[arg-type]
    )

    try:
        async for frame in gen:
            if frame == b"data: [DONE]\n\n":
                break
    finally:
        await gen.aclose()

    assert len(recorder.rows) == 1
    assert recorder.rows[0].anonymization_applied is True
