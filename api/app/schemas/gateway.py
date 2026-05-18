"""Pydantic schemas mirroring the gateway's OpenAI-compatible surface.

The gateway exposes :doc:`/v1/chat/completions <docs/api/gateway-openapi.yaml>`
as its inference entrypoint. This module declares the request and response
shapes the backend uses to talk to that surface. The shapes mirror
``gateway/app/providers/openai_schema.py`` (B3) — by ADR 0003 / CLAUDE.md
they cannot import from ``gateway/`` directly, so the parallel definitions
are kept in sync against the OpenAPI sketch.

LQ.AI extensions documented in ``docs/api/gateway-openapi.yaml``:

* Request side: ``minimum_inference_tier``, ``skill_name``, ``chat_id``,
  ``anonymize``.
* Response side: ``routed_inference_tier``, ``routed_provider``,
  ``cost_estimate``, ``anonymization_applied``.

Permissive policy
-----------------

``extra="allow"`` on the response models so a forward-looking gateway
revision (or a streaming chunk variant we don't know about yet) round-trips
without rejection. The backend reads only the fields it needs.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChatRole = Literal["system", "user", "assistant", "tool"]


# --- Chat completion request --------------------------------------------------


class ChatCompletionMessage(BaseModel):
    """One message in a chat-completion request or response."""

    model_config = ConfigDict(extra="allow")

    role: ChatRole
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    # M2-D2: when True, the gateway's anonymization pre-middleware
    # leaves this message's content unchanged. The api/ sets this on
    # the retrieval-context system message per Decision M2-1 so the
    # model sees intact source quotes for citation grounding. Mirrors
    # the gateway-side schema field of the same name.
    lq_ai_skip_anonymization: bool = False


class InlineSkillRef(BaseModel):
    """Wave D.2 Task 3.0 — one inline-body skill on a chat completion request.

    Mirrors :class:`gateway.app.providers.openai_schema.InlineSkillRef`.
    Forwarded from the backend's ``MessageCreateRequest.attached_skills``
    when an entry carries ``inline_body``: the backend synthesizes a
    name (so the gateway's assembler can key inputs / report applied
    skills consistently) and forwards the verbatim body without a
    catalogue fetch.

    .. note::

       OpenAPI sync deferred to Wave 9.1.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=128)
    """Synthesized, opaque name (e.g., ``__inline__<hex>``) so the
    gateway can key into ``lq_ai_skill_inputs`` and report the skill in
    ``lq_ai_applied_skills`` deterministically. Backend chooses; gateway
    never validates against the catalogue."""

    body: str = Field(min_length=1)
    """Verbatim Markdown skill body. The gateway treats this as the
    skill's ``content_md`` and runs it through the same assembler as
    catalogue skills (header / input substitution / system-message
    prepend) without an HTTP round-trip to the backend."""

    inputs: dict[str, Any] | None = None
    """Optional per-skill input bindings. Merged into
    ``lq_ai_skill_inputs`` server-side under this synthesized name."""

    minimum_inference_tier: int | None = Field(default=None, ge=1, le=5)
    """D1 tier-floor honored exactly like a catalogue skill's floor."""

    source: str | None = Field(default=None, max_length=64)
    """Provenance tag (``wizard-tryout``, etc.) — surfaced on audit logs."""


class ChatCompletionRequest(BaseModel):
    """OpenAI Chat Completions request body, plus LQ.AI extensions.

    The backend constructs one of these and posts it to the gateway's
    ``/v1/chat/completions`` endpoint. ``model`` is the operator-defined
    alias (``smart``, ``fast``) or a provider-native model name; the
    gateway router resolves it.
    """

    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    messages: list[ChatCompletionMessage]
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    stream: bool = False
    stop: list[str] | str | None = None
    n: int | None = Field(default=None, ge=1, le=1)

    # --- LQ.AI extensions (per gateway-openapi.yaml) -------------------------
    minimum_inference_tier: int | None = Field(default=None, ge=1, le=5)
    """D1: per-call request override of the tier floor. Most-restrictive
    of (this, project floor, skill floor) wins; gateway returns 403
    ``tier_below_minimum`` when routed tier falls below the effective
    floor."""

    lq_ai_project_minimum_inference_tier: int | None = Field(default=None, ge=1, le=5)
    """D1: backend forwards ``Project.minimum_inference_tier`` here when
    the chat lives in a project. Distinct surface from the request
    override so the gateway can attribute refusal source correctly."""

    skill_name: str | None = None
    chat_id: str | None = None
    anonymize: bool = True

    lq_ai_privileged: bool = False
    """M2-B3: backend forwards ``Project.privileged`` here when the chat
    lives in a project. The gateway's anonymization middleware skips
    entirely on ``True`` — rewriting attorney-client privileged work
    product risks corrupting it, so the conservative posture is
    "don't touch it." Defaults False so chats outside any project (and
    chats whose project is non-privileged) get the normal middleware
    behavior."""

    # --- C2 (skill prompt assembly per ADR 0007) -----------------------------
    lq_ai_skills: list[str] = Field(default_factory=list, max_length=16)
    """Skill names to attach. The gateway fetches each from
    ``/api/v1/internal/skills/{name}`` and assembles them into the
    system message before dispatching to the provider. Capped at 16
    entries (Wave D.2 Task 3.0 I1) to mirror
    ``ATTACHED_SKILLS_MAX_LEN`` on the request schema and bound the
    workload-multiplication DoS surface."""

    lq_ai_skill_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Per-skill input bindings, keyed by skill name."""

    lq_ai_inline_skills: list[InlineSkillRef] = Field(default_factory=list, max_length=16)
    """Wave D.2 Task 3.0: inline-body skills the gateway assembles
    without a catalogue fetch. Mirrors
    :attr:`gateway.app.providers.openai_schema.ChatCompletionRequest.lq_ai_inline_skills`.
    Empty list (default) preserves pre-D.2 wire shape exactly. Capped at
    16 entries (I1) to bound the workload-multiplication DoS surface —
    each entry can carry up to 64 KB of body content x catalogue
    round-trips for slug entries on the parallel list."""

    # --- C3 (chat / message identity for routing-log correlation) ------------
    lq_ai_chat_id: str | None = None
    """UUID for ``inference_routing_log.chat_id``. The backend generates
    the chat id (from the persisted ``chats`` row) and forwards it on
    the request envelope so the routing-log row carries it.
    Distinct from the pre-existing ``chat_id`` field (B3-era audit-log
    tag); ``lq_ai_chat_id`` takes precedence when both are present and
    is the canonical surface after C3."""

    lq_ai_message_id: str | None = None
    """UUID for ``inference_routing_log.message_id``. The backend
    generates a UUID for the assistant message *before* dispatch and
    forwards it; the gateway writes the same UUID into the routing log
    so the log row joins to the persisted message row by ``id``."""

    lq_ai_user_id: str | None = None
    """UUID of the authenticated user the request belongs to. The
    gateway uses this to look up user-scope skill shadows (ADR 0012)
    during prompt assembly — when set, ``/internal/skills/{slug}``
    resolves to the user's row first and falls back to the
    filesystem-canonical built-in. Omitted means "registry-only",
    which is the right behavior for non-user-bearing callers."""

    lq_ai_purpose: str | None = None
    """M2-E2: tag for the gateway's routing-log ``purpose`` column.
    Distinguishes Citation Engine Stage 3/4 judge calls from regular
    chat completions so per-model cost calibration filters
    routing-log rows down to judge traffic. Known values used in
    code: ``'judge_paraphrase'``. ``None`` or any unknown value
    records as ``'chat'`` on the gateway side. Stripped from the
    outbound provider body."""


# --- Chat completion response -------------------------------------------------


class ChatCompletionUsage(BaseModel):
    """Token-usage summary, OpenAI-shaped."""

    model_config = ConfigDict(extra="allow")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


FinishReason = Literal["stop", "length", "content_filter", "tool_calls"]


class ChatCompletionChoice(BaseModel):
    """One choice in a non-streaming chat-completion response."""

    model_config = ConfigDict(extra="allow")

    index: int = 0
    message: ChatCompletionMessage
    finish_reason: FinishReason | None = None


class ChatCompletionResponse(BaseModel):
    """Non-streaming chat-completion response body.

    Mirrors OpenAI's ``chat.completion`` plus the LQ.AI extension fields
    populated by the gateway (``routed_inference_tier``, etc.). The
    backend reads these to surface tier annotations to the API caller.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage = Field(default_factory=ChatCompletionUsage)

    # --- LQ.AI extensions ---------------------------------------------------
    routed_inference_tier: int | None = Field(default=None, ge=1, le=5)
    routed_provider: str | None = None
    cost_estimate: float | None = None
    anonymization_applied: bool | None = None
    lq_ai_applied_skills: list[str] | None = None
    """Skills successfully assembled into the prompt for this request
    (C2). Null when no skills were attached. Backend surfaces this in
    audit logs and the chat response."""


# --- Streaming chunk ----------------------------------------------------------


class ChatCompletionDelta(BaseModel):
    """Partial message delta inside a streaming chunk."""

    model_config = ConfigDict(extra="allow")

    role: ChatRole | None = None
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ChatCompletionChunkChoice(BaseModel):
    """One choice in a streaming chat-completion chunk."""

    model_config = ConfigDict(extra="allow")

    index: int = 0
    delta: ChatCompletionDelta = Field(default_factory=ChatCompletionDelta)
    finish_reason: FinishReason | None = None


class ChatCompletionChunk(BaseModel):
    """Streaming chat-completion chunk envelope.

    The gateway emits these as ``data: <json>`` SSE frames; the backend
    deserializes each frame back into a chunk via the streaming helper
    in :mod:`app.clients.gateway`.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChunkChoice]
    usage: ChatCompletionUsage | None = None

    # --- LQ.AI extensions ---------------------------------------------------
    routed_inference_tier: int | None = Field(default=None, ge=1, le=5)
    routed_provider: str | None = None
    lq_ai_applied_skills: list[str] | None = None


# --- Gateway error envelope --------------------------------------------------


class GatewayErrorPayload(BaseModel):
    """Inner error object — matches ``GatewayError.error`` in the sketch."""

    model_config = ConfigDict(extra="allow")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class GatewayErrorEnvelope(BaseModel):
    """Outer ``GatewayError`` shape — ``{"error": {...}}``.

    The backend deserializes any non-2xx response body into one of these
    so the gateway client can map ``error.code`` to the appropriate
    backend exception class via :func:`app.errors.map_gateway_error_code`.
    """

    error: GatewayErrorPayload
