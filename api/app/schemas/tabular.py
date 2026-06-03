"""Pydantic schemas for Tabular / Multi-Document Review — M3-C2.

Wire shapes for the ``/api/v1/tabular`` surface
([PRD §3.14](docs/PRD.md#314-tabular--multi-document-review-m3)).
The ORM model lives in :mod:`app.models.tabular`; this module is the
request / response surface for the endpoints landing in M3-C2.

Per Phase C prep doc Decision C-1, table-mode skills declare columns
via ``lq_ai.columns`` in their frontmatter (the :class:`ColumnSpec`
already defined in :mod:`app.skills.schema`). This module redefines the
wire-side ``ColumnSpec`` rather than importing the skills-side one
because the contexts differ: skills-side ``ColumnSpec`` is loaded from
SKILL.md frontmatter at startup; this wire-side ``ColumnSpec`` arrives
on each tabular-execution request as JSON. The shapes are identical
today; if they diverge (e.g., ad-hoc executions add ad-hoc-only
fields), this module owns the wire surface independent of the
authoring surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Deterministic namespace for synthesizing a tabular cell's ``citation_id``
# from its ``chunk_id``. The tabular executor persists raw ``cited_chunk_ids``
# (chunk references); the read-side surface (M3-C4) models structured
# ``Citation`` objects keyed by ``citation_id``. Until the executor mints
# real Citation-Engine rows (deferred — see PRD §9), we derive a stable,
# display-only ``citation_id = uuid5(NS, chunk_id)`` so the same chunk always
# maps to the same id. The citation drawer is display-only and never resolves
# this id against the Citation Engine, so a synthetic id is safe.
_TABULAR_CITATION_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "tabular-citation.lq.ai")

TabularExecutionStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
"""Lifecycle states for a :class:`TabularExecution`. Matches the CHECK
constraint on ``tabular_executions.status`` (migration 0036)."""

CellConfidence = Literal["high", "medium", "low", "failed"]
"""Per-cell confidence from the Citation Engine cascade. ``failed``
is the M3-C2 / Decision C-10 state for cells where extraction itself
errored (distinct from Citation Engine's red ``unverified`` state)."""


class ColumnSpec(BaseModel):
    """One column in a tabular execution's column spec.

    Mirrors :class:`app.skills.schema.ColumnSpec` — kept separate so
    the wire surface can evolve independently of the authoring surface
    (e.g., ad-hoc executions could add fields that don't make sense
    in SKILL.md frontmatter).
    """

    name: str
    """Grid column header. Required."""

    query: str
    """Per-row extraction prompt instantiated against each document.
    Required."""

    ensemble_verification: bool | None = None
    """Per-column override of the skill-level
    ``ensemble_verification`` field."""

    minimum_inference_tier: int | None = Field(
        default=None,
        ge=1,
        le=5,
        description="Per-column tier floor (1-5).",
    )


class Citation(BaseModel):
    """A single citation backing a cell value.

    Lightweight projection of the M2 Citation Engine's
    :class:`app.models.message_citation.MessageCitation` shape — kept
    minimal here because tabular cells reference citations by ID; the
    cell renderer looks up the full citation row via the existing
    Citation Engine surface (no duplicate persistence)."""

    citation_id: uuid.UUID
    document_id: uuid.UUID
    """The source document this citation lands in."""

    chunk_id: uuid.UUID | None = None
    """The specific chunk inside the document, when the cascade
    resolved one. None for chunk-boundary-spanning citations."""

    confidence: CellConfidence

    # --- Navigation fields (Donna) ----------------------------------------
    # Resolved at read time in ``GET /tabular/executions/{id}`` so the
    # frontend can open the cited source in its doc panel (same UX as chat
    # citations). They are optional + default ``None`` so the schema-level
    # ``_synthesize_cell_citations`` validator (no DB access) and the
    # XLSX/CSV export paths (which only read ``citation_id``) keep building
    # this model unchanged; the endpoint handler populates them via batched
    # lookups against ``documents`` and ``document_chunks``.
    source_file_id: uuid.UUID | None = None
    """The ``documents.file_id`` of the citation's source document. The
    critical missing piece for navigation: cells reference a
    ``documents.id`` (via ``document_id``), but the frontend's doc panel
    keys off ``files.id``. ``None`` until resolved (or when the backing
    chunk row is missing / stale)."""

    source_page: int | None = None
    """The cited chunk's ``document_chunks.page_start``. Nullable because
    some chunks have no clean page assignment (best-effort page mapping)."""

    source_text: str | None = None
    """The cited chunk's full ``document_chunks.content``. The frontend
    locates / highlights the cited span within this text."""

    verification_method: str | None = None
    """The Citation-Engine verification method backing this citation
    (Donna #6), e.g. ``ensemble_strict`` / ``ensemble_majority``.
    Mirrors the parent cell's ``verification_method`` onto each citation
    so the navigable UI can badge the ensemble-verified state per
    citation. ``None`` when the column isn't ensemble-verified or
    verification didn't confirm the value."""


class CellResult(BaseModel):
    """One cell in the tabular grid.

    Failed extraction renders as ``confidence='failed'`` + ``error``
    populated (Decision C-10). Successful extractions carry the
    extracted ``value`` plus the list of citations the Citation
    Engine grounded it against.
    """

    value: str | None = None
    """The extracted value. ``None`` when ``confidence='failed'``."""

    citations: list[Citation] = Field(default_factory=list)
    """Citations backing the cell value. Empty for failed cells or
    cells the Citation Engine couldn't ground."""

    confidence: CellConfidence
    tier_used: int | None = None
    """Inference tier actually routed for this cell. Set on success;
    None on failure before tier was selected."""

    cost_usd: Decimal | None = None
    """Per-cell cost. Sum across cells = ``cost_actual_usd`` on the
    parent execution row."""

    error: str | None = None
    """Error message when ``confidence='failed'``. Populated by the
    cell node's try/except (model error, no citation found,
    Citation Engine rejection)."""

    verification_method: str | None = None
    """The Citation-Engine verification method for the cell (Donna #6),
    e.g. ``ensemble_strict`` / ``ensemble_majority``. ``None`` when the
    column isn't ensemble-verified or verification didn't confirm the
    value (a verification miss never fails the cell)."""


class TabularRow(BaseModel):
    """One row in the tabular grid — all cells for a single document.

    Rows are returned in the order of the execution's
    ``document_ids`` array (NOT sorted by document name), so the grid
    matches the operator's selection order."""

    document_id: uuid.UUID
    document_name: str
    """Display name for the row label (the leftmost sticky column)."""

    cells: dict[str, CellResult]
    """Map of column name -> CellResult. Keys match the column names
    declared in the execution's column spec."""

    @model_validator(mode="before")
    @classmethod
    def _synthesize_cell_citations(cls, data: object) -> object:
        """Build display ``citations`` from each cell's persisted
        ``cited_chunk_ids``.

        The executor persists raw chunk references (``cited_chunk_ids``)
        rather than structured citations. Without this, the read-side
        ``CellResult.citations`` would always be empty even though the
        grounding chunks are recorded. We project each chunk id into a
        ``Citation`` using the row's ``document_id`` (the citation's
        source document), the cell's ``confidence``, and a deterministic
        synthetic ``citation_id``. Cells that already carry ``citations``
        (e.g., a future executor emitting real Citation-Engine rows) pass
        through untouched.
        """

        if not isinstance(data, dict):
            return data
        document_id = data.get("document_id")
        cells = data.get("cells")
        if document_id is None or not isinstance(cells, dict):
            return data
        for cell in cells.values():
            if not isinstance(cell, dict) or cell.get("citations"):
                continue
            chunk_ids = cell.get("cited_chunk_ids")
            if not isinstance(chunk_ids, list) or not chunk_ids:
                continue
            confidence = cell.get("confidence")
            verification_method = cell.get("verification_method")
            cell["citations"] = [
                {
                    "citation_id": str(uuid.uuid5(_TABULAR_CITATION_NAMESPACE, str(chunk_id))),
                    "document_id": str(document_id),
                    "chunk_id": str(chunk_id),
                    "confidence": confidence,
                    "verification_method": verification_method,
                }
                for chunk_id in chunk_ids
            ]
        return data


class TabularResults(BaseModel):
    """Aggregated grid shape persisted in ``tabular_executions.results``
    once status is ``completed``."""

    rows: list[TabularRow]


# --- Wire shapes for endpoints --------------------------------------------


class TabularExecutionCreate(BaseModel):
    """Request body for ``POST /api/v1/tabular/execute``.

    Either ``skill_name`` (resolved at execution start to snapshot
    the skill's ``lq_ai.columns``) OR ``columns`` (ad-hoc spec) is
    required. The handler resolves to the columns list either way
    before persisting.

    ``confirmed_cost_usd`` is the echo of the
    ``POST /api/v1/tabular/preview-cost`` response value; persisting
    it gives an audit trail of the operator confirming a specific
    cost ceiling before kickoff."""

    document_ids: list[uuid.UUID] = Field(min_length=1)
    skill_name: str | None = None
    columns: list[ColumnSpec] | None = None
    confirmed_cost_usd: Decimal | None = None


class TabularPreviewCostRequest(BaseModel):
    """Request body for ``POST /api/v1/tabular/preview-cost``.

    Cheaper synchronous endpoint; no execution row is created. The
    UI calls this before showing the cost-confirmation modal."""

    document_ids: list[uuid.UUID] = Field(min_length=1)
    skill_name: str | None = None
    columns: list[ColumnSpec] | None = None


class TabularPreviewCostResponse(BaseModel):
    """Response from ``POST /api/v1/tabular/preview-cost``.

    The UI uses ``estimated_cost_usd`` to decide whether to render
    the confirmation-checkbox gate (Decision C-5: gate above $1.00,
    no friction below).

    Ensemble columns cost more (Donna #6). When a column's effective
    ``ensemble_verification`` flag is true, each of its cells runs one
    Stage-4 ensemble pass (N judge-model calls) on top of the base
    extraction. ``estimated_cost_usd`` is the TOTAL — base extraction
    plus the ensemble premium — so the operator's confirmation reflects
    the real spend. ``ensemble_premium_usd`` and ``ensemble_cells_count``
    surface that premium explicitly."""

    cells_count: int
    estimated_tokens: int
    """Extraction tokens only. EXCLUDES ensemble judge-call tokens, whose
    cost is captured in ``ensemble_premium_usd`` — so this token figure
    and ``estimated_cost_usd`` are intentionally asymmetric (the dollar
    figure includes ensemble spend; the token figure does not)."""

    estimated_cost_usd: Decimal
    """Total estimated cost: base extraction (``per_cell_cost x
    cells_count``) plus ``ensemble_premium_usd``."""

    per_tier_breakdown: dict[str, int]
    """Map of tier name (e.g., ``"tier_2"``) -> cell count routed
    at that tier. Lets the operator see "20 cells at Tier 2,
    4 cells at Tier 4 for the high-stakes columns."""

    ensemble_cells_count: int = 0
    """Number of cells that will run ensemble verification — the count
    of cells whose column has an effective ``ensemble_verification`` of
    true (``n_docs x ensemble_column_count``). Zero when no column is
    ensemble-verified or the gateway has no ensemble configured."""

    ensemble_premium_usd: Decimal = Decimal("0")
    """The ensemble judge-call cost included in ``estimated_cost_usd``.
    Equals ``n_judges x per-judge-cost x ensemble_cells_count`` — one
    ensemble pass (N parallel judge calls) per ensemble cell. Zero when
    no cell is ensemble-verified."""


class TabularExecutionResponse(BaseModel):
    """Wire shape returned by every tabular execution endpoint
    (``POST /execute``, ``GET /executions/{id}``, etc.)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    parent_execution_id: uuid.UUID | None
    skill_name: str | None
    status: TabularExecutionStatus
    document_ids: list[uuid.UUID]
    document_names: list[str]
    """Filenames in the same order as ``document_ids`` — joined from
    ``documents → files.filename`` at response build time. Lets the
    UI render grid headers with human-readable labels from the moment
    the execution is created (before any row is populated by the
    worker), instead of falling back to raw UUIDs. Missing entries
    (file soft-deleted between create and fetch) surface as the empty
    string; the UI treats those as "deleted document" placeholders."""

    columns: list[ColumnSpec]
    results: TabularResults | None = None
    cost_estimate_usd: Decimal | None = None
    cost_actual_usd: Decimal | None = None
    error_text: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class TabularExecutionSummary(BaseModel):
    """Compact wire shape for the list endpoint
    (``GET /api/v1/tabular/executions``).

    Drops the (potentially large) ``results`` payload — operators
    fetch the full execution row when they open one."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    parent_execution_id: uuid.UUID | None
    skill_name: str | None
    status: TabularExecutionStatus
    document_count: int
    column_count: int
    cost_estimate_usd: Decimal | None = None
    cost_actual_usd: Decimal | None = None
    created_at: datetime
    completed_at: datetime | None = None


class TabularBulkOpRequest(BaseModel):
    """Request body for
    ``POST /api/v1/tabular/executions/{id}/bulk-op`` (M3-C4).

    Per Decision C-9, bulk ops spawn sibling execution rows rather
    than mutating the original grid. The sibling carries
    ``parent_execution_id`` set to this execution's ID."""

    op: Literal["redline", "summarize"]
    column_name: str
    skill_name_override: str | None = None
    """Override the default skill used for the operation. Default for
    ``redline`` is ``nda-review`` (or skill matched to the parent
    execution's skill family); default for ``summarize`` is the
    deployment-configured summary skill."""


__all__ = [
    "CellConfidence",
    "CellResult",
    "Citation",
    "ColumnSpec",
    "TabularBulkOpRequest",
    "TabularExecutionCreate",
    "TabularExecutionResponse",
    "TabularExecutionStatus",
    "TabularExecutionSummary",
    "TabularPreviewCostRequest",
    "TabularPreviewCostResponse",
    "TabularResults",
    "TabularRow",
]
