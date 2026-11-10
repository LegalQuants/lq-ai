"""Stateless Responses translation for Bedrock's compatible API.

Origin: @dropthejase's PR #265. Reimplemented with explicit retention,
complete tool history, terminal-state checks and streaming tool arguments.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from app.providers.anthropic import _iter_sse_events
from app.providers.base import (
    ProviderEmptyResponseError,
    ProviderHTTPError,
    ProviderUnsupportedError,
)
from app.providers.openai_schema import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    FinishReason,
)


def _invalid_response() -> ProviderHTTPError:
    return ProviderHTTPError("Bedrock returned an invalid Responses payload", upstream_status=502)


def _function(call: dict[str, Any]) -> dict[str, Any]:
    if call.get("type") != "function" or not isinstance(call.get("function"), dict):
        raise ProviderUnsupportedError("Bedrock accepts only governed function tools")
    fn: dict[str, Any] = call["function"]
    if not isinstance(fn.get("name"), str) or not fn["name"]:
        raise ProviderUnsupportedError("A governed function requires a name")
    return fn


def to_responses_request(
    request: ChatCompletionRequest, *, model: str, stream: bool
) -> dict[str, Any]:
    """Allowlist fields and reconstruct tool history without remote sessions."""
    extra = request.model_extra or {}
    if (
        extra.get("store") not in (None, False)
        or extra.get("background") not in (None, False)
        or extra.get("previous_response_id") is not None
        or extra.get("conversation") is not None
    ):
        raise ProviderUnsupportedError("Bedrock Responses supports only stateless requests")
    if request.stop is not None:
        raise ProviderUnsupportedError("Bedrock Responses does not support stop sequences")
    items: list[dict[str, Any]] = []
    for msg in request.messages:
        if msg.role == "tool":
            if not msg.tool_call_id:
                raise ProviderUnsupportedError("A tool result requires its original call ID")
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.tool_call_id,
                    "output": msg.content or "",
                }
            )
            continue
        if msg.content or not msg.tool_calls:
            items.append({"role": msg.role, "content": msg.content or ""})
        if msg.tool_calls:
            if msg.role != "assistant":
                raise ProviderUnsupportedError("Only assistant messages may contain tool calls")
            for call in msg.tool_calls:
                fn = _function(call)
                if not isinstance(call.get("id"), str) or not call["id"]:
                    raise ProviderUnsupportedError("A tool call requires its original call ID")
                if not isinstance(fn.get("arguments"), str):
                    raise ProviderUnsupportedError("Function arguments must be a JSON string")
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call["id"],
                        "name": fn["name"],
                        "arguments": fn["arguments"],
                    }
                )
    body: dict[str, Any] = {
        "model": model,
        "input": items,
        "stream": stream,
        "store": False,
        "background": False,
    }
    for field, target in (
        ("max_tokens", "max_output_tokens"),
        ("temperature", "temperature"),
        ("top_p", "top_p"),
    ):
        value = getattr(request, field)
        if value is not None:
            body[target] = value
    if request.reasoning_effort is not None:
        body["reasoning"] = {"effort": request.reasoning_effort}
    names: set[str] = set()
    if request.tools:
        tools = []
        for tool in request.tools:
            fn = _function(tool)
            names.add(fn["name"])
            spec = {
                "type": "function",
                "name": fn["name"],
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            }
            if "description" in fn:
                spec["description"] = fn["description"]
            if "strict" in fn:
                spec["strict"] = fn["strict"]
            tools.append(spec)
        body["tools"] = tools
    if request.tool_choice is not None:
        choice = request.tool_choice
        if isinstance(choice, str):
            if choice not in {"auto", "none", "required"} or (choice == "required" and not names):
                raise ProviderUnsupportedError("Unsupported Bedrock function choice")
            body["tool_choice"] = choice
        else:
            fn = _function(choice)
            if fn["name"] not in names:
                raise ProviderUnsupportedError(
                    "The forced function must be in the governed tool list"
                )
            body["tool_choice"] = {"type": "function", "name": fn["name"]}
    return body


def from_responses_response(payload: dict[str, Any], *, model: str) -> ChatCompletionResponse:
    """Refuse malformed/failed output rather than reporting a clean stop."""
    if not isinstance(payload, dict):
        raise _invalid_response()
    status = payload.get("status")
    if status not in {"completed", "incomplete"}:
        raise _invalid_response()
    finish: FinishReason = "stop"
    if status == "incomplete":
        incomplete = payload.get("incomplete_details")
        if not isinstance(incomplete, dict):
            raise _invalid_response()
        reason = incomplete.get("reason")
        if reason == "max_output_tokens":
            finish = "length"
        elif reason == "content_filter":
            finish = "content_filter"
        else:
            raise _invalid_response()
    output = payload.get("output")
    if not isinstance(output, list):
        raise _invalid_response()
    text: list[str] = []
    calls: list[dict[str, Any]] = []
    call_ids: set[str] = set()
    for item in output:
        if not isinstance(item, dict):
            raise _invalid_response()
        kind = item.get("type")
        if kind == "reasoning":
            continue
        if kind == "message":
            blocks = item.get("content")
            if not isinstance(blocks, list):
                raise _invalid_response()
            for block in blocks:
                if not isinstance(block, dict):
                    raise _invalid_response()
                if block.get("type") == "output_text" and isinstance(block.get("text"), str):
                    text.append(block["text"])
                elif block.get("type") == "refusal" and isinstance(block.get("refusal"), str):
                    text.append(block["refusal"])
                    finish = "content_filter"
                else:
                    raise _invalid_response()
        elif kind == "function_call":
            if not all(isinstance(item.get(k), str) and item[k] for k in ("call_id", "name")):
                raise _invalid_response()
            if not isinstance(item.get("arguments"), str):
                raise _invalid_response()
            if item["call_id"] in call_ids or not isinstance(json.loads(item["arguments"]), dict):
                raise _invalid_response()
            call_ids.add(item["call_id"])
            calls.append(
                {
                    "id": item["call_id"],
                    "type": "function",
                    "function": {"name": item["name"], "arguments": item["arguments"]},
                }
            )
        else:
            raise ProviderUnsupportedError("Bedrock returned an unsupported Responses output type")
    if not "".join(text) and not calls:
        raise ProviderEmptyResponseError("Bedrock returned no visible content or function calls")
    raw_usage = payload.get("usage")
    if not isinstance(raw_usage, dict) or not all(
        type(raw_usage.get(k)) is int and raw_usage[k] >= 0
        for k in ("input_tokens", "output_tokens")
    ):
        raise _invalid_response()
    if calls and finish == "stop":
        finish = "tool_calls"
    created = payload.get("created_at", time.time())
    if (
        type(created) not in (int, float)
        or not 0 <= created <= 2**63 - 1
        or (isinstance(created, float) and not math.isfinite(created))
    ):
        raise _invalid_response()
    response_id = payload.get("id")
    if not isinstance(response_id, str) or not response_id:
        raise _invalid_response()
    return ChatCompletionResponse(
        id=response_id,
        created=int(created),
        model=str(payload.get("model") or model),
        choices=[
            ChatCompletionChoice(
                message=ChatCompletionMessage(
                    role="assistant", content="".join(text) or None, tool_calls=calls or None
                ),
                finish_reason=finish,
            )
        ],
        usage=ChatCompletionUsage(
            prompt_tokens=raw_usage["input_tokens"],
            completion_tokens=raw_usage["output_tokens"],
            total_tokens=raw_usage["input_tokens"] + raw_usage["output_tokens"],
        ),
    )


@dataclass
class _StreamedTool:
    index: int
    call_id: str
    name: str
    arguments: str = ""


async def stream_responses(
    response: httpx.Response, *, model: str
) -> AsyncIterator[ChatCompletionChunk]:
    """Translate deltas, then reconcile every tool argument with the terminal output."""
    tools: dict[int, _StreamedTool] = {}
    text = ""
    response_id = ""
    created = int(time.time())

    def chunk(delta: ChatCompletionDelta) -> ChatCompletionChunk:
        if not response_id:
            raise _invalid_response()
        return ChatCompletionChunk(
            id=response_id,
            created=created,
            model=model,
            choices=[ChatCompletionChunkChoice(delta=delta)],
        )

    async for event, data in _iter_sse_events(response):
        if not data or data == "[DONE]":
            continue
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise _invalid_response()
        kind = parsed.get("type") or event
        if kind == "response.created":
            initial = parsed.get("response")
            if not isinstance(initial, dict) or response_id:
                raise _invalid_response()
            identifier = initial.get("id")
            if not isinstance(identifier, str) or not identifier:
                raise _invalid_response()
            response_id = identifier
            yield chunk(ChatCompletionDelta(role="assistant"))
        elif kind == "response.output_text.delta":
            delta = parsed.get("delta")
            if not isinstance(delta, str):
                raise _invalid_response()
            text += delta
            yield chunk(ChatCompletionDelta(content=delta))
        elif kind == "response.output_item.added":
            item = parsed.get("item") or {}
            if not isinstance(item, dict):
                raise _invalid_response()
            if item.get("type") == "function_call":
                output_index = parsed.get("output_index")
                if type(output_index) is not int or output_index in tools:
                    raise _invalid_response()
                if not all(isinstance(item.get(k), str) and item[k] for k in ("call_id", "name")):
                    raise _invalid_response()
                tool = _StreamedTool(index=len(tools), call_id=item["call_id"], name=item["name"])
                tools[output_index] = tool
                initial = item.get("arguments", "")
                if not isinstance(initial, str):
                    raise _invalid_response()
                tool.arguments = initial
                yield chunk(
                    ChatCompletionDelta(
                        tool_calls=[
                            {
                                "index": tool.index,
                                "id": tool.call_id,
                                "type": "function",
                                "function": {"name": tool.name, "arguments": initial},
                            }
                        ]
                    )
                )
            elif item.get("type") not in {"message", "reasoning"}:
                raise ProviderUnsupportedError(
                    "Bedrock returned an unsupported Responses output type"
                )
        elif kind == "response.function_call_arguments.delta":
            output_index = parsed.get("output_index")
            if type(output_index) is not int or output_index not in tools:
                raise _invalid_response()
            delta = parsed.get("delta")
            if not isinstance(delta, str):
                raise _invalid_response()
            tool = tools[output_index]
            tool.arguments += delta
            yield chunk(
                ChatCompletionDelta(
                    tool_calls=[{"index": tool.index, "function": {"arguments": delta}}]
                )
            )
        elif kind in {"response.completed", "response.incomplete"}:
            final = from_responses_response(parsed.get("response") or {}, model=model)
            if final.id != response_id:
                raise _invalid_response()
            message = final.choices[0].message
            final_text = message.content or ""
            if not final_text.startswith(text):
                raise _invalid_response()
            if final_text[len(text) :]:
                yield chunk(ChatCompletionDelta(content=final_text[len(text) :]))
            by_id = {tool.call_id: tool for tool in tools.values()}
            final_calls = message.tool_calls or []
            if len(by_id) != len(tools) or not set(by_id).issubset({x["id"] for x in final_calls}):
                raise _invalid_response()
            for call in final_calls:
                fn = call["function"]
                prior = by_id.get(call["id"])
                if prior is None:
                    yield chunk(ChatCompletionDelta(tool_calls=[{"index": len(by_id), **call}]))
                    by_id[call["id"]] = _StreamedTool(len(by_id), call["id"], fn["name"])
                else:
                    if fn["name"] != prior.name or not fn["arguments"].startswith(prior.arguments):
                        raise _invalid_response()
                    tail = fn["arguments"][len(prior.arguments) :]
                    if tail:
                        yield chunk(
                            ChatCompletionDelta(
                                tool_calls=[{"index": prior.index, "function": {"arguments": tail}}]
                            )
                        )
            terminal = chunk(ChatCompletionDelta())
            terminal.id = final.id
            terminal.model = final.model
            terminal.usage = final.usage
            terminal.choices[0].finish_reason = final.choices[0].finish_reason
            yield terminal
            return
        elif kind in {"error", "response.failed", "response.cancelled"}:
            raise ProviderHTTPError(
                "Bedrock Responses failed during streaming", upstream_status=502
            )
    raise ProviderHTTPError(
        "Bedrock Responses stream ended before its terminal event", upstream_status=502
    )
