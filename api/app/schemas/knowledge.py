"""Pydantic schemas for the knowledge-bases surface (Task C6).

Wire shapes for ``/api/v1/knowledge-bases`` matching ``KnowledgeBase``,
``KnowledgeBaseCreate``, ``KnowledgeBaseUpdate``, ``KBQueryRequest``,
and ``SearchResult`` in ``docs/api/backend-openapi.yaml``. The ORM
models live in ``app.models.knowledge``; this module is the
request/response surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

NAME_MAX_LEN: int = 200
"""Hard cap on KB ``name``. Matches the DB CHECK constraint."""

DESCRIPTION_MAX_LEN: int = 2000
"""Soft cap on the optional ``description`` field. Defensive — the DB
column is unrestricted ``TEXT``."""

DEFAULT_TOP_K: int = 10
"""Default top-k for the KB query handler."""

MAX_TOP_K: int = 50
"""Maximum top-k for the KB query handler — caps the SQL LIMIT we issue.
Beyond this the operator should be using a dedicated retrieval API or
batch path; the chat-driving query path is bounded for predictable
prompt-size budgets."""


KnowledgeBaseName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=NAME_MAX_LEN, strip_whitespace=True),
]
"""1-200 chars, leading/trailing whitespace stripped."""

KnowledgeBaseDescription = Annotated[
    str,
    StringConstraints(max_length=DESCRIPTION_MAX_LEN),
]
"""Free-form description; capped at 2000 chars."""

HybridAlpha = Annotated[float, Field(ge=0.0, le=1.0)]
"""Hybrid retrieval weight in [0, 1]. 0 means vector-only; 1 means
FTS-only; 0.5 means balanced."""


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class KnowledgeBaseCreateRequest(BaseModel):
    """``KnowledgeBaseCreate`` from backend-openapi.yaml."""

    model_config = ConfigDict(extra="forbid")

    name: KnowledgeBaseName
    description: KnowledgeBaseDescription | None = None
    project_id: uuid.UUID | None = None
    hybrid_alpha: HybridAlpha = 0.5


class KnowledgeBaseUpdateRequest(BaseModel):
    """``KnowledgeBaseUpdate`` from backend-openapi.yaml.

    All fields optional. PATCH applies only the fields the caller sets;
    the handler uses ``model_dump(exclude_unset=True)`` to distinguish
    "absent" from "explicit null."
    """

    model_config = ConfigDict(extra="forbid")

    name: KnowledgeBaseName | None = None
    description: KnowledgeBaseDescription | None = None
    project_id: uuid.UUID | None = None
    hybrid_alpha: HybridAlpha | None = None
    archived: bool | None = None
    """When set, archive (true) or unarchive (false) the KB. Same
    pattern as the projects PATCH archived flag."""


class AttachFileRequest(BaseModel):
    """``POST /api/v1/knowledge-bases/{id}/files`` body."""

    model_config = ConfigDict(extra="forbid")

    file_id: uuid.UUID


class KBQueryRequest(BaseModel):
    """``POST /api/v1/knowledge-bases/{id}/query`` body.

    ``hybrid_alpha`` overrides the KB's stored alpha for this query
    only. Out-of-bound values are caught by Pydantic's ``ge`` / ``le``.

    ``chat_id`` is set by the chat surface so the handler can write a
    ``inference.kb_chunks_retrieved`` audit row scoped to the chat —
    that row is what Receipts (Wave D.1 T5/T6) renders as a
    "📎 KB retrieval" event (T7). Omit for standalone retrieval
    (no audit row is written).
    """

    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, StringConstraints(min_length=1, max_length=10_000)]
    top_k: Annotated[int, Field(ge=1, le=MAX_TOP_K)] = DEFAULT_TOP_K
    hybrid_alpha: HybridAlpha | None = None
    chat_id: uuid.UUID | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class KnowledgeBaseResponse(BaseModel):
    """``KnowledgeBase`` schema from backend-openapi.yaml.

    ``file_count`` and ``chunk_count`` are computed at fetch-time by
    the handler; they don't live on the row.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    project_id: uuid.UUID | None = None
    name: str
    description: str | None = None
    hybrid_alpha: float
    file_count: int = 0
    chunk_count: int = 0
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class KBFileResponse(BaseModel):
    """Wire shape for one row of ``GET /knowledge-bases/{id}/files`` (Wave C).

    Mirrors the ``File`` schema in ``backend-openapi.yaml`` (the same
    shape ``POST /files`` returns) so the Knowledge surface can render
    per-doc ingestion status without a follow-up fetch per row. The
    underlying join carries ``attached_at`` — surfaced as ``attached_at``
    so the UI can sort by attachment time independently of file creation
    time (a user may attach an old file to a new KB).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    project_id: uuid.UUID | None = None
    filename: str
    mime_type: str
    size_bytes: int
    hash_sha256: str
    ingestion_status: str
    ingestion_error: str | None = None
    # M3-0.3 / DE-276: document-level ingest status surfaces silent
    # embed failures the file-level ``ingestion_status`` cannot detect.
    # Both fields are optional on the wire because pre-document file
    # rows (parse not yet attempted / parse failed before document
    # creation) have no row in ``documents`` to read from.
    ingest_status: str | None = None
    ingest_failure_reason: str | None = None
    page_count: int | None = None
    character_count: int | None = None
    # M3-A4: document_id is the parsed-content row's UUID, distinct from
    # ``id`` (the File UUID). Surfaces here so playbook-execute callers
    # can resolve File → Document without an extra fetch; null until the
    # C5 parse pipeline produces a documents row.
    document_id: uuid.UUID | None = None
    created_at: datetime
    attached_at: datetime


class SearchResultChunk(BaseModel):
    """One chunk in a search-result envelope.

    ``file_name`` is denormalized from ``files.filename`` so the UI can
    render the source label without a follow-up fetch. The chunk's own
    fields match :class:`app.models.document.DocumentChunk`.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    document_id: uuid.UUID
    file_id: uuid.UUID
    file_name: str
    content: str
    page_start: int | None = None
    page_end: int | None = None
    char_offset_start: int
    char_offset_end: int


class SearchResultScores(BaseModel):
    """Normalized score components for a search result.

    ``vector`` is the normalized cosine-similarity (1 - cosine_distance,
    clamped to [0, 1]); ``fts`` is the normalized ``ts_rank_cd`` score.
    Both are min-max-normalized across the candidate set per ADR 0008.
    """

    model_config = ConfigDict(extra="forbid")

    vector: float
    fts: float


class SearchResult(BaseModel):
    """``SearchResult`` schema from backend-openapi.yaml."""

    model_config = ConfigDict(extra="forbid")

    chunk: SearchResultChunk
    score: float
    """The combined hybrid score: ``(1 - alpha) * vector + alpha * fts``."""
    score_components: SearchResultScores


class KBQueryResponse(BaseModel):
    """``POST /api/v1/knowledge-bases/{id}/query`` response envelope.

    The brief asks for ranked chunks with scores; we wrap them in an
    object with the resolved ``hybrid_alpha`` so consumers can verify
    which weighting produced the ranking.
    """

    model_config = ConfigDict(extra="forbid")

    results: list[SearchResult]
    hybrid_alpha: float
