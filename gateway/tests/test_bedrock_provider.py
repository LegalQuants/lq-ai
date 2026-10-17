"""Opt-in, billable AWS gate: six cases, at most 18 inference requests.

Run only as documented in docs/bedrock-verification.md. A skip is not a pass.
The explicit opt-in fails (rather than skips) when credentials are absent.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from app.config import ProviderConfig
from app.providers.bedrock import BedrockAdapter
from app.providers.openai_schema import (
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
)

DEFAULTS = {
    "messages": ("runtime", "/anthropic", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    "chat_completions": ("runtime", "/openai/v1", "openai.gpt-oss-20b-1:0"),
    "responses": ("mantle", "/openai/v1", "google.gemma-4-31b"),
}
TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_test_value",
        "description": "Return the synthetic verification value.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


async def _call(
    adapter: BedrockAdapter,
    model: str,
    messages: list[ChatCompletionMessage],
    *,
    stream: bool,
    tools: bool = False,
    force_tool: bool = False,
) -> tuple[ChatCompletionMessage, int]:
    result = await adapter.chat_completion(
        ChatCompletionRequest(
            model=model,
            messages=messages,
            max_tokens=1024,
            tools=[TOOL] if tools else None,
            tool_choice={"type": "function", "function": {"name": "lookup_test_value"}}
            if force_tool
            else ("none" if tools else None),
        ),
        model=model,
        stream=stream,
    )
    if isinstance(result, ChatCompletionResponse):
        return result.choices[0].message, result.usage.total_tokens
    text = ""
    calls: dict[int, dict[str, Any]] = {}
    usage = 0
    finished = False
    async for chunk in result:
        if chunk.usage is not None:
            usage = chunk.usage.total_tokens
        for choice in chunk.choices:
            text += choice.delta.content or ""
            finished |= choice.finish_reason is not None
            for delta in choice.delta.tool_calls or []:
                call = calls.setdefault(
                    delta["index"],
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                call["id"] += delta.get("id", "")
                call["function"]["name"] += delta.get("function", {}).get("name", "")
                call["function"]["arguments"] += delta.get("function", {}).get("arguments", "")
    assert finished, "No terminal gateway chunk"
    return ChatCompletionMessage(
        role="assistant", content=text or None, tool_calls=list(calls.values()) or None
    ), usage


@pytest.mark.provider
@pytest.mark.parametrize("protocol", ["messages", "chat_completions", "responses"])
@pytest.mark.parametrize("stream", [False, True])
async def test_live_bedrock_protocol_and_tool_roundtrip(
    protocol: str, stream: bool, record_property: Any
) -> None:
    if os.environ.get("LQ_AI_BEDROCK_VERIFY") != "1":
        pytest.skip("AWS gate pending: set LQ_AI_BEDROCK_VERIFY=1 to authorize billable calls")
    if not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        pytest.fail("AWS verification blocked: AWS_BEARER_TOKEN_BEDROCK is not configured")
    region = os.environ.get("LQ_AI_BEDROCK_TEST_REGION", "us-east-1")
    endpoint, path, default_model = DEFAULTS[protocol]
    prefix = "LQ_AI_BEDROCK_" + protocol.upper()
    endpoint = os.environ.get(prefix + "_ENDPOINT", endpoint)
    host = (
        f"bedrock-runtime.{region}.amazonaws.com"
        if endpoint == "runtime"
        else f"bedrock-mantle.{region}.api.aws"
    )
    base_url = os.environ.get(prefix + "_BASE_URL", f"https://{host}{path}")
    model = os.environ.get(prefix + "_MODEL", default_model)
    cfg = ProviderConfig.model_validate(
        {
            "name": "bedrock-live-" + protocol,
            "type": "bedrock",
            "base_url": base_url,
            "bedrock_protocol": protocol,
            "bedrock_endpoint": endpoint,
            "tier": 3,
            "api_key_env": "AWS_BEARER_TOKEN_BEDROCK",
            "models": [model],
        }
    )
    adapter = BedrockAdapter.from_config(cfg)
    request_ids: list[str] = []

    async def record_aws_request(response: Any) -> None:
        value = response.headers.get("x-amzn-requestid") or response.headers.get("x-request-id")
        if value:
            request_ids.append(value)

    adapter._client.event_hooks["response"].append(record_aws_request)
    try:
        simple, tokens = await _call(
            adapter,
            model,
            [ChatCompletionMessage(role="user", content="Reply with the single word PONG.")],
            stream=stream,
        )
        assert simple.content and "PONG" in simple.content.upper()
        assert tokens > 0
        messages = [
            ChatCompletionMessage(
                role="user",
                content="Call lookup_test_value, then report its returned value exactly.",
            )
        ]
        proposal, tool_tokens = await _call(
            adapter, model, messages, stream=stream, tools=True, force_tool=True
        )
        assert proposal.tool_calls and len(proposal.tool_calls) == 1
        call = proposal.tool_calls[0]
        assert call["id"] and call["function"]["name"] == "lookup_test_value"
        assert isinstance(json.loads(call["function"]["arguments"]), dict)
        # This synthetic local tool stands in for the separately governed API
        # tool loop; the full application Gate C remains an independent gate.
        messages.extend(
            [
                proposal,
                ChatCompletionMessage(
                    role="tool", tool_call_id=call["id"], content='{"value":"LQ_TEST_VALUE"}'
                ),
            ]
        )
        continuation, final_tokens = await _call(
            adapter, model, messages, stream=stream, tools=True
        )
        assert continuation.content and "LQ_TEST_VALUE" in continuation.content
        assert tool_tokens > 0 and final_tokens > 0
        record_property("protocol", protocol)
        record_property("endpoint", endpoint)
        record_property("region", region)
        record_property("model", model)
        record_property("stream", str(stream))
        record_property("total_tokens", tokens + tool_tokens + final_tokens)
        record_property("aws_request_ids", ",".join(request_ids))
    finally:
        await adapter.aclose()
