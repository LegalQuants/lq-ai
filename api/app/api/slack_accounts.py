"""Backend-owned Slack identity linking. All mutations serialize on the install.

Only the verified Slack bridge may issue challenges. A normal active LQ.AI
session previews and explicitly confirms them. GETs never associate an account.
Tokens are random, ten-minute, single-use capabilities stored only as SHA-256.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.config import Settings, get_settings
from app.db.session import get_db
from app.errors import Conflict, InternalError, NotFound, Unauthorized, ValidationError
from app.models.slack_account import SlackAccountLink, SlackLinkRequest
from app.models.slack_workspace import SlackWorkspace
from app.schemas.slack_account import (
    SlackAccountResponse,
    SlackLinkPreview,
    SlackLinkStart,
    SlackLinkStarted,
    SlackLinkToken,
)


class SlackAccountRoute(APIRoute):
    """Do not echo capabilities or supplied credentials in validation errors."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def sanitized(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                raise ValidationError(message="Invalid Slack account linking request.") from None

        return sanitized


router = APIRouter(
    prefix="/integrations/slack", tags=["slack-accounts"], route_class=SlackAccountRoute
)
DB = Annotated[AsyncSession, Depends(get_db)]


def require_slack_command_auth(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.lq_ai_slack_command_token
    if not expected:
        raise InternalError(message="Slack account linking is not configured.")
    supplied = (
        authorization[len("Bearer ") :]
        if authorization and authorization.startswith("Bearer ")
        else ""
    )
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise Unauthorized(message="Invalid Slack command credential.")


def _unavailable() -> NotFound:
    return NotFound(message="This Slack link is invalid or expired. Run /lq help for a new link.")


async def _workspace(db: AsyncSession, workspace_id: uuid.UUID) -> SlackWorkspace:
    workspace = await db.scalar(
        select(SlackWorkspace).where(SlackWorkspace.id == workspace_id).with_for_update()
    )
    if workspace is None or workspace.deleted_at is not None:
        raise _unavailable()
    return workspace


async def _challenge(db: AsyncSession, token: str) -> tuple[SlackLinkRequest, SlackWorkspace]:
    digest = hashlib.sha256(token.encode()).hexdigest()
    # First discover the install, then lock it before rereading the request.
    # Disconnect, unlink, issuance and confirmation use this same lock order.
    workspace_id = await db.scalar(
        select(SlackLinkRequest.workspace_id).where(SlackLinkRequest.token_hash == digest)
    )
    if workspace_id is None:
        raise _unavailable()
    workspace = await _workspace(db, workspace_id)
    challenge = await db.scalar(
        select(SlackLinkRequest)
        .where(SlackLinkRequest.token_hash == digest)
        .execution_options(populate_existing=True)
    )
    if challenge is None or challenge.expires_at <= datetime.now(UTC):
        raise _unavailable()
    return challenge, workspace


def _response(link: SlackAccountLink, workspace: SlackWorkspace) -> SlackAccountResponse:
    return SlackAccountResponse(
        id=link.id,
        team_id=workspace.team_id,
        team_name=workspace.team_name,
        slack_user_id=link.slack_user_id,
        created_at=link.created_at,
    )


@router.post(
    "/link-requests",
    response_model=SlackLinkStarted,
    status_code=201,
    dependencies=[Depends(require_slack_command_auth)],
)
async def start_link(
    response: Response,
    body: SlackLinkStart,
    request: Request,
    db: DB,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SlackLinkStarted:
    response.headers["Cache-Control"] = "no-store"
    base = settings.lq_ai_web_public_url.rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"})
    ):
        raise InternalError(message="A secure LQ.AI web public URL must be configured.")
    workspace = await db.scalar(
        select(SlackWorkspace).where(SlackWorkspace.team_id == body.team_id).with_for_update()
    )
    if workspace is None or workspace.deleted_at is not None:
        raise _unavailable()
    await db.execute(
        delete(SlackLinkRequest).where(
            SlackLinkRequest.workspace_id == workspace.id,
            SlackLinkRequest.slack_user_id == body.slack_user_id,
        )
    )
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    db.add(
        SlackLinkRequest(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            workspace_id=workspace.id,
            slack_user_id=body.slack_user_id,
            expires_at=expires_at,
        )
    )
    await audit_action(
        db,
        user_id=None,
        action="slack.link_request.create",
        resource_type="slack_workspace",
        resource_id=str(workspace.id),
        request=request,
    )
    await db.commit()
    return SlackLinkStarted(url=f"{base}/lq-ai/slack/link#token={token}", expires_at=expires_at)


@router.post("/link-requests/preview", response_model=SlackLinkPreview)
async def preview_link(
    body: SlackLinkToken, _user: ActiveUser, db: DB, response: Response
) -> SlackLinkPreview:
    response.headers["Cache-Control"] = "no-store"
    challenge, workspace = await _challenge(db, body.token)
    return SlackLinkPreview(
        team_id=workspace.team_id,
        team_name=workspace.team_name,
        slack_user_id=challenge.slack_user_id,
        expires_at=challenge.expires_at,
    )


@router.post("/link-requests/confirm", response_model=SlackAccountResponse)
async def confirm_link(
    body: SlackLinkToken, user: ActiveUser, db: DB, request: Request
) -> SlackAccountResponse:
    challenge, workspace = await _challenge(db, body.token)
    existing = await db.scalar(
        select(SlackAccountLink).where(
            SlackAccountLink.workspace_id == workspace.id,
            SlackAccountLink.slack_user_id == challenge.slack_user_id,
        )
    )
    if existing is not None:
        raise Conflict(
            message="This Slack account is already linked. Unlink it before linking again."
        )
    link = SlackAccountLink(
        workspace_id=workspace.id, slack_user_id=challenge.slack_user_id, user_id=user.id
    )
    db.add(link)
    await db.delete(challenge)
    await audit_action(
        db,
        user_id=user.id,
        action="slack.account.link",
        resource_type="slack_workspace",
        resource_id=str(workspace.id),
        request=request,
        details={"slack_user_id": link.slack_user_id},
    )
    await db.flush()
    result = _response(link, workspace)
    await db.commit()
    return result


@router.get("/account-links", response_model=list[SlackAccountResponse])
async def list_links(user: ActiveUser, db: DB) -> list[SlackAccountResponse]:
    rows = await db.execute(
        select(SlackAccountLink, SlackWorkspace)
        .join(SlackWorkspace, SlackWorkspace.id == SlackAccountLink.workspace_id)
        .where(SlackAccountLink.user_id == user.id, SlackWorkspace.deleted_at.is_(None))
        .order_by(SlackAccountLink.created_at, SlackAccountLink.id)
    )
    return [_response(link, workspace) for link, workspace in rows]


@router.delete("/account-links/{link_id}", status_code=204, response_class=Response)
async def unlink(link_id: uuid.UUID, user: ActiveUser, db: DB, request: Request) -> Response:
    workspace_id = await db.scalar(
        select(SlackAccountLink.workspace_id).where(
            SlackAccountLink.id == link_id,
            SlackAccountLink.user_id == user.id,
        )
    )
    if workspace_id is None:
        raise NotFound(message="Slack account link not found.")
    await _workspace(db, workspace_id)
    link = await db.scalar(
        select(SlackAccountLink).where(
            SlackAccountLink.id == link_id,
            SlackAccountLink.user_id == user.id,
        )
    )
    if link is None:
        raise NotFound(message="Slack account link not found.")
    await db.execute(
        delete(SlackLinkRequest).where(
            SlackLinkRequest.workspace_id == workspace_id,
            SlackLinkRequest.slack_user_id == link.slack_user_id,
        )
    )
    await db.delete(link)
    await audit_action(
        db,
        user_id=user.id,
        action="slack.account.unlink",
        resource_type="slack_workspace",
        resource_id=str(workspace_id),
        request=request,
        details={"slack_user_id": link.slack_user_id},
    )
    await db.commit()
    return Response(status_code=204)
