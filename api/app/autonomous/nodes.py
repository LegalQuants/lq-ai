"""LangGraph nodes for the Autonomous executor — M4-A2/A3.

Five phase nodes run sequentially:

1. :func:`make_intake_node` — intake phase: retrieve context from KB
   when ``kb_id`` is provided in state.
2. :func:`make_analysis_node` — analysis phase: evaluate the
   incoming trigger against retrieved chunks, run skills / playbooks.
3. :func:`make_drafting_node` — drafting phase: parse the analysis
   node's structured output and dispatch per-item findings / memories /
   precedents via the chokepoint.
4. :func:`make_ethics_review_node` — ethics-review phase: validate
   the proposed output for privilege sensitivity, scope creep, etc.
5. :func:`make_delivery_node` — delivery phase: notify the user /
   downstream system and wrap up the session.

**A3.3b wiring:** nodes call the real
:func:`~app.autonomous.guard.guarded_tool_call` from
:mod:`app.autonomous.guard`. The old stub in this module is removed.

**Brake-commit contract:** :exc:`~app.errors.AutonomousBrake`
(SessionHalted / CostCapReached / ToolNotGranted) propagates from
:func:`~app.autonomous.guard.guarded_tool_call` to the executor's
terminal handler, which commits and persists the halt-state latch +
audit rows the chokepoint flushed. A node that catches a brake locally
MUST commit before returning, or the latch and audit row are silently
lost (the A2 data-loss class — see :mod:`app.autonomous.guard`).

Factory-closure style: each ``make_*_node`` function returns an async
callable bound to the resources it needs (``db``, ``gateway``) so the
LangGraph node functions remain pure-ish over the state dict and
:class:`~langgraph.graph.StateGraph` merge semantics stay clean.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.audit import autonomous_audit
from app.autonomous.enums import ToolIntent
from app.autonomous.guard import guarded_tool_call
from app.autonomous.phases import run_phase_transition
from app.autonomous.prompts import assemble_analysis_messages
from app.autonomous.receipt import build_receipt_safe
from app.autonomous.state import AutonomousSessionState
from app.autonomous.structured_output import parse_structured_output
from app.config import get_settings
from app.models.autonomous import AutonomousSession
from app.schemas.autonomous import Phase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase node factories
# ---------------------------------------------------------------------------


def make_intake_node(
    db: AsyncSession,
    gateway: Any = None,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the intake-phase node bound to a DB session.

    The intake node transitions the session to :attr:`Phase.intake`
    then dispatches on the session's ``params`` to call
    :func:`~app.autonomous.guard.guarded_tool_call` with
    :attr:`~app.autonomous.enums.ToolIntent.retrieve_chunks` in the
    mode matching the trigger that spawned the session (M4 Tasks 9/10):

    * Watch path — ``params["file_id"]`` present: scope to the arriving
      file's chunks via mode 2 of ``_handle_retrieve_chunks``.
    * Schedule path — ``params["kb_id"]`` + ``params["since"]``: scope
      to docs attached to the KB after ``since`` (the schedule's prior
      ``last_run_at``) via mode 3.
    * Schedule first-tick — ``params["kb_id"]`` with no ``since``: no
      baseline yet; skip retrieval and set
      ``first_tick_no_baseline=True`` so downstream nodes know the
      empty input is intentional.
    * No-target — neither ``file_id`` nor ``kb_id``: stay empty;
      delivery still completes with an empty-findings notification.

    Brakes (:exc:`~app.errors.AutonomousBrake`) propagate to the
    executor's terminal handler per the brake-commit contract.
    """

    async def intake_node(state: AutonomousSessionState) -> dict[str, Any]:
        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            logger.error(
                "autonomous.intake_node: session not found",
                extra={"event": "autonomous_intake_session_missing", "session_id": session_id},
            )
            return {"error": f"session {session_id} not found in intake_node"}

        logger.info(
            "autonomous.intake_node: entering",
            extra={"event": "autonomous_intake_enter", "session_id": session_id},
        )
        await run_phase_transition(session, Phase.intake, db)
        await db.flush()

        updates: dict[str, Any] = {"current_phase": str(Phase.intake)}

        params = session.params or {}
        kb_id = params.get("kb_id")
        file_id = params.get("file_id")
        since = params.get("since")

        if file_id:
            # Watch path: scope to the arriving file's chunks (mode 2).
            result = await guarded_tool_call(
                session,
                ToolIntent.retrieve_chunks,
                {
                    "kb_id": str(kb_id) if kb_id else None,
                    "file_id": str(file_id),
                },
                db,
                gateway,
            )
            updates["retrieved_chunks"] = result.data.get("chunks", []) if result.data else []
        elif kb_id and since:
            # Schedule path: scope to docs attached after `since` (mode 3).
            result = await guarded_tool_call(
                session,
                ToolIntent.retrieve_chunks,
                {"kb_id": str(kb_id), "since": since},
                db,
                gateway,
            )
            updates["retrieved_chunks"] = result.data.get("chunks", []) if result.data else []
        elif kb_id and not since and not file_id:
            # First-tick schedule (last_run_at was NULL at spawn): no
            # baseline yet — record the marker and skip retrieval.
            updates["retrieved_chunks"] = []
            updates["first_tick_no_baseline"] = True
        else:
            # No target at all — degenerate session (test/manual). Stay
            # empty; delivery will still complete with an empty-findings
            # notification.
            updates["retrieved_chunks"] = []

        return updates

    return intake_node


def make_analysis_node(
    db: AsyncSession,
    gateway: Any = None,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the analysis-phase node bound to a DB session.

    The analysis node transitions the session to :attr:`Phase.analysis`
    then makes ONE guarded inference call through the chokepoint:

    * If state carries ``first_tick_no_baseline`` (set by intake on a
      schedule's first cron tick — no baseline yet), the node skips the
      inference call entirely and returns ``analysis_content=None``;
      downstream drafting emits the empty-findings notification.
    * If the session's ``params`` carries neither ``skill_ref`` nor
      ``playbook_id``, the node also skips the call (a degenerate
      no-target session — downstream emits a "no autonomous target
      configured" finding).
    * Otherwise the node assembles messages via
      :func:`~app.autonomous.prompts.assemble_analysis_messages` from
      the skill's SKILL.md body / playbook render plus the retrieved
      chunks, picks ``ToolIntent.run_playbook`` when ``playbook_id`` is
      set else ``ToolIntent.run_skill``, picks a model from
      ``params["model"]`` -> :attr:`settings.autonomous_default_model`,
      and calls :func:`~app.autonomous.guard.guarded_tool_call` with
      ``anonymize=True``.

    The LLM's response text lands in ``state["analysis_content"]`` and
    the call's outcome (``"success"`` or ``"gateway_error"``) lands in
    ``state["analysis_outcome"]`` — both consumed by the drafting node
    (Task 12) and the tolerant structured-output parser (Task 8).

    Brakes (:exc:`~app.errors.AutonomousBrake`) propagate to the
    executor's terminal handler per the brake-commit contract.
    """

    async def analysis_node(state: AutonomousSessionState) -> dict[str, Any]:
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in analysis_node"}

        logger.info(
            "autonomous.analysis_node: entering",
            extra={"event": "autonomous_analysis_enter", "session_id": session_id},
        )
        await run_phase_transition(session, Phase.analysis, db)
        await db.flush()

        # First-tick schedule (intake had no baseline to retrieve against):
        # skip the inference call entirely; downstream drafting handles the
        # empty-input case.
        if state.get("first_tick_no_baseline"):
            return {
                "current_phase": str(Phase.analysis),
                "analysis_content": None,
                "first_tick_no_baseline": True,
            }

        params = session.params or {}
        skill_ref = params.get("skill_ref")
        playbook_id = params.get("playbook_id")
        if not skill_ref and not playbook_id:
            # Degenerate no-target session — drafting emits the
            # "no autonomous target configured" finding (Task 12).
            return {
                "current_phase": str(Phase.analysis),
                "analysis_content": None,
            }

        chunks = state.get("retrieved_chunks") or []
        messages = await assemble_analysis_messages(session, chunks=chunks, db=db)
        intent = ToolIntent.run_playbook if playbook_id else ToolIntent.run_skill

        settings = get_settings()
        model = params.get("model") or settings.autonomous_default_model

        result = await guarded_tool_call(
            session,
            intent,
            {
                "model": model,
                "messages": messages,
                "anonymize": True,
            },
            db,
            gateway,
        )

        return {
            "current_phase": str(Phase.analysis),
            "analysis_content": (result.data or {}).get("content"),
            "analysis_outcome": result.outcome,
        }

    return analysis_node


def make_drafting_node(
    db: AsyncSession,
    gateway: Any = None,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the drafting-phase node bound to a DB session.

    The drafting node transitions the session to :attr:`Phase.drafting`,
    then turns the analysis node's raw ``analysis_content`` into a set of
    durable proposals — each dispatched as its OWN
    :func:`~app.autonomous.guard.guarded_tool_call` so every finding,
    memory, and precedent is independently brake-checked and audited.

    Four input cases, in priority order:

    1. ``analysis_outcome == "gateway_error"`` — the analysis inference
       call failed at the gateway. Emit ONE explanatory finding
       (severity ``warn``) and continue honestly; no findings/memories/
       precedents are fabricated from a failed call.
    2. ``first_tick_no_baseline`` — the schedule's first cron tick had no
       baseline to analyze. Emit ONE ``info`` "baseline set" finding.
    3. Unparseable ``analysis_content`` — the tolerant parser
       (:func:`~app.autonomous.structured_output.parse_structured_output`)
       returns ``is_structured=False``. Emit ONE ``info`` finding carrying
       the raw content (truncated) so nothing is silently dropped.
    4. Structured output — dispatch each parsed finding via
       :attr:`~app.autonomous.enums.ToolIntent.emit_finding`, each
       suggested memory via
       :attr:`~app.autonomous.enums.ToolIntent.propose_memory`, and each
       suggested precedent via
       :attr:`~app.autonomous.enums.ToolIntent.propose_precedent`. The
       parser's ``privilege_concerns`` / ``scope_concerns`` are forwarded
       in the returned state for the ethics-review node.

    Every return path emits both ``findings`` (the list of dispatched
    finding dicts) and ``findings_count`` (its length) — ``findings_count``
    counts findings ONLY, never memories or precedents.

    Brakes propagate to the executor's terminal handler per the
    brake-commit contract.
    """

    async def drafting_node(state: AutonomousSessionState) -> dict[str, Any]:
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in drafting_node"}

        logger.info(
            "autonomous.drafting_node: entering",
            extra={"event": "autonomous_drafting_enter", "session_id": session_id},
        )
        await run_phase_transition(session, Phase.drafting, db)
        await db.flush()

        # Case 1 — honest gateway_error path: emit ONE explanatory finding.
        if state.get("analysis_outcome") == "gateway_error":
            finding = {
                "title": "Autonomous analysis failed at the gateway",
                "summary": (
                    "The analysis inference call returned a gateway error. "
                    "No findings, memories, or precedents were produced."
                ),
                "severity": "warn",
            }
            await guarded_tool_call(
                session,
                ToolIntent.emit_finding,
                {"finding": finding},
                db,
                gateway,
            )
            return {
                "current_phase": str(Phase.drafting),
                "findings": [finding],
                "findings_count": 1,
            }

        # Case 2 — schedule first tick: emit ONE baseline finding.
        if state.get("first_tick_no_baseline"):
            finding = {
                "title": "First scheduled tick — baseline set",
                "summary": (
                    "No documents attached before this run; "
                    "the next run will analyze what arrives in between."
                ),
                "severity": "info",
            }
            await guarded_tool_call(
                session,
                ToolIntent.emit_finding,
                {"finding": finding},
                db,
                gateway,
            )
            return {
                "current_phase": str(Phase.drafting),
                "findings": [finding],
                "findings_count": 1,
            }

        parsed = parse_structured_output(state.get("analysis_content"))

        # Case 3 — tolerant fallback: ONE finding carrying the raw content.
        if not parsed.is_structured:
            finding = {
                "title": "Unstructured autonomous output",
                "summary": parsed.raw_content[:8000] if parsed.raw_content else "(empty)",
                "severity": "info",
            }
            await guarded_tool_call(
                session,
                ToolIntent.emit_finding,
                {"finding": finding},
                db,
                gateway,
            )
            return {
                "current_phase": str(Phase.drafting),
                "findings": [finding],
                "findings_count": 1,
            }

        # Case 4 — structured: dispatch each item as its own guarded call.
        findings: list[dict[str, Any]] = []
        for finding in parsed.findings:
            await guarded_tool_call(
                session,
                ToolIntent.emit_finding,
                {"finding": finding},
                db,
                gateway,
            )
            findings.append(finding)

        for memory in parsed.suggested_memories:
            await guarded_tool_call(
                session,
                ToolIntent.propose_memory,
                {
                    "category": memory.get("category", "general"),
                    "content": memory.get("content", ""),
                    # rationale is accepted but ignored by the handler
                    # (AutonomousMemory has no rationale column); passed per
                    # the M4-D2 design — harmless.
                    "rationale": memory.get("rationale"),
                },
                db,
                gateway,
            )

        for precedent in parsed.suggested_precedents:
            await guarded_tool_call(
                session,
                ToolIntent.propose_precedent,
                {
                    "pattern_kind": precedent.get("pattern_kind", "general"),
                    "summary": precedent.get("summary", ""),
                },
                db,
                gateway,
            )

        # ``findings_count`` counts findings ONLY — memories and precedents
        # are deliberately excluded (they are proposals, not findings).
        return {
            "current_phase": str(Phase.drafting),
            "findings": findings,
            "findings_count": len(findings),
            "privilege_concerns": parsed.privilege_concerns,
            "scope_concerns": parsed.scope_concerns,
        }

    return drafting_node


def make_ethics_review_node(
    db: AsyncSession,
    gateway: Any = None,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the ethics-review-phase node bound to a DB session.

    The ethics-review node transitions the session to
    :attr:`Phase.ethics_review`, then emits ONE guarded
    :attr:`~app.autonomous.enums.ToolIntent.emit_finding` summarizing the
    ``privilege_concerns`` / ``scope_concerns`` the drafting node (Task 12)
    forwarded from the structured-output JSON. When both lists are empty it
    emits a single ``info`` "no concerns flagged" finding. A dedicated
    ethics LLM gate is a future enhancement (DE); ``emit_finding`` is the
    only tool intent permitted in this phase.

    Brakes propagate to the executor's terminal handler per the
    brake-commit contract.
    """

    async def ethics_review_node(state: AutonomousSessionState) -> dict[str, Any]:
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in ethics_review_node"}

        logger.info(
            "autonomous.ethics_review_node: entering",
            extra={"event": "autonomous_ethics_review_enter", "session_id": session_id},
        )
        await run_phase_transition(session, Phase.ethics_review, db)
        await db.flush()

        privilege = state.get("privilege_concerns") or []
        scope = state.get("scope_concerns") or []

        if privilege or scope:
            summary_lines: list[str] = []
            if privilege:
                summary_lines.append(f"Privilege concerns ({len(privilege)}):")
                summary_lines.extend(f"  - {c}" for c in privilege)
            if scope:
                summary_lines.append(f"Scope concerns ({len(scope)}):")
                summary_lines.extend(f"  - {c}" for c in scope)
            title = "Ethics-review concerns flagged"
            summary = "\n".join(summary_lines)
        else:
            title = "Ethics review: no concerns flagged"
            summary = (
                "The analysis output did not surface privilege or scope concerns. "
                "A dedicated ethics LLM gate is a future enhancement (DE)."
            )

        await guarded_tool_call(
            session,
            ToolIntent.emit_finding,
            {"finding": {"title": title, "summary": summary, "severity": "info"}},
            db,
            gateway,
        )

        return {"current_phase": str(Phase.ethics_review)}

    return ethics_review_node


def make_delivery_node(
    db: AsyncSession,
    gateway: Any = None,
) -> Callable[[AutonomousSessionState], Awaitable[dict[str, Any]]]:
    """Build the delivery-phase node bound to a DB session.

    The delivery node transitions the session to :attr:`Phase.delivery`,
    calls :func:`~app.autonomous.guard.guarded_tool_call` with
    :attr:`~app.autonomous.enums.ToolIntent.notify` to write the
    in-app notification row, writes the terminal
    ``autonomous_session.completed`` audit row (so the receipt's
    ``terminal_reason`` populates), then marks the session as completed
    and commits.

    Brakes propagate to the executor's terminal handler per the
    brake-commit contract.
    """

    async def delivery_node(state: AutonomousSessionState) -> dict[str, Any]:
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in delivery_node"}

        logger.info(
            "autonomous.delivery_node: entering",
            extra={"event": "autonomous_delivery_enter", "session_id": session_id},
        )
        await run_phase_transition(session, Phase.delivery, db)

        # Notify the user via the chokepoint — this is the canonical tool
        # call in the delivery phase; it must not bypass the gate.
        findings_count = state.get("findings_count", len(state.get("findings") or []))
        await guarded_tool_call(
            session,
            ToolIntent.notify,
            {
                "title": "Autonomous session complete",
                "body": f"Session completed with {findings_count} finding(s).",
                "payload": {"finding_count": findings_count},
            },
            db,
            gateway,
        )

        # Write the terminal 'completed' audit row BEFORE build_receipt so the
        # receipt's terminal_reason derives from it (bug fix: 2026-05-27
        # acceptance showed terminal_reason=None because no completed row existed).
        await autonomous_audit(
            db,
            session,
            "completed",
            cost_total_usd=str(session.cost_total_usd or "0"),
            findings_count=findings_count,
        )
        session.status = "completed"
        session.completed_at = datetime.now(UTC)
        # Persist the receipt into result BEFORE the commit so the JSONB
        # column is populated atomically with the terminal status update.
        # build_receipt reads audit rows that were flushed during the run
        # and are visible in the same session/transaction.
        session.result = await build_receipt_safe(session, db)
        await db.commit()

        return {"current_phase": str(Phase.delivery)}

    return delivery_node
