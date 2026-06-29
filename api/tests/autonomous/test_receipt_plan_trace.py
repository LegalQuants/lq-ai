"""WS-D PR1 Task 6 — plan trace surfaces in the session receipt.

Two delivery-node tests verify the D5 transparency requirement:

1. When ``analysis_plan_trace`` is present in state the delivery node
   merges it into ``session.result`` under the key ``plan_trace``.  The
   merged value carries the exact structure produced by Task 5
   (``{steps, halt_reason, decisions: [{step, intent, rationale}]}``)
   and every leaf string is short (P3 invariant — no tool payloads).

2. When ``analysis_plan_trace`` is absent (query-less / non-matter
   session) ``session.result`` has no ``plan_trace`` key at all
   (strictly additive; no pollution of the bare receipt shape).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.nodes import make_delivery_node
from app.autonomous.state import AutonomousSessionState
from app.models.autonomous import AutonomousSession

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_SAMPLE_TRACE: dict = {
    "steps": 1,
    "halt_reason": "planner_done",
    "decisions": [
        {
            "step": "0",
            "intent": "retrieve_caselaw",
            "rationale": "find authority on assignment clause enforceability",
        }
    ],
}


def _all_leaf_strings(obj: object) -> list[str]:
    """Recursively collect every str leaf value in a nested dict/list."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        out: list[str] = []
        for v in obj.values():
            out.extend(_all_leaf_strings(v))
        return out
    if isinstance(obj, list):
        out = []
        for item in obj:
            out.extend(_all_leaf_strings(item))
        return out
    return []


# ---------------------------------------------------------------------------
# Test 1: plan_trace present in state → receipt carries it
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delivery_merges_plan_trace_into_receipt(
    db_session: AsyncSession,
    running_session_at_delivery: AutonomousSession,
    mock_gateway: object,
) -> None:
    """delivery_node merges analysis_plan_trace into session.result["plan_trace"].

    Asserts:
    - halt_reason, steps, and the first decision's intent are preserved.
    - Every leaf string in the trace is short (<300 chars — no raw payloads).
    """
    node = make_delivery_node(db_session, mock_gateway)
    state: AutonomousSessionState = {
        "session_id": str(running_session_at_delivery.id),
        "findings": [],
        "findings_count": 1,
        "analysis_plan_trace": _SAMPLE_TRACE,
    }
    await node(state)

    await db_session.refresh(running_session_at_delivery)
    result = running_session_at_delivery.result
    assert result is not None, "session.result must not be None after delivery"
    assert "plan_trace" in result, "session.result must carry a 'plan_trace' key"

    trace = result["plan_trace"]
    assert trace["halt_reason"] == "planner_done"
    assert trace["steps"] == 1
    assert trace["decisions"][0]["intent"] == "retrieve_caselaw"

    # P3 invariant: no leaf string exceeds 300 chars (proves no tool payloads)
    for leaf in _all_leaf_strings(trace):
        assert len(leaf) < 300, f"plan_trace leaf string too long (P3 violation): {leaf!r}"


# ---------------------------------------------------------------------------
# Test 2: plan_trace absent in state → receipt has NO plan_trace key
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delivery_omits_plan_trace_when_absent_from_state(
    db_session: AsyncSession,
    running_session_at_delivery: AutonomousSession,
    mock_gateway: object,
) -> None:
    """delivery_node does NOT inject plan_trace when analysis_plan_trace is absent.

    This covers the query-less / non-matter session path where the loop
    never ran and state carries no trace.  The receipt shape must be
    unchanged (strictly additive invariant).
    """
    node = make_delivery_node(db_session, mock_gateway)
    state: AutonomousSessionState = {
        "session_id": str(running_session_at_delivery.id),
        "findings": [],
        "findings_count": 1,
        # analysis_plan_trace deliberately absent
    }
    await node(state)

    await db_session.refresh(running_session_at_delivery)
    result = running_session_at_delivery.result
    # result may be None (unlikely on a good receipt build) or a dict without plan_trace
    if result is not None:
        assert "plan_trace" not in result, (
            "plan_trace must NOT appear in session.result when absent from state"
        )
