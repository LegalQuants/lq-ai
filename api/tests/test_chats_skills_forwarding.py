"""Tests that POST /chats/{id}/messages forwards C2 skill fields (api/ side).

Covers the api/ side of the skill plumbing:

* ``MessageCreate.skills`` and ``MessageCreate.skill_inputs`` flow
  through to the gateway as ``lq_ai_skills`` / ``lq_ai_skill_inputs``.
* The gateway's ``lq_ai_applied_skills`` response field surfaces in the
  api response body's ``applied_skills`` list.
* The streaming ``complete`` SSE frame includes ``applied_skills``.
* Skill-fetch failures (skill_not_found, skill_fetch_failed,
  skill_input_missing) translate to the right backend HTTP statuses.

All tests respx-mock the gateway; no real gateway involved.
"""

from __future__ import annotations

import json as _json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.chat import Chat
from app.models.file import File
from app.models.user import User
from app.security import create_access_token, hash_password

_DUMMY_CHAT_ID = "00000000-0000-4000-8000-000000000000"
GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


@pytest_asyncio.fixture
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"skills-fwd-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Skills Forwarding Test",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture(autouse=True)
async def db_chat(db_session: AsyncSession, db_user: User) -> Chat:
    """Seed a chat at the well-known DUMMY id owned by db_user.

    Autouse so every test in this file gets the chat without restating the
    fixture in 8 signatures. POST /chats/{id}/messages calls
    _load_visible_chat which 404s when the row doesn't exist or isn't owned
    by the caller; these tests exercise the message-forwarding path, not
    chat creation, so we pre-seed rather than POSTing through /chats first.
    """
    chat = Chat(
        id=uuid.UUID(_DUMMY_CHAT_ID),
        owner_id=db_user.id,
        title="New chat",
    )
    db_session.add(chat)
    await db_session.flush()
    return chat


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override
    gw = GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)
    set_gateway_client(gw)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)
    await gw.aclose()
    set_gateway_client(None)


def _bearer_for(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


async def _make_file(
    db_session: AsyncSession,
    owner: User,
    *,
    deleted: bool = False,
) -> File:
    """Insert a minimal ``files`` row owned by ``owner``."""
    import datetime as _dt

    f = File(
        owner_id=owner.id,
        filename="contract.pdf",
        mime_type="application/pdf",
        size_bytes=1234,
        hash_sha256="0" * 64,
        storage_path=str(uuid.uuid4()),
        ingestion_status="ready",
        deleted_at=(_dt.datetime.now(tz=_dt.UTC) if deleted else None),
    )
    db_session.add(f)
    await db_session.flush()
    return f


def _success_payload(
    *,
    applied_skills: list[str] | None = None,
    content: str = "ok",
) -> dict[str, object]:
    body: dict[str, object] = {
        "id": "chatcmpl-c2",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "claude-sonnet-4-6",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        "routed_inference_tier": 3,
        "routed_provider": "anthropic-prod",
    }
    if applied_skills is not None:
        body["lq_ai_applied_skills"] = applied_skills
    return body


# --- Forwarding -------------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_forwards_skills_to_gateway(client: AsyncClient, db_user: User) -> None:
    """`skills` in MessageCreate becomes `lq_ai_skills` to the gateway."""

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(applied_skills=["nda-review"]))
    )
    token = _bearer_for(db_user)
    await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={
            "content": "review this NDA",
            "model": "smart",
            "skills": ["nda-review"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert route.called
    sent = _json.loads(route.calls[0].request.read())
    assert sent["lq_ai_skills"] == ["nda-review"]


@pytest.mark.integration
@respx.mock
async def test_forwards_skill_inputs_to_gateway(client: AsyncClient, db_user: User) -> None:
    """`skill_inputs` in MessageCreate becomes `lq_ai_skill_inputs`."""

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload(applied_skills=["nda-review"]))
    )
    token = _bearer_for(db_user)
    await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={
            "content": "review this NDA",
            "model": "smart",
            "skills": ["nda-review"],
            "skill_inputs": {"nda-review": {"document": "<NDA text>", "perspective": "discloser"}},
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    sent = _json.loads(route.calls[0].request.read())
    assert sent["lq_ai_skill_inputs"] == {
        "nda-review": {"document": "<NDA text>", "perspective": "discloser"}
    }


@pytest.mark.integration
@respx.mock
async def test_no_skills_means_empty_extension_fields(client: AsyncClient, db_user: User) -> None:
    """A request without `skills` sends empty `lq_ai_skills` to the gateway."""

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)
    await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={"content": "hi", "model": "smart"},
        headers={"Authorization": f"Bearer {token}"},
    )

    sent = _json.loads(route.calls[0].request.read())
    # The Pydantic model defaults to an empty list / dict. The gateway
    # client serializes with exclude_none=True, so empties may be
    # dropped — accept either "absent" or "empty".
    assert sent.get("lq_ai_skills", []) == []
    assert sent.get("lq_ai_skill_inputs", {}) == {}


# --- applied_skills surfacing -----------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_applied_skills_surfaces_in_response(client: AsyncClient, db_user: User) -> None:
    """The gateway's `lq_ai_applied_skills` lands in the response body's
    `applied_skills`."""

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json=_success_payload(applied_skills=["nda-review", "us-overlay"])
        )
    )
    token = _bearer_for(db_user)
    response = await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={
            "content": "hi",
            "model": "smart",
            "skills": ["nda-review", "us-overlay"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied_skills"] == ["nda-review", "us-overlay"]


@pytest.mark.integration
@respx.mock
async def test_no_applied_skills_means_empty_list(client: AsyncClient, db_user: User) -> None:
    """When the gateway doesn't surface applied_skills, the response shows []."""

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)
    response = await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={"content": "hi", "model": "smart"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied_skills"] == []


# --- Error pass-through ------------------------------------------------------


@pytest.mark.integration
@respx.mock
async def test_skill_not_found_propagates_to_404(client: AsyncClient, db_user: User) -> None:
    """Gateway's `skill_not_found` (404) passes through as 404 to the API caller."""

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "skill_not_found",
                    "message": "Skill 'nope' is not in the registry",
                    "details": {"skill_name": "nope"},
                }
            },
        )
    )
    token = _bearer_for(db_user)
    response = await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={
            "content": "hi",
            "model": "smart",
            "skills": ["nope"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["code"] == "skill_not_found"


@pytest.mark.integration
@respx.mock
async def test_skill_fetch_failed_propagates_to_502(client: AsyncClient, db_user: User) -> None:
    """Gateway's `skill_fetch_failed` (502) passes through as 502."""

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            502,
            json={
                "error": {
                    "code": "skill_fetch_failed",
                    "message": "Backend returned HTTP 503 fetching skill 'alpha'",
                    "details": {"skill_name": "alpha", "status_code": 503},
                }
            },
        )
    )
    token = _bearer_for(db_user)
    response = await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={"content": "hi", "model": "smart", "skills": ["alpha"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["detail"]["code"] == "skill_fetch_failed"


@pytest.mark.integration
@respx.mock
async def test_skill_input_missing_propagates_to_400(client: AsyncClient, db_user: User) -> None:
    """Gateway's `skill_input_missing` (400) passes through as 400."""

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "code": "skill_input_missing",
                    "message": "Required skill inputs are missing: alpha.document",
                    "details": {
                        "missing": ["alpha.document"],
                        "missing_by_skill": {"alpha": ["document"]},
                    },
                }
            },
        )
    )
    token = _bearer_for(db_user)
    response = await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={"content": "hi", "model": "smart", "skills": ["alpha"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == "skill_input_missing"
    assert "alpha.document" in body["detail"]["details"]["missing"]


# --- file_ids: per-message document context (Donna) -------------------------


def _stream_chunk(content: str) -> str:
    chunk = {
        "id": "chatcmpl-stream",
        "object": "chat.completion.chunk",
        "created": 1_700_000_000,
        "model": "claude-sonnet-4-6",
        "choices": [
            {"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}
        ],
        "routed_inference_tier": 3,
        "routed_provider": "anthropic-prod",
    }
    return f"data: {_json.dumps(chunk)}\n\n"


@pytest.mark.integration
@respx.mock
async def test_file_ids_forwarded_and_echoed_non_streaming(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """Caller-owned file_ids forward as lq_ai_file_ids and echo back."""

    f = await _make_file(db_session, db_user)
    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)
    response = await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={"content": "summarize this", "model": "smart", "file_ids": [str(f.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    sent = _json.loads(route.calls[0].request.read())
    assert sent["lq_ai_file_ids"] == [str(f.id)]
    body = response.json()
    assert body["applied_file_ids"] == [str(f.id)]


@pytest.mark.integration
@respx.mock
async def test_file_ids_foreign_owner_404(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """A file owned by another user 404s without leaking existence; no gateway call."""

    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Other",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(other)
    await db_session.flush()
    foreign = await _make_file(db_session, other)

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)
    response = await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={"content": "summarize this", "model": "smart", "file_ids": [str(foreign.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    # The gateway is never reached when validation fails.
    assert not route.called
    # The 404 detail carries only the id the caller already sent — no
    # owner / existence signal that distinguishes "not yours" from
    # "doesn't exist".
    body = response.json()
    assert body["detail"]["details"]["file_id"] == str(foreign.id)


@pytest.mark.integration
@respx.mock
async def test_file_ids_nonexistent_404(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """An unknown UUID 404s identically to a foreign file (id-probing-safe)."""

    ghost = str(uuid.uuid4())
    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)
    response = await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={"content": "hi", "model": "smart", "file_ids": [ghost]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert not route.called


@pytest.mark.integration
@respx.mock
async def test_file_ids_soft_deleted_404(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """A soft-deleted file owned by the caller still 404s."""

    f = await _make_file(db_session, db_user, deleted=True)
    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)
    response = await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={"content": "hi", "model": "smart", "file_ids": [str(f.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert not route.called


@pytest.mark.integration
@respx.mock
async def test_no_file_ids_means_empty_extension_field(client: AsyncClient, db_user: User) -> None:
    """Omitted file_ids is back-compatible: empty/absent lq_ai_file_ids, empty echo."""

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    token = _bearer_for(db_user)
    response = await client.post(
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={"content": "hi", "model": "smart"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    sent = _json.loads(route.calls[0].request.read())
    # exclude_none/exclude_default serialization may drop the empty list.
    assert sent.get("lq_ai_file_ids", []) == []
    assert response.json()["applied_file_ids"] == []


@pytest.mark.integration
@respx.mock
async def test_file_ids_echoed_on_streaming_complete_frame(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """The streaming `complete` SSE frame echoes applied_file_ids."""

    f = await _make_file(db_session, db_user)
    body = _stream_chunk("done") + "data: [DONE]\n\n"
    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )
    )
    token = _bearer_for(db_user)

    events: list[dict[str, object]] = []
    async with client.stream(
        "POST",
        f"/api/v1/chats/{_DUMMY_CHAT_ID}/messages",
        json={"content": "summarize", "stream": True, "file_ids": [str(f.id)]},
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line or line == "data: [DONE]":
                if line == "data: [DONE]":
                    break
                continue
            events.append(_json.loads(line[len("data:") :].strip()))

    complete = [e for e in events if e["type"] == "complete"]
    assert len(complete) == 1
    assert complete[0]["applied_file_ids"] == [str(f.id)]
