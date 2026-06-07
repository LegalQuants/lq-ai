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

import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.nodes import (
    make_analysis_node,
    make_delivery_node,
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
# Donna ask #8 — drafting_node artifact dispatch (opt-in)
# ---------------------------------------------------------------------------


def _tool_started_calls(rows: list[Any], tool: str) -> int:
    """Count the chokepoint's ``started`` audit rows for one tool intent."""
    return sum(
        1
        for r in rows
        if r.action == "autonomous_session.tool_call"
        and (r.details or {}).get("tool") == tool
        and (r.details or {}).get("outcome") == "started"
    )


def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Recording stub for ``app.storage.upload_bytes`` (the emit_artifact
    handler imports it locally at call time — the test_emit_artifact idiom)."""
    calls: list[dict[str, Any]] = []

    async def _fake_upload(*, storage_path: str, body: bytes, content_type: str) -> None:
        calls.append({"storage_path": storage_path, "body": body, "content_type": content_type})

    monkeypatch.setattr("app.storage.upload_bytes", _fake_upload)
    return calls


def _stub_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op stub for ``app.workers.queue.enqueue_embed_job`` (no Redis)."""

    async def _fake_enqueue(file_id: Any) -> bool:
        return True

    monkeypatch.setattr("app.workers.queue.enqueue_embed_job", _fake_enqueue)


def _structured_content(artifacts: list[dict[str, Any]]) -> str:
    """A well-formed analysis response carrying only an artifacts array."""
    return (
        "```json\n"
        + json.dumps(
            {
                "findings": [],
                "suggested_memories": [],
                "suggested_precedents": [],
                "privilege_concerns": [],
                "scope_concerns": [],
                "artifacts": artifacts,
            }
        )
        + "\n```"
    )


_TWO_ARTIFACTS = [
    {"name": "review-memo.md", "content_md": "# Memo\n\nFirst document body."},
    {"name": "summary.md", "content_md": "# Summary\n\nSecond document body."},
]


async def _make_drafting_session_with_kb(
    db_session: AsyncSession, *, emit_artifacts: bool
) -> AutonomousSession:
    """Running session at the drafting boundary with a real target KB.

    Builds on the conftest helpers (the test_emit_artifact import
    precedent) so the artifact persistence path has a real KB row to
    attach into.
    """
    from tests.autonomous.conftest import _make_kb, _make_optedin_user, _make_running_session

    user = await _make_optedin_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    params: dict[str, Any] = {"kb_id": str(kb.id)}
    if emit_artifacts:
        params["emit_artifacts"] = True
    return await _make_running_session(db_session, user=user, trigger_kind="watch", params=params)


@pytest.mark.integration
async def test_drafting_dispatches_artifacts_when_opted_in(
    db_session: AsyncSession,
    mock_gateway: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag on + 2 parsed artifacts → 2 emit_artifact chokepoint dispatches,
    2 persisted rows, artifacts_count == 2, no extra findings."""
    from sqlalchemy import select

    from app.models.autonomous import AutonomousArtifact

    _stub_storage(monkeypatch)
    _stub_embed(monkeypatch)
    session = await _make_drafting_session_with_kb(db_session, emit_artifacts=True)

    state: AutonomousSessionState = {
        "session_id": str(session.id),
        "analysis_content": _structured_content(_TWO_ARTIFACTS),
        "analysis_outcome": "success",
    }
    node = make_drafting_node(db_session, mock_gateway)
    result = await node(state)

    rows = await _autonomous_audit_rows(db_session, str(session.id))
    assert _tool_started_calls(rows, "emit_artifact") == 2
    assert result["artifacts_count"] == 2
    assert result["findings_count"] == 0
    artifact_rows = (
        (
            await db_session.execute(
                select(AutonomousArtifact).where(AutonomousArtifact.session_id == session.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(artifact_rows) == 2


@pytest.mark.integration
async def test_drafting_ignores_artifacts_when_flag_off(
    db_session: AsyncSession,
    mock_gateway: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag off + artifacts present in the parsed output → zero dispatches,
    artifacts_count == 0, no explanatory finding (defense-in-depth: the
    model was never asked for artifacts, so an unasked-for emission is
    ignored entirely)."""
    from sqlalchemy import select

    from app.models.autonomous import AutonomousArtifact

    upload_calls = _stub_storage(monkeypatch)
    _stub_embed(monkeypatch)
    session = await _make_drafting_session_with_kb(db_session, emit_artifacts=False)

    state: AutonomousSessionState = {
        "session_id": str(session.id),
        "analysis_content": _structured_content(_TWO_ARTIFACTS),
        "analysis_outcome": "success",
    }
    node = make_drafting_node(db_session, mock_gateway)
    result = await node(state)

    rows = await _autonomous_audit_rows(db_session, str(session.id))
    assert _tool_started_calls(rows, "emit_artifact") == 0
    assert result["artifacts_count"] == 0
    assert result["findings_count"] == 0
    assert upload_calls == []
    artifact_rows = (
        (
            await db_session.execute(
                select(AutonomousArtifact).where(AutonomousArtifact.session_id == session.id)
            )
        )
        .scalars()
        .all()
    )
    assert artifact_rows == []


@pytest.mark.integration
async def test_drafting_no_target_kb_emits_one_info_finding_and_stops(
    db_session: AsyncSession,
    running_session_at_drafting: AutonomousSession,
    mock_gateway: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """no_target_kb skip → exactly ONE info finding (even with 2 artifacts)
    and the loop stops after the first attempt — every remaining artifact
    would skip for the same reason."""
    upload_calls = _stub_storage(monkeypatch)
    _stub_embed(monkeypatch)
    # running_session_at_drafting has params={} → opt in without a kb_id.
    running_session_at_drafting.params = {"emit_artifacts": True}
    await db_session.flush()

    state: AutonomousSessionState = {
        "session_id": str(running_session_at_drafting.id),
        "analysis_content": _structured_content(_TWO_ARTIFACTS),
        "analysis_outcome": "success",
    }
    node = make_drafting_node(db_session, mock_gateway)
    result = await node(state)

    rows = await _autonomous_audit_rows(db_session, str(running_session_at_drafting.id))
    # Loop stopped after the FIRST skip — the second artifact never dispatched.
    assert _tool_started_calls(rows, "emit_artifact") == 1
    assert result["artifacts_count"] == 0
    # Exactly ONE explanatory info finding, counted like any other finding.
    assert result["findings_count"] == 1
    assert result["findings"][0]["title"] == ("Artifact not persisted — no target knowledge base")
    assert result["findings"][0]["severity"] == "info"
    assert upload_calls == []


@pytest.mark.integration
async def test_drafting_storage_error_emits_warn_and_continues(
    db_session: AsyncSession,
    mock_gateway: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A storage failure on one artifact → ONE warn finding for it, the
    loop continues, and artifacts_count counts only the persisted one."""
    _stub_embed(monkeypatch)
    calls = {"n": 0}

    async def _flaky_upload(*, storage_path: str, body: bytes, content_type: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("minio is down")

    monkeypatch.setattr("app.storage.upload_bytes", _flaky_upload)
    session = await _make_drafting_session_with_kb(db_session, emit_artifacts=True)

    state: AutonomousSessionState = {
        "session_id": str(session.id),
        "analysis_content": _structured_content(_TWO_ARTIFACTS),
        "analysis_outcome": "success",
    }
    node = make_drafting_node(db_session, mock_gateway)
    result = await node(state)

    rows = await _autonomous_audit_rows(db_session, str(session.id))
    # Both artifacts were attempted (the loop continued past the failure).
    assert _tool_started_calls(rows, "emit_artifact") == 2
    # Only the second persisted.
    assert result["artifacts_count"] == 1
    # ONE warn finding for the failed artifact, naming it + the error.
    assert result["findings_count"] == 1
    finding = result["findings"][0]
    assert finding["title"] == "Artifact persistence failed at storage"
    assert finding["severity"] == "warn"
    assert "review-memo.md" in finding["summary"]
    assert "RuntimeError" in finding["summary"]


# ---------------------------------------------------------------------------
# Donna ask #8 — delivery_node artifact_count in notify payload + audit
# ---------------------------------------------------------------------------


async def _delivery_notification_row(db_session: AsyncSession, session_id: Any) -> Any:
    from sqlalchemy import select

    from app.models.autonomous import AutonomousNotification

    return (
        await db_session.execute(
            select(AutonomousNotification).where(AutonomousNotification.session_id == session_id)
        )
    ).scalar_one()


async def _completed_audit_row(db_session: AsyncSession, session_id: str) -> Any:
    from sqlalchemy import select

    from app.models.audit import AuditLog

    return (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == "autonomous_session")
            .where(AuditLog.resource_id == session_id)
            .where(AuditLog.action == "autonomous_session.completed")
        )
    ).scalar_one()


@pytest.mark.integration
async def test_delivery_payload_and_body_carry_artifact_count(
    db_session: AsyncSession,
    running_session_at_delivery: AutonomousSession,
    mock_gateway: object,
) -> None:
    """artifacts_count > 0 → payload carries artifact_count, the body
    mentions the saved documents, and the completed audit row gains
    artifacts_count."""
    node = make_delivery_node(db_session, mock_gateway)
    state: AutonomousSessionState = {
        "session_id": str(running_session_at_delivery.id),
        "findings": [],
        "findings_count": 2,
        "artifacts_count": 3,
    }
    await node(state)

    note = await _delivery_notification_row(db_session, running_session_at_delivery.id)
    assert note.payload == {"finding_count": 2, "artifact_count": 3}
    assert "2 finding(s)" in note.body
    assert "3 document(s) saved to the knowledge base" in note.body

    audit = await _completed_audit_row(db_session, str(running_session_at_delivery.id))
    assert (audit.details or {}).get("artifacts_count") == 3
    assert (audit.details or {}).get("findings_count") == 2


@pytest.mark.integration
async def test_delivery_zero_artifacts_payload_honest_body_silent(
    db_session: AsyncSession,
    running_session_at_delivery: AutonomousSession,
    mock_gateway: object,
) -> None:
    """artifacts_count absent (pre-artifacts state shape) → payload still
    carries artifact_count == 0 (honest, distinguishes 'feature present,
    zero artifacts' from an old payload) but the body stays counts-only
    with no document mention."""
    node = make_delivery_node(db_session, mock_gateway)
    state: AutonomousSessionState = {
        "session_id": str(running_session_at_delivery.id),
        "findings": [],
        "findings_count": 1,
    }
    await node(state)

    note = await _delivery_notification_row(db_session, running_session_at_delivery.id)
    assert note.payload == {"finding_count": 1, "artifact_count": 0}
    assert "document" not in note.body
    assert note.body == "Session completed with 1 finding(s)."

    audit = await _completed_audit_row(db_session, str(running_session_at_delivery.id))
    assert (audit.details or {}).get("artifacts_count") == 0


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
