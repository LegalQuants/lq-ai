"""Signed /lq help issues a private association URL. No inference or profile API."""

from __future__ import annotations

import asyncio
import re
from typing import Annotated
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from .config import Settings, get_settings
from .signing import verify_slack_signature

router = APIRouter()


@router.post("/slack/commands")
async def commands(
    request: Request, cfg: Annotated[Settings, Depends(get_settings)]
) -> dict[str, str]:
    # Bound input before signature verification or form parsing.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16384:
            raise HTTPException(413, "command too large")
    if not verify_slack_signature(
        signing_secret=cfg.slack_signing_secret,
        timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
        body=bytes(raw),
        signature=request.headers.get("X-Slack-Signature", ""),
    ):
        raise HTTPException(401, "invalid Slack signature")
    try:
        fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=40)
    except (UnicodeError, ValueError):
        raise HTTPException(400, "invalid command") from None
    if any(len(values) != 1 for values in fields.values()):
        raise HTTPException(400, "ambiguous command")
    team = fields.get("team_id", [""])[0]
    user = fields.get("user_id", [""])[0]
    if not re.fullmatch(r"T[A-Z0-9]{1,63}", team) or not re.fullmatch(r"[UW][A-Z0-9]{1,63}", user):
        raise HTTPException(400, "invalid Slack identity")
    reply = {
        "response_type": "ephemeral",
        "text": "Use /lq help to link your Slack account. /lq ask is not available yet.",
    }
    if fields.get("command") != ["/lq"]:
        raise HTTPException(400, "unknown command")
    if fields.get("text", [""])[0].strip() not in {"", "help"}:
        return reply
    if not cfg.lq_ai_slack_command_token:
        reply["text"] = "Slack account linking is not configured. Contact your LQ.AI administrator."
        return reply
    try:
        async with asyncio.timeout(2.0), httpx.AsyncClient(timeout=2.0) as client:
            res = await client.post(
                f"{cfg.lq_ai_backend_url}/api/v1/integrations/slack/link-requests",
                headers={"Authorization": f"Bearer {cfg.lq_ai_slack_command_token}"},
                json={"team_id": team, "slack_user_id": user},
            )
        if res.status_code != 201:
            raise ValueError("link refused")
        url = res.json()["url"]
        if (
            not isinstance(url, str)
            or not url.startswith(("https://", "http://localhost:", "http://127.0.0.1:"))
            or any(char in url for char in "<>|\r\n")
        ):
            raise ValueError("invalid link")
    except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
        reply["text"] = (
            "Unable to create an account link. Check the workspace installation and try /lq help again."
        )
        return reply
    reply["text"] = (
        f"<{url}|Link your Slack account to LQ.AI>. Sign in and confirm only if you requested this link. "
        "It expires in 10 minutes. Creating a new link replaces your previous link. /lq ask is not available yet."
    )
    return reply
