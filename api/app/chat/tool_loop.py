"""Governed chat tool-loop (PR5b-ii / WS4).

Turns PR5b-i's gateway tool-passthrough into a usable chat capability: assemble
an operator-enabled tool allowlist, hand it to the model, and when the model
asks to call a tool, run it under the PR5a governance substrate
(:func:`app.tools.governance.governed_tool_invocation`) and feed the result
back — looping until the model produces a final answer or the per-turn cap is
hit.

Scope of this module
--------------------

* **Allowlist assembly** — :func:`assemble_mcp_tools` reads the operator's
  enabled MCP tools (``mcp_tools`` cache) and renders OpenAI function schemas,
  alongside a registry that carries each tool's ``read_only`` /
  ``destructive`` / ``requires_confirmation`` flags for the loop's gating.
* **The loop** — :func:`run_tool_loop` drives the conversation with
  non-streaming gateway calls: read-only tools execute inline and feed back;
  a tool flagged ``destructive`` / ``requires_confirmation`` raises
  :class:`ToolConfirmationRequired` so the caller can run the persist-and-resume
  confirmation gate (built in the chat endpoint, not here). The streaming chat
  path streams only the final answer turn.

Research (CourtListener) tools are assembled by a sibling helper when that
provider is configured; this module focuses on the MCP path that the
DeepWiki demo source exercises. Both share the same governance substrate.

Security invariants
-------------------

* Tool arguments are digested (types + key names only) for the audit row — the
  raw payload is fed into the conversation but never written to ``tool_call_log``
  (mirrors ``app.autonomous.guard._args_digest``; invariant spec §112).
* Every call passes through ``governed_tool_invocation`` (tier → cost → audit),
  so the gateway still tier-checks and SSRF/allowlist-guards each egress.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.guard import ToolResult
from app.clients.gateway import GatewayClient
from app.mcp import service as mcp_service
from app.schemas.gateway import (
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    FunctionDefinition,
    ToolDefinition,
)
from app.tools.governance import governed_tool_invocation, resolve_provider_tier

log = logging.getLogger(__name__)

DEFAULT_MAX_TOOL_CALLS = 8
"""Per-turn tool-call cap (spec L4). Operator-overridable via settings; the
loop stops engaging tools at the cap and lets the model finalize with what it
has, so a model that loops forever cannot run unbounded egress."""


@dataclass(frozen=True)
class ToolMeta:
    """Dispatch + governance metadata for one allowlisted tool."""

    provider: str
    tool: str
    read_only: bool
    destructive: bool
    requires_confirmation: bool


@dataclass
class AssembledTools:
    """The per-turn tool surface: OpenAI schemas + a name→metadata registry."""

    schemas: list[ToolDefinition] = field(default_factory=list)
    registry: dict[str, ToolMeta] = field(default_factory=dict)

    def __bool__(self) -> bool:  # truthy iff at least one tool is offered
        return bool(self.schemas)


class ToolConfirmationRequired(Exception):
    """Raised mid-loop when the model proposes a human-gated tool.

    Carries everything the confirmation gate needs to persist the pending call
    and the conversation-so-far resume state. The chat endpoint catches this,
    persists a ``pending_tool_call`` row, emits the ``tool_confirmation_required``
    SSE event, and ends the turn (spec L3 persist-and-resume).
    """

    def __init__(
        self,
        *,
        provider: str,
        tool: str,
        args: dict[str, Any],
        tool_call_id: str,
        destructive: bool,
        messages_so_far: list[ChatCompletionMessage],
    ) -> None:
        self.provider = provider
        self.tool = tool
        self.tool_args = args  # NOT ``self.args`` — that shadows BaseException.args (a tuple)
        self.tool_call_id = tool_call_id
        self.destructive = destructive
        self.messages_so_far = messages_so_far
        super().__init__(f"tool {provider}/{tool} requires confirmation")


def args_digest(args: dict[str, Any]) -> str:
    """Stable 16-hex digest of arg TYPES + KEY NAMES only (never values).

    Mirrors ``app.autonomous.guard._args_digest`` so chat-origin audit rows
    carry the same payload-free correlation handle as autonomous ones.
    """

    shape = {k: type(v).__name__ for k, v in sorted(args.items())}
    canonical = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


async def assemble_mcp_tools(
    db: AsyncSession,
    *,
    request_id: str | None = None,
) -> AssembledTools:
    """Build the per-turn MCP tool allowlist from operator-enabled tools.

    Walks the configured MCP servers (gateway config) and, for each, the cached
    tools that are ``enabled``. Renders an OpenAI function schema per tool and a
    registry entry carrying the provider + governance flags. Tools whose name
    collides across providers keep the first seen (logged) — OpenAI tool names
    must be unique within a request.
    """

    assembled = AssembledTools()
    try:
        servers = await mcp_service.list_servers(request_id=request_id)
    except Exception:  # pragma: no cover - config/gateway unavailable
        log.warning("mcp_tool_assembly: list_servers failed", exc_info=True)
        return assembled

    for server in servers:
        provider = server["name"]
        try:
            tools = await mcp_service.list_cached_tools(db, provider=provider)
        except Exception:  # pragma: no cover - defensive per-provider guard
            log.warning("mcp_tool_assembly: list_cached_tools failed", extra={"provider": provider})
            continue
        for tool in tools:
            if not tool.get("enabled"):
                continue
            name = tool["name"]
            if name in assembled.registry:
                log.warning(
                    "mcp_tool_assembly: duplicate tool name across providers; keeping first",
                    extra={"tool": name, "provider": provider},
                )
                continue
            params = tool.get("parameters") or {"type": "object", "properties": {}}
            assembled.schemas.append(
                ToolDefinition(
                    function=FunctionDefinition(
                        name=name,
                        description=tool.get("description"),
                        parameters=params,
                    )
                )
            )
            assembled.registry[name] = ToolMeta(
                provider=provider,
                tool=name,
                read_only=bool(tool.get("read_only")),
                destructive=bool(tool.get("destructive")),
                requires_confirmation=bool(tool.get("requires_confirmation", True)),
            )
    return assembled


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    """OpenAI carries tool-call arguments as a JSON string; degrade to {}."""

    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def execute_mcp_tool(
    db: AsyncSession,
    *,
    gateway: GatewayClient,
    meta: ToolMeta,
    args: dict[str, Any],
    user_id: UUID,
    chat_id: UUID,
    message_id: UUID,
    request_id: str | None,
    max_allowed_tier: int | None,
    confirmation_state: str = "not_required",
) -> ToolResult:
    """Run one MCP tool through the governance substrate + gateway egress.

    Shared by the inline read-only path and the confirmation-gate resume path
    (which passes ``confirmation_state="approved"``).
    """

    provider_tier = await resolve_provider_tier(meta.provider, request_id=request_id)

    async def _dispatch() -> ToolResult:
        payload = await gateway.call_tool(
            meta.provider,
            meta.tool,
            args,
            max_allowed_tier=max_allowed_tier,
            request_id=request_id,
        )
        return ToolResult(cost_usd=Decimal("0"), data=payload)

    return await governed_tool_invocation(
        db,
        origin="chat",
        provider=meta.provider,
        tool=meta.tool,
        intent=None,
        provider_tier=provider_tier,
        max_allowed_tier=max_allowed_tier,
        estimated_cost=Decimal("0"),
        dispatch=_dispatch,
        confirmation_state=confirmation_state,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        request_id=request_id,
        args_digest=args_digest(args),
    )


def _tool_result_content(result: ToolResult) -> str:
    """Render a tool result for the ``role="tool"`` reply message."""

    data = result.data
    if isinstance(data, dict) and "payload" in data:
        data = data["payload"]
    try:
        return json.dumps(data)
    except (TypeError, ValueError):
        return str(data)


async def run_tool_loop(
    db: AsyncSession,
    *,
    gateway: GatewayClient,
    base_request: ChatCompletionRequest,
    tools: AssembledTools,
    user_id: UUID,
    chat_id: UUID,
    message_id: UUID,
    request_id: str | None = None,
    max_allowed_tier: int | None = None,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> ChatCompletionResponse:
    """Drive the read-only execute-and-loop and return the final response.

    Non-streaming gateway calls decide tool use; read-only tools execute inline
    and feed back. A ``destructive`` / ``requires_confirmation`` tool raises
    :class:`ToolConfirmationRequired` (the caller runs the gate). At the
    per-turn cap, one final call is made WITHOUT tools so the model finalizes.

    Assumes ``tools`` is non-empty — callers skip the loop entirely (single-shot)
    when the allowlist is empty, preserving the pre-PR5b path.
    """

    messages: list[ChatCompletionMessage] = list(base_request.messages)
    calls_used = 0

    while True:
        offer_tools = calls_used < max_tool_calls
        req = base_request.model_copy(
            update={
                "messages": messages,
                "stream": False,
                "tools": [t.model_dump(mode="json") for t in tools.schemas]
                if offer_tools
                else None,
                "tool_choice": "auto" if offer_tools else None,
            }
        )
        resp = await gateway.chat_completion(req, request_id=request_id)
        if not resp.choices:
            return resp
        choice = resp.choices[0]
        tool_calls = choice.message.tool_calls or []
        if choice.finish_reason != "tool_calls" or not tool_calls or not offer_tools:
            return resp  # final answer

        # Replay the assistant's tool-call turn into the conversation.
        messages.append(
            ChatCompletionMessage(
                role="assistant",
                content=choice.message.content,
                tool_calls=tool_calls,
            )
        )

        for call in tool_calls:
            calls_used += 1
            fn = call.get("function") or {}
            name = str(fn.get("name") or "")
            call_id = str(call.get("id") or "")
            args = _parse_tool_args(fn.get("arguments"))
            meta = tools.registry.get(name)
            if meta is None:
                # Model hallucinated a tool not in the allowlist — tell it so.
                messages.append(
                    ChatCompletionMessage(
                        role="tool",
                        tool_call_id=call_id,
                        content=json.dumps({"error": f"unknown tool {name!r}"}),
                    )
                )
                continue
            if meta.destructive or meta.requires_confirmation:
                raise ToolConfirmationRequired(
                    provider=meta.provider,
                    tool=meta.tool,
                    args=args,
                    tool_call_id=call_id,
                    destructive=meta.destructive,
                    messages_so_far=messages,
                )
            result = await execute_mcp_tool(
                db,
                gateway=gateway,
                meta=meta,
                args=args,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                request_id=request_id,
                max_allowed_tier=max_allowed_tier,
            )
            messages.append(
                ChatCompletionMessage(
                    role="tool",
                    tool_call_id=call_id,
                    content=_tool_result_content(result),
                )
            )
