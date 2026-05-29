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

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.nodes import make_analysis_node, make_intake_node
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
