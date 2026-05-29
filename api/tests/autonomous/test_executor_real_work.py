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
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.nodes import make_intake_node
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
