"""PR5b Task 7 — integration: resume route POST /chats/{chat_id}/tool-calls/{pending_call_id}.

Covers six contract cases:
(a) approve → executes pending tool, resumes loop, streams LoopFinal, assistant
    Message persisted, pending status=resolved
(b) deny → resumes loop with denial message, streams LoopFinal, pending
    status=resolved, tool_call_log confirmation_state=denied
(c) expired pending → 409
(d) already-resolved (replay) → 409
(e) non-owner → 404
(f) unknown pending_call_id → 404

Strategy: mock execute_tool and run_chat_tool_loop in app.api.chats to isolate
from internals; use real DB for row-state assertions.
"""

from __future__ import annotations

import contextlib
import json as _json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.guard import ToolResult
from app.chat.tool_loop import LoopFinal
from app.chat.tool_schemas import ChatToolAllowlist, ToolSpec
from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.chat import Message
from app.models.chat_pending_tool_call import ChatPendingToolCall
from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.security import create_access_token, hash_password

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"

_DUMMY_UUID = uuid.UUID("00000000-0000-4000-8000-000000000000")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with gateway stub."""
    app.dependency_overrides[get_db] = _override_get_db(db_session)

    gw = GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)
    set_gateway_client(gw)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    set_gateway_client(None)
    await gw.aclose()
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"tool-resume-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Tool Resume Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Other User",
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
    kind: str = "mcp",
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


async def _create_chat_and_pending(
    db_session: AsyncSession,
    *,
    user: User,
    client: AsyncClient,
    status: str = "pending",
    expires_delta: timedelta = timedelta(minutes=15),
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create a chat and a ChatPendingToolCall row. Returns (chat_id, pending_id, assistant_msg_id)."""
    headers = _h(user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "resume-test"})
    assert chat_resp.status_code == 201, chat_resp.text
    chat_id = uuid.UUID(chat_resp.json()["id"])

    assistant_message_id = uuid.uuid4()
    spec = _make_tool_spec()

    # Create a linked ToolCallLog row first.
    tcl_row = ToolCallLog(
        origin="chat",
        provider=spec.provider,
        tool=spec.tool,
        tier=2,
        intent=None,
        confirmation_state="pending_confirmation",
        outcome="pending",
        cost_usd=None,
        args_digest="deadbeef" * 8,
        user_id=user.id,
        chat_id=chat_id,
        message_id=assistant_message_id,
    )
    db_session.add(tcl_row)
    await db_session.flush()

    pending_row = ChatPendingToolCall(
        chat_id=chat_id,
        user_id=user.id,
        assistant_message_id=assistant_message_id,
        function_name=spec.function_name,
        kind=spec.kind,
        provider=spec.provider,
        tool=spec.tool,
        destructive=spec.destructive,
        tier=2,
        tool_call_args={"doc_id": "abc123"},
        resume_state={
            "messages": [{"role": "user", "content": "delete the file"}],
            "calls_used": 0,
            "model": "smart",
        },
        status=status,
        expires_at=datetime.now(UTC) + expires_delta,
        tool_call_log_id=tcl_row.id,
    )
    db_session.add(pending_row)
    await db_session.flush()
    await db_session.commit()

    return chat_id, pending_row.id, assistant_message_id


# ---------------------------------------------------------------------------
# (a) Approve path — execute_tool succeeds, LoopFinal, assistant row persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_approve_executes_tool_and_streams_loop_final(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Approve → execute tool, resume loop → LoopFinal; start/delta/complete/[DONE] in stream;
    assistant Message row persisted; pending_row status=resolved.
    """
    chat_id, pending_id, assistant_message_id = await _create_chat_and_pending(
        db_session, user=db_user, client=client
    )

    spec = _make_tool_spec()
    final_text = "Done! The document was deleted."
    loop_final = LoopFinal(
        text=final_text,
        usage_prompt=80,
        usage_completion=30,
        tier=2,
        provider="anthropic-prod",
        model="claude-sonnet-4-6",
        applied_skills=[],
        calls_used=1,
    )
    tool_result = ToolResult(
        cost_usd=Decimal("0"),
        data={"deleted": "abc123"},
        outcome="success",
    )

    non_empty_allowlist = ChatToolAllowlist(specs={spec.function_name: spec})

    with (
        patch(
            "app.api.chats.assemble_allowlist",
            new=AsyncMock(return_value=non_empty_allowlist),
        ),
        # execute_tool is imported locally inside _generate(); patch the source module.
        patch(
            "app.chat.tool_loop.execute_tool",
            new=AsyncMock(return_value=tool_result),
        ),
        patch(
            "app.api.chats.run_chat_tool_loop",
            new=AsyncMock(return_value=loop_final),
        ),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/tool-calls/{pending_id}",
            headers=_h(db_user),
            json={"decision": "approve"},
        )

    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers.get("content-type", "")

    body = resp.content
    assert b"[DONE]" in body, "No [DONE] sentinel in stream"

    frames = _parse_sse_frames(body)
    types = [f.get("type") for f in frames]
    assert "start" in types, f"No start frame: {types}"
    assert "delta" in types, f"No delta frame: {types}"
    assert "complete" in types, f"No complete frame: {types}"

    delta_frames = [f for f in frames if f.get("type") == "delta"]
    assert any(final_text in f.get("delta", "") for f in delta_frames), (
        f"Final text not in delta frames: {delta_frames}"
    )

    # Assert pending row is resolved.
    await db_session.refresh(
        await db_session.get(ChatPendingToolCall, pending_id)  # type: ignore[arg-type]
    )
    pending_row = await db_session.get(ChatPendingToolCall, pending_id)
    assert pending_row is not None
    assert pending_row.status == "resolved", f"Expected resolved, got {pending_row.status!r}"

    # Assert assistant Message row was persisted.
    from sqlalchemy import select

    stmt = select(Message).where(
        Message.chat_id == chat_id,
        Message.role == "assistant",
        Message.id == assistant_message_id,
    )
    rows = (await db_session.execute(stmt)).scalars().all()
    assert rows, "No assistant Message row persisted after approve + LoopFinal"
    assert rows[0].content == final_text


# ---------------------------------------------------------------------------
# (b) Deny path — denial message fed to loop, LoopFinal, pending=resolved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deny_feeds_denial_message_and_streams_loop_final(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Deny → denial tool message fed to loop → LoopFinal; stream normal;
    pending_row status=resolved; ToolCallLog confirmation_state=denied.
    """
    chat_id, pending_id, assistant_message_id = await _create_chat_and_pending(
        db_session, user=db_user, client=client
    )

    # Reload the pending row to get its tool_call_log_id.
    pending_row = await db_session.get(ChatPendingToolCall, pending_id)
    assert pending_row is not None
    tcl_id = pending_row.tool_call_log_id

    spec = _make_tool_spec()
    final_text = "The deletion was denied. No changes were made."
    loop_final = LoopFinal(
        text=final_text,
        usage_prompt=60,
        usage_completion=25,
        tier=2,
        provider="anthropic-prod",
        model="claude-sonnet-4-6",
        applied_skills=[],
        calls_used=0,
    )

    non_empty_allowlist = ChatToolAllowlist(specs={spec.function_name: spec})

    with (
        patch(
            "app.api.chats.assemble_allowlist",
            new=AsyncMock(return_value=non_empty_allowlist),
        ),
        patch(
            "app.api.chats.run_chat_tool_loop",
            new=AsyncMock(return_value=loop_final),
        ),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/tool-calls/{pending_id}",
            headers=_h(db_user),
            json={"decision": "deny"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.content
    assert b"[DONE]" in body

    frames = _parse_sse_frames(body)
    types = [f.get("type") for f in frames]
    assert "start" in types
    assert "delta" in types
    assert "complete" in types

    # Assert pending row resolved.
    await db_session.refresh(pending_row)
    assert pending_row.status == "resolved"

    # Assert ToolCallLog confirmation_state=denied.
    if tcl_id is not None:
        tcl_row = await db_session.get(ToolCallLog, tcl_id)
        assert tcl_row is not None
        assert tcl_row.confirmation_state == "denied", (
            f"Expected denied, got {tcl_row.confirmation_state!r}"
        )
        assert tcl_row.outcome == "denied"

    # Assert assistant Message row persisted.
    from sqlalchemy import select

    stmt = select(Message).where(
        Message.chat_id == chat_id,
        Message.role == "assistant",
        Message.id == assistant_message_id,
    )
    rows = (await db_session.execute(stmt)).scalars().all()
    assert rows, "No assistant Message row persisted after deny + LoopFinal"


# ---------------------------------------------------------------------------
# (c) Expired pending → 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_expired_pending_returns_409(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """An expired pending tool-call row returns 409 Conflict."""
    chat_id, pending_id, _ = await _create_chat_and_pending(
        db_session,
        user=db_user,
        client=client,
        expires_delta=timedelta(seconds=-1),  # already expired
    )

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/tool-calls/{pending_id}",
        headers=_h(db_user),
        json={"decision": "approve"},
    )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert "detail" in body
    assert body["detail"]["code"] == "conflict"


# ---------------------------------------------------------------------------
# (d) Already-resolved (replay) → 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_already_resolved_returns_409(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """A pending row with status='resolved' returns 409 on replay."""
    chat_id, pending_id, _ = await _create_chat_and_pending(
        db_session,
        user=db_user,
        client=client,
        status="resolved",
    )

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/tool-calls/{pending_id}",
        headers=_h(db_user),
        json={"decision": "approve"},
    )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert "detail" in body
    assert body["detail"]["code"] == "conflict"


# ---------------------------------------------------------------------------
# (e) Non-owner → 404 (id-probing-safe)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_non_owner_gets_404(
    client: AsyncClient,
    db_user: User,
    other_user: User,
    db_session: AsyncSession,
) -> None:
    """A different user cannot see the pending row — 404 (id-probing-safe)."""
    chat_id, pending_id, _ = await _create_chat_and_pending(db_session, user=db_user, client=client)

    # other_user tries to resume the pending call owned by db_user.
    resp = await client.post(
        f"/api/v1/chats/{chat_id}/tool-calls/{pending_id}",
        headers=_h(other_user),
        json={"decision": "approve"},
    )

    # The chat itself is owner-scoped — other_user gets 404 on the chat load.
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# (f) Unknown pending_call_id → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unknown_pending_call_id_returns_404(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """A completely unknown pending_call_id (UUID that exists nowhere) → 404."""
    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "unknown-test"})
    assert chat_resp.status_code == 201, chat_resp.text
    chat_id = chat_resp.json()["id"]

    unknown_id = str(uuid.uuid4())

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/tool-calls/{unknown_id}",
        headers=headers,
        json={"decision": "approve"},
    )

    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert "detail" in body
    assert body["detail"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# (g) C1: already-resolved row returns 409 WITHOUT executing the tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_already_resolved_does_not_execute_tool(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """A replay POST on an already-resolved row must return 409 and never call execute_tool.

    This verifies the atomic claim gate: once a row is resolved, a second
    POST claiming the same row should lose the conditional UPDATE and return
    409 without executing the destructive tool.
    """
    chat_id, pending_id, _ = await _create_chat_and_pending(
        db_session,
        user=db_user,
        client=client,
        status="resolved",
    )

    execute_tool_mock = AsyncMock()

    # The handler imports execute_tool via `from app.chat.tool_loop import execute_tool`
    # inside _generate(); patch at the source module so the local reference is replaced.
    with patch("app.chat.tool_loop.execute_tool", new=execute_tool_mock):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/tool-calls/{pending_id}",
            headers=_h(db_user),
            json={"decision": "approve"},
        )

    assert resp.status_code == 409, resp.text
    # execute_tool must NEVER be called when the claim fails (the atomic gate rejected it)
    execute_tool_mock.assert_not_called()


# ---------------------------------------------------------------------------
# (h) C1: claim is committed before execute_tool is called — verified via DB read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_claim_committed_before_execute_tool(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """On approve, the pending row must be status='resolved' in the DB
    (committed, not just flushed) before execute_tool begins execution.

    Strategy: intercept execute_tool at app.api.chats (the bound name from the
    handler-level 'from app.chat.tool_loop import execute_tool') and have it
    inspect the row's status through the SAME db session that the handler uses.
    The handler committed before calling execute_tool, so the session should
    see status='resolved' on a fresh get().
    """
    chat_id, pending_id, _assistant_message_id = await _create_chat_and_pending(
        db_session, user=db_user, client=client
    )

    status_at_execute: list[str] = []

    # We capture the db argument passed to execute_tool (the handler's session).
    # After db.commit() the session's identity map is updated, so db.get() returns
    # the committed state.
    async def _capture_and_succeed(db: AsyncSession, *args: object, **kwargs: object) -> ToolResult:
        row = await db.get(ChatPendingToolCall, pending_id)
        if row is not None:
            status_at_execute.append(row.status)
        return ToolResult(cost_usd=Decimal("0"), data={"ok": True}, outcome="success")

    spec = _make_tool_spec()
    loop_final = LoopFinal(
        text="Done.",
        usage_prompt=10,
        usage_completion=5,
        tier=2,
        provider="anthropic-prod",
        model="claude-sonnet-4-6",
        applied_skills=[],
        calls_used=1,
    )
    non_empty_allowlist = ChatToolAllowlist(specs={spec.function_name: spec})

    # Patch the name as imported by the handler module (function-level import
    # 'from app.chat.tool_loop import execute_tool' runs at call time, so patching
    # the source attribute covers it).
    with (
        patch(
            "app.api.chats.assemble_allowlist",
            new=AsyncMock(return_value=non_empty_allowlist),
        ),
        patch(
            "app.chat.tool_loop.execute_tool",
            new=AsyncMock(side_effect=_capture_and_succeed),
        ),
        patch(
            "app.api.chats.run_chat_tool_loop",
            new=AsyncMock(return_value=loop_final),
        ),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/tool-calls/{pending_id}",
            headers=_h(db_user),
            json={"decision": "approve"},
        )

    assert resp.status_code == 200, resp.text
    # The status observed inside execute_tool must already be 'resolved' (committed)
    assert status_at_execute, "execute_tool was not called — test setup issue"
    assert status_at_execute[0] == "resolved", (
        f"Claim was not committed before execute_tool: status was {status_at_execute[0]!r}"
    )


# ---------------------------------------------------------------------------
# (i) I1: approve path writes EXECUTING tool_call_log row with confirmation_state=approved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_approve_executing_audit_row_has_approved_confirmation_state(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """On approve, the EXECUTING tool_call_log row written by governed_tool_invocation
    must have confirmation_state='approved' and outcome='executed'.

    Two-row audit model:
    - Gate row (pending.tool_call_log_id): the confirmation-request lifecycle
      record (pending_confirmation → approved).  confirmation_state='approved',
      but outcome is NOT 'executed' (it is the gate record, not the execution).
    - Execution row: written by execute_tool → governed_tool_invocation with
      confirmation_state='approved' and outcome='executed'.
    """
    chat_id, pending_id, _assistant_msg_id = await _create_chat_and_pending(
        db_session, user=db_user, client=client
    )

    # Reload the pending row to get its gate tool_call_log_id.
    pending_row = await db_session.get(ChatPendingToolCall, pending_id)
    assert pending_row is not None
    gate_tcl_id = pending_row.tool_call_log_id
    assert gate_tcl_id is not None

    spec = _make_tool_spec()
    loop_final = LoopFinal(
        text="Executed successfully.",
        usage_prompt=10,
        usage_completion=5,
        tier=2,
        provider="anthropic-prod",
        model="claude-sonnet-4-6",
        applied_skills=[],
        calls_used=1,
    )
    non_empty_allowlist = ChatToolAllowlist(specs={spec.function_name: spec})

    # Use the real execute_tool path (but mock governed_tool_invocation to avoid
    # actual tool dispatch) so the confirmation_state param flows through correctly.
    from app.autonomous.guard import ToolResult as _ToolResult

    execute_result = _ToolResult(cost_usd=Decimal("0"), data={"ok": True}, outcome="success")

    captured_kwargs: list[dict] = []

    async def _fake_gov(db: object, *args: object, **kwargs: object) -> _ToolResult:
        captured_kwargs.append(dict(kwargs))
        return execute_result

    with (
        patch(
            "app.api.chats.assemble_allowlist",
            new=AsyncMock(return_value=non_empty_allowlist),
        ),
        patch(
            "app.api.chats.run_chat_tool_loop",
            new=AsyncMock(return_value=loop_final),
        ),
        # Patch governed_tool_invocation at the name bound in tool_loop (the
        # from-import: 'from app.tools.governance import governed_tool_invocation').
        patch(
            "app.chat.tool_loop.governed_tool_invocation",
            new=AsyncMock(side_effect=_fake_gov),
        ),
        # Also patch resolve_provider_tier to avoid gateway calls.
        patch(
            "app.chat.tool_loop.resolve_provider_tier",
            new=AsyncMock(return_value=2),
        ),
        # patch estimate_tool_cost to avoid DB/gateway calls.
        patch(
            "app.chat.tool_loop.estimate_tool_cost",
            new=AsyncMock(return_value=Decimal("0")),
        ),
        # patch list_servers to avoid gateway calls.
        patch(
            "app.mcp.service.list_servers",
            new=AsyncMock(return_value=[]),
        ),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/tool-calls/{pending_id}",
            headers=_h(db_user),
            json={"decision": "approve"},
        )

    assert resp.status_code == 200, resp.text

    # governed_tool_invocation must have been called with confirmation_state="approved"
    assert captured_kwargs, "governed_tool_invocation was never called"
    got_state = captured_kwargs[0].get("confirmation_state", "MISSING")
    assert got_state == "approved", (
        f"Expected confirmation_state='approved' passed to governed_tool_invocation, "
        f"got {got_state!r}"
    )

    # The gate row must have confirmation_state="approved" but NOT outcome="executed".
    # (The gate row is the confirmation-request lifecycle record; only the execution
    # row — written by governed_tool_invocation — carries outcome="executed".)
    gate_row = await db_session.get(ToolCallLog, gate_tcl_id)
    assert gate_row is not None
    db_session.expire(gate_row)
    gate_row = await db_session.get(ToolCallLog, gate_tcl_id)
    assert gate_row is not None
    assert gate_row.confirmation_state == "approved", (
        f"Gate row confirmation_state expected 'approved', got {gate_row.confirmation_state!r}"
    )
    # Gate row outcome must NOT be "executed" — it is the confirmation-request record,
    # not the execution record.
    assert gate_row.outcome != "executed", (
        f"Gate row must not have outcome='executed' (it is the confirmation-request record, "
        f"not the execution record); got outcome={gate_row.outcome!r}"
    )


# ---------------------------------------------------------------------------
# (j) C1-fix: approve path — gateway receives valid assistant tool_calls turn
#             before the tool result (NOT an orphaned tool message)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_approve_gateway_receives_assistant_turn_before_tool_result(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Regression: on approve, the conversation sent to run_chat_tool_loop must end with
    an assistant message carrying a tool_calls entry, immediately followed by a role='tool'
    message whose tool_call_id matches that assistant entry's id.

    Without the C1 fix the resume path appended an orphaned role='tool' message with no
    preceding assistant tool_calls turn, causing Anthropic/OpenAI to return 400.
    This test asserts the conversation structure is valid — it FAILS against pre-fix code
    (where no assistant turn is reconstructed) and PASSES after the fix.
    """
    chat_id, pending_id, _assistant_message_id = await _create_chat_and_pending(
        db_session, user=db_user, client=client
    )

    spec = _make_tool_spec()
    loop_final = LoopFinal(
        text="Approved and done.",
        usage_prompt=80,
        usage_completion=30,
        tier=2,
        provider="anthropic-prod",
        model="claude-sonnet-4-6",
        applied_skills=[],
        calls_used=1,
    )
    tool_result_val = ToolResult(
        cost_usd=Decimal("0"),
        data={"deleted": "abc123"},
        outcome="success",
    )
    non_empty_allowlist = ChatToolAllowlist(specs={spec.function_name: spec})

    # Capture the messages argument passed to run_chat_tool_loop.
    captured_messages: list[list] = []

    async def _capture_loop(
        db: object,
        *,
        base_request: object,
        **kwargs: object,
    ) -> LoopFinal:
        from app.schemas.gateway import ChatCompletionRequest as _CCR

        assert isinstance(base_request, _CCR)
        captured_messages.append(list(base_request.messages))
        return loop_final

    with (
        patch(
            "app.api.chats.assemble_allowlist",
            new=AsyncMock(return_value=non_empty_allowlist),
        ),
        patch(
            "app.chat.tool_loop.execute_tool",
            new=AsyncMock(return_value=tool_result_val),
        ),
        patch(
            "app.api.chats.run_chat_tool_loop",
            new=AsyncMock(side_effect=_capture_loop),
        ),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/tool-calls/{pending_id}",
            headers=_h(db_user),
            json={"decision": "approve"},
        )

    assert resp.status_code == 200, resp.text
    assert captured_messages, "run_chat_tool_loop was never called — test setup issue"

    msgs = captured_messages[0]
    # Find the last assistant message with tool_calls.
    assistant_tool_msg = None
    for m in msgs:
        role = m.role if hasattr(m, "role") else m.get("role")
        tool_calls = m.tool_calls if hasattr(m, "tool_calls") else m.get("tool_calls")
        if role == "assistant" and tool_calls:
            assistant_tool_msg = m
    assert assistant_tool_msg is not None, (
        "No assistant message with tool_calls found in conversation sent to loop — "
        "the reconstructed assistant turn is missing (pre-fix orphan bug)"
    )

    # The role='tool' message must have a tool_call_id matching the assistant turn's id.
    tool_calls_list = (
        assistant_tool_msg.tool_calls
        if hasattr(assistant_tool_msg, "tool_calls")
        else assistant_tool_msg["tool_calls"]
    )
    assistant_tc_id = tool_calls_list[0]["id"]

    tool_msg = None
    for m in msgs:
        role = m.role if hasattr(m, "role") else m.get("role")
        if role == "tool":
            tool_call_id_val = (
                m.tool_call_id if hasattr(m, "tool_call_id") else m.get("tool_call_id")
            )
            tool_msg = m
            assert tool_call_id_val == assistant_tc_id, (
                f"role='tool' message has tool_call_id={tool_call_id_val!r} but "
                f"assistant turn has id={assistant_tc_id!r} — orphaned tool message!"
            )
            break

    assert tool_msg is not None, (
        "No role='tool' message found in conversation — tool result was not appended"
    )


# ---------------------------------------------------------------------------
# (k) C1-fix: deny path — gateway receives valid assistant tool_calls turn
#             before the denial error message (NOT an orphaned tool message)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_deny_gateway_receives_assistant_turn_before_denial_message(
    client: AsyncClient,
    db_user: User,
    db_session: AsyncSession,
) -> None:
    """Regression: on deny, the conversation sent to run_chat_tool_loop must end with
    an assistant message carrying a tool_calls entry, immediately followed by a role='tool'
    denial message whose tool_call_id matches that assistant entry's id.

    Without the C1 fix the deny path appended an orphaned role='tool' denial message with
    no preceding assistant tool_calls turn, causing Anthropic/OpenAI to return 400.
    This test FAILS against pre-fix code and PASSES after the fix.
    """
    chat_id, pending_id, _assistant_message_id = await _create_chat_and_pending(
        db_session, user=db_user, client=client
    )

    spec = _make_tool_spec()
    loop_final = LoopFinal(
        text="The deletion was denied. No changes were made.",
        usage_prompt=60,
        usage_completion=25,
        tier=2,
        provider="anthropic-prod",
        model="claude-sonnet-4-6",
        applied_skills=[],
        calls_used=0,
    )
    non_empty_allowlist = ChatToolAllowlist(specs={spec.function_name: spec})

    captured_messages: list[list] = []

    async def _capture_loop(
        db: object,
        *,
        base_request: object,
        **kwargs: object,
    ) -> LoopFinal:
        from app.schemas.gateway import ChatCompletionRequest as _CCR

        assert isinstance(base_request, _CCR)
        captured_messages.append(list(base_request.messages))
        return loop_final

    with (
        patch(
            "app.api.chats.assemble_allowlist",
            new=AsyncMock(return_value=non_empty_allowlist),
        ),
        patch(
            "app.api.chats.run_chat_tool_loop",
            new=AsyncMock(side_effect=_capture_loop),
        ),
    ):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/tool-calls/{pending_id}",
            headers=_h(db_user),
            json={"decision": "deny"},
        )

    assert resp.status_code == 200, resp.text
    assert captured_messages, "run_chat_tool_loop was never called — test setup issue"

    msgs = captured_messages[0]
    # Find any assistant message with tool_calls.
    assistant_tool_msg = None
    for m in msgs:
        role = m.role if hasattr(m, "role") else m.get("role")
        tool_calls = m.tool_calls if hasattr(m, "tool_calls") else m.get("tool_calls")
        if role == "assistant" and tool_calls:
            assistant_tool_msg = m
    assert assistant_tool_msg is not None, (
        "No assistant message with tool_calls found in conversation sent to loop on deny — "
        "the reconstructed assistant turn is missing (pre-fix orphan bug)"
    )

    tool_calls_list = (
        assistant_tool_msg.tool_calls
        if hasattr(assistant_tool_msg, "tool_calls")
        else assistant_tool_msg["tool_calls"]
    )
    assistant_tc_id = tool_calls_list[0]["id"]

    tool_msg = None
    for m in msgs:
        role = m.role if hasattr(m, "role") else m.get("role")
        if role == "tool":
            tool_call_id_val = (
                m.tool_call_id if hasattr(m, "tool_call_id") else m.get("tool_call_id")
            )
            tool_msg = m
            assert tool_call_id_val == assistant_tc_id, (
                f"role='tool' denial message has tool_call_id={tool_call_id_val!r} but "
                f"assistant turn has id={assistant_tc_id!r} — orphaned tool message on deny!"
            )
            break

    assert tool_msg is not None, (
        "No role='tool' denial message found in conversation — denial message was not appended"
    )
