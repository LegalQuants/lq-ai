"""Pydantic schemas for the chats + messages surface (Task C3).

Wire shapes for ``/api/v1/chats`` and ``/api/v1/chats/{id}/messages``
matching ``Chat``, ``ChatCreate``, ``ChatUpdate``, ``Message``,
``MessageCreate``, and ``MessagePostResponse`` in
``docs/api/backend-openapi.yaml``. The ORM models live in
``app.models.chat``; this module is the request/response surface.

Notes
-----

* ``MessageCreate`` extends OpenAPI's existing shape with the
  C2-introduced ``skills`` and ``skill_inputs`` fields. C3 adds nothing
  to that shape — message persistence is a server-side concern, not a
  request-body concern.
* ``Cursor`` pagination uses an opaque base64-encoded ``(created_at,
  id)`` tuple. The cursor is symmetric: encoded server-side on the
  ``next_cursor`` of one page, decoded server-side on the request's
  ``cursor`` query param. We keep the format internal so the client
  cannot manufacture cursors that bypass per-user isolation (the
  handler validates the decoded ``id`` belongs to the caller).
* Cost is presented over the wire as ``cost_estimate`` (a USD float)
  for client friendliness. Internally it is stored as integer USD
  micros (``cost_estimate_micros``); :func:`micros_to_usd` and
  :func:`usd_to_micros` translate.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

# --- Constants ---------------------------------------------------------------

TITLE_MAX_LEN: int = 200
"""Hard cap on chat ``title``. Matches the DB CHECK constraint."""

CONTENT_MIN_LEN: int = 1
"""Minimum length of a ``MessageCreate`` content string."""

AUTO_RENAME_MAX_CHARS: int = 80
"""First-message auto-rename truncation length (per C3 brief)."""

LIST_LIMIT_DEFAULT: int = 20
"""Default page size for chat / message listing."""

LIST_LIMIT_MAX: int = 100
"""Maximum page size accepted by the listing endpoints."""

INLINE_SKILL_BODY_MAX_BYTES: int = 32 * 1024
"""Wave D.2 Task 3.0 — hard cap on ``AttachedSkillRef.inline_body`` size.

Inline-body skills become part of the system prompt without a catalog
fetch. The body is fully user-controlled (the wizard's "Try it" mode
sends the user's draft body verbatim) so we bound it server-side
defensively: a 32 KB ceiling is roughly 8k tokens which comfortably
covers a long skill body but cuts off pathological inputs (full
documents pasted as a "skill"). 422 on overflow keeps the failure mode
explicit rather than letting the gateway choke on a 1 MB system prompt."""

ATTACHED_SKILLS_MAX_LEN: int = 16
"""Wave D.2 Task 3.0 (I1) — hard cap on the length of
``MessageCreateRequest.attached_skills`` and the legacy ``skills`` list.

Each list entry can ship up to ``INLINE_SKILL_BODY_MAX_BYTES`` (32 KB)
of verbatim body content plus an additional catalogue round-trip for
slug entries. Without a cap, a single message could attach thousands
of inline refs and force the gateway to assemble a multi-megabyte
system prompt — workload-multiplication DoS available to any
authenticated user. 16 is generous for realistic workflows: the slash
path attaches exactly one skill, the wizard tryout attaches exactly
one, and even an "attach multiple skills to a chat" UX rarely exceeds
a handful. Requests with more than 16 attachments 422 at schema time."""

MESSAGE_FILE_IDS_MAX_LEN: int = 16
"""Donna — hard cap on ``MessageCreateRequest.file_ids``.

Each id triggers an ownership-validation SELECT and forwards document
context to the gateway for one turn. Without a cap, a single message
could attach thousands of file ids — workload-multiplication DoS
available to any authenticated user. 16 matches
:data:`ATTACHED_SKILLS_MAX_LEN`; realistic per-turn document context is
a handful of files. Requests over the cap 422 at schema time."""

KNOWN_ATTACHED_SKILL_SOURCES: frozenset[str] = frozenset(
    {"slash", "wizard-tryout", "tryit-tab", "capture", "manual"}
)
"""Wave D.2 Task 3.0 — non-exhaustive list of recognized ``source``
values. The field is intentionally NOT enum-validated so future surfaces
(Word add-in, batch API, etc.) can introduce new sources without a
schema migration. The set is published so callers know the canonical
spellings."""


# --- Type aliases ------------------------------------------------------------

ChatTitle = Annotated[
    str,
    StringConstraints(min_length=1, max_length=TITLE_MAX_LEN, strip_whitespace=True),
]
"""1-200 chars, leading/trailing whitespace stripped."""


# --- Cost helpers ------------------------------------------------------------


def usd_to_micros(value: float | None) -> int | None:
    """Convert a USD float to integer micros (1e-6 USD).

    Returns ``None`` for ``None`` (the gateway leaves cost ``None`` when
    no rate is configured for the routed model). Handles edge cases:

    * ``0.0`` → ``0`` (round-trips as zero, not None — operators want
      to see "we routed this for free" distinctly from "we don't know").
    * Negative values → preserved as negative (operator can't reasonably
      get one, but if the gateway emits one we shouldn't lose the sign).
    * Very large floats → caller's responsibility; we round to the
      nearest integer micro and trust the BIGINT column to hold it.

    Uses :func:`round` (banker's rounding in Python 3.x) on the product
    so .5-cases round to even. The audit-log delta from one micro
    either way is well below "matters to a lawyer".
    """

    if value is None:
        return None
    return round(value * 1_000_000)


def micros_to_usd(value: int | None) -> float | None:
    """Convert integer micros back to a USD float.

    Inverse of :func:`usd_to_micros`. Returns ``None`` for ``None``.
    The float result has at most 6 decimal places of significance;
    formatting to fewer is the caller's concern.
    """

    if value is None:
        return None
    return value / 1_000_000


# --- Auto-rename helpers -----------------------------------------------------


def derive_chat_title(message_content: str) -> str:
    """Derive a chat title from the first user message.

    Strategy:

    * Take the first non-empty line (newlines and CRLF terminate).
    * Collapse runs of whitespace to single spaces.
    * Truncate to ``AUTO_RENAME_MAX_CHARS`` chars; append an ellipsis
      character (U+2026) if truncated.
    * Strip leading/trailing whitespace.
    * Fall back to ``"New chat"`` if the result is empty.

    Returns a string suitable for assignment to ``chats.title``.
    """

    if not message_content:
        return "New chat"

    # Take the first non-empty line.
    first_line = ""
    for line in message_content.splitlines():
        stripped = line.strip()
        if stripped:
            first_line = stripped
            break
    if not first_line:
        return "New chat"

    # Collapse internal whitespace runs.
    collapsed = " ".join(first_line.split())
    if len(collapsed) <= AUTO_RENAME_MAX_CHARS:
        return collapsed
    # Truncate, leaving room for the ellipsis. The ellipsis itself is
    # one codepoint so the total is AUTO_RENAME_MAX_CHARS exactly.
    head = collapsed[: AUTO_RENAME_MAX_CHARS - 1].rstrip()
    return f"{head}…"


# --- Cursor pagination -------------------------------------------------------


class Cursor(BaseModel):
    """Opaque cursor for ``(created_at, id)`` keyset pagination.

    Encoded as URL-safe base64 of a JSON dict so the wire shape is
    opaque to the client. The handler decodes, validates the ``id``
    belongs to the caller, and uses ``(created_at, id)`` as the
    keyset comparator.
    """

    model_config = ConfigDict(extra="forbid")

    created_at: datetime
    id: uuid.UUID

    def encode(self) -> str:
        """Return the URL-safe base64 string for the wire."""

        body = json.dumps(
            {"created_at": self.created_at.isoformat(), "id": str(self.id)},
            separators=(",", ":"),
        )
        return base64.urlsafe_b64encode(body.encode("utf-8")).rstrip(b"=").decode("ascii")

    @classmethod
    def decode(cls, value: str) -> Cursor:
        """Decode a wire cursor; raises ValueError on malformed input."""

        # Restore padding.
        padding = "=" * (-len(value) % 4)
        try:
            raw = base64.urlsafe_b64decode(value + padding).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("cursor is not valid base64") from exc
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("cursor body is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError("cursor body must be a JSON object")
        return cls.model_validate(decoded)


# --- Request schemas ---------------------------------------------------------


class ChatCreateRequest(BaseModel):
    """``ChatCreate`` from backend-openapi.yaml.

    All fields are optional. ``title`` defaults to ``"New chat"``
    (DB-side); when omitted, the API auto-renames the chat from the
    first user message.
    """

    model_config = ConfigDict(extra="forbid")

    title: ChatTitle | None = None
    project_id: uuid.UUID | None = None


class ChatUpdateRequest(BaseModel):
    """``ChatUpdate`` from backend-openapi.yaml.

    PATCH applies only the fields the caller sets (``exclude_unset``
    pattern at the handler boundary). ``archived`` toggles
    ``archived_at`` on/off; ``title`` updates the chat title.
    """

    model_config = ConfigDict(extra="forbid")

    title: ChatTitle | None = None
    archived: bool | None = None


class AttachedSkillRef(BaseModel):
    """Wave D.2 Task 3.0 — one entry in ``MessageCreateRequest.attached_skills``.

    Carries either a ``slug`` (a saved skill in the merged catalogue —
    built-in OR user-scoped shadow) OR an ``inline_body`` (a literal
    skill body the caller is sending without a persisted skill row, e.g.,
    the wizard's "Try it" preview). Exactly one of the two must be set;
    a request with neither or both is 422.

    ``source`` is optional provenance metadata so audit logs / receipts
    can attribute the attachment to the surface that produced it. See
    :data:`KNOWN_ATTACHED_SKILL_SOURCES` for the conventional spellings;
    the field is intentionally unrestricted so future surfaces can
    introduce new sources without a schema bump.

    .. note::

       OpenAPI sync deferred to Wave 9.1 — this shape is not yet in
       ``docs/api/backend-openapi.yaml``. The doc pass at end-of-wave
       picks it up.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Canonical skill slug (built-in OR user-shadow). XOR with ``inline_body``.",
    )
    inline_body: str | None = Field(
        default=None,
        min_length=1,
        max_length=INLINE_SKILL_BODY_MAX_BYTES,
        description=(
            "Verbatim skill body to inject without a catalogue fetch. "
            f"Capped at {INLINE_SKILL_BODY_MAX_BYTES} bytes. XOR with ``slug``."
        ),
    )
    source: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Optional provenance tag (e.g., 'slash', 'wizard-tryout', "
            "'tryit-tab', 'capture'). Surfaced on audit log + receipts."
        ),
    )
    inputs: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Per-attachment skill input bindings. For slug attachments these "
            "merge into ``MessageCreateRequest.skill_inputs`` keyed by the slug; "
            "for inline-body attachments they merge keyed by the synthesized "
            "inline-skill name (see the chats handler)."
        ),
    )

    @model_validator(mode="after")
    def _validate_xor(self) -> AttachedSkillRef:
        """Enforce: exactly one of slug / inline_body is set."""

        has_slug = self.slug is not None and self.slug.strip() != ""
        has_inline = self.inline_body is not None and self.inline_body != ""
        if has_slug and has_inline:
            raise ValueError(
                "attached_skill must set exactly one of 'slug' or 'inline_body', not both"
            )
        if not has_slug and not has_inline:
            raise ValueError("attached_skill must set exactly one of 'slug' or 'inline_body'")
        return self


class MessageCreateRequest(BaseModel):
    """``MessageCreate`` from backend-openapi.yaml (B5 + C2 + C3 + D.2).

    Wave D.2 Task 3.0 adds ``attached_skills``, a richer alternative to
    the legacy ``skills: list[str]`` shape. Both continue to work in
    parallel:

    * ``skills`` — legacy slug-only list; each entry is treated as if it
      were ``{slug: <name>}`` on an ``attached_skills`` entry. Forwarded
      to the gateway as ``lq_ai_skills``.
    * ``attached_skills`` — rich shape supporting both slug attachments
      (resolve from catalogue) and inline-body attachments (literal body
      forwarded to the gateway via ``lq_ai_inline_skills``, no catalogue
      fetch). XOR'd per-entry; the wizard's "Try it" surface uses the
      inline-body path so an unsaved draft can be tested.

    Empty ``attached_skills`` preserves the pre-D.2 behavior exactly.

    .. note::

       OpenAPI sync deferred to Wave 9.1.
    """

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=CONTENT_MIN_LEN)
    model: str = Field(default="smart")
    """Model alias (per the OpenAPI sketch). Defaults to ``smart``."""

    skills: list[str] = Field(default_factory=list, max_length=ATTACHED_SKILLS_MAX_LEN)
    """C2 (legacy): skill names to attach. Forwarded to the gateway as
    ``lq_ai_skills``. Continues to work in parallel with
    ``attached_skills``. Capped at :data:`ATTACHED_SKILLS_MAX_LEN`
    entries to bound workload multiplication (Wave D.2 Task 3.0 I1)."""

    attached_skills: list[AttachedSkillRef] = Field(
        default_factory=list,
        max_length=ATTACHED_SKILLS_MAX_LEN,
    )
    """Wave D.2 Task 3.0: rich attached-skill list. Each entry is XOR
    of ``slug`` / ``inline_body``. Slug entries merge into the legacy
    slug-resolved path; inline-body entries are forwarded as
    ``lq_ai_inline_skills`` so the gateway can assemble them without a
    catalogue fetch. Capped at :data:`ATTACHED_SKILLS_MAX_LEN` entries
    to bound workload multiplication (I1 — a single message attaching
    thousands of inline refs x 32 KB each is a DoS vector)."""

    skill_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """C2: per-skill input bindings, keyed by skill name. Forwarded as
    ``lq_ai_skill_inputs``. Per-attachment ``inputs`` on
    ``attached_skills`` entries are merged into this map at handler
    time (the per-attachment value wins on key collision).

    Note on the ``file_ids`` interaction: ``skill_inputs`` values are
    plain scalars interpolated into the skill body via ``{{name}}``
    substitution (ADR 0006 / the gateway's ``skills/assembler.py``).
    There is **no** ``type:"file"`` binding that resolves a ``file_id``
    to document content today — passing a file UUID as a skill-input
    value would interpolate the literal UUID string, not the file's
    text. To attach document context for a turn, use the separate
    :attr:`file_ids` channel below, not ``skill_inputs``."""

    file_ids: list[str] = Field(default_factory=list, max_length=MESSAGE_FILE_IDS_MAX_LEN)
    """Donna: caller-owned file UUIDs supplying ephemeral, per-message
    document context for this one chat turn. Distinct from KB attach
    (which is project-scoped and persistent): these ids bind document
    context to a single send and are not stored on the chat.

    Each id is validated server-side to exist and be owned by the
    caller (id-probing-safe: a foreign or unknown id 404s exactly like
    ``GET /files/{id}``). Validated ids are forwarded to the gateway as
    ``lq_ai_file_ids`` alongside ``lq_ai_skills`` and echoed back as
    ``applied_file_ids`` on the response / SSE ``complete`` frame.

    This is a **separate channel from** ``skill_inputs``: file_ids are
    NOT bound to a skill file-input via ``skill_inputs`` (no
    ``type:"file"`` binding is wired — see the ``skill_inputs`` note
    above). Populate ``file_ids`` for document context; populate
    ``skill_inputs`` for scalar skill parameters. Omitted / empty is
    fully back-compatible (pre-existing wire shape unchanged)."""

    stream: bool = False
    """Whether to stream the response as SSE. ``False`` returns a single
    JSON body."""


# --- Response schemas --------------------------------------------------------


class ChatResponse(BaseModel):
    """``Chat`` schema from backend-openapi.yaml.

    Built from the ORM row plus the rolled-up ``message_count``
    (counted in the handler with a single COUNT(*) per chat — fine on
    the M1 footprint).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    project_id: uuid.UUID | None = None
    title: str
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class MessageResponse(BaseModel):
    """``Message`` schema from backend-openapi.yaml.

    Cost is presented as a USD float for client friendliness; the DB
    stores integer micros and :func:`micros_to_usd` translates. The
    handler is expected to convert via :func:`message_to_response` —
    we do not use ``from_attributes=True`` here because the column
    name on the ORM row (``cost_estimate_micros``) differs from the
    wire field (``cost_estimate``).
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    chat_id: uuid.UUID
    role: Literal["user", "assistant", "system", "tool"]
    kind: Literal["user", "ai", "refusal", "system"] = "user"
    """Wave D.1 — distinguishes assistant rows that carry a model
    response (``ai``) from refusal rows (``refusal``) emitted by the
    gateway's tier-floor enforcement. Defaults to ``user`` to match the
    DB column server default; the override-tier-floor flow writes
    ``ai`` explicitly so the UI can tell a re-run apart from a refusal."""

    content: str
    applied_skills: list[str] = Field(default_factory=list)
    routed_inference_tier: int | None = None
    routed_provider: str | None = None
    routed_model: str | None = None
    requested_model: str | None = None
    """The originally-requested model alias or ``provider/model`` pair
    (ADR 0011 follow-on). Differs from ``routed_model`` when an alias
    was resolved; null on rows persisted before this column existed."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_estimate: float | None = None
    """USD float; derived from the integer micros column."""

    error_code: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime

    is_enhanced: bool = False
    """Wave D.1 T20 follow-on — true when the row's ``applied_skills``
    contains ``'enhance-prompt'`` (ADR 0007 denormalization). The
    frontend renders a ``✨ enhanced`` provenance pill on user-message
    bubbles where this is true so an operator can tell at a glance that
    the prompt that was sent had been expanded by the Enhance Prompt
    skill. Derived in :func:`message_to_response`; the field is not
    settable on the wire."""


def message_to_response(row: Any) -> MessageResponse:
    """Build a :class:`MessageResponse` from an ORM ``Message`` row.

    Materializes ``cost_estimate`` from the DB's integer micros column.
    Centralizing the conversion keeps the handler free of cost-unit
    bookkeeping and makes the schema's ``extra="forbid"`` posture
    workable (we don't accept the micros column on the wire).
    """

    applied_skills = list(row.applied_skills or [])
    return MessageResponse(
        id=row.id,
        chat_id=row.chat_id,
        role=row.role,
        kind=row.kind,
        content=row.content,
        applied_skills=applied_skills,
        routed_inference_tier=row.routed_inference_tier,
        routed_provider=row.routed_provider,
        routed_model=row.routed_model,
        requested_model=row.requested_model,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        cost_estimate=micros_to_usd(row.cost_estimate_micros),
        error_code=row.error_code,
        citations=list(row.citations or []),
        created_at=row.created_at,
        is_enhanced="enhance-prompt" in applied_skills,
    )


class ChatListResponse(BaseModel):
    """Paginated ``GET /api/v1/chats`` response."""

    model_config = ConfigDict(extra="forbid")

    items: list[ChatResponse]
    next_cursor: str | None = None


class MessageListResponse(BaseModel):
    """Paginated ``GET /api/v1/chats/{id}/messages`` response."""

    model_config = ConfigDict(extra="forbid")

    items: list[MessageResponse]
    next_cursor: str | None = None


class MessagePostResponse(BaseModel):
    """Non-streaming ``POST /api/v1/chats/{id}/messages`` response."""

    model_config = ConfigDict(extra="forbid")

    message: MessageResponse
    citations: list[dict[str, Any]] = Field(default_factory=list)
    routed_inference_tier: int | None = None
    routed_provider: str | None = None
    cost_estimate: float | None = None
    applied_skills: list[str] = Field(default_factory=list)
    applied_file_ids: list[str] = Field(default_factory=list)
    """Donna: caller-owned file ids that were validated and forwarded to
    the gateway as ``lq_ai_file_ids`` for this turn — the echo of
    :attr:`MessageCreateRequest.file_ids`. Mirrors how ``applied_skills``
    is echoed, but turn-scoped: there is no ``messages.file_ids`` column,
    so this surfaces only on the send response (and the SSE ``complete``
    frame), not on rows read back via ``GET /chats/{id}/messages``. Empty
    when no file_ids were attached."""

    attached_skill_names: list[str] = Field(default_factory=list)
    """Wave D.2 Task 2.7 — slugs the send-time slash fallback attached
    on the caller's behalf. Distinct from ``applied_skills`` (the
    gateway-reported list of skills that actually ran): this field
    captures *what the backend resolved from the message body*, so the
    frontend can render a chip / hint even before the gateway responds
    or in the unresolved-slash branch where no skill actually ran."""

    slash_unresolved: bool = False
    """Wave D.2 Task 2.7 — set when the user's content started with
    ``/<token>`` but no skill resolved against that token. The handler
    still forwards the original content to the gateway as plain text;
    this flag lets the UI surface a "couldn't resolve /foo" hint so
    typos don't silently produce non-skill answers."""


# --- Internal: helpers exposed for tests -------------------------------------


def encode_cursor(created_at: datetime, id_: uuid.UUID) -> str:
    """Encode a ``(created_at, id)`` pair as the wire cursor."""

    return Cursor(created_at=created_at, id=id_).encode()


def decode_cursor(value: str) -> Cursor:
    """Decode a wire cursor; raises ValueError on malformed input."""

    return Cursor.decode(value)


__all__ = [
    "ATTACHED_SKILLS_MAX_LEN",
    "AUTO_RENAME_MAX_CHARS",
    "CONTENT_MIN_LEN",
    "INLINE_SKILL_BODY_MAX_BYTES",
    "KNOWN_ATTACHED_SKILL_SOURCES",
    "LIST_LIMIT_DEFAULT",
    "LIST_LIMIT_MAX",
    "MESSAGE_FILE_IDS_MAX_LEN",
    "TITLE_MAX_LEN",
    "AttachedSkillRef",
    "ChatCreateRequest",
    "ChatListResponse",
    "ChatResponse",
    "ChatTitle",
    "ChatUpdateRequest",
    "Cursor",
    "MessageCreateRequest",
    "MessageListResponse",
    "MessagePostResponse",
    "MessageResponse",
    "decode_cursor",
    "derive_chat_title",
    "encode_cursor",
    "message_to_response",
    "micros_to_usd",
    "usd_to_micros",
]
