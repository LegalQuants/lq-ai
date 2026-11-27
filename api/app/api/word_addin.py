"""Word add-in plumbing surface (M3-B1, M3-B2, M3-B8) + document-chat (M3-B3).

Surfaces (current):

* ``GET /api/v1/admin/word-addin/manifest`` — admin-only; returns a
  rendered Office Add-in manifest XML with the operator's deployment URL
  + a freshly generated GUID substituted into the template (M3-B1).
* ``GET /api/v1/word-addin/version`` — **unauthenticated**; returns the
  deployment's version + the compatible add-in version range + the
  task-pane bundle URL. The task pane consults this on mount before
  the user even sees the sign-in screen, so an out-of-date add-in
  surfaces an "Update needed" overlay without the operator getting
  stuck at a broken OAuth handshake (M3-B8).
* ``POST /api/v1/word-addin/document-chat`` — authenticated; one-shot,
  document-grounded chat turn for the task pane's Chat tab (M3-B3). See
  that section below for why this is a dedicated, stateless endpoint
  rather than an extension of ``POST /chats/{chat_id}/messages``.

OAuth (M3-B2) reuses ``/api/v1/auth/login`` + ``/auth/refresh`` from the
existing auth surface — no Word-add-in-specific endpoint required.

Template loading: the manifest template lives at ``api/app/data/word_addin_
manifest.xml``. The source-of-truth lives in the sibling ``word-addin/
manifest.xml`` directory; a sync test in :mod:`api.tests.test_word_addin
_endpoints` asserts the two files match byte-for-byte so any change to
the add-in's manifest flows into the api package.

Per [PRD §9 DE-287](docs/PRD.md), the user-facing feature tabs inside
the add-in are descoped to M4 / community contribution; M3 shipped the
install-authenticate-version-check plumbing only. ``document-chat``
below is the first feature-surface piece to land ahead of that.

--- document-chat (M3-B3) -----------------------------------------------

Deliberately stateless: no ``db`` dependency on the handler below, no
``chat_id``/``message_id``, nothing written to ``chats``/``messages``.
Reasoning (settled after the DE-287 text itself was found to be silent
on this): on the web app, the persisted chat *is* the state — a
resumable, cross-session conversation. In the add-in, the open Word
document is the state; every turn re-derives its context by
re-enumerating the document's paragraphs fresh (never cached — see
``word-addin/src/services/documentChatClient.ts``). Persisting a
parallel transcript in Postgres would just be a second, driftable copy
of a conversation whose real ground truth is a document that can be
edited between turns. ``inference_routing_log`` still gets a row per
call (gateway-written, metadata only — no content columns), same as
every other inference call; that's cost/audit accounting, not chat
history, and isn't something this endpoint can or should opt out of.

``DocumentChatCreate.user_instruction`` is a client-built JSON string
(see ``documentChatClient.ts``'s ``toDocumentChatInstruction``) carrying
the document's paragraphs, the user's actual question, and input/output/
citation schema documentation together — this handler forwards it
verbatim as the user message content; it does not parse it. Structured
output (``DocumentChatResponse.content`` + ``.citations``) comes back via
a forced ``emit_answer`` tool call (``EMIT_ANSWER_TOOL``) — provider-
enforced schema conformance, not prompt-based JSON.
"""

from __future__ import annotations

import logging
import re
import uuid as _uuid_mod
from importlib import resources
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app import __version__ as _api_version
from app.api.dependencies import ActiveUser, AdminUser
from app.clients.gateway import GatewayClient, get_gateway_client
from app.errors import LQAIError
from app.schemas.gateway import (
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
)

log = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/admin/word-addin", tags=["admin"])
"""Admin-only routes (manifest generation). Mounted under the standard
``AdminUser`` gate in :mod:`app.api.__init__`."""

public_router = APIRouter(prefix="/word-addin", tags=["word-addin"])
"""Unauthenticated routes (version handshake). The task pane consults
the version endpoint before the user has signed in, so the gate must
not require an auth token. Mounted without the ``ActiveUser`` dependency
in :mod:`app.api.__init__` (same pattern as ``bootstrap.router``)."""

authenticated_router = APIRouter(prefix="/word-addin", tags=["word-addin"])
"""Authenticated routes (document-chat). Same URL prefix as
``public_router`` but mounted separately under the standard ``_active``
(bearer token + must_change_password=false) dependency group in
:mod:`app.api.__init__`, same split pattern as ``admin_router`` vs.
``public_router``."""

# Back-compat alias for callers that imported ``router`` directly before
# M3-B8 introduced the split. New code should reference ``admin_router``
# or ``public_router`` explicitly so the auth posture is clear at the
# import site.
router = admin_router


# Default values for manifest tokens. Operators can override per-request
# via query params; the defaults match the project's open-source identity.
DEFAULT_DISPLAY_NAME = "LQ.AI"
DEFAULT_PROVIDER_NAME = "LegalQuants"

# Token names in the manifest XML. Tokens render as ``{{ TOKEN_NAME }}``
# with single spaces; the regex below tolerates extra whitespace inside
# the braces but treats the token name as case-sensitive.
_TOKEN_PATTERN = re.compile(r"\{\{\s*(?P<name>[A-Z_]+)\s*\}\}")


def _load_manifest_template() -> str:
    """Load the bundled Office Add-in manifest template.

    Lives at ``api/app/data/word_addin_manifest.xml``; bundled into the
    api image at COPY time via the Dockerfile. The function is module-
    level (rather than a constant computed at import) so tests can patch
    the resource path if they need to exercise a different template.
    """
    return (
        resources.files("app.data").joinpath("word_addin_manifest.xml").read_text(encoding="utf-8")
    )


def render_manifest(
    *,
    deployment_origin: str,
    display_name: str = DEFAULT_DISPLAY_NAME,
    provider_name: str = DEFAULT_PROVIDER_NAME,
    addin_id: str | None = None,
) -> str:
    """Render the manifest template with the operator's deployment values.

    Pure function: separated from the FastAPI handler so unit tests can
    exercise every token-substitution path without spinning up the app.

    Args:
        deployment_origin: The operator's deployment URL with no trailing
            slash (e.g. ``https://lq.acme.example``). Validation happens
            upstream in the request handler.
        display_name: Branded name surfaced inside Word's ribbon and the
            task pane GetStarted message. Defaults to ``LQ.AI``.
        provider_name: ``ProviderName`` value the manifest surfaces to
            Microsoft 365 Admin Center. Defaults to ``LegalQuants``.
        addin_id: Lowercase hyphenated GUID; freshly generated per
            invocation when omitted so each install is uniquely
            addressable in the M365 catalog.

    Returns:
        Rendered manifest XML.

    Raises:
        ValueError: when the template contains a token that has no
            substitution value supplied by this function (catches
            template drift early).
    """
    if addin_id is None:
        addin_id = str(_uuid_mod.uuid4())

    substitutions = {
        "ADDIN_ID": addin_id,
        "DEPLOYMENT_ORIGIN": deployment_origin.rstrip("/"),
        "DEPLOYMENT_DISPLAY_NAME": display_name,
        "PROVIDER_NAME": provider_name,
    }

    template = _load_manifest_template()

    def _substitute(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in substitutions:
            raise ValueError(
                f"manifest template references unknown token {name!r}; "
                f"known tokens: {sorted(substitutions)}"
            )
        return substitutions[name]

    return _TOKEN_PATTERN.sub(_substitute, template)


def _resolve_deployment_origin(
    request: Request,
    override: str | None,
) -> str:
    """Derive the deployment origin for the rendered manifest.

    Preference order:
        1. Explicit ``deployment_origin`` query param when provided —
           lets an operator generate a manifest for a different
           deployment from the one serving the admin UI (rare but
           valid when a single ops team manages many deployments).
        2. The ``X-Forwarded-Proto`` + ``Host`` headers — these are
           what the reverse proxy reports, and match what the operator's
           users see in their browser address bar.
        3. The request URL's scheme + netloc as a final fallback for
           single-process dev setups.
    """
    if override is not None:
        return override.rstrip("/")

    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        return f"{scheme}://{host}".rstrip("/")

    return str(request.base_url).rstrip("/")


@admin_router.get(
    "/manifest",
    response_class=Response,
    summary="Render the Word add-in manifest XML for sideload (M3-B1).",
    responses={
        200: {
            "description": "Rendered Office Add-in XML manifest.",
            "content": {"application/xml": {}},
        },
        403: {"description": "Caller is not an admin user."},
    },
)
async def get_manifest(
    request: Request,
    _admin: AdminUser,
    deployment_origin: Annotated[
        str | None,
        Query(
            description=(
                "Override the deployment origin embedded in the manifest. "
                "Defaults to the request's effective origin (reverse-proxy "
                "aware). No trailing slash."
            ),
            examples=["https://lq.acme.example"],
        ),
    ] = None,
    display_name: Annotated[
        str,
        Query(
            description=(
                "Branded name surfaced inside Word's ribbon and the task pane GetStarted message."
            ),
            max_length=64,
        ),
    ] = DEFAULT_DISPLAY_NAME,
    provider_name: Annotated[
        str,
        Query(
            description=(
                "ProviderName value the manifest surfaces to Microsoft 365 "
                "Admin Center; typically the operator org's name."
            ),
            max_length=64,
        ),
    ] = DEFAULT_PROVIDER_NAME,
) -> Response:
    """Render and return the Office Add-in manifest XML for sideload.

    The endpoint is admin-only (``AdminUser`` dep at router level via
    ``api_router``). Returns ``application/xml`` with a
    ``Content-Disposition: attachment`` header so the browser downloads
    the file rather than rendering it as XML in the tab.
    """
    origin = _resolve_deployment_origin(request, deployment_origin)
    rendered = render_manifest(
        deployment_origin=origin,
        display_name=display_name,
        provider_name=provider_name,
    )

    return Response(
        content=rendered,
        media_type="application/xml",
        status_code=status.HTTP_200_OK,
        headers={
            "Content-Disposition": ('attachment; filename="lq-ai-word-addin-manifest.xml"'),
            "Cache-Control": "no-store",
        },
    )


# ---------------------------------------------------------------------------
# M3-B8 — Version handshake. The task pane calls this on mount BEFORE the
# user signs in, so the endpoint is unauthenticated and mounted on the
# ``public_router`` (no ``ActiveUser`` gate).
# ---------------------------------------------------------------------------


# The earliest add-in version that this deployment can talk to. Bump when a
# breaking change (e.g., a new required request field, an API rename) lands
# in the task-pane bundle; bumping forces operators to redistribute the
# manifest before the deployment will accept the older add-in.
ADDIN_MIN_COMPATIBLE_VERSION = "0.3.0"

# Upper bound on add-in versions this deployment recognizes. The default
# accepts every 0.3.x patch so operators don't have to bump the deployment
# for cosmetic add-in fixes; raise to ``0.4.99`` when M4 features ship.
ADDIN_MAX_COMPATIBLE_VERSION = "0.3.99"


class WordAddinVersionResponse(BaseModel):
    """Wire shape for the version handshake (M3-B8)."""

    deployment_version: str = Field(
        description=(
            "LQ.AI deployment version (api package ``__version__``). "
            "Informational — the add-in doesn't use this for "
            "compatibility decisions; it surfaces the value in the "
            "'Update needed' overlay so the user can quote it to "
            "support."
        )
    )
    addin_min_compatible_version: str = Field(
        description=(
            "Lowest add-in version (semver string) this deployment "
            "accepts. The task pane refuses to render features when "
            "its bundled version is lower."
        )
    )
    addin_max_compatible_version: str = Field(
        description=(
            "Highest add-in version this deployment recognizes. Task "
            "pane bundles newer than this should still load (forward "
            "compatibility is best-effort) but the add-in surfaces a "
            "soft warning so the operator knows to update the "
            "deployment."
        )
    )
    taskpane_bundle_url: str = Field(
        description=(
            "Canonical URL of the task-pane bundle's HTML entry point. "
            "The task pane reaches this from its `window.location` "
            "today; the value exists in the handshake so a future "
            "deployment can serve the bundle from a CDN or operator-"
            "chosen path without changing the manifest."
        )
    )
    taskpane_bundle_hash: str | None = Field(
        default=None,
        description=(
            "Optional SHA-256 hash of the deployed task-pane bundle "
            "JS. When present, the add-in can verify it loaded the "
            "bundle the deployment expects (catches Office's "
            "occasional stale-cache behavior). M3-B8 ships with this "
            "field nullable; M3-B7 / signing CI populates the value "
            "from the build manifest. Null means 'don't enforce' — "
            "not an error condition."
        ),
    )


@public_router.get(
    "/version",
    response_model=WordAddinVersionResponse,
    summary="Version handshake for the Word add-in task pane (M3-B8).",
    description=(
        "Unauthenticated endpoint the task pane consults on mount. "
        "Returns the deployment's version + the add-in version range "
        "this deployment is compatible with. The task pane compares "
        "its bundled version (baked in by webpack at build time) to "
        "the range; out-of-range bundles surface an 'Update needed' "
        "overlay rather than getting stuck against a breaking-change "
        "API call."
    ),
)
async def get_version(request: Request) -> WordAddinVersionResponse:
    origin = _resolve_deployment_origin(request, override=None)
    return WordAddinVersionResponse(
        deployment_version=_api_version,
        addin_min_compatible_version=ADDIN_MIN_COMPATIBLE_VERSION,
        addin_max_compatible_version=ADDIN_MAX_COMPATIBLE_VERSION,
        taskpane_bundle_url=f"{origin}/word-addin/taskpane.html",
        taskpane_bundle_hash=None,
    )


# ---------------------------------------------------------------------------
# M3-B3 — Document-chat. One-shot, document-grounded chat turn for the task
# pane's Chat tab. See the module docstring's "document-chat" section for
# why this is a dedicated, stateless endpoint rather than an extension of
# ``POST /chats/{chat_id}/messages``.
# ---------------------------------------------------------------------------

# Bound on the whole request body. The document, the model's input/output
# schema documentation, and the user's question all now travel together as
# one opaque JSON string (`user_instruction`) built client-side — see
# `word-addin/src/services/documentChatClient.ts`'s `toDocumentChatInstruction`.
# That means there's no longer a separate, Pydantic-enforced cap on paragraph
# *count* (the old `paragraphs: list[...] = Field(max_length=...)` — the
# invariant moved from two dimensions (count + char length) to one (char
# length only), a deliberate tradeoff since the char cap still bounds worst-
# case payload size. Sized generously above the old 120_000-char document-only
# cap to cover the JSON wrapper/schema boilerplate plus the extra per-
# paragraph overhead of `{"paragraphId":N,"text":"..."}` vs. the old flat
# `[P<id>] text` line format.
MAX_USER_INSTRUCTION_CHARS = 300_000

DOCUMENT_CHAT_SYSTEM_PROMPT = (
    "You are assisting a user with a Microsoft Word document that is "
    "currently open in their editor. The user's message below is a JSON "
    "object with four top-level keys: `input_schema` (the shape of this "
    "object's own `input` field), `citations_schema` (an explanation of "
    "how to cite specific paragraphs), `output_schema` (the shape you must "
    "return), and `input` (the actual document paragraphs plus the user's "
    "instruction). Read `input.paragraphs` as the document's content — each "
    "entry has a `paragraphId` and `text` — and `input.instruction` as the "
    "user's actual question. You MUST respond by calling the `emit_answer` "
    "function; never reply in plain text."
)


class DocumentChatCreate(BaseModel):
    """POST body for ``/api/v1/word-addin/document-chat``. Accepted on
    the wire as ``userInstruction`` (the frontend's own camelCase
    choice). ``user_instruction`` is a client-built JSON string (see
    ``documentChatClient.ts``'s ``toDocumentChatInstruction``) carrying
    the document paragraphs, the user's question, and input/output/
    citation schema documentation together — this handler passes it
    through verbatim as the user message content; it does not parse it
    server-side."""

    model_config = ConfigDict(populate_by_name=True)

    user_instruction: str = Field(
        min_length=1, max_length=MAX_USER_INSTRUCTION_CHARS, alias="userInstruction"
    )
    skills: list[str] | None = Field(default=None, max_length=16)
    model: str | None = Field(default=None, max_length=200)
    stream: bool = False
    """Accepted for forward-compatibility with the frontend's
    ``DocumentChatCreate`` shape; always treated as ``False`` here.
    This endpoint doesn't support streaming yet — see the module
    docstring."""


class DocumentChatCitation(BaseModel):
    """Points an answer back at a specific paragraph of the request's
    snapshot — resolved client-side via ``docxHelper.paragraph.search()``
    against the live Word document, not verified server-side (there's
    no persisted copy of an open Word document to verify against, unlike
    the KB Citation Engine's ``documents.normalized_content``). Serialized
    on the wire as ``paragraphId`` — FastAPI's ``response_model_by_alias``
    defaults to ``True``, so this alias applies on the way out the same
    way ``DocumentChatParagraph``'s applies on the way in."""

    model_config = ConfigDict(populate_by_name=True)

    paragraph_id: int = Field(alias="paragraphId")
    quote: str


class DocumentChatResponse(BaseModel):
    """Non-streaming response for ``POST /word-addin/document-chat``."""

    content: str
    citations: list[DocumentChatCitation] = Field(default_factory=list)


# Forced tool-calling gets the structured {content, citations} response
# via provider-enforced schema conformance (grammar-constrained decoding
# under `strict` mode) rather than asking the model nicely to reply in
# JSON — see the PR discussion for why this beats prompt-based JSON
# framing (skill-instruction collisions, no guarantee of valid JSON).
# This is the actual enforcement mechanism — the client also sends an
# `output_schema` inside `user_instruction`'s JSON (see documentChatClient.ts's
# `OUTPUT_SCHEMA`) as reinforcing documentation in the prompt, not a second
# enforcement path. Keep the two in sync by hand: `parameters` below must
# mirror `OUTPUT_SCHEMA` (same fields, same `paragraph_id` snake_case) —
# no shared source of truth between the two languages/files.
EMIT_ANSWER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "emit_answer",
        "description": (
            "Emit the answer to the user's question, with citations pointing "
            "back to the paragraph(s) (by [P<id>] index) the answer is "
            "grounded in. Always call this instead of replying in plain text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "response": {
                    "type": "string",
                    "description": (
                        "The answer to the user's question, in Markdown. When your "
                        "answer relies on a specific quote from the document, wrap "
                        "the relevant phrase from your own response in a Markdown "
                        "link to `citation:<n>`, where <n> is that citation's "
                        '0-based index in the citations array — e.g. "...allows '
                        "[30 days' written notice](citation:0)...\". The link text "
                        "is the only visible signal of what's being cited (no "
                        "separate preview), so wrap a natural, meaningful phrase, "
                        "not a bare number or symbol — the sentence should read the "
                        "same with the link markup stripped out."
                    ),
                },
                "citations": {
                    "type": "array",
                    "description": (
                        "Verbatim quotes from the document supporting the "
                        "answer. Empty if the answer isn't grounded in any "
                        "specific paragraph."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "paragraph_id": {
                                "type": "integer",
                                "description": "The [P<id>] index this citation is grounded in.",
                            },
                            "quote": {
                                "type": "string",
                                "description": (
                                    "Verbatim text from that paragraph — must be an "
                                    "exact substring, not a paraphrase, so the client "
                                    "can locate and highlight it in the live document."
                                ),
                            },
                        },
                        "required": ["paragraph_id", "quote"],
                    },
                },
            },
            "required": ["response", "citations"],
        },
    },
}

EMIT_ANSWER_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": "emit_answer"},
}


class _EmitAnswerCitation(BaseModel):
    paragraph_id: int = Field(ge=0)
    quote: str


class _EmitAnswerArgs(BaseModel):
    """Shape of ``emit_answer``'s tool-call arguments — validated after
    ``json.loads`` the same way ``app.autonomous.structured_output``
    tolerantly parses model JSON elsewhere in this codebase."""

    response: str
    citations: list[_EmitAnswerCitation] = Field(default_factory=list)


def _parse_document_chat_response(gw_response: ChatCompletionResponse) -> DocumentChatResponse:
    """Read ``emit_answer``'s forced tool-call arguments off the gateway
    response. Tolerant by design, never raises: a model that didn't call
    the tool (shouldn't happen with forced ``tool_choice``, but providers
    are not code) or emitted malformed arguments falls back to whatever
    plain-text content came back, with no citations — an honest
    "unstructured" result rather than a 500."""

    choice = gw_response.choices[0] if gw_response.choices else None
    tool_calls = choice.message.tool_calls if choice else None

    if not tool_calls:
        content = choice.message.content if choice and choice.message.content else ""
        return DocumentChatResponse(content=content, citations=[])

    raw_args = tool_calls[0].get("function", {}).get("arguments", "")
    try:
        parsed = _EmitAnswerArgs.model_validate_json(raw_args)
    except (ValueError, TypeError):
        log.warning(
            "document-chat: emit_answer arguments failed to parse; falling back to raw content",
            extra={"event": "document_chat_tool_parse_failed"},
        )
        return DocumentChatResponse(content=raw_args, citations=[])

    return DocumentChatResponse(
        content=parsed.response,
        citations=[
            # populate_by_name=True genuinely allows constructing by the
            # Python field name at runtime (verified) — the pydantic mypy
            # plugin just doesn't model that, hence the ignore.
            DocumentChatCitation(paragraph_id=c.paragraph_id, quote=c.quote)  # type: ignore[call-arg]
            for c in parsed.citations
        ],
    )


@authenticated_router.post(
    "/document-chat",
    response_model=DocumentChatResponse,
    summary="One-shot, document-grounded chat turn for the Word add-in's Chat tab (M3-B3).",
    description=(
        "Takes the user's question plus a snapshot of the open document's "
        "paragraphs, and returns a single model answer grounded in that "
        "snapshot, via a forced emit_answer tool call for structured "
        "citations. No persistence — every call is independent and "
        "nothing is written to chats/messages, unlike POST /chats/"
        "{chat_id}/messages. Non-streaming."
    ),
)
async def document_chat(
    body: DocumentChatCreate,
    request: Request,
    user: ActiveUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> DocumentChatResponse:
    gw_request = ChatCompletionRequest(
        model=body.model or "smart",
        messages=[
            # No lq_ai_skip_anonymization here: the whole user_instruction
            # JSON (document paragraphs included, now embedded inside it —
            # see documentChatClient.ts's toDocumentChatInstruction) goes
            # through anonymization like any other message. Whatever the
            # model quotes back gets rehydrated to the original text
            # automatically before this handler ever sees the response
            # (gateway's post_anonymize_response, unconditional whenever
            # pre_anonymize_request actually pseudonymized something) —
            # see the PR discussion for why this preserves citation
            # fidelity without needing the skip flag.
            ChatCompletionMessage(role="system", content=DOCUMENT_CHAT_SYSTEM_PROMPT),
            ChatCompletionMessage(role="user", content=body.user_instruction),
        ],
        stream=False,
        tools=[EMIT_ANSWER_TOOL],
        tool_choice=EMIT_ANSWER_TOOL_CHOICE,
        lq_ai_skills=body.skills or [],
        lq_ai_user_id=str(user.id),
    )

    try:
        gw_response = await gateway.chat_completion(
            gw_request, request_id=request.headers.get("x-request-id")
        )
    except LQAIError as exc:
        log.warning(
            "document-chat gateway call failed",
            extra={
                "event": "document_chat_gateway_error",
                "user_id": str(user.id),
                "error_code": exc.code,
            },
        )
        raise

    return _parse_document_chat_response(gw_response)
