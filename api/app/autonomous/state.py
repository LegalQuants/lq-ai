"""LangGraph state for the Autonomous executor — M4-A2.

The state is a single :class:`AutonomousSessionState` TypedDict that
the five phase nodes (intake / analysis / drafting / ethics_review /
delivery) read and extend. LangGraph's :class:`langgraph.graph.StateGraph`
merges each node's returned partial update into the running state.

All values are JSONable: UUIDs as ``str``, money as ``float``. This is
a hard requirement because LangGraph serializes state at node boundaries
and will fail on non-serializable objects (e.g., ``uuid.UUID``,
``decimal.Decimal``).

Per the M4-A2 scope, no checkpointing is wired (matching the playbook
executor pattern). Checkpoint-based resume is a candidate enhancement
once the executor's failure modes are better understood in production.
"""

from __future__ import annotations

from typing import TypedDict


class AutonomousSessionState(TypedDict, total=False):
    """LangGraph state for one autonomous session execution.

    Fields populated at graph entry (by :func:`~app.autonomous.executor.run_autonomous_session`):

    * ``session_id`` — the :class:`~app.models.autonomous.AutonomousSession`
      row being driven (UUID serialized as str).
    * ``user_id`` — the owning user (UUID as str); needed by audit calls
      inside phase nodes without a re-fetch.
    * ``current_phase`` — the session's phase at graph entry (str from
      :class:`~app.schemas.autonomous.Phase`).
    * ``halt_state`` — the session's brake state at graph entry (str from
      :class:`~app.schemas.autonomous.HaltState`).
    * ``cost_total_usd`` — accumulated spend as of graph entry (float).
    * ``max_cost_usd`` — per-session cost cap (float or None if uncapped).
    * ``findings`` — accumulated findings emitted by drafting / ethics
      nodes; each entry is a plain dict.
    * ``proposed_memory`` — memory notes the agent proposes for curation;
      each entry is a plain dict.
    * ``error`` — set when a node encounters an unrecoverable error so
      subsequent nodes can short-circuit.
    """

    session_id: str
    user_id: str
    current_phase: str
    halt_state: str
    cost_total_usd: float
    max_cost_usd: float | None
    findings: list[dict]
    proposed_memory: list[dict]
    error: str | None

    # A3.3b: optional KB retrieval inputs (set by caller when a KB is
    # relevant to the session).  When both are present the intake node
    # calls retrieve_chunks through the chokepoint.
    kb_id: str | None
    query: str | None
    # M4 Tasks 9/10: output of retrieve_chunks — the chunks list
    # (full text, for downstream LLM use).  Mode-agnostic across
    # watch/schedule/first-tick paths: empty list when no retrieval
    # ran or no chunks matched.
    retrieved_chunks: list[dict] | None
    # M4 Task 10: schedule-first-tick marker — set when intake skipped
    # retrieval because the schedule has no prior ``last_run_at`` to
    # compare against.  Downstream nodes treat empty input as
    # intentional rather than an error.
    first_tick_no_baseline: bool

    # M4 Task 11: analysis-phase output. ``analysis_content`` is the LLM's
    # raw response text (the JSON-fenced structured output the drafting
    # node parses via Task 8's tolerant parser) — ``None`` when the
    # analysis call was skipped (first_tick_no_baseline, no target) or
    # when the gateway returned an error. ``analysis_outcome`` is the
    # chokepoint's outcome label (``"success"`` or ``"gateway_error"``)
    # for the inference call; absent when no inference call was made.
    analysis_content: str | None
    analysis_outcome: str

    # M4 Task 12: drafting-phase output. ``findings_count`` is the number of
    # findings the drafting node dispatched through the chokepoint (one per
    # parsed finding, or 1 for the fallback / gateway-error / first-tick
    # single-finding paths). ``privilege_concerns`` / ``scope_concerns`` carry
    # the parser's flagged concerns forward to the ethics-review node.
    findings_count: int
    privilege_concerns: list[str]
    scope_concerns: list[str]

    # Donna ask #8: number of document-grade artifacts the drafting node
    # PERSISTED through the ``emit_artifact`` chokepoint (skips and storage
    # errors are excluded). Always present on the drafting node's return —
    # 0 when the session did not opt in (``params["emit_artifacts"]``
    # absent) or on the non-structured drafting paths. The delivery node
    # surfaces it as ``artifact_count`` in the notify payload and as
    # ``artifacts_count`` on the terminal ``completed`` audit row.
    artifacts_count: int
