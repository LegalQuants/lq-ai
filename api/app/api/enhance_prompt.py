"""Enhance Prompt endpoint — PRD §3.2 (Wave A).

POST /api/v1/enhance-prompt invokes the ``enhance-prompt`` skill
against the gateway (using a fast/budget alias by default) and returns
the structured expansion — expansion_applied + expanded_prompt +
reasoning + skip_reason + preview_to_user — so the frontend can show
the "review before sending" UI.

The skill itself lives at ``skills/enhance-prompt/SKILL.md``; this
endpoint is the thin orchestration layer the spec commits to:

* Loads the chat context (optional ``chat_id`` → last few message
  turns) so the skill can decide whether to skip when the prompt is a
  follow-up.
* Builds the structured input payload the skill expects
  (raw_input, attached_skills, attached_files, chat_history,
  jurisdiction).
* Posts to the gateway with ``lq_ai_skills=['enhance-prompt']`` so the
  skill body becomes the system prompt and the Organization Profile
  (if any) is prepended per ADR 0007.
* Parses the model's structured output (YAML or JSON block) using a
  tolerant parser — falls back to "skip with parse_error" rather than
  500ing the request.
* Persists an :class:`EnhancePromptInteraction` row for telemetry +
  the post-hoc ``used`` / ``edited_before_use`` updates.

The follow-up endpoint ``PATCH /api/v1/enhance-prompt/{id}`` updates
``used`` and ``edited_before_use`` once the user decides what to do
with the preview.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.clients.gateway import GatewayClient, get_gateway_client
from app.db.session import get_db
from app.errors import LQAIError
from app.models.chat import Chat, Message
from app.models.enhance_prompt import EnhancePromptInteraction
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

log = logging.getLogger(__name__)

router = APIRouter(prefix="/enhance-prompt", tags=["enhance-prompt"])

# Default alias the skill is invoked against. ``fast`` is the right
# default: enhance-prompt is a thin reasoning task and the spec
# explicitly says "typically a smaller/cheaper model" (PRD §3.2). The
# operator can override per-request via ``model`` on the request body.
DEFAULT_MODEL_ALIAS = "fast"

# How many recent message turns to fold into ``chat_history`` when the
# caller supplies a ``chat_id``. The spec says "typically last 4-8";
# 8 is the upper bound that keeps the context useful without making
# the enhancement call expensive.
CHAT_HISTORY_TURNS = 8

# Cap on the raw input length. The chat-completion path enforces its
# own message-size limits server-side; enhance-prompt's raw_input is
# meant to be a *short* prompt the user is about to expand. 4 KB is
# generous (a typical short prompt is <500 chars) and shields against
# pathological pastes.
_RAW_INPUT_MAX = 4096


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class EnhancePromptAttachedSkill(BaseModel):
    """Minimal shape the application supplies for an attached skill.

    The skill itself reads ``name`` and ``description`` — that's enough
    for it to decide whether the expansion should defer to the
    attached skill or complement it.
    """

    name: str
    description: str | None = None


class EnhancePromptAttachedFile(BaseModel):
    """Minimal shape for an attached file."""

    file_id: uuid.UUID | None = None
    filename: str
    mime_type: str | None = None
    description: str | None = None


class EnhancePromptRequest(BaseModel):
    """POST body for ``/api/v1/enhance-prompt``."""

    raw_input: str = Field(min_length=1, max_length=_RAW_INPUT_MAX)
    """The user's original prompt as typed."""

    chat_id: uuid.UUID | None = None
    """When supplied, the endpoint loads the chat's recent message
    history (last ``CHAT_HISTORY_TURNS`` turns) so the skill can decide
    whether to skip the expansion as a follow-up. Optional; omit for
    the standalone "draft a fresh prompt" surface."""

    attached_skills: list[EnhancePromptAttachedSkill] = Field(default_factory=list)
    """Skills the user has attached to the current chat. The skill
    uses this to ensure the expansion does not duplicate or conflict
    with skill instructions."""

    attached_files: list[EnhancePromptAttachedFile] = Field(default_factory=list)
    """Files the user has attached to the current chat. Informs the
    expansion when a document is in scope."""

    jurisdiction: str | None = Field(default=None, max_length=200)
    """User's preferred jurisdiction. The skill folds this into the
    expansion when the prompt would otherwise be jurisdictionally
    ambiguous."""

    model: str | None = Field(default=None, max_length=200)
    """Optional model alias override. Defaults to ``fast`` per the
    spec's "smaller/cheaper model" guidance."""


class EnhancePromptResponse(BaseModel):
    """Response body for ``/api/v1/enhance-prompt``.

    Mirrors the SKILL.md output schema plus the persisted
    ``interaction_id`` the frontend uses to PATCH ``used`` /
    ``edited_before_use`` after the user acts on the preview.
    """

    interaction_id: uuid.UUID
    expansion_applied: bool
    expanded_prompt: str
    reasoning: list[str] = Field(default_factory=list)
    skip_reason: str | None = None
    preview_to_user: str = ""
    routed_inference_tier: int | None = None
    routed_provider: str | None = None
    routed_model: str | None = None


class EnhancePromptOutcomeUpdate(BaseModel):
    """PATCH body for ``/api/v1/enhance-prompt/{id}``.

    The frontend sends this after the user acts on the preview:
    Submit → ``used=true``; Submit-after-edit → ``used=true`` +
    ``edited_before_use=true``; Skip → ``used=false`` (default —
    nothing to PATCH unless the caller wants to explicitly reset).
    """

    used: bool | None = None
    edited_before_use: bool | None = None


# ---------------------------------------------------------------------------
# Skill-output parsing
# ---------------------------------------------------------------------------


_CODE_FENCE_RE = re.compile(r"```(?:yaml|yml|json)?\s*\n(.*?)\n```", re.DOTALL)


def _parse_skill_output(
    raw_text: str,
) -> tuple[bool, str | None, list[str], str | None, str]:
    """Tolerantly parse the skill's structured output.

    Returns ``(expansion_applied, expanded_prompt, reasoning,
    skip_reason, preview_to_user)``. The skill's SKILL.md specifies a
    YAML object with these keys; in practice the model may emit:

    * A fenced ``yaml`` (or ``json``) block.
    * Bare YAML/JSON.
    * Prose wrapping a fenced block.

    The function tries fenced-block extraction first, then bare-YAML,
    and as a last resort returns a skip decision with
    ``skip_reason='parse_error'``. Never raises — a parse failure is
    a usable signal ("the model didn't produce structured output")
    rather than an HTTP 500.
    """

    candidate = raw_text
    match = _CODE_FENCE_RE.search(raw_text)
    if match is not None:
        candidate = match.group(1)

    parsed: Any | None = None
    try:
        parsed = yaml.safe_load(candidate)
    except yaml.YAMLError:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            parsed = None

    if not isinstance(parsed, dict):
        return (
            False,
            None,
            [],
            "parse_error",
            (
                "The enhancement model returned content the application could "
                "not parse as structured output. Submit the original prompt."
            ),
        )

    expansion_applied = bool(parsed.get("expansion_applied", False))
    expanded_prompt = parsed.get("expanded_prompt")
    skip_reason = parsed.get("skip_reason")
    preview = parsed.get("preview_to_user", "")
    reasoning_block = parsed.get("reasoning", [])

    if isinstance(reasoning_block, list):
        reasoning: list[str] = [str(item) for item in reasoning_block if item is not None]
    elif isinstance(reasoning_block, str):
        # Accept a single string as a one-bullet reasoning rather than
        # dropping it on the floor.
        reasoning = [reasoning_block]
    else:
        reasoning = []

    if expansion_applied and not isinstance(expanded_prompt, str):
        # The model claimed to expand but produced no string. Treat as
        # skip with parse_error so the application falls back cleanly.
        return (
            False,
            None,
            reasoning,
            "parse_error",
            "Enhancement returned malformed expansion; submit the original prompt.",
        )
    if not expansion_applied:
        expanded_prompt = None
        if not isinstance(skip_reason, str) or not skip_reason:
            skip_reason = "unspecified"

    return (
        expansion_applied,
        expanded_prompt if isinstance(expanded_prompt, str) else None,
        reasoning,
        skip_reason if isinstance(skip_reason, str) else None,
        str(preview) if preview is not None else "",
    )


def _format_skill_inputs(
    *,
    raw_input: str,
    attached_skills: list[EnhancePromptAttachedSkill],
    attached_files: list[EnhancePromptAttachedFile],
    chat_history: list[dict[str, str]],
    jurisdiction: str | None,
) -> str:
    """Render the inputs as a YAML user-message body.

    The skill expects the inputs as a structured block; YAML keeps the
    surface readable for the model and matches the format the skill's
    Output section uses for its own response.
    """

    payload: dict[str, Any] = {"raw_input": raw_input}
    if attached_skills:
        payload["attached_skills"] = [s.model_dump(exclude_none=True) for s in attached_skills]
    if attached_files:
        payload["attached_files"] = [
            f.model_dump(exclude_none=True, mode="json") for f in attached_files
        ]
    if chat_history:
        payload["chat_history"] = chat_history
    if jurisdiction:
        payload["jurisdiction"] = jurisdiction

    encoded = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return f"Inputs for Enhance Prompt:\n\n```yaml\n{encoded}```"


async def _load_chat_history(
    db: AsyncSession,
    *,
    chat_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int = CHAT_HISTORY_TURNS,
) -> list[dict[str, str]]:
    """Return the last ``limit`` message turns for ``chat_id`` (owner-only).

    Returns an empty list if the chat doesn't belong to the caller or
    doesn't exist — Enhance Prompt should still produce an expansion
    on a bare prompt; missing history is not an error. Mirrors the
    privacy posture in the chats endpoints.
    """

    chat = await db.get(Chat, chat_id)
    if chat is None or chat.owner_id != user_id:
        return []

    stmt = (
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    # Reverse to chronological order — the skill expects the order it
    # would see in the chat (oldest of the window first).
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=EnhancePromptResponse,
    summary="Expand a short prompt into a structured legal prompt (PRD §3.2)",
)
async def enhance_prompt(
    payload: EnhancePromptRequest,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> EnhancePromptResponse:
    """POST /api/v1/enhance-prompt — invoke the enhance-prompt skill.

    The skill is applied via the standard gateway prompt-assembly path
    (``lq_ai_skills=['enhance-prompt']``), so user/team-scope shadows
    of the skill are honored per the D8.1b resolver. Returns the
    structured expansion + an interaction_id the frontend uses to
    update ``used`` / ``edited_before_use`` post-hoc.
    """

    chat_history: list[dict[str, str]] = []
    if payload.chat_id is not None:
        chat_history = await _load_chat_history(db, chat_id=payload.chat_id, user_id=user.id)

    user_message_body = _format_skill_inputs(
        raw_input=payload.raw_input,
        attached_skills=payload.attached_skills,
        attached_files=payload.attached_files,
        chat_history=chat_history,
        jurisdiction=payload.jurisdiction,
    )

    model_alias = payload.model or DEFAULT_MODEL_ALIAS
    gw_request = ChatCompletionRequest(
        model=model_alias,
        messages=[ChatCompletionMessage(role="user", content=user_message_body)],
        stream=False,
        lq_ai_user_id=str(user.id),
        lq_ai_skills=["enhance-prompt"],
        # ADR 0007 §2: the gateway enforces the skill's declared required
        # inputs, and ``raw_input`` is the one this skill declares. Bind it
        # so the declaration stays true and enforcement is satisfied. The
        # YAML user turn above remains the skill's working input; the
        # gateway renders this binding into its data envelope (which
        # channel carries it is DE-388).
        lq_ai_skill_inputs={"enhance-prompt": {"raw_input": payload.raw_input}},
    )

    try:
        gw_response = await gateway.chat_completion(
            gw_request, request_id=request.headers.get("x-request-id")
        )
    except LQAIError as exc:
        # Surface gateway / provider failures as the same typed error the
        # chat endpoint uses; the frontend already handles those codes.
        log.warning(
            "enhance-prompt gateway call failed",
            extra={"event": "enhance_prompt_gateway_error", "error_code": exc.code},
        )
        raise

    raw_choice = gw_response.choices[0].message.content if gw_response.choices else ""
    raw_text = raw_choice if isinstance(raw_choice, str) else ""

    (
        expansion_applied,
        expanded_prompt,
        reasoning,
        skip_reason,
        preview_to_user,
    ) = _parse_skill_output(raw_text)

    # Persist BEFORE returning so the interaction_id we hand back is
    # durable. The same single-transaction-commit pattern the audit
    # writes use elsewhere.
    interaction = EnhancePromptInteraction(
        user_id=user.id,
        chat_id=payload.chat_id,
        raw_input=payload.raw_input,
        expansion_applied=expansion_applied,
        expanded_output=expanded_prompt,
        reasoning=reasoning,
        skip_reason=skip_reason,
        routed_inference_tier=gw_response.routed_inference_tier,
        routed_provider=gw_response.routed_provider,
        routed_model=gw_response.model,
        prompt_tokens=gw_response.usage.prompt_tokens,
        completion_tokens=gw_response.usage.completion_tokens,
    )
    db.add(interaction)
    await db.commit()
    await db.refresh(interaction)

    log.info(
        "enhance-prompt invocation",
        extra={
            "event": "enhance_prompt_invocation",
            "user_id": str(user.id),
            "chat_id": str(payload.chat_id) if payload.chat_id else None,
            "interaction_id": str(interaction.id),
            "expansion_applied": expansion_applied,
            "skip_reason": skip_reason,
            "model": model_alias,
            "routed_tier": gw_response.routed_inference_tier,
        },
    )

    return EnhancePromptResponse(
        interaction_id=interaction.id,
        expansion_applied=expansion_applied,
        expanded_prompt=expanded_prompt or payload.raw_input,
        reasoning=reasoning,
        skip_reason=skip_reason,
        preview_to_user=preview_to_user,
        routed_inference_tier=gw_response.routed_inference_tier,
        routed_provider=gw_response.routed_provider,
        routed_model=gw_response.model,
    )


@router.patch(
    "/{interaction_id}",
    response_model=EnhancePromptResponse,
    summary="Record what the user did with the enhancement preview (PRD §3.2)",
)
async def update_enhance_prompt_outcome(
    interaction_id: uuid.UUID,
    payload: EnhancePromptOutcomeUpdate,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnhancePromptResponse:
    """PATCH /api/v1/enhance-prompt/{id} — update used/edited flags.

    The frontend calls this after the user acts on the preview:
    * Submit as-is → ``used=true``.
    * Edit then submit → ``used=true``, ``edited_before_use=true``.
    * Skip / dismiss → no PATCH needed (defaults stand).

    Owner-only (404 if the row exists but belongs to another user —
    same id-probing posture as the user_skills + chats endpoints).
    Idempotent: re-applying the same flags returns 200 without
    writing to the DB.
    """

    row = await db.get(EnhancePromptInteraction, interaction_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="enhance-prompt interaction not found",
        )

    changed = False
    if payload.used is not None and payload.used != row.used:
        row.used = payload.used
        changed = True
    if payload.edited_before_use is not None and (
        payload.edited_before_use != row.edited_before_use
    ):
        row.edited_before_use = payload.edited_before_use
        changed = True

    if changed:
        await db.commit()
        await db.refresh(row)

    return EnhancePromptResponse(
        interaction_id=row.id,
        expansion_applied=row.expansion_applied,
        expanded_prompt=row.expanded_output or row.raw_input,
        reasoning=list(row.reasoning or []),
        skip_reason=row.skip_reason,
        preview_to_user="",
        routed_inference_tier=row.routed_inference_tier,
        routed_provider=row.routed_provider,
        routed_model=row.routed_model,
    )


__all__ = ["router"]
