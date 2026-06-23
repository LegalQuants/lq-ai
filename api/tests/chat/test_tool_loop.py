"""Tests for api/app/chat/tool_loop.py — PR5b Task 5.

Eight scenarios per the task brief (TDD: written RED first, then GREEN).

(a) Immediate final answer (no tools) -> LoopFinal
(b) One read_only research call -> execute -> LoopFinal; tool_call_log row written
(c) MCP read_only with token threaded (assert call_tool got user_token)
(d) Cap reached after settings.chat_tool_call_cap -> final-without-tools -> LoopFinal
(e) Cluster cache hit (second get_cluster does NOT re-call the service)
(f) ToolTierRefused -> error tool message appended, loop continues to LoopFinal
(g) Destructive tool -> LoopConfirmation (first call triggers; siblings abandoned)
(h) MCP oauth no token -> LoopMcpAuth
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_schemas import ChatToolAllowlist, ToolSpec
from app.errors import ToolTierRefused
from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)
from app.security import hash_password

# ---------------------------------------------------------------------------
# Test builder helpers
# ---------------------------------------------------------------------------


def _user_msg(content: str) -> ChatCompletionMessage:
    return ChatCompletionMessage(role="user", content=content)


def _req(messages: list[ChatCompletionMessage]) -> ChatCompletionRequest:
    return ChatCompletionRequest(model="smart", messages=messages)


def _resp_final(text: str) -> ChatCompletionResponse:
    """Build a response that terminates the loop (no tool_calls)."""
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=1_700_000_000,
        model="claude-opus-4",
        choices=[
            ChatCompletionChoice(
                index=0,
                finish_reason="stop",
                message=ChatCompletionMessage(role="assistant", content=text),
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        routed_inference_tier=2,
        routed_provider="anthropic",
    )


def _resp_tool_call(
    fn_name: str,
    args: dict,
    call_id: str = "c1",
) -> ChatCompletionResponse:
    """Build a response that requests a single tool call."""
    tool_calls = [
        {
            "id": call_id,
            "type": "function",
            "function": {
                "name": fn_name,
                "arguments": json.dumps(args),
            },
        }
    ]
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=1_700_000_000,
        model="claude-opus-4",
        choices=[
            ChatCompletionChoice(
                index=0,
                finish_reason="tool_calls",
                message=ChatCompletionMessage(
                    role="assistant",
                    content=None,
                    tool_calls=tool_calls,
                ),
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        routed_inference_tier=2,
        routed_provider="anthropic",
    )


def _resp_two_tool_calls(
    fn1: str,
    args1: dict,
    fn2: str,
    args2: dict,
) -> ChatCompletionResponse:
    """Build a response that requests two tool calls in one round."""
    tool_calls = [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": fn1, "arguments": json.dumps(args1)},
        },
        {
            "id": "c2",
            "type": "function",
            "function": {"name": fn2, "arguments": json.dumps(args2)},
        },
    ]
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=1_700_000_000,
        model="claude-opus-4",
        choices=[
            ChatCompletionChoice(
                index=0,
                finish_reason="tool_calls",
                message=ChatCompletionMessage(
                    role="assistant",
                    content=None,
                    tool_calls=tool_calls,
                ),
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        routed_inference_tier=2,
        routed_provider="anthropic",
    )


def _research_allowlist(provider: str = "cl-prod") -> ChatToolAllowlist:
    """Allowlist with one read_only research tool (search_case_law)."""
    spec = ToolSpec(
        function_name="search_case_law",
        kind="research",
        provider=provider,
        tool="search_case_law",
        read_only=True,
        destructive=False,
        requires_confirmation=False,
        parameters={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
        description="Search case law.",
    )
    return ChatToolAllowlist(specs={"search_case_law": spec})


def _get_cluster_allowlist(provider: str = "cl-prod") -> ChatToolAllowlist:
    """Allowlist with research tools: search_case_law + get_cluster."""
    specs = {}
    for op in ("search_case_law", "get_cluster"):
        specs[op] = ToolSpec(
            function_name=op,
            kind="research",
            provider=provider,
            tool=op,
            read_only=True,
            destructive=False,
            requires_confirmation=False,
            parameters={"type": "object", "properties": {}, "required": []},
            description=op,
        )
    return ChatToolAllowlist(specs=specs)


def _mcp_allowlist(
    server: str = "my-server",
    tool: str = "get_doc",
    destructive: bool = False,
    requires_confirmation: bool = False,
) -> ChatToolAllowlist:
    fn = f"mcp__{server}__{tool}"
    spec = ToolSpec(
        function_name=fn,
        kind="mcp",
        provider=server,
        tool=tool,
        read_only=True,
        destructive=destructive,
        requires_confirmation=requires_confirmation,
        parameters={"type": "object", "properties": {}},
        description="MCP tool.",
    )
    return ChatToolAllowlist(specs={fn: spec})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def user(db: AsyncSession) -> User:
    u = User(
        email=f"toolloop-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Tool Loop Tester",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(u)
    await db.flush()
    return u


# ---------------------------------------------------------------------------
# Scenario (a): immediate final answer — no tool calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_immediate_final(db: AsyncSession, user: User) -> None:
    """When the model answers without calling any tool, LoopFinal is returned immediately."""
    from app.chat.tool_loop import LoopFinal, run_chat_tool_loop

    gateway = AsyncMock()
    gateway.chat_completion.return_value = _resp_final("Here is your answer.")

    al = _research_allowlist()
    with patch("app.chat.tool_loop.list_servers", new=AsyncMock(return_value=[])):
        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("What is the law?")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
        )

    assert isinstance(outcome, LoopFinal)
    assert outcome.text == "Here is your answer."
    assert outcome.calls_used == 0
    # The gateway was called exactly once (no round-trip from tool execution)
    gateway.chat_completion.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario (b): one read_only research call -> execute -> LoopFinal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_executes_readonly_research_then_finalizes(db: AsyncSession, user: User) -> None:
    """A single research tool call executes, writes an audit row, then the model finalizes."""
    from app.chat.tool_loop import LoopFinal, run_chat_tool_loop

    gateway = AsyncMock()
    gateway.chat_completion.side_effect = [
        _resp_tool_call("search_case_law", {"q": "Brown"}, call_id="c1"),
        _resp_final("Found Brown v. Board."),
    ]
    al = _research_allowlist(provider="cl-prod")

    with (
        patch(
            "app.chat.tool_loop.research_service.search_case_law",
            new=AsyncMock(return_value={"results": [{"cluster_id": 1}]}),
        ),
        patch(
            "app.chat.tool_loop.resolve_provider_tier",
            new=AsyncMock(return_value=1),
        ),
        patch("app.chat.tool_loop.list_servers", new=AsyncMock(return_value=[])),
    ):
        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("find Brown")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
        )

    assert isinstance(outcome, LoopFinal)
    assert "Brown" in outcome.text
    assert outcome.calls_used == 1

    # A tool_call_log row was written by governed_tool_invocation
    rows = (
        (await db.execute(select(ToolCallLog).where(ToolCallLog.origin == "chat"))).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].outcome == "executed"


# ---------------------------------------------------------------------------
# Scenario (c): MCP read_only with token threaded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_mcp_threads_user_token(db: AsyncSession, user: User) -> None:
    """For an oauth MCP server with a valid token, call_tool receives user_token."""
    from app.chat.tool_loop import LoopFinal, run_chat_tool_loop

    fn = "mcp__my-server__get_doc"
    gateway = AsyncMock()
    gateway.chat_completion.side_effect = [
        _resp_tool_call(fn, {"id": "123"}, call_id="c1"),
        _resp_final("Document retrieved."),
    ]
    gateway.call_tool.return_value = {"payload": {"content": "doc body"}}

    al = _mcp_allowlist(server="my-server", tool="get_doc")

    # Server has auth=oauth; get_valid_token returns a token
    server_list = [{"name": "my-server", "type": "mcp", "auth": "oauth"}]

    with (
        patch(
            "app.chat.tool_loop.list_servers",
            new=AsyncMock(return_value=server_list),
        ),
        patch(
            "app.chat.tool_loop.get_valid_token",
            new=AsyncMock(return_value="tok-abc"),
        ),
        patch(
            "app.chat.tool_loop.resolve_provider_tier",
            new=AsyncMock(return_value=1),
        ),
    ):
        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("get document 123")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
        )

    assert isinstance(outcome, LoopFinal)
    # Verify call_tool was called with the user token
    gateway.call_tool.assert_called_once()
    call_kwargs = gateway.call_tool.call_args
    assert call_kwargs.kwargs.get("user_token") == "tok-abc"


# ---------------------------------------------------------------------------
# Scenario (d): cap reached -> final-without-tools -> LoopFinal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_cap_triggers_final_round(db: AsyncSession, user: User) -> None:
    """After chat_tool_call_cap executions, one final round without tools is issued."""
    from app.chat.tool_loop import LoopFinal, run_chat_tool_loop

    # We'll use cap=2 to keep the test fast
    # Round 1: tool call (executed, calls_used -> 1)
    # Round 2: tool call (executed, calls_used -> 2 == cap)
    # Final round: no tools -> LoopFinal
    gateway = AsyncMock()
    gateway.chat_completion.side_effect = [
        _resp_tool_call("search_case_law", {"q": "first"}, call_id="c1"),
        _resp_tool_call("search_case_law", {"q": "second"}, call_id="c2"),
        _resp_final("Summarized after cap."),
    ]
    al = _research_allowlist(provider="cl-prod")

    with (
        patch(
            "app.chat.tool_loop.research_service.search_case_law",
            new=AsyncMock(return_value={"results": []}),
        ),
        patch(
            "app.chat.tool_loop.resolve_provider_tier",
            new=AsyncMock(return_value=1),
        ),
        patch("app.chat.tool_loop.list_servers", new=AsyncMock(return_value=[])),
        patch("app.chat.tool_loop.get_settings") as mock_settings,
    ):
        settings_obj = MagicMock()
        settings_obj.chat_tool_call_cap = 2
        mock_settings.return_value = settings_obj

        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("research two things")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
        )

    assert isinstance(outcome, LoopFinal)
    assert outcome.text == "Summarized after cap."
    assert outcome.calls_used == 2

    # Verify the final round was called without tools (third call)
    assert gateway.chat_completion.call_count == 3
    final_call_request: ChatCompletionRequest = gateway.chat_completion.call_args_list[2].args[0]
    # Final round must have tool_choice="none" or no tools
    assert final_call_request.tools is None or final_call_request.tool_choice == "none"


# ---------------------------------------------------------------------------
# Scenario (e): cluster cache hit — second get_cluster does NOT re-call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_cluster_cache_prevents_double_fetch(db: AsyncSession, user: User) -> None:
    """The cluster cache prevents duplicate get_cluster calls within one turn."""
    from app.chat.tool_loop import LoopFinal, run_chat_tool_loop

    fn = "get_cluster"
    gateway = AsyncMock()
    gateway.chat_completion.side_effect = [
        # Round 1: call get_cluster for cluster_id 42
        _resp_tool_call(fn, {"cluster_id": 42}, call_id="c1"),
        # Round 2: call get_cluster again for same cluster_id
        _resp_tool_call(fn, {"cluster_id": 42}, call_id="c2"),
        _resp_final("Cluster data used twice."),
    ]
    al = _get_cluster_allowlist(provider="cl-prod")

    mock_get_cluster = AsyncMock(return_value={"id": 42, "case_name": "Test v. Case"})

    with (
        patch(
            "app.chat.tool_loop.research_service.get_cluster",
            new=mock_get_cluster,
        ),
        patch(
            "app.chat.tool_loop.resolve_provider_tier",
            new=AsyncMock(return_value=1),
        ),
        patch("app.chat.tool_loop.list_servers", new=AsyncMock(return_value=[])),
    ):
        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("get cluster 42 twice")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
        )

    assert isinstance(outcome, LoopFinal)
    # The underlying service should only have been called ONCE (cache hit on 2nd)
    mock_get_cluster.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario (f): ToolTierRefused -> error tool message, loop continues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_tier_refused_continues(db: AsyncSession, user: User) -> None:
    """ToolTierRefused appends an error tool message and the loop continues to LoopFinal."""
    from app.chat.tool_loop import LoopFinal, run_chat_tool_loop

    gateway = AsyncMock()
    gateway.chat_completion.side_effect = [
        _resp_tool_call("search_case_law", {"q": "risky"}, call_id="c1"),
        _resp_final("Could not retrieve, here is what I know."),
    ]
    al = _research_allowlist(provider="cl-prod")

    # governed_tool_invocation raises ToolTierRefused (written by governance before raise)
    tier_refused = ToolTierRefused(provider="cl-prod", tool="search_case_law", tier=5, ceiling=2)

    with (
        patch(
            "app.chat.tool_loop.governed_tool_invocation",
            new=AsyncMock(side_effect=tier_refused),
        ),
        patch(
            "app.chat.tool_loop.resolve_provider_tier",
            new=AsyncMock(return_value=5),
        ),
        patch("app.chat.tool_loop.list_servers", new=AsyncMock(return_value=[])),
    ):
        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("search risky")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
        )

    assert isinstance(outcome, LoopFinal)
    # Two gateway rounds: first with tools, second after tier-refused error message appended
    assert gateway.chat_completion.call_count == 2

    # The second round's messages should contain a tool error message
    second_call_req: ChatCompletionRequest = gateway.chat_completion.call_args_list[1].args[0]
    tool_messages = [m for m in second_call_req.messages if m.role == "tool"]
    assert len(tool_messages) == 1


# ---------------------------------------------------------------------------
# Scenario (g): destructive tool -> LoopConfirmation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_destructive_tool_returns_confirmation(db: AsyncSession, user: User) -> None:
    """A destructive tool call returns LoopConfirmation without executing anything."""
    from app.chat.tool_loop import LoopConfirmation, run_chat_tool_loop

    fn = "mcp__my-server__delete_doc"
    gateway = AsyncMock()
    gateway.chat_completion.return_value = _resp_tool_call(fn, {"id": "123"}, call_id="c1")

    al = ChatToolAllowlist(
        specs={
            fn: ToolSpec(
                function_name=fn,
                kind="mcp",
                provider="my-server",
                tool="delete_doc",
                read_only=False,
                destructive=True,
                requires_confirmation=False,
                parameters={"type": "object", "properties": {"id": {"type": "string"}}},
                description="Delete a document (destructive).",
            )
        }
    )

    server_list = [{"name": "my-server", "type": "mcp", "auth": "none"}]

    with patch("app.chat.tool_loop.list_servers", new=AsyncMock(return_value=server_list)):
        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("delete document 123")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
        )

    assert isinstance(outcome, LoopConfirmation)
    assert outcome.spec.tool == "delete_doc"
    assert outcome.args == {"id": "123"}
    # No execution — call_tool never called
    gateway.call_tool.assert_not_called()
    # messages and calls_used present for Task 6/7 resume
    assert outcome.messages is not None
    assert outcome.calls_used == 0


# ---------------------------------------------------------------------------
# Scenario (h): MCP oauth no token -> LoopMcpAuth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_mcp_oauth_no_token_returns_auth(db: AsyncSession, user: User) -> None:
    """When get_valid_token returns None for an oauth server, LoopMcpAuth is returned."""
    from app.chat.tool_loop import LoopMcpAuth, run_chat_tool_loop

    fn = "mcp__oauth-server__read_file"
    gateway = AsyncMock()
    gateway.chat_completion.return_value = _resp_tool_call(
        fn, {"path": "/docs/a.txt"}, call_id="c1"
    )

    al = ChatToolAllowlist(
        specs={
            fn: ToolSpec(
                function_name=fn,
                kind="mcp",
                provider="oauth-server",
                tool="read_file",
                read_only=True,
                destructive=False,
                requires_confirmation=False,
                parameters={"type": "object", "properties": {}},
                description="Read a file.",
            )
        }
    )

    server_list = [{"name": "oauth-server", "type": "mcp", "auth": "oauth"}]

    with (
        patch(
            "app.chat.tool_loop.list_servers",
            new=AsyncMock(return_value=server_list),
        ),
        # get_valid_token returns None -> no token stored -> must authorize
        patch(
            "app.chat.tool_loop.get_valid_token",
            new=AsyncMock(return_value=None),
        ),
    ):
        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("read file")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
        )

    assert isinstance(outcome, LoopMcpAuth)
    assert outcome.server == "oauth-server"
    # messages and calls_used present for Task 6/7 resume
    assert outcome.messages is not None
    assert outcome.calls_used == 0


# ---------------------------------------------------------------------------
# Scenario (i): hallucination-only round — cap NOT consumed, terminates via guard
# ---------------------------------------------------------------------------


def _resp_tool_call_multi(calls: list[tuple[str, dict, str]]) -> ChatCompletionResponse:
    """Build a response that requests multiple tool calls (arbitrary count)."""
    tool_calls = [
        {
            "id": call_id,
            "type": "function",
            "function": {"name": fn, "arguments": json.dumps(args)},
        }
        for fn, args, call_id in calls
    ]
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        created=1_700_000_000,
        model="claude-opus-4",
        choices=[
            ChatCompletionChoice(
                index=0,
                finish_reason="tool_calls",
                message=ChatCompletionMessage(
                    role="assistant",
                    content=None,
                    tool_calls=tool_calls,
                ),
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        routed_inference_tier=2,
        routed_provider="anthropic",
    )


@pytest.mark.asyncio
async def test_loop_hallucinated_calls_do_not_increment_cap(db: AsyncSession, user: User) -> None:
    """Hallucinated tool names (spec is None) do not advance calls_used toward the cap.

    A round where the model proposes only unknown function names must:
    - NOT increment calls_used (no governed calls were made).
    - Trigger the zero-governed termination guard, yielding LoopFinal.
    - NOT write any tool_call_log rows (hallucinated calls never reach governance).
    """
    from app.chat.tool_loop import LoopFinal, run_chat_tool_loop

    gateway = AsyncMock()
    # Round 1: model proposes two hallucinated tool names not in the allowlist.
    # The zero-governed guard fires after this round and issues the final round.
    # Round 2 (final, no-tools): model returns a text answer.
    gateway.chat_completion.side_effect = [
        _resp_tool_call_multi(
            [
                ("nonexistent_tool_alpha", {"x": 1}, "h1"),
                ("nonexistent_tool_beta", {"y": 2}, "h2"),
            ]
        ),
        _resp_final("I could not find the right tools."),
    ]

    al = _research_allowlist(provider="cl-prod")  # only search_case_law is valid

    with patch("app.chat.tool_loop.list_servers", new=AsyncMock(return_value=[])):
        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("do something")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
        )

    assert isinstance(outcome, LoopFinal)
    # cap was NOT consumed by hallucinated calls
    assert outcome.calls_used == 0
    # Exactly two gateway calls: one tool round + one final no-tools round
    assert gateway.chat_completion.call_count == 2
    # Confirm the final call had no tools (zero-governed guard fired)
    final_call_req: ChatCompletionRequest = gateway.chat_completion.call_args_list[1].args[0]
    assert final_call_req.tools is None or final_call_req.tool_choice == "none"

    # No tool_call_log rows should exist — hallucinated calls never reached governance
    rows = (
        (await db.execute(select(ToolCallLog).where(ToolCallLog.origin == "chat"))).scalars().all()
    )
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_loop_hallucination_only_round_terminates_finitely(
    db: AsyncSession, user: User
) -> None:
    """A hallucination-only round must terminate via the zero-governed guard, not loop forever.

    The gateway side_effect list is finite.  If the loop were infinite, it would
    exhaust the list and raise StopIteration — the test passing proves termination.
    """
    from app.chat.tool_loop import LoopFinal, run_chat_tool_loop

    gateway = AsyncMock()
    # Only two responses: one hallucinated round + one final answer.
    # An infinite loop would consume more than two and raise StopIteration.
    gateway.chat_completion.side_effect = [
        _resp_tool_call("ghost_tool", {"arg": "val"}, call_id="hx1"),
        _resp_final("Terminating gracefully."),
    ]

    al = _research_allowlist(provider="cl-prod")  # ghost_tool not in allowlist

    with patch("app.chat.tool_loop.list_servers", new=AsyncMock(return_value=[])):
        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("try ghost tool")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
        )

    # Must terminate as LoopFinal (not raise StopIteration, not loop infinitely)
    assert isinstance(outcome, LoopFinal)
    assert outcome.calls_used == 0
    # Exactly two gateway calls consumed — no extras that would signal infinite loop
    assert gateway.chat_completion.call_count == 2


# ---------------------------------------------------------------------------
# Scenario (j): cap-triggered final round injects an explicit synthesis directive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_cap_final_round_injects_synthesis_directive(
    db: AsyncSession, user: User
) -> None:
    """Regression: the cap-triggered final no-tools round must carry an explicit
    synthesis directive so the model writes its answer instead of returning empty.

    Bug: a research turn that exhausts the tool-call cap mid-research issued a
    plain ``tool_choice="none"`` round (tools off, identical message list). With
    no instruction to stop researching and write, the model returned empty
    content and the turn persisted a zero-length assistant message. The final
    round must append a user directive instructing synthesis from what was
    already gathered — and that directive must NOT leak into the persisted turn.
    """
    from app.chat.tool_loop import LoopFinal, run_chat_tool_loop

    gateway = AsyncMock()
    gateway.chat_completion.side_effect = [
        _resp_tool_call("search_case_law", {"q": "x"}, call_id="c1"),
        _resp_final("Here is the synthesized answer."),
    ]
    al = _research_allowlist(provider="cl-prod")

    with (
        patch(
            "app.chat.tool_loop.research_service.search_case_law",
            new=AsyncMock(return_value={"results": []}),
        ),
        patch("app.chat.tool_loop.resolve_provider_tier", new=AsyncMock(return_value=1)),
        patch("app.chat.tool_loop.list_servers", new=AsyncMock(return_value=[])),
        patch("app.chat.tool_loop.get_settings") as mock_settings,
    ):
        settings_obj = MagicMock()
        settings_obj.chat_tool_call_cap = 1  # trip the cap after one executed call
        mock_settings.return_value = settings_obj

        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("research it")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
        )

    assert isinstance(outcome, LoopFinal)
    assert outcome.text == "Here is the synthesized answer."

    # Final (2nd) round: tools disabled AND a synthesis directive appended last.
    assert gateway.chat_completion.call_count == 2
    final_req: ChatCompletionRequest = gateway.chat_completion.call_args_list[1].args[0]
    assert final_req.tools is None
    last_msg = final_req.messages[-1]
    assert last_msg.role == "user"
    assert "final answer" in (last_msg.content or "").lower()

    # The directive must NOT leak into the persisted turn messages.
    assert all(
        "final answer" not in (m.get("content") or "").lower()
        for m in outcome.messages
        if isinstance(m, dict)
    )


# ---------------------------------------------------------------------------
# Scenario (k): the tool-call audit row is chat-scoped (chat_id threaded through)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_threads_chat_id_into_tool_call_audit(db: AsyncSession, user: User) -> None:
    """Regression (issue #207, finding 3): ``run_chat_tool_loop`` must pass
    ``chat_id`` through to ``execute_tool`` so the ``tool_call_log`` audit row is
    chat-scoped. It was previously omitted, leaving ``chat_id`` NULL and making
    chat-scoped audit queries miss the rows.
    """
    from app.chat.tool_loop import LoopFinal, run_chat_tool_loop

    chat_id = uuid.uuid4()
    gateway = AsyncMock()
    gateway.chat_completion.side_effect = [
        _resp_tool_call("search_case_law", {"q": "Brown"}, call_id="c1"),
        _resp_final("Found Brown v. Board."),
    ]
    al = _research_allowlist(provider="cl-prod")

    with (
        patch(
            "app.chat.tool_loop.research_service.search_case_law",
            new=AsyncMock(return_value={"results": [{"cluster_id": 1}]}),
        ),
        patch("app.chat.tool_loop.resolve_provider_tier", new=AsyncMock(return_value=1)),
        patch("app.chat.tool_loop.list_servers", new=AsyncMock(return_value=[])),
    ):
        outcome = await run_chat_tool_loop(
            db,
            user=user,
            gateway=gateway,
            base_request=_req([_user_msg("find Brown")]),
            allowlist=al,
            assistant_message_id=uuid.uuid4(),
            chat_id=chat_id,
        )

    assert isinstance(outcome, LoopFinal)

    rows = (
        (await db.execute(select(ToolCallLog).where(ToolCallLog.origin == "chat"))).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].chat_id == chat_id
