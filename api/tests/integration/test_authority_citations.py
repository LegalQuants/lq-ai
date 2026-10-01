"""Integration tests for the chat authority-citation finalize hook (WS-E PR1c Task 5).

Unlike ``tests/citation/test_authority_verify.py`` (Task 4 — direct-call unit
tests of ``verify_and_persist_authority_citations`` with hand-built
``ToolSourceRecord`` inputs), this file drives the REAL chain end to end:

    fake gateway (chat_completion + call_tool)
      -> app.chat.tool_loop.run_chat_tool_loop (real dispatch routing)
      -> app.chat.tool_loop._dispatch_authority (real GovInfoAdapter parsing +
         real store_authority_text cache write, object storage faked)
      -> verify_and_persist_authority_citations (the same call chats.py's
         finalize sites make, using the loop's real outcome.text /
         outcome.tool_sources)
      -> assemble_ledger_entries -> compute_and_record_gate

This proves fetch -> cache -> verify -> ledger -> gate for the authority path,
mirroring the caselaw analogs in tests/integration/test_caselaw_paraphrase_judge.py
and test_caselaw_fail_attribution.py (which assemble the ledger + gate after a
direct verify call) but sourcing tool_sources from a genuine tool-loop run
instead of a hand-rolled ToolSourceRecord.

Note: this does NOT drive the HTTP /messages endpoint — no existing test in
this codebase mocks the model at that layer for the citation-verify chain (the
caselaw integration tests call verify_and_persist_caselaw_citations directly).
chats.py's finalize wiring itself (Steps 3-5) is exercised by ruff/mypy +
inspection; it is a thin pass-through of already-tested pieces.

Refs ADR 0021 D3, DE-369.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_loop import LoopFinal, run_chat_tool_loop
from app.chat.tool_schemas import ChatToolAllowlist, ToolSpec
from app.citation.authority import verify_and_persist_authority_citations
from app.citation.gate import compute_and_record_gate
from app.citation.ledger import assemble_ledger_entries
from app.models.chat import Chat, Message
from app.models.message_authority_citation import MessageAuthorityCitation
from app.models.user import User
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)
from app.security import hash_password

pytestmark = pytest.mark.integration

_PACKAGE_ID = "USCODE-2022-title17"
_BODY = (
    "Notwithstanding the provisions of sections 106 and 106A, the fair use "
    "of a copyrighted work is not an infringement of copyright."
)
_VERBATIM_PASSAGE = "the fair use of a copyrighted work is not an infringement of copyright."
_FABRICATED_PASSAGE = "the statute expressly bans all reproduction without a signed license."

_AUTHORITY_PAYLOAD = {
    "package_id": _PACKAGE_ID,
    "citation": "17 U.S.C. 107",
    "title": "Limitations on exclusive rights: Fair use",
    "url": "https://govinfo.example/uscode17",
    "text": _BODY,
}


# ---------------------------------------------------------------------------
# Object-storage fake (mirrors tests/chat/test_tool_loop.py's
# fake_authority_storage; store_authority_text hits real object storage
# otherwise).
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_authority_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    store: dict[str, bytes] = {}

    async def _upload(*, storage_path: str, body: bytes, content_type: str) -> None:
        store[storage_path] = body

    class _Reader:
        def __init__(self, data: bytes) -> None:
            self._data = data

        async def __aenter__(self) -> AsyncIterator[bytes]:
            data = self._data

            async def _gen() -> AsyncIterator[bytes]:
                yield data

            return _gen()

        async def __aexit__(self, *a: object) -> bool:
            return False

    def _download(*, storage_path: str) -> _Reader:
        return _Reader(store[storage_path])

    monkeypatch.setattr("app.citation.authority.upload_bytes", _upload)
    monkeypatch.setattr("app.citation.authority.stream_download", _download)
    return store


# ---------------------------------------------------------------------------
# Gateway stub: serves the tool-loop's two chat_completion rounds (tool call,
# then final answer) via chat_responses, and get_authority's call_tool. Any
# chat_completion call beyond the seeded rounds (the Pass-B paraphrase judge)
# falls back to a rejecting verdict unless overridden.
# ---------------------------------------------------------------------------


class _FakeGateway:
    def __init__(
        self,
        chat_responses: list[ChatCompletionResponse],
        authority_payload: dict,
        judge_verdict_json: str = json.dumps({"verdict": "no"}),
    ) -> None:
        self._chat_responses = list(chat_responses)
        self._authority_payload = authority_payload
        self._judge_verdict_json = judge_verdict_json
        self.chat_calls = 0
        self.call_tool_calls: list[tuple[str, str, dict]] = []

    async def chat_completion(
        self, request: ChatCompletionRequest, *, request_id: str | None = None
    ) -> ChatCompletionResponse:
        self.chat_calls += 1
        if self._chat_responses:
            return self._chat_responses.pop(0)
        return ChatCompletionResponse(
            id="chatcmpl-judge",
            created=0,
            model="fast",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionMessage(
                        role="assistant", content=self._judge_verdict_json
                    ),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
        )

    async def call_tool(self, provider: str, op: str, args: dict) -> dict:
        self.call_tool_calls.append((provider, op, args))
        return {"payload": self._authority_payload}


def _authority_allowlist() -> ChatToolAllowlist:
    spec = ToolSpec(
        function_name="get_authority",
        kind="authority",
        provider="govinfo",
        tool="get_authority",
        read_only=True,
        destructive=False,
        requires_confirmation=False,
        parameters={
            "type": "object",
            "properties": {"package_id": {"type": "string"}},
            "required": ["package_id"],
        },
        description="Fetch a statute/regulation body from GovInfo.",
    )
    return ChatToolAllowlist(specs={"get_authority": spec})


def _resp_tool_call(fn_name: str, args: dict) -> ChatCompletionResponse:
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
                    tool_calls=[
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": fn_name, "arguments": json.dumps(args)},
                        }
                    ],
                ),
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        routed_inference_tier=2,
        routed_provider="anthropic",
    )


def _resp_final(text: str) -> ChatCompletionResponse:
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> tuple[User, Chat, uuid.UUID]:
    """Seed a user + chat + assistant message; yield (user, chat, message_id)."""
    user = User(
        email=f"auth-cite-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Authority Citation Test User",
        hashed_password=hash_password("hunter2"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()

    chat = Chat(owner_id=user.id, project_id=None, title="authority-cite-chat")
    db_session.add(chat)
    await db_session.flush()

    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="")
    db_session.add(msg)
    await db_session.flush()

    return user, chat, msg.id


async def _run_loop(
    db_session: AsyncSession,
    user: User,
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
    gw: _FakeGateway,
) -> LoopFinal:
    with (
        patch("app.chat.tool_loop.resolve_provider_tier", new=AsyncMock(return_value=1)),
        patch("app.chat.tool_loop.list_servers", new=AsyncMock(return_value=[])),
    ):
        outcome = await run_chat_tool_loop(
            db_session,
            user=user,
            gateway=gw,
            base_request=ChatCompletionRequest(
                model="smart",
                messages=[
                    ChatCompletionMessage(
                        role="user", content="Does 17 U.S.C. 107 excuse this use?"
                    )
                ],
            ),
            allowlist=_authority_allowlist(),
            assistant_message_id=message_id,
            chat_id=chat_id,
        )
    assert isinstance(outcome, LoopFinal), f"expected LoopFinal, got {outcome!r}"
    return outcome


# ---------------------------------------------------------------------------
# Test 1 — verbatim quote of the fetched statute -> PASS row -> fiduciary_grade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_get_authority_verbatim_quote_verifies_and_gates(
    db_session: AsyncSession,
    seeded: tuple[User, Chat, uuid.UUID],
    fake_authority_storage: dict[str, bytes],
) -> None:
    user, chat, message_id = seeded

    gw = _FakeGateway(
        chat_responses=[
            _resp_tool_call("get_authority", {"package_id": _PACKAGE_ID}),
            _resp_final(f"Under 17 U.S.C. 107:\n\n> {_VERBATIM_PASSAGE}\n"),
        ],
        authority_payload=_AUTHORITY_PAYLOAD,
    )

    outcome = await _run_loop(db_session, user, chat.id, message_id, gw)
    assert gw.call_tool_calls == [("govinfo", "get_authority", {"package_id": _PACKAGE_ID})]
    assert outcome.tool_sources, "loop produced no tool_sources for get_authority"

    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=message_id,
        assistant_text=outcome.text,
        tool_sources=outcome.tool_sources,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 1, f"expected 1 authority citation row, got {n}"

    rows = (
        (
            await db_session.execute(
                select(MessageAuthorityCitation).where(
                    MessageAuthorityCitation.message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].verified is True
    assert rows[0].content_kind == "statute"
    assert rows[0].external_ref == _PACKAGE_ID

    await assemble_ledger_entries(db_session, message_id=message_id)
    await compute_and_record_gate(db_session, message_id=message_id)

    from app.models.citation_ledger_entry import CitationLedgerEntry

    ledger_rows = (
        (
            await db_session.execute(
                select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == message_id)
            )
        )
        .scalars()
        .all()
    )
    assert any(e.source_kind == "statute" for e in ledger_rows)

    gate = (
        await db_session.execute(
            select(WorkProductFiduciaryGate).where(
                WorkProductFiduciaryGate.message_id == message_id
            )
        )
    ).scalar_one()
    assert gate.gate_status == "fiduciary_grade"


# ---------------------------------------------------------------------------
# Test 2 — fabricated quote (not in the fetched body) -> 0 rows, gate unaffected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_fabricated_authority_quote_dropped(
    db_session: AsyncSession,
    seeded: tuple[User, Chat, uuid.UUID],
    fake_authority_storage: dict[str, bytes],
) -> None:
    user, chat, message_id = seeded

    gw = _FakeGateway(
        chat_responses=[
            _resp_tool_call("get_authority", {"package_id": _PACKAGE_ID}),
            _resp_final(f"Under 17 U.S.C. 107:\n\n> {_FABRICATED_PASSAGE}\n"),
        ],
        authority_payload=_AUTHORITY_PAYLOAD,
        judge_verdict_json=json.dumps({"verdict": "no"}),
    )

    outcome = await _run_loop(db_session, user, chat.id, message_id, gw)

    n = await verify_and_persist_authority_citations(
        db_session,
        message_id=message_id,
        assistant_text=outcome.text,
        tool_sources=outcome.tool_sources,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 0, f"expected 0 authority citation rows for a fabricated quote, got {n}"
    # The paraphrase-judge Pass B was consulted (and rejected) — it does not
    # write a FAIL row for authority (unattributed drop-on-miss, DE-370 defers
    # attributed-authority FAIL).
    assert gw.chat_calls >= 3  # 2 loop rounds + >=1 judge call

    rows = (
        (
            await db_session.execute(
                select(MessageAuthorityCitation).where(
                    MessageAuthorityCitation.message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == []

    await assemble_ledger_entries(db_session, message_id=message_id)
    await compute_and_record_gate(db_session, message_id=message_id)

    gate = (
        await db_session.execute(
            select(WorkProductFiduciaryGate).where(
                WorkProductFiduciaryGate.message_id == message_id
            )
        )
    ).scalar_one()
    # No authority assertion was recorded -> the gate is not "flagged" on
    # account of authority (no FAIL entries were produced).
    assert gate.gate_status != "flagged"
