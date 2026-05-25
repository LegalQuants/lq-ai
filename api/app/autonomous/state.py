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
