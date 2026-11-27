"""Closed, metadata-only contracts for the internal workspace-event foundation.

These are service contracts, not a public ingestion API. Source adapters must
establish source access and lifecycle before calling the service; none is wired
in this slice. New source kinds require an explicitly reviewed contract change.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SourceKind = Literal["internal"]
EventType = Literal["finding.created"]
Sensitivity = Literal["confidential", "privileged"]


class EventContract(BaseModel):
    """Reject additional fields, including accidental raw source payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class EventProvenance(EventContract):
    """The bounded producer identity; no arbitrary metadata or source content."""

    producer: Literal["autonomous"] = "autonomous"


class EventSource(EventContract):
    """Opaque internal source identity, scoped by the separately supplied owner."""

    source_kind: SourceKind = "internal"
    source_ref: uuid.UUID


class WorkspaceEventCreate(EventSource):
    """Trusted backend input; observation time, identity and status are server-owned."""

    event_type: EventType = "finding.created"
    project_id: uuid.UUID | None = None
    occurred_at: AwareDatetime | None = None
    provenance: EventProvenance = Field(default_factory=EventProvenance)
    sensitivity: Sensitivity = "confidential"


class EventCursor(EventContract):
    """Stable chronological boundary, applied only within the querying owner's scope."""

    occurred_at: AwareDatetime
    event_id: uuid.UUID


class WorkspaceEventQuery(EventContract):
    """Bounded oldest-first query with a half-open [start_at, end_at) UTC window."""

    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    source_kind: SourceKind | None = None
    event_type: EventType | None = None
    project_id: uuid.UUID | None = None
    after: EventCursor | None = None
    limit: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def check_window(self) -> WorkspaceEventQuery:
        """Reject reversed and zero-width time windows instead of hiding mistakes."""
        if self.start_at is not None and self.end_at is not None and self.start_at >= self.end_at:
            raise ValueError("start_at must precede end_at")
        return self


class WorkspaceEventRead(EventContract):
    """Exportable event metadata; a later Today projection will resolve source content."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, from_attributes=True
    )

    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None
    source_kind: SourceKind
    source_ref: uuid.UUID
    event_type: EventType
    status: Literal["recorded"]
    occurred_at: AwareDatetime
    observed_at: AwareDatetime
    provenance: EventProvenance
    sensitivity: Sensitivity
    dedupe_digest: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
