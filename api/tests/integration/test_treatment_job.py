from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User
from app.workers import treatment_worker

pytestmark = pytest.mark.integration


class _FastGW:
    """Stub gateway whose judge-model fetch always returns 'fast' without I/O.

    Injected into the existing graph-only test so no real network call is made
    after Task 6 adds get_gateway_client() resolution to run_treatment_derivation.
    """

    async def get_citation_engine_judge_model(self, *, fallback: str = "fast") -> str:
        return fallback


@pytest.mark.asyncio
async def test_run_treatment_derivation_writes_row_and_links(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Prevent any outbound HTTP attempt after Task 6 wires in get_gateway_client().
    # The stub returns "fast" (the default) without hitting the network.
    monkeypatch.setattr(treatment_worker, "get_gateway_client", lambda: _FastGW())

    # Seed a turn with a caselaw citation + ledger entry (as in Task 3's fixture).
    user = User(email=f"j-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="j")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x")
    db_session.add(msg)
    await db_session.flush()
    cc = MessageCaselawCitation(
        message_id=msg.id,
        opinion_id=2812209,
        cluster_id=2812209,
        source_offset_start=0,
        source_offset_end=5,
        source_text="q",
        verified=True,
        verification_method="exact_match",
    )
    db_session.add(cc)
    await db_session.flush()
    entry = CitationLedgerEntry(
        chat_id=chat.id,
        message_id=msg.id,
        source_kind="caselaw",
        message_caselaw_citation_id=cc.id,
        verification_status="exact_match",
    )
    db_session.add(entry)
    await db_session.flush()

    # The job's _run helper takes an injected session + fetch so we can test it without Redis/arq.
    from app.workers.treatment_worker import run_treatment_derivation

    async def fake_fetch(opinion_id: int) -> dict:
        return {
            "cited_by_count": 7,
            "citing": [
                {
                    "cluster_id": 1,
                    "opinion_id": 2,
                    "case_name": "A",
                    "court": "ca9",
                    "date_filed": "2022-01-01",
                }
            ],
        }

    linked = await run_treatment_derivation(db_session, message_id=msg.id, fetch_citing=fake_fetch)
    assert linked == 1
    row = (
        await db_session.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == 2812209)
        )
    ).scalar_one()
    assert row.cited_by_count == 7
    await db_session.refresh(entry)
    assert entry.treatment_id == row.id


@pytest.mark.asyncio
async def test_run_resolves_gateway_and_passes_it(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a gateway is injected and its judge-model fetch succeeds, derive is
    called with that gateway instance and the returned model name."""
    captured: dict[str, Any] = {}

    async def fake_derive(
        db: Any,
        *,
        message_id: Any,
        now: Any,
        fetch_citing: Any = None,
        gateway: Any = None,
        judge_model: str = "fast",
    ) -> int:
        captured["gateway"] = gateway
        captured["judge_model"] = judge_model
        return 0

    monkeypatch.setattr(treatment_worker, "derive_treatment_for_message", fake_derive)

    class GW:
        async def get_citation_engine_judge_model(self, *, fallback: str = "fast") -> str:
            return "balanced"

    gw = GW()
    await treatment_worker.run_treatment_derivation(
        db_session,
        message_id=uuid.uuid4(),
        gateway=gw,  # type: ignore[arg-type]
    )
    assert captured["gateway"] is gw
    assert captured["judge_model"] == "balanced"


@pytest.mark.asyncio
async def test_run_degrades_to_graph_only_on_gateway_failure(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the gateway's judge-model fetch raises, the worker degrades to
    graph-only (gateway=None passed to derive)."""
    captured: dict[str, Any] = {}

    async def fake_derive(
        db: Any,
        *,
        message_id: Any,
        now: Any,
        fetch_citing: Any = None,
        gateway: Any = None,
        judge_model: str = "fast",
    ) -> int:
        captured["gateway"] = gateway
        return 0

    monkeypatch.setattr(treatment_worker, "derive_treatment_for_message", fake_derive)

    class BadGW:
        async def get_citation_engine_judge_model(self, *, fallback: str = "fast") -> str:
            raise RuntimeError("no gateway config")

    await treatment_worker.run_treatment_derivation(
        db_session,
        message_id=uuid.uuid4(),
        gateway=BadGW(),  # type: ignore[arg-type]
    )
    assert captured["gateway"] is None  # degraded to graph-only
