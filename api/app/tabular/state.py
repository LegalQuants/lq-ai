"""LangGraph state for the Tabular Review executor — M3-C2.

Mirrors the M3-A2 :mod:`app.playbooks.state` pattern. The state is a
single :class:`TabularExecutionState` TypedDict that the executor's
nodes (load-documents / extract-cells / aggregate) read and extend.

Per Decision C-3 the runtime runs inside the ARQ worker; per-node
checkpointing is deliberately not wired in v0.3.0. A failure mid-flight
surfaces as a single ``error`` field and the row flips to
``status='failed'``; the operator restarts a fresh execution rather
than resuming partial state. Per-node checkpointing is a candidate
enhancement once production failure modes are better understood.
"""

from __future__ import annotations

from typing import Any, TypedDict


class _ColumnSpecState(TypedDict, total=False):
    """A column spec, serialized for the executor's state.

    Mirrors :class:`app.schemas.tabular.ColumnSpec` but as a TypedDict
    so LangGraph's state serialization stays straightforward (Pydantic
    models inside the state are fine but a TypedDict signals the
    intent: this is data, not behavior)."""

    name: str
    query: str
    ensemble_verification: bool | None
    minimum_inference_tier: int | None


class _DocumentSnapshot(TypedDict):
    """A document loaded for the run — minimal shape the executor needs.

    Loaded once at the top of :func:`app.tabular.executor.run_tabular_execution`
    so the cell-extraction node doesn't re-hit the DB per cell. The
    document's normalized content lives on the row (for FTS) but the
    cell extraction works against the per-chunk content fetched at
    cell time."""

    id: str
    name: str


class _CellResultState(TypedDict, total=False):
    """One cell result accumulated by the extraction node.

    Kept ``total=False`` so the extraction failure path can write
    partial keys without satisfying every field. The aggregation node
    reads keys defensively (``.get``) so a missing key defaults to a
    sensible value.

    Persisted shape (post-aggregation) is
    :class:`app.schemas.tabular.CellResult`. This TypedDict is the
    in-flight shape carrying the document_id + column_name so the
    aggregation node can group cells back into rows.
    """

    document_id: str
    column_name: str
    value: str | None
    cited_chunk_ids: list[str]
    confidence: str  # high|medium|low|failed
    tier_used: int | None
    cost_usd: str  # Decimal as string for JSON serializability
    error: str | None
    # Citation-Engine verification method for the cell (Donna #6), e.g.
    # ``ensemble_strict`` / ``ensemble_majority``. None when the column
    # isn't ensemble-verified or verification didn't confirm the value.
    verification_method: str | None


class TabularExecutionState(TypedDict, total=False):
    """LangGraph state for one tabular execution.

    Fields populated at graph entry (by :func:`run_tabular_execution`):

    * ``execution_id`` — the row in ``tabular_executions`` being filled.
    * ``columns`` — resolved column spec (snapshot of skill's
      ``lq_ai.columns`` OR operator's ad-hoc list — already decided at
      request time).
    * ``judge_model`` — alias the gateway resolves for cell-extraction
      calls (typically ``"smart"``).

    Fields populated by intermediate nodes:

    * ``documents`` — loaded by :func:`load_documents_node`; passed
      through to the extraction node.
    * ``per_cell_results`` — accumulated by :func:`extract_cells_node`;
      grouped by document_id by :func:`aggregate_node` into the final
      ``tabular_executions.results`` JSONB payload.

    Failure state:

    * ``error`` — populated when a node raises; :func:`aggregate_node`
      flips the execution status to ``'failed'`` rather than
      ``'completed'``.
    """

    execution_id: str
    columns: list[_ColumnSpecState]
    judge_model: str

    documents: list[_DocumentSnapshot]
    per_cell_results: list[_CellResultState]
    error: str | None


# Public-ish helpers for outside-the-graph callers. Anything the
# worker or endpoint imports for type hints lives here.

__all__ = [
    "TabularExecutionState",
]


# Internal re-export — keeps the nodes module from re-deriving the
# CellResult shape; outside callers continue to use the Pydantic
# :class:`app.schemas.tabular.CellResult` for the wire surface.
_InternalCellResult = _CellResultState
_InternalDocumentSnapshot = _DocumentSnapshot
_InternalColumnSpec = _ColumnSpecState
_InternalAny = Any  # mypy-friendly forward-compat placeholder
