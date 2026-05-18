"""Pydantic models for the OpenAI-compatible gateway surface.

Every provider adapter consumes and emits these shapes; the gateway never
exposes a provider's native format to its callers. The field set tracks
:doc:`docs/api/gateway-openapi.yaml` (the canonical contract per
:doc:`CLAUDE.md` decision routing) plus the LQ.AI extensions documented
there:

* ``minimum_inference_tier`` — refusal floor for the request (B4/D1).
* ``skill_name``             — audit-log routing tag (no inference effect).
* ``chat_id``                — UUID for audit-log correlation.
* ``anonymize``              — anonymization opt-in (M2; ignored before).

* ``routed_inference_tier``  — derived tier echoed in the response (B4).
* ``routed_provider``        — provider name that handled the call (B4).
* ``cost_estimate``          — USD estimate for the request (cost tracker).
* ``anonymization_applied``  — whether the M2 middleware ran (M2).

These extension fields are **populated by the gateway, not the adapter**.
B3 leaves them ``None``; B4 and downstream tasks fill them as they land.

Permissive policy
-----------------

Models use ``extra="allow"`` so unknown fields from a forward-looking
caller (or a streaming chunk variant we don't know about yet) round-trip
without rejection. The adapter only reads the fields it needs.

Streaming chunks
----------------

OpenAI's chat-completion streaming format emits a sequence of objects
with ``object="chat.completion.chunk"`` and partial deltas in each
``choices[i].delta``. We model both the chunk envelope
(:class:`ChatCompletionChunk`) and the delta payload
(:class:`ChatCompletionDelta`). The gateway serializes these as SSE
``data:`` lines per the OpenAI convention.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --- Roles --------------------------------------------------------------------

ChatRole = Literal["system", "user", "assistant", "tool"]
"""OpenAI chat-completion role values.

The gateway accepts the four standard roles. Assistant-with-tool-calls and
tool-result messages pass through; B3's Anthropic adapter handles the
common case (system / user / assistant text). Tool-call translation gets
expanded as part of skills work (PRD §7) — see ``app.providers.anthropic``
for current coverage.
"""


# --- Chat completion request --------------------------------------------------


class ChatCompletionMessage(BaseModel):
    """One message in a chat-completion request or response."""

    model_config = ConfigDict(extra="allow")

    role: ChatRole
    # OpenAI permits ``content: null`` for assistant messages that have
    # tool_calls but no text. Pre-B6 we accept the full union but only
    # serialize the string case to providers.
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    # M2-D2: when True, the gateway's anonymization pre-middleware
    # leaves this message's content unchanged even if anonymization
    # is otherwise active for the request. Per Decision M2-1, the
    # api/ sets this on the retrieval-context system message so
    # source documents in retrieval are NOT pseudonymized before
    # being sent to the provider — the model needs intact source
    # quotes for citation grounding. The flag is api-internal
    # (``lq_ai_`` prefix); it's stripped before the request leaves
    # the gateway for any upstream provider.
    lq_ai_skip_anonymization: bool = False


class InlineSkillRef(BaseModel):
    """Wave D.2 Task 3.0 — one inline-body skill on a chat completion request.

    Carries a literal skill body the gateway assembles into the system
    message without an HTTP round-trip to the backend's
    ``/internal/skills/{name}`` endpoint. This unlocks the wizard's
    "Try it" surface: an unsaved draft body can be tested as a skill
    against a real send without first persisting a ``user_skills`` row.

    The ``name`` is synthesized by the backend (e.g.,
    ``__inline__<hex>``) so it never collides with a real skill slug
    (real slugs are lowercase-kebab; the synthesized form uses
    underscores, which the slug pattern rejects). The gateway uses it
    as the key into ``lq_ai_skill_inputs`` and reports it in
    ``lq_ai_applied_skills`` for audit consistency — operators see a
    distinct marker rather than an opaque token.

    .. note::

       OpenAPI sync deferred to Wave 9.1.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=128)
    """Synthesized opaque name (e.g., ``__inline__<hex>``). Backend
    chooses; gateway never validates against the catalogue."""

    body: str = Field(min_length=1, max_length=64 * 1024)
    """Verbatim Markdown skill body. The gateway treats this as the
    skill's ``content_md`` and runs the standard assembler pipeline
    over it (header / input substitution / system-message prepend).

    Hard-capped here as a defense-in-depth bound — the *backend's*
    schema applies a 32 KB cap on the upstream side; the gateway accepts
    up to 64 KB so we don't false-positive on a slightly-larger value
    from a non-backend caller, but still refuse a multi-megabyte body
    that would blow the upstream provider's context window."""

    inputs: dict[str, Any] | None = None
    """Optional per-skill input bindings. The gateway merges these
    into ``lq_ai_skill_inputs`` keyed under :attr:`name` before
    assembly."""

    minimum_inference_tier: int | None = Field(default=None, ge=1, le=5)
    """D1 tier-floor. Participates in
    :func:`app.tier_floor.resolve_tier_floor` exactly like a catalogue
    skill's floor — the synthesized :class:`Skill` instance built from
    this ref carries the tier through unchanged."""

    source: str | None = Field(default=None, max_length=64)
    """Provenance tag (``wizard-tryout``, etc.). Surfaced by the
    backend on audit-log rows; the gateway treats it as opaque
    metadata."""


class ChatCompletionRequest(BaseModel):
    """OpenAI Chat Completions request body, plus LQ.AI extensions.

    Fields beyond the OpenAI baseline are documented in
    :doc:`docs/api/gateway-openapi.yaml`. ``model`` accepts either an
    operator-defined alias from ``model_aliases`` (``smart``, ``fast``,
    etc.) or a concrete provider-native model name (``claude-sonnet-4-6``);
    B4's router decides which.
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
    """OpenAI permits ``n>1``; the gateway only serves ``n=1`` because
    Anthropic Messages doesn't expose an equivalent and supporting it
    multiplies cost without a corresponding skill use case (PRD §7).
    """

    # --- LQ.AI extensions (per gateway-openapi.yaml) -------------------------
    minimum_inference_tier: int | None = Field(default=None, ge=1, le=5)
    """D1: per-call request override of the tier floor. The most restrictive
    of (this, project floor, skill floor) wins; if the resolved routed
    tier falls below the effective floor the gateway returns HTTP 403
    with ``tier_below_minimum``."""

    lq_ai_project_minimum_inference_tier: int | None = Field(default=None, ge=1, le=5)
    """D1: project-level tier floor forwarded by the backend when the chat
    lives inside a Project (per ``Project.minimum_inference_tier``).
    Gateway never queries the backend for the project; the backend is
    the authority on whether a chat belongs to a project, and this field
    is the single carrier of the project floor on the gateway hop."""

    skill_name: str | None = None
    """Audit-log routing tag (B3 / B4); does not by itself trigger skill
    prompt assembly — see ``lq_ai_skills`` for that. When ``lq_ai_skills``
    is set and ``skill_name`` is not, the gateway populates this field
    with the first attached skill's name for audit consistency."""

    chat_id: str | None = None
    anonymize: bool = True
    """Per-request anonymization opt-out (M2-B3). ``True`` (the default)
    lets the gateway middleware pseudonymize entities before the
    provider call when the deployment-level ``anonymization.enabled``
    flag and tier gating both permit. ``False`` is the per-request
    escape hatch — operators send it when they need the raw text on
    the upstream call (e.g. running an evaluation that compares
    original vs. rehydrated)."""

    lq_ai_privileged: bool = False
    """M2-B3: the chat lives inside an attorney-client privileged
    Project (``projects.privileged = true`` in the backend). The
    anonymization middleware skips entirely for privileged chats —
    pseudonym rewriting of a privileged communication risks corrupting
    the work product that privilege protects, so the conservative
    posture is "don't touch it." Backend resolves the flag from the
    project row and forwards it; the gateway never queries the
    backend for it."""

    # --- C2 (skill prompt assembly per ADR 0007) -----------------------------
    lq_ai_skills: list[str] = Field(default_factory=list, max_length=16)
    """Ordered list of skill names to attach to this request. The gateway
    fetches each from the backend's internal-skills endpoint, assembles
    the bodies (with reference files and input substitution applied),
    and prepends the result to the request's system message. Capped at
    16 entries (Wave D.2 Task 3.0 I1) to bound the
    workload-multiplication DoS surface — each catalogue entry triggers
    a backend round-trip plus an assembled-body system-prompt
    contribution."""

    lq_ai_skill_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Per-skill input bindings, keyed by skill name. Inner dict maps
    input variable names to values. Per-skill scoping means two attached
    skills with overlapping variable names don't collide."""

    lq_ai_inline_skills: list[InlineSkillRef] = Field(default_factory=list, max_length=16)
    """Wave D.2 Task 3.0 — inline-body skills the gateway assembles
    without a backend round-trip. Each entry carries a synthesized
    ``name``, a verbatim ``body``, optional ``inputs``, optional
    ``minimum_inference_tier``, and optional ``source`` (provenance
    tag). Capped at 16 entries (I1) to bound the
    workload-multiplication DoS surface — each entry can ship up to
    64 KB of verbatim body content that lands in the system prompt.

    The assembler builds a :class:`app.clients.backend.Skill` instance
    from each entry directly (no HTTP) and appends it to the same
    ordered list that :attr:`lq_ai_skills` resolves into, so tier-floor
    resolution and ``lq_ai_applied_skills`` reporting work uniformly
    across both code paths. Order: catalogue (``lq_ai_skills``) first,
    then inline (``lq_ai_inline_skills``) — both preserve their
    input order within the group.

    Empty list (default) preserves pre-D.2 wire shape exactly.

    .. note::

       OpenAPI sync deferred to Wave 9.1.
    """

    # --- C3 (chat / message identity for routing-log correlation) ------------
    lq_ai_chat_id: str | None = None
    """UUID for ``inference_routing_log.chat_id``. The backend generates
    this from the persisted ``chats`` row. Distinct from the pre-existing
    ``chat_id`` field (B3-era audit-log tag); ``lq_ai_chat_id`` takes
    precedence when both are present and is the canonical surface after
    C3."""

    lq_ai_message_id: str | None = None
    """UUID for ``inference_routing_log.message_id``. The backend
    generates a UUID for the assistant message *before* dispatch and
    forwards it; the gateway writes the same UUID into the routing log
    so the audit-log row joins to the persisted message row by ``id``."""

    lq_ai_user_id: str | None = None
    """UUID of the authenticated user (D8 / ADR 0012). When set, the
    gateway threads it through the ``/internal/skills/{slug}`` lookup
    so user-scope shadows resolve correctly. Omitted means
    "registry-only", which is the right behavior for non-user-bearing
    callers (smoke scripts, internal admin tooling, etc.)."""

    lq_ai_purpose: str | None = None
    """M2-E2: tag for the routing-log ``purpose`` column. Distinguishes
    judge calls (Citation Engine Stage 3/4) from regular chat
    completions so per-model cost calibration filters down to judge
    traffic. Known values used in code: ``'judge_paraphrase'``;
    ``None`` or any unknown value falls back to ``'chat'`` in the
    persisted row. Stripped from the outbound provider body."""


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

    Mirrors OpenAI's ``chat.completion`` object plus the LQ.AI extension
    metadata documented in :doc:`docs/api/gateway-openapi.yaml`. The
    extension fields are stamped by gateway middleware after the adapter
    returns, so adapters leave them ``None``.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    """Unix timestamp (seconds) at which the gateway received the response."""
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage = Field(default_factory=ChatCompletionUsage)

    # --- LQ.AI extensions ---------------------------------------------------
    routed_inference_tier: int | None = Field(default=None, ge=1, le=5)
    routed_provider: str | None = None
    cost_estimate: float | None = None
    anonymization_applied: bool | None = None
    lq_ai_applied_skills: list[str] | None = None
    """Skills that were assembled into this request's prompt (C2). Null
    when no skills were attached; populated on requests with at least
    one entry in ``lq_ai_skills``. The backend surfaces this on the
    audit log so operators can see which skills shaped a given response."""


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

    The gateway emits these as ``data: <json>\\n\\n`` SSE frames terminated
    by ``data: [DONE]\\n\\n``, matching OpenAI's streaming format.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChunkChoice]
    # OpenAI emits a final usage block on the last chunk when
    # ``stream_options.include_usage`` is set; we always include it when
    # the adapter has the data.
    usage: ChatCompletionUsage | None = None

    # --- LQ.AI extensions ---------------------------------------------------
    routed_inference_tier: int | None = Field(default=None, ge=1, le=5)
    routed_provider: str | None = None
    lq_ai_applied_skills: list[str] | None = None


# --- Embeddings ---------------------------------------------------------------


class EmbeddingsRequest(BaseModel):
    """OpenAI-compatible embeddings request body."""

    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    input: str | list[str]
    encoding_format: Literal["float", "base64"] | None = None
    dimensions: int | None = Field(default=None, ge=1)
    user: str | None = None


class EmbeddingObject(BaseModel):
    """One embedding entry in an embeddings response."""

    model_config = ConfigDict(extra="allow")

    object: Literal["embedding"] = "embedding"
    embedding: list[float]
    index: int


class EmbeddingsUsage(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt_tokens: int = 0
    total_tokens: int = 0


class EmbeddingsResponse(BaseModel):
    """OpenAI-compatible embeddings response body."""

    model_config = ConfigDict(extra="allow")

    object: Literal["list"] = "list"
    data: list[EmbeddingObject]
    model: str
    usage: EmbeddingsUsage = Field(default_factory=EmbeddingsUsage)
