"""Integration tests for M4-C1 notification dispatch + read/dismiss API.

Covers:
- notify at Phase.delivery writes one in-app AutonomousNotification row.
- R6 regression: notify is rejected (ToolNotGranted) in any non-delivery phase.
- Email no-op when SMTP unconfigured: notify handler still succeeds + writes
  the in-app row; send_notification_email returns False without raising.
- Email sent when configured: a send is attempted with the session user's
  email + the notification title; a send EXCEPTION never breaks the handler.
- No raw values: the notification title/body carry only what params carried.
- GET /autonomous/notifications: empty, ?unread=true filter, pagination,
  newest-first, isolation, 401.
- POST /autonomous/notifications/{id}/read: sets read_at; idempotent re-read
  preserves the original timestamp; excluded from ?unread=true afterwards;
  cross-user → 404; audit row; 401.
- OpenAPI conformance for the 2 notification paths + schemas.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import Phase, ToolIntent
from app.autonomous.guard import guarded_tool_call
from app.config import get_settings
from app.db.session import get_db
from app.errors import ToolNotGranted
from app.main import app
from app.models.autonomous import AutonomousNotification, AutonomousSession
from app.models.user import User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _override_get_db(db_session: AsyncSession):
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


async def _make_user(db: AsyncSession, *, suffix: str = "") -> User:
    user = User(
        email=f"notif-test-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Notif Test User {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,  # M4-C2: mutate endpoints require opt-in
    )
    db.add(user)
    await db.flush()
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


async def _make_session(
    db: AsyncSession,
    *,
    user: User,
    phase: str = "delivery",
) -> AutonomousSession:
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        halt_state="running",
        status="running",
        current_phase=phase,
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


async def _make_notification(
    db: AsyncSession,
    *,
    user: User,
    session: AutonomousSession,
    title: str = "Session complete",
    body: str = "3 findings; receipt: /autonomous/sessions/x",
    read: bool = False,
) -> AutonomousNotification:
    from datetime import UTC, datetime

    note = AutonomousNotification(
        user_id=user.id,
        session_id=session.id,
        channel="in_app",
        title=title,
        body=body,
        read_at=datetime.now(UTC) if read else None,
    )
    db.add(note)
    await db.flush()
    await db.refresh(note)
    return note


class _StubGateway:
    pass


# ---------------------------------------------------------------------------
# notify chokepoint handler — in-app row + R6 + email
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_notify_at_delivery_writes_in_app_row(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """notify in Phase.delivery writes one in_app AutonomousNotification row."""
    sess = await _make_session(db_session, user=user_a, phase=str(Phase.delivery))

    result = await guarded_tool_call(
        sess,
        ToolIntent.notify,
        {"title": "Run complete", "body": "2 findings; receipt: /x"},
        db_session,
        _StubGateway(),
    )

    note_id = uuid.UUID(result.data["notification_id"])
    row = (
        await db_session.execute(
            select(AutonomousNotification).where(AutonomousNotification.id == note_id)
        )
    ).scalar_one()

    assert row.channel == "in_app"
    assert row.title == "Run complete"
    assert row.body == "2 findings; receipt: /x"
    assert row.user_id == user_a.id
    assert row.session_id == sess.id

    # Exactly one row written.
    all_rows = (
        (
            await db_session.execute(
                select(AutonomousNotification).where(AutonomousNotification.session_id == sess.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(all_rows) == 1


@pytest.mark.integration
async def test_notify_rejected_outside_delivery(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """R6 regression: notify is only granted at Phase.delivery.

    In every other phase the chokepoint raises ToolNotGranted before any
    notification row is written.
    """
    for phase in (Phase.intake, Phase.analysis, Phase.drafting, Phase.ethics_review):
        sess = await _make_session(db_session, user=user_a, phase=str(phase))
        with pytest.raises(ToolNotGranted):
            await guarded_tool_call(
                sess,
                ToolIntent.notify,
                {"title": "nope", "body": "should not write"},
                db_session,
                _StubGateway(),
            )


@pytest.mark.integration
async def test_notify_email_noop_when_unconfigured(
    db_session: AsyncSession,
    user_a: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With SMTP unconfigured the handler succeeds + writes the in-app row.

    send_notification_email returns False without raising; the in-app row
    is the durable record regardless.
    """
    # Ensure smtp_host is unset for this test.
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", None)

    sess = await _make_session(db_session, user=user_a, phase=str(Phase.delivery))

    result = await guarded_tool_call(
        sess,
        ToolIntent.notify,
        {"title": "Run complete", "body": "1 finding; receipt: /x"},
        db_session,
        _StubGateway(),
    )

    note_id = uuid.UUID(result.data["notification_id"])
    row = (
        await db_session.execute(
            select(AutonomousNotification).where(AutonomousNotification.id == note_id)
        )
    ).scalar_one()
    assert row.title == "Run complete"

    # And the sender itself is a clean no-op.
    from app.autonomous.notify_email import send_notification_email

    sent = await send_notification_email(to_addr=user_a.email, subject="x", body="y")
    assert sent is False


@pytest.mark.integration
async def test_notify_email_sent_when_configured(
    db_session: AsyncSession,
    user_a: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With SMTP configured, the notify handler attempts a send to the user.

    Patches smtplib.SMTP so no real network call happens; asserts the
    recipient + subject reached the send path.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_use_tls", False)
    monkeypatch.setattr(settings, "smtp_username", None)
    monkeypatch.setattr(settings, "smtp_password", None)
    monkeypatch.setattr(settings, "smtp_from", "noreply@lq.ai")

    sent_messages: list[dict[str, str]] = []

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout

        def __enter__(self) -> _FakeSMTP:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def starttls(self) -> None:  # pragma: no cover - tls disabled here
            pass

        def login(self, username: str, password: str) -> None:  # pragma: no cover
            pass

        def send_message(self, msg: object) -> None:
            sent_messages.append(
                {"to": msg["To"], "subject": msg["Subject"], "from": msg["From"]}  # type: ignore[index]
            )

    monkeypatch.setattr("app.autonomous.notify_email.smtplib.SMTP", _FakeSMTP)

    sess = await _make_session(db_session, user=user_a, phase=str(Phase.delivery))
    await guarded_tool_call(
        sess,
        ToolIntent.notify,
        {"title": "Run complete", "body": "2 findings; receipt: /x"},
        db_session,
        _StubGateway(),
    )

    assert len(sent_messages) == 1
    assert sent_messages[0]["to"] == user_a.email
    assert sent_messages[0]["subject"] == "Run complete"


@pytest.mark.integration
async def test_notify_email_failure_does_not_break_handler(
    db_session: AsyncSession,
    user_a: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A send exception is swallowed; the in-app row still lands + handler succeeds."""
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "noreply@lq.ai")

    class _BoomSMTP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise OSError("connection refused")

    monkeypatch.setattr("app.autonomous.notify_email.smtplib.SMTP", _BoomSMTP)

    sess = await _make_session(db_session, user=user_a, phase=str(Phase.delivery))
    result = await guarded_tool_call(
        sess,
        ToolIntent.notify,
        {"title": "Run complete", "body": "2 findings; receipt: /x"},
        db_session,
        _StubGateway(),
    )

    note_id = uuid.UUID(result.data["notification_id"])
    row = (
        await db_session.execute(
            select(AutonomousNotification).where(AutonomousNotification.id == note_id)
        )
    ).scalar_one()
    assert row.title == "Run complete"


@pytest.mark.integration
async def test_send_notification_email_smtp_timeout_degrades_to_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connect TimeoutError is caught best-effort: returns False, never raises.

    Also asserts the configured ``smtp_timeout`` is forwarded to the SMTP
    constructor — a hung mail server must not tie up the worker thread.
    """
    from app.autonomous.notify_email import send_notification_email

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_from", "noreply@lq.ai")
    monkeypatch.setattr(settings, "smtp_timeout", 7)

    captured: dict[str, object] = {}

    class _HangSMTP:
        def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout
            # socket.timeout is an alias of the builtin TimeoutError.
            raise TimeoutError("timed out")

    monkeypatch.setattr("app.autonomous.notify_email.smtplib.SMTP", _HangSMTP)

    sent = await send_notification_email(to_addr="x@example.com", subject="hi", body="body")
    assert sent is False
    # The configured timeout was forwarded to the SMTP constructor.
    assert captured["timeout"] == 7


@pytest.mark.integration
async def test_notify_handles_missing_user_email_through_handler(
    db_session: AsyncSession,
    user_a: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session whose user is gone (email None) still writes the in-app row.

    Drives the notify chokepoint handler with SMTP configured but the user
    lookup returning None (a deleted user). The ``user.email if user else
    None`` no-op path is exercised end-to-end through the handler: the email
    send is a no-op (no recipient), the in-app row still lands, no raise.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "noreply@lq.ai")

    sent_messages: list[dict[str, str]] = []

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
            pass

        def __enter__(self) -> _FakeSMTP:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def starttls(self) -> None:  # pragma: no cover - tls disabled here
            pass

        def login(self, username: str, password: str) -> None:  # pragma: no cover
            pass

        def send_message(self, msg: object) -> None:  # pragma: no cover - never sent
            sent_messages.append({"to": msg["To"]})  # type: ignore[index]

    monkeypatch.setattr("app.autonomous.notify_email.smtplib.SMTP", _FakeSMTP)

    sess = await _make_session(db_session, user=user_a, phase=str(Phase.delivery))

    # Simulate a deleted user: the handler's db.get(User, ...) returns None.
    real_get = db_session.get

    async def _get_none(entity: object, ident: object, *a: object, **k: object):
        if entity is User:
            return None
        return await real_get(entity, ident, *a, **k)

    monkeypatch.setattr(db_session, "get", _get_none)

    result = await guarded_tool_call(
        sess,
        ToolIntent.notify,
        {"title": "Run complete", "body": "1 finding; receipt: /x"},
        db_session,
        _StubGateway(),
    )

    note_id = uuid.UUID(result.data["notification_id"])
    row = (
        await db_session.execute(
            select(AutonomousNotification).where(AutonomousNotification.id == note_id)
        )
    ).scalar_one()
    assert row.title == "Run complete"
    # No recipient → email was a no-op; no send was attempted.
    assert sent_messages == []


@pytest.mark.integration
async def test_send_notification_email_newline_title_cannot_inject_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newline in the subject cannot inject a header — degrades to False.

    EmailMessage's header-set rejects an embedded newline, raising inside
    _send_sync. The best-effort except catches it: no header injection, no
    raise, returns False.
    """
    from app.autonomous.notify_email import send_notification_email

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "noreply@lq.ai")

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int | None = None) -> None:
            pass

        def __enter__(self) -> _FakeSMTP:  # pragma: no cover - never reached
            return self

        def __exit__(self, *args: object) -> None:  # pragma: no cover
            return None

        def send_message(self, msg: object) -> None:  # pragma: no cover
            pass

    monkeypatch.setattr("app.autonomous.notify_email.smtplib.SMTP", _FakeSMTP)

    sent = await send_notification_email(
        to_addr="x@example.com",
        subject="line1\nInjected: header",
        body="b",
    )
    assert sent is False


@pytest.mark.integration
async def test_notify_body_carries_only_params(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """The notification title/body contain exactly what params carried.

    No raw entity text is injected by the handler — the body is the
    counts/IDs/receipt-link string the caller supplied (privacy spirit of
    the observability tests).
    """
    sess = await _make_session(db_session, user=user_a, phase=str(Phase.delivery))
    title = "Analysis complete"
    body = "5 clauses reviewed; 2 flagged; receipt: /autonomous/sessions/abc"

    result = await guarded_tool_call(
        sess,
        ToolIntent.notify,
        {"title": title, "body": body},
        db_session,
        _StubGateway(),
    )

    note_id = uuid.UUID(result.data["notification_id"])
    row = (
        await db_session.execute(
            select(AutonomousNotification).where(AutonomousNotification.id == note_id)
        )
    ).scalar_one()
    assert row.title == title
    assert row.body == body


# ---------------------------------------------------------------------------
# GET /autonomous/notifications
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_notifications_empty_for_new_user(
    client: AsyncClient,
    user_a: User,
) -> None:
    """A user with no notifications gets notifications=[] and total_count=0."""
    resp = await client.get("/api/v1/autonomous/notifications", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["notifications"] == []
    assert body["total_count"] == 0
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.integration
async def test_list_notifications_unread_filter(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """?unread=true returns only rows with read_at IS NULL."""
    sess = await _make_session(db_session, user=user_a)
    unread = await _make_notification(db_session, user=user_a, session=sess, read=False)
    read = await _make_notification(db_session, user=user_a, session=sess, read=True)

    resp = await client.get(
        "/api/v1/autonomous/notifications",
        headers=_bearer(user_a),
        params={"unread": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {n["id"] for n in body["notifications"]}
    assert str(unread.id) in ids
    assert str(read.id) not in ids
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_list_notifications_no_filter_returns_all(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Without ?unread, all the caller's notifications are returned."""
    sess = await _make_session(db_session, user=user_a)
    unread = await _make_notification(db_session, user=user_a, session=sess, read=False)
    read = await _make_notification(db_session, user=user_a, session=sess, read=True)

    resp = await client.get("/api/v1/autonomous/notifications", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {n["id"] for n in body["notifications"]}
    assert str(unread.id) in ids
    assert str(read.id) in ids
    assert body["total_count"] == 2


@pytest.mark.integration
async def test_list_notifications_pagination(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """limit and offset are honoured; total_count reflects the full count."""
    sess = await _make_session(db_session, user=user_a)
    for _ in range(5):
        await _make_notification(db_session, user=user_a, session=sess)

    resp = await client.get(
        "/api/v1/autonomous/notifications",
        headers=_bearer(user_a),
        params={"limit": 2, "offset": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["notifications"]) == 2
    assert body["total_count"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1


@pytest.mark.integration
async def test_list_notifications_newest_first(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Notifications are returned in created_at DESC order."""
    import datetime as _dt

    sess = await _make_session(db_session, user=user_a)
    for _ in range(3):
        await _make_notification(db_session, user=user_a, session=sess)

    resp = await client.get("/api/v1/autonomous/notifications", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    created_ats = [_dt.datetime.fromisoformat(n["created_at"]) for n in body["notifications"]]
    for i in range(len(created_ats) - 1):
        assert created_ats[i] >= created_ats[i + 1]


@pytest.mark.integration
async def test_list_notifications_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """User A's list never returns user B's notifications."""
    sess_a = await _make_session(db_session, user=user_a)
    sess_b = await _make_session(db_session, user=user_b)
    note_a = await _make_notification(db_session, user=user_a, session=sess_a)
    note_b = await _make_notification(db_session, user=user_b, session=sess_b)

    resp = await client.get("/api/v1/autonomous/notifications", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {n["id"] for n in body["notifications"]}
    assert str(note_a.id) in ids
    assert str(note_b.id) not in ids
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_list_notifications_unauth_returns_401(client: AsyncClient) -> None:
    """No Authorization header returns 401."""
    resp = await client.get("/api/v1/autonomous/notifications")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# POST /autonomous/notifications/{id}/read
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_read_sets_read_at(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Marking read sets read_at and returns the updated notification."""
    sess = await _make_session(db_session, user=user_a)
    note = await _make_notification(db_session, user=user_a, session=sess, read=False)

    resp = await client.post(
        f"/api/v1/autonomous/notifications/{note.id}/read",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(note.id)
    assert body["read_at"] is not None

    await db_session.refresh(note)
    assert note.read_at is not None


@pytest.mark.integration
async def test_read_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Re-reading an already-read notification preserves the original read_at."""
    import datetime as _dt

    sess = await _make_session(db_session, user=user_a)
    note = await _make_notification(db_session, user=user_a, session=sess, read=True)
    original = note.read_at

    resp = await client.post(
        f"/api/v1/autonomous/notifications/{note.id}/read",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    returned = _dt.datetime.fromisoformat(body["read_at"])
    if returned.tzinfo is None:
        returned = returned.replace(tzinfo=_dt.UTC)
    assert original is not None
    if original.tzinfo is None:
        original = original.replace(tzinfo=_dt.UTC)
    assert returned == original


@pytest.mark.integration
async def test_read_excludes_from_unread_filter(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """After marking read, the notification drops out of ?unread=true."""
    sess = await _make_session(db_session, user=user_a)
    note = await _make_notification(db_session, user=user_a, session=sess, read=False)

    await client.post(
        f"/api/v1/autonomous/notifications/{note.id}/read",
        headers=_bearer(user_a),
    )

    resp = await client.get(
        "/api/v1/autonomous/notifications",
        headers=_bearer(user_a),
        params={"unread": "true"},
    )
    body = resp.json()
    ids = {n["id"] for n in body["notifications"]}
    assert str(note.id) not in ids
    assert body["total_count"] == 0


@pytest.mark.integration
async def test_read_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Read writes an autonomous_notification.read audit row."""
    from sqlalchemy import select as _select

    from app.models.audit import AuditLog

    sess = await _make_session(db_session, user=user_a)
    note = await _make_notification(db_session, user=user_a, session=sess, read=False)

    await client.post(
        f"/api/v1/autonomous/notifications/{note.id}/read",
        headers=_bearer(user_a),
    )

    rows = (
        (
            await db_session.execute(
                _select(AuditLog)
                .where(AuditLog.action == "autonomous_notification.read")
                .where(AuditLog.resource_id == str(note.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_read_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """Marking another user's notification read returns 404 (not 403)."""
    sess_b = await _make_session(db_session, user=user_b)
    note_b = await _make_notification(db_session, user=user_b, session=sess_b)

    resp = await client.post(
        f"/api/v1/autonomous/notifications/{note_b.id}/read",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_read_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """No Authorization header returns 401."""
    sess = await _make_session(db_session, user=user_a)
    note = await _make_notification(db_session, user=user_a, session=sess)
    resp = await client.post(f"/api/v1/autonomous/notifications/{note.id}/read")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# OpenAPI conformance
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_openapi_notification_paths_registered() -> None:
    """The two notification paths are registered in the OpenAPI spec."""
    schema = app.openapi()
    paths = schema["paths"]
    assert "/api/v1/autonomous/notifications" in paths
    assert "/api/v1/autonomous/notifications/{notification_id}/read" in paths


@pytest.mark.unit
def test_openapi_notification_list_accepts_unread_filter() -> None:
    """GET /notifications accepts ?unread, ?limit, ?offset."""
    schema = app.openapi()
    params = schema["paths"]["/api/v1/autonomous/notifications"]["get"]["parameters"]
    names = {p["name"] for p in params}
    assert "unread" in names
    assert "limit" in names
    assert "offset" in names


@pytest.mark.unit
def test_openapi_notification_schemas_in_components() -> None:
    """AutonomousNotificationRead + AutonomousNotificationListResponse are in components."""
    schema = app.openapi()
    schemas = schema.get("components", {}).get("schemas", {})
    assert "AutonomousNotificationRead" in schemas
    assert "AutonomousNotificationListResponse" in schemas

    list_props = schemas["AutonomousNotificationListResponse"].get("properties", {})
    assert "notifications" in list_props
    assert "total_count" in list_props
    assert "limit" in list_props
    assert "offset" in list_props
