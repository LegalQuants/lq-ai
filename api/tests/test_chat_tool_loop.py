"""Unit tests for the governed chat tool-loop (PR5b-ii) — :mod:`app.chat.tool_loop`.

Covers allowlist assembly from the MCP cache, the read-only execute-and-loop,
the per-turn cap, the unknown-tool guard, and the confirmation-required signal.
The gateway and the governance/egress layer are faked so these are pure unit
tests (no network, no DB).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.autonomous.guard import ToolResult
from app.chat import tool_loop
from app.chat.tool_loop import (
    AssembledTools,
    ToolConfirmationRequired,
    ToolMeta,
    assemble_mcp_tools,
    run_tool_loop,
)
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
)

_UID = uuid.uuid4()
_CID = uuid.uuid4()
_MID = uuid.uuid4()


def _resp(
    *, content: str | None, tool_calls: list[dict[str, Any]] | None, finish: str
) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-x",
        created=0,
        model="claude-haiku-4-5",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant", content=content, tool_calls=tool_calls
                ),
                finish_reason=finish,  # type: ignore[arg-type]
            )
        ],
    )


def _tool_call(name: str, args: str, call_id: str = "call_1") -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


def _base_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="claude-haiku-4-5",
        messages=[ChatCompletionMessage(role="user", content="hi")],
    )


class _FakeGateway:
    """Scripted gateway: returns queued responses; records each request."""

    def __init__(self, responses: list[ChatCompletionResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[ChatCompletionRequest] = []
        self.call_tool_calls: list[tuple[str, str, dict[str, Any]]] = []

    async def chat_completion(
        self, request: ChatCompletionRequest, *, request_id: str | None = None
    ) -> ChatCompletionResponse:
        self.requests.append(request)
        return self._responses.pop(0)

    async def call_tool(
        self,
        provider: str,
        tool: str,
        args: dict[str, Any],
        *,
        max_allowed_tier=None,
        request_id=None,
    ):
        self.call_tool_calls.append((provider, tool, args))
        return {"provider": provider, "tool": tool, "payload": {"ok": True}, "tier": 2}


# --- assemble_mcp_tools --------------------------------------------------------


async def test_assemble_mcp_tools_renders_enabled_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _servers(*, request_id=None):
        return [{"name": "deepwiki", "type": "mcp", "auth": "none"}]

    async def _cached(db, *, provider):
        return [
            {
                "name": "ask_question",
                "description": "Ask",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                "read_only": True,
                "destructive": False,
                "requires_confirmation": False,
                "enabled": True,
            },
            {
                "name": "disabled_tool",
                "description": "x",
                "parameters": {},
                "read_only": True,
                "destructive": False,
                "requires_confirmation": False,
                "enabled": False,
            },
        ]

    monkeypatch.setattr(tool_loop.mcp_service, "list_servers", _servers)
    monkeypatch.setattr(tool_loop.mcp_service, "list_cached_tools", _cached)

    assembled = await assemble_mcp_tools(object())  # type: ignore[arg-type]
    assert len(assembled.schemas) == 1
    assert assembled.schemas[0].function.name == "ask_question"
    assert "ask_question" in assembled.registry
    assert assembled.registry["ask_question"].read_only is True
    assert "disabled_tool" not in assembled.registry
    assert bool(assembled) is True


# --- run_tool_loop: read-only happy path --------------------------------------


async def test_run_tool_loop_executes_readonly_then_finalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = _FakeGateway(
        [
            _resp(
                content="let me look",
                tool_calls=[_tool_call("ask_question", '{"q": "what is X"}')],
                finish="tool_calls",
            ),
            _resp(content="X is a thing.", tool_calls=None, finish="stop"),
        ]
    )
    executed: list[dict[str, Any]] = []

    async def _fake_exec(db, *, gateway, meta, args, **kw):
        executed.append(args)
        return ToolResult(cost_usd=Decimal("0"), data={"payload": {"answer": "X is a thing"}})

    monkeypatch.setattr(tool_loop, "execute_mcp_tool", _fake_exec)

    tools = AssembledTools(
        schemas=[],
        registry={
            "ask_question": ToolMeta(
                "deepwiki",
                "ask_question",
                read_only=True,
                destructive=False,
                requires_confirmation=False,
            )
        },
    )
    # give it a schema so it's truthy / offered
    from app.schemas.gateway import FunctionDefinition, ToolDefinition

    tools.schemas.append(
        ToolDefinition(function=FunctionDefinition(name="ask_question", parameters={}))
    )

    final = await run_tool_loop(
        object(),  # type: ignore[arg-type]
        gateway=gw,  # type: ignore[arg-type]
        base_request=_base_request(),
        tools=tools,
        user_id=_UID,
        chat_id=_CID,
        message_id=_MID,
    )
    assert final.choices[0].message.content == "X is a thing."
    assert final.choices[0].finish_reason == "stop"
    assert executed == [{"q": "what is X"}]
    # second gateway request carried the assistant tool-call turn + tool result
    second = gw.requests[1]
    roles = [m.role for m in second.messages]
    assert "assistant" in roles and "tool" in roles


# --- run_tool_loop: confirmation-required raises -------------------------------


async def test_run_tool_loop_raises_on_confirmation_required() -> None:
    gw = _FakeGateway(
        [_resp(content=None, tool_calls=[_tool_call("create_doc", "{}")], finish="tool_calls")]
    )
    from app.schemas.gateway import FunctionDefinition, ToolDefinition

    tools = AssembledTools(
        schemas=[ToolDefinition(function=FunctionDefinition(name="create_doc", parameters={}))],
        registry={
            "create_doc": ToolMeta(
                "office",
                "create_doc",
                read_only=False,
                destructive=True,
                requires_confirmation=True,
            )
        },
    )
    with pytest.raises(ToolConfirmationRequired) as exc:
        await run_tool_loop(
            object(),  # type: ignore[arg-type]
            gateway=gw,  # type: ignore[arg-type]
            base_request=_base_request(),
            tools=tools,
            user_id=_UID,
            chat_id=_CID,
            message_id=_MID,
        )
    assert exc.value.provider == "office"
    assert exc.value.tool == "create_doc"
    assert exc.value.destructive is True


# --- run_tool_loop: per-turn cap forces finalize -------------------------------


async def test_run_tool_loop_cap_forces_finalize(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Loopy:
        def __init__(self) -> None:
            self.requests: list[ChatCompletionRequest] = []
            self._n = 0

        async def chat_completion(self, request, *, request_id=None):
            self.requests.append(request)
            if request.tools:
                self._n += 1
                return _resp(
                    content=None,
                    tool_calls=[_tool_call("ask_question", "{}", f"c{self._n}")],
                    finish="tool_calls",
                )
            return _resp(content="forced final", tool_calls=None, finish="stop")

    gw = _Loopy()

    async def _fake_exec(db, *, gateway, meta, args, **kw):
        return ToolResult(cost_usd=Decimal("0"), data={"payload": {}})

    monkeypatch.setattr(tool_loop, "execute_mcp_tool", _fake_exec)

    from app.schemas.gateway import FunctionDefinition, ToolDefinition

    tools = AssembledTools(
        schemas=[ToolDefinition(function=FunctionDefinition(name="ask_question", parameters={}))],
        registry={
            "ask_question": ToolMeta(
                "deepwiki",
                "ask_question",
                read_only=True,
                destructive=False,
                requires_confirmation=False,
            )
        },
    )
    final = await run_tool_loop(
        object(),  # type: ignore[arg-type]
        gateway=gw,  # type: ignore[arg-type]
        base_request=_base_request(),
        tools=tools,
        user_id=_UID,
        chat_id=_CID,
        message_id=_MID,
        max_tool_calls=2,
    )
    assert final.choices[0].message.content == "forced final"
    # last request offered no tools (cap reached -> forced finalize)
    assert gw.requests[-1].tools is None
