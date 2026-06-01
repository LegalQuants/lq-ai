# Platform Cohesion Phase 1 — Autonomous Operability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the shipped M4 Autonomous Layer discoverable, learnable, and operable — a user can find it, turn it on, understand schedules vs watches, set a cost cap, see readable target names, and run a skill/playbook once on demand to inspect the receipt before arming — plus correct one Tabular honesty overclaim.

**Architecture:** Phase 1 of `docs/superpowers/specs/2026-05-31-platform-cohesion-and-autonomous-operability-design.md` (§4 only; Phases 2–5 are roadmap, not built). One small backend addition (a `trigger_kind='manual'` "Run now" spawn endpoint that reuses the existing executor + R4/R5/R6 brakes + receipt, mirroring `_run_schedule_sweep`), and several frontend changes on the SvelteKit OpenWebUI fork (discoverability signpost, Configure/education tab, cost-cap field + readable names in the schedule/watch modals & rows, a Run-now UI). No new execution model, no migrations.

**Tech Stack:** FastAPI + SQLAlchemy async + arq (`api/`); pytest (live Postgres via conftest SAVEPOINT throwaway DB). SvelteKit + TypeScript (`web/`); vitest + svelte-check + Cypress.

**Spec:** `docs/superpowers/specs/2026-05-31-platform-cohesion-and-autonomous-operability-design.md`

**Branch:** `feat/lqvern-m4-autonomous` (lands inside M4, ahead of the v0.4.0 tag). Repo: `~/Code/lq-ai` (NEVER `~/Desktop`; the Bash cwd resets to `~/Desktop` between calls, so **prefix every command with `cd ~/Code/lq-ai &&`**).

**Hard rules (apply to EVERY task):**
- DCO: `git commit -s` + trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` (keep 4.7 for branch consistency).
- After each task's commit, push BOTH remotes: `git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous`.
- TDD: failing test → run-it-fails → minimal impl → run-it-passes → commit.
- **NEVER run host-side `alembic upgrade head` against `127.0.0.1:15432/lq_ai`** (the live dev DB — crash-loops the stack). This plan adds NO migration; verify backend behavior only via pytest's throwaway DB.
- **Do NOT `docker compose down -v`** (preserves the attorney-review acceptance data).
- For any touched SvelteKit route/component: `cd ~/Code/lq-ai/web && npm run check:lq-ai` must report **0 errors** before commit (pre-existing warnings in unrelated components are acceptable).
- Backend gate before each backend commit: `cd ~/Code/lq-ai/api && ruff format app tests && ruff check app tests && mypy app` (all clean).
- Truth discipline: this is real product code; never invent an endpoint/field/path — the file references below were verified against source at planning time, but re-read the cited file before editing.

---

## File Structure (created or modified)

**Backend (`api/`):**
- Modify `api/app/schemas/autonomous.py` — add `AutonomousManualRunRequest` (Task 2).
- Modify `api/app/api/autonomous.py` — add `spawn_manual_session` helper + `POST /autonomous/run-now` endpoint (Task 2).
- Test `api/tests/autonomous/test_run_now.py` — new (Task 2).

**Frontend API layer (`web/src/lib/lq-ai/`):**
- Modify `web/src/lib/lq-ai/api/autonomous.ts` — `runNow()` client + `ManualRunRequest` type (Task 3).
- Test `web/src/lib/lq-ai/api/__tests__/autonomous.test.ts` (or sibling) — `runNow` (Task 3).

**Frontend UI (`web/src/routes/lq-ai/`):**
- Modify `web/src/routes/lq-ai/autonomous/schedules/+page.svelte` — cost-cap field + readable target/KB/matter names (Tasks 5, 6).
- Modify `web/src/routes/lq-ai/autonomous/watches/+page.svelte` — cost-cap field + readable names (Tasks 5, 6).
- Modify `web/src/routes/lq-ai/autonomous/+page.svelte` — "Run now" button + modal; instructive empty-state (Tasks 7, 8).
- Modify `web/src/routes/lq-ai/autonomous/+layout.svelte` — add "Configure" nav link (Task 8).
- Create `web/src/routes/lq-ai/autonomous/configure/+page.svelte` — education page (Task 8).
- Modify the Home discoverability surface (`web/src/lib/lq-ai/components/FeaturedToolsRow.svelte` and/or `GettingStartedChecklist.svelte` + `getting-started-signals.ts`) — autonomous signpost (Task 9).
- Modify `web/src/routes/lq-ai/tabular/+page.svelte` and `web/src/routes/lq-ai/tabular/new/+page.svelte` — Citation-Engine wording fix (Task 1).

---

## Task 1: Tabular honesty fix (§4.5) — independent, do first

Corrects the overclaim that tabular cells are "grounded by the Citation Engine" (source emits display-only synthetic citation IDs — DE-309).

**Files:**
- Modify: `web/src/routes/lq-ai/tabular/+page.svelte`
- Modify: `web/src/routes/lq-ai/tabular/new/+page.svelte`

- [ ] **Step 1: Find the exact strings**

Run: `cd ~/Code/lq-ai && rg -n "Citation Engine|grounded by" web/src/routes/lq-ai/tabular/+page.svelte web/src/routes/lq-ai/tabular/new/+page.svelte`
Expected: 1+ hits per file asserting each cell is "grounded by the Citation Engine".

- [ ] **Step 2: Read each hit in context**

Read ~10 lines around each hit so the replacement preserves surrounding sentence/markup.

- [ ] **Step 3: Replace the overclaim with honest wording**

For each occurrence, change the claim from Citation-Engine grounding to source-chunk references. Use this wording (adapt tense/grammar to the surrounding sentence, do not change markup):
- "grounded by the Citation Engine" → "grounded by source-chunk references"
- If a sentence says cells are *verified* by the Citation Engine, change to: "each cell links to the source chunks it was extracted from (display-only references; full Citation-Engine verification is deferred — DE-309)".

Keep it conservative and factual; do not add new claims.

- [ ] **Step 4: Verify no overclaim remains + page checks**

Run: `cd ~/Code/lq-ai && rg -n "Citation Engine" web/src/routes/lq-ai/tabular/+page.svelte web/src/routes/lq-ai/tabular/new/+page.svelte`
Expected: either no hits, or only hits that are now honestly qualified (deferred/DE-309). Then:
Run: `cd ~/Code/lq-ai/web && npm run check:lq-ai`
Expected: 0 errors.

- [ ] **Step 5: Commit + push**

```bash
cd ~/Code/lq-ai && git add web/src/routes/lq-ai/tabular/+page.svelte web/src/routes/lq-ai/tabular/new/+page.svelte && \
git commit -s -m "fix(tabular): correct Citation-Engine overclaim to source-chunk references (DE-309)

Tabular emits display-only synthetic citation IDs, not Citation-Engine-
verified provenance. Reword the UI claim to match source.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" && \
git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous
```

---

## Task 2: Backend — "Run now" spawn endpoint (§4.4)

Adds `POST /api/v1/autonomous/run-now`: spawn a one-off `trigger_kind='manual'` session for a chosen skill OR playbook (+ optional KB / matter / cost cap), reusing the executor and brakes. Mirrors the session-construction in `_run_schedule_sweep` (`api/app/workers/autonomous_worker.py:367-397`) and the endpoint shape of `create_schedule` (`api/app/api/autonomous.py:1036-1087`). The `manual` value already exists in `TriggerKind` (`api/app/schemas/autonomous.py:40`) and in the `autonomous_sessions.trigger_kind` CHECK constraint — no migration needed.

**Files:**
- Modify: `api/app/schemas/autonomous.py` (add request schema near the other Create schemas, ~after line 169)
- Modify: `api/app/api/autonomous.py` (add helper + endpoint near the schedule endpoints, ~after `create_schedule` at line 1088)
- Test: `api/tests/autonomous/test_run_now.py` (new)

- [ ] **Step 1: Read the patterns to mirror**

Read `api/app/workers/autonomous_worker.py:327-402` (the `_run_schedule_sweep` session construction — params dict, `max_cost_usd` fallback, `db.add` + `flush` + `enqueue`) and `api/app/api/autonomous.py:1036-1088` (`create_schedule` — `AutonomousEnabledUser` dep, audit, commit, refresh, return). Also confirm the enqueue helper import: `cd ~/Code/lq-ai && rg -n "enqueue_autonomous_session_job" api/app/workers/queue.py`.

- [ ] **Step 2: Write the request schema**

In `api/app/schemas/autonomous.py`, after `AutonomousScheduleUpdate` (line ~187), add:

```python
class AutonomousManualRunRequest(BaseModel):
    """Request body for ``POST /autonomous/run-now`` (Phase 1, §4.4).

    Spawns a single one-off autonomous session (``trigger_kind='manual'``)
    so a user can test what a skill/playbook does — and inspect the
    resulting receipt — before arming it as a schedule or watch. Exactly
    one of ``playbook_id`` / ``skill_ref`` must be set (the agent runs an
    existing artifact; custom-task authoring is out of scope for Phase 1).
    ``target_kb_id`` and ``project_id`` are optional scope. ``max_cost_usd``
    is the per-run cap (NULL = fall back to
    ``settings.autonomous_default_max_cost_usd`` at spawn time, so R4 always
    trips).
    """

    playbook_id: uuid.UUID | None = None
    skill_ref: str | None = None
    target_kb_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    max_cost_usd: Decimal | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "AutonomousManualRunRequest":
        if (self.playbook_id is None) == (self.skill_ref is None):
            raise ValueError("exactly one of playbook_id or skill_ref must be set")
        return self
```

Confirm `model_validator`, `Decimal`, and `uuid` are already imported at the top of the file (they are used by the existing schemas). If `model_validator` is not imported, add `from pydantic import ... model_validator` to the existing pydantic import line.

- [ ] **Step 3: Write the failing test**

Create `api/tests/autonomous/test_run_now.py`. Read an existing sibling first (`cd ~/Code/lq-ai && ls api/tests/autonomous/` then read `test_r4_per_trigger_cap.py` for the fixtures: how it builds an opted-in user, how it calls the API with auth, and how it asserts a session row). Then write:

```python
"""POST /autonomous/run-now — one-off manual session spawn (Phase 1 §4.4)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.autonomous import AutonomousSession


@pytest.mark.asyncio
async def test_run_now_spawns_manual_session(
    client: AsyncClient,
    autonomous_user_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """A skill-targeted run-now creates a running, trigger_kind='manual' session with a non-null cap."""
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        json={"skill_ref": "nda-review", "max_cost_usd": "0.50"},
        headers=autonomous_user_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["trigger_kind"] == "manual"
    assert body["status"] == "running"
    session_id = uuid.UUID(body["id"])
    row = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.id == session_id)
        )
    ).scalar_one()
    assert row.trigger_kind == "manual"
    assert row.max_cost_usd == Decimal("0.50")
    assert row.params.get("skill_ref") == "nda-review"


@pytest.mark.asyncio
async def test_run_now_defaults_cost_cap_when_omitted(
    client: AsyncClient,
    autonomous_user_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Omitting max_cost_usd falls back to the config default (never NULL → R4 always armed)."""
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        json={"skill_ref": "nda-review"},
        headers=autonomous_user_headers,
    )
    assert resp.status_code == 201, resp.text
    session_id = uuid.UUID(resp.json()["id"])
    row = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.id == session_id)
        )
    ).scalar_one()
    assert row.max_cost_usd is not None


@pytest.mark.asyncio
async def test_run_now_requires_exactly_one_target(
    client: AsyncClient,
    autonomous_user_headers: dict[str, str],
) -> None:
    """Zero or both of playbook_id/skill_ref → 422."""
    both = await client.post(
        "/api/v1/autonomous/run-now",
        json={"skill_ref": "nda-review", "playbook_id": str(uuid.uuid4())},
        headers=autonomous_user_headers,
    )
    assert both.status_code == 422, both.text
    neither = await client.post(
        "/api/v1/autonomous/run-now", json={}, headers=autonomous_user_headers
    )
    assert neither.status_code == 422, neither.text


@pytest.mark.asyncio
async def test_run_now_requires_opt_in(
    client: AsyncClient,
    active_user_headers: dict[str, str],
) -> None:
    """A user without autonomous_enabled gets 403 (AutonomousEnabledUser gate)."""
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        json={"skill_ref": "nda-review"},
        headers=active_user_headers,
    )
    assert resp.status_code == 403, resp.text
```

NOTE: the exact fixture names (`client`, `autonomous_user_headers`, `active_user_headers`, `db_session`) must match what `api/tests/autonomous/conftest.py` / `api/tests/conftest.py` actually provide. Read them first (`cd ~/Code/lq-ai && rg -n "def autonomous_user_headers|def active_user_headers|def client|def db_session" api/tests/conftest.py api/tests/autonomous/conftest.py`) and adjust the fixture names/usage in the test to match the real ones before running. Also confirm the enqueue side effect won't fail the test (the schedule tests inject/monkeypatch the enqueue; mirror however `test_r4_per_trigger_cap.py` handles enqueue so a missing Redis doesn't error — e.g. monkeypatch `enqueue_autonomous_session_job` to an async no-op).

- [ ] **Step 4: Run the test — verify it fails**

Run: `cd ~/Code/lq-ai/api && pytest tests/autonomous/test_run_now.py -v`
Expected: FAIL (404 — route not defined yet).

- [ ] **Step 5: Implement the spawn helper + endpoint**

In `api/app/api/autonomous.py`: add the schema import (`AutonomousManualRunRequest`) to the `from app.schemas.autonomous import (...)` block; add `from app.workers.queue import enqueue_autonomous_session_job` and `from app.config import get_settings` if not already imported (check the top of the file first). Then, after `create_schedule` (line ~1088), add:

```python
async def _spawn_manual_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    body: AutonomousManualRunRequest,
    enqueue: Callable[[uuid.UUID], Awaitable[bool]] | None = None,
) -> AutonomousSession:
    """Create + enqueue a one-off manual autonomous session.

    Mirrors the session construction in
    :func:`app.workers.autonomous_worker._run_schedule_sweep`: builds
    ``params`` carrying only the non-null target keys, sets a non-null
    ``max_cost_usd`` (per-run cap or the config default so R4 always
    arms), flushes to obtain the id, then best-effort enqueues. The
    five-phase executor + R4/R5/R6 brakes + receipt are unchanged.
    """
    enqueue_fn = enqueue if enqueue is not None else enqueue_autonomous_session_job
    settings = get_settings()

    params: dict[str, object] = {"since": None}
    if body.target_kb_id is not None:
        params["kb_id"] = str(body.target_kb_id)
    if body.playbook_id is not None:
        params["playbook_id"] = str(body.playbook_id)
    if body.skill_ref is not None:
        params["skill_ref"] = body.skill_ref

    session = AutonomousSession(
        user_id=user_id,
        project_id=body.project_id,
        trigger_kind="manual",
        trigger_ref=None,
        status="running",
        current_phase="intake",
        max_cost_usd=body.max_cost_usd
        if body.max_cost_usd is not None
        else settings.autonomous_default_max_cost_usd,
        params=params,
    )
    db.add(session)
    await db.flush()
    await enqueue_fn(session.id)
    return session


@router.post(
    "/run-now",
    response_model=AutonomousSessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Run a skill or playbook once now (one-off manual autonomous session)",
    responses={
        201: {"description": "Session spawned"},
        403: {"description": "Autonomous layer not enabled for this user"},
        422: {"description": "Invalid target (need exactly one of playbook_id/skill_ref)"},
        401: {"description": "Not authenticated"},
    },
)
async def run_now(
    body: AutonomousManualRunRequest,
    request: Request,
    user: AutonomousEnabledUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AutonomousSessionRead:
    """POST /api/v1/autonomous/run-now

    Spawn a single ``trigger_kind='manual'`` session so the user can test
    a skill/playbook and inspect its receipt before arming a schedule or
    watch. Gated by opt-in (``AutonomousEnabledUser``); the spawned
    session runs under the same R4/R5/R6 brakes as every other session.
    Audited.
    """
    session = await _spawn_manual_session(db, user_id=user.id, body=body)
    await audit_action(
        db,
        user_id=user.id,
        action="autonomous_session.run_now",
        resource_type="autonomous_session",
        resource_id=str(session.id),
        request=request,
    )
    await db.commit()
    await db.refresh(session)
    return AutonomousSessionRead.model_validate(session)
```

Add the imports `from collections.abc import Awaitable, Callable` at the top if not present (check first — the worker uses them; the api module may not yet).

- [ ] **Step 6: Run the test — verify it passes**

Run: `cd ~/Code/lq-ai/api && pytest tests/autonomous/test_run_now.py -v`
Expected: PASS (4 tests). If the audit `action` string trips an audit-action allowlist, check `api/app/audit.py` for an action enum/allowlist and add `autonomous_session.run_now` there (read `cd ~/Code/lq-ai && rg -n "run_now|_ACTIONS|autonomous_session\." api/app/audit.py api/app/autonomous/audit.py`); re-run.

- [ ] **Step 7: Backend gate**

Run: `cd ~/Code/lq-ai/api && ruff format app tests && ruff check app tests && mypy app`
Expected: all clean. Also run the existing autonomous suite to confirm no regression: `cd ~/Code/lq-ai/api && pytest tests/autonomous/ -q`. Expected: all pass.

- [ ] **Step 8: OpenAPI conformance (if enforced)**

Run: `cd ~/Code/lq-ai/api && pytest tests/test_openapi.py -q` (if present). If it pins a path count, update the expected count to include `/autonomous/run-now`. Expected: PASS.

- [ ] **Step 9: Commit + push**

```bash
cd ~/Code/lq-ai && git add api/app/schemas/autonomous.py api/app/api/autonomous.py api/tests/autonomous/test_run_now.py && \
git commit -s -m "feat(autonomous): POST /autonomous/run-now — one-off manual session (§4.4)

Wires the defined-but-unused trigger_kind='manual': spawn a single
session for a skill/playbook (+optional KB/matter/cap), reusing the
executor + R4/R5/R6 brakes + receipt, mirroring _run_schedule_sweep.
Lets a user test before arming a schedule/watch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" && \
git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous
```

---

## Task 3: Frontend API client — `runNow()`

**Files:**
- Modify: `web/src/lib/lq-ai/api/autonomous.ts`
- Test: `web/src/lib/lq-ai/api/__tests__/autonomous.test.ts` (or the existing sibling test file for this client)

- [ ] **Step 1: Read the existing client + a test**

Read `web/src/lib/lq-ai/api/autonomous.ts` (find `createSchedule` — copy its fetch/error pattern and the `AutonomousScheduleRead`/`AutonomousSessionRead` TS types) and its existing test file (`cd ~/Code/lq-ai && rg -ln "createSchedule|autonomousApi" web/src/lib/lq-ai/api/__tests__/ web/src/lib/lq-ai/**/__tests__/ 2>/dev/null`).

- [ ] **Step 2: Write the failing test**

In the autonomous client's test file, add (mirror how sibling tests mock `fetch`/the client):

```ts
it('runNow posts to /autonomous/run-now and returns the session', async () => {
  const session = { id: 's1', trigger_kind: 'manual', status: 'running' };
  mockFetchOnce(201, session); // use whatever mock helper the sibling tests use
  const result = await autonomousApi.runNow({ skill_ref: 'nda-review', max_cost_usd: '0.50' });
  expect(result.trigger_kind).toBe('manual');
  expect(lastFetchUrl()).toContain('/autonomous/run-now');
  expect(lastFetchMethod()).toBe('POST');
});
```

Adapt `mockFetchOnce`/`lastFetchUrl`/`lastFetchMethod` to the real test helpers in that file.

- [ ] **Step 3: Run test — verify it fails**

Run: `cd ~/Code/lq-ai/web && npx vitest run src/lib/lq-ai/api/__tests__/autonomous.test.ts`
Expected: FAIL (`runNow` not a function).

- [ ] **Step 4: Implement `runNow` + the request type**

In `web/src/lib/lq-ai/api/autonomous.ts`, add the type and method (match the file's existing style — `AutonomousSessionRead` already exists there):

```ts
export interface ManualRunRequest {
  playbook_id?: string;
  skill_ref?: string;
  target_kb_id?: string;
  project_id?: string;
  max_cost_usd?: string; // Decimal serialized as string, matching createSchedule
}

// inside the autonomousApi object, next to createSchedule:
async runNow(body: ManualRunRequest): Promise<AutonomousSessionRead> {
  return apiPost<AutonomousSessionRead>('/autonomous/run-now', body); // use the file's actual post helper
}
```

Use the exact post helper / client wrapper the other methods use (e.g. `client.post` / `apiFetch`) — read `createSchedule` and copy it precisely.

- [ ] **Step 5: Run test — verify it passes**

Run: `cd ~/Code/lq-ai/web && npx vitest run src/lib/lq-ai/api/__tests__/autonomous.test.ts`
Expected: PASS.

- [ ] **Step 6: Type-check + commit + push**

```bash
cd ~/Code/lq-ai/web && npm run check:lq-ai   # 0 errors
cd ~/Code/lq-ai && git add web/src/lib/lq-ai/api/autonomous.ts web/src/lib/lq-ai/api/__tests__/autonomous.test.ts && \
git commit -s -m "feat(autonomous-ui): runNow() API client for /autonomous/run-now

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" && \
git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous
```

---

## Task 4: Cost-cap field in the New Schedule + New Watch modals (§4.3 part 1)

The API accepts `max_cost_usd` on create (`AutonomousScheduleCreate`/`AutonomousWatchCreate`) and enforces R4, but the modals don't expose it. Add an optional cost-cap input to both create modals.

**Files:**
- Modify: `web/src/routes/lq-ai/autonomous/schedules/+page.svelte`
- Modify: `web/src/routes/lq-ai/autonomous/watches/+page.svelte`

- [ ] **Step 1: Read the schedule modal**

Read `web/src/routes/lq-ai/autonomous/schedules/+page.svelte` — note the form state vars (`formName`, `formCronExpr`, `formPlaybookId`, `formSkillRef`, `formKbId`, `formProjectId`), the `createSchedule({...})` call (~line 231), the `modal-field` markup pattern (lines ~422-565), and the `closeModal`/reset logic.

- [ ] **Step 2: Add the cost-cap form state + reset**

Add `let formMaxCostUsd = '';` alongside the other form vars. In the modal reset (`openModal`/`closeModal`), reset it to `''`.

- [ ] **Step 3: Add the cost-cap field to the schedule modal markup**

After the optional Matter/project field (~line 565, before the actions block), add a `modal-field` matching the existing pattern:

```svelte
<!-- Cost cap (optional) -->
<div class="modal-field">
  <label class="modal-label" for="sched-cost-cap">
    Cost cap (USD) <span class="modal-optional">(optional)</span>
  </label>
  <input
    id="sched-cost-cap"
    type="number"
    min="0"
    step="0.01"
    class="modal-input"
    bind:value={formMaxCostUsd}
    placeholder="e.g. 1.00 — defaults to the system cap if blank"
    disabled={submitting}
  />
  <p class="modal-hint">
    The most this run may spend before it halts (R4). Blank uses the system default.
  </p>
</div>
```

If `.modal-hint` is not an existing class in the file, reuse whatever hint/secondary-text class the file already uses (grep the file for `modal-hint` / a help-text class); do not invent a new style.

- [ ] **Step 4: Pass `max_cost_usd` to createSchedule**

In `handleSubmit`, change the `createSchedule({...})` call to include the cap only when set:

```ts
await autonomousApi.createSchedule({
  // ...existing fields...
  ...(formMaxCostUsd.trim() !== '' ? { max_cost_usd: formMaxCostUsd.trim() } : {})
});
```

Confirm `createSchedule`'s TS type accepts `max_cost_usd?: string`; if not, add it to that type in `autonomous.ts`.

- [ ] **Step 5: Repeat for the watch modal**

Apply Steps 1–4 to `web/src/routes/lq-ai/autonomous/watches/+page.svelte` (same field, `createWatch({...})` call, ids prefixed `watch-cost-cap`).

- [ ] **Step 6: Type-check**

Run: `cd ~/Code/lq-ai/web && npm run check:lq-ai`
Expected: 0 errors.

- [ ] **Step 7: Commit + push**

```bash
cd ~/Code/lq-ai && git add web/src/routes/lq-ai/autonomous/schedules/+page.svelte web/src/routes/lq-ai/autonomous/watches/+page.svelte && \
git commit -s -m "feat(autonomous-ui): expose per-trigger cost cap in schedule/watch create modals (§4.3)

The cap exists in the API + enforces R4 but was not settable in the UI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" && \
git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous
```

---

## Task 5: Readable target/KB/matter names in schedule + watch list rows (§4.3 part 2)

Rows currently render raw UUIDs (`playbook_id`/`skill_ref`/`kb_id`). Resolve them to human names using the picker lists the page already loads (playbooks, skills, KBs, projects).

**Files:**
- Modify: `web/src/routes/lq-ai/autonomous/schedules/+page.svelte`
- Modify: `web/src/routes/lq-ai/autonomous/watches/+page.svelte`

- [ ] **Step 1: Confirm the loaded lists + the row render**

In the schedules page, confirm the page loads `playbooks`, `skillSummaries`, `kbs`, `projects` (it does — for the modal pickers) and find the `targetSummary(s)` function (~the row "Target" cell) that currently shows the UUID.

- [ ] **Step 2: Write a name resolver**

Add helpers that map an id to a name, falling back to the id if not found (so a deleted/foreign target still renders something):

```ts
function playbookName(id: string | null): string {
  if (!id) return '';
  return playbooks.find((p) => p.id === id)?.name ?? id;
}
function skillName(ref: string | null): string {
  if (!ref) return '';
  return skillSummaries.find((s) => s.name === ref)?.title || ref;
}
function kbName(id: string | null): string {
  if (!id) return '';
  return kbs.find((k) => k.id === id)?.name ?? id;
}
function projectName(id: string | null): string {
  if (!id) return '';
  return projects.find((p) => p.id === id)?.name ?? id;
}
```

Use the exact field names from the loaded list types (read them — playbooks use `.id`/`.name`; skills use `.name`/`.title`; KBs `.id`/`.name`; projects `.id`/`.name`, confirmed in the modal pickers).

- [ ] **Step 3: Use the resolvers in `targetSummary` + KB/matter cells**

Update `targetSummary(s)` to render `playbookName(s.playbook_id)` or `skillName(s.skill_ref)` (with a "Playbook: " / "Skill: " prefix), and any KB/matter cell to use `kbName`/`projectName`. Keep the existing markup; only change the displayed string.

- [ ] **Step 4: Repeat for the watch page**

Apply to `watches/+page.svelte` (it loads the same picker lists; KB is required so always resolvable).

- [ ] **Step 5: Type-check + commit + push**

```bash
cd ~/Code/lq-ai/web && npm run check:lq-ai   # 0 errors
cd ~/Code/lq-ai && git add web/src/routes/lq-ai/autonomous/schedules/+page.svelte web/src/routes/lq-ai/autonomous/watches/+page.svelte && \
git commit -s -m "feat(autonomous-ui): show readable target/KB/matter names in schedule/watch rows (§4.3)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" && \
git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous
```

---

## Task 6: "Run now" UI (§4.4 frontend)

A button on the Autonomous Sessions page opens a modal (mirroring the New-Schedule modal minus the cron field) to run a skill/playbook once; on success, navigate to the new session's receipt.

**Files:**
- Modify: `web/src/routes/lq-ai/autonomous/+page.svelte` (the Sessions page)

- [ ] **Step 1: Read the Sessions page + reuse the modal pattern**

Read `web/src/routes/lq-ai/autonomous/+page.svelte`. Note how it loads sessions, the page header area (for a button), and how it navigates to a session detail (`goto('/lq-ai/autonomous/sessions/' + id)`). Reuse the modal markup/state pattern from `schedules/+page.svelte` (Target radio Skill|Playbook + pickers + optional KB/Matter + cost cap — but NO cron field).

- [ ] **Step 2: Add Run-now modal state + a header button**

Add form state (`runTargetKind: 'skill'|'playbook'`, `runSkillRef`, `runPlaybookId`, `runKbId`, `runProjectId`, `runMaxCostUsd`, `runModalOpen`, `runSubmitting`, `runError`) and load the picker lists (playbooks/skills/kbs/projects) on mount the same way the schedules page does. Add a `Run now` button in the page header next to the title.

- [ ] **Step 3: Implement submit**

```ts
async function submitRunNow() {
  runSubmitting = true;
  runError = null;
  try {
    const session = await autonomousApi.runNow({
      ...(runTargetKind === 'skill' ? { skill_ref: runSkillRef } : { playbook_id: runPlaybookId }),
      ...(runKbId ? { target_kb_id: runKbId } : {}),
      ...(runProjectId ? { project_id: runProjectId } : {}),
      ...(runMaxCostUsd.trim() !== '' ? { max_cost_usd: runMaxCostUsd.trim() } : {})
    });
    runModalOpen = false;
    await goto(`/lq-ai/autonomous/sessions/${session.id}`);
  } catch (err) {
    runError = err instanceof Error ? err.message : String(err);
  } finally {
    runSubmitting = false;
  }
}
```

- [ ] **Step 4: Add the modal markup**

Mirror the schedules modal (Target radio + Skill/Playbook select + optional KB + optional Matter + cost cap + Cancel/"Run now"), bound to the `run*` state, calling `submitRunNow`. Title: "Run a skill or playbook once". Include a one-line honest note: "This runs once now so you can see the result before arming a schedule or watch."

- [ ] **Step 5: Type-check**

Run: `cd ~/Code/lq-ai/web && npm run check:lq-ai`
Expected: 0 errors.

- [ ] **Step 6: Cypress smoke (extend the existing autonomous spec)**

Read `web/cypress/e2e/m4-autonomous.cy.ts`. Add a test that (with autonomous enabled, the spec's existing setup) opens the Run-now modal, selects a skill, submits, and asserts navigation to a `/lq-ai/autonomous/sessions/` URL. Use the spec's existing API-mock/intercept pattern (intercept `POST /api/v1/autonomous/run-now` → 201 with a session). Do not require a live worker.

Run: `cd ~/Code/lq-ai/web && npx cypress run --spec cypress/e2e/m4-autonomous.cy.ts` (or the project's Cypress command). Expected: PASS. If Cypress isn't runnable headless in this env, note it and rely on the vitest + check gates.

- [ ] **Step 7: Commit + push**

```bash
cd ~/Code/lq-ai && git add web/src/routes/lq-ai/autonomous/+page.svelte web/cypress/e2e/m4-autonomous.cy.ts && \
git commit -s -m "feat(autonomous-ui): Run now — one-off run of a skill/playbook with receipt (§4.4)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" && \
git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous
```

---

## Task 7: Configure / education tab + instructive empty-states (§4.2)

Add a "Configure" sub-tab in the Autonomous area that explains the Off/On state, schedules vs watches, targets/scope/cost-cap, and where results land; and replace bare empty-states with instructive ones.

**Files:**
- Modify: `web/src/routes/lq-ai/autonomous/+layout.svelte` (add the nav link)
- Create: `web/src/routes/lq-ai/autonomous/configure/+page.svelte`
- Modify: `web/src/routes/lq-ai/autonomous/+page.svelte` (Sessions empty-state)
- Modify: `web/src/routes/lq-ai/autonomous/schedules/+page.svelte` (empty-state)
- Modify: `web/src/routes/lq-ai/autonomous/watches/+page.svelte` (empty-state)

- [ ] **Step 1: Add the nav link**

In `web/src/routes/lq-ai/autonomous/+layout.svelte`, add to the `navLinks` array a leading entry:
```ts
{ href: '/lq-ai/autonomous/configure', label: 'Configure', exact: false },
```
(Place it first, before "Sessions", so it reads as the starting point.)

- [ ] **Step 2: Create the Configure page**

Create `web/src/routes/lq-ai/autonomous/configure/+page.svelte`. It is static educational content (reuse the page-heading/text classes used elsewhere in the autonomous section — read a sibling page for the class names). Cover, in honest plain language:
- **On/Off:** the layer is opt-in and off by default; it's enabled in Settings → Autonomous; turning it off stops new runs but you keep receipts and can still halt running ones.
- **Schedules:** a cron-driven run of a chosen skill or playbook (optionally scoped to a KB and/or matter), with a per-run cost cap.
- **Watches:** a run triggered when a document is attached to a chosen knowledge base.
- **Run now:** run a skill/playbook once on demand (from the Sessions tab) to see the result before arming a schedule/watch.
- **Where results land:** Sessions (each run + its inspectable receipt), plus Memory / Precedents / Proposals / Notifications.
- **Safety:** every run is bounded by a cost cap (R4), an external halt + idle watchdog (R5), and per-phase tool limits (R6), and produces a receipt.
Include a link to Settings → Autonomous (`/lq-ai/settings/autonomous`) for the toggle.

Do NOT overstate: no claim of custom-task authoring or test-harness beyond Run-now.

- [ ] **Step 3: Instructive empty-states**

In each of Sessions / Schedules / Watches pages, replace the bare empty-state line with a short instructive one that names the first action and links to Configure. Examples:
- Sessions: "No runs yet. Use **Run now** to run a skill or playbook once, or set up a **Schedule** or **Watch**. New here? See **Configure**."
- Schedules: keep "No schedules yet." + add "A schedule runs a skill/playbook on a cron cadence. See **Configure** to learn how." with a link.
- Watches: similar, KB-trigger framing.
Make "Configure" a link to `/lq-ai/autonomous/configure`.

- [ ] **Step 4: Type-check**

Run: `cd ~/Code/lq-ai/web && npm run check:lq-ai`
Expected: 0 errors.

- [ ] **Step 5: Commit + push**

```bash
cd ~/Code/lq-ai && git add web/src/routes/lq-ai/autonomous/+layout.svelte web/src/routes/lq-ai/autonomous/configure/+page.svelte web/src/routes/lq-ai/autonomous/+page.svelte web/src/routes/lq-ai/autonomous/schedules/+page.svelte web/src/routes/lq-ai/autonomous/watches/+page.svelte && \
git commit -s -m "feat(autonomous-ui): Configure/education tab + instructive empty-states (§4.2)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" && \
git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous
```

---

## Task 8: Discoverability signpost on Home (§4.1)

Surface the Autonomous Layer where a new user looks, with a path to the opt-in — resolving the chicken-and-egg (today the tab is hidden until enabled and nothing links to the buried Settings toggle).

**Files:**
- Modify: the Home discoverability surface — determine which of `web/src/lib/lq-ai/components/FeaturedToolsRow.svelte`, `web/src/lib/lq-ai/components/GettingStartedChecklist.svelte`, or `web/src/lib/lq-ai/getting-started-signals.ts` is the right host (read all three first).

- [ ] **Step 1: Read the Home components**

Read `FeaturedToolsRow.svelte`, `GettingStartedChecklist.svelte`, and `getting-started-signals.ts`. Decide the least-intrusive host: a "Featured tool" card for Autonomous (always shown, links to Settings → Autonomous when off, or to the Autonomous tab when on), OR a getting-started checklist item ("Try the Autonomous layer"). Prefer the FeaturedToolsRow card if it renders unconditionally for all users (so off-by-default users see it). Confirm how the component knows `autonomous_enabled` (the `preferences` store — `$preferences.autonomous_enabled`, as used in `TopTabBar.svelte`).

- [ ] **Step 2: Add the signpost**

Add an Autonomous entry to the chosen surface:
- Label/blurb: "Autonomous — let LQ.AI run a skill or playbook on a schedule or when documents arrive (opt-in, off by default)."
- Link target: if `$preferences.autonomous_enabled` → `/lq-ai/autonomous`; else → `/lq-ai/settings/autonomous` (the opt-in), so a new user can reach the toggle without hunting the gear.
Match the existing card/item markup; do not invent a new component or palette.

- [ ] **Step 3: Unit test (if the host has one)**

If `FeaturedToolsRow`/`GettingStartedChecklist` has a vitest spec, add an assertion that the Autonomous entry renders and links to `/lq-ai/settings/autonomous` when autonomous is disabled. Run: `cd ~/Code/lq-ai/web && npx vitest run <the spec>`. Expected: PASS. If no spec exists, skip (don't create scaffolding the codebase doesn't have for siblings).

- [ ] **Step 4: Type-check**

Run: `cd ~/Code/lq-ai/web && npm run check:lq-ai`
Expected: 0 errors.

- [ ] **Step 5: Commit + push**

```bash
cd ~/Code/lq-ai && git add web/src/lib/lq-ai/components/ web/src/lib/lq-ai/getting-started-signals.ts && \
git commit -s -m "feat(autonomous-ui): Home discoverability signpost + path to opt-in (§4.1)

Resolves the chicken-and-egg: surfaces Autonomous on Home and links a
not-yet-enabled user straight to Settings -> Autonomous.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" && \
git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous
```

---

## Task 9: Final verification pass

**Files:** none (verification only; small fixups allowed).

- [ ] **Step 1: Full frontend type-check**

Run: `cd ~/Code/lq-ai/web && npm run check:lq-ai`
Expected: 0 errors (pre-existing warnings acceptable).

- [ ] **Step 2: Frontend unit tests**

Run: `cd ~/Code/lq-ai/web && npx vitest run`
Expected: PASS (no regressions).

- [ ] **Step 3: Backend suite + gate**

Run: `cd ~/Code/lq-ai/api && ruff format --check app tests && ruff check app tests && mypy app && pytest tests/autonomous/ tests/test_openapi.py -q`
Expected: all clean / PASS.

- [ ] **Step 4: Spec coverage check**

Confirm each §4 item is delivered: §4.1 Home signpost (Task 8), §4.2 Configure tab + empty-states (Task 7), §4.3 cost-cap field (Task 4) + readable names (Task 5), §4.4 Run-now backend (Task 2) + client (Task 3) + UI (Task 6), §4.5 Tabular honesty (Task 1). Note any gap.

- [ ] **Step 5: Report**

Summarize the edited/created files, the new endpoint, and confirm both remotes are at the same HEAD (`cd ~/Code/lq-ai && git rev-parse --short HEAD origin/feat/lqvern-m4-autonomous tucuxi/feat/lqvern-m4-autonomous`). Hand back for the v0.4.0 readiness check (Task 20 closeout + attorney walk-through + tag still follow this build).

---

## Self-Review notes (author)

- **Spec coverage:** §4.1→Task 8; §4.2→Task 7; §4.3→Tasks 4+5; §4.4→Tasks 2+3+6; §4.5→Task 1. Phases 2–5 intentionally excluded (roadmap). All §4 items mapped.
- **No migration:** `trigger_kind='manual'` is already in the `TriggerKind` enum and the `autonomous_sessions.trigger_kind` CHECK; Run-now reuses it. No alembic — honors the no-host-alembic rule.
- **Reuse over invention:** Run-now mirrors `_run_schedule_sweep`'s session construction (params, non-null cap, flush+enqueue) and `create_schedule`'s endpoint shape (opt-in dep, audit, commit, refresh). Cost-cap field + name resolvers reuse the lists the modals already load.
- **Ordering:** Task 1 (honesty, independent) first; backend Run-now (2) before its client (3) before its UI (6); the two modal enhancements (4,5) are independent; education (7) and discoverability (8) last. Treat as an ordered list.
- **Known soft spots flagged inline for the implementer:** exact pytest fixture names (read conftest), the audit-action allowlist (may need `autonomous_session.run_now` added), the post-helper name in `autonomous.ts`, and which Home component is the right signpost host — each step says "read first, then adapt."
