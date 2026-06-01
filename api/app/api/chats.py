"""Chats and messages endpoints — Task C3 (Chat service + persistence).

Surface (per ``docs/api/backend-openapi.yaml``):

* ``POST   /api/v1/chats``                                — create.
* ``GET    /api/v1/chats``                                — list with cursor
  pagination and ``project_id`` / ``archived`` filters.
* ``GET    /api/v1/chats/{chat_id}``                      — fetch single.
* ``PATCH  /api/v1/chats/{chat_id}``                      — partial update
  (title, archived).
* ``DELETE /api/v1/chats/{chat_id}``                      — soft-delete.
* ``GET    /api/v1/chats/{chat_id}/messages``             — list messages
  with cursor pagination.
* ``POST   /api/v1/chats/{chat_id}/messages``             — **the keystone**:
  persist user message → forward to gateway → persist assistant message
  (or stream SSE chunks and persist the assistant row at end-of-stream).

All endpoints inherit the auth + must-change-password gate from the
chats router's router-level ``Depends(get_active_user)`` in
``app.api.__init__`` (B2 pattern). Each handler also takes
``ActiveUser`` directly so the user object is available for owner
checks (FastAPI dedupes the dependency).

**Per-user isolation.** Chats are scoped to ``owner_id``. Cross-user
access returns 404, not 403, to avoid leaking existence (same posture
as C4 / files and C7 / projects).

**The keystone POST /messages flow** (the heart of C3):

1. Validate auth + chat ownership (404 on cross-user).
2. Persist a ``user`` message row (with the request's ``skills`` list
   captured as ``applied_skills``).
3. Auto-rename the chat from the first user message if its title is
   still ``"New chat"``.
4. Generate a UUID for the eventual assistant message.
5. Forward to the gateway via :class:`GatewayClient`. Pass
   ``lq_ai_chat_id`` and ``lq_ai_message_id`` so the gateway's routing
   log row carries the same identifiers (closing the A2-deferred FKs).
6. Streaming: emit OpenAI-style SSE chunks per ADR 0007. Persist the
   assistant row at end-of-stream — partial writes during streaming
   would expose half-built rows to readers. If the stream fails
   mid-way, persist a row with whatever content was received and the
   error code populated (full audit; clients can resume).
7. Non-streaming: persist the assistant row from the gateway's
   complete response.

We do NOT write ``inference_routing_log`` from the backend — the
gateway is the canonical writer (B4). The backend persists the message
row; the gateway writes the routing log with ``message_id`` pointing at
that same row.
"""

from __future__ import annotations

import json as _json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

# `trace` is for add_event() on the active span; spans use app.observability_helpers.
from opentelemetry import trace
from pydantic import BaseModel, ValidationError as PydanticValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.api.skills import _resolve_skill_for_user
from app.audit import audit_action
from app.citation import extract_citations, verify
from app.citation.cost import estimate_judge_call_cost_usd
from app.clients.gateway import EnsembleConfig, GatewayClient, get_gateway_client
from app.db.session import get_db
from app.errors import LQAIError, NotFound, ValidationError
from app.knowledge.embed import DEFAULT_EMBEDDING_MODEL, request_embedding_vector
from app.knowledge.retrieval import HybridSearchResult, hybrid_search
from app.models.chat import Chat, Message, MessageCitation
from app.models.document import Document
from app.models.file import File
from app.models.inference import InferenceRoutingLog
from app.models.knowledge import KnowledgeBase
from app.models.project import Project
from app.models.project_knowledge_base import ProjectKnowledgeBase
from app.models.user import User
from app.observability_helpers import get_tracer, record_attributes
from app.schemas.chats import (
    LIST_LIMIT_DEFAULT,
    LIST_LIMIT_MAX,
    ChatCreateRequest,
    ChatListResponse,
    ChatResponse,
    ChatUpdateRequest,
    Cursor,
    MessageCreateRequest,
    MessageListResponse,
    MessagePostResponse,
    decode_cursor,
    derive_chat_title,
    encode_cursor,
    message_to_response,
    usd_to_micros,
)
from app.schemas.gateway import (
    ChatCompletionMessage,
    ChatCompletionRequest,
    InlineSkillRef,
)
from app.skills.registry import MutableSkillRegistry, SkillRegistry

router = APIRouter(prefix="/chats", tags=["chats"])
log = logging.getLogger(__name__)


# Wave D.2 Task 2.7 — send-time slash fallback. If the user's content
# starts with ``/<token>`` and the frontend didn't pre-resolve it, the
# backend retries against the merged catalogue. Token grammar matches
# the autocomplete + ``user_skills.slash_alias`` shape: lowercase
# alphanumerics or hyphens, 1-64 chars (slugs can be slightly longer
# than aliases — the check that follows is by-value, not by-length, so
# being a touch permissive here is fine), followed by whitespace.
_LEADING_SLASH_RE = re.compile(r"^/([a-z0-9-]{1,64})\s")


async def _maybe_resolve_leading_slash(
    request: Request, db: AsyncSession, user: User, content: str
) -> tuple[str | None, str, bool]:
    """If ``content`` starts with ``/slug ``, try to resolve it to a skill.

    Returns a 3-tuple ``(resolved_slug, content, slash_unresolved)``:

    * ``resolved_slug`` — the canonical skill slug if resolution
      succeeded, else ``None``.
    * ``content`` — the original content with the leading ``/slug ``
      token stripped *only when resolution succeeded*; otherwise
      unchanged (the user's typo is forwarded verbatim so they still
      get a real LLM answer).
    * ``slash_unresolved`` — ``True`` when the regex matched but no row
      resolved (either slug or slash_alias). The handler uses this to
      flip the matching flag on the response body so the UI can hint.

    The function is no-op when ``content`` doesn't start with
    ``/<token><whitespace>`` — returns ``(None, content, False)``.
    """

    m = _LEADING_SLASH_RE.match(content)
    if not m:
        return None, content, False

    token = m.group(1)
    # Try slug match first (built-ins and user-shadows), then alias
    # match against ``slash_alias`` (user/team rows only — built-ins
    # don't carry an alias column per ADR 0012 / Wave D.2 Task 2.4).
    resolved = await _resolve_skill_for_user(request, db, user=user, slug=token)
    if resolved is None:
        resolved = await _resolve_skill_for_user(request, db, user=user, slash_alias="/" + token)

    if resolved is None:
        return None, content, True
    slug_value = resolved.get("slug")
    if not isinstance(slug_value, str):
        # Defensive: the merged-catalogue dict always carries ``slug``,
        # but if it ever doesn't, treat as unresolved rather than
        # crashing the send path.
        return None, content, True
    return slug_value, content[m.end() :], False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_chat_id(chat_id: str) -> uuid.UUID:
    """Reject non-UUID chat ids per the OpenAPI sketch's ``{chat_id}: uuid``."""

    try:
        return uuid.UUID(chat_id)
    except ValueError as exc:
        raise ValidationError(
            "chat_id must be a UUID",
            details={"chat_id": chat_id},
        ) from exc


async def _load_visible_chat(
    db: AsyncSession,
    chat_id: uuid.UUID,
    owner_id: uuid.UUID,
    *,
    include_archived: bool = False,
) -> Chat:
    """Load a chat row scoped to the caller; 404 on miss / cross-user.

    ``include_archived=True`` surfaces archived rows (used by GET so
    archived chats can still be viewed; list excludes them by default).
    """

    stmt = select(Chat).where(Chat.id == chat_id, Chat.owner_id == owner_id)
    if not include_archived:
        stmt = stmt.where(Chat.archived_at.is_(None))

    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFound(
            f"Chat {chat_id} not found.",
            details={"chat_id": str(chat_id)},
        )
    return row


async def _validate_owned_file_ids(
    db: AsyncSession,
    file_ids: list[str],
    owner_id: uuid.UUID,
) -> list[str]:
    """Validate caller-owned, non-deleted file ids for per-message attach.

    Mirrors :func:`app.api.files._load_visible_file`'s ownership posture:
    each id must parse as a UUID and resolve to a non-soft-deleted
    ``files`` row owned by ``owner_id``. Any id that is malformed,
    nonexistent, soft-deleted, or owned by another user raises
    :class:`NotFound` (404) — **id-probing-safe**: a foreign file is
    indistinguishable from a nonexistent one, so the caller can't probe
    for the existence of files they don't own (per CLAUDE.md
    information-leakage avoidance + the C4 file-ownership brief).

    Returns the validated ids as strings (deduped, order-preserving) for
    forwarding to the gateway as ``lq_ai_file_ids``. Empty input returns
    an empty list without a DB round-trip — the back-compatible no-op
    path.
    """

    if not file_ids:
        return []

    # Parse + dedupe while preserving first-seen order. A malformed id is
    # a 404 (not a 422) so it's indistinguishable from "not yours" — the
    # caller learns nothing about which ids exist.
    parsed: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for raw in file_ids:
        try:
            fid = uuid.UUID(raw)
        except (ValueError, AttributeError) as exc:
            raise NotFound(
                f"File {raw} not found.",
                details={"file_id": str(raw)},
            ) from exc
        if fid not in seen:
            seen.add(fid)
            parsed.append(fid)

    # Single SELECT for all ids, scoped to owner + not-deleted. Any id
    # that doesn't come back is 404'd (the loop above already deduped).
    stmt = select(File.id).where(
        File.id.in_(parsed),
        File.owner_id == owner_id,
        File.deleted_at.is_(None),
    )
    found = set((await db.execute(stmt)).scalars().all())
    for fid in parsed:
        if fid not in found:
            raise NotFound(
                f"File {fid} not found.",
                details={"file_id": str(fid)},
            )

    return [str(fid) for fid in parsed]


async def _load_attached_file_contexts(
    db: AsyncSession,
    file_ids: list[str],
    owner_id: uuid.UUID,
) -> list[tuple[str, str]]:
    """Load ``(filename, content)`` for per-message attached files, in caller order.

    The text is :attr:`Document.normalized_content` (the canonical
    PyMuPDF character stream) joined ``File → Document`` on
    ``Document.file_id == File.id``. The query is **owner-scoped**
    (``owner_id == ... AND deleted_at IS NULL``) as defense in depth —
    even though :func:`_validate_owned_file_ids` has already validated
    ownership upstream, this read re-asserts the boundary rather than
    trusting the caller-supplied ids.

    Files are returned in the order their ids appear in ``file_ids``
    (deduped, first-seen). A file with **no Document row yet** (ingestion
    pending or failed) or with empty ``normalized_content`` is OMITTED
    from the result — it was validly attached, it just has no extractable
    text to inject. This is graceful, not an error: the send still
    proceeds, the file simply contributes no document-context block.

    Empty input returns an empty list without a DB round-trip.
    """

    if not file_ids:
        return []

    parsed: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for raw in file_ids:
        try:
            fid = uuid.UUID(raw)
        except (ValueError, AttributeError):
            # Upstream validation already 404s malformed ids; if a bad id
            # reaches here it simply contributes no context.
            continue
        if fid not in seen:
            seen.add(fid)
            parsed.append(fid)

    stmt = (
        select(File.id, File.filename, Document.normalized_content)
        .join(Document, Document.file_id == File.id)
        .where(
            File.id.in_(parsed),
            File.owner_id == owner_id,
            File.deleted_at.is_(None),
        )
    )
    rows = (await db.execute(stmt)).all()
    by_id: dict[uuid.UUID, tuple[str, str]] = {}
    for row in rows:
        fid, filename, content = row[0], row[1], row[2]
        # Omit files with no extractable text (empty / whitespace-only).
        if content and content.strip():
            by_id[fid] = (filename, content)

    # Preserve caller-supplied order; files without a Document or with no
    # text simply don't appear in ``by_id`` and are skipped.
    return [by_id[fid] for fid in parsed if fid in by_id]


async def _message_count(db: AsyncSession, chat_id: uuid.UUID) -> int:
    """Return the count of messages for a chat (single COUNT(*) query)."""

    stmt = select(func.count()).select_from(Message).where(Message.chat_id == chat_id)
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def _message_counts_for(db: AsyncSession, chat_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Return per-chat message counts in a single GROUP BY query."""

    if not chat_ids:
        return {}
    stmt = (
        select(Message.chat_id, func.count())
        .where(Message.chat_id.in_(chat_ids))
        .group_by(Message.chat_id)
    )
    result = await db.execute(stmt)
    counts = {row[0]: int(row[1]) for row in result.all()}
    # Chats with zero messages don't appear in the GROUP BY result;
    # backfill with 0 so callers get a complete map.
    for cid in chat_ids:
        counts.setdefault(cid, 0)
    return counts


async def _serialize_chat(
    db: AsyncSession,
    chat: Chat,
    *,
    message_count: int | None = None,
) -> ChatResponse:
    """Build the ``ChatResponse`` for a single row."""

    if message_count is None:
        message_count = await _message_count(db, chat.id)
    return ChatResponse(
        id=chat.id,
        owner_id=chat.owner_id,
        project_id=chat.project_id,
        title=chat.title,
        archived_at=chat.archived_at,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        message_count=message_count,
    )


def _decode_cursor_or_400(value: str) -> Cursor:
    """Decode a wire cursor; raise ValidationError on malformed input."""

    try:
        return decode_cursor(value)
    except (ValueError, PydanticValidationError) as exc:
        raise ValidationError(
            "cursor is malformed",
            details={"cursor": value},
        ) from exc


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ChatResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new chat",
    description=(
        "Create a chat owned by the caller. ``title`` defaults to "
        '"New chat" when omitted; the API auto-renames the chat from '
        "the first user message's first 80 chars on the first POST "
        "/messages call."
    ),
)
async def create_chat(
    payload: ChatCreateRequest,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChatResponse:
    chat = Chat(
        owner_id=user.id,
        project_id=payload.project_id,
        title=payload.title or "New chat",
    )
    db.add(chat)
    await db.flush()
    await db.commit()
    await db.refresh(chat)

    log.info(
        "chat created",
        extra={
            "event": "chat_created",
            "user_id": str(user.id),
            "chat_id": str(chat.id),
            "project_id": str(chat.project_id) if chat.project_id else None,
        },
    )

    return await _serialize_chat(db, chat, message_count=0)


class ChatSearchHit(BaseModel):
    """One row in the chat-search response.

    Carries the matching chat ID + title for navigation, the per-row
    relevance rank from the FTS engine, and a snippet of the matching
    message body (or the title itself when only the title matched).
    """

    chat_id: uuid.UUID
    title: str
    snippet: str
    match_source: str
    """Either ``'title'`` (the chat title matched) or ``'message'``
    (a message body matched)."""

    rank: float
    """The Postgres ``ts_rank_cd`` score for the matching row. Higher
    means a better match; relative within a single response only."""

    created_at: datetime
    updated_at: datetime


class ChatSearchResponse(BaseModel):
    items: list[ChatSearchHit]
    query: str


@router.get(
    "/search",
    response_model=ChatSearchResponse,
    summary="Full-text search across the caller's chats + messages (PRD §1.7)",
)
async def search_chats(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ChatSearchResponse:
    """GET /api/v1/chats/search — Postgres FTS over chats + messages.

    Wave B — PRD §1.7 acceptance criterion: "search prior chats."
    Uses ``websearch_to_tsquery`` against the ``title_tsv`` /
    ``content_tsv`` generated columns (migration 0016) so the query
    parser is the friendly Google-flavored one (no operator escaping
    required). Results are ranked by ``ts_rank_cd`` and capped at
    ``limit``.

    Owner-scoped: only the caller's own chats + messages are searched.
    Archived chats are excluded — the search affordance is for finding
    active work, not historic cleanup.
    """

    from sqlalchemy import literal, text as sa_text

    tsquery = func.websearch_to_tsquery("english", q)

    # Title hits — each chat contributes at most one row (one title).
    title_subq = (
        select(
            Chat.id.label("chat_id"),
            Chat.title.label("title"),
            Chat.title.label("snippet"),
            literal("title").label("match_source"),
            func.ts_rank_cd(sa_text("chats.title_tsv"), tsquery).label("rank"),
            Chat.created_at.label("created_at"),
            Chat.updated_at.label("updated_at"),
        )
        .where(
            Chat.owner_id == user.id,
            Chat.archived_at.is_(None),
            sa_text("chats.title_tsv @@ websearch_to_tsquery('english', :q)"),
        )
        .params(q=q)
    )

    # Message hits — DISTINCT ON (chat_id) to surface only the
    # highest-ranking message per chat (Postgres extension; falls back
    # to row_number window if portability matters later).
    message_subq = (
        select(
            Message.chat_id.label("chat_id"),
            Chat.title.label("title"),
            func.ts_headline(
                "english",
                Message.content,
                tsquery,
                "MaxFragments=2, MinWords=5, MaxWords=20",
            ).label("snippet"),
            literal("message").label("match_source"),
            func.ts_rank_cd(sa_text("messages.content_tsv"), tsquery).label("rank"),
            Chat.created_at.label("created_at"),
            Chat.updated_at.label("updated_at"),
        )
        .join(Chat, Chat.id == Message.chat_id)
        .where(
            Chat.owner_id == user.id,
            Chat.archived_at.is_(None),
            sa_text("messages.content_tsv @@ websearch_to_tsquery('english', :q)"),
        )
        .params(q=q)
    )

    union = title_subq.union_all(message_subq).subquery()
    stmt = select(union).order_by(union.c.rank.desc(), union.c.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    rows = result.mappings().all()

    return ChatSearchResponse(
        query=q,
        items=[
            ChatSearchHit(
                chat_id=row["chat_id"],
                title=row["title"] or "",
                snippet=row["snippet"] or "",
                match_source=row["match_source"],
                rank=float(row["rank"] or 0),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ],
    )


@router.get(
    "",
    response_model=ChatListResponse,
    summary="List the caller's chats (cursor-paginated)",
    description=(
        "Returns the caller's active chats by default. "
        "``archived=true`` returns archived chats only. "
        "``project_id`` filters to chats inside a specific project. "
        "``cursor`` and ``limit`` paginate; ``next_cursor`` in the "
        "response carries the next page's cursor (null when "
        "exhausted)."
    ),
)
async def list_chats(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter to chats inside a specific project."),
    ] = None,
    archived: Annotated[
        bool | None,
        Query(description="When true, return archived chats only."),
    ] = None,
    cursor: Annotated[
        str | None,
        Query(description="Opaque cursor from a previous page's `next_cursor`."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=LIST_LIMIT_MAX, description="Page size; capped at 100."),
    ] = LIST_LIMIT_DEFAULT,
) -> ChatListResponse:
    stmt = select(Chat).where(Chat.owner_id == user.id)
    if archived is True:
        stmt = stmt.where(Chat.archived_at.is_not(None))
    else:
        stmt = stmt.where(Chat.archived_at.is_(None))

    if project_id is not None:
        stmt = stmt.where(Chat.project_id == project_id)

    # Newest-first listing. The keyset cursor compares against
    # ``(created_at, id)`` so ties on created_at break by id (stable
    # ordering across pages even if the same created_at is assigned
    # to multiple rows).
    if cursor is not None:
        decoded = _decode_cursor_or_400(cursor)
        stmt = stmt.where(
            or_(
                Chat.created_at < decoded.created_at,
                and_(Chat.created_at == decoded.created_at, Chat.id < decoded.id),
            )
        )

    stmt = stmt.order_by(Chat.created_at.desc(), Chat.id.desc()).limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    next_cursor: str | None = None
    if len(rows) > limit:
        # Trim the over-fetched row; encode the page's last row as the
        # cursor for the next page.
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, last.id)

    counts = await _message_counts_for(db, [r.id for r in rows])
    items = [await _serialize_chat(db, row, message_count=counts.get(row.id, 0)) for row in rows]

    return ChatListResponse(items=items, next_cursor=next_cursor)


@router.get(
    "/{chat_id}",
    response_model=ChatResponse,
    summary="Fetch a single chat",
)
async def get_chat(
    chat_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChatResponse:
    cid = _validate_chat_id(chat_id)
    # Archived chats are visible via direct GET (so a client can render
    # the archived-detail page); list excludes them by default.
    chat = await _load_visible_chat(db, cid, user.id, include_archived=True)
    return await _serialize_chat(db, chat)


@router.patch(
    "/{chat_id}",
    response_model=ChatResponse,
    summary="Partial update of a chat",
)
async def update_chat(
    chat_id: str,
    payload: ChatUpdateRequest,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChatResponse:
    cid = _validate_chat_id(chat_id)
    chat = await _load_visible_chat(db, cid, user.id, include_archived=True)

    update_fields = payload.model_dump(exclude_unset=True)

    if "title" in update_fields:
        new_title = update_fields["title"]
        if new_title is None:
            raise ValidationError(
                "title cannot be cleared; supply a non-empty value or omit the field.",
            )
        chat.title = new_title

    if "archived" in update_fields:
        archived = update_fields["archived"]
        if archived is True and chat.archived_at is None:
            chat.archived_at = datetime.now(tz=UTC)
        elif archived is False and chat.archived_at is not None:
            chat.archived_at = None

    await db.commit()
    await db.refresh(chat)

    log.info(
        "chat updated",
        extra={
            "event": "chat_updated",
            "user_id": str(user.id),
            "chat_id": str(chat.id),
            "fields": sorted(update_fields.keys()),
        },
    )
    return await _serialize_chat(db, chat)


@router.delete(
    "/{chat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a chat",
    description=(
        "Sets ``archived_at`` on the chat. Hard-delete is owned by D6. "
        "Idempotent: a second delete on an already-archived chat returns 404."
    ),
    response_class=Response,
)
async def delete_chat(
    chat_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    cid = _validate_chat_id(chat_id)
    chat = await _load_visible_chat(db, cid, user.id, include_archived=False)
    chat.archived_at = datetime.now(tz=UTC)
    await db.commit()
    log.info(
        "chat archived",
        extra={
            "event": "chat_archived",
            "user_id": str(user.id),
            "chat_id": str(cid),
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Messages: list
# ---------------------------------------------------------------------------


@router.get(
    "/{chat_id}/messages",
    response_model=MessageListResponse,
    summary="List messages in a chat (cursor-paginated, oldest-first)",
)
async def list_messages(
    chat_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[
        str | None,
        Query(description="Opaque cursor from a previous page's `next_cursor`."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=LIST_LIMIT_MAX, description="Page size; capped at 100."),
    ] = LIST_LIMIT_DEFAULT,
) -> MessageListResponse:
    cid = _validate_chat_id(chat_id)
    # The chat must be visible to the caller (404 cross-user). We
    # accept archived chats so a user can read history of an archived
    # conversation.
    await _load_visible_chat(db, cid, user.id, include_archived=True)

    stmt = select(Message).where(Message.chat_id == cid)

    if cursor is not None:
        decoded = _decode_cursor_or_400(cursor)
        # Oldest-first listing — the cursor represents the last
        # already-seen row, so the next page is rows AFTER it.
        stmt = stmt.where(
            or_(
                Message.created_at > decoded.created_at,
                and_(Message.created_at == decoded.created_at, Message.id > decoded.id),
            )
        )

    stmt = stmt.order_by(Message.created_at.asc(), Message.id.asc()).limit(limit + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, last.id)

    return MessageListResponse(
        items=[message_to_response(row) for row in rows],
        next_cursor=next_cursor,
    )


# ---------------------------------------------------------------------------
# Wave D.1 T7b: RAG step for the chat-send path
# ---------------------------------------------------------------------------


# Number of chunks retrieved per attached KB. Conservative default —
# the model sees k chunks per KB summed across attachments. T7b does
# not surface this in the request payload; a future task may expose
# it on MessageCreateRequest if Kevin wants per-call tuning.
RAG_TOP_K_PER_KB: int = 5

# Maximum total chunks injected into the gateway request. Bounds the
# context-prepend size when many KBs are attached.
RAG_MAX_TOTAL_CHUNKS: int = 10


async def _load_attached_kb_ids_for_chat(
    db: AsyncSession, project_id: uuid.UUID
) -> list[uuid.UUID]:
    """Return the KB ids attached to the chat's project via the T2 junction.

    Mirrors :func:`app.api.projects._load_attached_kb_ids`. Inlined here
    rather than imported to keep the chat surface free of a reverse
    dependency on the projects router module — both helpers are
    one-statement SELECTs against the junction table.
    """

    stmt = (
        select(ProjectKnowledgeBase.knowledge_base_id)
        .where(ProjectKnowledgeBase.project_id == project_id)
        .order_by(ProjectKnowledgeBase.attached_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _retrieve_kb_context_for_chat(
    db: AsyncSession,
    *,
    chat: Chat,
    query: str,
    gateway: GatewayClient,
    request_id: str | None,
) -> tuple[list[HybridSearchResult], list[uuid.UUID]]:
    """Run hybrid search across every KB attached to the chat's project.

    Returns a 2-tuple ``(chunks, kb_ids_searched)`` where ``chunks`` is
    the merged-then-truncated list of :class:`HybridSearchResult`
    ordered by descending ``hybrid_score`` (capped at
    :data:`RAG_MAX_TOTAL_CHUNKS`) and ``kb_ids_searched`` is the list of
    KB ids we actually queried (empty if the chat has no project or the
    project has no KBs attached).

    The embedding for ``query`` is computed once and reused across every
    KB call — embed-on-read is the same shape as ``query_kb``. If the
    embed fetch fails we downgrade to FTS-only retrieval per KB (the
    same fallback ``query_kb`` uses).

    The audit-row write is the caller's responsibility — this helper
    only does retrieval. Empty-result handling is the caller's too
    (T7 contract: no audit row when results are empty).
    """

    if chat.project_id is None:
        return [], []

    kb_ids = await _load_attached_kb_ids_for_chat(db, chat.project_id)
    if not kb_ids:
        return [], []

    # Load KB rows (for hybrid_alpha per KB). One SELECT for the set.
    kb_stmt = select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
    kb_rows = (await db.execute(kb_stmt)).scalars().all()

    # Embed the query once (reused across every KB). Mirrors the
    # alpha<1.0 gate in query_kb: if every attached KB is FTS-only
    # (hybrid_alpha == 1.0) we skip the embed call entirely. We also
    # tolerate embed-fetch failure by downgrading to FTS-only.
    needs_embedding = any(float(kb.hybrid_alpha) < 1.0 for kb in kb_rows)
    query_embedding: list[float] | None = None
    if needs_embedding:
        try:
            query_embedding = await request_embedding_vector(
                query,
                model=DEFAULT_EMBEDDING_MODEL,
                gateway=gateway,
                request_id=request_id,
            )
        except LQAIError as exc:
            log.warning(
                "chat-send RAG: query-embedding fetch failed; FTS-only fallback",
                extra={
                    "event": "chat_rag_embed_fetch_failed",
                    "chat_id": str(chat.id),
                    "error_code": exc.effective_code,
                },
            )
            query_embedding = None

    # Iterate every attached KB. hybrid_search is single-KB by
    # signature (C6 / ADR 0008); a multi-KB primitive is a v1.1+
    # refinement candidate. For M1 the per-call cost is small —
    # legal users attach a handful of KBs, not hundreds.
    merged: list[HybridSearchResult] = []
    for kb in kb_rows:
        alpha = float(kb.hybrid_alpha)
        try:
            results = await hybrid_search(
                db,
                kb_id=kb.id,
                query=query,
                query_embedding=query_embedding,
                top_k=RAG_TOP_K_PER_KB,
                alpha=alpha,
            )
        except Exception:
            log.exception(
                "chat-send RAG: hybrid_search failed for KB; skipping",
                extra={
                    "event": "chat_rag_kb_search_failed",
                    "chat_id": str(chat.id),
                    "kb_id": str(kb.id),
                },
            )
            continue
        merged.extend(results)

    if not merged:
        return [], [kb.id for kb in kb_rows]

    merged.sort(key=lambda r: r.hybrid_score, reverse=True)
    top = merged[:RAG_MAX_TOTAL_CHUNKS]
    return top, [kb.id for kb in kb_rows]


def _format_retrieval_context_block(
    chunks: list[HybridSearchResult],
) -> str:
    """Render retrieved chunks as a Markdown system-message context block.

    The shape is intentionally lightweight — a header line so the LLM
    can recognize the block as retrieved context, then one Markdown
    list item per chunk with a short header (``file_name``, optional
    page range) and the chunk text. The block is prepended to the
    gateway request as a ``system`` message so the LLM treats it as
    grounding rather than user turn content.

    The header carries the M2 Citation Engine's citation contract: when
    the model grounds a claim in a retrieved chunk, it must quote the
    source verbatim in straight double quotes followed by
    ``(Source: [N])`` where N matches the bracketed index of the chunk
    below. The extractor (``app.citation.extraction``) parses that
    shape; the Stage 1 verifier checks the quote byte-for-byte against
    ``documents.normalized_content``. Paraphrases or smart-quoted
    citations fail Stage 1 and fall through to later stages when those
    ship (M2-B1 tolerant-match, M2-C1 LLM judge).

    Chunk text is included verbatim. We do not truncate at the
    character level (the LLM's tokenizer will window if the request is
    oversized); :data:`RAG_MAX_TOTAL_CHUNKS` upstream is the bound.
    """

    lines: list[str] = [
        "Retrieved context from your matter's knowledge bases. "
        "Cite these sources when they bear on the user's question; "
        "ignore them if they are not relevant.",
        "",
        "Citation format: when you ground a claim in a retrieved chunk, "
        'quote the source passage VERBATIM in straight double quotes "..." '
        "immediately followed by `(Source: [N])` where N is the bracketed "
        "index of the chunk below. Quotes must be byte-for-byte exact - "
        "do not paraphrase, summarize, or change punctuation, casing, or "
        "whitespace inside quoted material. Use this format every time you "
        "rely on a chunk; otherwise the citation will render as unverified.",
        "",
    ]
    for idx, chunk in enumerate(chunks, start=1):
        location = ""
        if chunk.page_start is not None:
            if chunk.page_end is not None and chunk.page_end != chunk.page_start:
                location = f" (pp. {chunk.page_start}-{chunk.page_end})"
            else:
                location = f" (p. {chunk.page_start})"
        header = f"[{idx}] {chunk.file_name}{location}"
        lines.append(f"{header}:")
        lines.append(chunk.content)
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_attached_files_block(files: list[tuple[str, str]]) -> str:
    """Render per-message attached files as a Markdown system-message block.

    Mirrors :func:`_format_retrieval_context_block`'s style: a header line
    so the LLM recognizes the block as attached document context, then one
    ``### {filename}`` section per file with the file's extracted text
    verbatim. The block is injected as a ``system`` message marked
    ``lq_ai_skip_anonymization=True`` so the content stays verbatim to the
    provider (Decision M2-1 — attached files are document content, like
    retrieved KB documents, and the model needs intact source text).

    Callers must only pass files that actually produced text; this helper
    does not filter (the empty-text omission happens in
    :func:`_load_attached_file_contexts`).
    """

    lines: list[str] = [
        "## Attached documents for this turn",
        "",
        "Documents the user attached to this message. Treat them as "
        "primary source material for the user's question.",
        "",
    ]
    for filename, content in files:
        lines.append(f"### {filename}")
        lines.append("")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Messages: post (the keystone)
# ---------------------------------------------------------------------------


@router.post(
    "/{chat_id}/messages",
    response_model=None,  # union return type; FastAPI handles via Response
    summary="Post a user message; persist + forward to gateway + persist response",
    description=(
        "C3: persists the user message, forwards to the gateway, "
        "persists the assistant message (or streams SSE chunks and "
        "persists the assistant row at end-of-stream). Returns either "
        "a JSON body or an SSE stream depending on ``stream``."
    ),
)
async def send_message(
    chat_id: str,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> JSONResponse | StreamingResponse:
    cid = _validate_chat_id(chat_id)

    try:
        raw_body = await request.json()
    except Exception as exc:
        raise ValidationError("Request body is not valid JSON") from exc

    try:
        payload = MessageCreateRequest.model_validate(raw_body)
    except PydanticValidationError as exc:
        # ``include_context=False`` strips the raw exception instance
        # pydantic stashes in ``ctx.error`` for ``value_error`` failures —
        # those instances aren't JSON-serializable and the canonical
        # error envelope is JSON-encoded. Wave D.2 Task 3.0's
        # ``AttachedSkillRef`` XOR validator raises ``ValueError`` which
        # surfaces this; previously all the schema's failures were
        # type/missing-style which don't carry a ctx.error so the issue
        # was latent.
        #
        # ``include_input=False`` strips pydantic's echo of the offending
        # input payload. Without it, a ``string_too_long`` failure on a
        # 32K+1-byte ``inline_body`` returns the FULL submitted body
        # verbatim in the response envelope — leaking the user-drafted
        # skill body back over the wire and violating the
        # ``LQAIError.details MUST NOT contain secrets or PII`` contract
        # (per ``api/app/errors.py``). Regression in
        # ``tests/integration/test_attached_skills_send.py``.
        raise ValidationError(
            "Request body failed schema validation",
            details={
                "errors": exc.errors(
                    include_context=False,
                    include_url=False,
                    include_input=False,
                )
            },
        ) from exc

    # Auth + ownership: load the chat (visible to caller, not
    # archived). Posting to an archived chat returns 404 — clients
    # must explicitly unarchive (PATCH archived=false) before posting.
    chat = await _load_visible_chat(db, cid, user.id, include_archived=False)

    # Donna — validate caller-owned ``file_ids`` before anything is
    # persisted or dispatched. Ownership is enforced id-probing-safe
    # (404 on foreign / nonexistent / soft-deleted, indistinguishable
    # from one another) so the caller can't enumerate file ids they
    # don't own. Validated ids forward to the gateway as
    # ``lq_ai_file_ids`` and echo back as ``applied_file_ids``. Empty /
    # omitted is a no-op (no DB round-trip) — back-compatible.
    effective_file_ids = await _validate_owned_file_ids(db, payload.file_ids, user.id)

    # Wave D.2 Task 3.0 — merge legacy ``skills`` with new
    # ``attached_skills``. Each ``attached_skills`` entry is XOR'd at
    # schema time: ``slug`` entries roll into the legacy slug path
    # (forwarded as ``lq_ai_skills`` to the gateway), ``inline_body``
    # entries roll into a separate inline-body list forwarded as
    # ``lq_ai_inline_skills``. Per-entry ``inputs`` merge into the
    # combined ``skill_inputs`` map keyed by slug (catalogue) or the
    # synthesized name (inline). Per-entry ``source`` is captured for
    # audit-log provenance below.
    effective_skills: list[str] = list(payload.skills)
    effective_skill_inputs: dict[str, dict[str, Any]] = {
        k: dict(v) for k, v in payload.skill_inputs.items()
    }
    inline_skill_refs: list[InlineSkillRef] = []
    # Per-attachment provenance for the audit log. Each entry is
    # ``{"name": <slug or synthesized>, "source": <str|null>,
    #   "kind": "slug"|"inline"}``.
    attached_skill_provenance: list[dict[str, str | None]] = [
        {"name": slug, "source": None, "kind": "slug"} for slug in payload.skills
    ]
    for entry in payload.attached_skills:
        if entry.slug is not None:
            effective_skills.append(entry.slug)
            if entry.inputs:
                # Per-attachment inputs win on collision with the
                # top-level skill_inputs[<slug>] (the caller's
                # most-specific intent for *this* attachment).
                merged = dict(effective_skill_inputs.get(entry.slug, {}))
                merged.update(entry.inputs)
                effective_skill_inputs[entry.slug] = merged
            attached_skill_provenance.append(
                {"name": entry.slug, "source": entry.source, "kind": "slug"}
            )
        else:
            # inline_body — XOR validator guarantees it's non-empty here.
            assert entry.inline_body is not None
            # Synthesized name: opaque + collision-free against real
            # slugs (real slugs are lowercase-kebab; ``__inline__`` uses
            # underscores which the slug pattern rejects). Hex tail keeps
            # it unique within a single request so two inline entries
            # don't collide in the gateway's per-skill inputs map.
            inline_name = f"__inline__{uuid.uuid4().hex[:8]}"
            inline_skill_refs.append(
                InlineSkillRef(
                    name=inline_name,
                    body=entry.inline_body,
                    inputs=entry.inputs,
                    source=entry.source,
                )
            )
            if entry.inputs:
                effective_skill_inputs[inline_name] = dict(entry.inputs)
            attached_skill_provenance.append(
                {"name": inline_name, "source": entry.source, "kind": "inline"}
            )

    # Wave D.2 Task 2.7 — send-time slash fallback. If the caller
    # didn't pre-attach any skills (legacy OR new attached_skills)
    # AND the content starts with ``/<token> ``, try to resolve the
    # token against the merged catalogue. On hit: append the slug to
    # ``applied_skills`` for this turn and strip the leading token
    # from the content so the gateway sees the same body the user
    # would type without the ``/foo`` prefix. On miss: set
    # ``slash_unresolved=True`` on the response so the UI can render
    # a hint, but forward the original content as plain text — the
    # user still gets an answer, the typo just doesn't activate a
    # skill.
    effective_content: str = payload.content
    slash_unresolved = False
    attached_skill_names: list[str] = list(payload.skills)
    # Surface slug attachments (not inline ones) in
    # ``attached_skill_names`` — the field is documented as "slugs the
    # send-time slash fallback attached on the caller's behalf" and is
    # consumed by the UI to render chips; inline skills don't have a
    # browsable slug to chip.
    attached_skill_names.extend(
        # ``name`` is always a non-empty str on a slug-kind row (we
        # construct it from ``payload.skills`` / ``entry.slug`` /
        # resolved slash slugs). The ``cast`` keeps mypy honest given
        # the ``str | None`` value-type on the provenance dict.
        str(e["name"])
        for e in attached_skill_provenance
        if e["kind"] == "slug" and e["name"] is not None and e["name"] not in attached_skill_names
    )
    have_any_attached = bool(payload.skills) or bool(payload.attached_skills)
    if not have_any_attached and payload.content.startswith("/"):
        resolved_slug, effective_content, slash_unresolved = await _maybe_resolve_leading_slash(
            request, db, user, payload.content
        )
        if resolved_slug is not None:
            effective_skills.append(resolved_slug)
            attached_skill_names.append(resolved_slug)
            attached_skill_provenance.append(
                {"name": resolved_slug, "source": "slash", "kind": "slug"}
            )

    # Persist the user message FIRST. This is unconditionally written,
    # even if the gateway call ultimately fails — the user did say
    # something and the audit trail must reflect that.
    #
    # Wave D.2 Task 3.0 — the user-message ``applied_skills`` column
    # records *both* slug attachments AND synthesized inline-skill
    # names. The synthesized name is opaque (``__inline__<hex>``); the
    # audit-log row written later carries the full per-attachment
    # provenance (kind/source) so receipts can render "from wizard
    # tryout" instead of an inscrutable hex blob.
    user_applied_skills: list[str] = [
        e["name"] for e in attached_skill_provenance if e["name"] is not None
    ]
    user_message = Message(
        chat_id=cid,
        role="user",
        content=effective_content,
        applied_skills=user_applied_skills,
    )
    db.add(user_message)

    # Auto-rename if this is still the default title. We do this in the
    # same transaction so the rename and the user message land
    # atomically. ``derive_chat_title`` returns "New chat" for empty
    # input, so a degenerate first message keeps the default rather
    # than blanking the title. We derive from ``effective_content`` so a
    # resolved-slash send (``/foo go``) names the chat ``go`` rather
    # than ``/foo go`` — matching what the user actually asked.
    if chat.title == "New chat":
        chat.title = derive_chat_title(effective_content)

    await db.flush()
    await db.commit()
    await db.refresh(user_message)
    await db.refresh(chat)

    # Generate the assistant message id BEFORE dispatch so the gateway
    # can stamp it on the routing log row and the persisted message
    # row carries the same id. Idempotent across retries.
    assistant_message_id = uuid.uuid4()

    request_id = (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
        or f"req_{uuid.uuid4().hex}"
    )

    # D1: forward the project's tier floor (if any) so the gateway can
    # enforce ``Project.minimum_inference_tier`` as one of three sources
    # of a tier floor (per PRD §4.4 / D1). The backend is authoritative
    # on chat ↔ project; the gateway never queries projects directly,
    # so the value travels on the request envelope.
    # M2-B3: also resolve ``Project.privileged`` so the gateway's
    # anonymization middleware can short-circuit for privileged chats.
    # Cheaper to fetch both in one SELECT than two round-trips.
    project_floor: int | None = None
    project_privileged: bool = False
    project_ensemble_verification: bool = False
    if chat.project_id is not None:
        project_stmt = select(
            Project.minimum_inference_tier,
            Project.privileged,
            Project.ensemble_verification,
        ).where(Project.id == chat.project_id)
        project_row = (await db.execute(project_stmt)).one_or_none()
        if project_row is not None:
            project_floor = project_row[0]
            project_privileged = bool(project_row[1])
            project_ensemble_verification = bool(project_row[2])

    # Wave D.1 T7b — RAG step: when the chat's project has KBs attached,
    # run hybrid_search across all of them for the user's just-sent
    # message, write the T7-shape audit row so Receipts surfaces the
    # 📎 KB retrieval event, and prepend the retrieved chunks as a
    # ``system`` message to the gateway request so the LLM actually
    # sees them. Empty results → no audit row, no context injection
    # (same guard as T7's query_kb path).
    retrieved_chunks, kb_ids_searched = await _retrieve_kb_context_for_chat(
        db,
        chat=chat,
        query=effective_content,
        gateway=gateway,
        request_id=request.headers.get("x-request-id"),
    )

    # Build the gateway messages list. T7b prepends a ``system``-role
    # context block when we have retrieved chunks; this is the
    # least-invasive injection point — the gateway treats it as a
    # system message and the C2 / ADR 0007 prompt-assembly logic still
    # runs on top (the gateway concatenates its own system messages
    # before the user turn, so the retrieved context shows up at the
    # very front of the prompt). The user's just-sent message
    # remains the last entry, unchanged.
    gw_messages: list[ChatCompletionMessage] = []
    if retrieved_chunks:
        context_block = _format_retrieval_context_block(retrieved_chunks)
        # M2-D2 / Decision M2-1: retrieved source documents are NOT
        # pseudonymized when sent to the provider — the model needs
        # intact source quotes for citation grounding. The skip flag
        # tells the gateway's anonymization pre-middleware to leave
        # this message's content unchanged even if the chat's other
        # content is being pseudonymized. The pre-middleware still
        # pseudonymizes the user turn + any chat-side system message.
        gw_messages.append(
            ChatCompletionMessage(
                role="system",
                content=context_block,
                lq_ai_skip_anonymization=True,
            )
        )
        # T7-shape audit row. Same details schema as query_kb (kb_ids
        # plural here; query_kb is single-KB). The row commits with
        # its own boundary so it's durable even if the gateway call
        # later fails — Receipts must show retrieval happened
        # regardless of LLM-call outcome.
        await audit_action(
            db,
            user_id=user.id,
            action="inference.kb_chunks_retrieved",
            resource_type="chat",
            resource_id=str(cid),
            project_id=chat.project_id,
            request=request,
            details={
                "kb_ids": [str(k) for k in kb_ids_searched],
                "chunk_count": len(retrieved_chunks),
                "chunk_ids": [str(c.chunk_id) for c in retrieved_chunks],
                "query_token_estimate": len(effective_content.split()),
            },
        )
        await db.commit()

    # Part B — inject per-message attached-file content as a verbatim
    # document-context system message, mirroring the KB-retrieval block
    # above. ``effective_file_ids`` are already ownership-validated;
    # ``_load_attached_file_contexts`` re-asserts the owner scope (defense
    # in depth) and returns ``(filename, content)`` per file that has
    # extractable text. Files with no Document yet (ingestion pending /
    # failed) or empty content are omitted gracefully — no block, no
    # error. Decision M2-1: attached files are document content, so the
    # injected message opts out of anonymization (verbatim to provider),
    # exactly like the retrieval block. Injecting here — before the final
    # ``user`` turn and at the single ``gw_messages`` build site — covers
    # both the streaming and non-streaming dispatch paths.
    attached_file_contexts = await _load_attached_file_contexts(
        db, list(effective_file_ids), user.id
    )
    if attached_file_contexts:
        attached_block = _format_attached_files_block(attached_file_contexts)
        gw_messages.append(
            ChatCompletionMessage(
                role="system",
                content=attached_block,
                lq_ai_skip_anonymization=True,
            )
        )
        # Audit row mirroring inference.kb_chunks_retrieved — committed on
        # its own boundary so Receipts records that file content was
        # attached regardless of the downstream gateway-call outcome.
        await audit_action(
            db,
            user_id=user.id,
            action="inference.message_files_attached",
            resource_type="chat",
            resource_id=str(cid),
            project_id=chat.project_id,
            request=request,
            details={
                # All validated file_ids forwarded this turn, vs. the count
                # whose extracted text was actually injected as document
                # context (a file with no parsed text yet is attached but
                # contributes nothing) — kept as distinct fields so Receipts
                # don't conflate "attached" with "reached the model".
                "file_ids": list(effective_file_ids),
                "attached_count": len(effective_file_ids),
                "injected_count": len(attached_file_contexts),
            },
        )
        await db.commit()

    gw_messages.append(ChatCompletionMessage(role="user", content=effective_content))

    # Build the gateway request. C3 still sends a single-turn request
    # (the user's content as one ``user`` message); a future task may
    # widen this to include prior history. The gateway does the skill
    # prompt assembly per ADR 0007. T7b prepends a system context
    # block when KB retrieval returned chunks (see above).
    #
    # Wave D.2 Task 3.0 — ``lq_ai_inline_skills`` carries inline-body
    # attachments. The gateway assembles them alongside ``lq_ai_skills``
    # without a backend round-trip; ``effective_skill_inputs`` is the
    # merged-and-flattened map keyed by both slug AND synthesized
    # inline-skill name.
    gw_request = ChatCompletionRequest(
        model=payload.model,
        messages=gw_messages,
        stream=payload.stream,
        chat_id=str(cid),
        lq_ai_chat_id=str(cid),
        lq_ai_message_id=str(assistant_message_id),
        lq_ai_user_id=str(user.id),
        lq_ai_skills=list(effective_skills),
        lq_ai_skill_inputs=dict(effective_skill_inputs),
        lq_ai_inline_skills=list(inline_skill_refs),
        lq_ai_file_ids=list(effective_file_ids),
        lq_ai_project_minimum_inference_tier=project_floor,
        lq_ai_privileged=project_privileged,
    )

    # M3-F2 / Task 6 — emit one ``skill.execute`` marker span per applied
    # skill at the gateway-dispatch seam. The spans live under the same
    # trace as the HTTP span auto-instrumented on the inbound request,
    # giving operators a per-skill signal alongside the gateway's
    # inference spans. Only slug-based skills are spanned here; inline-
    # body skills (``__inline__<hex>``) are implementation artefacts, not
    # catalogue entries, so they carry no registry metadata.
    # Telemetry must never break a send: a failure emitting marker spans is
    # logged and swallowed rather than propagated into the user's request.
    try:
        _emit_skill_spans(
            list(effective_skills),
            registry=_skill_registry_from_request(request),
            project_id=chat.project_id,
            project_privileged=project_privileged,
            chat_id=cid,
        )
    except Exception:  # pragma: no cover - defensive telemetry guard
        log.warning("skill_span_emit_failed", exc_info=True)

    log.info(
        "chat send_message",
        extra={
            "event": "chat_send_message",
            "user_id": str(user.id),
            "chat_id": str(cid),
            "user_message_id": str(user_message.id),
            "assistant_message_id": str(assistant_message_id),
            "model": payload.model,
            "stream": payload.stream,
            "request_id": request_id,
        },
    )

    if payload.stream:
        return await _stream_response(
            db=db,
            user=user,
            gateway=gateway,
            request=gw_request,
            chat=chat,
            assistant_message_id=assistant_message_id,
            user_message_id=user_message.id,
            request_id=request_id,
            retrieved_chunks=retrieved_chunks,
            http_request=request,
            attached_skill_provenance=attached_skill_provenance,
            project_ensemble_verification=project_ensemble_verification,
        )
    return await _non_streaming_response(
        db=db,
        user=user,
        gateway=gateway,
        request=gw_request,
        chat=chat,
        assistant_message_id=assistant_message_id,
        user_message_id=user_message.id,
        request_id=request_id,
        retrieved_chunks=retrieved_chunks,
        http_request=request,
        attached_skill_names=attached_skill_names,
        slash_unresolved=slash_unresolved,
        attached_skill_provenance=attached_skill_provenance,
        project_ensemble_verification=project_ensemble_verification,
    )


@router.get(
    "/{chat_id}/messages/{message_id}/citations",
    summary="Get citations for a message (M2-A2: relational message_citations rows)",
)
async def get_citations(
    chat_id: str,
    message_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, Any]]:
    """Return citations persisted for a message.

    M2-A2 (this version) reads from ``message_citations`` (one row per
    citation) rather than the legacy ``messages.citations`` JSONB
    column. Each citation in the response carries the verifier's
    verdict (``verified``, ``verification_method``,
    ``verification_confidence``, ``partial``) so the UI (M2-C2) can
    render the five citation states distinctly — including the
    paraphrase-judge "partial" verdict surfaced via the ``partial``
    flag (M2-C1).

    The legacy JSONB column is kept at its ``'[]'`` default by the
    chat-send path; readers should consume this endpoint, not the
    column. The column itself remains for backward compatibility with
    older clients and is slated for retirement by M2-C2.

    Chat ownership is enforced so a cross-user request can't enumerate
    message ids — the visibility check uses the same path as message
    list reads.
    """

    cid = _validate_chat_id(chat_id)
    try:
        mid = uuid.UUID(message_id)
    except ValueError as exc:
        raise ValidationError(
            "message_id must be a UUID",
            details={"message_id": message_id},
        ) from exc

    await _load_visible_chat(db, cid, user.id, include_archived=True)

    # Confirm the message exists (and belongs to the chat) before
    # returning an empty list — distinguishes "no citations" from
    # "no message" for the caller.
    msg_stmt = select(Message.id).where(Message.id == mid, Message.chat_id == cid)
    if (await db.execute(msg_stmt)).scalar_one_or_none() is None:
        raise NotFound(
            f"Message {mid} not found.",
            details={"message_id": str(mid)},
        )

    cite_stmt = (
        select(MessageCitation)
        .where(MessageCitation.message_id == mid)
        .order_by(MessageCitation.created_at, MessageCitation.id)
    )
    rows = (await db.execute(cite_stmt)).scalars().all()

    return [
        {
            "id": str(c.id),
            "source_file_id": str(c.source_file_id),
            "source_offset_start": c.source_offset_start,
            "source_offset_end": c.source_offset_end,
            "source_page": c.source_page,
            "source_text": c.source_text,
            "verified": c.verified,
            "verification_method": c.verification_method,
            "verification_confidence": (
                float(c.verification_confidence) if c.verification_confidence is not None else None
            ),
            "partial": c.partial,
            "created_at": c.created_at.isoformat(),
        }
        for c in rows
    ]


# ---------------------------------------------------------------------------
# Internal: persistence flow for non-streaming and streaming
# ---------------------------------------------------------------------------


async def _audit_message_sent(
    db: AsyncSession,
    *,
    user: User,
    chat: Chat,
    assistant_message_id: uuid.UUID,
    user_message_id: uuid.UUID,
    routed_inference_tier: int | None,
    routed_provider: str | None,
    applied_skills: list[str],
    error_code: str | None,
    request: Request | None,
    attached_skill_provenance: list[dict[str, str | None]] | None = None,
) -> None:
    """Write the D3 audit row for a completed chat-message exchange.

    Per PRD §5.3: every state-changing API call writes to ``audit_log``;
    chat exchanges in privileged projects must mark the row privileged
    and capture the routed inference tier so admins can audit which
    matters routed to which providers.

    Wave D.2 Task 3.0 — ``attached_skill_provenance`` carries
    per-attachment ``{name, source, kind}`` so receipts can render
    "from wizard tryout" / "from slash" instead of an opaque list of
    slugs and ``__inline__`` synthesized names. Inline-body content is
    NOT recorded here (PII risk); only the synthesized name + provenance
    tag travel through the log.

    The privilege resolution walks ``chat.project_id`` to read the
    project's ``privileged`` flag. The audit row commits with the
    handler's outer transaction (FastAPI dependency commits per
    request); we flush so the row is visible to subsequent reads in
    the same request scope.
    """

    project: Project | None = None
    if chat.project_id is not None:
        project = await db.get(Project, chat.project_id)

    details: dict[str, Any] = {
        "chat_id": str(chat.id),
        "user_message_id": str(user_message_id),
        "applied_skills": list(applied_skills),
        "error_code": error_code,
    }
    if attached_skill_provenance:
        # Filter null-source entries to keep the row tidy when no
        # surface tagged itself. Inline-body content is intentionally
        # not included.
        details["attached_skills"] = [
            {"name": e["name"], "source": e["source"], "kind": e["kind"]}
            for e in attached_skill_provenance
        ]

    await audit_action(
        db,
        user_id=user.id,
        action="chat.message_sent",
        resource_type="message",
        resource_id=str(assistant_message_id),
        project=project,
        routed_inference_tier=routed_inference_tier,
        routed_provider=routed_provider,
        request=request,
        details=details,
    )
    await db.commit()


def _skill_registry_from_request(http_request: Request | None) -> SkillRegistry | None:
    """Return the current :class:`SkillRegistry` snapshot, or None.

    The lifespan handler installs ``app.state.skill_registry`` as a
    :class:`MutableSkillRegistry`. Tests may install nothing (the
    registry is optional for the chat-send path on Stages 1-3) so we
    return None on absence rather than raise — M2-D1 Stage 4 then
    silently skips skill-frontmatter activation.
    """

    if http_request is None:
        return None
    holder: MutableSkillRegistry | None = getattr(http_request.app.state, "skill_registry", None)
    if holder is None:
        return None
    return holder.current()


def _emit_skill_spans(
    skill_slugs: list[str],
    *,
    registry: SkillRegistry | None,
    project_id: uuid.UUID | None,
    project_privileged: bool,
    chat_id: uuid.UUID,
) -> None:
    """Emit one ``skill.execute`` span per applied skill (M3-F2 / Task 6).

    Marker spans recording which skills were applied to a send; the
    actual prompt assembly + inference run in the gateway under the same
    trace. ``version`` comes from :attr:`Skill.version` when the
    registry resolves the slug. ``author`` comes from
    :attr:`Skill.author`, promoted to the wire shape from
    :class:`LQAIFrontmatter` (DE-316); it is ``None`` only when the
    skill's frontmatter omits ``author``. ``None`` attributes are
    silently dropped by :func:`record_attributes` per the OTel
    attribute-hygiene contract.

    No-op when ``skill_slugs`` is empty. Safe to call before or after
    ``gw_request`` construction — it does not mutate any shared state.
    """

    tracer = get_tracer()
    for slug in skill_slugs:
        skill = registry.get_skill(slug) if registry is not None else None
        with tracer.start_as_current_span("skill.execute") as span:
            record_attributes(
                span,
                **{
                    "skill.slug": slug,
                    "skill.version": getattr(skill, "version", None),
                    "skill.author": getattr(skill, "author", None),
                    "project.id": str(project_id) if project_id is not None else None,
                    "project.privileged": project_privileged,
                    "chat.id": str(chat_id),
                },
            )


async def _resolve_ensemble_config(
    *,
    gateway: GatewayClient | None,
    applied_skills: list[str] | None,
    project_ensemble_verification: bool,
    skill_registry: SkillRegistry | None,
    n_candidates: int,
    message_id: uuid.UUID,
    db: AsyncSession | None = None,
) -> EnsembleConfig | None:
    """Decide whether Stage 4 should run for this message — M2-D1.

    Returns the resolved :class:`EnsembleConfig` when ensemble is
    activated AND the per-message cost-budget pre-flight passes.
    Returns ``None`` when ensemble is not activated, the gateway has
    no ensemble configured, or the cost estimate exceeds the budget
    (cost-budget fallback → cascade drops back to Stage 3).

    Activation is ``any()`` across three sources:

    * The project's ``ensemble_verification`` column.
    * Any skill in ``applied_skills`` whose frontmatter declares
      ``ensemble_verification: true``.
    * The gateway's
      ``citation_engine.ensemble_verification.default_enabled``.

    Cost-budget pre-flight uses M2-E2 per-model calibration via
    :func:`estimate_judge_call_cost_usd` — each configured judge
    model's recent rolling-average cost from ``inference_routing_log``
    rows tagged ``purpose='judge_paraphrase'``. Cold-start (a model
    with fewer than 5 recent judge calls) falls back to the
    conservative constant. The check errs toward dropping back to
    single-judge Stage 3 rather than letting an ensemble silently
    overrun.

    ``db=None`` is honored by tests that don't exercise the cost-budget
    path; in that case the estimator skips the DB query and uses the
    cold-start default. Production callers always pass a real session.
    """

    if gateway is None:
        return None

    skill_activated = False
    if applied_skills and skill_registry is not None:
        for skill_name in applied_skills:
            skill = skill_registry.get_skill(skill_name)
            if skill is not None and skill.ensemble_verification:
                skill_activated = True
                break

    config = await gateway.get_citation_engine_ensemble_config()
    if config is None:
        # Gateway has no ensemble configured (empty judge_models or
        # endpoint unreachable). Whatever the activation flags say,
        # Stage 4 cannot run.
        return None

    activated = skill_activated or project_ensemble_verification or config.default_enabled
    if not activated:
        return None

    # Pre-flight cost-budget check. Per-message cap; if the estimated
    # ensemble spend exceeds the cap, fall back to single-judge Stage 3
    # by returning None (the cascade routes through verify_paraphrase
    # instead). Logged so operators can see when the cap bites.
    #
    # M2-E2: sum per-model rolling-average judge costs rather than
    # multiplying a single flat constant — accuracy matters because
    # judge models span order-of-magnitude cost differences
    # (haiku ~$0.001 vs opus ~$0.04 per call).
    per_judge_costs = [
        await estimate_judge_call_cost_usd(db, judge_model=judge_model)
        for judge_model in config.judge_models
    ]
    estimated_usd = float(Decimal(n_candidates) * sum(per_judge_costs, Decimal("0")))
    if estimated_usd > config.max_cost_per_message_usd:
        log.warning(
            "chat-send citations: ensemble budget exceeded, falling back to single judge",
            extra={
                "event": "chat_message_ensemble_budget_fallback",
                "message_id": str(message_id),
                "n_candidates": n_candidates,
                "n_judges": len(config.judge_models),
                "estimated_usd": round(estimated_usd, 4),
                "max_cost_per_message_usd": config.max_cost_per_message_usd,
                "per_judge_usd": [float(c) for c in per_judge_costs],
            },
        )
        trace.get_current_span().add_event(
            "ensemble.budget_fallback",
            attributes={
                "estimated_usd": float(estimated_usd),
                "budget_usd": float(config.max_cost_per_message_usd),
            },
        )
        return None

    return config


async def _persist_message_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    assistant_text: str,
    retrieved_chunks: list[HybridSearchResult],
    gateway: GatewayClient | None = None,
    applied_skills: list[str] | None = None,
    project_ensemble_verification: bool = False,
    skill_registry: SkillRegistry | None = None,
) -> None:
    """Extract, verify, and persist citations from an assistant message — M2-A2.

    Runs after :func:`_persist_assistant_message` so ``message_id`` is
    a real FK target. No-op when ``retrieved_chunks`` is empty
    (no RAG context this turn → nothing to cite) or when extraction
    finds no ``"..." (Source: [N])`` pairs.

    Verifier cascade (per the M2 plan):

    * Stage 1 (exact-match) — M2-A2.
    * Stage 2 (tolerant-match) — M2-B1.
    * Stage 3 (paraphrase judge) — M2-C1, runs only when ``gateway``
      is supplied and ensemble is NOT activated. The judge model is
      resolved via :meth:`GatewayClient.get_citation_engine_judge_model`
      (cached for the process) so the operator configures it once in
      ``gateway.yaml`` rather than on the api/ side.
    * Stage 4 (ensemble) — M2-D1. Activated when any of:
      ``applied_skills`` includes a skill whose frontmatter declares
      ``ensemble_verification: true``, OR ``project_ensemble_verification``
      is True, OR the gateway's ``default_enabled`` is True. Replaces
      Stage 3 on activation. Falls back to Stage 3 if the per-message
      cost-budget pre-flight estimate exceeds the configured cap.

    Candidates that pass any stage persist with the stage's method
    string and confidence. Stage 3 ``partial`` verdicts persist with
    ``verified=true, partial=true`` — the M2-C2 UI renders these as
    "verified with caveats". Stage 4 ``ensemble_strict`` /
    ``ensemble_majority`` rows additionally carry ``tier_envelope``
    (the maximum tier across the judge ensemble). Candidates that
    miss every stage are NOT persisted; their absence is the
    unverified signal the UI consumes.
    """

    if not retrieved_chunks:
        return

    # Batch-load the documents the retrieved chunks point at so the
    # verifier has ``document.normalized_content`` and the extractor
    # has the same surface for the M3-0.2 / DE-277 chunk-boundary
    # fallback. Loading by retrieved-chunk document_ids (rather than
    # by candidate document_ids as M2 did) is a superset: every
    # candidate's document is in this set by construction, and the
    # extra documents the verifier never consults are negligible.
    chunk_doc_ids = {chunk.document_id for chunk in retrieved_chunks}
    doc_rows = (
        (await db.execute(select(Document).where(Document.id.in_(chunk_doc_ids)))).scalars().all()
    )
    docs_by_id = {d.id: d for d in doc_rows}
    doc_contents = {d.id: d.normalized_content for d in doc_rows}

    candidates = extract_citations(assistant_text, retrieved_chunks, doc_contents)
    if not candidates:
        return

    # M2-C1: resolve the Stage 3 judge model once per persist call.
    # The lookup is process-cached on the GatewayClient, so the per-
    # request cost is one Python-dict read after the first call.
    judge_model = "fast"
    if gateway is not None:
        judge_model = await gateway.get_citation_engine_judge_model()

    # M2-D1: resolve Stage 4 (ensemble) activation. The chat-send
    # caller passes the project's flag + the applied skills + the
    # skill registry; this function ORs them with the gateway's
    # default to decide whether to dispatch ensemble verification.
    ensemble_config = await _resolve_ensemble_config(
        db=db,
        gateway=gateway,
        applied_skills=applied_skills,
        project_ensemble_verification=project_ensemble_verification,
        skill_registry=skill_registry,
        n_candidates=len(candidates),
        message_id=message_id,
    )

    new_rows: list[MessageCitation] = []
    for cand in candidates:
        doc = docs_by_id.get(cand.source_document_id)
        if doc is None:
            # Defensive: chunk pointed at a document that was deleted
            # between retrieval and persistence. Skip; the schema's FK
            # would reject anyway.
            continue

        result = await verify(
            cand,
            doc,
            gateway=gateway,
            judge_model=judge_model,
            ensemble_config=ensemble_config,
        )
        if not result.verified:
            # Every wired stage rejected the candidate. M2-C2's UI
            # consumes the *absence* of a row as the unverified
            # signal — no DB row for an emitted quote means "we
            # couldn't verify it; render as unverified."
            continue

        new_rows.append(
            MessageCitation(
                message_id=message_id,
                source_file_id=cand.source_file_id,
                source_offset_start=cand.source_offset_start,
                source_offset_end=cand.source_offset_end,
                source_page=cand.source_page,
                source_text=cand.source_text,
                verified=True,
                verification_method=result.method,
                verification_confidence=result.confidence,
                partial=result.partial,
                tier_envelope=result.tier_envelope,
            )
        )

    if not new_rows:
        return

    db.add_all(new_rows)
    await db.commit()

    log.info(
        "chat-send citations: persisted",
        extra={
            "event": "chat_message_citations_persisted",
            "message_id": str(message_id),
            "citation_count": len(new_rows),
        },
    )


async def _persist_assistant_message(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    chat_id: uuid.UUID,
    content: str,
    requested_model: str | None,
    routed_provider: str | None,
    routed_model: str | None,
    routed_inference_tier: int | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost_estimate_usd: float | None,
    applied_skills: list[str],
    error_code: str | None,
    kind: str = "ai",
) -> Message:
    """Insert one assistant message row in its own transaction.

    The handler calls this exactly once per request — at end-of-stream
    for streaming, after the gateway response for non-streaming. We
    take the explicit ``message_id`` so the value matches the
    ``lq_ai_message_id`` we forwarded to the gateway, which means the
    gateway's routing-log row's ``message_id`` resolves to this row.

    ``requested_model`` is the value the client sent in
    ``ChatCompletionRequest.model`` (ADR 0011 follow-on). It may match
    the ``routed_*`` pair (direct dispatch) or differ (alias resolved
    server-side); persisting both lets the UI explain the difference.

    ``kind`` is the messages.kind discriminator (T1). Defaults to
    ``'ai'`` because this helper exclusively persists assistant rows;
    callers can override (e.g., to ``'refusal'`` if a future surface
    needs it) but should never let the DB default of ``'user'`` leak
    in — that's the latent T1 bug this parameter exists to prevent.
    """

    row = Message(
        id=message_id,
        chat_id=chat_id,
        role="assistant",
        kind=kind,
        content=content,
        applied_skills=list(applied_skills),
        routed_inference_tier=routed_inference_tier,
        routed_provider=routed_provider,
        routed_model=routed_model,
        requested_model=requested_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_estimate_micros=usd_to_micros(cost_estimate_usd),
        error_code=error_code,
        citations=[],
    )
    db.add(row)
    await db.flush()

    # Wave C — chain-of-custody row per PRD §3.3 data model.
    # Skipped on error_code (no model-generated artifact to attribute).
    if error_code is None:
        await _write_work_product_attribution(
            db,
            message=row,
            applied_skills=applied_skills,
            routed_inference_tier=routed_inference_tier,
            routed_provider=routed_provider,
            routed_model=routed_model,
        )

    await db.commit()
    await db.refresh(row)
    return row


async def _write_work_product_attribution(
    db: AsyncSession,
    *,
    message: Message,
    applied_skills: list[str],
    routed_inference_tier: int | None,
    routed_provider: str | None,
    routed_model: str | None,
) -> None:
    """Insert the WorkProductAttribution row for a successful assistant
    message (Wave C — PRD §3.3).

    Same single-transaction-commit pattern as the audit-log writes —
    the attribution row rides the same flush as the Message itself so
    a chat send is either fully persisted (message + attribution) or
    not at all.
    """

    import hashlib

    from app.models.chat import Chat as ChatORM
    from app.models.work_product import WorkProductAttribution

    # Look up the chat to populate the owner + project denormalized
    # columns. The chat row was loaded earlier by the calling handler;
    # a per-message lookup keeps this helper self-contained.
    chat_row = await db.get(ChatORM, message.chat_id)
    if chat_row is None:  # pragma: no cover — message FK guarantees existence
        return

    content_hash = hashlib.sha256((message.content or "").encode("utf-8")).hexdigest()

    attribution = WorkProductAttribution(
        message_id=message.id,
        user_id=chat_row.owner_id,
        chat_id=message.chat_id,
        project_id=chat_row.project_id,
        routed_inference_tier=routed_inference_tier,
        provider=routed_provider,
        model=routed_model,
        model_version=routed_model,
        skill_ids=list(applied_skills or []),
        playbook_id=None,
        content_hash=content_hash,
    )
    db.add(attribution)
    await db.flush()


async def _non_streaming_response(
    *,
    db: AsyncSession,
    user: User,
    gateway: GatewayClient,
    request: ChatCompletionRequest,
    chat: Chat,
    assistant_message_id: uuid.UUID,
    user_message_id: uuid.UUID,
    request_id: str,
    retrieved_chunks: list[HybridSearchResult] | None = None,
    http_request: Request | None = None,
    attached_skill_names: list[str] | None = None,
    slash_unresolved: bool = False,
    attached_skill_provenance: list[dict[str, str | None]] | None = None,
    project_ensemble_verification: bool = False,
) -> JSONResponse:
    """Run the non-streaming path: forward, persist, return JSON.

    Wave D.2 Task 2.7 — ``attached_skill_names`` and ``slash_unresolved``
    are propagated from :func:`send_message`'s slash-fallback path.
    Defaults preserve the pre-Task-2.7 wire contract for any caller
    that doesn't pass them in."""

    try:
        response = await gateway.chat_completion(request, request_id=request_id)
    except LQAIError as exc:
        # Gateway-side failure: the user message is already persisted.
        # We do NOT persist an assistant row — the assistant produced
        # nothing. The error envelope from the global LQAIError handler
        # surfaces the failure to the client. This is the
        # gateway-failure-pre-stream case.
        log.warning(
            "chat send_message failed pre-response",
            extra={
                "event": "chat_send_message_failed_pre",
                "user_id": str(user.id),
                "chat_id": str(chat.id),
                "assistant_message_id": str(assistant_message_id),
                "request_id": request_id,
                "error_code": getattr(exc, "effective_code", "internal_error"),
            },
        )
        raise

    assistant_text = ""
    if response.choices:
        message = response.choices[0].message
        assistant_text = message.content or ""

    applied_skills = list(response.lq_ai_applied_skills or [])

    persisted = await _persist_assistant_message(
        db,
        message_id=assistant_message_id,
        chat_id=chat.id,
        content=assistant_text,
        requested_model=request.model,
        routed_provider=response.routed_provider,
        routed_model=response.model,
        routed_inference_tier=response.routed_inference_tier,
        prompt_tokens=response.usage.prompt_tokens if response.usage else None,
        completion_tokens=response.usage.completion_tokens if response.usage else None,
        cost_estimate_usd=response.cost_estimate,
        applied_skills=applied_skills,
        error_code=None,
    )

    # M2-A2 / M2-B1 / M2-C1 / M2-D1: extract + verify + persist
    # citations from the assistant response. Cascade: Stage 1
    # (exact-match) → Stage 2 (tolerant-match) → Stage 3 (single
    # paraphrase judge) OR Stage 4 (ensemble) when activated. No-op
    # when no chunks were retrieved.
    await _persist_message_citations(
        db,
        message_id=assistant_message_id,
        assistant_text=assistant_text,
        retrieved_chunks=retrieved_chunks or [],
        gateway=gateway,
        applied_skills=applied_skills,
        project_ensemble_verification=project_ensemble_verification,
        skill_registry=_skill_registry_from_request(http_request),
    )

    await _audit_message_sent(
        db,
        user=user,
        chat=chat,
        assistant_message_id=assistant_message_id,
        user_message_id=user_message_id,
        routed_inference_tier=response.routed_inference_tier,
        routed_provider=response.routed_provider,
        applied_skills=applied_skills,
        error_code=None,
        request=http_request,
        attached_skill_provenance=attached_skill_provenance,
    )

    body = MessagePostResponse(
        message=message_to_response(persisted),
        citations=[],
        routed_inference_tier=response.routed_inference_tier,
        routed_provider=response.routed_provider,
        cost_estimate=response.cost_estimate,
        applied_skills=applied_skills,
        applied_file_ids=list(request.lq_ai_file_ids),
        attached_skill_names=list(attached_skill_names or []),
        slash_unresolved=slash_unresolved,
    )

    headers: dict[str, str] = {}
    if response.routed_inference_tier is not None:
        headers["X-LQ-AI-Routed-Inference-Tier"] = str(response.routed_inference_tier)
    if response.routed_provider is not None:
        headers["X-LQ-AI-Routed-Provider"] = response.routed_provider

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=body.model_dump(mode="json"),
        headers=headers,
    )


async def _stream_response(
    *,
    db: AsyncSession,
    user: User,
    gateway: GatewayClient,
    request: ChatCompletionRequest,
    chat: Chat,
    assistant_message_id: uuid.UUID,
    user_message_id: uuid.UUID,
    request_id: str,
    retrieved_chunks: list[HybridSearchResult] | None = None,
    http_request: Request | None = None,
    attached_skill_provenance: list[dict[str, str | None]] | None = None,
    project_ensemble_verification: bool = False,
) -> StreamingResponse:
    """Run the streaming path: forward, stream SSE, persist at end."""

    async def _generate() -> AsyncIterator[bytes]:
        accumulated: list[str] = []
        last_tier: int | None = None
        last_provider: str | None = None
        last_model: str | None = None
        last_applied_skills: list[str] | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        error_code: str | None = None
        error_envelope: dict[str, Any] | None = None

        # The opening frame carries the ``lq_ai_message_id`` so clients
        # can poll the persisted row later. Per ADR 0007 / C3 brief.
        opening = {
            "type": "start",
            "lq_ai_message_id": str(assistant_message_id),
            "chat_id": str(chat.id),
        }
        yield f"data: {_json.dumps(opening, separators=(',', ':'))}\n\n".encode()

        try:
            async for chunk in gateway.chat_completion_stream(request, request_id=request_id):
                last_tier = chunk.routed_inference_tier or last_tier
                last_provider = chunk.routed_provider or last_provider
                last_model = chunk.model
                if chunk.lq_ai_applied_skills is not None:
                    last_applied_skills = list(chunk.lq_ai_applied_skills)
                if chunk.usage is not None:
                    if chunk.usage.prompt_tokens:
                        prompt_tokens = chunk.usage.prompt_tokens
                    if chunk.usage.completion_tokens:
                        completion_tokens = chunk.usage.completion_tokens

                for choice in chunk.choices:
                    delta = choice.delta.content or ""
                    if not delta:
                        continue
                    accumulated.append(delta)
                    frame: dict[str, Any] = {
                        "type": "delta",
                        "delta": delta,
                        "lq_ai_message_id": str(assistant_message_id),
                    }
                    # Per ADR 0007 / C3 brief: surface the LQ.AI extension
                    # fields on each chunk so header-blind clients can
                    # observe routing without a separate request.
                    if last_tier is not None:
                        frame["routed_inference_tier"] = last_tier
                    if last_applied_skills is not None:
                        frame["applied_skills"] = list(last_applied_skills)
                    yield f"data: {_json.dumps(frame, separators=(',', ':'))}\n\n".encode()
        except LQAIError as exc:
            # Stream ended in failure. We persist a partial assistant
            # row with whatever content the client already saw, and
            # ``error_code`` populated. This is the audit-friendly
            # decision documented inline in the C3 brief.
            error_code = exc.effective_code
            error_envelope = exc.to_envelope()
            log.warning(
                "chat send_message failed mid-stream",
                extra={
                    "event": "chat_send_message_failed_mid_stream",
                    "user_id": str(user.id),
                    "chat_id": str(chat.id),
                    "assistant_message_id": str(assistant_message_id),
                    "request_id": request_id,
                    "error_code": error_code,
                },
            )

        # Persist the assistant row exactly once. Even if everything
        # failed, we record what we got so operators see the full
        # exchange. ``content`` may be empty if the failure happened
        # before the first chunk.
        try:
            await _persist_assistant_message(
                db,
                message_id=assistant_message_id,
                chat_id=chat.id,
                content="".join(accumulated),
                requested_model=request.model,
                routed_provider=last_provider,
                routed_model=last_model,
                routed_inference_tier=last_tier,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                # Streaming chunks carry no cost surface today (the
                # gateway populates it on the routing log; the chunk
                # envelope has only token usage). Leave NULL on the
                # message; the routing-log row carries the
                # authoritative cost.
                cost_estimate_usd=None,
                applied_skills=last_applied_skills or [],
                error_code=error_code,
            )
            # M2-A2 / M2-D1: citations from the streamed assistant
            # content. Skipped on error_code (no full artifact to
            # cite). Failures here must not block the stream; log
            # and continue.
            if error_code is None:
                try:
                    await _persist_message_citations(
                        db,
                        message_id=assistant_message_id,
                        assistant_text="".join(accumulated),
                        retrieved_chunks=retrieved_chunks or [],
                        gateway=gateway,
                        applied_skills=last_applied_skills,
                        project_ensemble_verification=project_ensemble_verification,
                        skill_registry=_skill_registry_from_request(http_request),
                    )
                except Exception as cite_exc:
                    log.warning(
                        "chat send_message: citation persistence failed",
                        extra={
                            "event": "chat_citation_persist_failed",
                            "user_id": str(user.id),
                            "chat_id": str(chat.id),
                            "assistant_message_id": str(assistant_message_id),
                            "error": str(cite_exc),
                        },
                    )
            # D3 audit row — best-effort, must not break the stream.
            try:
                await _audit_message_sent(
                    db,
                    user=user,
                    chat=chat,
                    assistant_message_id=assistant_message_id,
                    user_message_id=user_message_id,
                    routed_inference_tier=last_tier,
                    routed_provider=last_provider,
                    applied_skills=last_applied_skills or [],
                    error_code=error_code,
                    request=http_request,
                    attached_skill_provenance=attached_skill_provenance,
                )
            except Exception as audit_exc:
                log.warning(
                    "chat send_message: failed to write audit row",
                    extra={
                        "event": "chat_audit_failed",
                        "user_id": str(user.id),
                        "chat_id": str(chat.id),
                        "assistant_message_id": str(assistant_message_id),
                        "error": str(audit_exc),
                    },
                )
        except Exception as persist_exc:
            # Persisting the audit row must not break the stream; the
            # operator sees this in logs and the client gets the same
            # final SSE frames it would have without the failure.
            log.error(
                "chat send_message: failed to persist assistant row",
                extra={
                    "event": "chat_persist_failed",
                    "user_id": str(user.id),
                    "chat_id": str(chat.id),
                    "assistant_message_id": str(assistant_message_id),
                    "error": repr(persist_exc),
                },
            )

        # Final frames.
        if error_envelope is not None:
            yield (f"data: {_json.dumps(error_envelope, separators=(',', ':'))}\n\n".encode())
        else:
            complete: dict[str, Any] = {
                "type": "complete",
                "lq_ai_message_id": str(assistant_message_id),
                "message": {
                    "id": str(assistant_message_id),
                    "chat_id": str(chat.id),
                    "role": "assistant",
                    "content": "".join(accumulated),
                    "model": last_model,
                    "provider": last_provider,
                    "routed_inference_tier": last_tier,
                    "tokens_in": prompt_tokens,
                    "tokens_out": completion_tokens,
                    "created_at": datetime.now(tz=UTC).isoformat(),
                },
                "applied_skills": last_applied_skills or [],
                # Donna — echo the validated, caller-owned file ids that
                # were forwarded to the gateway for this turn (mirrors
                # ``applied_skills``; turn-scoped, not persisted).
                "applied_file_ids": list(request.lq_ai_file_ids),
                "citations": [],
                "routed_inference_tier": last_tier,
                "routed_provider": last_provider,
            }
            yield f"data: {_json.dumps(complete, separators=(',', ':'))}\n\n".encode()

        yield b"data: [DONE]\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Wave D.1 T4 — admin tier-floor override helper
# ---------------------------------------------------------------------------


async def run_inference_override(
    *,
    db: AsyncSession,
    gateway: GatewayClient,
    chat: Chat,
    user: User,
    user_msg: Message,
    refusal_msg: Message,
    override_reason: str,
    request: Request | None = None,
) -> tuple[Message, uuid.UUID | None]:
    """Re-run a refused inference with the tier floor lifted.

    Wave D.1 T4. Admin-only re-run of a refused user message: the
    backend forwards the original user prompt to the gateway with both
    ``minimum_inference_tier`` and ``lq_ai_project_minimum_inference_tier``
    set to ``None`` so no tier floor binds for this turn. The new
    assistant row is persisted with ``kind='ai'`` on initial INSERT
    (via the ``kind`` parameter on :func:`_persist_assistant_message`)
    so the UI can tell it apart from the refusal it supersedes, and so
    the row's kind never disagrees with the audit row written by the
    caller.

    Mirrors the synchronous, non-streaming branch of ``send_message``
    (no SSE; one-shot JSON) — the override surface is admin-driven and
    doesn't require streaming. Returns the persisted assistant
    :class:`Message` plus the gateway-written
    ``inference_routing_log`` row id (lookup by ``message_id``; the
    gateway is still the canonical writer per B4).

    ``override_reason`` is captured in the request log envelope; the
    caller writes the audit row (we keep audit + commit in the
    handler so the handler's transaction boundary is explicit).
    """

    assistant_message_id = uuid.uuid4()
    request_id = (
        (request.headers.get("x-request-id") if request else None)
        or (request.headers.get("x-correlation-id") if request else None)
        or f"req_{uuid.uuid4().hex}"
    )

    # Build the gateway request. Critically: do NOT forward the
    # project floor and do NOT set a per-call minimum — both are None
    # for this turn so the gateway routes without a tier floor.
    gw_request = ChatCompletionRequest(
        model="smart",
        messages=[ChatCompletionMessage(role="user", content=user_msg.content)],
        stream=False,
        chat_id=str(chat.id),
        lq_ai_chat_id=str(chat.id),
        lq_ai_message_id=str(assistant_message_id),
        lq_ai_user_id=str(user.id),
        lq_ai_skills=list(user_msg.applied_skills or []),
        minimum_inference_tier=None,
        lq_ai_project_minimum_inference_tier=None,
    )

    log.info(
        "inference override re-run",
        extra={
            "event": "inference_tier_floor_override",
            "user_id": str(user.id),
            "chat_id": str(chat.id),
            "refusal_message_id": str(refusal_msg.id),
            "assistant_message_id": str(assistant_message_id),
            "request_id": request_id,
            # ``override_reason`` is recorded on the audit row by the
            # caller; we log presence here but not the prose so the
            # operator log stays terse.
            "override_reason_present": bool(override_reason),
        },
    )

    response = await gateway.chat_completion(gw_request, request_id=request_id)

    assistant_text = ""
    if response.choices:
        assistant_text = response.choices[0].message.content or ""

    applied_skills = list(response.lq_ai_applied_skills or [])

    # Persist the assistant message with ``kind='ai'`` (the new row is
    # a successful AI response, not a refusal). The helper writes
    # ``kind`` on initial INSERT so the message + audit row never
    # disagree about what kind of row this is (T1 + T4).
    persisted = await _persist_assistant_message(
        db,
        message_id=assistant_message_id,
        chat_id=chat.id,
        content=assistant_text,
        requested_model=gw_request.model,
        routed_provider=response.routed_provider,
        routed_model=response.model,
        routed_inference_tier=response.routed_inference_tier,
        prompt_tokens=response.usage.prompt_tokens if response.usage else None,
        completion_tokens=response.usage.completion_tokens if response.usage else None,
        cost_estimate_usd=response.cost_estimate,
        applied_skills=applied_skills,
        error_code=None,
        kind="ai",
    )

    # Look up the gateway-written routing log row by message_id. The
    # gateway is the canonical writer (B4); the row exists by the time
    # ``chat_completion`` returns. Returns None if the gateway did not
    # write one (defensive — keeps the helper testable when the test
    # stubs respx and doesn't write to the routing-log table).
    routing_log_row = await db.execute(
        select(InferenceRoutingLog.id).where(InferenceRoutingLog.message_id == assistant_message_id)
    )
    routing_log_id = routing_log_row.scalar_one_or_none()

    return persisted, routing_log_id


__all__ = [
    "create_chat",
    "delete_chat",
    "get_chat",
    "get_citations",
    "list_chats",
    "list_messages",
    "router",
    "run_inference_override",
    "send_message",
    "update_chat",
]
