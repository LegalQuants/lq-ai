"""Pydantic schemas for the file-upload surface (Task C4).

These match the ``File`` schema in ``docs/api/backend-openapi.yaml``. The
ORM model lives in ``app.models.file``; this module is purely the wire
shape returned by the file endpoints (``POST /api/v1/files``,
``GET /api/v1/files/{id}``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IngestionStatus = Literal["pending", "processing", "ready", "failed"]


class FileMetadata(BaseModel):
    """Wire shape for the ``File`` schema in backend-openapi.yaml.

    Mirrors the YAML's ``File`` definition. ``page_count`` and
    ``character_count`` are populated by the document pipeline (Task C5)
    once the file moves to ``ingestion_status='ready'``; until then they
    are NULL and serialize as JSON ``null``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    project_id: uuid.UUID | None = None
    filename: str
    mime_type: str
    size_bytes: int
    hash_sha256: str = Field(
        ...,
        description=(
            "SHA-256 of the file bytes (hex, lowercase). Computed during "
            "the streaming upload; stable for the lifetime of the row."
        ),
    )
    ingestion_status: IngestionStatus
    page_count: int | None = None
    character_count: int | None = None
    # M3-A6 Phase 6: the parsed-content ``documents`` row's UUID,
    # distinct from ``id`` (the File UUID). ``None`` until the C5 parse
    # pipeline produces a document row; the Easy Playbook wizard polls
    # GET /files/{id} until this flips non-null, then passes the value
    # to POST /playbooks/easy in ``document_ids``.
    document_id: uuid.UUID | None = None
    created_at: datetime
