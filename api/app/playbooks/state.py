"""LangGraph state for the Playbook executor — M3-A2.

The state is a single :class:`PlaybookExecutionState` TypedDict that
the four nodes (retrieve / classify / redline / compile) read and
extend. LangGraph's :class:`langgraph.graph.StateGraph` merges each
node's returned partial update into the running state.

Per the M3-1 architectural decision the runtime runs in-process; the
state isn't checkpointed between nodes (LangGraph's
:mod:`langgraph.checkpoint` is deliberately not wired). A failure
mid-flight surfaces as a single ``error`` field and the executor
restarts from the top on retry. This keeps the v0.3 implementation
simple; per-node checkpointing is a candidate enhancement once the
executor's failure modes are better understood in production.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

PositionVerdict = Literal[
    "matches_standard",
    "matches_fallback",
    "deviates",
    "missing",
]
"""One of the four per-position classification verdicts the executor
emits. ``matches_fallback`` is single-valued (the executor records
which fallback tier matched in the result's ``matched_fallback_rank``
field rather than encoding the rank in the verdict itself)."""


class _PositionInput(TypedDict):
    """A playbook position, denormalized for executor use.

    Loaded once at the top of :func:`run_playbook_execution` so the
    nodes can be pure functions over the state dict without re-hitting
    the DB per position. Mirrors :class:`app.models.playbook.PlaybookPosition`
    plus a serializable form of ``fallback_tiers``.
    """

    id: str  # uuid as str — JSONable for LangGraph state serialization
    issue: str
    description: str
    standard_language: str
    fallback_tiers: list[dict[str, Any]]
    redline_strategy: str
    severity_if_missing: str
    detection_keywords: list[str]
    detection_examples: list[str]
    position_order: int


class _ChunkForRetrieval(TypedDict):
    """A document chunk shape the retrieve node returns to classify."""

    id: str
    chunk_index: int
    content: str
    char_offset_start: int
    char_offset_end: int
    page_start: int | None


class _RetrievedForPosition(TypedDict):
    """The chunks the retrieve node picked for one playbook position."""

    position_id: str
    chunks: list[_ChunkForRetrieval]


class _RedlineSuggestion(TypedDict):
    """Output of the redline node for one deviating position."""

    old_text: str
    new_text: str
    justification: str


class _PositionResult(TypedDict):
    """One per-position outcome the executor accumulates and persists.

    Shape mirrors what the M3-A4 UI renders and what the Word add-in
    (M3-B5) writes back as Word comments + tracked changes. The
    ``cited_chunk_ids`` field carries the chunks the classification
    referenced — the Citation Engine integration (deferred from
    M3-A2 per the task scope; surfaced in M3-A4) consumes this list.
    """

    position_id: str
    issue: str
    severity_if_missing: str
    verdict: PositionVerdict
    confidence: float
    matched_fallback_rank: int | None
    cited_chunk_ids: list[str]
    matched_text: str  # the contract's actual clause text the classifier matched
    redline: _RedlineSuggestion | None  # only populated for `deviates`
    justification: str


class PlaybookExecutionState(TypedDict, total=False):
    """LangGraph state for one playbook execution.

    Fields populated at graph entry (by :func:`run_playbook_execution`):

    * ``execution_id`` — the row in ``playbook_executions`` being filled.
    * ``playbook_id``, ``target_document_id`` — denormalized for nodes.
    * ``positions`` — playbook's positions in ``position_order``.
    * ``document_normalized_content`` — for the redline node to slice
      around matched chunks.
    * ``judge_model`` — alias the gateway resolves for the classify +
      redline LLM calls (typically ``"smart"``).

    Fields populated by intermediate nodes:

    * ``retrievals`` — per-position chunk lists from :func:`retrieve_node`.
    * ``per_position_results`` — accumulated outcomes; final shape
      written into ``playbook_executions.results`` by
      :func:`compile_node`.

    Failure state:

    * ``error`` — populated when a node raises; ``compile_node`` flips
      the execution status to ``'error'`` rather than ``'completed'``.

    The TypedDict is ``total=False`` so each node can return only the
    keys it produces; LangGraph merges them onto the running state.
    """

    execution_id: str
    playbook_id: str
    target_document_id: str
    positions: list[_PositionInput]
    document_normalized_content: str
    judge_model: str

    retrievals: list[_RetrievedForPosition]
    per_position_results: list[_PositionResult]
    error: str | None
