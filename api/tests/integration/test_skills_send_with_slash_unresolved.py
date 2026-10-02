"""Wave D.2 / Task 2.7 — integration: send-time slash fallback.

Scenario: the chat composer ships a user message that *starts with*
``/<token>`` but the token doesn't resolve to any user-scope shadow or
built-in skill. The send-message handler must:

* set ``slash_unresolved=True`` on the JSON response so the frontend can
  surface a UI hint ("we tried to resolve ``/foo`` and couldn't"),
* leave ``attached_skill_names`` empty (no skill was attached),
* pass the original content through to the gateway as plain text (so the
  user still gets an answer; nothing is hidden from the model).

The resolved-slash path is exercised in the unit-style test alongside
the helper; this integration test pins the wire contract for the
unresolved branch — the one a real user is most likely to hit when they
typo a skill name.

Fixture pattern mirrors ``test_user_skills_versions_endpoint.py`` —
there is no shared ``authed_client`` fixture in this repo, so we wire
our own ``client`` + ``_h(user)`` Bearer-token helper, plus a respx
gateway mock so the handler's downstream call succeeds.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password
from app.skills import load_registry
from app.skills.registry import MutableSkillRegistry

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "skills"

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with the fixture skill registry + gateway stub."""

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    registry_present = FIXTURES_DIR.exists()
    prior_holder = getattr(app.state, "skill_registry", None)
    if registry_present:
        app.state.skill_registry = MutableSkillRegistry(load_registry(FIXTURES_DIR))
    elif prior_holder is None:
        app.state.skill_registry = MutableSkillRegistry(load_registry(Path("/nonexistent")))

    gw = GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)
    set_gateway_client(gw)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    set_gateway_client(None)
    await gw.aclose()
    if prior_holder is None:
        if hasattr(app.state, "skill_registry"):
            delattr(app.state, "skill_registry")
    else:
        app.state.skill_registry = prior_holder
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"slash-fallback-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Slash Fallback Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _h(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


def _success_payload() -> dict[str, object]:
    """Minimal OpenAI-shape success body for the gateway mock."""

    return {
        "id": "chatcmpl-slash-fallback",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "claude-sonnet-4-6",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "fallback answer"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "routed_inference_tier": 3,
        "routed_provider": "anthropic-prod",
        "cost_estimate": 0.0001,
    }


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_send_with_leading_unresolved_slash_sends_as_plain_text(
    client: AsyncClient, db_user: User
) -> None:
    """``/nonexistent-skill ...`` → 200 + ``slash_unresolved=True``, no skill attached."""

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    assert chat_resp.status_code in (200, 201), chat_resp.text
    chat_id = chat_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "/nonexistent-skill review this"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("slash_unresolved") is True, body
    assert body.get("attached_skill_names", []) == [], body
