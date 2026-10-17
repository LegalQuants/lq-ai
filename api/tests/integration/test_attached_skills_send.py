"""Wave D.2 / Task 3.0 — integration: ``attached_skills`` on send-message.

Exercises the wire contract the wizard's "Try it" surface relies on:

* Legacy ``skills: list[str]`` continues to work unchanged.
* ``attached_skills`` with ``slug`` entries flows through the same
  catalogue-resolved path as the legacy field, forwarded to the gateway
  as ``lq_ai_skills``.
* ``attached_skills`` with ``inline_body`` entries flows to the gateway
  as ``lq_ai_inline_skills`` — the gateway then assembles the body
  without a catalogue fetch.
* Mixed slug + inline payloads work.
* Schema validation rejects malformed entries (neither slug nor
  inline_body; both at once; oversized inline body) with HTTP 422.
* The persisted user message + audit log carry the synthesized inline
  name AND per-attachment provenance (kind, source).

The gateway is mocked at the HTTP boundary — we capture the request
body sent over the wire so we can assert exactly what
``lq_ai_inline_skills`` shape the backend forwarded. The handler's
slash-fallback (Task 2.7) is intentionally not exercised here; that
contract is covered by ``test_skills_send_with_slash_unresolved.py``.
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import Message
from app.models.user import User
from app.schemas.chats import ATTACHED_SKILLS_MAX_LEN, INLINE_SKILL_BODY_MAX_BYTES
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
    prior_holder = getattr(app.state, "skill_registry", None)
    if FIXTURES_DIR.exists():
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
        email=f"attached-skills-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Attached Skills Test User",
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


def _success_payload(applied_skills: list[str] | None = None) -> dict[str, object]:
    """Minimal OpenAI-shape success body for the gateway mock."""

    body: dict[str, object] = {
        "id": "chatcmpl-attached-skills",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "claude-sonnet-4-6",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "routed_inference_tier": 3,
        "routed_provider": "anthropic-prod",
        "cost_estimate": 0.0001,
    }
    if applied_skills is not None:
        body["lq_ai_applied_skills"] = applied_skills
    return body


# ---------------------------------------------------------------------------
# Validation (no gateway call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_attached_skills_neither_slug_nor_inline_returns_422(
    client: AsyncClient, db_user: User
) -> None:
    """An entry with neither slug nor inline_body fails schema validation."""

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    chat_id = chat_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={
            "content": "hello",
            "attached_skills": [{"source": "slash"}],
        },
    )
    # The chats send handler wraps pydantic ValidationError in
    # ``app.errors.ValidationError`` which renders as HTTP 400 with
    # ``code='validation_error'`` under the canonical ``detail`` envelope
    # (not 422 — that's FastAPI's default for body-parser failures, which
    # this handler bypasses).
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["detail"]["code"] == "validation_error"


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_attached_skills_both_slug_and_inline_returns_422(
    client: AsyncClient, db_user: User
) -> None:
    """An entry with BOTH slug and inline_body fails schema validation."""

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    chat_id = chat_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={
            "content": "hello",
            "attached_skills": [{"slug": "nda-review", "inline_body": "x", "source": "slash"}],
        },
    )
    # The chats send handler wraps pydantic ValidationError in
    # ``app.errors.ValidationError`` which renders as HTTP 400 with
    # ``code='validation_error'`` (not 422 — that's FastAPI's default
    # for body-parser failures, which this handler bypasses).
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_inline_body_oversize_returns_422(client: AsyncClient, db_user: User) -> None:
    """An inline_body exceeding the configured ceiling fails schema validation."""

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    chat_id = chat_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={
            "content": "hello",
            "attached_skills": [{"inline_body": "x" * (INLINE_SKILL_BODY_MAX_BYTES + 1)}],
        },
    )
    # The chats send handler wraps pydantic ValidationError in
    # ``app.errors.ValidationError`` which renders as HTTP 400 with
    # ``code='validation_error'`` (not 422 — that's FastAPI's default
    # for body-parser failures, which this handler bypasses).
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_inline_body_oversize_error_does_not_echo_body_content(
    client: AsyncClient, db_user: User
) -> None:
    """Wave D.2 Task 3.0 security — the 4xx error envelope returned for
    an oversize ``inline_body`` MUST NOT echo the submitted body content.

    Regression for the C2 finding in the Task 3.0 code+security review:
    pydantic's ``exc.errors()`` includes the offending ``input`` payload
    by default, so a ``string_too_long`` failure on a 32K+1-byte
    ``inline_body`` returned the FULL submitted body verbatim in the
    response envelope. Violates the ``details MUST NOT contain secrets
    or PII`` contract on ``app.errors.LQAIError``.

    Fix: pass ``include_input=False`` to ``exc.errors()`` at the
    schema-validation rescue site in ``api/app/api/chats.py``.
    """

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    chat_id = chat_resp.json()["id"]

    # Sentinel marker so the assertion is unambiguous — must not appear
    # anywhere else in the implementation or test fixtures.
    sentinel = "S3CR3T-INLINE-BODY-LEAK-TEST-BACKEND-"
    oversize_body = sentinel * ((INLINE_SKILL_BODY_MAX_BYTES // len(sentinel)) + 2)
    assert len(oversize_body) > INLINE_SKILL_BODY_MAX_BYTES

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={
            "content": "hello",
            "attached_skills": [{"inline_body": oversize_body}],
        },
    )
    # Validation failure still surfaces as 4xx (existing wrapping is 400).
    assert 400 <= resp.status_code < 500, resp.status_code

    body_text = resp.text
    # CRITICAL: the submitted inline_body sentinel must not appear in
    # the response envelope. Check both the raw text and the leading
    # bytes that pydantic was previously echoing verbatim.
    assert sentinel not in body_text, (
        "Inline-body content leaked back in the error envelope — "
        "pydantic input echo is not suppressed at the validation rescue site."
    )
    # Useful error identifier MUST still be present (we strip the
    # input, not the diagnostic).
    assert "string_too_long" in body_text or "inline_body" in body_text, (
        f"Error envelope is missing a useful identifier; got: {body_text!r}"
    )


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_attached_skills_over_cap_returns_4xx(client: AsyncClient, db_user: User) -> None:
    """Wave D.2 Task 3.0 (I1) — ``attached_skills`` is capped at
    :data:`ATTACHED_SKILLS_MAX_LEN` entries.

    Regression for the I1 finding in the Task 3.0 code+security review:
    without a cap, a single message could attach thousands of inline
    refs and force the gateway to assemble a multi-megabyte system
    prompt — workload-multiplication DoS available to any authenticated
    user. The schema now refuses lists longer than the cap at validation
    time.
    """

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    chat_id = chat_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={
            "content": "hello",
            "attached_skills": [{"slug": f"skill-{i}"} for i in range(ATTACHED_SKILLS_MAX_LEN + 1)],
        },
    )
    # Schema validation failure wraps as 400 ``validation_error`` per
    # the chats handler's exception path.
    assert 400 <= resp.status_code < 500, resp.text
    assert "too_long" in resp.text or "attached_skills" in resp.text, resp.text


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_legacy_skills_over_cap_returns_4xx(client: AsyncClient, db_user: User) -> None:
    """Wave D.2 Task 3.0 (I1) — the legacy ``skills`` list is also capped.

    Same DoS surface as ``attached_skills``; cap applied symmetrically
    so the legacy field doesn't become an escape hatch.
    """

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    chat_id = chat_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={
            "content": "hello",
            "skills": [f"skill-{i}" for i in range(ATTACHED_SKILLS_MAX_LEN + 1)],
        },
    )
    assert 400 <= resp.status_code < 500, resp.text
    assert "too_long" in resp.text or "skills" in resp.text, resp.text


# ---------------------------------------------------------------------------
# Legacy path still works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_legacy_skills_list_continues_to_work(client: AsyncClient, db_user: User) -> None:
    """``skills: ["foo"]`` forwards to the gateway as ``lq_ai_skills``."""

    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json=_success_payload(["nda-review"]))

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(side_effect=_capture)

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    chat_id = chat_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "review this", "skills": ["nda-review"]},
    )
    assert resp.status_code == 200, resp.text

    fwd = captured["body"]
    assert isinstance(fwd, dict)
    assert fwd["lq_ai_skills"] == ["nda-review"]
    # No inline skills in the forwarded request.
    assert fwd.get("lq_ai_inline_skills", []) == []


# ---------------------------------------------------------------------------
# attached_skills — slug path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_attached_skills_slug_forwards_as_lq_ai_skills(
    client: AsyncClient, db_user: User
) -> None:
    """``attached_skills: [{slug, source}]`` flows to ``lq_ai_skills``."""

    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json=_success_payload(["nda-review"]))

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(side_effect=_capture)

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    chat_id = chat_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={
            "content": "review",
            "attached_skills": [{"slug": "nda-review", "source": "slash"}],
        },
    )
    assert resp.status_code == 200, resp.text

    fwd = captured["body"]
    assert isinstance(fwd, dict)
    assert fwd["lq_ai_skills"] == ["nda-review"]
    assert fwd.get("lq_ai_inline_skills", []) == []

    body = resp.json()
    assert "nda-review" in body["attached_skill_names"]


# ---------------------------------------------------------------------------
# attached_skills — inline path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_attached_skills_inline_forwards_as_lq_ai_inline_skills(
    client: AsyncClient, db_user: User, db_session: AsyncSession
) -> None:
    """Inline-body attachment → forwarded as ``lq_ai_inline_skills`` + audit.

    Also verifies that:

    * The user-message row's ``applied_skills`` carries the synthesized
      ``__inline__<hex>`` name (so the chat history can show the skill
      ran on this turn).
    * The ``chat.message_sent`` audit row carries ``attached_skills``
      provenance with ``kind=inline`` and the supplied ``source``.
    * Inline body content does NOT appear in the audit row's details
      (PII posture).
    """

    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json=_success_payload(["__inline__placeholder"]))

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(side_effect=_capture)

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    chat_id = chat_resp.json()["id"]

    inline_body = "# Wizard Draft\n\nAct as an NDA-review specialist..."

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={
            "content": "try it on this",
            "attached_skills": [{"inline_body": inline_body, "source": "wizard-tryout"}],
        },
    )
    assert resp.status_code == 200, resp.text

    # Forwarded body should carry an inline-skills entry — name is
    # backend-synthesized so we match by shape, not literal value.
    fwd = captured["body"]
    assert isinstance(fwd, dict)
    inline_list = fwd.get("lq_ai_inline_skills")
    assert isinstance(inline_list, list) and len(inline_list) == 1
    ref = inline_list[0]
    assert ref["body"] == inline_body
    assert ref["source"] == "wizard-tryout"
    assert isinstance(ref["name"], str) and ref["name"].startswith("__inline__")
    # The synthesized name also shows up in lq_ai_skills? NO — only in
    # the dedicated field; lq_ai_skills is reserved for catalogue slugs.
    assert ref["name"] not in fwd.get("lq_ai_skills", [])

    synthesized_name = ref["name"]

    # User message row carries the synthesized name in applied_skills.
    user_msgs = (
        (
            await db_session.execute(
                select(Message)
                .where(Message.chat_id == uuid.UUID(chat_id))
                .where(Message.role == "user")
            )
        )
        .scalars()
        .all()
    )
    assert len(user_msgs) == 1
    assert synthesized_name in (user_msgs[0].applied_skills or [])

    # Audit log carries per-attachment provenance.
    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "chat.message_sent")))
        .scalars()
        .all()
    )
    assert audit_rows, "expected chat.message_sent audit row"
    # The most recent send-message audit row. The audit_log model
    # names its time column ``timestamp`` (see app.models.audit).
    audit = sorted(audit_rows, key=lambda r: r.timestamp)[-1]
    attached = (audit.details or {}).get("attached_skills")
    assert isinstance(attached, list) and len(attached) == 1
    assert attached[0]["kind"] == "inline"
    assert attached[0]["source"] == "wizard-tryout"
    assert attached[0]["name"] == synthesized_name
    # PII posture: the inline body content itself MUST NOT be in the
    # audit details.
    assert "Wizard Draft" not in str(audit.details)


# ---------------------------------------------------------------------------
# Mixed: slug + inline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_attached_skills_mixed_slug_and_inline(client: AsyncClient, db_user: User) -> None:
    """Mixed payload forwards each branch to the appropriate gateway field."""

    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json=_success_payload(["nda-review", "__inline__x"]))

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(side_effect=_capture)

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    chat_id = chat_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={
            "content": "go",
            "attached_skills": [
                {"slug": "nda-review", "source": "slash"},
                {"inline_body": "Draft body", "source": "wizard-tryout"},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    fwd = captured["body"]
    assert isinstance(fwd, dict)
    assert fwd["lq_ai_skills"] == ["nda-review"]
    inline_list = fwd.get("lq_ai_inline_skills", [])
    assert len(inline_list) == 1
    assert inline_list[0]["body"] == "Draft body"
    assert inline_list[0]["source"] == "wizard-tryout"


# ---------------------------------------------------------------------------
# Empty attached_skills preserves legacy behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
@respx.mock
async def test_empty_attached_skills_preserves_pre_d2_wire_shape(
    client: AsyncClient, db_user: User
) -> None:
    """Sending with empty ``attached_skills`` matches old behavior exactly."""

    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json=_success_payload())

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(side_effect=_capture)

    headers = _h(db_user)
    chat_resp = await client.post("/api/v1/chats", headers=headers, json={"title": "x"})
    chat_id = chat_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "just a question", "attached_skills": []},
    )
    assert resp.status_code == 200, resp.text
    fwd = captured["body"]
    assert isinstance(fwd, dict)
    # No skills attached on either field; legacy contract intact.
    assert fwd.get("lq_ai_skills", []) == []
    assert fwd.get("lq_ai_inline_skills", []) == []
