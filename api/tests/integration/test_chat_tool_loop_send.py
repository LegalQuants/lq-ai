"""PR5b Task 6 — integration: chat tool-loop integrated into send_message.

Covers the four contract cases:
(a) Empty allowlist → byte-identical to the existing single-shot streaming path.
    Regression guard: assemble_allowlist is mocked to return an empty allowlist;
    the generator must use gateway.chat_completion_stream (NOT run_chat_tool_loop).
(b) Streaming send, research allowlist, loop returns LoopFinal →
    start / delta(final text) / complete / [DONE]; assistant Message row persisted;
    a tool_call_log row present (written by governed_tool_invocation inside the loop
    for the intermediate tool call, if any — or simply the LoopFinal path).
(c) Streaming send, LoopConfirmation → terminal tool_confirmation_required event;
    chat_pending_tool_call row status=pending; tool_call_log row
    confirmation_state=pending_confirmation / outcome=pending; NO assistant Message;
    stream ends.
(d) Streaming send, LoopMcpAuth → terminal mcp_authorization_required event;
    no pending row written; stream ends.

Strategy: for (b)/(c)/(d) we mock ``run_chat_tool_loop`` to return the desired
outcome directly — this isolates Task 6 rendering/persistence logic from the
loop internals (covered in Task 5). For (a) we mock ``assemble_allowlist`` to
return an empty allowlist and mock the gateway SSE path.
"""

from __future__ import annotations

import contextlib
import json as _json
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_loop import LoopConfirmation, LoopFinal, LoopMcpAuth
from app.chat.tool_schemas import ChatToolAllowlist, ToolSpec
from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.chat import Message
from app.models.chat_pending_tool_call import ChatPendingToolCall
from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.schemas.gateway import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
)
from app.security import create_access_token, hash_password
from app.skills import load_registry
from app.skills.registry import MutableSkillRegistry

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "skills"

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with fixture skill registry + gateway stub."""

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    prior_holder = getattr(app.state, "skill_registry", None)
    if FIXTURES_DIR.exists():
        app.state.skill_registry = MutableSkillRegistry(load_registry(FIXTURES_DIR))
    elif prior_holder is None:
        app.state.skill_registry = MutableSkillRegistry(load_registry(Path("/nonexistent")))

    gw = GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)
    set_gateway_client(gw)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    set_gateway_client(None)
    await gw.aclose()
    if prior_holder is None:
        if hasattr(app.state, "skill_registry"):
            delattr(app.state, "skill_registry")
    else:
        app.state.skill_registry = prior_holder
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"tool-loop-send-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Tool Loop Send Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _h(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


def _parse_sse_frames(body: bytes) -> list[dict]:
    """Parse SSE body into a list of data dicts (excludes [DONE])."""
    frames = []
    for line in body.decode("utf-8").splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :]
        if payload == "[DONE]":
            continue
        with contextlib.suppress(_json.JSONDecodeError):
            frames.append(_json.loads(payload))
    return frames


def _make_tool_spec(
    *,
    function_name: str = "mcp__files__delete_doc",
    kind: Literal["research", "mcp", "authority"] = "mcp",
    provider: str = "files",
    tool: str = "delete_doc",
    destructive: bool = True,
    requires_confirmation: bool = True,
) -> ToolSpec:
    return ToolSpec(
        function_name=function_name,
        kind=kind,
        provider=provider,
        tool=tool,
        read_only=False,
        destructive=destructive,
        requires_confirmation=requires_confirmation,
        parameters={},
        description="delete a document",
    )


def _make_non_empty_allowlist() -> ChatToolAllowlist:
    spec = _make_tool_spec()
    return ChatToolAllowlist(specs={spec.function_name: spec})


# ---------------------------------------------------------------------------
# (a) Empty allowlist — byte-identical to today (no-regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_empty_allowlist_uses_single_shot_stream_path(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Empty allowlist → existing single-shot streaming path; loop NOT called.

    Mocks assemble_allowlist to return an empty ChatToolAllowlist, mocks the
    gateway's chat_completion_stream to yield one delta chunk, and asserts:
    - The SSE stream carries start / delta / complete / [DONE]
    - run_chat_tool_loop was never called
    - The assistant Message row is persisted
    """
    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "regression"})
    assert chat_resp.status_code == 201, chat_resp.text
    chat_id = chat_resp.json()["id"]

    # Build a minimal chunk that gateway.chat_completion_stream would yield.
    chunk = ChatCompletionChunk(
        id="chunk-0",
        created=0,
        model="claude-sonnet-4-6",
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionDelta(content="Hello from stream"),
                finish_reason="stop",
            )
        ],
        routed_inference_tier=3,
        routed_provider="anthropic-prod",
    )

    async def _stream_gen(*_args: object, **_kwargs: object) -> AsyncIterator[ChatCompletionChunk]:
        yield chunk

    empty_allowlist = ChatToolAllowlist(specs={})

    with (
        patch(
            "app.api.chats.assemble_allowlist",
            new=AsyncMock(return_value=empty_allowlist),
        ),
        patch.object(
            GatewayClient,
            "chat_completion_stream",
            new=lambda self, *a, **kw: _stream_gen(self, *a, **kw),
        ),
        patch(
            "app.api.chats.run_chat_tool_loop",
            new=AsyncMock(),
        ) as mock_loop,
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/messages",
            headers=headers,
            json={"content": "hello", "stream": True},
        )

    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers.get("content-type", ""), resp.headers

    frames = _parse_sse_frames(resp.content)
    types = [f.get("type") for f in frames]
    assert "start" in types, f"No start frame: {types}"
    assert "delta" in types, f"No delta frame: {types}"
    assert "complete" in types, f"No complete frame: {types}"

    # Assert the loop was NOT invoked (empty allowlist → single-shot path).
    mock_loop.assert_not_called()

    # Assert the delta carries the text from the mock chunk.
    delta_frames = [f for f in frames if f.get("type") == "delta"]
    assert any("Hello from stream" in f.get("delta", "") for f in delta_frames)

    # Assert the assistant Message row was persisted.
    stmt = select(Message).where(Message.chat_id == uuid.UUID(chat_id), Message.role == "assistant")
    rows = (await db_session.execute(stmt)).scalars().all()
    assert rows, "No assistant Message row persisted for empty-allowlist streaming send"


# ---------------------------------------------------------------------------
# (b) Research allowlist, loop returns LoopFinal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loop_final_emits_delta_complete_and_persists(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Streaming send with non-empty allowlist and LoopFinal outcome.

    Asserts: start / delta(final text) / complete / [DONE] in the stream,
    the assistant Message row is persisted with the final text.
    """
    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "loop-final"})
    assert chat_resp.status_code == 201, chat_resp.text
    chat_id = chat_resp.json()["id"]

    final_text = "Here is the answer from the loop."
    loop_outcome = LoopFinal(
        text=final_text,
        usage_prompt=100,
        usage_completion=50,
        tier=3,
        provider="anthropic-prod",
        model="claude-sonnet-4-6",
        applied_skills=[],
        calls_used=1,
    )

    non_empty_allowlist = _make_non_empty_allowlist()

    with (
        patch(
            "app.api.chats.assemble_allowlist",
            new=AsyncMock(return_value=non_empty_allowlist),
        ),
        patch(
            "app.api.chats.run_chat_tool_loop",
            new=AsyncMock(return_value=loop_outcome),
        ),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/messages",
            headers=headers,
            json={"content": "search for something", "stream": True},
        )

    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers.get("content-type", ""), resp.headers

    body_text = resp.content.decode("utf-8")
    assert "[DONE]" in body_text, "No [DONE] sentinel in stream"

    frames = _parse_sse_frames(resp.content)
    types = [f.get("type") for f in frames]
    assert "start" in types, f"No start frame: {types}"
    assert "delta" in types, f"No delta frame: {types}"
    assert "complete" in types, f"No complete frame: {types}"

    delta_frames = [f for f in frames if f.get("type") == "delta"]
    assert any(final_text in f.get("delta", "") for f in delta_frames), (
        f"Final text not in delta frames: {delta_frames}"
    )

    # Assert no gate frames.
    assert "tool_confirmation_required" not in types
    assert "mcp_authorization_required" not in types

    # Assert assistant Message row persisted with the final text.
    stmt = select(Message).where(Message.chat_id == uuid.UUID(chat_id), Message.role == "assistant")
    rows = (await db_session.execute(stmt)).scalars().all()
    assert rows, "No assistant Message row persisted after LoopFinal"
    assert rows[0].content == final_text, (
        f"Persisted content mismatch: {rows[0].content!r} != {final_text!r}"
    )


# ---------------------------------------------------------------------------
# (c) LoopConfirmation — pending rows written, terminal event emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loop_confirmation_emits_gate_event_and_persists_rows(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Streaming send, LoopConfirmation → tool_confirmation_required terminal event.

    Asserts:
    - The SSE stream ends with a tool_confirmation_required frame
    - A ChatPendingToolCall row exists with status='pending'
    - A ToolCallLog row exists with confirmation_state='pending_confirmation' / outcome='pending'
    - No assistant Message row was persisted (resume path handles that)
    """
    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "loop-confirm"})
    assert chat_resp.status_code == 201, chat_resp.text
    chat_id = chat_resp.json()["id"]

    spec = _make_tool_spec()
    loop_outcome = LoopConfirmation(
        spec=spec,
        args={"doc_id": "abc123", "reason": "remove outdated"},
        tier=2,
        args_summary="digest-placeholder",
        messages=[{"role": "user", "content": "delete the file"}],
        calls_used=0,
    )

    non_empty_allowlist = _make_non_empty_allowlist()

    with (
        patch(
            "app.api.chats.assemble_allowlist",
            new=AsyncMock(return_value=non_empty_allowlist),
        ),
        patch(
            "app.api.chats.run_chat_tool_loop",
            new=AsyncMock(return_value=loop_outcome),
        ),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/messages",
            headers=headers,
            json={"content": "delete doc abc123", "stream": True},
        )

    assert resp.status_code == 200, resp.text
    body_text = resp.content.decode("utf-8")
    assert "[DONE]" in body_text, "No [DONE] sentinel in stream"

    frames = _parse_sse_frames(resp.content)
    gate_frames = [f for f in frames if f.get("type") == "tool_confirmation_required"]
    assert gate_frames, (
        f"No tool_confirmation_required frame; got: {[f.get('type') for f in frames]}"
    )

    gate = gate_frames[0]
    assert "pending_call_id" in gate, f"pending_call_id missing from gate frame: {gate}"
    assert gate["provider"] == spec.provider
    assert gate["tool"] == spec.tool
    assert gate["function_name"] == spec.function_name
    assert gate["destructive"] is True
    assert gate["tier"] == 2

    pending_call_id = uuid.UUID(gate["pending_call_id"])

    # Assert no complete frame (stream ends at gate, not complete).
    assert not any(f.get("type") == "complete" for f in frames), (
        "complete frame found after LoopConfirmation — should not be emitted"
    )

    # Assert ChatPendingToolCall row with status='pending'.
    pending_row = await db_session.get(ChatPendingToolCall, pending_call_id)
    assert pending_row is not None, "ChatPendingToolCall row not found"
    assert pending_row.status == "pending"
    assert pending_row.function_name == spec.function_name
    assert pending_row.provider == spec.provider
    assert pending_row.tool == spec.tool
    assert pending_row.destructive is True

    # Assert ToolCallLog row with pending_confirmation.
    assert pending_row.tool_call_log_id is not None, "tool_call_log_id not linked"
    tcl_row = await db_session.get(ToolCallLog, pending_row.tool_call_log_id)
    assert tcl_row is not None, "ToolCallLog row not found"
    assert tcl_row.confirmation_state == "pending_confirmation"
    assert tcl_row.outcome == "pending"
    assert tcl_row.origin == "chat"
    assert tcl_row.provider == spec.provider
    assert tcl_row.tool == spec.tool

    # Assert NO finalized assistant Message row.
    stmt = select(Message).where(Message.chat_id == uuid.UUID(chat_id), Message.role == "assistant")
    rows = (await db_session.execute(stmt)).scalars().all()
    assert not rows, (
        f"Assistant Message was persisted after LoopConfirmation — should not be: {rows}"
    )


# ---------------------------------------------------------------------------
# (d) LoopMcpAuth — terminal event, no pending row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loop_mcp_auth_emits_gate_event_no_pending_row(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Streaming send, LoopMcpAuth → mcp_authorization_required terminal event.

    Asserts:
    - The SSE stream ends with mcp_authorization_required
    - The authorize_url points to /api/v1/mcp/oauth/{server}/authorize
    - No ChatPendingToolCall row was written
    """
    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "loop-mcp-auth"})
    assert chat_resp.status_code == 201, chat_resp.text
    chat_id = chat_resp.json()["id"]

    loop_outcome = LoopMcpAuth(
        server="legal-research",
        authorize_url=None,
        messages=[{"role": "user", "content": "search"}],
        calls_used=0,
    )

    non_empty_allowlist = _make_non_empty_allowlist()

    with (
        patch(
            "app.api.chats.assemble_allowlist",
            new=AsyncMock(return_value=non_empty_allowlist),
        ),
        patch(
            "app.api.chats.run_chat_tool_loop",
            new=AsyncMock(return_value=loop_outcome),
        ),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/messages",
            headers=headers,
            json={"content": "search legal docs", "stream": True},
        )

    assert resp.status_code == 200, resp.text
    body_text = resp.content.decode("utf-8")
    assert "[DONE]" in body_text, "No [DONE] sentinel in stream"

    frames = _parse_sse_frames(resp.content)
    auth_frames = [f for f in frames if f.get("type") == "mcp_authorization_required"]
    assert auth_frames, (
        f"No mcp_authorization_required frame; got: {[f.get('type') for f in frames]}"
    )

    auth = auth_frames[0]
    assert auth["server"] == "legal-research"
    assert "/api/v1/mcp/oauth/legal-research/authorize" in auth["authorize_url"]

    # Assert no complete frame.
    assert not any(f.get("type") == "complete" for f in frames)

    # Assert no ChatPendingToolCall rows were written.
    stmt = select(ChatPendingToolCall).where(ChatPendingToolCall.chat_id == uuid.UUID(chat_id))
    rows = (await db_session.execute(stmt)).scalars().all()
    assert not rows, f"ChatPendingToolCall rows found after LoopMcpAuth — should not be: {rows}"


# ---------------------------------------------------------------------------
# Fix 1: gate-persist failure emits an error frame, not a silent [DONE]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_gate_persist_failure_emits_error_frame(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Streaming LoopConfirmation with a simulated db.commit failure.

    When the ChatPendingToolCall + ToolCallLog persist step raises, the
    stream must:
    - NOT emit a tool_confirmation_required frame (no partial state)
    - Emit an error SSE frame ({"detail": {...}}) before [DONE]
    - End with [DONE]
    - NOT persist a ChatPendingToolCall row (the commit failed)
    - NOT persist an assistant Message row
    """
    headers = _h(db_user)
    chat_resp = await client.post(
        "/api/v1/chats", headers=headers, json={"title": "gate-persist-fail"}
    )
    assert chat_resp.status_code == 201, chat_resp.text
    chat_id = chat_resp.json()["id"]

    spec = _make_tool_spec()
    loop_outcome = LoopConfirmation(
        spec=spec,
        args={"doc_id": "xyz", "reason": "test persist fail"},
        tier=2,
        args_summary="digest-x",
        messages=[{"role": "user", "content": "delete it"}],
        calls_used=0,
    )

    non_empty_allowlist = _make_non_empty_allowlist()

    # Monkeypatch db.commit so that early commits (user message persist) succeed
    # but the gate-branch commit (2nd call inside the /messages endpoint) fails.
    # The send_message endpoint commits at least once before reaching the gate branch
    # (user message + auto-rename), so we let the first commit through and raise on
    # the second to simulate a gate-persistence failure.
    _original_commit = db_session.commit
    _commit_call_count = 0

    async def _fail_on_second_commit() -> None:
        nonlocal _commit_call_count
        _commit_call_count += 1
        if _commit_call_count >= 2:
            raise RuntimeError("simulated db commit failure")
        await _original_commit()

    with (
        patch(
            "app.api.chats.assemble_allowlist",
            new=AsyncMock(return_value=non_empty_allowlist),
        ),
        patch(
            "app.api.chats.run_chat_tool_loop",
            new=AsyncMock(return_value=loop_outcome),
        ),
        patch.object(db_session, "commit", side_effect=_fail_on_second_commit),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/messages",
            headers=headers,
            json={"content": "delete doc xyz", "stream": True},
        )

    assert resp.status_code == 200, resp.text
    body_text = resp.content.decode("utf-8")

    # [DONE] must be present — stream must terminate cleanly.
    assert "[DONE]" in body_text, f"No [DONE] in stream: {body_text!r}"

    frames = _parse_sse_frames(resp.content)
    types = [f.get("type") for f in frames]

    # No tool_confirmation_required — persist failed before it was emitted.
    assert "tool_confirmation_required" not in types, (
        f"tool_confirmation_required emitted despite persist failure: {types}"
    )

    # An error frame must be present ({"detail": {...}}).
    error_frames = [f for f in frames if "detail" in f]
    assert error_frames, f"No error frame emitted after gate persist failure; frames: {frames}"
    err_detail = error_frames[0]["detail"]
    assert "code" in err_detail, f"Error detail missing 'code': {err_detail}"
    assert err_detail["code"] == "internal_error", f"Unexpected error code: {err_detail['code']!r}"
    # Confirm no exception internals / args leaked into the message.
    assert "simulated" not in err_detail.get("message", ""), (
        f"Exception internals leaked into error message: {err_detail['message']!r}"
    )

    # No assistant Message row (gate failed; resume path would write it).
    stmt = select(Message).where(Message.chat_id == uuid.UUID(chat_id), Message.role == "assistant")
    msg_rows = (await db_session.execute(stmt)).scalars().all()
    assert not msg_rows, f"Unexpected assistant Message row after gate persist failure: {msg_rows}"
