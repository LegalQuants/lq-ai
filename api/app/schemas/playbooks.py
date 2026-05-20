"""Pydantic schemas for the Playbook engine — M3-A1.

Wire shapes for the ``/api/v1/playbooks`` and
``/api/v1/playbook-executions`` surfaces ([PRD §3.7](docs/PRD.md#37-playbooks)).
The ORM models live in :mod:`app.models.playbook`; this module is the
request / response surface for the endpoints that land in M3-A2.

PRD §3.7 sketches the ``Playbook`` and ``Position`` shapes; this module
adds the missing pieces:

* :class:`FallbackTier` — the PRD references ``List[FallbackTier]`` on
  ``Position`` but does not spec the shape. We pick a minimal,
  forward-compatible shape: ranked tier + description + alternative
  language. Stored as JSONB so additional fields can be added later
  without a migration.
* :class:`PlaybookExecutionStatus` — enum literal for the lifecycle
  the executor (M3-A2) walks: ``pending → running → completed | error``.

The schemas live as their own module rather than alongside
``chats.py`` / ``projects.py`` so the surface is discoverable for the
M3-A2 executor and the M3-A4 UI without grep-spelunking.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PlaybookExecutionStatus = Literal["pending", "running", "completed", "error"]
"""Lifecycle states for a :class:`PlaybookExecution`. Matches the CHECK
constraint on ``playbook_executions.status`` (migration 0031)."""

PositionSeverity = Literal["critical", "high", "medium", "low"]
"""Severity bucket for a missing position. Matches the CHECK constraint
on ``playbook_positions.severity_if_missing`` (migration 0031) and the
``severity_if_missing`` enum documented in [PRD §3.7](docs/PRD.md#37-playbooks)."""


class FallbackTier(BaseModel):
    """One acceptable alternative to a position's standard language.

    The PRD's ``Position`` schema references ``List[FallbackTier]`` but
    does not define ``FallbackTier``. We pick a minimal, ranked shape:

    * ``rank`` — 1-based order of preference (1 = preferred fallback,
      2 = next, etc.).
    * ``description`` — what makes this tier acceptable
      (e.g., "12-month liability cap" vs. the standard "uncapped").
    * ``language`` — the actual clause text the playbook will accept.

    Stored as JSONB on ``playbook_positions.fallback_tiers`` so
    additional fields (e.g., approval workflow, escalation contact)
    can land in a future iteration without a schema migration.
    """

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1, description="1-based order of preference.")
    description: str = Field(description="Why this tier is acceptable.")
    language: str = Field(description="The alternative clause text.")


class Position(BaseModel):
    """One issue in a playbook — org's standard + fallbacks for a clause.

    Mirrors the ``Position`` shape in [PRD §3.7](docs/PRD.md#37-playbooks)
    with the ``id`` and ``position_order`` fields the storage layer
    needs. ``detection_keywords`` and ``detection_examples`` feed the
    M3-A2 executor's retrieval step (lexical + embedding match).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    issue: str = Field(description='e.g. "Limitation of Liability".')
    description: str = ""
    standard_language: str = Field(description="The org's preferred clause.")
    fallback_tiers: list[FallbackTier] = Field(
        default_factory=list,
        description="Ranked acceptable alternatives.",
    )
    redline_strategy: str = Field(
        default="",
        description="How to redline if the contract deviates.",
    )
    severity_if_missing: PositionSeverity
    detection_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords for the executor's lexical match step.",
    )
    detection_examples: list[str] = Field(
        default_factory=list,
        description="Example clauses for the executor's embedding match step.",
    )
    position_order: int = Field(
        default=0,
        ge=0,
        description="Ascending walk order. Stable per playbook.",
    )


class PositionCreate(BaseModel):
    """Request shape for creating a position — same as :class:`Position` minus ``id``."""

    model_config = ConfigDict(extra="forbid")

    issue: str
    description: str = ""
    standard_language: str
    fallback_tiers: list[FallbackTier] = Field(default_factory=list)
    redline_strategy: str = ""
    severity_if_missing: PositionSeverity
    detection_keywords: list[str] = Field(default_factory=list)
    detection_examples: list[str] = Field(default_factory=list)
    position_order: int = Field(default=0, ge=0)


class Playbook(BaseModel):
    """Full playbook — header plus ordered positions.

    Mirrors the ``Playbook`` shape in [PRD §3.7](docs/PRD.md#37-playbooks).
    ``contract_type`` is free-form text per PRD; the canonical values
    used by the built-in playbooks are ``"NDA"``, ``"NDA-unilateral"``,
    ``"MSA-SaaS"``, ``"MSA-Commercial"``, ``"DPA"``, but operators may
    define their own.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    contract_type: str
    description: str = ""
    version: str = "1.0.0"
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    positions: list[Position] = Field(default_factory=list)


class PlaybookCreate(BaseModel):
    """Request shape for ``POST /api/v1/playbooks``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    contract_type: str
    description: str = ""
    version: str = "1.0.0"
    positions: list[PositionCreate] = Field(default_factory=list)


class PlaybookUpdate(BaseModel):
    """Request shape for ``PATCH /api/v1/playbooks/{id}`` — M3-A6 Phase 2.

    Every field is optional; the server treats a missing field as
    "leave alone." The exception is ``positions``: when supplied, the
    server **replaces the entire positions list atomically** (drops the
    old rows, inserts the new ones in a single transaction). Per-position
    diff/patch is not supported — the wizard's "edit then save" flow
    always sends the full set, and the alternative (PATCH per position)
    would introduce id-vs-order-vs-content ambiguities for marginal
    value. To leave positions alone, omit the field.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    contract_type: str | None = None
    description: str | None = None
    version: str | None = None
    positions: list[PositionCreate] | None = None


class PlaybookExecution(BaseModel):
    """One execution of a playbook against a target document.

    ``results`` is a free-form JSONB payload populated by the M3-A2
    executor; this schema doesn't pin its shape because the executor
    surface is still being defined. The wire-level guarantee at this
    layer is just "if status='completed', results is present; if
    status='error', error text is populated."
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    playbook_id: uuid.UUID
    target_document_id: uuid.UUID
    user_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    status: PlaybookExecutionStatus
    results: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class PlaybookExecutionCreate(BaseModel):
    """Request shape for ``POST /api/v1/playbooks/{id}/execute``.

    ``project_id`` is optional — the executor uses it for RBAC scoping
    and to inherit the project's ``minimum_inference_tier`` /
    ``ensemble_verification`` flags. A null ``project_id`` runs the
    playbook against the document in the caller's personal scope.
    """

    model_config = ConfigDict(extra="forbid")

    target_document_id: uuid.UUID
    project_id: uuid.UUID | None = None


# ---------------------------------------------------------------------------
# Easy Playbook generation (M3-A6 Phase 5)
# ---------------------------------------------------------------------------


EasyPlaybookGenerationStatus = Literal["pending", "running", "completed", "error"]
"""Lifecycle states for an :class:`EasyPlaybookGeneration` row. Matches
the CHECK constraint on ``easy_playbook_generations.status`` (migration
0035) and the M3-A6 wizard's polling state machine."""


class EasyPlaybookGenerationCreate(BaseModel):
    """Request shape for ``POST /api/v1/playbooks/easy``.

    ``document_ids`` is the corpus the wizard's Step 1 upload step
    accumulated; the user-attorney also names the playbook (via the
    optional ``name``) and identifies the contract family
    (``contract_type``) so the extractor + assembly LLM calls have
    family-appropriate context.

    Per M3-A6 §3.3 the uploaded documents are persisted to the user's
    library by default. ``persist_documents_after_generation=False``
    is reserved for a future "ephemeral upload" mode and is not
    consumed by Phase 5 — the field is accepted to lock the wire
    shape now and avoid a body-shape migration when the mode lands.
    """

    model_config = ConfigDict(extra="forbid")

    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    contract_type: str = Field(min_length=1)
    name: str | None = Field(
        default=None,
        description=(
            "Playbook name the wizard's Step 1 collected. Falls back to "
            "an auto-generated 'Generated {contract_type} Playbook' if omitted."
        ),
    )
    persist_documents_after_generation: bool = Field(
        default=True,
        description=(
            "Reserved for a future 'ephemeral upload' mode. Currently always "
            "true — uploaded documents persist to the user's library."
        ),
    )


class EasyPlaybookGeneration(BaseModel):
    """One Easy Playbook generation row.

    Returned by ``POST /api/v1/playbooks/easy`` (at status ``pending``)
    and by ``GET /api/v1/playbooks/easy/{id}`` (the wizard's Step 2
    polling target).

    ``draft_playbook`` is the assembled :class:`PlaybookCreate` shape
    when status is ``completed`` — the wizard's Step 3 inline editor
    binds to this. The free-form ``dict`` typing here matches the
    JSONB column; the wizard validates by ``PlaybookCreate.model_validate``
    on render and again at save time (POST /api/v1/playbooks).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None = None
    contract_type: str
    status: EasyPlaybookGenerationStatus
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    draft_playbook: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
