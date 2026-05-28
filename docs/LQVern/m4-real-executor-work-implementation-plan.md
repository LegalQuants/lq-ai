# M4 — Wire real in-loop agentic work into the Autonomous executor — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the M4 executor-skeleton honesty gap — wire the five executor nodes to do real work (run the bound skill/playbook against the triggering work via the autonomous chokepoint, parse a structured-output JSON response, dispatch findings + memory/precedent proposals as their own guarded calls) — plus the two enabling changes (`max_cost_usd` per-trigger with safe default; `retrieve_chunks` scope extension) and the two bug fixes (`terminal_reason="completed"` + watch-trigger live verification), so v0.4.0 ships a genuinely working single-agent Autonomous Layer rather than a substrate release.

**Architecture:** Each of the five LangGraph nodes (`intake`/`analysis`/`drafting`/`ethics_review`/`delivery`) calls real work **only through** the existing autonomous `guarded_tool_call` chokepoint. Nesting the Playbook executor is forbidden (its internal gateway calls would route around the R4/R5/R6 brakes). The analysis call uses a **single structured-output** JSON contract `{findings[], suggested_memories[], suggested_precedents[], privilege_concerns[], scope_concerns[]}`; the drafting node parses it and dispatches each item as its own guarded call. Watch sessions analyze the arriving document (`retrieve_chunks` by `file_id`); schedule sessions analyze documents attached since `last_run_at` (`retrieve_chunks` by `since`). Every spawned session **always** has a `max_cost_usd` (per-trigger or global default ~$5), so R4 has teeth in production.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, LangGraph, arq workers, pytest with the existing throwaway-DB conftest. Mirrors the patterns in `api/app/playbooks/` and `api/app/autonomous/guard.py`.

**Companion to:** [`docs/LQVern/m4-real-executor-work-design.md`](m4-real-executor-work-design.md) (the design contract this plan executes), [`docs/M4-IMPLEMENTATION-PLAN.md`](../M4-IMPLEMENTATION-PLAN.md), [`docs/LQVern/agentic-flow-alignment-guide.md`](agentic-flow-alignment-guide.md), [ADR 0013](../adr/0013-autonomous-layer-design-influences.md).

---

## Environment + workflow rules (read first)

- **Canonical repo:** `~/Code/lq-ai` (NEVER `~/Desktop/lq-ai`). The Bash tool's cwd RESETS to `~/Desktop` between calls — prefix every command with `cd ~/Code/lq-ai &&`.
- **Branch:** `feat/lqvern-m4-autonomous`. Do NOT create or switch branches.
- **Migrations:** NEVER run host-side `alembic upgrade head` against `127.0.0.1:15432/lq_ai` — it desyncs the live dev DB and crash-loops the api+arq+ingest trio. Verify migrations via pytest only (conftest builds its own throwaway DB on the same server, isolated). To apply a new migration to the dev stack, rebuild the api+arq-worker+ingest-worker trio together.
- **Local tests:**
  ```bash
  cd ~/Code/lq-ai/api && \
    PW=$(grep -m1 '^POSTGRES_PASSWORD=' ../.env | cut -d= -f2-) && \
    DATABASE_URL="postgresql+asyncpg://lq_ai:${PW}@127.0.0.1:15432/lq_ai" \
    ./.venv/bin/pytest tests/autonomous/ -q
  ```
- **Gates (every task that touches Python):** `ruff format` AND `ruff check` (separately — CI runs both as separate gates) + `mypy` (standard mode for `api/`). For multi-file changes also run the targeted test suite.
- **DCO:** every commit is `git commit -s` and ends with the trailer:
  `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- **Push after each task:** `git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous`. Never delete branches.
- **Honesty / no-drift:** every span attribute, audit action, outcome label, and receipt field used by tests or new code MUST match what shipped code in `api/app/autonomous/{guard,audit,receipt,enums}.py` already emits. Re-grep if in doubt.

---

## File structure

| File | Action | Responsibility |
|---|---|---|
| `api/alembic/versions/0045_autonomous_per_trigger_max_cost.py` | **Create** | Adds `max_cost_usd NUMERIC(10,4) NULL` to `autonomous_watches` and `autonomous_schedules`. |
| `api/app/config.py` | Modify | Add `autonomous_default_max_cost_usd: Decimal = Decimal("5.00")` setting + env override `LQ_AI_AUTONOMOUS_DEFAULT_MAX_COST_USD`. |
| `api/app/models/autonomous.py` | Modify | Add `max_cost_usd` Mapped column to `AutonomousWatch` and `AutonomousSchedule` ORM models. |
| `api/app/schemas/autonomous.py` | Modify | Add `max_cost_usd: Decimal \| None = None` to `AutonomousWatchCreate`/`AutonomousWatchUpdate`/`AutonomousWatchRead`, `AutonomousScheduleCreate`/`AutonomousScheduleUpdate`/`AutonomousScheduleRead`. |
| `api/app/api/autonomous.py` | Modify | POST + PATCH /watches and /schedules persist max_cost_usd; GET surfaces it. |
| `api/app/autonomous/watch_trigger.py` | Modify | `fire_watches_for_kb` sets `session.max_cost_usd = watch.max_cost_usd or settings.autonomous_default_max_cost_usd` (never None). |
| `api/app/workers/autonomous_worker.py` | Modify | `_run_schedule_sweep` sets `session.max_cost_usd` the same way; also writes `last_run_at` (existing field) into `session.params["since"]` so intake can scope retrieve_chunks. |
| `api/app/autonomous/guard.py` | Modify | `_handle_retrieve_chunks` accepts optional `file_id` (fetch a specific file's chunks) and `since` + `kb_id` (fetch chunks of files with `attached_at > since`); existing query path unchanged. |
| `api/app/autonomous/prompts.py` | **Create** | `assemble_analysis_messages(session, chunks, db, registry) -> list[dict]` — load skill_ref via `SkillRegistry.get_skill` OR playbook_id via `select(Playbook)...`, build the system prompt + user message + the structured-output JSON instruction tail. One responsibility: prompt assembly. |
| `api/app/autonomous/structured_output.py` | **Create** | `parse_structured_output(content: str \| None) -> StructuredResult` — tolerant JSON parser (strip ```json fences, `json.loads`, on failure return a `StructuredResult.unstructured(content)` sentinel). One responsibility: parsing + dataclass. |
| `api/app/autonomous/nodes.py` | Modify | Wire all 5 nodes (intake/analysis/drafting/ethics_review/delivery) to do real work per the design §3 table. Remove the "skeleton" docstrings. |
| `api/tests/autonomous/test_retrieve_chunks_scope.py` | **Create** | Tests for the file_id + since extensions to `_handle_retrieve_chunks`. |
| `api/tests/autonomous/test_prompts.py` | **Create** | Tests for `assemble_analysis_messages` with skill_ref vs playbook_id vs neither. |
| `api/tests/autonomous/test_structured_output.py` | **Create** | Tests for the tolerant parser (well-formed JSON, ```json fences, malformed, empty). |
| `api/tests/autonomous/test_executor_real_work.py` | **Create** | End-to-end test of the wired nodes against a mocked gateway: full happy-path session produces findings + memory/precedent proposals + `terminal_reason="completed"`. |
| `api/tests/autonomous/test_executor_gateway_error.py` | **Create** | Gateway transport error completes honestly (one error-explanation emit_finding; `terminal_reason="completed"`; not halted). |
| `api/tests/autonomous/test_spawn_max_cost_usd.py` | **Create** | Watch + schedule spawn paths set `session.max_cost_usd` from per-trigger value or default; never None. |
| `api/tests/autonomous/test_r4_per_trigger_cap.py` | **Create** | A low per-trigger `max_cost_usd` makes the analysis call latch `cost_cap_reached` (R4 live, in production-shape spawn path). |
| `api/tests/autonomous/test_terminal_reason_completed.py` | **Create** | Delivery node writes the `completed` audit row; receipt shows `terminal_reason="completed"`. |
| `api/tests/autonomous/test_executor_skeleton.py` | **Modify** | Existing skeleton test that asserts no tool path bypasses the chokepoint — UPDATE its expectations so the analysis/drafting node assertions match real-work behavior (the chokepoint invariant stays). |

---

## Task 1: Migration 0045 — `max_cost_usd` on watches + schedules

**Files:**
- Create: `api/alembic/versions/0045_autonomous_per_trigger_max_cost.py`

- [ ] **Step 1: Read the prior autonomous migrations to mirror their style**

```bash
cd ~/Code/lq-ai && ls api/alembic/versions/ | grep 004
```

Read at least `0044_user_autonomous_enabled.py` and the migration that created `autonomous_sessions` (which has the existing `max_cost_usd` column on sessions) so the new column type/constraint matches.

- [ ] **Step 2: Write the migration**

```python
"""autonomous_watches + autonomous_schedules per-trigger max_cost_usd — M4 real executor work

Adds an optional ``max_cost_usd`` to both trigger tables so a user can cap
autonomous spend per watch / per schedule. ``NULL`` means "fall back to the
global default at spawn time" (``settings.autonomous_default_max_cost_usd``,
mirroring the gateway.yaml default of $5).

Mirrors the existing ``autonomous_sessions.max_cost_usd`` column type
(``NUMERIC(10,4)``). Spawn paths in
:func:`app.autonomous.watch_trigger.fire_watches_for_kb` and
:func:`app.workers.autonomous_worker._run_schedule_sweep` are updated in
the same PR to ALWAYS set the spawned session's ``max_cost_usd`` (per-trigger
value or global default) so R4 has teeth in production.

Revision ID: 0045
Revises: 0044
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "autonomous_watches",
        sa.Column("max_cost_usd", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "autonomous_schedules",
        sa.Column("max_cost_usd", sa.Numeric(10, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("autonomous_schedules", "max_cost_usd")
    op.drop_column("autonomous_watches", "max_cost_usd")
```

- [ ] **Step 3: Run pytest's throwaway-DB to verify the migration applies cleanly**

```bash
cd ~/Code/lq-ai/api && \
  PW=$(grep -m1 '^POSTGRES_PASSWORD=' ../.env | cut -d= -f2-) && \
  DATABASE_URL="postgresql+asyncpg://lq_ai:${PW}@127.0.0.1:15432/lq_ai" \
  ./.venv/bin/pytest tests/autonomous/test_brakes.py -q
```

Expected: 10 passed (conftest builds a throwaway DB; that includes running `alembic upgrade head` through 0045).

- [ ] **Step 4: Commit**

```bash
cd ~/Code/lq-ai && git add api/alembic/versions/0045_autonomous_per_trigger_max_cost.py && \
  git commit -s -m "feat(m4): migration 0045 — per-trigger max_cost_usd on watches + schedules

Adds an optional max_cost_usd NUMERIC(10,4) NULL column to autonomous_watches
and autonomous_schedules. Mirrors the existing autonomous_sessions.max_cost_usd
column type. NULL = fall back to the global default at spawn time (next task
adds the config + spawn-path enforcement).

Refs M4-D2 real-executor-work design §5

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Config — `autonomous_default_max_cost_usd`

**Files:**
- Modify: `api/app/config.py`

- [ ] **Step 1: Locate the Settings class**

```bash
cd ~/Code/lq-ai && grep -n "class Settings\|class.*Settings.*Base" api/app/config.py | head -5
```

- [ ] **Step 2: Write the failing test**

Create or extend `api/tests/test_config.py` (or wherever existing config tests live — `grep -rn "from app.config\|settings\." api/tests/ | head` to locate):

```python
# api/tests/autonomous/test_config_autonomous_defaults.py
from decimal import Decimal

from app.config import get_settings


def test_autonomous_default_max_cost_usd_present_with_sane_default() -> None:
    s = get_settings()
    assert s.autonomous_default_max_cost_usd == Decimal("5.00")


def test_autonomous_default_max_cost_usd_env_override(monkeypatch) -> None:
    monkeypatch.setenv("LQ_AI_AUTONOMOUS_DEFAULT_MAX_COST_USD", "1.25")
    get_settings.cache_clear()  # if lru_cache; otherwise instantiate Settings()
    try:
        s = get_settings()
        assert s.autonomous_default_max_cost_usd == Decimal("1.25")
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_config_autonomous_defaults.py -v
```

Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'autonomous_default_max_cost_usd'`.

- [ ] **Step 4: Add the field**

In `api/app/config.py`, in the Settings class (near the other autonomous-related settings — search for `session_idle_timeout_seconds` if needed and add it nearby):

```python
from decimal import Decimal
# ... other imports ...

class Settings(BaseSettings):
    # ... existing fields ...

    autonomous_default_max_cost_usd: Decimal = Field(
        default=Decimal("5.00"),
        description=(
            "Global default per-session cost cap (USD) for autonomous sessions "
            "spawned by a watch or schedule that did not set max_cost_usd. "
            "Mirrors the gateway.yaml default. R4 (economic brake) trips when "
            "projected cost would exceed this cap."
        ),
        validation_alias=AliasChoices("LQ_AI_AUTONOMOUS_DEFAULT_MAX_COST_USD"),
    )
```

(Import `Decimal`, `Field`, `AliasChoices` if not already imported; match the file's existing style.)

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_config_autonomous_defaults.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Format + lint + type-check**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/ruff format app/config.py tests/autonomous/test_config_autonomous_defaults.py && \
  ./.venv/bin/ruff check app/config.py tests/autonomous/test_config_autonomous_defaults.py && \
  ./.venv/bin/mypy app/config.py
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/config.py api/tests/autonomous/test_config_autonomous_defaults.py && \
  git commit -s -m "feat(m4): autonomous_default_max_cost_usd config setting (default \$5)

Global fallback cap for autonomous sessions whose spawning trigger
(watch/schedule) did not specify max_cost_usd. Env-overridable via
LQ_AI_AUTONOMOUS_DEFAULT_MAX_COST_USD. Mirrors gateway.yaml default.

Refs M4-D2 real-executor-work design §5

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: ORM models + Pydantic schemas — `max_cost_usd` on watch + schedule

**Files:**
- Modify: `api/app/models/autonomous.py`
- Modify: `api/app/schemas/autonomous.py`

- [ ] **Step 1: Write the failing test**

`api/tests/autonomous/test_watch_schedule_max_cost_field.py`:

```python
from decimal import Decimal
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.autonomous import AutonomousSchedule, AutonomousWatch
from app.schemas.autonomous import (
    AutonomousScheduleCreate,
    AutonomousScheduleRead,
    AutonomousWatchCreate,
    AutonomousWatchRead,
)


def test_watch_create_schema_accepts_max_cost_usd() -> None:
    body = AutonomousWatchCreate(
        knowledge_base_id=uuid.uuid4(),
        max_cost_usd=Decimal("0.50"),
    )
    assert body.max_cost_usd == Decimal("0.50")


def test_watch_create_schema_default_max_cost_is_none() -> None:
    body = AutonomousWatchCreate(knowledge_base_id=uuid.uuid4())
    assert body.max_cost_usd is None


def test_schedule_create_schema_accepts_max_cost_usd() -> None:
    body = AutonomousScheduleCreate(
        cron_expr="*/5 * * * *",
        max_cost_usd=Decimal("0.10"),
    )
    assert body.max_cost_usd == Decimal("0.10")


@pytest.mark.asyncio
async def test_watch_model_round_trips_max_cost_usd(db_session: AsyncSession, test_user) -> None:
    # test_user fixture: assumed to exist from conftest (mirror existing tests)
    kb_id = uuid.uuid4()  # not FK-checked here; conftest may need a real KB
    watch = AutonomousWatch(
        user_id=test_user.id,
        knowledge_base_id=kb_id,
        enabled=True,
        max_cost_usd=Decimal("0.25"),
    )
    db_session.add(watch)
    await db_session.flush()
    await db_session.refresh(watch)
    assert watch.max_cost_usd == Decimal("0.25")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_watch_schedule_max_cost_field.py -v
```

Expected: FAIL — Pydantic model doesn't have `max_cost_usd` and ORM model doesn't accept it.

- [ ] **Step 3: Add the column to the ORM models**

In `api/app/models/autonomous.py`, add to `AutonomousWatch` near the other Mapped columns:

```python
from decimal import Decimal
# ... existing imports ...

class AutonomousWatch(Base):
    # ... existing columns ...
    max_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4),
        nullable=True,
    )
```

And the same field on `AutonomousSchedule`. Match the existing column style (the file already uses `Numeric(10, 4)` for `autonomous_sessions.max_cost_usd` — mirror it).

- [ ] **Step 4: Add the Pydantic field**

In `api/app/schemas/autonomous.py`, add to BOTH `AutonomousWatchCreate` and `AutonomousWatchUpdate` and `AutonomousWatchRead`, and the same three for Schedule:

```python
from decimal import Decimal
# ... existing imports ...

class AutonomousWatchCreate(BaseModel):
    knowledge_base_id: uuid.UUID
    playbook_id: uuid.UUID | None = None
    skill_ref: str | None = None
    project_id: uuid.UUID | None = None
    enabled: bool = True
    max_cost_usd: Decimal | None = None  # NEW
```

Mirror in `AutonomousWatchUpdate`, `AutonomousWatchRead`, `AutonomousScheduleCreate`, `AutonomousScheduleUpdate`, `AutonomousScheduleRead`. `Read` schemas use `Decimal | None` (the DB value, may be NULL).

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_watch_schedule_max_cost_field.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Format + lint + type-check**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/ruff format app/models/autonomous.py app/schemas/autonomous.py tests/autonomous/test_watch_schedule_max_cost_field.py && \
  ./.venv/bin/ruff check app/models/autonomous.py app/schemas/autonomous.py tests/autonomous/test_watch_schedule_max_cost_field.py && \
  ./.venv/bin/mypy app/models/autonomous.py app/schemas/autonomous.py
```

- [ ] **Step 7: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/models/autonomous.py api/app/schemas/autonomous.py api/tests/autonomous/test_watch_schedule_max_cost_field.py && \
  git commit -s -m "feat(m4): max_cost_usd field on AutonomousWatch + AutonomousSchedule

ORM column + Pydantic Create/Update/Read schemas. NULL allowed; spawn
paths in subsequent tasks fall back to settings.autonomous_default_max_cost_usd
when unset. Mirrors the existing autonomous_sessions.max_cost_usd column.

Refs M4-D2 real-executor-work design §5

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Watch + Schedule endpoints persist + surface `max_cost_usd`

**Files:**
- Modify: `api/app/api/autonomous.py`

- [ ] **Step 1: Write the failing API tests**

`api/tests/autonomous/test_watch_schedule_max_cost_endpoints.py`:

```python
from decimal import Decimal

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_watch_with_max_cost_usd_round_trips(
    api_client: AsyncClient, auth_headers, test_kb_id
) -> None:
    resp = await api_client.post(
        "/api/v1/autonomous/watches",
        headers=auth_headers,
        json={"knowledge_base_id": str(test_kb_id), "max_cost_usd": "0.50"},
    )
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert Decimal(body["max_cost_usd"]) == Decimal("0.50")


@pytest.mark.asyncio
async def test_patch_watch_max_cost_usd(
    api_client: AsyncClient, auth_headers, test_kb_id
) -> None:
    create = await api_client.post(
        "/api/v1/autonomous/watches",
        headers=auth_headers,
        json={"knowledge_base_id": str(test_kb_id)},
    )
    watch_id = create.json()["id"]
    patched = await api_client.patch(
        f"/api/v1/autonomous/watches/{watch_id}",
        headers=auth_headers,
        json={"max_cost_usd": "0.10"},
    )
    assert patched.status_code == 200
    assert Decimal(patched.json()["max_cost_usd"]) == Decimal("0.10")


@pytest.mark.asyncio
async def test_create_schedule_with_max_cost_usd_round_trips(
    api_client: AsyncClient, auth_headers
) -> None:
    resp = await api_client.post(
        "/api/v1/autonomous/schedules",
        headers=auth_headers,
        json={"cron_expr": "0 9 * * *", "max_cost_usd": "0.25"},
    )
    assert resp.status_code in (200, 201)
    assert Decimal(resp.json()["max_cost_usd"]) == Decimal("0.25")
```

(The `api_client`, `auth_headers`, `test_kb_id` fixtures come from the existing conftest — check `api/tests/autonomous/conftest.py` and `api/tests/conftest.py` for the established fixture names; adapt the test if names differ.)

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_watch_schedule_max_cost_endpoints.py -v
```

Expected: FAIL — the existing endpoints don't read or write `max_cost_usd`.

- [ ] **Step 3: Update the watch + schedule endpoint handlers**

In `api/app/api/autonomous.py`, find the watch create handler (search for `POST /watches` or `@router.post("/watches"...)`); persist `body.max_cost_usd` to the ORM row. Same for PATCH /watches/{id}, POST /schedules, PATCH /schedules/{id}. The Read schemas already include the field (Task 3), so GET responses surface it automatically.

```python
# In create_watch:
watch = AutonomousWatch(
    user_id=current_user.id,
    knowledge_base_id=body.knowledge_base_id,
    playbook_id=body.playbook_id,
    skill_ref=body.skill_ref,
    project_id=body.project_id,
    enabled=body.enabled,
    max_cost_usd=body.max_cost_usd,  # NEW
)

# In patch_watch:
if body.max_cost_usd is not None:
    watch.max_cost_usd = body.max_cost_usd
# (or use Pydantic's model_dump(exclude_unset=True) pattern if that's the file's style)
```

Same for schedule. Read the file's existing patch idiom before editing — match it.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_watch_schedule_max_cost_endpoints.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the wider autonomous endpoint tests to confirm no regression**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/ -q
```

Expected: all green (existing tests should be unaffected — additive change).

- [ ] **Step 6: Format + lint + type-check**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/ruff format app/api/autonomous.py tests/autonomous/test_watch_schedule_max_cost_endpoints.py && \
  ./.venv/bin/ruff check app/api/autonomous.py tests/autonomous/test_watch_schedule_max_cost_endpoints.py && \
  ./.venv/bin/mypy app/api/autonomous.py
```

- [ ] **Step 7: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/api/autonomous.py api/tests/autonomous/test_watch_schedule_max_cost_endpoints.py && \
  git commit -s -m "feat(m4): /watches + /schedules endpoints persist + surface max_cost_usd

POST + PATCH on both routes accept Decimal max_cost_usd; GET surfaces it
via the Read schemas. Watch/Schedule update preserves existing partial-update
semantics. OpenAPI surfaces the new field automatically.

Refs M4-D2 real-executor-work design §5

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Spawn paths always set `session.max_cost_usd` (per-trigger or default)

**Files:**
- Modify: `api/app/autonomous/watch_trigger.py`
- Modify: `api/app/workers/autonomous_worker.py`

- [ ] **Step 1: Write the failing tests**

`api/tests/autonomous/test_spawn_max_cost_usd.py`:

```python
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.watch_trigger import fire_watches_for_kb
from app.models.autonomous import AutonomousSession, AutonomousWatch


@pytest.mark.asyncio
async def test_watch_spawn_threads_per_trigger_max_cost(
    db_session: AsyncSession, opted_in_user, test_kb, test_file
) -> None:
    """A watch with max_cost_usd set spawns a session with that cap."""
    watch = AutonomousWatch(
        user_id=opted_in_user.id,
        knowledge_base_id=test_kb.id,
        enabled=True,
        max_cost_usd=Decimal("0.10"),
    )
    db_session.add(watch)
    await db_session.flush()

    count = await fire_watches_for_kb(db_session, kb_id=test_kb.id, file_id=test_file.id)
    assert count == 1

    sessions = (await db_session.execute(
        select(AutonomousSession).where(AutonomousSession.user_id == opted_in_user.id)
    )).scalars().all()
    assert len(sessions) == 1
    assert sessions[0].max_cost_usd == Decimal("0.10")


@pytest.mark.asyncio
async def test_watch_spawn_falls_back_to_default_when_unset(
    db_session: AsyncSession, opted_in_user, test_kb, test_file, monkeypatch
) -> None:
    """A watch with max_cost_usd=NULL spawns a session with the config default; never None."""
    watch = AutonomousWatch(
        user_id=opted_in_user.id,
        knowledge_base_id=test_kb.id,
        enabled=True,
        max_cost_usd=None,
    )
    db_session.add(watch)
    await db_session.flush()

    await fire_watches_for_kb(db_session, kb_id=test_kb.id, file_id=test_file.id)
    session = (await db_session.execute(
        select(AutonomousSession).where(AutonomousSession.user_id == opted_in_user.id)
    )).scalar_one()
    # default from settings; matches Task 2's default of $5.00
    assert session.max_cost_usd == Decimal("5.00")
    assert session.max_cost_usd is not None
```

Add the analogous test for the schedule sweep — call into `_run_schedule_sweep` (or whichever internal helper the worker exposes; mirror `api/tests/autonomous/test_idle_watchdog.py`'s pattern for invoking the sweep directly with `db_session` + an injected `now`).

- [ ] **Step 2: Run to verify the tests fail**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_spawn_max_cost_usd.py -v
```

Expected: FAIL — the current spawn path doesn't set `max_cost_usd`.

- [ ] **Step 3: Update `fire_watches_for_kb`**

In `api/app/autonomous/watch_trigger.py`, in the AutonomousSession construction:

```python
from decimal import Decimal
from app.config import get_settings

# inside fire_watches_for_kb, where the session is created:
settings = get_settings()
session = AutonomousSession(
    user_id=watch.user_id,
    trigger_kind="watch",
    trigger_ref=watch.id,
    status="running",
    current_phase="intake",
    halt_state="running",
    max_cost_usd=watch.max_cost_usd or settings.autonomous_default_max_cost_usd,  # NEW: never None
    params={"kb_id": str(kb_id), "file_id": str(file_id), **(
        {"playbook_id": str(watch.playbook_id)} if watch.playbook_id else {}
    ), **(
        {"skill_ref": watch.skill_ref} if watch.skill_ref else {}
    )},
)
```

Match the file's existing style; if `AutonomousSession` already gets some of these fields elsewhere, only ADD the `max_cost_usd=` line.

- [ ] **Step 4: Update `_run_schedule_sweep`**

In `api/app/workers/autonomous_worker.py`, in the schedule dispatcher's session-creation block:

```python
settings = get_settings()
session = AutonomousSession(
    user_id=schedule.user_id,
    trigger_kind="schedule",
    trigger_ref=schedule.id,
    status="running",
    current_phase="intake",
    halt_state="running",
    max_cost_usd=schedule.max_cost_usd or settings.autonomous_default_max_cost_usd,  # NEW
    params={
        "kb_id": str(schedule.target_kb_id) if schedule.target_kb_id else None,
        "playbook_id": str(schedule.playbook_id) if schedule.playbook_id else None,
        "skill_ref": schedule.skill_ref,
        "since": schedule.last_run_at.isoformat() if schedule.last_run_at else None,  # NEW
    },
)
```

The new `"since"` key in params is what Task 10's intake_node reads to scope retrieve_chunks for schedule triggers. `None` means "first tick — no prior baseline" (handled by Task 10).

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_spawn_max_cost_usd.py -v
```

Expected: tests pass.

- [ ] **Step 6: Run the wider suite to confirm no regression**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/ -q
```

Expected: all green.

- [ ] **Step 7: Format + lint + type-check**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/ruff format app/autonomous/watch_trigger.py app/workers/autonomous_worker.py tests/autonomous/test_spawn_max_cost_usd.py && \
  ./.venv/bin/ruff check app/autonomous/watch_trigger.py app/workers/autonomous_worker.py tests/autonomous/test_spawn_max_cost_usd.py && \
  ./.venv/bin/mypy app/autonomous/watch_trigger.py app/workers/autonomous_worker.py
```

- [ ] **Step 8: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/autonomous/watch_trigger.py api/app/workers/autonomous_worker.py api/tests/autonomous/test_spawn_max_cost_usd.py && \
  git commit -s -m "feat(m4): spawn paths always set session.max_cost_usd (per-trigger or default)

fire_watches_for_kb + _run_schedule_sweep now ALWAYS set max_cost_usd
on the spawned session — per-trigger value when set, else the config
default (~\$5). Closes the no-cap runaway gap: R4 can now trip in
production. Schedule sweep also threads last_run_at into params['since']
so intake (Task 10) can scope retrieve_chunks to docs since last run.

Refs M4-D2 real-executor-work design §5

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `_handle_retrieve_chunks` accepts optional `file_id` + `since` (additive)

**Files:**
- Modify: `api/app/autonomous/guard.py`
- Create: `api/tests/autonomous/test_retrieve_chunks_scope.py`

- [ ] **Step 1: Write the failing tests**

`api/tests/autonomous/test_retrieve_chunks_scope.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.guard import _handle_retrieve_chunks


@pytest.mark.asyncio
async def test_retrieve_chunks_query_path_unchanged(
    db_session: AsyncSession, kb_with_one_indexed_file
) -> None:
    """Existing query-based hybrid search path keeps working."""
    result = await _handle_retrieve_chunks(
        {"kb_id": str(kb_with_one_indexed_file.kb_id), "query": "test"},
        db=db_session,
    )
    assert "summary" in result.data
    assert "chunks" in result.data
    assert isinstance(result.data["summary"]["chunk_count"], int)


@pytest.mark.asyncio
async def test_retrieve_chunks_by_file_id(
    db_session: AsyncSession, kb_with_one_indexed_file
) -> None:
    """file_id scope: return only that file's chunks; no query needed."""
    result = await _handle_retrieve_chunks(
        {
            "kb_id": str(kb_with_one_indexed_file.kb_id),
            "file_id": str(kb_with_one_indexed_file.file_id),
        },
        db=db_session,
    )
    assert result.data["summary"]["chunk_count"] > 0
    for chunk in result.data["chunks"]:
        assert chunk["document_id"] == str(kb_with_one_indexed_file.file_id)


@pytest.mark.asyncio
async def test_retrieve_chunks_since_scope(
    db_session: AsyncSession, kb_with_old_and_new_files
) -> None:
    """since + kb_id: return only chunks of files attached after `since`."""
    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    result = await _handle_retrieve_chunks(
        {
            "kb_id": str(kb_with_old_and_new_files.kb_id),
            "since": cutoff.isoformat(),
        },
        db=db_session,
    )
    returned_file_ids = {c["document_id"] for c in result.data["chunks"]}
    assert str(kb_with_old_and_new_files.new_file_id) in returned_file_ids
    assert str(kb_with_old_and_new_files.old_file_id) not in returned_file_ids
```

(The `kb_with_one_indexed_file` and `kb_with_old_and_new_files` fixtures will need to be added to `api/tests/autonomous/conftest.py`; they create a KB + file + ingested chunks with controlled `attached_at` timestamps. Mirror the fixture pattern in `api/tests/integration/` if one already builds KBs with chunks.)

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_retrieve_chunks_scope.py -v
```

Expected: `test_retrieve_chunks_query_path_unchanged` may pass (existing behavior); `test_retrieve_chunks_by_file_id` and `test_retrieve_chunks_since_scope` FAIL because params are ignored.

- [ ] **Step 3: Extend `_handle_retrieve_chunks`**

In `api/app/autonomous/guard.py`, change `_handle_retrieve_chunks` so:

```python
async def _handle_retrieve_chunks(
    params: dict[str, Any],
    *,
    db: AsyncSession,
) -> ToolResult:
    """Handle retrieve_chunks — hybrid KB search OR file-scoped OR since-scoped fetch.

    Modes (mutually exclusive at the highest level):
    1. ``query`` (+ optional ``query_embedding``, ``top_k``, ``alpha``):
       hybrid semantic+FTS search. Existing path, unchanged.
    2. ``file_id``: return the file's chunks directly (no semantic
       ranking), in ``char_offset_start`` order. Used by watch-triggered
       intake to fetch the arriving document's chunks.
    3. ``since`` + ``kb_id`` (no query): return chunks of files in the KB
       whose ``KnowledgeBaseFile.attached_at`` > ``since`` (an ISO-8601
       string or aware datetime), in ``attached_at`` order. Used by
       schedule-triggered intake for the "new since last_run_at" path.

    All modes return the same shape: ``data["summary"]`` (counts + IDs
    + offsets, audit-safe) and ``data["chunks"]`` (full text for the
    node's LLM use).
    """
    from sqlalchemy import select
    from app.models.document import DocumentChunk  # or wherever the chunk model lives
    from app.models.knowledge import KnowledgeBaseFile

    kb_id_raw = params.get("kb_id")
    file_id_raw = params.get("file_id")
    since_raw = params.get("since")
    query = params.get("query")

    if file_id_raw is not None:
        # Mode 2: file-scoped fetch.
        file_id = uuid.UUID(str(file_id_raw))
        rows = (await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.file_id == file_id)
            .order_by(DocumentChunk.char_offset_start)
        )).scalars().all()
        return _format_chunks_result(rows, file_id_field="file_id")

    if since_raw is not None and kb_id_raw is not None:
        # Mode 3: since-scoped fetch — chunks of files attached after `since`.
        from datetime import datetime
        if isinstance(since_raw, str):
            since_dt = datetime.fromisoformat(since_raw)
        else:
            since_dt = since_raw
        kb_id = uuid.UUID(str(kb_id_raw))
        rows = (await db.execute(
            select(DocumentChunk)
            .join(KnowledgeBaseFile, KnowledgeBaseFile.file_id == DocumentChunk.file_id)
            .where(KnowledgeBaseFile.kb_id == kb_id)
            .where(KnowledgeBaseFile.attached_at > since_dt)
            .order_by(KnowledgeBaseFile.attached_at, DocumentChunk.char_offset_start)
        )).scalars().all()
        return _format_chunks_result(rows, file_id_field="file_id")

    # Mode 1: query-based hybrid search (existing path — unchanged).
    if query is None:
        raise ValueError("_handle_retrieve_chunks: provide one of query, file_id, or since+kb_id")
    return await _handle_retrieve_chunks_query(params, db=db)
```

Refactor the existing body into a private `_handle_retrieve_chunks_query(params, db=db)` and add a `_format_chunks_result(rows, file_id_field)` helper that builds the summary + chunks payload identically to the existing query path (DRY).

**Important:** verify the exact chunk-model module path before editing — check `api/app/models/` for `DocumentChunk` (or whatever the existing `hybrid_search` joins). Match what `_hydrate_chunks` in `api/app/knowledge/retrieval.py` uses. Do NOT invent column names; read the model.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_retrieve_chunks_scope.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Re-run the full brakes suite — verify chokepoint behavior unchanged**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_brakes.py tests/autonomous/test_idle_watchdog.py tests/autonomous/test_optin_gate.py -q
```

Expected: 31 passed (no regression in brake behavior).

- [ ] **Step 6: Format + lint + type-check**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/ruff format app/autonomous/guard.py tests/autonomous/test_retrieve_chunks_scope.py && \
  ./.venv/bin/ruff check app/autonomous/guard.py tests/autonomous/test_retrieve_chunks_scope.py && \
  ./.venv/bin/mypy app/autonomous/guard.py
```

- [ ] **Step 7: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/autonomous/guard.py api/tests/autonomous/test_retrieve_chunks_scope.py && \
  git commit -s -m "feat(m4): retrieve_chunks gains file_id + since scopes (additive)

_handle_retrieve_chunks now supports three modes: (1) existing query
hybrid search, (2) file_id direct fetch (watch intake), (3) since+kb_id
fetch of docs attached after a cutoff (schedule intake). The existing
query path is unchanged. Privacy-safe summary shape preserved across
all three modes.

Refs M4-D2 real-executor-work design §6

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `prompts.py` — assemble analysis messages from skill/playbook + chunks

**Files:**
- Create: `api/app/autonomous/prompts.py`
- Create: `api/tests/autonomous/test_prompts.py`

The prompts module's single responsibility: take a session's target (`skill_ref` or `playbook_id`) + the retrieved chunks + the structured-output instruction tail, and return a `list[dict]` of `{role, content}` messages ready for `run_skill`/`run_playbook` via the chokepoint.

- [ ] **Step 1: Write the failing tests**

`api/tests/autonomous/test_prompts.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.prompts import (
    STRUCTURED_OUTPUT_INSTRUCTION,
    assemble_analysis_messages,
)
from app.models.autonomous import AutonomousSession


@pytest.mark.asyncio
async def test_assemble_messages_for_skill_ref(
    db_session: AsyncSession, session_with_skill_ref, sample_chunks
) -> None:
    msgs = await assemble_analysis_messages(
        session_with_skill_ref, chunks=sample_chunks, db=db_session
    )
    # Shape: list of role/content dicts
    assert all("role" in m and "content" in m for m in msgs)
    # System prompt carries the skill's SKILL.md
    assert msgs[0]["role"] == "system"
    assert "nda-review-mutual" in msgs[0]["content"] or len(msgs[0]["content"]) > 100
    # The structured-output instruction tail is appended (system or final user msg)
    full = "\n".join(m["content"] for m in msgs)
    assert STRUCTURED_OUTPUT_INSTRUCTION in full
    # Chunks reach the model
    assert any("CHUNK" in m["content"] or "[chunk_id" in m["content"] for m in msgs)


@pytest.mark.asyncio
async def test_assemble_messages_for_playbook_id(
    db_session: AsyncSession, session_with_playbook_id, sample_chunks
) -> None:
    msgs = await assemble_analysis_messages(
        session_with_playbook_id, chunks=sample_chunks, db=db_session
    )
    assert msgs[0]["role"] == "system"
    # The playbook definition is in the system content
    assert len(msgs[0]["content"]) > 50


@pytest.mark.asyncio
async def test_assemble_messages_no_target_raises(
    db_session: AsyncSession, session_without_target, sample_chunks
) -> None:
    with pytest.raises(ValueError, match="no skill_ref or playbook_id"):
        await assemble_analysis_messages(
            session_without_target, chunks=sample_chunks, db=db_session
        )


def test_structured_output_instruction_carries_schema_keys() -> None:
    """The instruction tail names every key the drafting node parses."""
    inst = STRUCTURED_OUTPUT_INSTRUCTION
    assert "findings" in inst
    assert "suggested_memories" in inst
    assert "suggested_precedents" in inst
    assert "privilege_concerns" in inst
    assert "scope_concerns" in inst
```

(The session and chunks fixtures need to be added to `tests/autonomous/conftest.py`.)

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_prompts.py -v
```

Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `prompts.py`**

```python
"""Prompt assembly for the autonomous executor's analysis phase — M4 real-work.

Single responsibility: take an :class:`AutonomousSession` whose ``params``
identifies a target (``skill_ref`` OR ``playbook_id``) + the retrieved chunks,
and produce a ``list[dict]`` of ``{role, content}`` messages ready for the
chokepoint's :func:`_handle_gateway_inference` (which expects ``model`` +
``messages`` in its params).

The model itself is chosen at the call site (the analysis node passes
``settings.autonomous_default_model`` or the skill/playbook's pinned model);
this module owns prompt assembly only.

Skill targets: resolved via the global ``SkillRegistry`` (mirroring
``api/app/api/internal.py:get_skill_internal``). The skill's ``SKILL.md``
content becomes the system prompt.

Playbook targets: loaded via ``select(Playbook).where(Playbook.id == ...)``
mirroring ``api/app/playbooks/executor.py:205``. The playbook's definition
(positions, instructions) is rendered to a system prompt.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.autonomous import AutonomousSession
from app.models.playbook import Playbook
from app.skills import get_registry  # see Step 4 below

STRUCTURED_OUTPUT_INSTRUCTION = """\
After your analysis, return a final JSON object with this exact shape (and \
nothing after it):

{
  "findings": [
    {"title": "...", "summary": "...", "severity": "info|warn|critical",
     "source_chunk_ids": ["..."]}
  ],
  "suggested_memories": [
    {"category": "...", "content": "...", "rationale": "..."}
  ],
  "suggested_precedents": [
    {"pattern_kind": "...", "summary": "..."}
  ],
  "privilege_concerns": ["..."],
  "scope_concerns": ["..."]
}

All arrays may be empty. Wrap the JSON in a ```json fenced block. \
The JSON is parsed by the autonomous executor; everything else in your \
response is logged as a finding only if the JSON cannot be parsed.
"""


async def assemble_analysis_messages(
    session: AutonomousSession,
    *,
    chunks: list[dict[str, Any]],
    db: AsyncSession,
) -> list[dict[str, str]]:
    """Build the analysis-phase ``messages`` payload.

    Resolves the session's target (``skill_ref`` or ``playbook_id`` from
    ``session.params``) into a system prompt, formats the retrieved
    chunks as a user message, and appends the structured-output
    instruction tail.

    Raises ``ValueError`` if neither ``skill_ref`` nor ``playbook_id`` is set.
    """
    params = session.params or {}
    skill_ref = params.get("skill_ref")
    playbook_id_raw = params.get("playbook_id")

    if skill_ref:
        system = await _load_skill_system_prompt(skill_ref)
    elif playbook_id_raw:
        system = await _load_playbook_system_prompt(uuid.UUID(str(playbook_id_raw)), db)
    else:
        raise ValueError(
            "assemble_analysis_messages: session has no skill_ref or playbook_id in params"
        )

    user_chunks = _format_chunks_as_user_content(chunks)
    return [
        {"role": "system", "content": system + "\n\n" + STRUCTURED_OUTPUT_INSTRUCTION},
        {"role": "user", "content": user_chunks},
    ]


async def _load_skill_system_prompt(skill_ref: str) -> str:
    """Resolve a skill_ref via the global SkillRegistry; return its SKILL.md body."""
    registry = get_registry()
    skill = registry.get_skill(skill_ref)
    if skill is None:
        raise ValueError(f"skill not found in registry: {skill_ref!r}")
    # The exact attribute name for the SKILL.md body depends on the
    # SkillRecord shape — match what get_skill_internal at
    # api/app/api/internal.py:185 uses. Examples that have worked:
    #   skill.content / skill.body / skill.files["SKILL.md"]
    # Pick the one that exists; the test in Step 1 catches mismatch.
    return skill.body  # adjust to actual attribute


async def _load_playbook_system_prompt(playbook_id: uuid.UUID, db: AsyncSession) -> str:
    """Load a Playbook + its positions; render to a system prompt."""
    playbook = (await db.execute(
        select(Playbook).where(Playbook.id == playbook_id).options(selectinload(Playbook.positions))
    )).scalar_one_or_none()
    if playbook is None:
        raise ValueError(f"playbook not found: {playbook_id}")
    return _render_playbook(playbook)


def _render_playbook(playbook: Playbook) -> str:
    """Render a Playbook + its positions to a single system prompt string."""
    lines: list[str] = []
    lines.append(f"# Playbook: {playbook.name}")
    if getattr(playbook, "description", None):
        lines.append(playbook.description)
    lines.append("")
    lines.append("## Positions to evaluate")
    for pos in playbook.positions or []:
        lines.append(f"- {pos.title or pos.id}: {getattr(pos, 'description', '')}")
    return "\n".join(lines)


def _format_chunks_as_user_content(chunks: list[dict[str, Any]]) -> str:
    """Render retrieved chunks as a single user-role message."""
    if not chunks:
        return "[No chunks retrieved for this session.]"
    out: list[str] = ["Document chunks to analyze:\n"]
    for c in chunks:
        out.append(f"[chunk_id {c.get('chunk_id')} | file_id {c.get('document_id')}]")
        out.append(c.get("content", ""))
        out.append("")
    return "\n".join(out)
```

The `get_registry()` import needs to exist — check `api/app/skills/__init__.py` for the public name (`MutableSkillRegistry` is in the registry module; whichever singleton holds the loaded registry is the right import). If no `get_registry` helper exists, add one OR import the module-level mutable singleton the same way `api/app/api/internal.py` does it. Match the existing pattern.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_prompts.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Format + lint + type-check**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/ruff format app/autonomous/prompts.py tests/autonomous/test_prompts.py && \
  ./.venv/bin/ruff check app/autonomous/prompts.py tests/autonomous/test_prompts.py && \
  ./.venv/bin/mypy app/autonomous/prompts.py
```

- [ ] **Step 6: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/autonomous/prompts.py api/tests/autonomous/test_prompts.py && \
  git commit -s -m "feat(m4): prompts.py — assemble analysis messages from skill/playbook + chunks

Single-responsibility module: resolves session.params skill_ref via
SkillRegistry or playbook_id via select(Playbook), renders the target
to a system prompt, formats retrieved chunks as the user message, and
appends the structured-output JSON instruction tail. Used by Task 11's
analysis_node.

Refs M4-D2 real-executor-work design §3-§4

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `structured_output.py` — tolerant JSON parser

**Files:**
- Create: `api/app/autonomous/structured_output.py`
- Create: `api/tests/autonomous/test_structured_output.py`

- [ ] **Step 1: Write the failing tests**

`api/tests/autonomous/test_structured_output.py`:

```python
from app.autonomous.structured_output import (
    StructuredResult,
    parse_structured_output,
)


def test_parse_well_formed_json() -> None:
    raw = """Here is my analysis.
```json
{
  "findings": [{"title": "F1", "summary": "S1", "severity": "info", "source_chunk_ids": []}],
  "suggested_memories": [{"category": "preference", "content": "C", "rationale": "R"}],
  "suggested_precedents": [{"pattern_kind": "clause", "summary": "P"}],
  "privilege_concerns": [],
  "scope_concerns": ["minor"]
}
```"""
    r = parse_structured_output(raw)
    assert r.is_structured is True
    assert len(r.findings) == 1
    assert r.findings[0]["title"] == "F1"
    assert len(r.suggested_memories) == 1
    assert len(r.suggested_precedents) == 1
    assert r.privilege_concerns == []
    assert r.scope_concerns == ["minor"]


def test_parse_json_without_fences() -> None:
    raw = '{"findings": [], "suggested_memories": [], "suggested_precedents": [], ' \
          '"privilege_concerns": [], "scope_concerns": []}'
    r = parse_structured_output(raw)
    assert r.is_structured is True
    assert r.findings == []


def test_parse_malformed_returns_unstructured_with_raw() -> None:
    raw = "I couldn't follow the format instructions, sorry."
    r = parse_structured_output(raw)
    assert r.is_structured is False
    assert r.raw_content == raw


def test_parse_empty_content_is_unstructured() -> None:
    r = parse_structured_output(None)
    assert r.is_structured is False
    assert r.raw_content == ""


def test_parse_partial_json_missing_arrays_defaults_to_empty() -> None:
    raw = '```json\n{"findings": [{"title": "X", "summary": "Y", "severity": "warn", "source_chunk_ids": []}]}\n```'
    r = parse_structured_output(raw)
    assert r.is_structured is True
    assert len(r.findings) == 1
    # Missing arrays default to []
    assert r.suggested_memories == []
    assert r.suggested_precedents == []
    assert r.privilege_concerns == []
    assert r.scope_concerns == []
```

- [ ] **Step 2: Run to verify the tests fail**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_structured_output.py -v
```

Expected: FAIL (module not found).

- [ ] **Step 3: Implement `structured_output.py`**

```python
"""Tolerant structured-output parser for the autonomous executor — M4 real-work.

Single responsibility: parse the analysis call's response content into a
:class:`StructuredResult`. Tolerant by design — a malformed response
becomes a graceful ``is_structured=False`` result with ``raw_content``
preserved, NOT an exception. The drafting node uses ``is_structured`` to
decide whether to dispatch per-finding/memory/precedent calls or a single
``emit_finding`` fallback with the raw text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class StructuredResult:
    is_structured: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    suggested_memories: list[dict[str, Any]] = field(default_factory=list)
    suggested_precedents: list[dict[str, Any]] = field(default_factory=list)
    privilege_concerns: list[str] = field(default_factory=list)
    scope_concerns: list[str] = field(default_factory=list)
    raw_content: str = ""

    @classmethod
    def unstructured(cls, raw: str | None) -> "StructuredResult":
        return cls(is_structured=False, raw_content=raw or "")


def parse_structured_output(content: str | None) -> StructuredResult:
    """Parse the analysis call's response into a :class:`StructuredResult`.

    Order of attempts:
    1. Find a ```json ... ``` (or unlabeled ```) fenced JSON block; parse it.
    2. Try ``json.loads`` on the whole content.
    3. Return :meth:`StructuredResult.unstructured` with the raw content.

    A successfully-parsed result fills missing arrays with ``[]``.
    """
    if not content:
        return StructuredResult.unstructured(content)

    parsed: dict[str, Any] | None = None

    match = _FENCED_JSON_RE.search(content)
    if match:
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            parsed = None

    if parsed is None:
        try:
            parsed = json.loads(content.strip())
        except json.JSONDecodeError:
            return StructuredResult.unstructured(content)

    if not isinstance(parsed, dict):
        return StructuredResult.unstructured(content)

    return StructuredResult(
        is_structured=True,
        findings=list(parsed.get("findings") or []),
        suggested_memories=list(parsed.get("suggested_memories") or []),
        suggested_precedents=list(parsed.get("suggested_precedents") or []),
        privilege_concerns=list(parsed.get("privilege_concerns") or []),
        scope_concerns=list(parsed.get("scope_concerns") or []),
        raw_content=content,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_structured_output.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Format + lint + type-check**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/ruff format app/autonomous/structured_output.py tests/autonomous/test_structured_output.py && \
  ./.venv/bin/ruff check app/autonomous/structured_output.py tests/autonomous/test_structured_output.py && \
  ./.venv/bin/mypy app/autonomous/structured_output.py
```

- [ ] **Step 6: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/autonomous/structured_output.py api/tests/autonomous/test_structured_output.py && \
  git commit -s -m "feat(m4): structured_output.py — tolerant analysis-response parser

Parses {findings, suggested_memories, suggested_precedents, privilege_concerns,
scope_concerns} from the analysis call's response. ```json fences are stripped;
unparseable content returns is_structured=False with raw_content preserved so
the drafting node can fall back to a single emit_finding without raising.

Refs M4-D2 real-executor-work design §4

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Wire `intake_node` — watch path (`file_id` scope)

**Files:**
- Modify: `api/app/autonomous/nodes.py`

- [ ] **Step 1: Write the failing test**

`api/tests/autonomous/test_executor_real_work.py` (we add to this file across multiple tasks):

```python
import pytest
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.nodes import make_intake_node
from app.autonomous.state import AutonomousSessionState


@pytest.mark.asyncio
async def test_intake_watch_path_scopes_retrieve_chunks_by_file_id(
    db_session: AsyncSession, running_watch_session, mock_gateway
) -> None:
    """Watch session (kb_id+file_id in params, no since): intake calls
    retrieve_chunks scoped to the file_id."""
    node = make_intake_node(db_session, mock_gateway)
    state: AutonomousSessionState = {
        "session_id": running_watch_session.id,
        "kb_id": str(running_watch_session.params["kb_id"]),
        "file_id": str(running_watch_session.params["file_id"]),
        "query": None,
        "since": None,
    }
    result = await node(state)
    # state["retrieved_chunks"] populated; no semantic query was used
    assert "retrieved_chunks" in result
    assert result.get("error") is None
```

(Fixture `running_watch_session`: creates an opted-in user + a watch + a session with `trigger_kind='watch'`, `params={kb_id, file_id}`. Add to conftest.)

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_executor_real_work.py::test_intake_watch_path_scopes_retrieve_chunks_by_file_id -v
```

Expected: FAIL — current intake reads `kb_id` + `query`, not `file_id`.

- [ ] **Step 3: Update `make_intake_node`**

In `api/app/autonomous/nodes.py`:

```python
async def intake_node(state: AutonomousSessionState) -> dict[str, Any]:
    session_id = state["session_id"]
    session = await db.get(AutonomousSession, session_id)
    if session is None:
        return {"error": f"session {session_id} not found in intake_node"}

    logger.info("autonomous.intake_node: entering",
                extra={"event": "autonomous_intake_enter", "session_id": session_id})
    await run_phase_transition(session, Phase.intake, db)
    await db.flush()

    updates: dict[str, Any] = {"current_phase": str(Phase.intake)}

    params = session.params or {}
    kb_id = params.get("kb_id")
    file_id = params.get("file_id")
    since = params.get("since")

    if file_id:
        # Watch path: scope to the arriving file's chunks.
        result = await guarded_tool_call(
            session,
            ToolIntent.retrieve_chunks,
            {"kb_id": str(kb_id) if kb_id else None, "file_id": str(file_id)},
            db, gateway,
        )
        updates["retrieved_chunks"] = result.data.get("chunks", [])
    # (Task 10 adds the since branch and the no-target branch.)

    return updates
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_executor_real_work.py::test_intake_watch_path_scopes_retrieve_chunks_by_file_id -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/autonomous/nodes.py api/tests/autonomous/test_executor_real_work.py && \
  git commit -s -m "feat(m4): intake_node — watch path scopes retrieve_chunks by file_id

Reads session.params (set by watch_trigger.fire_watches_for_kb) for kb_id +
file_id; calls retrieve_chunks with the file_id scope (Task 6 extension)
so the arriving document's chunks reach the analysis node.

Refs M4-D2 real-executor-work design §3

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Wire `intake_node` — schedule path (`since` scope + first-tick semantics)

**Files:**
- Modify: `api/app/autonomous/nodes.py`

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/autonomous/test_executor_real_work.py`:

```python
@pytest.mark.asyncio
async def test_intake_schedule_path_scopes_retrieve_chunks_by_since(
    db_session: AsyncSession, running_schedule_session_with_since, mock_gateway
) -> None:
    """Schedule session (kb_id+since in params): intake calls retrieve_chunks
    with the since scope so only new-since-last-run docs come back."""
    node = make_intake_node(db_session, mock_gateway)
    state = {
        "session_id": running_schedule_session_with_since.id,
        "kb_id": str(running_schedule_session_with_since.params["kb_id"]),
        "file_id": None,
        "query": None,
        "since": running_schedule_session_with_since.params["since"],
    }
    result = await node(state)
    assert "retrieved_chunks" in result
    # Only chunks of files attached after `since` (fixture invariant)


@pytest.mark.asyncio
async def test_intake_schedule_first_tick_empty_since_sets_no_baseline(
    db_session: AsyncSession, running_schedule_session_first_tick, mock_gateway
) -> None:
    """Schedule session with since=None (first cron tick): no docs retrieved;
    subsequent analysis emits a 'first tick — no prior baseline' finding."""
    node = make_intake_node(db_session, mock_gateway)
    state = {
        "session_id": running_schedule_session_first_tick.id,
        "kb_id": str(running_schedule_session_first_tick.params["kb_id"]),
        "file_id": None,
        "query": None,
        "since": None,
    }
    result = await node(state)
    assert result.get("retrieved_chunks") == []
    assert result.get("first_tick_no_baseline") is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_executor_real_work.py -v -k "schedule_path or first_tick"
```

- [ ] **Step 3: Extend `intake_node` with the schedule branch**

```python
# Inside intake_node, after the file_id branch:

elif kb_id and since:
    # Schedule path: scope to docs attached after `since` (last_run_at).
    result = await guarded_tool_call(
        session,
        ToolIntent.retrieve_chunks,
        {"kb_id": str(kb_id), "since": since},
        db, gateway,
    )
    updates["retrieved_chunks"] = result.data.get("chunks", [])

elif kb_id and not since and not file_id:
    # First-tick schedule (last_run_at was NULL at spawn): no baseline.
    # Don't retrieve anything; downstream nodes handle empty input.
    updates["retrieved_chunks"] = []
    updates["first_tick_no_baseline"] = True

else:
    # No target at all — degenerate session (test/manual). Stay empty;
    # delivery will still complete with an empty-findings notification.
    updates["retrieved_chunks"] = []
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_executor_real_work.py -v -k "schedule_path or first_tick"
```

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/autonomous/nodes.py api/tests/autonomous/test_executor_real_work.py && \
  git commit -s -m "feat(m4): intake_node — schedule path (since scope) + first-tick semantics

When session.params carries since (set by schedule sweep with last_run_at),
intake calls retrieve_chunks with the since scope so only docs attached after
the last run are analyzed. When since is NULL (first cron tick — no baseline),
intake records first_tick_no_baseline=True and skips retrieval; downstream
nodes handle empty input gracefully.

Refs M4-D2 real-executor-work design §3

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Wire `analysis_node` — guarded `run_skill`/`run_playbook` call

**Files:**
- Modify: `api/app/autonomous/nodes.py`

- [ ] **Step 1: Write the failing test**

Add to `api/tests/autonomous/test_executor_real_work.py`:

```python
@pytest.mark.asyncio
async def test_analysis_calls_run_skill_through_chokepoint(
    db_session: AsyncSession, running_watch_session, sample_chunks, mock_gateway
) -> None:
    """analysis_node assembles messages and makes one guarded run_skill call;
    the structured-output content is stored in state."""
    from unittest.mock import AsyncMock

    # Mock gateway returns a well-formed structured response.
    mock_gateway.chat_completion = AsyncMock(return_value=type("R", (), {
        "choices": [type("C", (), {
            "message": type("M", (), {"content": '```json\n{"findings": [{"title": "T", "summary": "S", "severity": "info", "source_chunk_ids": []}], "suggested_memories": [], "suggested_precedents": [], "privilege_concerns": [], "scope_concerns": []}\n```'})()
        })()],
        "usage": type("U", (), {"prompt_tokens": 10, "completion_tokens": 20})(),
    })())

    node = make_analysis_node(db_session, mock_gateway)
    state = {
        "session_id": running_watch_session.id,
        "retrieved_chunks": sample_chunks,
    }
    result = await node(state)
    assert mock_gateway.chat_completion.await_count == 1
    assert "analysis_content" in result
    assert "findings" in result["analysis_content"]  # structured JSON present
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_executor_real_work.py::test_analysis_calls_run_skill_through_chokepoint -v
```

Expected: FAIL — current analysis_node is a no-op.

- [ ] **Step 3: Update `make_analysis_node`**

```python
from app.autonomous.prompts import assemble_analysis_messages
from app.config import get_settings


def make_analysis_node(db, gateway=None):
    async def analysis_node(state):
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in analysis_node"}

        logger.info("autonomous.analysis_node: entering",
                    extra={"event": "autonomous_analysis_enter", "session_id": session_id})
        await run_phase_transition(session, Phase.analysis, db)
        await db.flush()

        chunks = state.get("retrieved_chunks") or []
        first_tick = state.get("first_tick_no_baseline", False)

        if first_tick:
            # Schedule's first cron tick — no docs to analyze yet.
            return {"current_phase": str(Phase.analysis),
                    "analysis_content": None,
                    "first_tick_no_baseline": True}

        params = session.params or {}
        if not params.get("skill_ref") and not params.get("playbook_id"):
            # No target — degenerate session; downstream emits one
            # "no autonomous target configured" finding and completes.
            return {"current_phase": str(Phase.analysis), "analysis_content": None}

        # Assemble messages and make ONE guarded inference call.
        messages = await assemble_analysis_messages(session, chunks=chunks, db=db)
        intent = ToolIntent.run_playbook if params.get("playbook_id") else ToolIntent.run_skill

        settings = get_settings()
        model = (
            params.get("model")
            or getattr(settings, "autonomous_default_model", None)
            or settings.default_chat_model  # the existing chat model default
        )

        result = await guarded_tool_call(
            session,
            intent,
            {
                "model": model,
                "messages": messages,
                "anonymize": True,
            },
            db, gateway,
        )

        return {
            "current_phase": str(Phase.analysis),
            "analysis_content": (result.data or {}).get("content"),
            "analysis_outcome": result.outcome,  # "success" or "gateway_error"
        }
    return analysis_node
```

If `settings.default_chat_model` doesn't exist, check `api/app/config.py` for the actual setting name (e.g. `default_model`, `gateway_default_model`); match that. If no chat-model default exists, ADD an `autonomous_default_model: str = "claude-opus-4-7"` setting in `api/app/config.py` as a follow-on to Task 2 — but only if no existing default model name fits the role.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_executor_real_work.py::test_analysis_calls_run_skill_through_chokepoint -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/autonomous/nodes.py api/tests/autonomous/test_executor_real_work.py && \
  git commit -s -m "feat(m4): analysis_node — guarded run_skill / run_playbook call

Assembles the analysis messages (Task 7's prompts module) and makes ONE
guarded inference call through the autonomous chokepoint — so R4/R5/R6
brakes apply. The structured-output JSON content is stored in state for
the drafting node. first-tick + no-target sessions skip the call and
emit a degenerate-session finding downstream.

Refs M4-D2 real-executor-work design §3

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Wire `drafting_node` — parse structured output + dispatch guarded calls

**Files:**
- Modify: `api/app/autonomous/nodes.py`

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/autonomous/test_executor_real_work.py`:

```python
@pytest.mark.asyncio
async def test_drafting_dispatches_per_item_guarded_calls(
    db_session: AsyncSession, running_session_at_drafting, mock_gateway
) -> None:
    """drafting_node parses analysis_content (well-formed JSON) and dispatches
    each finding/memory/precedent as its own guarded call."""
    state = {
        "session_id": running_session_at_drafting.id,
        "analysis_content": (
            '```json\n{'
            '"findings": [{"title": "F1", "summary": "S1", "severity": "info", "source_chunk_ids": []}, '
            '{"title": "F2", "summary": "S2", "severity": "warn", "source_chunk_ids": []}], '
            '"suggested_memories": [{"category": "preference", "content": "C", "rationale": "R"}], '
            '"suggested_precedents": [{"pattern_kind": "clause", "summary": "P"}], '
            '"privilege_concerns": [], "scope_concerns": []}\n```'
        ),
        "analysis_outcome": "success",
    }
    node = make_drafting_node(db_session, mock_gateway)
    result = await node(state)

    # Count audit rows: 2 emit_finding + 1 propose_memory + 1 propose_precedent
    from app.models.audit import AuditLog
    from sqlalchemy import select
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.resource_type == "autonomous_session")
        .where(AuditLog.resource_id == str(running_session_at_drafting.id))
    )).scalars().all()
    actions = [r.action for r in rows]
    # The exact counts depend on whether tool_call audit is started+success or just success;
    # check that we have at least 4 tool_call rows after drafting.
    assert sum(1 for a in actions if a == "autonomous_session.tool_call") >= 4
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_executor_real_work.py::test_drafting_dispatches_per_item_guarded_calls -v
```

- [ ] **Step 3: Update `make_drafting_node`**

```python
from app.autonomous.structured_output import parse_structured_output


def make_drafting_node(db, gateway=None):
    async def drafting_node(state):
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in drafting_node"}

        logger.info("autonomous.drafting_node: entering",
                    extra={"event": "autonomous_drafting_enter", "session_id": session_id})
        await run_phase_transition(session, Phase.drafting, db)
        await db.flush()

        analysis_outcome = state.get("analysis_outcome")
        analysis_content = state.get("analysis_content")
        first_tick = state.get("first_tick_no_baseline", False)

        findings_count = 0

        # Honest gateway_error path (Task 13 covers this fully): if the
        # analysis call failed at the gateway, emit one explanatory finding
        # and continue. terminal_reason stays "completed" in the receipt.
        if analysis_outcome == "gateway_error":
            await guarded_tool_call(
                session, ToolIntent.emit_finding,
                {"finding": {
                    "title": "Autonomous analysis failed at the gateway",
                    "summary": "The analysis inference call returned a gateway error. "
                               "No findings, memories, or precedents were produced.",
                    "severity": "warn",
                }},
                db, gateway,
            )
            return {"current_phase": str(Phase.drafting), "findings_count": 1}

        if first_tick:
            await guarded_tool_call(
                session, ToolIntent.emit_finding,
                {"finding": {
                    "title": "First scheduled tick — baseline set",
                    "summary": "No documents attached before this run; "
                               "the next run will analyze what arrives in between.",
                    "severity": "info",
                }},
                db, gateway,
            )
            return {"current_phase": str(Phase.drafting), "findings_count": 1}

        parsed = parse_structured_output(analysis_content)

        if not parsed.is_structured:
            # Tolerant fallback — one finding with the raw content.
            await guarded_tool_call(
                session, ToolIntent.emit_finding,
                {"finding": {
                    "title": "Unstructured autonomous output",
                    "summary": parsed.raw_content[:8000] if parsed.raw_content else "(empty)",
                    "severity": "info",
                }},
                db, gateway,
            )
            return {"current_phase": str(Phase.drafting), "findings_count": 1}

        for f in parsed.findings:
            await guarded_tool_call(
                session, ToolIntent.emit_finding,
                {"finding": f},
                db, gateway,
            )
            findings_count += 1

        for m in parsed.suggested_memories:
            await guarded_tool_call(
                session, ToolIntent.propose_memory,
                {
                    "category": m.get("category", "general"),
                    "content": m.get("content", ""),
                    "rationale": m.get("rationale"),
                },
                db, gateway,
            )

        for p in parsed.suggested_precedents:
            await guarded_tool_call(
                session, ToolIntent.propose_precedent,
                {
                    "pattern_kind": p.get("pattern_kind", "general"),
                    "summary": p.get("summary", ""),
                },
                db, gateway,
            )

        return {
            "current_phase": str(Phase.drafting),
            "findings_count": findings_count,
            "privilege_concerns": parsed.privilege_concerns,
            "scope_concerns": parsed.scope_concerns,
        }
    return drafting_node
```

The exact `params` shape for each handler must match the existing `_handle_emit_finding` / `_handle_propose_memory` / `_handle_propose_precedent` signatures in `api/app/autonomous/guard.py` — re-grep before editing to confirm field names (e.g. `category` vs `kind`; `content` vs `text`). Adjust the `params` dicts above to match shipped handler signatures exactly.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_executor_real_work.py::test_drafting_dispatches_per_item_guarded_calls -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/autonomous/nodes.py api/tests/autonomous/test_executor_real_work.py && \
  git commit -s -m "feat(m4): drafting_node — parse structured output + per-item guarded calls

Parses Task 11's analysis_content via Task 8's tolerant parser, then dispatches
each finding/memory/precedent as its OWN guarded_tool_call (so each is
independently brake-checked + audited). Unparseable content → one emit_finding
with raw_content fallback. Gateway-error from analysis → one explanatory
emit_finding, session continues honestly. First-tick → one 'baseline set'
finding.

Refs M4-D2 real-executor-work design §3

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Tolerant-parse + gateway-error end-to-end tests

**Files:**
- Create: `api/tests/autonomous/test_executor_gateway_error.py`

- [ ] **Step 1: Write the tests**

```python
import pytest
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.executor import run_autonomous_session


@pytest.mark.asyncio
async def test_gateway_error_completes_honestly(
    db_session: AsyncSession, running_watch_session_with_chunks
) -> None:
    """Gateway raises mid-analysis → session completes (not halted) with one
    error-explanation finding; terminal_reason='completed'; receipt is honest."""
    gateway = AsyncMock()
    gateway.chat_completion = AsyncMock(side_effect=RuntimeError("simulated gateway transport error"))

    await run_autonomous_session(running_watch_session_with_chunks.id, db_session, gateway=gateway)

    await db_session.refresh(running_watch_session_with_chunks)
    assert running_watch_session_with_chunks.status == "completed"
    receipt = running_watch_session_with_chunks.result
    assert receipt is not None
    assert receipt["terminal_reason"] == "completed"
    # At least one finding, and the failure tool_call was audited as gateway_error
    outcomes = {tc["outcome"] for tc in receipt["tool_calls"]}
    assert "gateway_error" in outcomes


@pytest.mark.asyncio
async def test_tolerant_parse_unstructured_completes_with_raw_finding(
    db_session: AsyncSession, running_watch_session_with_chunks
) -> None:
    """Gateway returns text that doesn't fit the JSON schema → one emit_finding
    with the raw content; session completes."""
    gateway = AsyncMock()
    gateway.chat_completion = AsyncMock(return_value=type("R", (), {
        "choices": [type("C", (), {
            "message": type("M", (), {"content": "Sorry, I couldn't follow the format."})()
        })()],
        "usage": type("U", (), {"prompt_tokens": 5, "completion_tokens": 10})(),
    })())

    await run_autonomous_session(running_watch_session_with_chunks.id, db_session, gateway=gateway)
    await db_session.refresh(running_watch_session_with_chunks)
    assert running_watch_session_with_chunks.status == "completed"
    receipt = running_watch_session_with_chunks.result
    assert receipt["terminal_reason"] == "completed"
```

- [ ] **Step 2: Run to verify they pass with the wiring from Tasks 11-12**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_executor_gateway_error.py -v
```

Expected: 2 passed (this is integration-level verification of the honest gateway_error path the drafting node added in Task 12 + the terminal_reason fix coming in Task 15).

If `test_gateway_error_completes_honestly`'s `terminal_reason="completed"` assertion fails: that's expected until Task 15. The test can be marked `xfail` here and un-marked in Task 15, OR re-order Tasks 13 and 15 so the terminal_reason fix lands first. Recommended: bring Task 15 before Task 13 in the actual execution order, since 13 depends on 15's audit row.

- [ ] **Step 3: Commit (or defer to Task 15 if reorder chosen)**

```bash
cd ~/Code/lq-ai && git add api/tests/autonomous/test_executor_gateway_error.py && \
  git commit -s -m "test(m4): gateway_error and unstructured-output complete honestly

Both failure modes — gateway transport failure mid-analysis and
unparseable analysis output — result in a completed session with a
single explanatory finding and terminal_reason='completed' on the receipt.

Refs M4-D2 real-executor-work design §3.2, §4

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Wire `ethics_review_node` — privilege/scope concerns finding

**Files:**
- Modify: `api/app/autonomous/nodes.py`

- [ ] **Step 1: Write the failing test**

Add to `api/tests/autonomous/test_executor_real_work.py`:

```python
@pytest.mark.asyncio
async def test_ethics_review_emits_privilege_and_scope_finding(
    db_session: AsyncSession, running_session_at_ethics, mock_gateway
) -> None:
    """ethics_review_node emits ONE finding summarizing the structured-output
    privilege/scope concerns. Empty arrays → emit 'no concerns flagged'."""
    state_with_concerns = {
        "session_id": running_session_at_ethics.id,
        "privilege_concerns": ["mention of attorney-client communication on p.2"],
        "scope_concerns": [],
    }
    node = make_ethics_review_node(db_session, mock_gateway)
    result = await node(state_with_concerns)

    # Verify the audit row exists and details carry the concern strings as counts.
    from sqlalchemy import select
    from app.models.audit import AuditLog
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.resource_id == str(running_session_at_ethics.id))
    )).scalars().all()
    emit_findings = [r for r in rows if r.action == "autonomous_session.tool_call"
                     and (r.details or {}).get("tool") == "emit_finding"
                     and (r.details or {}).get("outcome") == "success"]
    assert len(emit_findings) >= 1
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_executor_real_work.py::test_ethics_review_emits_privilege_and_scope_finding -v
```

- [ ] **Step 3: Update `make_ethics_review_node`**

```python
def make_ethics_review_node(db, gateway=None):
    async def ethics_review_node(state):
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in ethics_review_node"}

        logger.info("autonomous.ethics_review_node: entering",
                    extra={"event": "autonomous_ethics_review_enter", "session_id": session_id})
        await run_phase_transition(session, Phase.ethics_review, db)
        await db.flush()

        privilege = state.get("privilege_concerns") or []
        scope = state.get("scope_concerns") or []

        if privilege or scope:
            summary_lines = []
            if privilege:
                summary_lines.append(f"Privilege concerns ({len(privilege)}):")
                summary_lines.extend(f"  - {c}" for c in privilege)
            if scope:
                summary_lines.append(f"Scope concerns ({len(scope)}):")
                summary_lines.extend(f"  - {c}" for c in scope)
            title = "Ethics-review concerns flagged"
            summary = "\n".join(summary_lines)
        else:
            title = "Ethics review: no concerns flagged"
            summary = ("The analysis output did not surface privilege or scope concerns. "
                       "A dedicated ethics LLM gate is a future enhancement (DE).")

        await guarded_tool_call(
            session, ToolIntent.emit_finding,
            {"finding": {"title": title, "summary": summary, "severity": "info"}},
            db, gateway,
        )

        return {"current_phase": str(Phase.ethics_review)}
    return ethics_review_node
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_executor_real_work.py::test_ethics_review_emits_privilege_and_scope_finding -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/autonomous/nodes.py api/tests/autonomous/test_executor_real_work.py && \
  git commit -s -m "feat(m4): ethics_review_node — emit privilege/scope concerns finding

Light v1: emit ONE guarded emit_finding summarizing privilege_concerns +
scope_concerns from the structured-output JSON; empty arrays → 'no concerns
flagged' finding. A dedicated ethics LLM gate is a future DE.

Refs M4-D2 real-executor-work design §3

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Wire `delivery_node` — write `completed` audit row (terminal_reason fix)

**Files:**
- Modify: `api/app/autonomous/nodes.py`
- Create: `api/tests/autonomous/test_terminal_reason_completed.py`

- [ ] **Step 1: Write the failing test**

`api/tests/autonomous/test_terminal_reason_completed.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.nodes import make_delivery_node
from app.models.audit import AuditLog


@pytest.mark.asyncio
async def test_delivery_writes_completed_audit_row_so_receipt_terminal_reason_populates(
    db_session: AsyncSession, running_session_at_delivery, mock_gateway
) -> None:
    """delivery_node writes autonomous_session.completed before build_receipt
    so the receipt's terminal_reason is 'completed' (was None — the bug)."""
    node = make_delivery_node(db_session, mock_gateway)
    state = {"session_id": running_session_at_delivery.id, "findings": []}
    await node(state)

    # An autonomous_session.completed audit row exists for this session.
    rows = (await db_session.execute(
        select(AuditLog)
        .where(AuditLog.resource_type == "autonomous_session")
        .where(AuditLog.resource_id == str(running_session_at_delivery.id))
        .where(AuditLog.action == "autonomous_session.completed")
    )).scalars().all()
    assert len(rows) == 1

    # The session's stored receipt has terminal_reason='completed'.
    await db_session.refresh(running_session_at_delivery)
    receipt = running_session_at_delivery.result
    assert receipt is not None
    assert receipt["terminal_reason"] == "completed"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_terminal_reason_completed.py -v
```

Expected: FAIL — the current `make_delivery_node` writes no `completed` audit row.

- [ ] **Step 3: Update `make_delivery_node`**

In `api/app/autonomous/nodes.py`, update the delivery node:

```python
from app.autonomous.audit import autonomous_audit  # already imported


def make_delivery_node(db, gateway=None):
    async def delivery_node(state):
        if state.get("error"):
            return {}

        session_id = state["session_id"]
        session = await db.get(AutonomousSession, session_id)
        if session is None:
            return {"error": f"session {session_id} not found in delivery_node"}

        logger.info("autonomous.delivery_node: entering",
                    extra={"event": "autonomous_delivery_enter", "session_id": session_id})
        await run_phase_transition(session, Phase.delivery, db)

        findings_count = state.get("findings_count", len(state.get("findings") or []))
        await guarded_tool_call(
            session, ToolIntent.notify,
            {
                "title": "Autonomous session complete",
                "body": f"Session completed with {findings_count} finding(s).",
                "payload": {"finding_count": findings_count},
            },
            db, gateway,
        )

        # NEW (terminal_reason fix): write the completed audit row BEFORE
        # build_receipt so receipt.terminal_reason picks it up.
        await autonomous_audit(
            db, session, "completed",
            cost_total_usd=str(session.cost_total_usd or "0"),
            findings_count=findings_count,
        )

        session.status = "completed"
        session.completed_at = datetime.now(UTC)
        # Persist the receipt into result BEFORE the commit so the JSONB
        # column is populated atomically with the terminal status update.
        session.result = await build_receipt(session, db)
        await db.commit()

        return {"current_phase": str(Phase.delivery)}
    return delivery_node
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_terminal_reason_completed.py -v
```

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add api/app/autonomous/nodes.py api/tests/autonomous/test_terminal_reason_completed.py && \
  git commit -s -m "fix(m4): delivery_node writes 'completed' audit row → receipt terminal_reason populates

Bug fix from the 2026-05-27 fresh-install acceptance: completed sessions
showed terminal_reason=None on the receipt because build_receipt derives
it from a terminal audit row, but delivery_node only set
session.status='completed' without auditing. Now writes
autonomous_session.completed via autonomous_audit (already in the closed
event set) immediately before build_receipt. Regression-tested.

Refs M4-D2 real-executor-work design §7.1

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: R4 per-trigger live test (production-shape spawn path)

**Files:**
- Create: `api/tests/autonomous/test_r4_per_trigger_cap.py`

- [ ] **Step 1: Write the test**

```python
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.executor import run_autonomous_session


@pytest.mark.asyncio
async def test_low_per_trigger_max_cost_latches_cost_cap_reached(
    db_session: AsyncSession, opted_in_user, test_kb_with_indexed_file, test_skill_ref
) -> None:
    """A watch with max_cost_usd=0.001 + a real-cost analysis call latches R4."""
    from app.models.autonomous import AutonomousWatch
    from app.autonomous.watch_trigger import fire_watches_for_kb

    watch = AutonomousWatch(
        user_id=opted_in_user.id,
        knowledge_base_id=test_kb_with_indexed_file.kb_id,
        enabled=True,
        skill_ref=test_skill_ref,
        max_cost_usd=Decimal("0.001"),
    )
    db_session.add(watch)
    await db_session.flush()

    await fire_watches_for_kb(
        db_session, kb_id=test_kb_with_indexed_file.kb_id,
        file_id=test_kb_with_indexed_file.file_id,
    )

    # Mock gateway: returns enough projected cost to exceed $0.001.
    gateway = AsyncMock()
    gateway.chat_completion = AsyncMock(return_value=type("R", (), {
        "choices": [type("C", (), {
            "message": type("M", (), {"content": '{}'})()
        })()],
        "usage": type("U", (), {"prompt_tokens": 5000, "completion_tokens": 2000})(),
    })())

    # Find the spawned session, run it.
    from sqlalchemy import select
    from app.models.autonomous import AutonomousSession
    session = (await db_session.execute(
        select(AutonomousSession).where(AutonomousSession.user_id == opted_in_user.id)
    )).scalar_one()

    await run_autonomous_session(session.id, db_session, gateway=gateway)
    await db_session.refresh(session)

    assert session.cost_cap_reached is True
    assert session.halt_state == "halted"
    receipt = session.result
    assert receipt["terminal_reason"] == "cost_cap_reached"
```

- [ ] **Step 2: Run to verify it passes against Tasks 1-15**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/test_r4_per_trigger_cap.py -v
```

Expected: pass. (This is a verification test — the wiring done in Tasks 1-15 should make this work end-to-end.) If projected cost from `estimate_tool_cost` is structurally below `$0.001`, lower the cap further or raise the simulated token counts; the exact threshold is in `api/app/autonomous/cost.py`.

- [ ] **Step 3: Commit**

```bash
cd ~/Code/lq-ai && git add api/tests/autonomous/test_r4_per_trigger_cap.py && \
  git commit -s -m "test(m4): R4 live-trips with a low per-trigger max_cost_usd

End-to-end: watch.max_cost_usd=0.001 → spawned session inherits it →
analysis call's R4 brake latches cost_cap_reached → session halts →
receipt terminal_reason='cost_cap_reached'. Confirms the production-shape
spawn path's R4 wiring (existing brake unit tests covered the chokepoint
in isolation; this verifies the trigger → session → R4 chain).

Refs M4-D2 real-executor-work design §3.1, §10

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Update the existing `test_executor_skeleton.py`

**Files:**
- Modify: `api/tests/autonomous/test_executor_skeleton.py`

The existing executor-skeleton test asserts behaviors that are now obsolete (e.g. that analysis_node makes no tool call, that drafting emits a hardcoded `{"phase":"drafting","status":"oriented"}`). Update it to assert what the test name's invariant ACTUALLY says: "no tool path bypasses the chokepoint."

- [ ] **Step 1: Read the existing test**

```bash
cd ~/Code/lq-ai && cat api/tests/autonomous/test_executor_skeleton.py
```

- [ ] **Step 2: Update assertions**

For each test in the file:
- Drop any assertion that says "no tool calls made" or "drafting emits exactly one hardcoded finding" — those are now wrong.
- Keep / strengthen any assertion that says "every guarded_tool_call goes through the chokepoint" / "no audit row appears with action != autonomous_session.*" — that invariant still holds and is what the test name promises.
- If the file has a `test_skeleton_no_tool_calls` test, rename it to `test_no_tool_call_bypasses_chokepoint` and rewrite the body to assert that all `tool_call` audit rows have a recognized intent in `ToolIntent` and a recognized outcome.

- [ ] **Step 3: Run all autonomous tests**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/pytest tests/autonomous/ -q
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
cd ~/Code/lq-ai && git add api/tests/autonomous/test_executor_skeleton.py && \
  git commit -s -m "test(m4): update executor_skeleton test for real-work behavior

The 'no tool path bypasses the chokepoint' invariant is preserved and
strengthened; the obsolete 'no tool calls made' / 'drafting emits one
hardcoded finding' assertions are removed since nodes now do real work.

Refs M4-D2 real-executor-work design

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 18: Full pytest + ruff + mypy gate before re-acceptance

- [ ] **Step 1: Run the full autonomous suite + brake/idle/optin**

```bash
cd ~/Code/lq-ai/api && \
  PW=$(grep -m1 '^POSTGRES_PASSWORD=' ../.env | cut -d= -f2-) && \
  DATABASE_URL="postgresql+asyncpg://lq_ai:${PW}@127.0.0.1:15432/lq_ai" \
  ./.venv/bin/pytest tests/autonomous/ -v
```

Expected: all green (including the 31 baseline brake/idle/optin tests and every new test created in Tasks 1-17).

- [ ] **Step 2: Run ruff format + check across all touched files**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/ruff format app/autonomous/ app/api/autonomous.py app/workers/autonomous_worker.py app/models/autonomous.py app/schemas/autonomous.py app/config.py tests/autonomous/ && \
  ./.venv/bin/ruff check app/autonomous/ app/api/autonomous.py app/workers/autonomous_worker.py app/models/autonomous.py app/schemas/autonomous.py app/config.py tests/autonomous/
```

Expected: clean.

- [ ] **Step 3: Run mypy across app/autonomous/**

```bash
cd ~/Code/lq-ai/api && ./.venv/bin/mypy app/autonomous/ app/api/autonomous.py app/workers/autonomous_worker.py
```

Expected: clean.

- [ ] **Step 4: Push to both remotes**

```bash
cd ~/Code/lq-ai && git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous
```

---

## Task 19: Fresh-install re-acceptance (the v0.4.0 tag gate)

This is the destructive acceptance run that closes the M4 milestone. It **wipes the dev DB volume** — get explicit go-ahead before running.

- [ ] **Step 1: Confirm with Kevin before destructive teardown**

The stack is currently up + healthy after the 2026-05-27 acceptance. `docker compose down -v` will wipe it. Confirm before proceeding.

- [ ] **Step 2: Tear down + rebuild**

```bash
cd ~/Code/lq-ai && docker compose down -v && docker compose up -d --build
```

Wait for all containers to be healthy (`docker compose ps` shows healthy for api, gateway, postgres, redis, minio, ingest-worker, arq-worker, web).

- [ ] **Step 3: Capture admin password + change it + login**

```bash
cd ~/Code/lq-ai && PW=$(docker compose logs api 2>&1 | grep "Reset password for admin@lq.ai" | tail -1 | sed -E 's/.*: //')
# Login, change password, re-login (the must_change_password gate):
B=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"admin@lq.ai\",\"password\":\"$PW\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -X POST http://localhost:8000/api/v1/auth/change-password \
    -H "Authorization: Bearer $B" -H "Content-Type: application/json" \
    -d "{\"current_password\":\"$PW\",\"new_password\":\"AcceptTest12345!\"}"
B=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@lq.ai","password":"AcceptTest12345!"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

- [ ] **Step 4: Enable opt-in + create KB + watch (with low cost cap for the R4 demo) bound to a seed playbook**

```bash
H="Authorization: Bearer $B"
curl -s -X PATCH http://localhost:8000/api/v1/users/me/preferences -H "$H" -H "Content-Type: application/json" -d '{"autonomous_enabled":true}'
KB=$(curl -s -X POST http://localhost:8000/api/v1/knowledge-bases -H "$H" -H "Content-Type: application/json" -d '{"name":"M4 Real-Work Acceptance"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
# Get a seed playbook id (NDA-mutual or similar):
PB=$(curl -s "http://localhost:8000/api/v1/playbooks" -H "$H" | python3 -c "import sys,json;d=json.load(sys.stdin);print([p['id'] for p in d['playbooks'] if 'nda' in p['name'].lower()][0])")
# Watch with a generous cap for the happy-path demo:
curl -s -X POST http://localhost:8000/api/v1/autonomous/watches -H "$H" -H "Content-Type: application/json" \
    -d "{\"knowledge_base_id\":\"$KB\",\"playbook_id\":\"$PB\",\"max_cost_usd\":\"1.00\"}"
```

- [ ] **Step 5: Upload an NDA PDF + attach to the KB (the watch fires)**

```bash
# Upload the file to the files endpoint (replace with the actual upload route):
F=$(curl -s -X POST "http://localhost:8000/api/v1/files" -H "$H" -F "file=@$HOME/Code/lq-ai/tests/fixtures/sample-nda.pdf" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
# Attach by file_id (correct flow, not multipart):
curl -s -X POST "http://localhost:8000/api/v1/knowledge-bases/$KB/files" -H "$H" -H "Content-Type: application/json" -d "{\"file_id\":\"$F\"}"
```

(Locate the actual upload-by-multipart route name during execution — `grep -nE "@router\\.(post|put).*[fF]ile|UploadFile" api/app/api/*.py | head` if the path above is wrong.)

- [ ] **Step 6: Wait ~30s + verify the spawned session ran real work**

```bash
sleep 30
curl -s "http://localhost:8000/api/v1/autonomous/sessions" -H "$H" | python3 -m json.tool
# Expect: trigger_kind="watch", status="completed", current_phase="delivery"
# Cost > 0; tool_calls include run_playbook (or run_skill) with outcome=success;
# emit_finding rows for each finding; possibly propose_memory + propose_precedent rows.

# Check the receipt has terminal_reason populated:
SID=$(curl -s "http://localhost:8000/api/v1/autonomous/sessions" -H "$H" | python3 -c "import sys,json;print(json.load(sys.stdin)['sessions'][0]['id'])")
curl -s "http://localhost:8000/api/v1/autonomous/sessions/$SID" -H "$H" | python3 -c "import sys,json;d=json.load(sys.stdin);print('terminal_reason=', d['receipt']['terminal_reason']);print('cost_total_usd=', d['receipt']['cost_total_usd']);print('phase_transitions=', [t['to_phase'] for t in d['receipt']['phase_transitions']]);print('tool_calls=', [(tc['tool'], tc['outcome']) for tc in d['receipt']['tool_calls']])"
# Expect: terminal_reason='completed', cost > 0, all five phases, real tool calls.

# Check the proposal surfaces have content:
curl -s "http://localhost:8000/api/v1/autonomous/memory" -H "$H" | python3 -c "import sys,json;print('memory_count=', len(json.load(sys.stdin)['memory']))"
curl -s "http://localhost:8000/api/v1/autonomous/precedents" -H "$H" | python3 -c "import sys,json;print('precedent_count=', len(json.load(sys.stdin)['precedents']))"
# Expect: > 0 if the playbook surfaces those (skill-dependent).
```

- [ ] **Step 7: R4 live-demo — second watch with a tight cap**

```bash
# Second watch with max_cost_usd=0.001 → next doc trips R4.
curl -s -X POST http://localhost:8000/api/v1/autonomous/watches -H "$H" -H "Content-Type: application/json" \
    -d "{\"knowledge_base_id\":\"$KB\",\"playbook_id\":\"$PB\",\"max_cost_usd\":\"0.001\"}"
# Drop another doc:
F2=$(curl -s -X POST "http://localhost:8000/api/v1/files" -H "$H" -F "file=@$HOME/Code/lq-ai/tests/fixtures/sample-msa.pdf" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -X POST "http://localhost:8000/api/v1/knowledge-bases/$KB/files" -H "$H" -H "Content-Type: application/json" -d "{\"file_id\":\"$F2\"}"
sleep 15
# Find the new session and verify R4 fired:
curl -s "http://localhost:8000/api/v1/autonomous/sessions" -H "$H" | python3 -c "import sys,json;d=json.load(sys.stdin)['sessions'];[print(s['id'], s['status'], s['halt_state'], s.get('cost_cap_reached')) for s in d[:3]]"
# Expect: latest session shows status=halted, halt_state=halted, cost_cap_reached=true.
```

- [ ] **Step 8: R5 live-demo — halt a running session**

(Optional — schedule a session that takes longer than instant, then POST /halt before delivery. Already test-covered; live demo only if a long-running session is available.)

- [ ] **Step 9: Document acceptance results in handoff**

Update `docs/LQVern/HANDOFF-*.md` (or create a new dated handoff) with the acceptance evidence — which surfaces validated, which gaps surfaced (file as DE-XXX in PRD §9). At this point M4-D2 docs can proceed (boundary-registers flip + PRD §3.10 SHIPPED + autonomous-layer.md + HONEST-STATE sweep).

- [ ] **Step 10: Hand off to the attorney walk-through**

Per `feedback_no_maintainer_legal_review`, the attorney legal-substance walk-through against a real document is Kevin's. Provide him the session receipt + finding text so the walk-through has concrete inputs.

---

## Self-review (writing-plans skill checklist)

**Spec coverage:**
- §1 context → covered by Tasks 1-17 collectively (substrate stays real; nodes wire up).
- §2 locked decisions → Decision 1 (work model) in Tasks 5, 9, 10; Decision 2 (chokepoint-aligned inference) in Task 11; Decision 3 (single structured-output) in Tasks 11-12; Decision 4 (max_cost_usd) in Tasks 1-5; Decision 5 (light ethics) in Task 14; Decision 6 (model selection) in Task 11.
- §3 architecture table → Task 9 (intake watch), Task 10 (intake schedule), Task 11 (analysis), Task 12 (drafting), Task 14 (ethics), Task 15 (delivery).
- §4 structured-output contract → Task 7 (instruction text) + Task 8 (parser).
- §5 schema changes → Tasks 1-4 (migration, config, models, schemas, endpoints).
- §6 retrieve_chunks scope extension → Task 6.
- §7 bug fixes — §7.1 terminal_reason → Task 15; §7.2 watch-trigger live → Task 19 Step 5.
- §8 out-of-scope DEs → filed by Kevin during M4-D2 docs (separate from this plan).
- §9 testing strategy → Tasks 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18.
- §10 fresh-install acceptance → Task 19.

**Placeholder scan:** the plan contains specific instructions where the actual API names need re-grepping (skill `body` vs `content` attribute; existing config default model name; exact `_handle_emit_finding` param shape). These are explicitly flagged in the relevant tasks with the grep command to verify — NOT placeholder TBDs, but real "match the existing pattern" instructions.

**Type consistency:** the `StructuredResult` dataclass and `parse_structured_output` signature match across Tasks 8, 12, 13. The `assemble_analysis_messages` signature matches between Task 7 and Task 11. The `max_cost_usd: Decimal | None` type matches across Tasks 1-5.

---

## Execution handoff

**Plan complete and saved to `docs/LQVern/m4-real-executor-work-implementation-plan.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec compliance + code quality) between tasks, fast iteration in this session.
2. **Inline Execution** — execute tasks in this session via `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?
