"""Integration tests for the caselaw FAIL tier via H3 attribution (P1-B1c).

Invariants:
1. Attributed + judge REJECT -> one FAIL row (verified=False, method NULL)
   -> ledger 'unverified' -> gate 'flagged'.
2. Attributed + judge ACCEPT -> SUPPORTED row (paraphrase_judge) [B1b preserved].
3. UNATTRIBUTED (H3 matches no consulted case) + would-reject -> drop, NO FAIL
   (the false-positive guard).
4. Attributed + over-budget -> unverified FAIL row.
5. Attributed + transient judge error -> drop, no row.

Refs ADR 0018 D2/D3, P1-B1c.
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
from app.models.research import ResearchClusterMetadata, ResearchOpinionMetadata
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

_OPINION_TEXT = (
    "The court considered the duty of good faith. It held that every contract "
    "carries an implied covenant of good faith and fair dealing between parties."
)
# Paraphrase (not verbatim) so the verbatim loop produces nothing.
_PASSAGE = "the court recognized an implied covenant of good faith in all contracts"
_CASE_NAME = "Smith v. Acme Corp."


def _caselaw_source(cluster_id: int) -> ToolSourceRecord:
    return ToolSourceRecord(
        source_kind="caselaw",
        label=_CASE_NAME,
        subtitle=None,
        url=None,
        external_ref=str(cluster_id),
        provider="courtlistener",
        tool="get_cluster",
    )


def _attributed_answer() -> str:
    return f"### {_CASE_NAME}, N.Y., 2001 (1 N.Y. 1)\n\n**Relevant passage:**\n> {_PASSAGE}\n"


def _judge_completion(verdict_json: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-fail-test",
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
    def __init__(self, verdict_json: str) -> None:
        self._verdict = verdict_json
        self.calls = 0

    async def chat_completion(
        self, request: ChatCompletionRequest, *, request_id: str | None = None
    ) -> ChatCompletionResponse:
        self.calls += 1
        return _judge_completion(self._verdict)


class _ErroringGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_completion(
        self, request: ChatCompletionRequest, *, request_id: str | None = None
    ) -> ChatCompletionResponse:
        self.calls += 1
        raise RuntimeError("transient gateway failure")


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession):
    user = User(
        email=f"fail-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="member"
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="fail-chat")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="passage")
    db_session.add(msg)
    await db_session.flush()
    opinion_id, cluster_id = 9001, 901
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=opinion_id,
            cluster_id=cluster_id,
            text_field_used="plain_text",
            storage_path=f"courtlistener/opinions/by-cluster/{cluster_id}/{opinion_id}",
            char_length=len(_OPINION_TEXT),
        )
    )
    db_session.add(
        ResearchClusterMetadata(
            cluster_id=cluster_id, case_name=_CASE_NAME, court="N.Y.", date_filed="2001-01-01"
        )
    )
    await db_session.flush()
    return msg.id, opinion_id, cluster_id


async def _loader(db: AsyncSession, opinion_id: int) -> str:
    return _OPINION_TEXT


async def _rows(db_session: AsyncSession, message_id: uuid.UUID) -> list[MessageCaselawCitation]:
    return list(
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


@pytest.mark.asyncio
async def test_attributed_reject_writes_fail_row_and_flags(
    db_session: AsyncSession, seeded
) -> None:
    message_id, opinion_id, cluster_id = seeded
    gw = _FakeGateway(json.dumps({"verdict": "no"}))
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=_attributed_answer(),
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 1
    rows = await _rows(db_session, message_id)
    assert len(rows) == 1
    assert rows[0].verified is False
    assert rows[0].verification_method is None
    assert rows[0].opinion_id == opinion_id
    assert rows[0].source_offset_end == len(_PASSAGE)
    await assemble_ledger_entries(db_session, message_id=message_id)
    await compute_and_record_gate(db_session, message_id=message_id)
    gate = (
        await db_session.execute(
            select(WorkProductFiduciaryGate).where(
                WorkProductFiduciaryGate.message_id == message_id
            )
        )
    ).scalar_one()
    assert gate.gate_status == "flagged"


@pytest.mark.asyncio
async def test_attributed_accept_writes_supported_row(db_session: AsyncSession, seeded) -> None:
    message_id, _opinion_id, cluster_id = seeded
    gw = _FakeGateway(json.dumps({"verdict": "yes", "confidence": "high"}))
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=_attributed_answer(),
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 1
    rows = await _rows(db_session, message_id)
    assert rows[0].verified is True
    assert rows[0].verification_method == "paraphrase_judge"


@pytest.mark.asyncio
async def test_unattributed_reject_drops_no_fail(db_session: AsyncSession, seeded) -> None:
    message_id, _opinion_id, cluster_id = seeded
    # H3 names a DIFFERENT case than the consulted cluster -> no attribution.
    answer = "### Totally Different Case, N.Y., 1999\n\n**Relevant passage:**\n> " + _PASSAGE + "\n"
    gw = _FakeGateway(json.dumps({"verdict": "no"}))
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=answer,
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 0
    assert await _rows(db_session, message_id) == []


@pytest.mark.asyncio
async def test_attributed_over_budget_writes_unverified_fail(
    db_session: AsyncSession, seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.citation.caselaw as caselaw_mod

    monkeypatch.setattr(caselaw_mod, "CASE_CONTENT_JUDGE_BUDGET_USD", Decimal("0"))
    message_id, opinion_id, cluster_id = seeded
    gw = _FakeGateway(json.dumps({"verdict": "yes", "confidence": "high"}))
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=_attributed_answer(),
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 1
    rows = await _rows(db_session, message_id)
    assert rows[0].verified is False
    assert rows[0].verification_method is None
    assert rows[0].opinion_id == opinion_id
    assert gw.calls == 0  # over-budget -> never judged


@pytest.mark.asyncio
async def test_attributed_transient_error_drops(db_session: AsyncSession, seeded) -> None:
    message_id, _opinion_id, cluster_id = seeded
    gw = _ErroringGateway()
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=_attributed_answer(),
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 0
    assert await _rows(db_session, message_id) == []
    assert gw.calls >= 1


@pytest.mark.asyncio
async def test_attributed_yes_without_confidence_drops(db_session: AsyncSession, seeded) -> None:
    """A 'yes' verdict without a confidence field is non-substantive -> drop, no row.

    _parse_judge_response returns _MISS for {"verdict": "yes"} with no confidence.
    That MISS must NOT set saw_reject=True; only an explicit "no" may do that.
    """
    message_id, _opinion_id, cluster_id = seeded
    # verdict "yes" but no confidence field -> _parse_judge_response -> _MISS
    gw = _FakeGateway(json.dumps({"verdict": "yes"}))
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=_attributed_answer(),
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 0, "a yes-without-confidence should drop, not write a FAIL row"
    assert await _rows(db_session, message_id) == []


@pytest.mark.asyncio
async def test_attributed_nonjson_output_drops(db_session: AsyncSession, seeded) -> None:
    """Truncated / non-JSON judge output is non-substantive -> drop, no row.

    The judge caps at max_tokens=400; a verbose justification can truncate the
    JSON. That non-JSON body must NOT set saw_reject=True.
    """
    message_id, _opinion_id, cluster_id = seeded
    # plain prose, not JSON -> _parse_judge_response -> _MISS
    gw = _FakeGateway("the opinion does support this, frankly")
    n = await verify_and_persist_caselaw_citations(
        db_session,
        message_id=message_id,
        assistant_text=_attributed_answer(),
        tool_sources=[_caselaw_source(cluster_id)],
        load_opinion_text=_loader,
        gateway=gw,
        judge_model="fast",
    )
    assert n == 0, "non-JSON judge output should drop, not write a FAIL row"
    assert await _rows(db_session, message_id) == []
