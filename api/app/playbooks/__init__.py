"""Playbook engine — LangGraph executor for M3 ([PRD §3.7](docs/PRD.md#37-playbooks)).

This package contains the substrate the chat / Word add-in / Tabular
surfaces consume. The split:

* :mod:`app.playbooks.state` — typed state shape the LangGraph workflow
  passes between nodes.
* :mod:`app.playbooks.nodes` — individual node functions
  (retrieve / classify / redline / compile).
* :mod:`app.playbooks.executor` — the orchestrator: builds the graph,
  loads playbook + document, runs the workflow, persists the result.

The M3 plan's M3-1 decision locks the runtime in-process inside the
``api/`` service rather than as a separate ``executor/`` container —
Playbook executions are first-class application operations needing
synchronous access to skills, citations, knowledge bases, and project
RBAC.
"""

from __future__ import annotations

from app.playbooks.executor import (
    PlaybookExecutorError,
    run_playbook_execution,
)
from app.playbooks.state import PlaybookExecutionState, PositionVerdict

__all__ = [
    "PlaybookExecutionState",
    "PlaybookExecutorError",
    "PositionVerdict",
    "run_playbook_execution",
]
