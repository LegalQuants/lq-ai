"""Real gateway HTTP contract with synthetic AWS responses; no live AWS calls.

The tool result is supplied by the test caller, not executed by the gateway.
Backend tool governance is covered separately by the provider-independent API suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import yaml

from app.main import app

CALL_ID = "call-synthetic-1"
ARGUMENTS = '{"key":"synthetic"}'
TOOL = {
    "type": "function",
    "function": {
        "name": "lookup",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}},
    },
}
CALL = {
    "id": CALL_ID,
    "type": "function",
    "function": {"name": "lookup", "arguments": ARGUMENTS},
}


def _sse(events: list[dict[str, Any] | str]) -> httpx.Response:
    frames = []
    for event in events:
        if isinstance(event, str):
            frames.append(f"data: {event}\n\n")
        else:
            frames.append(f"data: {json.dumps(event)}\n\n")
    return httpx.Response(200, text="".join(frames), headers={"content-type": "text/event-stream"})


def _upstream(protocol: str, *, stream: bool, tool: bool) -> httpx.Response:
    text = "LQ_TEST_VALUE"
    if protocol == "messages":
        content = (
            {"type": "tool_use", "id": CALL_ID, "name": "lookup", "input": json.loads(ARGUMENTS)}
            if tool
            else {"type": "text", "text": text}
        )
        reason = "tool_use" if tool else "end_turn"
        if not stream:
            return httpx.Response(
                200,
                json={
                    "id": "msg-test",
                    "model": "native",
                    "content": [content],
                    "stop_reason": reason,
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                },
            )
        return _sse(
            [
                {
                    "type": "message_start",
                    "message": {"id": "msg-test", "model": "native", "usage": {"input_tokens": 3}},
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {**content, "input": {}}
                    if tool
                    else {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": ARGUMENTS}
                    if tool
                    else {"type": "text_delta", "text": text},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": reason},
                    "usage": {"output_tokens": 2},
                },
                {"type": "message_stop"},
            ]
        )
    if protocol == "chat_completions":
        message = (
            {"role": "assistant", "tool_calls": [CALL]}
            if tool
            else {"role": "assistant", "content": text}
        )
        usage = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
        common = {"id": "chat-test", "created": 1, "model": "native"}
        reason = "tool_calls" if tool else "stop"
        if not stream:
            return httpx.Response(
                200,
                json={
                    **common,
                    "choices": [{"message": message, "finish_reason": reason}],
                    "usage": usage,
                },
            )
        delta = {"role": "assistant", "tool_calls": [{"index": 0, **CALL}]} if tool else message
        return _sse(
            [
                {**common, "choices": [{"index": 0, "delta": delta}]},
                {**common, "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]},
                {**common, "choices": [], "usage": usage},
                "[DONE]",
            ]
        )
    item = (
        {"type": "function_call", "call_id": CALL_ID, "name": "lookup", "arguments": ARGUMENTS}
        if tool
        else {"type": "message", "content": [{"type": "output_text", "text": text}]}
    )
    payload = {
        "id": "resp-test",
        "created_at": 1,
        "model": "native",
        "status": "completed",
        "output": [item],
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }
    if not stream:
        return httpx.Response(200, json=payload)
    events = [{"type": "response.created", "response": {"id": "resp-test"}}]
    if tool:
        events.extend(
            [
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {**item, "arguments": ""},
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 0,
                    "delta": ARGUMENTS[:8],
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 0,
                    "delta": ARGUMENTS[8:],
                },
            ]
        )
    else:
        events.append({"type": "response.output_text.delta", "delta": text})
    events.append({"type": "response.completed", "response": payload})
    return _sse(events)


def _message(response: httpx.Response, *, stream: bool) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    if not stream:
        payload = response.json()
        assert payload["routed_provider"] == "aws-it"
        assert payload["routed_inference_tier"] == 3
        assert payload["usage"]["total_tokens"] == 5
        return dict(payload["choices"][0]["message"])
    assert response.text.rstrip().endswith("data: [DONE]")
    chunks = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert all("error" not in chunk for chunk in chunks), response.text
    assert any(chunk.get("routed_provider") == "aws-it" for chunk in chunks)
    assert any((chunk.get("usage") or {}).get("total_tokens") == 5 for chunk in chunks)
    assert any(
        choice.get("finish_reason") for chunk in chunks for choice in chunk.get("choices", [])
    )
    message: dict[str, Any] = {"role": "assistant", "content": ""}
    calls: dict[int, dict[str, Any]] = {}
    for chunk in chunks:
        for choice in chunk.get("choices", []):
            delta = choice["delta"]
            message["content"] += delta.get("content") or ""
            for call in delta.get("tool_calls") or []:
                value = calls.setdefault(
                    call["index"],
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                value["id"] += call.get("id", "")
                for field in ("name", "arguments"):
                    value["function"][field] += call.get("function", {}).get(field, "")
    if calls:
        message["tool_calls"] = list(calls.values())
    message["content"] = message["content"] or None
    return message


@pytest.mark.parametrize("protocol", ["messages", "chat_completions", "responses"])
@pytest.mark.parametrize("endpoint", ["runtime", "mantle"])
@pytest.mark.parametrize("stream", [False, True])
async def test_gateway_function_result_roundtrip(
    protocol: str, endpoint: str, stream: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = (
        "https://bedrock-runtime.us-east-1.amazonaws.com"
        if endpoint == "runtime"
        else "https://bedrock-mantle.us-east-1.api.aws"
    )
    prefix = (
        "/anthropic"
        if protocol == "messages"
        else ("/v1" if endpoint == "mantle" and protocol == "chat_completions" else "/openai/v1")
    )
    path = {
        "messages": "/v1/messages",
        "chat_completions": "/chat/completions",
        "responses": "/responses",
    }[protocol]
    file = tmp_path / "gateway.yaml"
    file.write_text(
        yaml.safe_dump(
            {
                "gateway_auth": {"enabled": False},
                "anonymization": {"enabled": False},
                "providers": [
                    {
                        "name": "aws-it",
                        "type": "bedrock",
                        "bedrock_protocol": protocol,
                        "bedrock_endpoint": endpoint,
                        "base_url": host + prefix,
                        "tier": 3,
                        "api_key_env": "BEDROCK_IT_KEY",
                        "models": ["native"],
                    }
                ],
            }
        )
    )
    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(file))
    monkeypatch.setenv("BEDROCK_IT_KEY", "synthetic-key")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LQ_AI_DATABASE_URL", raising=False)
    with respx.mock as router:
        route = router.post(host + prefix + path).mock(
            side_effect=[
                _upstream(protocol, stream=stream, tool=True),
                _upstream(protocol, stream=stream, tool=False),
            ]
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            messages: list[dict[str, Any]] = [{"role": "user", "content": "Look up synthetic."}]
            payload = {
                "model": "aws-it/native",
                "messages": messages,
                "stream": stream,
                "anonymize": False,
                "tools": [TOOL],
                "tool_choice": {"type": "function", "function": {"name": "lookup"}},
            }
            proposal = _message(
                await client.post("/v1/chat/completions", json=payload), stream=stream
            )
            call = proposal["tool_calls"][0]
            assert call["id"] == CALL_ID and call["function"]["name"] == "lookup"
            assert json.loads(call["function"]["arguments"]) == json.loads(ARGUMENTS)
            messages.extend(
                [proposal, {"role": "tool", "tool_call_id": CALL_ID, "content": "LQ_TEST_VALUE"}]
            )
            payload["tool_choice"] = "none"
            result = _message(
                await client.post("/v1/chat/completions", json=payload), stream=stream
            )
            assert result["content"] == "LQ_TEST_VALUE"
        assert route.call_count == 2
        sent = json.loads(route.calls.last.request.content)
        assert sent["model"] == "native"
        if protocol == "messages":
            history = sent["messages"]
            assert history[-2]["content"][0]["id"] == CALL_ID
            assert history[-2]["content"][0]["input"] == json.loads(ARGUMENTS)
            assert history[-1]["content"][0]["tool_use_id"] == CALL_ID
            assert history[-1]["content"][0]["content"] == "LQ_TEST_VALUE"
        elif protocol == "chat_completions":
            assert sent["messages"][-2]["tool_calls"][0]["id"] == CALL_ID
            assert sent["messages"][-1]["tool_call_id"] == CALL_ID
            assert sent["messages"][-1]["content"] == "LQ_TEST_VALUE"
        else:
            assert sent["store"] is False and sent["background"] is False
            assert sent["input"][-2]["call_id"] == CALL_ID
            assert json.loads(sent["input"][-2]["arguments"]) == json.loads(ARGUMENTS)
            assert sent["input"][-1] == {
                "type": "function_call_output",
                "call_id": CALL_ID,
                "output": "LQ_TEST_VALUE",
            }
