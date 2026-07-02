# Cross-user Auditor Role Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only, deployment-wide `auditor` RBAC role so that `{admin, auditor}` (the "privileged reader" set) may read another user's citation ledger / message sources / autonomous-session ledger / chat receipts, with every privileged cross-user read audit-logged, while non-privileged non-owners keep getting an existence-safe 404.

**Architecture:** Additive authorization change. A new `auditor` value in the existing `users.role` enum (one migration). A pure predicate `is_privileged_reader(user)` and a closed-enum `auditor_audit(...)` wrapper are the shared substrate. Each owner-scoped read endpoint gains a load-then-branch reader helper that returns `(row, was_privileged)`; when `was_privileged`, the handler writes one audit row and explicitly commits it (a GET read-path commit — the one deliberate novelty). No JWT/token change (role is re-read from the DB each request).

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, pytest. Python; `ruff format` + `ruff check` + `mypy` (api standard mode).

**Spec:** `docs/superpowers/specs/2026-07-02-cross-user-auditor-role-design.md`

## Global Constraints

- **Security-gated:** authorization change → the PR auto-routes to security reviewers per `.github/CODEOWNERS`. Do not self-merge past that gate.
- **Existence-safety:** a *non-privileged* non-owner MUST get an indistinguishable **404** on the ledger/sources/session-ledger endpoints (never 403, never a different message). Reader helpers load-then-branch so the non-privileged path is identical for "exists, not yours" and "doesn't exist".
- **Privileged reader = `user.is_admin or user.role == "auditor"`** — this exact predicate, everywhere.
- **Audit only privileged *cross-user* reads.** Owner-reading-own writes no audit row. Privileged read writes exactly one row via `auditor_audit`, then the handler `await db.commit()`s it (GET handlers do not otherwise commit).
- **Do NOT change non-privileged failure codes:** ledger endpoints stay 404; receipts stays 403 for non-privileged non-owners. (The 404-vs-403 reconciliation is a deferred DE, out of scope.)
- **`auditor` is read-only for free:** `_MUTATING_ROLES = {"admin","member"}` is UNCHANGED — do not add `auditor` to it. `MutatingUser` therefore 403s auditors on every mutating endpoint automatically.
- **`is_admin` stays `False` for an auditor** (the admin role handler already sets `is_admin = role == "admin"`).
- **Dev-env:** NEVER host-side `alembic upgrade` on the live dev DB. Verify migration 0065 on a throwaway `pgvector/pgvector:pg16` container (conftest auto-migrates). Apply to the dev stack by rebuilding `api` + `arq-worker` + `ingest-worker` together. Never `docker compose down -v`.
- **No new routes** → the `IMPLEMENTED_ROUTES` (`api/tests/test_endpoints.py`) and `EXPECTED_PATHS` path-count (`api/tests/test_openapi.py`) guards are unaffected and must NOT be edited.
- Run BOTH `ruff format` and `ruff check` locally (CI runs them as separate gates). Coverage must not decrease.
- Commits: `git commit -s` (DCO) AND trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File map

- Modify `api/app/api/admin.py` — add `"auditor"` to `_ROLE_ENUM` (line 655).
- Create `api/alembic/versions/0065_users_role_add_auditor.py` — widen `chk_users_role_enum`.
- Modify `api/app/api/dependencies.py` — add `is_privileged_reader(user)` predicate.
- Create `api/app/auditor_audit.py` — closed-enum `auditor_audit(...)` wrapper (mirrors `app/autonomous/audit.py`).
- Modify `api/app/api/chats.py` — add `_load_chat_for_reader(...)`; wire into `get_chat_ledger` (1799) and `get_message_sources` (1745).
- Modify `api/app/api/autonomous.py` — add `_load_session_for_reader(...)`; wire into `get_session_ledger` (667).
- Modify `api/app/api/chat_receipts.py` — extend the `is_admin` bypass (line 103) to `is_privileged_reader`; add audit; same for the export variant.
- Modify `docs/api/backend-openapi.yaml` — add `auditor` to the role enum schema.
- Tests: `api/tests/test_wave_c.py`, `api/tests/integration/test_ledger_endpoint.py`, `api/tests/test_message_tool_sources.py`, `api/tests/autonomous/test_session_ledger_endpoint.py`, `api/tests/test_chat_receipts.py`, plus a new `api/tests/test_auditor_audit.py`.

---

## Task 1: Role enum + migration 0065 + granting acceptance

**Files:**
- Modify: `api/app/api/admin.py:655`
- Create: `api/alembic/versions/0065_users_role_add_auditor.py`
- Test: `api/tests/test_wave_c.py`

**Produces:** `"auditor"` is a valid `users.role` value (DB CHECK + `_ROLE_ENUM`); `PATCH /api/v1/admin/users/{id}/role` accepts it; an `auditor` user is non-mutating.

- [ ] **Step 1: Write the failing tests** (append to `api/tests/test_wave_c.py`):

```python
@pytest.mark.asyncio
async def test_update_user_role_to_auditor_sets_readonly(client, admin_headers, make_user):
    target = await make_user(email="assoc@example.com", role="member")
    resp = await client.patch(
        f"/api/v1/admin/users/{target.id}/role",
        json={"role": "auditor"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "auditor"
    assert body["is_admin"] is False  # auditor is NOT an operator-admin


@pytest.mark.asyncio
async def test_auditor_is_rejected_from_mutating_endpoint(client, make_user, login_as):
    # An auditor hitting any mutating (POST/PATCH/DELETE) endpoint gets 403 via MutatingUser.
    auditor = await make_user(email="auditor@example.com", role="auditor")
    headers = await login_as(auditor)
    resp = await client.post("/api/v1/projects", json={"name": "x"}, headers=headers)
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"
```

(Match the file's existing fixture names — read `test_wave_c.py` for the real `make_user`/`login_as`/`admin_headers` fixtures and adapt the calls; the assertions above are the contract.)

- [ ] **Step 2: Run — expect FAIL** (role not in enum → 422/400, or fixture gap):

Run: `cd api && python -m pytest tests/test_wave_c.py -k auditor -v`
Expected: FAIL (role `auditor` rejected by `_ROLE_ENUM`).

- [ ] **Step 3: Add `auditor` to the enum.** In `api/app/api/admin.py:655`:

```python
_ROLE_ENUM = frozenset({"admin", "member", "viewer", "auditor"})
```

- [ ] **Step 4: Create migration `api/alembic/versions/0065_users_role_add_auditor.py`:**

```python
"""users.role — add 'auditor' to the RBAC CHECK constraint.

Widens ``chk_users_role_enum`` (migration 0017) from
('admin','member','viewer') to include 'auditor' — a read-only,
deployment-wide cross-user reviewer role (see the cross-user auditor spec).
No data migration: existing rows all satisfy the wider set.

Revision ID: 0065
Revises: 0064
"""

from alembic import op

revision = "0065"
down_revision = "0064"  # VERIFY: must equal the `revision` var in 0064_*.py
branch_labels = None
depends_on = None

_OLD = "role IN ('admin', 'member', 'viewer')"
_NEW = "role IN ('admin', 'member', 'viewer', 'auditor')"


def upgrade() -> None:
    op.drop_constraint("chk_users_role_enum", "users", type_="check")
    op.create_check_constraint("chk_users_role_enum", "users", _NEW)


def downgrade() -> None:
    # Safe only if no 'auditor' rows exist; forward-only in practice.
    op.drop_constraint("chk_users_role_enum", "users", type_="check")
    op.create_check_constraint("chk_users_role_enum", "users", _OLD)
```

- [ ] **Step 5: Verify `down_revision`.** Open `api/alembic/versions/0064_authority_citations_and_text_cache.py`, read its `revision = "..."`, and set `down_revision` in 0065 to that exact value (expected `"0064"`).

- [ ] **Step 6: Run — expect PASS** (conftest auto-migrates the throwaway pgvector, so the new constraint is live):

Run: `cd api && python -m pytest tests/test_wave_c.py -k auditor -v`
Expected: PASS (both tests).

- [ ] **Step 7: Migration sanity test** — add to `test_wave_c.py` (or wherever migration/constraint tests live):

```python
@pytest.mark.asyncio
async def test_users_role_constraint_accepts_auditor_rejects_bogus(db_session, make_user):
    u = await make_user(email="aud2@example.com", role="auditor")  # must not raise
    assert u.role == "auditor"
    from sqlalchemy.exc import IntegrityError, DBAPIError
    with pytest.raises((IntegrityError, DBAPIError)):
        await make_user(email="bogus@example.com", role="notarole")
```

Run: `cd api && python -m pytest tests/test_wave_c.py -k "auditor or constraint" -v` → PASS. Then `ruff format . && ruff check .`.

- [ ] **Step 8: Commit**

```bash
git add api/app/api/admin.py api/alembic/versions/0065_users_role_add_auditor.py api/tests/test_wave_c.py
git commit -s -m "feat(auditor): add auditor role to RBAC enum + migration 0065

Refs Donna cross-user-auditor-role request"
```

---

## Task 2: Shared authz substrate — predicate + audit wrapper

**Files:**
- Modify: `api/app/api/dependencies.py` (add `is_privileged_reader`, near `_MUTATING_ROLES` at line 191)
- Create: `api/app/auditor_audit.py`
- Test: `api/tests/test_auditor_audit.py`

**Interfaces produced (later tasks consume these exact signatures):**
- `is_privileged_reader(user: User) -> bool` — returns `user.is_admin or user.role == "auditor"`.
- `async def auditor_audit(db: AsyncSession, *, user: User, event: str, resource_type: str, resource_id: str, viewed_user_id: uuid.UUID) -> None` — writes one `audit_log` row `action=f"auditor.{event}"`, `details={"viewed_user_id": str(viewed_user_id)}`; asserts `event` is in the closed set; does **NOT** commit (caller commits).

- [ ] **Step 1: Write the failing tests** (`api/tests/test_auditor_audit.py`):

```python
import uuid
import pytest
from sqlalchemy import select
from app.api.dependencies import is_privileged_reader
from app.auditor_audit import auditor_audit, _AUDITOR_EVENTS
from app.models.audit import AuditLog


class _FakeUser:
    def __init__(self, is_admin=False, role="member", uid=None):
        self.is_admin = is_admin
        self.role = role
        self.id = uid or uuid.uuid4()


def test_is_privileged_reader_truth_table():
    assert is_privileged_reader(_FakeUser(is_admin=True, role="admin")) is True
    assert is_privileged_reader(_FakeUser(is_admin=False, role="auditor")) is True
    assert is_privileged_reader(_FakeUser(is_admin=False, role="member")) is False
    assert is_privileged_reader(_FakeUser(is_admin=False, role="viewer")) is False


@pytest.mark.asyncio
async def test_auditor_audit_writes_row(db_session, make_user):
    reader = await make_user(email="r@example.com", role="auditor")
    viewed = uuid.uuid4()
    await auditor_audit(
        db_session, user=reader, event="ledger_viewed",
        resource_type="chat", resource_id=str(uuid.uuid4()), viewed_user_id=viewed,
    )
    await db_session.flush()
    row = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "auditor.ledger_viewed")
    )).scalars().one()
    assert row.user_id == reader.id
    assert row.details["viewed_user_id"] == str(viewed)


@pytest.mark.asyncio
async def test_auditor_audit_rejects_unknown_event(db_session, make_user):
    reader = await make_user(email="r2@example.com", role="auditor")
    with pytest.raises(AssertionError):
        await auditor_audit(
            db_session, user=reader, event="not_an_event",
            resource_type="chat", resource_id="x", viewed_user_id=uuid.uuid4(),
        )
```

- [ ] **Step 2: Run — expect FAIL** (modules/symbols don't exist):

Run: `cd api && python -m pytest tests/test_auditor_audit.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Add the predicate** to `api/app/api/dependencies.py` (just below `_MUTATING_ROLES`, ~line 192):

```python
def is_privileged_reader(user: User) -> bool:
    """True for callers allowed to read ANY user's ledger/gate/receipts.

    The "privileged reader" set is {admin, auditor}: operator-admins
    (``is_admin``) and the read-only cross-user ``auditor`` role. Ordinary
    ``member``/``viewer`` users are owner-scoped and never privileged here.
    """
    return user.is_admin or getattr(user, "role", "member") == "auditor"
```

- [ ] **Step 4: Create `api/app/auditor_audit.py`:**

```python
"""Closed-enum audit wrapper for privileged cross-user reads.

Every time an admin/auditor reads ANOTHER user's ledger / sources /
session-ledger / receipts, the handler records one ``audit_log`` row
through this wrapper ("audit the auditor"). Mirrors
``app/autonomous/audit.py``: a closed event set caught at call time.

NOTE: like ``audit_action``, this flushes but does NOT commit — but its
callers are GET handlers that do not otherwise commit, so each caller
MUST ``await db.commit()`` after calling this (see the endpoint tasks).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit_action
from app.models.user import User

_AUDITOR_EVENTS: frozenset[str] = frozenset(
    {
        "ledger_viewed",
        "sources_viewed",
        "session_ledger_viewed",
        "receipts_viewed",
        "receipts_exported",
    }
)


async def auditor_audit(
    db: AsyncSession,
    *,
    user: User,
    event: str,
    resource_type: str,
    resource_id: str,
    viewed_user_id: uuid.UUID,
) -> None:
    """Write one ``audit_log`` row for a privileged cross-user read.

    ``event`` must be in :data:`_AUDITOR_EVENTS` (AssertionError otherwise —
    catches call-site typos in tests). Does not commit; the caller does.
    """
    assert event in _AUDITOR_EVENTS, f"unknown auditor audit event: {event!r}"
    await audit_action(
        db,
        user_id=user.id,
        action=f"auditor.{event}",
        resource_type=resource_type,
        resource_id=resource_id,
        details={"viewed_user_id": str(viewed_user_id)},
    )
```

- [ ] **Step 5: Run — expect PASS:**

Run: `cd api && python -m pytest tests/test_auditor_audit.py -v`
Expected: PASS (4 tests). Then `ruff format . && ruff check . && mypy app/auditor_audit.py`.

- [ ] **Step 6: Commit**

```bash
git add api/app/api/dependencies.py api/app/auditor_audit.py api/tests/test_auditor_audit.py
git commit -s -m "feat(auditor): is_privileged_reader predicate + auditor_audit wrapper

Refs Donna cross-user-auditor-role request"
```

---

## Task 3: Chat ledger + message sources — privileged reader + audit

**Files:**
- Modify: `api/app/api/chats.py` (new `_load_chat_for_reader`; wire `get_chat_ledger` @1799, `get_message_sources` @1745)
- Test: `api/tests/integration/test_ledger_endpoint.py`, `api/tests/test_message_tool_sources.py`

**Consumes:** `is_privileged_reader` (dependencies.py), `auditor_audit` (app.auditor_audit).

- [ ] **Step 1: Write failing tests.** In `api/tests/integration/test_ledger_endpoint.py`, extend the cross-user coverage (near `test_ledger_cross_user_404`):

```python
@pytest.mark.asyncio
async def test_ledger_auditor_can_read_cross_user_and_is_audited(
    client, make_user, login_as, seed_chat_with_ledger, db_session
):
    owner = await make_user(email="owner@example.com", role="member")
    chat = await seed_chat_with_ledger(owner)  # returns a Chat with >=1 ledger entry
    auditor = await make_user(email="aud@example.com", role="auditor")
    headers = await login_as(auditor)

    resp = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=headers)
    assert resp.status_code == 200
    assert "entries" in resp.json()

    from sqlalchemy import select
    from app.models.audit import AuditLog
    row = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "auditor.ledger_viewed")
    )).scalars().one()
    assert row.user_id == auditor.id
    assert row.details["viewed_user_id"] == str(owner.id)


@pytest.mark.asyncio
async def test_ledger_member_cross_user_still_404_and_not_audited(
    client, make_user, login_as, seed_chat_with_ledger, db_session
):
    owner = await make_user(email="owner2@example.com", role="member")
    chat = await seed_chat_with_ledger(owner)
    other = await make_user(email="other@example.com", role="member")
    headers = await login_as(other)

    resp = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=headers)
    assert resp.status_code == 404
    from sqlalchemy import select, func
    from app.models.audit import AuditLog
    count = (await db_session.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "auditor.ledger_viewed")
    )).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_ledger_owner_read_not_audited(
    client, make_user, login_as, seed_chat_with_ledger, db_session
):
    owner = await make_user(email="owner3@example.com", role="member")
    chat = await seed_chat_with_ledger(owner)
    headers = await login_as(owner)
    resp = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=headers)
    assert resp.status_code == 200
    from sqlalchemy import select, func
    from app.models.audit import AuditLog
    count = (await db_session.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "auditor.ledger_viewed")
    )).scalar_one()
    assert count == 0
```

Add the analogous **cross-user triad for `/messages/{message_id}/sources`** in `api/tests/test_message_tool_sources.py` (this endpoint has NO cross-user test today), asserting `auditor.sources_viewed` is written for the privileged read and not for the 404/owner cases.

(Adapt fixture names — read each test file for the real `make_user`/`login_as`/seed helpers. If no `seed_chat_with_ledger` helper exists, follow the existing `test_ledger_endpoint.py` setup that creates a chat + ledger entry and reuse it.)

- [ ] **Step 2: Run — expect FAIL** (auditor gets 404 today):

Run: `cd api && python -m pytest tests/integration/test_ledger_endpoint.py -k "auditor or cross_user or owner_read" tests/test_message_tool_sources.py -k "auditor or cross_user" -v`
Expected: FAIL (auditor read → 404; no audit rows).

- [ ] **Step 3: Add the reader helper** in `api/app/api/chats.py` (just after `_load_visible_chat`, ~line 353). Add imports at the top of the file: `from app.api.dependencies import is_privileged_reader` and `from app.auditor_audit import auditor_audit`.

```python
async def _load_chat_for_reader(
    db: AsyncSession,
    chat_id: uuid.UUID,
    user: User,
    *,
    include_archived: bool = True,
) -> tuple[Chat, bool]:
    """Load a chat for a *reader*; return ``(chat, was_privileged_cross_user)``.

    Owner → ``(chat, False)``. A privileged reader (admin/auditor) reading a
    chat they do not own → ``(chat, True)``. Everyone else — and a missing
    chat — → 404, indistinguishably (existence-safe): a non-privileged
    non-owner cannot tell "exists, not yours" from "doesn't exist".
    """
    stmt = select(Chat).where(Chat.id == chat_id)
    if not include_archived:
        stmt = stmt.where(Chat.archived_at.is_(None))
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFound(f"Chat {chat_id} not found.", details={"chat_id": str(chat_id)})
    if row.owner_id == user.id:
        return row, False
    if is_privileged_reader(user):
        return row, True
    raise NotFound(f"Chat {chat_id} not found.", details={"chat_id": str(chat_id)})
```

(Confirm `User` is imported in chats.py; if not, add `from app.models.user import User`.)

- [ ] **Step 4: Wire `get_chat_ledger`** — replace the ownership line at `chats.py:1822` (`await _load_visible_chat(db, cid, user.id, include_archived=True)`) with:

```python
    chat, was_privileged = await _load_chat_for_reader(db, cid, user, include_archived=True)
    if was_privileged:
        await auditor_audit(
            db, user=user, event="ledger_viewed",
            resource_type="chat", resource_id=str(cid), viewed_user_id=chat.owner_id,
        )
        await db.commit()  # GET read-path: persist the audit row explicitly
```

Leave the rest of the handler (message-id validation, `resolve_ledger_entries`, `resolve_gates`, the treatment fallback) unchanged.

- [ ] **Step 5: Wire `get_message_sources`** — replace the ownership line at `chats.py:1766` with the same block but `event="sources_viewed"`:

```python
    chat, was_privileged = await _load_chat_for_reader(db, cid, user, include_archived=True)
    if was_privileged:
        await auditor_audit(
            db, user=user, event="sources_viewed",
            resource_type="chat", resource_id=str(cid), viewed_user_id=chat.owner_id,
        )
        await db.commit()
```

- [ ] **Step 6: Run — expect PASS:**

Run: `cd api && python -m pytest tests/integration/test_ledger_endpoint.py tests/test_message_tool_sources.py -v`
Expected: PASS (new + pre-existing tests). Then `ruff format . && ruff check . && mypy app/api/chats.py`.

- [ ] **Step 7: Commit**

```bash
git add api/app/api/chats.py api/tests/integration/test_ledger_endpoint.py api/tests/test_message_tool_sources.py
git commit -s -m "feat(auditor): privileged cross-user read on chat ledger + message sources

Adds _load_chat_for_reader (existence-safe), audit-logs privileged reads.
Refs Donna cross-user-auditor-role request"
```

---

## Task 4: Autonomous session ledger — privileged reader + audit

**Files:**
- Modify: `api/app/api/autonomous.py` (new `_load_session_for_reader`; wire `get_session_ledger` @667)
- Test: `api/tests/autonomous/test_session_ledger_endpoint.py`

**Consumes:** `is_privileged_reader`, `auditor_audit`.

- [ ] **Step 1: Write failing tests** in `api/tests/autonomous/test_session_ledger_endpoint.py` — the triad, mirroring Task 3 but for `GET /api/v1/autonomous/sessions/{id}/ledger`, asserting `auditor.session_ledger_viewed` written for the privileged read, not for member-404 or owner reads. (Reuse the file's existing session+ledger seed helper — see `test_session_ledger_endpoint_cross_user_returns_404` at line 162 for the setup pattern.)

- [ ] **Step 2: Run — expect FAIL:**

Run: `cd api && python -m pytest tests/autonomous/test_session_ledger_endpoint.py -k "auditor or cross_user or owner" -v`
Expected: FAIL (auditor → 404 today).

- [ ] **Step 3: Add the reader helper** in `api/app/api/autonomous.py` (after `_load_owned_session`, ~line 274). Add imports: `from app.api.dependencies import is_privileged_reader`, `from app.auditor_audit import auditor_audit`.

```python
async def _load_session_for_reader(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    user: User,
) -> tuple[AutonomousSession, bool]:
    """Load a session for a *reader*; return ``(session, was_privileged_cross_user)``.

    Owner → ``(session, False)``. Privileged reader (admin/auditor) non-owner
    → ``(session, True)``. Everyone else / missing → 404 indistinguishably
    (existence-safe), matching :func:`_load_owned_session`.
    """
    row = (
        await db.execute(
            select(AutonomousSession).where(AutonomousSession.id == session_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="autonomous session not found")
    if row.user_id == user.id:
        return row, False
    if is_privileged_reader(user):
        return row, True
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="autonomous session not found")
```

(Confirm `User` is imported in autonomous.py; add `from app.models.user import User` if not.)

- [ ] **Step 4: Wire `get_session_ledger`** — replace the ownership line at `autonomous.py:688` (`await _load_owned_session(db, session_id=session_id, user_id=user.id)`) with:

```python
    session, was_privileged = await _load_session_for_reader(db, session_id=session_id, user=user)
    if was_privileged:
        await auditor_audit(
            db, user=user, event="session_ledger_viewed",
            resource_type="autonomous_session", resource_id=str(session_id),
            viewed_user_id=session.user_id,
        )
        await db.commit()
```

Leave the rest (the `Chat` lookup by `autonomous_session_id`, the `resolve_ledger_entries`/`resolve_gates`, the no-ledger 404) unchanged.

- [ ] **Step 5: Run — expect PASS:**

Run: `cd api && python -m pytest tests/autonomous/test_session_ledger_endpoint.py -v`
Expected: PASS. Then `ruff format . && ruff check . && mypy app/api/autonomous.py`.

- [ ] **Step 6: Commit**

```bash
git add api/app/api/autonomous.py api/tests/autonomous/test_session_ledger_endpoint.py
git commit -s -m "feat(auditor): privileged cross-user read on autonomous session ledger

Refs Donna cross-user-auditor-role request"
```

---

## Task 5: Chat receipts (read + export) — extend bypass to auditor + audit

**Files:**
- Modify: `api/app/api/chat_receipts.py` (the `is_admin` gate @103, and the export variant's equivalent gate)
- Test: `api/tests/test_chat_receipts.py`

**Consumes:** `is_privileged_reader`, `auditor_audit`.

- [ ] **Step 1: Write failing tests** in `api/tests/test_chat_receipts.py` (near `test_receipts_admin_can_view_any_chat` @~213): an `auditor` reading another user's receipts → 200 **and** an `auditor.receipts_viewed` audit row; a `member` non-owner → 403 (unchanged) and no audit row; the same pair for the `export` variant asserting `auditor.receipts_exported`.

- [ ] **Step 2: Run — expect FAIL** (auditor → 403 today):

Run: `cd api && python -m pytest tests/test_chat_receipts.py -k "auditor" -v`
Expected: FAIL.

- [ ] **Step 3: Extend the bypass.** Add imports to `api/app/api/chat_receipts.py`: `from app.api.dependencies import is_privileged_reader` and `from app.auditor_audit import auditor_audit`. Replace the gate at lines 103-107:

```python
    is_priv = chat.owner_id != user.id and is_privileged_reader(user)
    if chat.owner_id != user.id and not is_privileged_reader(user):
        raise Forbidden(
            "You do not own this chat.",
            details={"chat_id": str(chat_id)},
        )
    if is_priv:
        await auditor_audit(
            db, user=user, event="receipts_viewed",
            resource_type="chat", resource_id=str(chat_id), viewed_user_id=chat.owner_id,
        )
        await db.commit()
```

- [ ] **Step 4: Apply the same change to the receipts `export` handler** in the same file (find its owner/`is_admin` gate — the export variant tested at `test_chat_receipts.py:359`) using `event="receipts_exported"`. Keep its existing non-privileged failure behavior unchanged; add the privileged bypass + audit + commit exactly as above.

- [ ] **Step 5: Run — expect PASS:**

Run: `cd api && python -m pytest tests/test_chat_receipts.py -v`
Expected: PASS (auditor bypass + audit; member still 403; export variant likewise). Then `ruff format . && ruff check . && mypy app/api/chat_receipts.py`.

- [ ] **Step 6: Commit**

```bash
git add api/app/api/chat_receipts.py api/tests/test_chat_receipts.py
git commit -s -m "feat(auditor): auditor joins admin bypass on chat receipts read + export

Refs Donna cross-user-auditor-role request"
```

---

## Task 6: OpenAPI role enum sync + Donna integration note

**Files:**
- Modify: `docs/api/backend-openapi.yaml` (add `auditor` to the role enum)
- Modify: `docs/integration/2026-07-01-donna-fiduciary-auditability-integration.md` (the contract note for Donna)
- Test: `api/tests/test_openapi.py`

- [ ] **Step 1: Add `auditor` to the role enum** in `docs/api/backend-openapi.yaml`. Search the file for the role enum (`enum:` list containing `admin`, `member`, `viewer` — likely on the admin `UpdateUserRole` request body and/or a `User` schema). Add `auditor` to every such enum list. Do NOT change any path count / add routes.

- [ ] **Step 2: Run the authoritative OpenAPI conformance check:**

Run: `cd api && python -m pytest tests/test_openapi.py -v`
Expected: PASS (no path-count change; the guard is unaffected — do not edit `EXPECTED_PATHS`).

- [ ] **Step 3: Add the contract note for Donna** to `docs/integration/2026-07-01-donna-fiduciary-auditability-integration.md` — a short subsection under §2.6 recording the delivered contract: the `auditor` role, granted via `PATCH /api/v1/admin/users/{id}/role`; the failure-mode matrix (owner 200 / privileged {admin,auditor} 200+audit / non-privileged 404 on ledger-sources-session, 403 on receipts); the `auditor.*` audit events; and that cross-user *listing* is out of scope (read by known id). If that integration doc is not present in the lq-ai repo (it's referenced from Donna's pin), instead add the same note to `docs/HONEST-STATE.md` or a new `docs/integration/` file and flag the location in the PR body.

- [ ] **Step 4: Full-suite gate + commit:**

Run: `cd api && python -m pytest -q` (or the standard api subset) and confirm no regressions; `ruff format . && ruff check .`.

```bash
git add docs/api/backend-openapi.yaml docs/integration/ docs/HONEST-STATE.md
git commit -s -m "docs(auditor): OpenAPI role enum + Donna integration contract note

Refs Donna cross-user-auditor-role request"
```

---

## Self-Review

**Spec coverage:**
- §4.1 role addition + migration + granting → Task 1. ✓
- §4.2 `is_privileged_reader` + reader helpers → Task 2 (predicate) + Tasks 3/4 (helpers) + Task 5 (receipts bypass). ✓
- §4.3 audit-the-auditor + read-path commit → Task 2 (wrapper) + Tasks 3/4/5 (call + `await db.commit()`). ✓
- §4.4 failure-mode matrix → tests in Tasks 3/4/5 assert every row of it (owner/privileged/non-privileged/nonexistent). ✓
- §5 testing (incl. the missing `/messages/{mid}/sources` cross-user test) → Task 3 Step 1. ✓
- §6 dev-env, OpenAPI, security-gating → Global Constraints + Task 6. ✓
- Non-goals (no listing, no scoping, no JWT, no 404/403 reconciliation) → honored: no task touches list endpoints, JWT, or non-privileged failure codes. ✓

**Placeholder scan:** every code step shows real code; migration, predicate, wrapper, helpers, and wiring blocks are complete. The only deferred lookups are explicit *verification* steps (0064's `revision` id; real fixture names in each test file) — flagged as steps, not hand-waves. ✓

**Type/name consistency:** `is_privileged_reader(user)`, `auditor_audit(db, *, user, event, resource_type, resource_id, viewed_user_id)`, `_load_chat_for_reader(...) -> (Chat, bool)`, `_load_session_for_reader(...) -> (AutonomousSession, bool)`, and the five `auditor.*` events are named identically across Tasks 2–6 and match the spec. `_MUTATING_ROLES` is asserted unchanged. ✓
