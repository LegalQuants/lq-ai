"""Refusal accounting stays distinct from argument and audit-storage errors."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.guard import _handle_emit_artifact
from app.autonomous.nodes import make_analysis_node
from app.autonomous.state import AutonomousSessionState
from app.models.autonomous import AutonomousSession
from tests.autonomous.conftest import _CHUNK_TEXT_DEFAULT, KbOneFile
from tests.autonomous.test_agentic_loop import _audit_rows, _ScriptedGateway


@pytest.mark.parametrize("mode", ["query", "file", "since"])
async def test_repeated_denials_and_validation_error_have_one_closing_row_each(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
    kb_with_one_indexed_file: KbOneFile,
    mode: str,
) -> None:
    session, kb = seeded_matter_session, kb_with_one_indexed_file
    assert session.user_id != kb.owner_id
    private_query = "PRIVATE_QUERY_494_REPEATED"
    args_by_mode: dict[str, dict[str, Any]] = {
        "query": {"kb_id": str(kb.kb_id), "query": private_query},
        "file": {"file_id": str(kb.file_id)},
        "since": {"kb_id": str(kb.kb_id), "since": "2026-01-01T00:00:00Z"},
    }
    refusal = {"next_intent": "retrieve_chunks", "args": args_by_mode[mode], "rationale": "x"}
    gateway = _ScriptedGateway(
        [
            refusal,
            refusal,
            {"next_intent": "retrieve_chunks", "args": {"top_k": -1}, "rationale": "x"},
            {"done": True, "rationale": "done"},
        ]
    )
    state: AutonomousSessionState = {
        "session_id": str(session.id),
        "query": "Research the test agreement",
        "retrieved_chunks": [],
    }
    result = await make_analysis_node(db_session, gateway)(state)
    assert result["analysis_content"] is not None
    assert result["analysis_plan_trace"]["steps"] == 3
    assert not result["analysis_evidence"]
    rows = await _audit_rows(db_session, str(session.id))
    retrieval_details = [
        r.details for r in rows if r.details and r.details.get("tool") == "retrieve_chunks"
    ]
    assert sorted(d["outcome"] for d in retrieval_details) == [
        "error",
        "ownership_denied",
        "ownership_denied",
        "started",
        "started",
    ]
    assert [d for d in retrieval_details if d["outcome"] == "error"] == [
        {"tool": "retrieve_chunks", "outcome": "error", "error_type": "ValueError"}
    ]
    assert [d for d in retrieval_details if d["outcome"] == "ownership_denied"] == [
        {"tool": "retrieve_chunks", "outcome": "ownership_denied"}
    ] * 2
    audit_text = json.dumps([r.details for r in rows])
    prompt_text = "\n".join(
        m.content
        for req in gateway.captured_requests
        for m in req.messages
        if isinstance(m.content, str)
    )
    assert prompt_text.count("retrieve_chunks → failed (ValueError)") >= 3
    for private_text in (private_query, _CHUNK_TEXT_DEFAULT):
        assert private_text not in audit_text
        assert private_text not in prompt_text


async def test_clean_denial_audit_error_keeps_generic_failure_logging(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
    kb_with_one_indexed_file: KbOneFile,
) -> None:
    session, kb = seeded_matter_session, kb_with_one_indexed_file
    gateway = _ScriptedGateway(
        [
            {
                "next_intent": "retrieve_chunks",
                "args": {"kb_id": str(kb.kb_id), "query": "private"},
                "rationale": "x",
            },
            {"done": True, "rationale": "done"},
        ]
    )
    state: AutonomousSessionState = {
        "session_id": str(session.id),
        "query": "Research the test agreement",
        "retrieved_chunks": [],
    }
    with (
        patch(
            "app.autonomous.guard.audit_retrieval_ownership_denial",
            new=AsyncMock(side_effect=RuntimeError("audit unavailable")),
        ),
        patch(
            "app.autonomous.guard._handle_retrieve_chunks_query", new_callable=AsyncMock
        ) as retrieve,
    ):
        result = await make_analysis_node(db_session, gateway)(state)
        retrieve.assert_not_awaited()
    assert result["analysis_content"] is not None
    assert not result["analysis_evidence"]
    rows = await _audit_rows(db_session, str(session.id))
    closing = [
        r.details
        for r in rows
        if r.details
        and r.details.get("tool") == "retrieve_chunks"
        and r.details.get("outcome") != "started"
    ]
    assert closing == [
        {"tool": "retrieve_chunks", "outcome": "error", "error_type": "RuntimeError"}
    ]
    prompt_text = "\n".join(
        m.content
        for req in gateway.captured_requests
        for m in req.messages
        if isinstance(m.content, str)
    )
    assert "retrieve_chunks → failed (RuntimeError)" in prompt_text
    assert _CHUNK_TEXT_DEFAULT not in prompt_text
    assert "audit unavailable" not in json.dumps([r.details for r in rows])


async def test_artifact_ownership_refusal_does_not_become_retrieval_denial(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
    kb_with_one_indexed_file: KbOneFile,
) -> None:
    session, kb = seeded_matter_session, kb_with_one_indexed_file
    assert session.user_id != kb.owner_id
    session.params = {**(session.params or {}), "kb_id": str(kb.kb_id)}
    with patch("app.storage.upload_bytes", new_callable=AsyncMock) as upload:
        with pytest.raises(ValueError, match="not accessible") as refusal:
            await _handle_emit_artifact(
                {"artifact": {"name": "memo.md", "content": "private"}},
                db=db_session,
                session=session,
            )
        upload.assert_not_awaited()
    assert type(refusal.value) is ValueError
    rows = await _audit_rows(db_session, str(session.id))
    assert not [r for r in rows if r.details and r.details.get("outcome") == "ownership_denied"]
