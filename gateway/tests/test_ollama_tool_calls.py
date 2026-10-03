"""Ollama tool calls round-trip through the adapter.

Responses: Ollama's ``message.tool_calls`` (``function.arguments`` as an
object, no id) becomes OpenAI-shaped ``tool_calls`` (synthesized id,
``type: "function"``, arguments as a JSON string) on the message (unary)
and delta (streaming), and the turn's ``finish_reason`` is ``tool_calls``.

Requests: assistant messages sent back carry their tool calls in Ollama's
shape (arguments as an object), and tool-result messages get ``tool_name``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.providers import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    OllamaAdapter,
)
from app.providers.ollama import _from_ollama_response, _to_ollama_request

OLLAMA_BASE = "http://ollama:11434"
MODEL = "qwen3.8:27b"

OLLAMA_CALL = {"function": {"name": "search", "arguments": {"q": "pdpa", "limit": 3}}}


# --- Responses: unary --------------------------------------------------------


@pytest.mark.unit
def test_unary_tool_calls_become_openai_shaped() -> None:
    payload = {
        "model": MODEL,
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [OLLAMA_CALL, {"function": {"name": "noop", "arguments": {}}}],
        },
        "done": True,
        "done_reason": "stop",
    }
    result = _from_ollama_response(payload, requested_model=MODEL)
    choice = result.choices[0]
    calls = choice.message.tool_calls
    assert calls is not None and len(calls) == 2
    first = calls[0]
    assert first["type"] == "function"
    assert first["id"].startswith("call_") and len(first["id"]) > len("call_")
    assert first["function"]["name"] == "search"
    # Arguments are a JSON string in the OpenAI shape.
    assert isinstance(first["function"]["arguments"], str)
    assert json.loads(first["function"]["arguments"]) == {"q": "pdpa", "limit": 3}
    assert json.loads(calls[1]["function"]["arguments"]) == {}
    assert calls[0]["id"] != calls[1]["id"]
    # Ollama says "stop" for a tool-call turn; OpenAI callers expect this.
    assert choice.finish_reason == "tool_calls"


@pytest.mark.unit
def test_unary_keeps_ollama_supplied_call_id() -> None:
    payload = {
        "model": MODEL,
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_abc", **OLLAMA_CALL}],
        },
        "done": True,
        "done_reason": "stop",
    }
    calls = _from_ollama_response(payload, requested_model=MODEL).choices[0].message.tool_calls
    assert calls is not None and calls[0]["id"] == "call_abc"


@pytest.mark.unit
def test_unary_without_tool_calls_is_unchanged() -> None:
    result = _from_ollama_response(
        {
            "model": MODEL,
            "message": {"role": "assistant", "content": "hi"},
            "done": True,
            "done_reason": "stop",
        },
        requested_model=MODEL,
    )
    assert result.choices[0].message.tool_calls is None
    assert result.choices[0].finish_reason == "stop"


@pytest.mark.unit
def test_unary_length_finish_is_not_overridden_by_tool_calls() -> None:
    result = _from_ollama_response(
        {
            "model": MODEL,
            "message": {"role": "assistant", "content": "", "tool_calls": [OLLAMA_CALL]},
            "done": True,
            "done_reason": "length",
        },
        requested_model=MODEL,
    )
    assert result.choices[0].finish_reason == "length"


# --- Responses: streaming ----------------------------------------------------

TOOL_CALL_NDJSON = (
    f'{{"model":"{MODEL}","message":{{"role":"assistant","content":"","tool_calls":['
    '{"function":{"name":"search","arguments":{"q":"pdpa"}}},'
    '{"function":{"name":"fetch","arguments":{"id":7}}}]},"done":false}\n'
    f'{{"model":"{MODEL}","message":{{"role":"assistant","content":""}},"done":true,'
    '"done_reason":"stop","prompt_eval_count":4,"eval_count":6}\n'
)


async def _stream(adapter: OllamaAdapter, req: ChatCompletionRequest) -> list[ChatCompletionChunk]:
    result = await adapter.chat_completion(req, model=MODEL, stream=True)
    assert not isinstance(result, ChatCompletionResponse)
    return [chunk async for chunk in result]


def _request(**overrides: Any) -> ChatCompletionRequest:
    payload: dict[str, Any] = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "find it"}],
    }
    payload.update(overrides)
    return ChatCompletionRequest.model_validate(payload)


@pytest.mark.unit
@respx.mock
async def test_streaming_tool_calls_emit_indexed_delta_and_tool_calls_finish() -> None:
    respx.post(f"{OLLAMA_BASE}/api/chat").mock(
        return_value=httpx.Response(
            200, text=TOOL_CALL_NDJSON, headers={"content-type": "application/x-ndjson"}
        )
    )
    adapter = OllamaAdapter(name="ollama-test", base_url=OLLAMA_BASE)
    try:
        chunks = await _stream(adapter, _request(stream=True))
    finally:
        await adapter.aclose()

    tool_chunks = [c for c in chunks if c.choices[0].delta.tool_calls]
    assert len(tool_chunks) == 1  # sent whole, in one chunk
    calls = tool_chunks[0].choices[0].delta.tool_calls
    assert calls is not None
    assert [c["index"] for c in calls] == [0, 1]
    assert all(c["type"] == "function" and c["id"].startswith("call_") for c in calls)
    assert calls[0]["id"] != calls[1]["id"]
    assert json.loads(calls[0]["function"]["arguments"]) == {"q": "pdpa"}
    assert calls[1]["function"]["name"] == "fetch"
    assert json.loads(calls[1]["function"]["arguments"]) == {"id": 7}
    # Terminal chunk reports tool_calls with usage.
    assert chunks[-1].choices[0].finish_reason == "tool_calls"
    assert chunks[-1].usage is not None and chunks[-1].usage.total_tokens == 10


@pytest.mark.unit
@respx.mock
async def test_streaming_without_tool_calls_still_finishes_stop() -> None:
    body = (
        f'{{"model":"{MODEL}","message":{{"role":"assistant","content":"Hi"}},"done":false}}\n'
        f'{{"model":"{MODEL}","message":{{"role":"assistant","content":""}},"done":true,'
        '"done_reason":"stop"}\n'
    )
    respx.post(f"{OLLAMA_BASE}/api/chat").mock(
        return_value=httpx.Response(200, text=body, headers={"content-type": "x-ndjson"})
    )
    adapter = OllamaAdapter(name="ollama-test", base_url=OLLAMA_BASE)
    try:
        chunks = await _stream(adapter, _request(stream=True))
    finally:
        await adapter.aclose()
    assert all(c.choices[0].delta.tool_calls is None for c in chunks)
    assert chunks[-1].choices[0].finish_reason == "stop"


# --- Requests: messages sent back to Ollama ----------------------------------


@pytest.mark.unit
def test_assistant_tool_calls_converted_to_ollama_shape() -> None:
    req = _request(
        messages=[
            {"role": "user", "content": "find it"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q": "pdpa", "n": 2}'},
                    }
                ],
            },
        ]
    )
    sent = _to_ollama_request(req, model=MODEL, stream=False)["messages"][1]
    call = sent["tool_calls"][0]
    assert call["function"]["name"] == "search"
    assert call["function"]["arguments"] == {"q": "pdpa", "n": 2}  # object, not string
    assert call["id"] == "call_1"
    assert "type" not in call


@pytest.mark.unit
@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ("{not json", "{not json"),  # unparsable: raw string passes through
        ("[1, 2]", "[1, 2]"),  # valid JSON but not an object: left as given
        ("", {}),
        ({"already": "dict"}, {"already": "dict"}),
    ],
)
def test_tool_call_arguments_edge_cases(arguments: Any, expected: Any) -> None:
    req = _request(
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "f", "arguments": arguments}}],
            },
        ]
    )
    sent = _to_ollama_request(req, model=MODEL, stream=False)["messages"][0]
    assert sent["tool_calls"][0]["function"]["arguments"] == expected


@pytest.mark.unit
def test_tool_result_message_gets_tool_name() -> None:
    req = _request(
        messages=[
            {"role": "tool", "content": "3 hits", "tool_call_id": "call_1", "name": "search"},
        ]
    )
    sent = _to_ollama_request(req, model=MODEL, stream=False)["messages"][0]
    assert sent["tool_name"] == "search"
    assert sent["name"] == "search"
    assert sent["tool_call_id"] == "call_1"


@pytest.mark.unit
def test_plain_messages_get_no_tool_keys() -> None:
    req = _request(
        messages=[
            {"role": "user", "content": "hi", "name": "alice"},
            {"role": "assistant", "content": "hello"},
        ]
    )
    user, assistant = _to_ollama_request(req, model=MODEL, stream=False)["messages"]
    assert "tool_name" not in user  # only tool-result messages
    assert set(assistant) == {"role", "content"}


@pytest.mark.unit
@respx.mock
async def test_tool_round_trip_over_http() -> None:
    """Request carries converted history; response is OpenAI-shaped."""

    route = respx.post(f"{OLLAMA_BASE}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": MODEL,
                "message": {"role": "assistant", "content": "", "tool_calls": [OLLAMA_CALL]},
                "done": True,
                "done_reason": "stop",
            },
        )
    )
    adapter = OllamaAdapter(name="ollama-test", base_url=OLLAMA_BASE)
    try:
        result = await adapter.chat_completion(
            _request(
                messages=[
                    {"role": "user", "content": "x"},
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "c",
                                "type": "function",
                                "function": {"name": "a", "arguments": "{}"},
                            }
                        ],
                    },
                    {"role": "tool", "content": "r", "name": "a", "tool_call_id": "c"},
                ]
            ),
            model=MODEL,
            stream=False,
        )
    finally:
        await adapter.aclose()
    sent = json.loads(route.calls.last.request.content)["messages"]
    assert sent[1]["tool_calls"][0]["function"]["arguments"] == {}
    assert sent[2]["tool_name"] == "a"
    assert isinstance(result, ChatCompletionResponse)
    assert result.choices[0].finish_reason == "tool_calls"
