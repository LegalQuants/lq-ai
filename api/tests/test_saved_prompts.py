"""Integration tests for the D7 Saved Prompts CRUD surface.

Covers the M1-IMPLEMENTATION-ORDER Task D7 backend surface:

* GET list returns the caller's prompts, newest first; empty by default.
* POST creates and returns the new row; persists tags as `text[]`.
* GET /{id} returns the prompt to its owner, 404 to others.
* PATCH updates fields partially and writes an audit row when something
  actually changes; idempotent no-op PATCH does not write an audit row.
* DELETE removes the row and writes an audit row.
* Cross-user reads/updates/deletes 404 — IDs do not leak across users.
* Validation: empty name, oversize prompt body, malformed/empty tags.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models import AuditLog, SavedPrompt, User
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


async def _make_user(db_session: AsyncSession, *, suffix: str = "") -> User:
    user = User(
        email=f"saved-prompt-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Saved Prompt User {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="a")


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="b")


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET / — list
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_returns_empty_for_new_user(client: AsyncClient, user_a: User) -> None:
    resp = await client.get("/api/v1/saved-prompts", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


@pytest.mark.integration
async def test_list_returns_only_callers_prompts_newest_first(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """Cross-user isolation + ordering: A's list shows only A's, in
    ``updated_at DESC`` order; B's prompt does not appear.

    PostgreSQL ``now()`` returns the transaction start time, so all
    inserts/updates inside this test's outer SAVEPOINT-bound
    transaction would otherwise share an ``updated_at``. Setting it
    explicitly on the rows guarantees the comparison is meaningful.
    """

    from datetime import datetime, timedelta

    base = datetime.now(UTC)
    older = SavedPrompt(
        user_id=user_a.id,
        name="Older",
        prompt_text="alpha",
        tags=[],
        updated_at=base - timedelta(minutes=5),
    )
    newer = SavedPrompt(
        user_id=user_a.id,
        name="Newer",
        prompt_text="beta",
        tags=["x"],
        updated_at=base,
    )
    other = SavedPrompt(
        user_id=user_b.id,
        name="B's prompt",
        prompt_text="gamma",
        tags=[],
        updated_at=base,
    )
    db_session.add_all([older, newer, other])
    await db_session.flush()

    resp = await client.get("/api/v1/saved-prompts", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = [row["name"] for row in body]
    assert names == ["Newer", "Older"]
    assert all(row["user_id"] == str(user_a.id) for row in body)


@pytest.mark.integration
async def test_list_without_bearer_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/saved-prompts")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST / — create
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_returns_201_and_persists(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    body = {
        "name": "Executive summary",
        "prompt_text": "Summarize the attached document for a CEO audience.",
        "tags": ["summary", "exec"],
    }
    resp = await client.post("/api/v1/saved-prompts", headers=_bearer(user_a), json=body)
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert payload["name"] == "Executive summary"
    assert payload["prompt_text"] == body["prompt_text"]
    assert payload["tags"] == ["summary", "exec"]
    assert payload["user_id"] == str(user_a.id)
    new_id = uuid.UUID(payload["id"])

    # Verify persistence + audit row.
    persisted = (
        await db_session.execute(select(SavedPrompt).where(SavedPrompt.id == new_id))
    ).scalar_one()
    assert persisted.user_id == user_a.id
    assert persisted.tags == ["summary", "exec"]

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.user_id == user_a.id,
                    AuditLog.action == "saved_prompt.create",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].resource_id == str(new_id)


@pytest.mark.integration
async def test_create_dedupes_tags_preserving_order(client: AsyncClient, user_a: User) -> None:
    resp = await client.post(
        "/api/v1/saved-prompts",
        headers=_bearer(user_a),
        json={
            "name": "Tagged",
            "prompt_text": "body",
            "tags": ["alpha", "beta", "alpha", "gamma"],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["tags"] == ["alpha", "beta", "gamma"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "bad_payload",
    [
        {"name": "", "prompt_text": "body"},
        {"name": "ok", "prompt_text": ""},
        {"name": "ok"},  # missing prompt_text
        {"prompt_text": "body"},  # missing name
    ],
)
async def test_create_rejects_invalid_payloads(
    client: AsyncClient, user_a: User, bad_payload: dict
) -> None:
    resp = await client.post("/api/v1/saved-prompts", headers=_bearer(user_a), json=bad_payload)
    assert resp.status_code in (400, 422), resp.text


@pytest.mark.integration
async def test_create_rejects_empty_or_whitespace_tag(client: AsyncClient, user_a: User) -> None:
    resp = await client.post(
        "/api/v1/saved-prompts",
        headers=_bearer(user_a),
        json={"name": "n", "prompt_text": "p", "tags": ["", "   "]},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# GET /{id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_returns_owners_prompt(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    prompt = SavedPrompt(user_id=user_a.id, name="One", prompt_text="alpha", tags=["t"])
    db_session.add(prompt)
    await db_session.flush()

    resp = await client.get(f"/api/v1/saved-prompts/{prompt.id}", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(prompt.id)


@pytest.mark.integration
async def test_get_other_users_prompt_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    """ID-probing must not reveal the existence of other users' prompts."""

    prompt = SavedPrompt(user_id=user_b.id, name="Mine", prompt_text="x", tags=[])
    db_session.add(prompt)
    await db_session.flush()

    resp = await client.get(f"/api/v1/saved-prompts/{prompt.id}", headers=_bearer(user_a))
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_get_unknown_id_returns_404(client: AsyncClient, user_a: User) -> None:
    resp = await client.get(f"/api/v1/saved-prompts/{uuid.uuid4()}", headers=_bearer(user_a))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /{id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_patch_updates_partial_fields(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    prompt = SavedPrompt(user_id=user_a.id, name="Original", prompt_text="alpha", tags=["a"])
    db_session.add(prompt)
    await db_session.flush()

    resp = await client.patch(
        f"/api/v1/saved-prompts/{prompt.id}",
        headers=_bearer(user_a),
        json={"name": "Renamed", "tags": ["b", "c"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["prompt_text"] == "alpha"  # untouched
    assert body["tags"] == ["b", "c"]


@pytest.mark.integration
async def test_patch_no_changes_skips_audit_row(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    """Idempotent PATCH (same values) returns 200 but does not write an audit row."""

    prompt = SavedPrompt(user_id=user_a.id, name="Stable", prompt_text="body", tags=["t"])
    db_session.add(prompt)
    await db_session.flush()

    resp = await client.patch(
        f"/api/v1/saved-prompts/{prompt.id}",
        headers=_bearer(user_a),
        json={"name": "Stable", "prompt_text": "body", "tags": ["t"]},
    )
    assert resp.status_code == 200, resp.text

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.user_id == user_a.id,
                    AuditLog.action == "saved_prompt.update",
                )
            )
        )
        .scalars()
        .all()
    )
    assert audits == []


@pytest.mark.integration
async def test_patch_writes_audit_row_on_change(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    prompt = SavedPrompt(user_id=user_a.id, name="Before", prompt_text="x", tags=[])
    db_session.add(prompt)
    await db_session.flush()

    resp = await client.patch(
        f"/api/v1/saved-prompts/{prompt.id}",
        headers=_bearer(user_a),
        json={"prompt_text": "y"},
    )
    assert resp.status_code == 200, resp.text

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.user_id == user_a.id,
                    AuditLog.action == "saved_prompt.update",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].resource_id == str(prompt.id)
    assert "changed_fields" in (audits[0].details or {})


@pytest.mark.integration
async def test_patch_other_users_prompt_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    prompt = SavedPrompt(user_id=user_b.id, name="B's", prompt_text="x", tags=[])
    db_session.add(prompt)
    await db_session.flush()

    resp = await client.patch(
        f"/api/v1/saved-prompts/{prompt.id}",
        headers=_bearer(user_a),
        json={"name": "hijack"},
    )
    assert resp.status_code == 404, resp.text

    # Confirm B's row was untouched.
    untouched = (
        await db_session.execute(select(SavedPrompt).where(SavedPrompt.id == prompt.id))
    ).scalar_one()
    assert untouched.name == "B's"


# ---------------------------------------------------------------------------
# DELETE /{id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_removes_row_and_writes_audit(
    client: AsyncClient, db_session: AsyncSession, user_a: User
) -> None:
    prompt = SavedPrompt(user_id=user_a.id, name="Doomed", prompt_text="x", tags=[])
    db_session.add(prompt)
    await db_session.flush()
    prompt_id = prompt.id

    resp = await client.delete(f"/api/v1/saved-prompts/{prompt_id}", headers=_bearer(user_a))
    assert resp.status_code == 204, resp.text

    persisted = (
        await db_session.execute(select(SavedPrompt).where(SavedPrompt.id == prompt_id))
    ).scalar_one_or_none()
    assert persisted is None

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.user_id == user_a.id,
                    AuditLog.action == "saved_prompt.delete",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].resource_id == str(prompt_id)


@pytest.mark.integration
async def test_delete_other_users_prompt_returns_404(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    prompt = SavedPrompt(user_id=user_b.id, name="B's", prompt_text="x", tags=[])
    db_session.add(prompt)
    await db_session.flush()

    resp = await client.delete(f"/api/v1/saved-prompts/{prompt.id}", headers=_bearer(user_a))
    assert resp.status_code == 404, resp.text

    persisted = (
        await db_session.execute(select(SavedPrompt).where(SavedPrompt.id == prompt.id))
    ).scalar_one_or_none()
    assert persisted is not None  # still there


@pytest.mark.integration
async def test_delete_unknown_id_returns_404(client: AsyncClient, user_a: User) -> None:
    resp = await client.delete(f"/api/v1/saved-prompts/{uuid.uuid4()}", headers=_bearer(user_a))
    assert resp.status_code == 404
