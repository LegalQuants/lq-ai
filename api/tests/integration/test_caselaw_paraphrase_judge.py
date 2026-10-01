"""Integration tests for the caselaw paraphrase-judge SUPPORTED pass (P1-B1b).

These tests cover the four invariants in the task brief:

1. Paraphrased quote (not verbatim) + accepting judge -> one paraphrase_judge
   row -> ledger + gate -> gate_status == 'supported_only'.
2. Mocked judge rejects all consulted opinions -> NO row written (additive-only).
3. Budget set to zero (monkeypatch CASE_CONTENT_JUDGE_BUDGET_USD) -> judge mock
   is NEVER called and no row is written.
4. gateway=None -> unchanged today (verbatim path only; no judge, no rows).

Refs ADR 0018 D2/D3, DE-280, P1-B1b.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_loop import ToolSourceRecord
from app.citation.caselaw import verify_and_persist_caselaw_citations
from app.citation.gate import compute_and_record_gate
from app.citation.ledger import assemble_ledger_entries
from app.models.chat import Chat, Message
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchOpinionMetadata
from app.models.user import User
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Opinion text — deliberately NOT verbatim; passage is a paraphrase.
# ---------------------------------------------------------------------------

_OPINION_TEXT = (
    "The Supreme Court addressed the good faith doctrine at length. "
    "The justices unanimously agreed that every commercial contract "
    "carries an implied duty of honest dealing between parties. "
    "This principle has been recognised since at least 1890. "
    "It applies regardless of whether the parties are sophisticated. "
    "The holding was clear: good-faith performance is mandatory."
)

# This passage paraphrases the opinion but is NOT a verbatim substring.
_PARAPHRASED_PASSAGE = "the court held that an implied duty of good faith applies to all contracts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _caselaw_source(cluster_id: int) -> ToolSourceRecord:
    return ToolSourceRecord(
        source_kind="caselaw",
        label=f"Cluster {cluster_id}",
        subtitle=None,
        url=None,
        external_ref=str(cluster_id),
        provider="courtlistener",
        tool="get_cluster",
    )


def _judge_completion(verdict_json: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-pj-test",
        created=0,
        model="fast",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=verdict_json),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


class _FakeGateway:
    """Minimal gateway stub that records calls and returns a canned verdict."""

    def __init__(self, verdict_json: str) -> None:
        self._verdict = verdict_json
        self.calls = 0
        self.last_request: ChatCompletionRequest | None = None

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str | None = None,
    ) -> ChatCompletionResponse:
        self.calls += 1
        self.last_request = request
        return _judge_completion(self._verdict)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_msg(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, int, int]:
    """Seed a user + chat + assistant message and a consulted opinion.

    Returns (message_id, opinion_id, cluster_id).
    """
    user = User(
        email=f"pj-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="member",
    )
    db_session.add(user)
    await db_session.flush()

    chat = Chat(owner_id=user.id, title="pj-chat")
    db_session.add(chat)
    await db_session.flush()

    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="passage")
    db_session.add(msg)
    await db_session.flush()

    opinion_id = 8001
    cluster_id = 701
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=opinion_id,
            cluster_id=cluster_id,
            text_field_used="plain_text",
            storage_path=f"courtlistener/opinions/by-cluster/{cluster_id}/{opinion_id}",
            char_length=len(_OPINION_TEXT),
        )
    )
    await db_session.flush()

    return msg.id, chat.id, opinion_id, cluster_id


async def _fake_loader(db: AsyncSession, opinion_id: int) -> str:
    return _OPINION_TEXT


# ---------------------------------------------------------------------------
# Test 1 — accept -> paraphrase_judge row -> supported_only gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accepting_judge_writes_paraphrase_judge_row_and_gate(
    db_session: AsyncSession,
    seeded_msg: tuple[uuid.UUID, uuid.UUID, int, int],
) -> None:
    """Paraphrased quote + accepting judge -> one paraphrase_judge row.

    After assemble_ledger_entries + compute_and_record_gate the gate must be
    'supported_only' because paraphrase_judge maps to SUPPORTED_STATUSES.
    """
    message_id, _chat_id, opinion_id, cluster_id = seeded_msg

    assistant_text = f"> {_PARAPHRASED_PASSAGE}\n"
    gw = _FakeGateway(json.dumps({"verdict": "yes", "confidence": "high"}))

    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=assistant_text,
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_fake_loader,
        gateway=gw,
        judge_model="fast",
    )

    # One row written.
    assert n == 1, f"Expected 1 row, got {n}"

    rows = (
        (
            await db_session.execute(
                select(MessageCaselawCitation).where(
                    MessageCaselawCitation.message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.verified is True
    assert row.verification_method == "paraphrase_judge"
    assert row.opinion_id == opinion_id
    assert row.partial is True
    assert row.source_offset_start == 0
    assert row.source_offset_end == len(_OPINION_TEXT)

    # Ledger + gate.
    await assemble_ledger_entries(db_session, message_id=message_id)
    await compute_and_record_gate(db_session, message_id=message_id)

    gate = (
        await db_session.execute(
            select(WorkProductFiduciaryGate).where(
                WorkProductFiduciaryGate.message_id == message_id
            )
        )
    ).scalar_one()
    assert gate.gate_status == "supported_only"


# ---------------------------------------------------------------------------
# Test 2 — rejecting judge -> no row (additive-only invariant)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejecting_judge_writes_no_row(
    db_session: AsyncSession,
    seeded_msg: tuple[uuid.UUID, uuid.UUID, int, int],
) -> None:
    """Judge rejects all consulted opinions -> no row written, additive-only."""
    message_id, _chat_id, _opinion_id, cluster_id = seeded_msg

    assistant_text = f"> {_PARAPHRASED_PASSAGE}\n"
    gw = _FakeGateway(json.dumps({"verdict": "no"}))

    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=assistant_text,
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_fake_loader,
        gateway=gw,
        judge_model="fast",
    )

    assert n == 0, f"Expected 0 rows, got {n}"

    rows = (
        (
            await db_session.execute(
                select(MessageCaselawCitation).where(
                    MessageCaselawCitation.message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 0
    # Judge was called (there was a passage to judge and budget was available).
    assert gw.calls >= 1


# ---------------------------------------------------------------------------
# Test 3 — budget=0 -> judge never called, no row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_budget_prevents_judge_call(
    db_session: AsyncSession,
    seeded_msg: tuple[uuid.UUID, uuid.UUID, int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Budget monkeypatched to Decimal('0') -> judge mock never called, no row."""
    import app.citation.caselaw as caselaw_mod

    monkeypatch.setattr(caselaw_mod, "CASE_CONTENT_JUDGE_BUDGET_USD", Decimal("0"))

    message_id, _chat_id, _opinion_id, cluster_id = seeded_msg

    assistant_text = f"> {_PARAPHRASED_PASSAGE}\n"
    gw = _FakeGateway(json.dumps({"verdict": "yes", "confidence": "high"}))

    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=assistant_text,
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_fake_loader,
        gateway=gw,
        judge_model="fast",
    )

    assert n == 0, f"Expected 0 rows, got {n}"
    assert gw.calls == 0, f"Judge should not be called with budget=0; got {gw.calls} calls"


# ---------------------------------------------------------------------------
# Test 4 — gateway=None -> verbatim-only path unchanged, no judge, no rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_none_is_verbatim_only(
    db_session: AsyncSession,
    seeded_msg: tuple[uuid.UUID, uuid.UUID, int, int],
) -> None:
    """gateway=None -> behaves exactly as today: no judge, no paraphrase_judge rows."""
    message_id, _chat_id, _opinion_id, cluster_id = seeded_msg

    # The passage is paraphrased, so the verbatim path produces nothing.
    assistant_text = f"> {_PARAPHRASED_PASSAGE}\n"

    # No gateway kwarg -> defaults to None.
    n_paraphrase = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=assistant_text,
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_fake_loader,
        # gateway omitted — defaults to None
    )
    assert n_paraphrase == 0, (
        f"gateway=None must not produce rows for paraphrased quote; got {n_paraphrase}"
    )

    rows = (
        (
            await db_session.execute(
                select(MessageCaselawCitation).where(
                    MessageCaselawCitation.message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 0
