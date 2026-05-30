"""End-to-end honest-failure tests for the autonomous executor (Task 13).

Two failure modes are exercised through the full
:func:`~app.autonomous.executor.run_autonomous_session` pipeline (intake →
analysis → drafting → ethics_review → delivery), proving that the
honest-failure paths wired in Tasks 11/12/15 hold end-to-end:

1. **Gateway transport failure mid-analysis** — the analysis node's
   ``guarded_tool_call(... run_skill ...)`` reaches
   :func:`app.autonomous.guard._handle_gateway_inference`, which wraps the
   ``gateway.chat_completion`` call in ``try/except Exception`` and returns a
   ``ToolResult(outcome="gateway_error", ...)`` rather than raising. The
   session therefore does NOT halt — analysis returns
   ``analysis_outcome="gateway_error"``, drafting emits one explanatory
   finding, delivery writes the ``completed`` audit row, and the receipt
   carries ``terminal_reason="completed"`` with ``gateway_error`` among the
   tool-call outcomes.

2. **Unparseable analysis output** — the gateway returns text that is not
   JSON, so the tool call succeeds (``outcome="success"``) but drafting's
   tolerant ``parse_structured_output`` reports ``is_structured=False`` and
   emits one raw-content finding; the session completes honestly.

These are pure tests: no production code is touched. A failure here points
at the fixture/mock/call, not at production behavior.

Reuses the ``running_watch_session_at_analysis`` fixture from
``tests/autonomous/conftest.py`` — a watch-triggered, opted-in session with
``params={kb_id, file_id, skill_ref}``, a real indexed chunk, the installed
skill registry (so ``skill_ref`` resolves), ``status="running"``,
``current_phase="intake"``, and a finite ``max_cost_usd``. Intake retrieves
the file's chunk; analysis then fires the gateway inference because
``skill_ref`` resolves.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.executor import run_autonomous_session
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession


@pytest.mark.integration
async def test_gateway_error_completes_honestly(
    db_session: AsyncSession, running_watch_session_at_analysis: AutonomousSession
) -> None:
    """Gateway raises mid-analysis → session completes (not halted) with one
    error-explanation finding; terminal_reason='completed'; receipt is honest."""
    session = running_watch_session_at_analysis
    gateway = AsyncMock()
    gateway.chat_completion = AsyncMock(
        side_effect=RuntimeError("simulated gateway transport error")
    )

    await run_autonomous_session(db_session, session_id=session.id, gateway=gateway)

    await db_session.refresh(session)
    assert session.status == "completed"
    receipt = session.result
    assert receipt is not None
    assert receipt["terminal_reason"] == "completed"
    outcomes = {tc["outcome"] for tc in receipt["tool_calls"]}
    assert "gateway_error" in outcomes


@pytest.mark.integration
async def test_tolerant_parse_unstructured_completes_with_raw_finding(
    db_session: AsyncSession, running_watch_session_at_analysis: AutonomousSession
) -> None:
    """Gateway returns text that doesn't fit the JSON schema → one emit_finding
    with the raw content; session completes."""
    session = running_watch_session_at_analysis
    gateway = AsyncMock()
    gateway.chat_completion = AsyncMock(
        return_value=type(
            "R",
            (),
            {
                "choices": [
                    type(
                        "C",
                        (),
                        {
                            "message": type(
                                "M",
                                (),
                                {"content": "Sorry, I couldn't follow the format."},
                            )()
                        },
                    )()
                ],
                "usage": type("U", (), {"prompt_tokens": 5, "completion_tokens": 10})(),
            },
        )()
    )

    await run_autonomous_session(db_session, session_id=session.id, gateway=gateway)

    # The gateway WAS actually called — analysis fired inference rather than
    # silently skipping it (which would also yield status=="completed").
    gateway.chat_completion.assert_awaited()

    await db_session.refresh(session)
    assert session.status == "completed"
    receipt = session.result
    assert receipt is not None
    assert receipt["terminal_reason"] == "completed"

    # Prove the tolerant-parse fallback finding actually landed. The receipt's
    # tool_calls record only tool+outcome (not finding titles/bodies), so the
    # queryable proof is the emit_finding success rows in the audit log. For
    # this unstructured scenario exactly two emit_finding calls succeed:
    #   1. drafting_node Case 3 — the raw-content "Unstructured autonomous
    #      output" fallback finding (the path under test); and
    #   2. ethics_review_node — its single "no concerns flagged" finding
    #      (privilege/scope concerns are empty on the unstructured path).
    # Two success rows therefore proves the fallback emit_finding fired.
    emit_finding_successes = (
        await db_session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "autonomous_session.tool_call")
            .where(AuditLog.resource_id == str(session.id))
            .where(AuditLog.details["tool"].astext == "emit_finding")
            .where(AuditLog.details["outcome"].astext == "success")
        )
    ).scalar_one()
    assert emit_finding_successes == 2
