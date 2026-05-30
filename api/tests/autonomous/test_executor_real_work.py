"""End-to-end-ish tests of the wired autonomous executor nodes (M4 real work).

Each test exercises one node's wiring against a mocked gateway. Full-session
integration is covered in Tasks 13 + 16.

Tasks 9 + 10 cover the intake-node dispatch:

* Watch path — ``params["file_id"]`` present: ``retrieve_chunks`` is
  called with the file_id scope (mode 2) so the arriving document's
  chunks reach analysis.
* Schedule path — ``params["kb_id"]`` + ``params["since"]``:
  ``retrieve_chunks`` is called with the since scope (mode 3) so
  only docs attached after ``last_run_at`` come back.
* Schedule first-tick — ``params["kb_id"]`` with no ``since``: intake
  skips retrieval and sets ``first_tick_no_baseline=True``.
* No target — empty ``params``: intake stays empty without error.

Task 11 covers the analysis-node dispatch:

* Happy path — session has a ``skill_ref`` and intake produced chunks:
  analysis assembles messages via prompts.assemble_analysis_messages,
  picks ``ToolIntent.run_skill``, and routes ONE call through the
  chokepoint. The mocked gateway's structured-output content lands in
  ``state["analysis_content"]`` and the outcome is ``"success"``.
* First-tick — ``state["first_tick_no_baseline"] is True``: analysis
  returns early WITHOUT calling the gateway.
* No-target — session params carry neither ``skill_ref`` nor
  ``playbook_id``: analysis returns early WITHOUT calling the gateway.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.nodes import (
    make_analysis_node,
    make_drafting_node,
    make_ethics_review_node,
    make_intake_node,
)
from app.autonomous.state import AutonomousSessionState
from app.models.autonomous import AutonomousSession


@pytest.mark.integration
async def test_intake_watch_path_scopes_retrieve_chunks_by_file_id(
    db_session: AsyncSession,
    running_watch_session: AutonomousSession,
    mock_gateway: object,
) -> None:
    """Watch session (kb_id+file_id in params): intake calls retrieve_chunks
    scoped to the file_id (mode 2) and the watch-fixture's indexed chunk
    appears in the returned list."""
    node = make_intake_node(db_session, mock_gateway)
    state: AutonomousSessionState = {
        "session_id": str(running_watch_session.id),
    }
    result = await node(state)
    assert result.get("error") is None
    assert "retrieved_chunks" in result
    chunks = result["retrieved_chunks"]
    assert isinstance(chunks, list)
    # The watch fixture attaches exactly one chunk to the file_id,
    # so mode 2 should return that single chunk.
    assert len(chunks) == 1
    # No first_tick marker on the watch path.
    assert not result.get("first_tick_no_baseline", False)


@pytest.mark.integration
async def test_intake_schedule_path_scopes_retrieve_chunks_by_since(
    db_session: AsyncSession,
    running_schedule_session_with_since: AutonomousSession,
    mock_gateway: object,
) -> None:
    """Schedule session (kb_id+since in params): intake calls retrieve_chunks
    with the since scope (mode 3) so only new-since-last-run docs come back —
    exactly one chunk (the "new" file), not the old file's chunk."""
    node = make_intake_node(db_session, mock_gateway)
    state: AutonomousSessionState = {
        "session_id": str(running_schedule_session_with_since.id),
    }
    result = await node(state)
    assert result.get("error") is None
    assert "retrieved_chunks" in result
    chunks = result["retrieved_chunks"]
    assert isinstance(chunks, list)
    # Only the new file's chunk is past the since cutoff (5min ago);
    # the old file is backdated 1 hour and should be filtered out.
    assert len(chunks) == 1
    assert "Fresh contract" in chunks[0]["content"]
    assert not result.get("first_tick_no_baseline", False)


@pytest.mark.integration
async def test_intake_schedule_first_tick_empty_since_sets_no_baseline(
    db_session: AsyncSession,
    running_schedule_session_first_tick: AutonomousSession,
    mock_gateway: object,
) -> None:
    """Schedule session with since=None (first cron tick): no docs retrieved;
    intake sets ``first_tick_no_baseline=True``."""
    node = make_intake_node(db_session, mock_gateway)
    state: AutonomousSessionState = {
        "session_id": str(running_schedule_session_first_tick.id),
    }
    result = await node(state)
    assert result.get("error") is None
    assert result.get("retrieved_chunks") == []
    assert result.get("first_tick_no_baseline") is True


@pytest.mark.integration
async def test_intake_no_target_returns_empty_chunks(
    db_session: AsyncSession,
    running_session_without_target: AutonomousSession,
    mock_gateway: object,
) -> None:
    """Session with no target (no kb_id/file_id/since): empty chunks, no
    first-tick marker, no error — delivery will still finish."""
    node = make_intake_node(db_session, mock_gateway)
    state: AutonomousSessionState = {
        "session_id": str(running_session_without_target.id),
    }
    result = await node(state)
    assert result.get("error") is None
    assert result.get("retrieved_chunks") == []
    assert not result.get("first_tick_no_baseline", False)


# ---------------------------------------------------------------------------
# Task 11 — analysis_node guarded run_skill / run_playbook dispatch
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_analysis_calls_run_skill_through_chokepoint(
    db_session: AsyncSession,
    running_watch_session_at_analysis: AutonomousSession,
    mock_gateway_structured_response: object,
) -> None:
    """analysis_node assembles messages and makes one guarded run_skill call;
    the structured-output content is stored in state."""
    node = make_analysis_node(db_session, mock_gateway_structured_response)
    state: AutonomousSessionState = {
        "session_id": str(running_watch_session_at_analysis.id),
        "retrieved_chunks": [
            {
                "chunk_id": "c1",
                "document_id": "d1",
                "file_id": "f1",
                "file_name": "test.txt",
                "content": "test chunk",
                "char_offset_start": 0,
                "char_offset_end": 10,
                "hybrid_score": None,
            }
        ],
    }
    result = await node(state)
    assert mock_gateway_structured_response.chat_completion.await_count == 1
    assert "analysis_content" in result
    assert result.get("analysis_outcome") == "success"
    # The mocked gateway returned a JSON-shaped fenced string.
    assert "findings" in (result["analysis_content"] or "")


@pytest.mark.integration
async def test_analysis_first_tick_skips_gateway(
    db_session: AsyncSession,
    running_schedule_session_first_tick: AutonomousSession,
    mock_gateway: object,
) -> None:
    """If state carries first_tick_no_baseline, analysis_node returns early
    without calling the gateway."""
    node = make_analysis_node(db_session, mock_gateway)
    state: AutonomousSessionState = {
        "session_id": str(running_schedule_session_first_tick.id),
        "retrieved_chunks": [],
        "first_tick_no_baseline": True,
    }
    result = await node(state)
    assert mock_gateway.chat_completion.await_count == 0
    assert result.get("analysis_content") is None
    assert result.get("first_tick_no_baseline") is True


@pytest.mark.integration
async def test_analysis_no_target_skips_gateway(
    db_session: AsyncSession,
    running_session_without_target: AutonomousSession,
    mock_gateway: object,
) -> None:
    """A session with no skill_ref + no playbook_id returns early with
    analysis_content=None (no gateway call)."""
    node = make_analysis_node(db_session, mock_gateway)
    state: AutonomousSessionState = {
        "session_id": str(running_session_without_target.id),
        "retrieved_chunks": [],
    }
    result = await node(state)
    assert mock_gateway.chat_completion.await_count == 0
    assert result.get("analysis_content") is None


# ---------------------------------------------------------------------------
# Task 12 — drafting_node structured-output parse + per-item guarded dispatch
# ---------------------------------------------------------------------------


def _started_tool_calls(rows: list[Any]) -> int:
    """Count the chokepoint's per-call ``started`` audit rows.

    The chokepoint writes one ``tool_call`` row with ``outcome="started"``
    per guarded call (plus a second row with the terminal outcome). Counting
    only the ``started`` rows yields the number of distinct guarded calls.
    """
    return sum(
        1
        for r in rows
        if r.action == "autonomous_session.tool_call"
        and (r.details or {}).get("outcome") == "started"
    )


async def _autonomous_audit_rows(db_session: AsyncSession, session_id: str) -> list[Any]:
    from sqlalchemy import select

    from app.models.audit import AuditLog

    return list(
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.resource_type == "autonomous_session")
                .where(AuditLog.resource_id == session_id)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.integration
async def test_drafting_dispatches_per_item_guarded_calls(
    db_session: AsyncSession,
    running_session_at_drafting: AutonomousSession,
    mock_gateway: object,
) -> None:
    """drafting_node parses analysis_content (well-formed JSON) and dispatches
    each finding/memory/precedent as its own guarded call."""
    state: AutonomousSessionState = {
        "session_id": str(running_session_at_drafting.id),
        "analysis_content": (
            "```json\n{"
            '"findings": [{"title": "F1", "summary": "S1", "severity": "info", '
            '"source_chunk_ids": []}, '
            '{"title": "F2", "summary": "S2", "severity": "warn", "source_chunk_ids": []}], '
            '"suggested_memories": [{"category": "preference", "content": "C", '
            '"rationale": "R"}], '
            '"suggested_precedents": [{"pattern_kind": "clause", "summary": "P"}], '
            '"privilege_concerns": [], "scope_concerns": []}\n```'
        ),
        "analysis_outcome": "success",
    }
    node = make_drafting_node(db_session, mock_gateway)
    result = await node(state)

    rows = await _autonomous_audit_rows(db_session, str(running_session_at_drafting.id))
    # Two findings + one memory + one precedent = 4 distinct guarded calls.
    assert _started_tool_calls(rows) >= 4
    assert result["findings_count"] == 2
    # The structured path returns the emitted finding dicts in ``findings``
    # (memories/precedents excluded) and ``findings_count`` is its length —
    # the delivery node reads ``state["findings"]`` so both must be coherent.
    assert isinstance(result["findings"], list)
    assert len(result["findings"]) == result["findings_count"] == 2


@pytest.mark.integration
async def test_drafting_unstructured_emits_single_fallback_finding(
    db_session: AsyncSession,
    running_session_at_drafting: AutonomousSession,
    mock_gateway: object,
) -> None:
    """Plain prose (no JSON) → exactly ONE emit_finding carrying the raw
    content as the fallback, findings_count == 1."""
    state: AutonomousSessionState = {
        "session_id": str(running_session_at_drafting.id),
        "analysis_content": "Just some prose with no structured JSON block at all.",
        "analysis_outcome": "success",
    }
    node = make_drafting_node(db_session, mock_gateway)
    result = await node(state)

    rows = await _autonomous_audit_rows(db_session, str(running_session_at_drafting.id))
    assert _started_tool_calls(rows) == 1
    assert result["findings_count"] == 1


@pytest.mark.integration
async def test_drafting_gateway_error_emits_single_explanatory_finding(
    db_session: AsyncSession,
    running_session_at_drafting: AutonomousSession,
    mock_gateway: object,
) -> None:
    """analysis_outcome=gateway_error → exactly ONE emit_finding (severity
    warn), findings_count == 1, session continues honestly."""
    state: AutonomousSessionState = {
        "session_id": str(running_session_at_drafting.id),
        "analysis_content": None,
        "analysis_outcome": "gateway_error",
    }
    node = make_drafting_node(db_session, mock_gateway)
    result = await node(state)

    rows = await _autonomous_audit_rows(db_session, str(running_session_at_drafting.id))
    assert _started_tool_calls(rows) == 1
    assert result["findings_count"] == 1


# ---------------------------------------------------------------------------
# Task 14 — ethics_review_node privilege/scope concerns finding
# ---------------------------------------------------------------------------


def _emit_finding_success_rows(rows: list[Any]) -> list[Any]:
    """Terminal-success ``emit_finding`` tool_call rows."""
    return [
        r
        for r in rows
        if r.action == "autonomous_session.tool_call"
        and (r.details or {}).get("tool") == "emit_finding"
        and (r.details or {}).get("outcome") == "success"
    ]


@pytest.mark.integration
async def test_ethics_review_emits_privilege_and_scope_finding(
    db_session: AsyncSession,
    running_session_at_ethics: AutonomousSession,
    mock_gateway: object,
) -> None:
    """ethics_review_node emits ONE finding summarizing privilege/scope concerns."""
    state: AutonomousSessionState = {
        "session_id": str(running_session_at_ethics.id),
        "privilege_concerns": ["mention of attorney-client communication on p.2"],
        "scope_concerns": [],
    }
    node = make_ethics_review_node(db_session, mock_gateway)
    await node(state)

    rows = await _autonomous_audit_rows(db_session, str(running_session_at_ethics.id))
    emit_findings = _emit_finding_success_rows(rows)
    assert len(emit_findings) >= 1


@pytest.mark.integration
async def test_ethics_review_empty_concerns_emits_single_finding(
    db_session: AsyncSession,
    running_session_at_ethics: AutonomousSession,
    mock_gateway: object,
) -> None:
    """Both concern lists empty → still emits exactly ONE 'no concerns' finding."""
    state: AutonomousSessionState = {
        "session_id": str(running_session_at_ethics.id),
        "privilege_concerns": [],
        "scope_concerns": [],
    }
    node = make_ethics_review_node(db_session, mock_gateway)
    await node(state)

    rows = await _autonomous_audit_rows(db_session, str(running_session_at_ethics.id))
    emit_findings = _emit_finding_success_rows(rows)
    assert len(emit_findings) == 1
