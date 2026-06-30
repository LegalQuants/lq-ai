"""Integration tests for the governed analysis-phase loop (WS-D PR1, Task 5).

Tests the plan→act→observe→replan loop inside ``make_analysis_node`` and
pins the five load-bearing invariants from the task brief CONTROLLER ADDENDUM.

Gateway / planner are stubbed in-test — do NOT pass ``-m provider``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.nodes import make_analysis_node
from app.autonomous.state import AutonomousSessionState
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# ---------------------------------------------------------------------------
# Scripted gateway stub
# ---------------------------------------------------------------------------


def _resp(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
    )


_SYNTHESIS_JSON = (
    '```json\n{"findings": [{"title": "t", "summary": "s", '
    '"severity": "info", "source_chunk_ids": []}], "suggested_memories": [], '
    '"suggested_precedents": [], "privilege_concerns": [], "scope_concerns": []}\n```'
)


class _ScriptedGateway:
    """Minimal gateway stub that distinguishes planner from synthesis calls.

    Planner calls have 'research planner' in ``messages[0].content`` (the
    system prompt built by ``build_planner_messages``).  Synthesis / single
    inference calls don't, and receive the fixed structured-JSON stub.

    ``list_tool_providers`` returns an empty list so ``resolve_available_sources``
    (called once per loop in ``_run_analysis_loop``) sees no configured
    providers and lists no sources in the planner prompt.  This is correct
    for unit tests that do not exercise ``retrieve_authority`` — sources only
    appear in the prompt when a matching provider is gateway-configured.
    """

    def __init__(self, planner_script: list[Any]) -> None:
        self.planner_script = list(planner_script)

    async def list_tool_providers(self) -> list[dict[str, Any]]:
        """No providers configured in the agentic-loop unit tests."""
        return []

    async def chat_completion(self, request: Any, *, request_id: object = None) -> SimpleNamespace:
        system = request.messages[0].content
        if "research planner" in system:
            return _resp(json.dumps(self.planner_script.pop(0)))
        # synthesis or single-call path → structured findings stub
        return _resp(_SYNTHESIS_JSON)


# ---------------------------------------------------------------------------
# Audit-row helpers (mirror the pattern in test_executor_real_work.py)
# ---------------------------------------------------------------------------


async def _audit_rows(db: AsyncSession, session_id: str) -> list[Any]:
    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.resource_type == "autonomous_session")
                .where(AuditLog.resource_id == session_id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _tool_started_calls(rows: list[Any], tool: str) -> int:
    """Count ``started`` audit rows for a specific tool intent."""
    return sum(
        1
        for r in rows
        if r.action == "autonomous_session.tool_call"
        and (r.details or {}).get("tool") == tool
        and (r.details or {}).get("outcome") == "started"
    )


# ---------------------------------------------------------------------------
# Invariant 1 — query-less session is byte-identical to today's behaviour
# ---------------------------------------------------------------------------


async def test_query_less_session_is_unchanged(
    db_session: AsyncSession,
    seeded_skill_session_no_query: AutonomousSession,
) -> None:
    """No ``state['query']`` → single ``run_skill`` path; no ``plan`` intent audited.

    Pins invariant #1: the query-less path must be behaviorally byte-identical
    to the pre-loop behaviour.  No ``analysis_plan_trace`` key in the return.
    """
    gw = _ScriptedGateway([])  # planner_script is never consulted
    node = make_analysis_node(db_session, gw)
    state: AutonomousSessionState = {
        "session_id": str(seeded_skill_session_no_query.id),
        "retrieved_chunks": [],
        # deliberately omit "query" — must take the single-call path
    }
    result = await node(state)

    # Single-call path: analysis_content present, outcome success
    assert "analysis_content" in result
    assert result.get("analysis_outcome") == "success"
    # No plan intent was dispatched (invariant #1)
    rows = await _audit_rows(db_session, str(seeded_skill_session_no_query.id))
    assert _tool_started_calls(rows, "plan") == 0
    # No loop trace key on the query-less path
    assert "analysis_plan_trace" not in result


# ---------------------------------------------------------------------------
# Invariant 2 — loop runs planner then done, synthesis always follows
# ---------------------------------------------------------------------------


async def test_loop_runs_planner_then_done_then_synthesis(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
    kb_with_one_indexed_file: Any,  # KbOneFile from conftest
) -> None:
    """Planner returns one retrieve_chunks action then done.

    Verifies: the action is dispatched through the chokepoint (audit row),
    the synthesis runs and produces parseable analysis_content, and the
    returned ``analysis_plan_trace`` carries the correct step count and
    halt_reason.

    ``retrieve_chunks`` (local, no HTTP) was chosen over ``retrieve_caselaw``
    (external, HTTP to gateway) so the action actually SUCCEEDS — giving a
    real observation assertion on chunk count.
    """
    kb_id = str(kb_with_one_indexed_file.kb_id)
    gw = _ScriptedGateway(
        [
            {
                "next_intent": "retrieve_chunks",
                "args": {"kb_id": kb_id, "query": "confidential"},
                "rationale": "gather clause context",
            },
            {"done": True, "rationale": "enough evidence"},
        ]
    )
    node = make_analysis_node(db_session, gw)
    state: AutonomousSessionState = {
        "session_id": str(seeded_matter_session.id),
        "query": "Is the assignment clause enforceable?",
        "retrieved_chunks": [],
    }
    result = await node(state)

    # Synthesis produced parseable analysis_content
    assert result.get("analysis_content") is not None
    assert "findings" in (result["analysis_content"] or "")

    # Trace: 1 action step, halt_reason=planner_done
    trace = result.get("analysis_plan_trace")
    assert trace is not None
    assert trace["steps"] == 1
    assert trace["halt_reason"] == "planner_done"
    assert isinstance(trace["decisions"], list)
    # decisions = [action entry, done entry]
    assert len(trace["decisions"]) == 2
    assert trace["decisions"][0]["intent"] == "retrieve_chunks"
    assert trace["decisions"][1]["intent"] == "done"

    # Audit: plan was issued twice (action step + done step); retrieve_chunks once
    rows = await _audit_rows(db_session, str(seeded_matter_session.id))
    assert _tool_started_calls(rows, "plan") >= 2
    assert _tool_started_calls(rows, "retrieve_chunks") == 1


# ---------------------------------------------------------------------------
# Invariant 2 + step cap — loop stops at max_analysis_steps, synthesis runs
# ---------------------------------------------------------------------------


async def test_step_cap_halts_and_still_synthesizes(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
) -> None:
    """Planner never says done → loop stops at ``max_analysis_steps``; synthesis
    always runs (partial-but-honest, never a crash).

    Uses ``retrieve_chunks`` with empty args so the action raises ``ValueError``
    immediately (no HTTP calls, deterministic failure) → caught per addendum §A.
    """
    # 20 action decisions; only 2 should be consumed with max_analysis_steps=2
    gw = _ScriptedGateway([{"next_intent": "retrieve_chunks", "args": {}, "rationale": "x"}] * 20)
    # Override cap via session params (node reads params["max_analysis_steps"])
    seeded_matter_session.params = {
        **(seeded_matter_session.params or {}),
        "max_analysis_steps": 2,
    }
    await db_session.flush()

    node = make_analysis_node(db_session, gw)
    state: AutonomousSessionState = {
        "session_id": str(seeded_matter_session.id),
        "query": "Is the assignment clause enforceable?",
        "retrieved_chunks": [],
    }
    result = await node(state)

    # Synthesis still ran (partial-but-honest)
    assert result.get("analysis_content") is not None

    trace = result.get("analysis_plan_trace")
    assert trace is not None
    assert trace["steps"] == 2
    assert trace["halt_reason"] == "step_cap"
    # Exactly 2 action entries in decisions (no "done" entry on step_cap path)
    assert len(trace["decisions"]) == 2
    assert all(d["intent"] == "retrieve_chunks" for d in trace["decisions"])

    # Audit: plan called twice, retrieve_chunks started twice (then caught)
    rows = await _audit_rows(db_session, str(seeded_matter_session.id))
    assert _tool_started_calls(rows, "retrieve_chunks") == 2


# ---------------------------------------------------------------------------
# Invariant 2 — unparseable planner stops loop, synthesis still runs
# ---------------------------------------------------------------------------


async def test_unparseable_planner_stops_loop_then_synthesizes(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
) -> None:
    """Planner returns garbage JSON → loop stops immediately; synthesis runs.

    ``halt_reason`` is ``"planner_unparseable"`` and no action intent is
    dispatched (only the plan call + the final synthesis call).
    """
    gw = _ScriptedGateway(["not json at all"])
    node = make_analysis_node(db_session, gw)
    state: AutonomousSessionState = {
        "session_id": str(seeded_matter_session.id),
        "query": "Is the assignment clause enforceable?",
        "retrieved_chunks": [],
    }
    result = await node(state)

    # Synthesis ran despite planner failure
    assert result.get("analysis_content") is not None

    trace = result.get("analysis_plan_trace")
    assert trace is not None
    assert trace["steps"] == 0
    assert trace["halt_reason"] == "planner_unparseable"
    # No action steps — decisions is empty
    assert trace["decisions"] == []

    # No action intent was dispatched (only plan + synthesis)
    rows = await _audit_rows(db_session, str(seeded_matter_session.id))
    assert _tool_started_calls(rows, "retrieve_chunks") == 0
    assert _tool_started_calls(rows, "retrieve_caselaw") == 0


# ---------------------------------------------------------------------------
# Invariant 5 (addendum §B) — bad planner arg is a non-fatal observation
# ---------------------------------------------------------------------------


async def test_action_error_is_nonfatal_observation(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
) -> None:
    """A bad planner arg that makes the handler raise is a non-fatal observation.

    ``retrieve_chunks`` with ``{}`` (no ``query``/``file_id``/``since``) raises
    ``ValueError``.  The node must NOT propagate the exception; the step is
    still counted in the trace; synthesis runs; ``halt_reason='planner_done'``.

    This pins the milestone's partial-but-honest-over-crash thesis.
    """
    gw = _ScriptedGateway(
        [
            {"next_intent": "retrieve_chunks", "args": {}, "rationale": "x"},
            {"done": True, "rationale": "enough evidence"},
        ]
    )
    node = make_analysis_node(db_session, gw)
    state: AutonomousSessionState = {
        "session_id": str(seeded_matter_session.id),
        "query": "Is the assignment clause enforceable?",
        "retrieved_chunks": [],
    }
    # Must not raise — invariant #5
    result = await node(state)

    # Synthesis ran (partial-but-honest over crash)
    assert result.get("analysis_content") is not None

    trace = result.get("analysis_plan_trace")
    assert trace is not None
    assert trace["steps"] == 1  # the failed step is still counted
    assert trace["halt_reason"] == "planner_done"

    # The action is recorded in decisions despite the failure
    action_decisions = [d for d in trace["decisions"] if d.get("intent") == "retrieve_chunks"]
    assert len(action_decisions) == 1

    # The ``started`` audit row for the action was written before the error
    rows = await _audit_rows(db_session, str(seeded_matter_session.id))
    assert _tool_started_calls(rows, "retrieve_chunks") >= 1


# ---------------------------------------------------------------------------
# C1 — boundary-validate bad planner args before they reach the SQL layer
# ---------------------------------------------------------------------------


async def test_bad_top_k_is_nonfatal_validation_observation(
    db_session: AsyncSession,
    seeded_matter_session: AutonomousSession,
) -> None:
    """C1: planner emits retrieve_chunks with top_k=-1 → validate_action_args fires.

    The validation raises ValueError BEFORE the SQL layer is touched, so the
    AsyncSession is never poisoned by a DBAPIError.  The loop captures the error
    as a non-fatal failed observation; synthesis runs and produces analysis_content;
    halt_reason is 'planner_done'.
    """
    gw = _ScriptedGateway(
        [
            {
                "next_intent": "retrieve_chunks",
                "args": {"top_k": -1},
                "rationale": "x",
            },
            {"done": True, "rationale": "enough evidence"},
        ]
    )
    node = make_analysis_node(db_session, gw)
    state: AutonomousSessionState = {
        "session_id": str(seeded_matter_session.id),
        "query": "Is the assignment clause enforceable?",
        "retrieved_chunks": [],
    }
    # Must not raise — validation must degrade to a failed observation, not crash
    result = await node(state)

    assert result.get("analysis_content") is not None
    trace = result.get("analysis_plan_trace")
    assert trace is not None
    assert trace["halt_reason"] == "planner_done"
    assert trace["steps"] == 1  # the failed (validated) step is still counted

    action_decisions = [d for d in trace["decisions"] if d.get("intent") == "retrieve_chunks"]
    assert len(action_decisions) == 1


# ---------------------------------------------------------------------------
# I1 — playbook+query session synthesizes under run_playbook, not run_skill
# ---------------------------------------------------------------------------


async def test_playbook_session_synthesizes_under_run_playbook(
    db_session: AsyncSession,
    seeded_playbook_matter_session: AutonomousSession,
) -> None:
    """I1: a matter-scoped session with playbook_id synthesizes under run_playbook.

    Previously _run_analysis_loop hardcoded ToolIntent.run_skill for the synthesis
    call regardless of session target.  The fix computes the correct intent from
    playbook_id / skill_ref and passes it through.  This test asserts the synthesis
    call audits as run_playbook (not run_skill) when the session carries a playbook.
    """
    # Planner immediately signals done; synthesis is the only inference call.
    gw = _ScriptedGateway([{"done": True, "rationale": "nothing to gather"}])
    node = make_analysis_node(db_session, gw)
    state: AutonomousSessionState = {
        "session_id": str(seeded_playbook_matter_session.id),
        "query": "Is the indemnification clause market-standard?",
        "retrieved_chunks": [],
    }
    result = await node(state)

    assert result.get("analysis_content") is not None

    rows = await _audit_rows(db_session, str(seeded_playbook_matter_session.id))
    # Synthesis must audit as run_playbook (I1 fix)
    assert _tool_started_calls(rows, "run_playbook") >= 1, (
        "synthesis for a playbook session must audit as run_playbook, not run_skill"
    )
    assert _tool_started_calls(rows, "run_skill") == 0, (
        "run_skill must NOT appear in the audit log for a playbook session"
    )
