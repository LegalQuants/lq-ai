# M4-C2 Autonomous Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the SvelteKit web dashboard for the Autonomous Layer — opt-in gate, sessions+receipts+halt, memory review, precedent board + promote loop, schedule/watch config, and notifications — driving the complete `/autonomous/*` API.

**Architecture:** A new `Autonomous` top-tab opens a left-rail sub-app under `web/src/routes/lq-ai/autonomous/`, mirroring the existing `admin/*` multi-page pattern. A contained backend slice adds a per-user `autonomous_enabled` opt-in (a `users` column + preferences endpoint extension), enforces it (a router dependency on mutate endpoints + spawn-path guards), and adds per-entry timestamps to the receipt builder so the web layer can render an interleaved timeline. The web layer renders receipts; it does not run the loop (ADR 0013 D2).

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + Pydantic v2 (backend); SvelteKit (OpenWebUI fork, design-system `lq-*` primitives, no React, no ad-hoc Tailwind); pytest (backend), svelte-check + ESLint + Cypress (web).

**Design source:** `docs/LQVern/m4-c2-dashboard-design.md`. **Task spec:** `docs/M4-IMPLEMENTATION-PLAN.md` → Task M4-C2.

---

## Conventions (apply to every task)

- **Local test DB:** read `POSTGRES_PASSWORD` from repo-root `.env`, then:
  `cd api && DATABASE_URL="postgresql+asyncpg://lq_ai:<pw>@127.0.0.1:15432/lq_ai" ./.venv/bin/pytest <paths> -q` (conftest spins a throwaway DB — safe).
- **⚠️ NEVER run `alembic upgrade head` / `downgrade` directly against `127.0.0.1:15432/lq_ai`.** That host port maps to `lq-ai-postgres-1` — the **live dev DB shared with the running Docker stack**. Host-side alembic against it desyncs the running containers: if their image predates the migration, their startup `alembic upgrade head` then fails with "Can't locate revision …" and the api + arq-worker + ingest-worker crash-loop (→ login `ERR_CONNECTION_REFUSED` on `:8000`). Migration correctness is validated by **pytest only** (conftest builds + tears down its own throwaway DB). To run the new migration in the dev stack, **rebuild the api+arq-worker+ingest-worker trio together** (`docker compose build … && docker compose up -d …`) and let their entrypoint apply it. See [[feedback-no-host-alembic-on-dev-db]].
- **Backend gates:** `cd api && ./.venv/bin/ruff format . && ./.venv/bin/ruff check . && ./.venv/bin/mypy app` (run `ruff format` AND `ruff check` separately — CI runs both).
- **Web gates:** `cd web && npm run check` + `npm run lint`. ⚠️ `npm run check` (svelte-check) has a **large pre-existing baseline (~9359 errors)** in the inherited OpenWebUI-fork JS — it will never be zero. The gate is **no NEW errors attributable to the files this task adds/modifies** (grep the check output for your file paths; confirm none appear). Same for `npm run lint`.
- **Commits:** `git commit -s` (DCO) with trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. One commit per task (or per red→green cycle).
- **Push both remotes after each task:** `git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous`.
- **DELETE/204 pitfall (CLAUDE.md):** the autonomous API already returns 200-with-entity on DELETE — keep that; do not introduce a 204 `JSONResponse`.
- Branch: `feat/lqvern-m4-autonomous` (already checked out).

---

## File structure

**Backend (the opt-in slice):**
- Modify `api/app/models/user.py` — add `autonomous_enabled` column.
- Create `api/alembic/versions/0044_user_autonomous_enabled.py` — the migration.
- Modify `api/app/api/users.py` — extend preferences schema + GET + PATCH change-tracking.
- Modify `api/app/api/dependencies.py` — add `AutonomousEnabledUser` gate dependency.
- Modify `api/app/api/autonomous.py` — apply the gate to mutate endpoints (read+halt stay open).
- Modify `api/app/autonomous/watch_trigger.py` + `api/app/workers/autonomous_worker.py` — spawn-path guards (skip opted-out users).
- Modify `api/app/autonomous/receipt.py` — per-entry `at` timestamps.
- Modify `docs/api/backend-openapi.yaml` + `api/tests/test_openapi.py` — preferences field (no new paths).

**Web (the dashboard):**
- Create `web/src/lib/lq-ai/api/autonomous.ts` — api client; register in `web/src/lib/lq-ai/api/index.ts`.
- Modify `web/src/lib/lq-ai/types.ts` — `autonomous_enabled` on `Preferences` + autonomous entity types.
- Modify `web/src/lib/lq-ai/stores/preferences.ts` — default `autonomous_enabled: false`.
- Modify `web/src/lib/lq-ai/tabs.ts` — `autonomous` tab gated on opt-in.
- Create `web/src/routes/lq-ai/settings/autonomous/+page.svelte` — opt-in toggle + explainer; register in `web/src/routes/lq-ai/settings/+layout.svelte`.
- Create `web/src/routes/lq-ai/autonomous/+layout.svelte` — left rail + opt-in redirect guard.
- Create `web/src/routes/lq-ai/autonomous/+page.svelte` (sessions) + `sessions/[id]/+page.svelte` (receipt).
- Create `.../memory/`, `.../precedents/`, `.../proposals/`, `.../schedules/`, `.../watches/`, `.../notifications/` `+page.svelte`.
- Create pure helpers + vitest tests: `web/src/lib/lq-ai/autonomous/receipt-timeline.ts`, `cron.ts`, and per-page `page-helpers.ts` where logic warrants (mirror `playbook-executions/[id]/page-helpers.ts`).
- Create `web/cypress/e2e/m4-autonomous.cy.ts`.

---

# Phase 1 — Backend opt-in slice

### Task 1: `autonomous_enabled` column on the User model + migration

**Files:**
- Modify: `api/app/models/user.py` (after the `provenance_pills` column, ~line 76)
- Create: `api/alembic/versions/0044_user_autonomous_enabled.py`
- Test: `api/tests/models/test_user_autonomous_enabled.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/models/test_user_autonomous_enabled.py
"""autonomous_enabled column — defaults off, persists true (M4-C2 opt-in)."""
import pytest
from sqlalchemy import select
from app.models.user import User


@pytest.mark.asyncio
async def test_autonomous_enabled_defaults_false(db_session):
    user = User(email="optin@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    assert user.autonomous_enabled is False


@pytest.mark.asyncio
async def test_autonomous_enabled_persists_true(db_session):
    user = User(email="optin2@example.com", password_hash="x", autonomous_enabled=True)
    db_session.add(user)
    await db_session.flush()
    fetched = (
        await db_session.execute(select(User).where(User.email == "optin2@example.com"))
    ).scalar_one()
    assert fetched.autonomous_enabled is True
```

> Confirm the `db_session` fixture name + the `User` required kwargs (`password_hash` vs `hashed_password`) against an existing model test in `api/tests/models/` before running; match it exactly.

- [ ] **Step 2: Run test — verify it fails**

Run: `cd api && DATABASE_URL="postgresql+asyncpg://lq_ai:<pw>@127.0.0.1:15432/lq_ai" ./.venv/bin/pytest tests/models/test_user_autonomous_enabled.py -q`
Expected: FAIL — `AttributeError: ... 'autonomous_enabled'` / unknown column.

- [ ] **Step 3: Add the column**

In `api/app/models/user.py`, after the `provenance_pills` mapped_column:

```python
    # M4-C2 — Autonomous Layer per-user opt-in (PRD §3.10: off by default).
    # Gates the /autonomous/* mutate surface + the spawn paths
    # (watch_trigger, schedule sweep). Read+halt stay reachable when off.
    autonomous_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
```

Ensure `Boolean` is imported from `sqlalchemy` at the top of the file (add to the existing import if absent).

- [ ] **Step 4: Write the migration**

```python
# api/alembic/versions/0044_user_autonomous_enabled.py
"""user.autonomous_enabled — M4-C2 Autonomous Layer opt-in (off by default).

Revision ID: 0044
Revises: 0043
"""
from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "autonomous_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "autonomous_enabled")
```

> Verify `revision`/`down_revision` string style against `0043_autonomous_notifications_read_index.py` (some repos use full filenames as IDs) and match it.

- [ ] **Step 5: Run test — verify it passes** (conftest applies migrations to the throwaway DB)

Run: same pytest command as Step 2.
Expected: PASS (2 tests).

- [ ] **Step 6: Verify the migration round-trips — via the throwaway test DB ONLY**

The conftest-driven pytest in Step 5 already applies `0044` to its throwaway DB, which is the safe round-trip proof. **Do NOT** run `alembic upgrade head`/`downgrade` against `127.0.0.1:15432/lq_ai` (the live dev DB — see the ⚠️ in Conventions; doing so crash-loops the running stack). If you want an explicit up/down/up check, point alembic at a *scratch* database you create and drop yourself (e.g. `lq_ai_migtest`), never the dev DB.
Expected: pytest green ⇒ `0044` applies cleanly on a fresh DB.

- [ ] **Step 7: Gates + commit**

```bash
cd api && ./.venv/bin/ruff format . && ./.venv/bin/ruff check . && ./.venv/bin/mypy app
git add api/app/models/user.py api/alembic/versions/0044_user_autonomous_enabled.py api/tests/models/test_user_autonomous_enabled.py
git commit -s -m "feat(m4-c2): add users.autonomous_enabled opt-in column (off by default)"
```

> **Migration-rebuild note for deploy:** when `0044` ships to a running stack, rebuild api + arq-worker + ingest-worker together (the standing rule).

---

### Task 2: Expose `autonomous_enabled` through the preferences endpoint

**Files:**
- Modify: `api/app/api/users.py` (`UserPreferencesUpdate`, `UserPreferencesResponse`, `get_me_preferences`, `patch_me_preferences`)
- Test: `api/tests/api/test_users_preferences_autonomous.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/api/test_users_preferences_autonomous.py
"""autonomous_enabled rides the /users/me/preferences GET + PATCH."""
import pytest


@pytest.mark.asyncio
async def test_preferences_get_includes_autonomous_enabled(auth_client):
    resp = await auth_client.get("/api/v1/users/me/preferences")
    assert resp.status_code == 200
    assert resp.json()["autonomous_enabled"] is False  # default off


@pytest.mark.asyncio
async def test_preferences_patch_opt_in(auth_client):
    resp = await auth_client.patch(
        "/api/v1/users/me/preferences", json={"autonomous_enabled": True}
    )
    assert resp.status_code == 200
    assert resp.json()["autonomous_enabled"] is True
    # Read-back persists.
    again = await auth_client.get("/api/v1/users/me/preferences")
    assert again.json()["autonomous_enabled"] is True
```

> Match the authenticated-client fixture name to an existing `api/tests/api/` test (e.g. `auth_client` / `client`); copy its usage exactly.

- [ ] **Step 2: Run — verify it fails**

Run: `cd api && DATABASE_URL=... ./.venv/bin/pytest tests/api/test_users_preferences_autonomous.py -q`
Expected: FAIL — response has no `autonomous_enabled` key / PATCH ignores it.

- [ ] **Step 3: Extend the schemas + handlers**

In `api/app/api/users.py`:

`UserPreferencesUpdate` — add field:
```python
    autonomous_enabled: bool | None = None
```

`UserPreferencesResponse` — add field:
```python
    autonomous_enabled: bool
```

`get_me_preferences` return — add:
```python
        autonomous_enabled=getattr(user, "autonomous_enabled", False),
```

`patch_me_preferences` — add a change-tracking block alongside the existing ones (note: stringify the bool for the `changed` dict, which is typed `dict[str, dict[str, str]]`):
```python
    if payload.autonomous_enabled is not None:
        before = str(row.autonomous_enabled)
        after = str(payload.autonomous_enabled)
        if before != after:
            row.autonomous_enabled = payload.autonomous_enabled
            changed["autonomous_enabled"] = {"before": before, "after": after}
```

- [ ] **Step 4: Run — verify it passes**

Run: same as Step 2. Expected: PASS (2 tests).

- [ ] **Step 5: Gates + commit**

```bash
cd api && ./.venv/bin/ruff format . && ./.venv/bin/ruff check . && ./.venv/bin/mypy app
git add api/app/api/users.py api/tests/api/test_users_preferences_autonomous.py
git commit -s -m "feat(m4-c2): surface autonomous_enabled on /users/me/preferences"
```

---

### Task 3: `AutonomousEnabledUser` gate dependency on mutate endpoints

**Files:**
- Modify: `api/app/api/dependencies.py` (add `get_autonomous_enabled_user` + `AutonomousEnabledUser`)
- Modify: `api/app/api/autonomous.py` (swap `ActiveUser` → `AutonomousEnabledUser` on **mutate** endpoints only)
- Test: `api/tests/autonomous/test_optin_gate.py`

**Mutate endpoints to gate** (everything that creates/changes state): `keep_memory`, `dismiss_memory`, `delete_memory`, `dismiss_precedent`, `promote_precedent`, `accept_project_context_proposal`, `reject_project_context_proposal`, `create_schedule`, `update_schedule`, `delete_schedule`, `create_watch`, `update_watch`, `delete_watch`, `read_notification`.
**Leave on `ActiveUser` (reachable when opted out):** `halt_session`, `list_sessions`, `get_session`, `list_memory`, `list_precedents`, `list_project_context_proposals`, `list_schedules`, `list_watches`, `list_notifications`.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/autonomous/test_optin_gate.py
"""Opt-out keeps read+halt; mutate paths 403 (M4-C2 §2 opt-out split)."""
import pytest


@pytest.mark.asyncio
async def test_mutate_403_when_opted_out(auth_client):
    # default autonomous_enabled is False
    r = await auth_client.post(
        "/api/v1/autonomous/schedules",
        json={"cron_expr": "0 9 * * 1", "name": "scan"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_read_and_halt_reachable_when_opted_out(auth_client):
    # Reads stay open (200) even when opted out — audit trail must remain.
    r = await auth_client.get("/api/v1/autonomous/sessions")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_mutate_allowed_when_opted_in(auth_client):
    await auth_client.patch(
        "/api/v1/users/me/preferences", json={"autonomous_enabled": True}
    )
    r = await auth_client.post(
        "/api/v1/autonomous/schedules",
        json={"cron_expr": "0 9 * * 1", "name": "scan"},
    )
    assert r.status_code in (200, 201)
```

- [ ] **Step 2: Run — verify it fails**

Run: `cd api && DATABASE_URL=... ./.venv/bin/pytest tests/autonomous/test_optin_gate.py -q`
Expected: FAIL — schedule create returns 200/201 while opted out (no gate yet).

- [ ] **Step 3: Add the dependency**

In `api/app/api/dependencies.py`, after `get_active_user` / `ActiveUser`:

```python
async def get_autonomous_enabled_user(user: ActiveUser) -> User:
    """`ActiveUser` plus the per-user Autonomous Layer opt-in gate.

    The /autonomous/* mutate surface requires the user to have opted in
    (PRD §3.10, off by default). Read + halt endpoints intentionally stay
    on plain `ActiveUser` so a user who opts out never loses access to the
    audit trail of what already ran (M4-C2 §2 opt-out split).
    """
    if not getattr(user, "autonomous_enabled", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autonomous Layer is not enabled for this user.",
        )
    return user


AutonomousEnabledUser = Annotated[User, Depends(get_autonomous_enabled_user)]
```

Ensure `HTTPException` and `status` are imported in `dependencies.py` (add if absent).

- [ ] **Step 4: Apply the gate**

In `api/app/api/autonomous.py`, import it:
```python
from app.api.dependencies import ActiveUser, AutonomousEnabledUser
```
Then on each **mutate** endpoint listed above, change the parameter `user: ActiveUser` → `user: AutonomousEnabledUser`. Leave the read/halt endpoints on `ActiveUser`.

- [ ] **Step 5: Run — verify it passes**

Run: same as Step 2. Expected: PASS (3 tests).

- [ ] **Step 6: Run the full autonomous suite — no regressions**

Run: `cd api && DATABASE_URL=... ./.venv/bin/pytest tests/autonomous/ -q`
Expected: PASS (existing per-user-isolation tests still green; they create their own opted-in users — if any now 403, the test user needs `autonomous_enabled=True`; fix those fixtures).

> Existing autonomous tests that mutate will now need their user opted in. Grep `tests/autonomous/` for user-creation helpers and set `autonomous_enabled=True`, or flip it via the preferences PATCH in the fixture. This is expected fallout, not a bug.

- [ ] **Step 7: Gates + commit**

```bash
cd api && ./.venv/bin/ruff format . && ./.venv/bin/ruff check . && ./.venv/bin/mypy app
git add api/app/api/dependencies.py api/app/api/autonomous.py api/tests/
git commit -s -m "feat(m4-c2): gate /autonomous mutate endpoints on per-user opt-in (read+halt stay open)"
```

---

### Task 4: Spawn-path guards — skip opted-out users

**Files:**
- Modify: `api/app/autonomous/watch_trigger.py` (the `watches_stmt` select)
- Modify: `api/app/workers/autonomous_worker.py` (the schedule-sweep select, ~line 329)
- Test: `api/tests/autonomous/test_spawn_optin_guard.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/autonomous/test_spawn_optin_guard.py
"""Watches/schedules owned by opted-out users do not spawn sessions."""
import uuid
import pytest
from app.autonomous.watch_trigger import fire_watches_for_kb
from app.models.autonomous import AutonomousWatch


@pytest.mark.asyncio
async def test_watch_skips_opted_out_owner(db_session, make_user, make_kb):
    user = await make_user(autonomous_enabled=False)
    kb = await make_kb(user_id=user.id)
    db_session.add(
        AutonomousWatch(user_id=user.id, knowledge_base_id=kb.id, enabled=True)
    )
    await db_session.flush()
    spawned = await fire_watches_for_kb(
        db_session, kb_id=kb.id, file_id=uuid.uuid4(),
        enqueue=lambda _sid: _noop(),
    )
    assert spawned == 0


async def _noop() -> bool:
    return True
```

> Adapt `make_user` / `make_kb` to the actual fixtures used in `tests/autonomous/` (the watch tests from B4 already build a user + KB + watch — copy that setup). Add an opted-in counterpart asserting `spawned == 1`.

- [ ] **Step 2: Run — verify it fails**

Run: `cd api && DATABASE_URL=... ./.venv/bin/pytest tests/autonomous/test_spawn_optin_guard.py -q`
Expected: FAIL — `spawned == 1` (guard not yet applied).

- [ ] **Step 3: Add the guard to watch_trigger**

In `api/app/autonomous/watch_trigger.py`, join the owner and require opt-in:

```python
from app.models.user import User

    watches_stmt = (
        select(AutonomousWatch)
        .join(User, User.id == AutonomousWatch.user_id)
        .where(
            AutonomousWatch.knowledge_base_id == kb_id,
            AutonomousWatch.enabled.is_(True),
            AutonomousWatch.deleted_at.is_(None),
            User.autonomous_enabled.is_(True),
        )
    )
```

- [ ] **Step 4: Add the guard to the schedule sweep**

In `api/app/workers/autonomous_worker.py` (the `_run_schedule_sweep` select around line 329), add the same join + `User.autonomous_enabled.is_(True)` predicate.

- [ ] **Step 5: Run — verify it passes**

Run: same as Step 2 (plus the schedule-sweep equivalent test if added). Expected: PASS.

- [ ] **Step 6: Full suite + gates + commit**

```bash
cd api && DATABASE_URL=... ./.venv/bin/pytest tests/autonomous/ -q
cd api && ./.venv/bin/ruff format . && ./.venv/bin/ruff check . && ./.venv/bin/mypy app
git add api/app/autonomous/watch_trigger.py api/app/workers/autonomous_worker.py api/tests/
git commit -s -m "feat(m4-c2): spawn paths skip opted-out users (watch + schedule sweep)"
```

---

### Task 5: Per-entry timestamps in `build_receipt`

**Files:**
- Modify: `api/app/autonomous/receipt.py` (the phase-transition + tool-call assembly loop, ~lines 84–100)
- Test: `api/tests/autonomous/test_receipt.py` (extend existing) or new `test_receipt_timestamps.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/autonomous/test_receipt_timestamps.py
"""build_receipt carries per-entry ISO timestamps so the web layer can
interleave phase_transitions + tool_calls into one ordered timeline."""
import pytest
from app.autonomous.receipt import build_receipt


@pytest.mark.asyncio
async def test_receipt_entries_carry_timestamps(db_session, seeded_session_with_audit):
    # seeded_session_with_audit: a session with >=1 phase_transition and >=1
    # tool_call audit row (reuse the existing receipt-test seeding helper).
    receipt = await build_receipt(db_session, seeded_session_with_audit)
    assert all("at" in e and e["at"] for e in receipt["phase_transitions"])
    assert all("at" in e and e["at"] for e in receipt["tool_calls"])
```

> Reuse the seeding fixture/helper from the existing `tests/autonomous/test_receipt.py` (A4-i). If receipt tests live inline, extend that file instead of creating a new one.

- [ ] **Step 2: Run — verify it fails**

Run: `cd api && DATABASE_URL=... ./.venv/bin/pytest tests/autonomous/test_receipt_timestamps.py -q`
Expected: FAIL — entries have no `at` key.

- [ ] **Step 3: Add timestamps in the assembly loop**

In `api/app/autonomous/receipt.py`, in the loop over audit `rows`, include the row's `created_at` (ISO 8601) on each appended entry:

```python
        at = row.created_at.isoformat() if row.created_at is not None else None

        if suffix == "phase_transition":
            phase_transitions.append(
                {
                    "to_phase": details.get("to_phase"),
                    "at": at,
                }
            )
        elif suffix == "tool_call":
            entry: dict[str, Any] = {
                "tool": details.get("tool"),
                "outcome": details.get("outcome"),
                "at": at,
            }
            if "cost_usd" in details:
                entry["cost_usd"] = details["cost_usd"]
            tool_calls.append(entry)
```

(Preserve the existing fields; only add `"at"`.)

- [ ] **Step 4: Run — verify it passes**

Run: same as Step 2. Expected: PASS. Also re-run the existing receipt test to confirm no regression: `./.venv/bin/pytest tests/autonomous/test_receipt.py -q`.

- [ ] **Step 5: Gates + commit**

```bash
cd api && ./.venv/bin/ruff format . && ./.venv/bin/ruff check . && ./.venv/bin/mypy app
git add api/app/autonomous/receipt.py api/tests/autonomous/
git commit -s -m "feat(m4-c2): add per-entry timestamps to session receipt for timeline rendering"
```

---

### Task 6: OpenAPI conformance for the preferences change

**Files:**
- Modify: `docs/api/backend-openapi.yaml` (the `UserPreferencesResponse` + `UserPreferencesUpdate` schemas)
- Modify/verify: `api/tests/test_openapi.py`

- [ ] **Step 1: Update the OpenAPI sketch**

Add `autonomous_enabled` (`type: boolean`) to the `UserPreferencesResponse` (required) and `UserPreferencesUpdate` (optional) schemas in `docs/api/backend-openapi.yaml`. **No new paths** — `EXPECTED_PATHS`/the 113 count is unchanged.

- [ ] **Step 2: Run the conformance test**

Run: `cd api && DATABASE_URL=... ./.venv/bin/pytest tests/test_openapi.py -q`
Expected: PASS (path count still 113; the property-superset/conformance check passes with the new boolean field).

- [ ] **Step 3: Commit**

```bash
git add docs/api/backend-openapi.yaml api/tests/test_openapi.py
git commit -s -m "docs(m4-c2): declare autonomous_enabled in preferences OpenAPI schema"
```

---

# Phase 2 — Web foundation

### Task 7: `autonomous.ts` api client + entity types

**Files:**
- Create: `web/src/lib/lq-ai/api/autonomous.ts`
- Modify: `web/src/lib/lq-ai/api/index.ts` (barrel export)
- Test: `web/src/lib/lq-ai/api/__tests__/autonomous.test.ts`

- [ ] **Step 1: Write the client** (mirror `intakeBridges.ts` + `models.ts`; types match `api/app/schemas/autonomous.py`)

```typescript
// web/src/lib/lq-ai/api/autonomous.ts
/**
 * Autonomous Layer API client — M4-C2. Wraps /api/v1/autonomous/*.
 * Read + halt are reachable when opted out; mutate paths 403 (the server
 * gate). Types mirror app/schemas/autonomous.py.
 */
import { apiRequest } from './client';

export type SessionStatus = 'running' | 'paused' | 'completed' | 'halted' | 'failed';
export type TriggerKind = 'schedule' | 'watch' | 'manual';
export type MemoryState = 'proposed' | 'kept' | 'dismissed';

export interface SessionSummary {
	id: string;
	trigger_kind: TriggerKind;
	status: SessionStatus;
	current_phase: string | null;
	cost_total_usd: number;
	max_cost_usd: number | null;
	created_at: string;
}
export interface SessionListResponse { items: SessionSummary[]; total: number; }

export interface ReceiptPhase { to_phase: string | null; timestamp: string | null; }
export interface ReceiptToolCall {
	tool: string | null; outcome: string | null; timestamp: string | null; cost_usd?: number;
}
export interface SessionReceipt {
	session_id: string; trigger_kind: string; status: string | null;
	halt_state: string | null; current_phase: string | null;
	cost_total_usd: number; max_cost_usd: number | null; cost_cap_reached: boolean;
	phase_transitions: ReceiptPhase[]; tool_calls: ReceiptToolCall[];
	terminal_reason: string | null;
}

export interface MemoryEntry {
	id: string; category: string | null; content: string; state: MemoryState;
	created_at: string; kept_at: string | null;
}
export interface PrecedentEntry {
	id: string; pattern: string; dismissed: boolean; created_at: string;
}
export interface ContextProposal {
	id: string; project_id: string; precedent_id: string | null;
	content: string; status: string; created_at: string;
}
export interface Schedule {
	id: string; name: string | null; cron_expr: string;
	playbook_id: string | null; skill_ref: string | null;
	target_kb_id: string | null; project_id: string | null;
	enabled: boolean; next_run_at: string | null;
}
export interface Watch {
	id: string; knowledge_base_id: string;
	playbook_id: string | null; skill_ref: string | null;
	project_id: string | null; enabled: boolean;
}
export interface Notification {
	id: string; title: string; body: string; read_at: string | null; created_at: string;
}

// --- sessions (read + halt) ---
export const listSessions = (limit = 50, offset = 0) =>
	apiRequest<SessionListResponse>(`/autonomous/sessions?limit=${limit}&offset=${offset}`);
export const getSession = (id: string) =>
	apiRequest<SessionReceipt>(`/autonomous/sessions/${id}`);
export const haltSession = (id: string) =>
	apiRequest<unknown>(`/autonomous/sessions/${id}/halt`, { method: 'POST' });

// --- memory ---
export const listMemory = (state?: MemoryState) =>
	apiRequest<{ items: MemoryEntry[] }>(`/autonomous/memory${state ? `?state=${state}` : ''}`);
export const keepMemory = (id: string, content?: string) =>
	apiRequest<MemoryEntry>(`/autonomous/memory/${id}/keep`, {
		method: 'POST', body: content !== undefined ? { content } : undefined,
	});
export const dismissMemory = (id: string) =>
	apiRequest<MemoryEntry>(`/autonomous/memory/${id}/dismiss`, { method: 'POST' });
export const deleteMemory = (id: string) =>
	apiRequest<MemoryEntry>(`/autonomous/memory/${id}`, { method: 'DELETE' });

// --- precedents + proposals ---
export const listPrecedents = () =>
	apiRequest<{ items: PrecedentEntry[] }>(`/autonomous/precedents`);
export const dismissPrecedent = (id: string) =>
	apiRequest<PrecedentEntry>(`/autonomous/precedents/${id}/dismiss`, { method: 'POST' });
export const promotePrecedent = (id: string, projectId: string) =>
	apiRequest<ContextProposal>(`/autonomous/precedents/${id}/promote`, {
		method: 'POST', body: { project_id: projectId },
	});
export const listProposals = () =>
	apiRequest<{ items: ContextProposal[] }>(`/autonomous/project-context-proposals`);
export const acceptProposal = (id: string) =>
	apiRequest<ContextProposal>(`/autonomous/project-context-proposals/${id}/accept`, { method: 'POST' });
export const rejectProposal = (id: string) =>
	apiRequest<ContextProposal>(`/autonomous/project-context-proposals/${id}/reject`, { method: 'POST' });

// --- schedules ---
export const listSchedules = () => apiRequest<{ items: Schedule[] }>(`/autonomous/schedules`);
export const createSchedule = (body: Partial<Schedule>) =>
	apiRequest<Schedule>(`/autonomous/schedules`, { method: 'POST', body });
export const updateSchedule = (id: string, body: Partial<Schedule>) =>
	apiRequest<Schedule>(`/autonomous/schedules/${id}`, { method: 'PATCH', body });
export const deleteSchedule = (id: string) =>
	apiRequest<Schedule>(`/autonomous/schedules/${id}`, { method: 'DELETE' });

// --- watches ---
export const listWatches = () => apiRequest<{ items: Watch[] }>(`/autonomous/watches`);
export const createWatch = (body: Partial<Watch>) =>
	apiRequest<Watch>(`/autonomous/watches`, { method: 'POST', body });
export const updateWatch = (id: string, body: Partial<Watch>) =>
	apiRequest<Watch>(`/autonomous/watches/${id}`, { method: 'PATCH', body });
export const deleteWatch = (id: string) =>
	apiRequest<Watch>(`/autonomous/watches/${id}`, { method: 'DELETE' });

// --- notifications ---
export const listNotifications = (unreadOnly = false) =>
	apiRequest<{ items: Notification[] }>(`/autonomous/notifications${unreadOnly ? '?unread=true' : ''}`);
export const readNotification = (id: string) =>
	apiRequest<Notification>(`/autonomous/notifications/${id}/read`, { method: 'POST' });
```

> **Verify each path + response shape against `api/app/api/autonomous.py` and `docs/api/backend-openapi.yaml` before relying on it** — confirm the list-envelope key (`items` vs `sessions`), the exact field names on each `*Read` schema, and the promote/keep request body shapes. Adjust the interfaces to match reality; do not guess.

- [ ] **Step 2: Register the barrel export**

In `web/src/lib/lq-ai/api/index.ts` add:
```typescript
export * as autonomousApi from './autonomous';
```

- [ ] **Step 3: Write a smoke test for URL construction** (mirror an existing `__tests__/*.test.ts`)

```typescript
// web/src/lib/lq-ai/api/__tests__/autonomous.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as client from '../client';
import * as autonomous from '../autonomous';

describe('autonomous api client', () => {
	beforeEach(() => vi.restoreAllMocks());
	it('lists memory filtered by state', async () => {
		const spy = vi.spyOn(client, 'apiRequest').mockResolvedValue({ items: [] } as never);
		await autonomous.listMemory('proposed');
		expect(spy).toHaveBeenCalledWith('/autonomous/memory?state=proposed');
	});
	it('keeps memory with edited content', async () => {
		const spy = vi.spyOn(client, 'apiRequest').mockResolvedValue({} as never);
		await autonomous.keepMemory('abc', 'edited');
		expect(spy).toHaveBeenCalledWith('/autonomous/memory/abc/keep', {
			method: 'POST', body: { content: 'edited' },
		});
	});
});
```

- [ ] **Step 4: Run web unit tests + gates**

Run: `cd web && npx vitest run src/lib/lq-ai/api/__tests__/autonomous.test.ts && npm run check`
Expected: tests PASS, svelte-check clean.

> Confirm the vitest invocation matches the repo (`package.json` "test" script / existing `__tests__` runner). If the repo uses a different runner, match it.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/lq-ai/api/autonomous.ts web/src/lib/lq-ai/api/index.ts web/src/lib/lq-ai/api/__tests__/autonomous.test.ts
git commit -s -m "feat(m4-c2): autonomous.ts api client + entity types"
```

---

### Task 8: Opt-in in the preferences store + Settings → Autonomous page

**Files:**
- Modify: `web/src/lib/lq-ai/types.ts` (`Preferences` + `User`)
- Modify: `web/src/lib/lq-ai/stores/preferences.ts` (`defaultPreferences`)
- Create: `web/src/routes/lq-ai/settings/autonomous/+page.svelte`
- Modify: `web/src/routes/lq-ai/settings/+layout.svelte` (add the nav link)

- [ ] **Step 1: Extend the types**

In `web/src/lib/lq-ai/types.ts`, add to `Preferences`:
```typescript
	autonomous_enabled: boolean;
```
and to `User` (optional, mirroring the other prefs):
```typescript
	autonomous_enabled?: boolean;
```

- [ ] **Step 2: Default it off in the store**

In `web/src/lib/lq-ai/stores/preferences.ts`, add to `defaultPreferences`:
```typescript
	autonomous_enabled: false
```

- [ ] **Step 3: Build the Settings → Autonomous page** (toggle + explainer; reuse the `setPreference` store action)

```svelte
<!-- web/src/routes/lq-ai/settings/autonomous/+page.svelte -->
<script lang="ts">
	import { onMount } from 'svelte';
	import { preferences, setPreference, initPreferences } from '$lib/lq-ai/stores/preferences';

	onMount(initPreferences);

	function toggle(): void {
		setPreference('autonomous_enabled', !$preferences.autonomous_enabled);
	}
</script>

<h2 class="lq-text-panel-h" style="margin-bottom: var(--lq-space-4);">Autonomous Layer</h2>
<p class="lq-text-body" style="color: var(--lq-text-secondary); margin-bottom: var(--lq-space-6);">
	When enabled, LQ.AI can run background agents that watch your knowledge bases,
	run scheduled scans, propose memory about your preferences, and surface
	cross-matter precedents — always under hard cost, halt, and per-phase tool
	limits, and always producing an inspectable receipt of what it did. Off by
	default. Turning it off stops new runs; you keep access to past receipts and
	can still halt anything running.
</p>

<label class="lq-toggle-row">
	<input type="checkbox" checked={$preferences.autonomous_enabled} on:change={toggle} />
	<span class="lq-text-label">Enable the Autonomous Layer for my account</span>
</label>
```

> Match the toggle markup/classes to whatever `SettingsToggleGroup` or an existing checkbox in `settings/appearance` uses; reuse the design-system primitive rather than inventing `lq-toggle-row` if a class exists.

- [ ] **Step 4: Add the nav link** in `web/src/routes/lq-ai/settings/+layout.svelte` (mirror how `account` / `appearance` links are listed): add a link to `/lq-ai/settings/autonomous` labelled "Autonomous".

- [ ] **Step 5: Gates**

Run: `cd web && npm run check && npm run lint`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/lq-ai/types.ts web/src/lib/lq-ai/stores/preferences.ts web/src/routes/lq-ai/settings/
git commit -s -m "feat(m4-c2): autonomous opt-in toggle in Settings + preferences store"
```

---

### Task 9: Autonomous top-tab + route layout (rail + opt-in redirect guard)

**Files:**
- Modify: `web/src/lib/lq-ai/tabs.ts` (add `autonomous` TabId + entry + opt-in-aware visibility)
- Create: `web/src/routes/lq-ai/autonomous/+layout.svelte` (left rail + redirect guard)
- Test: `web/src/lib/lq-ai/__tests__/tabs.test.ts` (extend if present, else create)

- [ ] **Step 1: Write the failing visibility test**

```typescript
// web/src/lib/lq-ai/__tests__/tabs.test.ts
import { describe, it, expect } from 'vitest';
import { isTabVisible } from '../tabs';

const base = { id: '1', email: 'a@b.c', is_admin: false, must_change_password: false };

describe('autonomous tab opt-in gating', () => {
	it('hidden when not opted in', () => {
		expect(isTabVisible('autonomous', { ...base }, { autonomousEnabled: false })).toBe(false);
	});
	it('visible when opted in', () => {
		expect(isTabVisible('autonomous', { ...base }, { autonomousEnabled: true })).toBe(true);
	});
});
```

- [ ] **Step 2: Run — verify it fails**

Run: `cd web && npx vitest run src/lib/lq-ai/__tests__/tabs.test.ts`
Expected: FAIL — `isTabVisible` takes 2 args / `'autonomous'` not a TabId.

- [ ] **Step 3: Extend tabs.ts**

- Add `'autonomous'` to the `TabId` union.
- Add to `TABS` (before `admin`):
  ```typescript
  { id: 'autonomous', label: 'Autonomous', icon: '🤖', route: '/lq-ai/autonomous', available: true },
  ```
- Add an optional opts param + a `requiresAutonomous` marker:
  ```typescript
  export interface TabVisibilityOpts { autonomousEnabled?: boolean; }

  export function isTabVisible(
    id: TabId, user: User | null, opts: TabVisibilityOpts = {}
  ): boolean {
    const tab = TABS.find((t) => t.id === id);
    if (!tab) return false;
    if (id === 'autonomous') return opts.autonomousEnabled === true;
    if (tab.adminOnly) return user?.role === 'admin' || user?.is_admin === true;
    return true;
  }
  ```
- Update `visibleTabsFor` in `TopTabBar.svelte` to pass `{ autonomousEnabled: $preferences.autonomous_enabled }` (import the `preferences` store there). Where `visibleTabsFor(user)` is called, thread the opt-in flag.

- [ ] **Step 4: Run — verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 5: Build the route layout (rail + redirect guard)**

```svelte
<!-- web/src/routes/lq-ai/autonomous/+layout.svelte -->
<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { preferences, initPreferences } from '$lib/lq-ai/stores/preferences';

	const RAIL = [
		{ href: '/lq-ai/autonomous', label: 'Sessions', exact: true },
		{ href: '/lq-ai/autonomous/memory', label: 'Memory' },
		{ href: '/lq-ai/autonomous/precedents', label: 'Precedents' },
		{ href: '/lq-ai/autonomous/proposals', label: 'Proposals' },
		{ href: '/lq-ai/autonomous/schedules', label: 'Schedules' },
		{ href: '/lq-ai/autonomous/watches', label: 'Watches' },
		{ href: '/lq-ai/autonomous/notifications', label: 'Notifications' }
	];

	onMount(async () => {
		await initPreferences();
		if (!$preferences.autonomous_enabled) {
			goto('/lq-ai/settings/autonomous');
		}
	});

	$: pathname = $page.url.pathname;
	function active(href: string, exact?: boolean): boolean {
		return exact ? pathname === href : pathname === href || pathname.startsWith(href + '/');
	}
</script>

{#if $preferences.autonomous_enabled}
	<div class="lq-autonomous-shell" style="display:flex; gap: var(--lq-space-5);">
		<nav class="lq-subnav" aria-label="Autonomous">
			{#each RAIL as item}
				<a href={item.href} class="lq-subnav-link" class:lq-subnav-link--active={active(item.href, item.exact)}>
					{item.label}
				</a>
			{/each}
		</nav>
		<section style="flex:1; min-width:0;">
			<slot />
		</section>
	</div>
{/if}
```

> Match the rail markup/classes to the `admin/*` layout's sub-nav (look at `web/src/routes/lq-ai/admin/+layout.svelte` if present) so styling is consistent. Reuse its classes rather than introducing new ones.

- [ ] **Step 6: Gates**

Run: `cd web && npm run check && npm run lint`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/lq-ai/tabs.ts web/src/lib/lq-ai/components/TopTabBar.svelte web/src/routes/lq-ai/autonomous/+layout.svelte web/src/lib/lq-ai/__tests__/tabs.test.ts
git commit -s -m "feat(m4-c2): Autonomous top-tab (opt-in gated) + rail layout with redirect guard"
```

---

# Phase 3 — Surfaces

> Each surface page mirrors `web/src/routes/lq-ai/admin/intake-bridges/+page.svelte`: `onMount(load)`, a `load()` that calls the api client and sets `list` / `loading` / `listError`, action functions that confirm-then-call-then-reload, and `actionError` / `actionSuccess` banners. Use `LQAIApiError` for typed 403 handling. Use `lq-*` design-system classes throughout. Extract any non-trivial pure logic into a sibling `page-helpers.ts` with a vitest test (mirror `playbook-executions/[id]/page-helpers.ts`).

### Task 10: Sessions list (+ inline Halt)

**Files:**
- Create: `web/src/routes/lq-ai/autonomous/+page.svelte`
- Create: `web/src/routes/lq-ai/autonomous/page-helpers.ts` + `__tests__/page-helpers.test.ts`

- [ ] **Step 1: Write the helper + failing test** (status→pill-class + cost formatting)

```typescript
// web/src/routes/lq-ai/autonomous/page-helpers.ts
import type { SessionStatus } from '$lib/lq-ai/api/autonomous';

export function statusPillClass(status: SessionStatus): string {
	switch (status) {
		case 'running': return 'lq-pill lq-pill--info';
		case 'completed': return 'lq-pill lq-pill--success';
		case 'halted': return 'lq-pill lq-pill--warn';
		case 'failed': return 'lq-pill lq-pill--danger';
		default: return 'lq-pill';
	}
}
// NOTE: SessionSummary.cost_total_usd / max_cost_usd arrive as STRINGS
// (Pydantic Decimal→string in JSON), unlike the receipt's number fields —
// coerce with Number() before formatting.
export function formatCost(total: string | number, cap: string | number | null): string {
	const t = `$${Number(total).toFixed(2)}`;
	return cap != null ? `${t} / $${Number(cap).toFixed(2)}` : t;
}
export function isHaltable(status: SessionStatus): boolean {
	return status === 'running' || status === 'paused';
}
```

```typescript
// web/src/routes/lq-ai/autonomous/__tests__/page-helpers.test.ts
import { describe, it, expect } from 'vitest';
import { statusPillClass, formatCost, isHaltable } from '../page-helpers';

describe('sessions helpers', () => {
	it('maps status to pill', () => expect(statusPillClass('running')).toContain('info'));
	it('formats cost with cap', () => expect(formatCost(0.1, 0.5)).toBe('$0.10 / $0.50'));
	it('formats cost without cap', () => expect(formatCost(0.1, null)).toBe('$0.10'));
	it('haltable only while active', () => {
		expect(isHaltable('running')).toBe(true);
		expect(isHaltable('completed')).toBe(false);
	});
});
```

- [ ] **Step 2: Run — verify it fails, then passes** once the helper exists.

Run: `cd web && npx vitest run src/routes/lq-ai/autonomous/__tests__/page-helpers.test.ts`

- [ ] **Step 3: Build the page** — `onMount` → `autonomousApi.listSessions()`; render newest-first rows: status pill, trigger, phase, `formatCost`, created_at; each row links to `/lq-ai/autonomous/sessions/{id}`; rows where `isHaltable` show a **Halt** button that `confirm()`s then calls `autonomousApi.haltSession(id)` and reloads. Use the intake-bridges page as the structural template (loading/error/success banners).

- [ ] **Step 4: Gates + commit**

```bash
cd web && npm run check && npm run lint && npx vitest run src/routes/lq-ai/autonomous/__tests__/page-helpers.test.ts
git add web/src/routes/lq-ai/autonomous/+page.svelte web/src/routes/lq-ai/autonomous/page-helpers.ts web/src/routes/lq-ai/autonomous/__tests__/
git commit -s -m "feat(m4-c2): autonomous sessions list with inline halt"
```

---

### Task 11: Receipt view — chronological interleaved timeline

**Files:**
- Create: `web/src/routes/lq-ai/autonomous/sessions/[id]/+page.svelte`
- Create: `web/src/lib/lq-ai/autonomous/receipt-timeline.ts` + `__tests__/receipt-timeline.test.ts`

- [ ] **Step 1: Write the merge helper + failing test** (interleave phases + tool calls by `at`)

```typescript
// web/src/lib/lq-ai/autonomous/receipt-timeline.ts
import type { SessionReceipt, ReceiptPhase, ReceiptToolCall } from '$lib/lq-ai/api/autonomous';

export type TimelineNode =
	| { kind: 'phase'; at: string | null; phase: string | null }
	| { kind: 'tool'; at: string | null; tool: string | null; outcome: string | null; cost_usd?: number };

/** Merge phase_transitions + tool_calls into one ascending-time thread.
 *  Entries without a timestamp keep their relative order, appended stably. */
export function buildTimeline(receipt: SessionReceipt): TimelineNode[] {
	const phases: TimelineNode[] = receipt.phase_transitions.map((p: ReceiptPhase) => ({
		kind: 'phase', at: p.timestamp, phase: p.to_phase
	}));
	const tools: TimelineNode[] = receipt.tool_calls.map((t: ReceiptToolCall) => ({
		kind: 'tool', at: t.timestamp, tool: t.tool, outcome: t.outcome, cost_usd: t.cost_usd
	}));
	return [...phases, ...tools].sort((a, b) => {
		if (a.at == null) return 1;
		if (b.at == null) return -1;
		return a.at < b.at ? -1 : a.at > b.at ? 1 : 0;
	});
}
```

```typescript
// web/src/lib/lq-ai/autonomous/__tests__/receipt-timeline.test.ts
import { describe, it, expect } from 'vitest';
import { buildTimeline } from '../receipt-timeline';

it('interleaves phases and tool calls by timestamp', () => {
	const r = {
		phase_transitions: [
			{ to_phase: 'intake', timestamp: '2026-05-25T10:00:00Z' },
			{ to_phase: 'analysis', timestamp: '2026-05-25T10:00:02Z' }
		],
		tool_calls: [
			{ tool: 'retrieve_chunks', outcome: 'success', timestamp: '2026-05-25T10:00:01Z' },
			{ tool: 'run_skill', outcome: 'success', timestamp: '2026-05-25T10:00:03Z' }
		]
	} as never;
	const t = buildTimeline(r);
	expect(t.map((n) => n.at)).toEqual([
		'2026-05-25T10:00:00Z', '2026-05-25T10:00:01Z',
		'2026-05-25T10:00:02Z', '2026-05-25T10:00:03Z'
	]);
});
```

- [ ] **Step 2: Run — fails then passes** once the helper exists.

- [ ] **Step 3: Build the receipt page** — `onMount` → `getSession(params.id)`; header shows status, phase, `cost_total/cap`, `cost_cap_reached`, `terminal_reason`; if `isHaltable(status)` show a Halt button (confirm → `haltSession` → reload). Render `buildTimeline(receipt)` as a vertical timeline: `phase` nodes are markers, `tool` nodes expand (`<details>`) to show tool, outcome, `cost_usd`. The terminal reason is the final node. Never render raw values — only the safe scalar fields the receipt carries.

- [ ] **Step 4: Gates + commit**

```bash
cd web && npm run check && npm run lint && npx vitest run src/lib/lq-ai/autonomous/__tests__/receipt-timeline.test.ts
git add web/src/routes/lq-ai/autonomous/sessions/ web/src/lib/lq-ai/autonomous/receipt-timeline.ts web/src/lib/lq-ai/autonomous/__tests__/
git commit -s -m "feat(m4-c2): session receipt view as a chronological timeline"
```

---

### Task 12: Memory review (state tabs + keep/edit/dismiss/delete)

**Files:**
- Create: `web/src/routes/lq-ai/autonomous/memory/+page.svelte`

- [ ] **Step 1: Build the page** — a state-tab bar (Proposed / Kept / Dismissed) driving `listMemory(state)` (default `'proposed'`). Proposed rows: `Keep` (`keepMemory(id)`), `Edit & keep` (reveal inline `<textarea>` → `keepMemory(id, edited)`), `Dismiss` (`dismissMemory(id)`). Kept rows: `Edit` (textarea → `keepMemory(id, edited)`), `Delete` (`deleteMemory(id)` with confirm). Reload after each action. Intake-bridges structural template.

- [ ] **Step 2: Gates + commit**

```bash
cd web && npm run check && npm run lint
git add web/src/routes/lq-ai/autonomous/memory/
git commit -s -m "feat(m4-c2): memory review surface (state tabs + keep/edit/dismiss/delete)"
```

---

### Task 13: Precedent board (read + dismiss + promote)

**Files:**
- Create: `web/src/routes/lq-ai/autonomous/precedents/+page.svelte`

- [ ] **Step 1: Build the page** — `listPrecedents()`; each entry shows the pattern text + `Dismiss` (`dismissPrecedent(id)`, confirm) + **Promote** (opens a small project picker — reuse the projects list from `projectsApi`; on select → `promotePrecedent(id, projectId)`; toast "Proposal created — review under Proposals", link to `/lq-ai/autonomous/proposals`). Reload after dismiss.

- [ ] **Step 2: Gates + commit**

```bash
cd web && npm run check && npm run lint
git add web/src/routes/lq-ai/autonomous/precedents/
git commit -s -m "feat(m4-c2): precedent board (dismiss + promote to project)"
```

---

### Task 14: Proposals (accept / reject)

**Files:**
- Create: `web/src/routes/lq-ai/autonomous/proposals/+page.svelte`

- [ ] **Step 1: Build the page** — `listProposals()`; each pending proposal shows the proposed context text + target project + `Accept` (`acceptProposal(id)`, toast linking to the matter) / `Reject` (`rejectProposal(id)`, confirm). Reload after each.

- [ ] **Step 2: Gates + commit**

```bash
cd web && npm run check && npm run lint
git add web/src/routes/lq-ai/autonomous/proposals/
git commit -s -m "feat(m4-c2): project-context proposal review (accept/reject)"
```

---

### Task 15: Schedules (list + create modal + cron input)

**Files:**
- Create: `web/src/routes/lq-ai/autonomous/schedules/+page.svelte`
- Create: `web/src/lib/lq-ai/autonomous/cron.ts` + `__tests__/cron.test.ts`
- Create: `web/src/lib/lq-ai/components/CronInput.svelte` (preset + custom + next-run preview)

- [ ] **Step 1: Write the cron helper + failing test** (preset→cron compile + client-side next-run preview, no new dep)

```typescript
// web/src/lib/lq-ai/autonomous/cron.ts
export type Preset = 'daily' | 'weekly' | 'monthly' | 'custom';

/** Compile a preset + params into a 5-field cron. */
export function presetToCron(p: Preset, opts: { hour: number; minute: number; dow?: number; dom?: number }): string {
	const { hour, minute, dow = 1, dom = 1 } = opts;
	switch (p) {
		case 'daily': return `${minute} ${hour} * * *`;
		case 'weekly': return `${minute} ${hour} * * ${dow}`;
		case 'monthly': return `${minute} ${hour} ${dom} * *`;
		case 'custom': return '';
	}
}

/** Compute the next run after `from` for a standard 5-field cron.
 *  Supports `*`, single values, and comma lists per field (enough for the
 *  presets + common custom exprs); returns null if no match within ~366 days. */
export function nextRun(cron: string, from: Date = new Date()): Date | null {
	const parts = cron.trim().split(/\s+/);
	if (parts.length !== 5) return null;
	const [min, hr, dom, mon, dow] = parts;
	const match = (field: string, value: number): boolean =>
		field === '*' || field.split(',').some((v) => Number(v) === value);
	const d = new Date(from.getTime());
	d.setSeconds(0, 0);
	d.setMinutes(d.getMinutes() + 1);
	for (let i = 0; i < 366 * 24 * 60; i++) {
		if (
			match(min, d.getMinutes()) && match(hr, d.getHours()) &&
			match(dom, d.getDate()) && match(mon, d.getMonth() + 1) &&
			match(dow, d.getDay())
		) return new Date(d.getTime());
		d.setMinutes(d.getMinutes() + 1);
	}
	return null;
}
```

```typescript
// web/src/lib/lq-ai/autonomous/__tests__/cron.test.ts
import { describe, it, expect } from 'vitest';
import { presetToCron, nextRun } from '../cron';

describe('cron', () => {
	it('compiles weekly preset', () =>
		expect(presetToCron('weekly', { hour: 9, minute: 0, dow: 1 })).toBe('0 9 * * 1'));
	it('finds next Monday 09:00', () => {
		const from = new Date('2026-05-25T08:00:00'); // Mon
		expect(nextRun('0 9 * * 1', from)?.getHours()).toBe(9);
	});
	it('returns null for malformed cron', () => expect(nextRun('bad', new Date())).toBeNull());
});
```

- [ ] **Step 2: Run — fails then passes** once `cron.ts` exists.

Run: `cd web && npx vitest run src/lib/lq-ai/autonomous/__tests__/cron.test.ts`

- [ ] **Step 3: Build `CronInput.svelte`** — a frequency `<select>` (Daily/Weekly/Monthly/Custom) + hour/minute (+ day-of-week for weekly, day-of-month for monthly); Custom reveals a raw `<input>`. Emits the compiled cron via a bound prop / `on:change`. Shows a live preview line: `nextRun(cron)` formatted, or "Invalid expression" when `nextRun` returns null. (Server-side 422 on submit is the source of truth; this preview is advisory.)

- [ ] **Step 4: Build the schedules page** — `listSchedules()` rows with enable/disable toggle (`updateSchedule(id, { enabled })`) + soft-delete (`deleteSchedule(id)`, confirm). A **New schedule** button opens a modal (mirror `NewMatterModal`): name, `CronInput`, target picker (playbook via playbooks list OR skill via `SkillPicker`), optional KB (`target_kb_id`) + project; submit → `createSchedule(body)`; surface the API 422 inline on the cron field. Reload after actions.

- [ ] **Step 5: Gates + commit**

```bash
cd web && npm run check && npm run lint && npx vitest run src/lib/lq-ai/autonomous/__tests__/cron.test.ts
git add web/src/routes/lq-ai/autonomous/schedules/ web/src/lib/lq-ai/autonomous/cron.ts web/src/lib/lq-ai/autonomous/__tests__/cron.test.ts web/src/lib/lq-ai/components/CronInput.svelte
git commit -s -m "feat(m4-c2): schedules surface + cron input with client-side next-run preview"
```

---

### Task 16: Watches (list + create modal)

**Files:**
- Create: `web/src/routes/lq-ai/autonomous/watches/+page.svelte`

- [ ] **Step 1: Build the page** — `listWatches()` rows with enable/disable toggle (`updateWatch(id, { enabled })`) + soft-delete (`deleteWatch(id)`, confirm). **New watch** modal: required KB picker (`knowledge_base_id`, reuse the KB picker from `knowledgeBasesApi` / `AttachKBModal` pattern), target picker (playbook/skill), optional project; submit → `createWatch(body)`. No cron. Reload after actions.

- [ ] **Step 2: Gates + commit**

```bash
cd web && npm run check && npm run lint
git add web/src/routes/lq-ai/autonomous/watches/
git commit -s -m "feat(m4-c2): watches surface (KB-trigger config)"
```

---

### Task 17: Notifications (rail page + unread badge)

**Files:**
- Create: `web/src/routes/lq-ai/autonomous/notifications/+page.svelte`
- Modify: `web/src/routes/lq-ai/autonomous/+layout.svelte` (unread count badge on the rail item)

- [ ] **Step 1: Build the page** — `listNotifications()`; each row shows title/body/created_at, unread rows visually distinct; click → `readNotification(id)` then reload; a **Mark all read** button iterates unread ids. 

- [ ] **Step 2: Add the unread badge** — in `+layout.svelte`, on mount also call `listNotifications(true)` and show the count as a badge on the Notifications rail link (and optionally the tab). Refresh after the notifications page marks items read (e.g., re-fetch on navigation).

- [ ] **Step 3: Gates + commit**

```bash
cd web && npm run check && npm run lint
git add web/src/routes/lq-ai/autonomous/notifications/ web/src/routes/lq-ai/autonomous/+layout.svelte
git commit -s -m "feat(m4-c2): notifications rail page + unread badge"
```

---

# Phase 4 — E2E, deferrals, final verification

### Task 18: Cypress E2E

**Files:**
- Create: `web/cypress/e2e/m4-autonomous.cy.ts`

- [ ] **Step 1: Write the E2E** (mirror `web/cypress/e2e/m3-c-tabular-review.cy.ts` for login/setup helpers)

Cover the spec's flow:
1. Log in; navigate to Settings → Autonomous; assert the Autonomous tab is **absent** pre-opt-in; toggle opt-in on; assert the Autonomous tab now appears.
2. Visit `/lq-ai/autonomous`; if a seeded session exists, open its receipt and assert the timeline renders phases + tool calls + terminal state; click Halt on a running session and assert the confirm + state change.
3. Memory: open the Proposed tab, Keep an entry, assert it moves to Kept.
4. Precedents: Dismiss an entry, assert it leaves the active list.
5. (Negative) toggle opt-in **off**; assert the tab disappears and visiting `/lq-ai/autonomous` redirects to Settings → Autonomous, but `/lq-ai/autonomous` session reads / halt remain reachable per the gate (or assert redirect — match the implemented guard).

> Seed data: reuse the backend test-seeding approach the other Cypress specs use (API calls in `before()`), or assert gracefully on empty states where seeding a real autonomous session isn't feasible in E2E. Keep the opt-in→tab-visibility and memory-keep / precedent-dismiss assertions as the hard gates.

- [ ] **Step 2: Run against a running stack**

Run: `cd web && npx cypress run --spec cypress/e2e/m4-autonomous.cy.ts` (stack up per the repo's E2E instructions).
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/cypress/e2e/m4-autonomous.cy.ts
git commit -s -m "test(m4-c2): Cypress E2E — opt-in, receipt, halt, memory keep, precedent dismiss"
```

---

### Task 19: File the deferred enhancements (PRD §9)

**Files:**
- Modify: `docs/PRD.md` §9

- [ ] **Step 1: Add DE-323 and DE-324** to PRD §9, in the existing DE format:
  - **DE-323 — Autonomous context proposals on the Matter detail page.** Surface pending `project_context_proposals` as an inbox banner on `/lq-ai/matters/[id]`, complementing the in-Autonomous Proposals surface. Origin: M4-C2 design §5.
  - **DE-324 — Global-chrome notification bell.** A bell + unread badge in the shared OpenWebUI chrome (with its own opt-in gating), complementing the Autonomous rail Notifications page. Origin: M4-C2 design §7.

- [ ] **Step 2: Commit**

```bash
git add docs/PRD.md
git commit -s -m "docs(m4-c2): file DE-323 (proposals on matter page) + DE-324 (global notification bell)"
```

---

### Task 20: Final verification + mark M4-C2 complete

- [ ] **Step 1: Full backend gates + autonomous suite**

Run:
```bash
cd api && ./.venv/bin/ruff format --check . && ./.venv/bin/ruff check . && ./.venv/bin/mypy app
cd api && DATABASE_URL=... ./.venv/bin/pytest tests/autonomous/ tests/api/test_users_preferences_autonomous.py tests/models/test_user_autonomous_enabled.py tests/test_openapi.py -q
```
Expected: all green; OpenAPI path count still 113.

- [ ] **Step 2: Full web gates + unit + E2E**

Run:
```bash
cd web && npm run check && npm run lint && npx vitest run src/lib/lq-ai/autonomous src/routes/lq-ai/autonomous src/lib/lq-ai/api/__tests__/autonomous.test.ts
cd web && npx cypress run --spec cypress/e2e/m4-autonomous.cy.ts
```
Expected: clean / PASS.

- [ ] **Step 3: Visual smoke** — log in fresh (opted out): confirm the Autonomous tab is hidden and `/lq-ai/autonomous` redirects to Settings → Autonomous. Opt in: confirm all seven rail pages load.

- [ ] **Step 4: Update the M4 plan + handoff** — tick Task M4-C2 in `docs/M4-IMPLEMENTATION-PLAN.md`; note completion in the handoff (next: Phase D — D1 Learn viz, D2 boundary-registers flip + fresh-install acceptance).

- [ ] **Step 5: Final push**

```bash
git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous
```

---

## Self-review notes (for the executor)

- **Verify-before-trust:** every `autonomous.ts` path + interface field, and every list-envelope key, MUST be checked against `api/app/api/autonomous.py` + `docs/api/backend-openapi.yaml` before use (Task 7 Step 1 note). The schemas in this plan are the expected shape, not verified ground truth.
- **Existing-test fallout (Task 3):** gating mutate endpoints will 403 any existing autonomous test whose user isn't opted in. Flipping those fixtures to `autonomous_enabled=True` is expected work, not a regression.
- **Fixture names** (`db_session`, `auth_client`, `make_user`, `make_kb`, seeding helpers) are placeholders matched to the real conftest fixtures before running — confirm each against a neighboring test in the same directory.
- **DELETE returns 200-with-entity** across the autonomous API (CLAUDE.md 204 pitfall) — the api client types DELETEs as returning the entity accordingly.
