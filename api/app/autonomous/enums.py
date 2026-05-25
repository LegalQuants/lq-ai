"""Autonomous executor enums and phase-grant map — M4-A2.

``Phase`` and ``HaltState`` are imported from the canonical source of
truth in :mod:`app.schemas.autonomous` — do NOT redefine them here.

This module adds:

* :class:`ToolIntent` — the closed set of tool operations the executor
  can request. The chokepoint (:func:`~app.autonomous.nodes.guarded_tool_call`,
  implemented in M4-A3) validates every tool call against the grant set
  for the session's current phase.

* :data:`PHASE_GRANTS` — the authoritative per-phase grant set. A node
  may only invoke a tool intent that appears in this map for the phase
  it is currently in. The map is immutable at runtime (frozensets as
  values).
"""

from __future__ import annotations

from enum import StrEnum

from app.schemas.autonomous import HaltState, Phase

# Re-export Phase and HaltState so callers in this package can import
# from one place, but the canonical definitions remain in schemas.
__all__ = [
    "PHASE_GRANTS",
    "HaltState",
    "Phase",
    "ToolIntent",
]


class ToolIntent(StrEnum):
    """The closed set of tool intents the autonomous executor can invoke.

    Each member corresponds to one class of external action. The
    :data:`PHASE_GRANTS` map governs which intents are permitted in each
    phase; :func:`~app.autonomous.nodes.guarded_tool_call` enforces the
    grant at call time (M4-A3).
    """

    retrieve_chunks = "retrieve_chunks"
    run_skill = "run_skill"
    run_playbook = "run_playbook"
    propose_memory = "propose_memory"
    propose_precedent = "propose_precedent"
    emit_finding = "emit_finding"
    notify = "notify"


PHASE_GRANTS: dict[Phase, frozenset[ToolIntent]] = {
    Phase.intake: frozenset({ToolIntent.retrieve_chunks}),
    Phase.analysis: frozenset(
        {
            ToolIntent.retrieve_chunks,
            ToolIntent.run_skill,
            ToolIntent.run_playbook,
            # propose_precedent at analysis: document/clause patterns are
            # observed while reading docs (M4-B2, Decision B2-b).
            ToolIntent.propose_precedent,
        }
    ),
    Phase.drafting: frozenset(
        {
            ToolIntent.run_skill,
            ToolIntent.emit_finding,
            ToolIntent.propose_memory,
            # propose_precedent at drafting: recurring patterns recognized
            # during synthesis (M4-B2, Decision B2-b).
            ToolIntent.propose_precedent,
        }
    ),
    Phase.ethics_review: frozenset({ToolIntent.emit_finding}),
    Phase.delivery: frozenset({ToolIntent.notify}),
}
"""Per-phase tool-intent grant sets.

A node in phase ``P`` may only call a tool with intent ``I`` when
``I in PHASE_GRANTS[P]``. The chokepoint enforces this at runtime
(M4-A3). The grant sets are ``frozenset`` to prevent accidental
mutation.
"""
