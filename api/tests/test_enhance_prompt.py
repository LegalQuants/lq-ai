"""Integration tests for the Enhance Prompt endpoint — Wave A (PRD §3.2).

The endpoint invokes the enhance-prompt skill via the gateway. We
mock the gateway client so the tests don't depend on a live provider
and so we can drive deterministic output shapes (well-formed YAML,
malformed YAML, JSON, bare prose) through the parser.

Covers:

* End-to-end happy path: gateway returns YAML expansion → endpoint
  persists row + returns structured response.
* Skip-decision path: gateway returns ``expansion_applied: false`` →
  row persists with skip_reason, no expanded_output.
* Parse-error fallback: gateway returns prose → endpoint surfaces
  skip with ``skip_reason='parse_error'`` rather than 500.
* JSON fallback: gateway returns a fenced JSON block → parser handles.
* Chat history loading: when ``chat_id`` is supplied, the endpoint
  threads the last N messages into the skill payload.
* Owner privacy: chat_id belonging to another user → history is silently
  empty (skill still runs).
* PATCH update: ``used`` / ``edited_before_use`` flags flip; 404 on
  cross-user PATCH.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, get_gateway_client
from app.db.session import get_db
from app.main import app
from app.models import EnhancePromptInteraction, User
from app.models.chat import Chat, Message
from app.schemas.gateway import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionResponse,
    ChatCompletionUsage,
)
from app.security import create_access_token, hash_password
from app.skills import load_registry
from app.skills.registry import MutableSkillRegistry

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "skills"


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


def _mock_gateway(model_text: str) -> AsyncMock:
    """Return a GatewayClient mock whose chat_completion yields ``model_text``."""

    mock = AsyncMock(spec=GatewayClient)
    mock.chat_completion.return_value = ChatCompletionResponse(
        id="cmpl_test",
        created=0,
        model="claude-sonnet-4-6",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=model_text),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=120, completion_tokens=80, total_tokens=200),
        routed_inference_tier=3,
        routed_provider="anthropic-prod",
    )
    return mock


@pytest_asyncio.fixture
async def caller(db_session: AsyncSession) -> User:
    user = User(
        email=f"enhance-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Enhance Test",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"enhance-other-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Enhance Other",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


def _client_with(*, db_session: AsyncSession, gateway_mock: AsyncMock) -> AsyncClient:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    app.dependency_overrides[get_gateway_client] = lambda: gateway_mock
    holder = MutableSkillRegistry(load_registry(FIXTURES_DIR))
    app.state.skill_registry = holder
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _cleanup() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_gateway_client, None)


# ---------------------------------------------------------------------------
# Happy path: YAML expansion
# ---------------------------------------------------------------------------


YAML_EXPANSION = """\
```yaml
expansion_applied: true
expanded_prompt: |
  You are in-house counsel. Review the attached NDA for unusual provisions.
  Identify the top 3-5 risks, with citations to specific sections.
reasoning:
  - Added in-house counsel role since the prompt was role-implicit.
  - Specified top 3-5 risks to bound the scope.
skip_reason: null
preview_to_user: |
  Expanded prompt:
    You are in-house counsel...
  Reasoning:
    - Added in-house counsel role...
```
"""


@pytest.mark.integration
async def test_enhance_prompt_happy_path_persists_and_returns_expansion(
    db_session: AsyncSession, caller: User
) -> None:
    gateway = _mock_gateway(YAML_EXPANSION)
    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.post(
                "/api/v1/enhance-prompt",
                headers=_bearer(caller),
                json={"raw_input": "review this NDA"},
            )
    finally:
        _cleanup()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["expansion_applied"] is True
    assert "in-house counsel" in body["expanded_prompt"]
    assert len(body["reasoning"]) == 2
    assert body["skip_reason"] is None
    assert body["routed_inference_tier"] == 3
    assert body["routed_provider"] == "anthropic-prod"
    assert body["interaction_id"]

    # Row persisted.
    row = await db_session.get(EnhancePromptInteraction, uuid.UUID(body["interaction_id"]))
    assert row is not None
    assert row.user_id == caller.id
    assert row.expansion_applied is True
    assert row.expanded_output is not None
    assert "in-house counsel" in row.expanded_output
    assert len(row.reasoning) == 2
    assert row.routed_provider == "anthropic-prod"
    assert row.prompt_tokens == 120


# ---------------------------------------------------------------------------
# Skip decision: model says skip, structured
# ---------------------------------------------------------------------------


YAML_SKIP = """\
```yaml
expansion_applied: false
expanded_prompt: ""
reasoning: []
skip_reason: "prompt is conversational"
preview_to_user: ""
```
"""


@pytest.mark.integration
async def test_enhance_prompt_skip_decision_persists_with_reason(
    db_session: AsyncSession, caller: User
) -> None:
    gateway = _mock_gateway(YAML_SKIP)
    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.post(
                "/api/v1/enhance-prompt",
                headers=_bearer(caller),
                json={"raw_input": "thanks"},
            )
    finally:
        _cleanup()

    assert resp.status_code == 200
    body = resp.json()
    assert body["expansion_applied"] is False
    assert body["skip_reason"] == "prompt is conversational"
    # Echo back the original so the frontend can keep its existing flow.
    assert body["expanded_prompt"] == "thanks"

    row = await db_session.get(EnhancePromptInteraction, uuid.UUID(body["interaction_id"]))
    assert row is not None
    assert row.expansion_applied is False
    assert row.expanded_output is None
    assert row.skip_reason == "prompt is conversational"


# ---------------------------------------------------------------------------
# Parse-error fallback: model returns bare prose
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_enhance_prompt_parse_error_returns_skip_not_500(
    db_session: AsyncSession, caller: User
) -> None:
    gateway = _mock_gateway("Sorry I cannot help with this request right now.")
    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.post(
                "/api/v1/enhance-prompt",
                headers=_bearer(caller),
                json={"raw_input": "review this NDA"},
            )
    finally:
        _cleanup()

    assert resp.status_code == 200
    body = resp.json()
    assert body["expansion_applied"] is False
    assert body["skip_reason"] == "parse_error"
    assert body["expanded_prompt"] == "review this NDA"


# ---------------------------------------------------------------------------
# JSON fenced output is also accepted
# ---------------------------------------------------------------------------


JSON_EXPANSION = """\
```json
{
  "expansion_applied": true,
  "expanded_prompt": "Adopt in-house counsel role and review for risk.",
  "reasoning": ["Added role"],
  "skip_reason": null,
  "preview_to_user": "Expanded prompt: ..."
}
```
"""


@pytest.mark.integration
async def test_enhance_prompt_json_fenced_output_parses(
    db_session: AsyncSession, caller: User
) -> None:
    gateway = _mock_gateway(JSON_EXPANSION)
    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.post(
                "/api/v1/enhance-prompt",
                headers=_bearer(caller),
                json={"raw_input": "review this NDA"},
            )
    finally:
        _cleanup()

    assert resp.status_code == 200
    body = resp.json()
    assert body["expansion_applied"] is True
    assert body["expanded_prompt"].startswith("Adopt in-house counsel role")
    assert body["reasoning"] == ["Added role"]


# ---------------------------------------------------------------------------
# Chat history is loaded when chat_id is supplied and owner matches
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_enhance_prompt_threads_chat_history_for_owner(
    db_session: AsyncSession, caller: User
) -> None:
    chat = Chat(owner_id=caller.id, title="Test chat")
    db_session.add(chat)
    await db_session.flush()
    for role, content in [
        ("user", "first message"),
        ("assistant", "first reply"),
        ("user", "second message"),
        ("assistant", "second reply"),
    ]:
        db_session.add(Message(chat_id=chat.id, role=role, content=content))
    await db_session.flush()

    gateway = _mock_gateway(YAML_SKIP)  # response value doesn't matter; we check the call args
    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.post(
                "/api/v1/enhance-prompt",
                headers=_bearer(caller),
                json={
                    "raw_input": "shorter please",
                    "chat_id": str(chat.id),
                },
            )
    finally:
        _cleanup()

    assert resp.status_code == 200
    # The gateway request's user message should include chat history.
    sent_request = gateway.chat_completion.call_args.args[0]
    user_content = sent_request.messages[0].content
    assert "chat_history" in user_content
    assert "first message" in user_content
    assert "second reply" in user_content


@pytest.mark.integration
async def test_enhance_prompt_ignores_chat_belonging_to_other_user(
    db_session: AsyncSession, caller: User, other_user: User
) -> None:
    """chat_id pointing at someone else's chat → history silently empty.

    The skill still runs; we just don't leak the other user's content.
    """

    other_chat = Chat(owner_id=other_user.id, title="Other's chat")
    db_session.add(other_chat)
    await db_session.flush()
    db_session.add(Message(chat_id=other_chat.id, role="user", content="secret content"))
    await db_session.flush()

    gateway = _mock_gateway(YAML_SKIP)
    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.post(
                "/api/v1/enhance-prompt",
                headers=_bearer(caller),
                json={"raw_input": "test", "chat_id": str(other_chat.id)},
            )
    finally:
        _cleanup()

    assert resp.status_code == 200
    sent_request = gateway.chat_completion.call_args.args[0]
    assert "secret content" not in sent_request.messages[0].content
    assert "chat_history" not in sent_request.messages[0].content


# ---------------------------------------------------------------------------
# PATCH outcome update
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_enhance_prompt_patch_used_flips(db_session: AsyncSession, caller: User) -> None:
    gateway = _mock_gateway(YAML_EXPANSION)
    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            created = await client.post(
                "/api/v1/enhance-prompt",
                headers=_bearer(caller),
                json={"raw_input": "review this NDA"},
            )
            iid = created.json()["interaction_id"]
            updated = await client.patch(
                f"/api/v1/enhance-prompt/{iid}",
                headers=_bearer(caller),
                json={"used": True, "edited_before_use": True},
            )
    finally:
        _cleanup()

    assert updated.status_code == 200

    row = await db_session.get(EnhancePromptInteraction, uuid.UUID(iid))
    assert row is not None
    assert row.used is True
    assert row.edited_before_use is True


@pytest.mark.integration
async def test_enhance_prompt_patch_cross_user_returns_404(
    db_session: AsyncSession, caller: User, other_user: User
) -> None:
    gateway = _mock_gateway(YAML_EXPANSION)
    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            created = await client.post(
                "/api/v1/enhance-prompt",
                headers=_bearer(caller),
                json={"raw_input": "review this NDA"},
            )
            iid = created.json()["interaction_id"]
            cross = await client.patch(
                f"/api/v1/enhance-prompt/{iid}",
                headers=_bearer(other_user),
                json={"used": True},
            )
    finally:
        _cleanup()

    assert cross.status_code == 404


# ---------------------------------------------------------------------------
# DB schema sanity (migration 0015)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_enhance_prompt_table_check_constraint_skip_requires_reason(
    db_session: AsyncSession, caller: User
) -> None:
    """``expansion_applied=false`` with NULL skip_reason violates the CHECK."""

    from sqlalchemy.exc import IntegrityError

    bad = EnhancePromptInteraction(
        user_id=caller.id,
        raw_input="x",
        expansion_applied=False,
        skip_reason=None,
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
