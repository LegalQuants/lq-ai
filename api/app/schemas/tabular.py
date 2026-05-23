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

from pydantic import BaseModel, ConfigDict, Field

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
    no friction below)."""

    cells_count: int
    estimated_tokens: int
    estimated_cost_usd: Decimal
    per_tier_breakdown: dict[str, int]
    """Map of tier name (e.g., ``"tier_2"``) -> cell count routed
    at that tier. Lets the operator see "20 cells at Tier 2,
    4 cells at Tier 4 for the high-stakes columns."""


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
