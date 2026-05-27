# M4 Implementation Plan — Autonomous Layer (LQVern)

> **Purpose:** Dependency-ordered task list for the M4 Autonomous Layer build. Each task is a discrete unit of work sized for a focused Claude Code session, with a verifiable end-state. Follows the same conventions as [`M1-IMPLEMENTATION-ORDER.md`](M1-IMPLEMENTATION-ORDER.md), [`M2-IMPLEMENTATION-PLAN.md`](M2-IMPLEMENTATION-PLAN.md), and [`M3-IMPLEMENTATION-PLAN.md`](M3-IMPLEMENTATION-PLAN.md).
>
> **Status:** Authoritative once committed. Updates land in the same release cadence as the PRD.
>
> **Audience:** Claude Code or any human contributor implementing M4. Hand this document along with [`docs/adr/0013-autonomous-layer-design-influences.md`](adr/0013-autonomous-layer-design-influences.md), [`docs/PRD.md §3.10`](PRD.md#310-autonomous-layer-m4), [`docs/LQVern/agentic-flow-alignment-guide.md`](LQVern/agentic-flow-alignment-guide.md), `docs/db-schema.md`, the OpenAPI sketches, `gateway.yaml.example`, and `CLAUDE.md`. **The design is done and approved — this plan implements it; it does not re-decide it.**
>
> **Process note (writing-plans × house style):** this plan was written through the `superpowers:writing-plans` discipline (zero-context assumption, exact file paths, real symbol names, TDD-first verification, no placeholders) but renders in the project's M1–M3 phase/task house style (Scope / Dependencies / Output / Verification / Effort / References) so it sits coherently alongside the prior milestone plans. The load-bearing task (M4-A3, the `guarded_tool_call` chokepoint) carries concrete code keyed to the real backend symbols it calls.

The M4 milestone is the **autonomy** release. It adds one largely self-contained subsystem — the **Autonomous Layer** ([PRD §3.10](PRD.md#310-autonomous-layer-m4)) — a long-running, per-user agent that observes activity, runs scheduled and event-triggered work, learns patterns, and proposes actions, **off by default and opt-in per user**. M4 is also where **Tier 2 of the boundary-register catalog** ([§1.8](PRD.md#18-security-posture), [`docs/security/boundary-registers.md`](security/boundary-registers.md)) — R4 economic, R5 temporal, R6 contextual — first attaches to running code.

The design is pinned in **[ADR 0013](adr/0013-autonomous-layer-design-influences.md)** (D1–D6) and built out in **[PRD §3.10](PRD.md#310-autonomous-layer-m4)**; the contributor how-to with the chokepoint pseudo-code is **[`docs/LQVern/agentic-flow-alignment-guide.md`](LQVern/agentic-flow-alignment-guide.md)**. M4 v1 ships **four primitives**, each of which spawns an `autonomous_session` the single agent runs under the R4/R5/R6 brakes:

1. **Watches** — new documents in a watched Knowledge Base trigger a configured playbook/skill; findings are notified.
2. **Scheduled tasks** — cron-scheduled periodic runs (e.g., a weekly compliance scan against a contract repository).
3. **Per-user memory** — the observe-and-propose preference store (*system-proposes, user-owns*).
4. **Precedent board** — system-observed patterns about documents/clauses across matters, read-mostly and user-dismissable.

The single non-negotiable that shapes every task: **the alignment contract** (ADR 0013 D6). Every autonomous flow, by construction, emits `autonomous.session` + `autonomous.tool_call` OTel spans (counts/types/IDs/costs only — never raw entity values), writes a closed-enum audit trail, and produces a human-readable per-session receipt. **Code without these is not done.**

This document supersedes any conflicting sequencing in earlier roadmap documents. The PRD §8 roadmap remains the canonical capability commitment; this document is the implementation contract.

---

## Architectural decisions locked for M4

These decisions are pinned by [ADR 0013](adr/0013-autonomous-layer-design-influences.md) and **must not be re-litigated mid-task**. They are restated here (D1–D6) plus the three implementation-level resolutions (M4-7 through M4-9) the ADR left to this plan. If a task surfaces a question these decisions don't anticipate, **stop, ask Kevin, document the answer here, then resume** — the cost of stopping is minutes; the cost of an undocumented architectural choice is hours-to-days of rework (CLAUDE.md).

### Decision M4-1 (ADR 0013 D1): Single-agent for M4 v1, designed to extend

One agent per `autonomous_session`. M4 ships single-agent flows — this delivers every committed §3.10 user story without the agent-to-agent handoff surface. **DE-294 (cross-agent handoff validation) stays deferred.** Do **not** plan multi-agent orchestration. The executor's interfaces (typed session state, closed `ToolIntent` enum) are designed so a future multi-agent orchestrator can wrap single-agent sessions without redesign.

### Decision M4-2 (ADR 0013 D2): Executor in `api/app/autonomous/` on the arq-worker, mirroring playbooks

The executor is a **LangGraph state machine** in `api/app/autonomous/` running on the existing **arq-worker**, mirroring the shipped Playbook executor (`api/app/playbooks/{executor,nodes,state}.py`). Inference goes through the **gateway** (`app.clients.gateway.GatewayClient`), exactly as playbooks call it — never a direct provider SDK call from `api/`. Routing through the gateway is what gives autonomous flows anonymization + tier enforcement + cost accounting for free; the gateway stays the stateless key-holding boundary. This supersedes §3.10's old "OpenWebUI Pipelines" wording (the web layer renders the dashboard + receipts; it does not run the agent loop).

### Decision M4-3 (ADR 0013 D3): The Tier-2 brakes (DE-293), checked at one chokepoint

Every tool call passes through a single `guarded_tool_call` chokepoint that enforces all three brakes **before** the tool runs:

- **R4 economic:** `autonomous_sessions.max_cost_usd` (deployment default **$5** in `gateway.yaml`), checked against `cost_total_usd` using the M2-E2 estimator; overrun → `cost_cap_reached` terminal state + partial result preserved.
- **R5 temporal:** `autonomous_sessions.halt_state` enum (`running`/`halt_requested`/`halted`/`paused`), read before every tool call; `POST …/halt`; idle past `idle_halt_minutes` (default **5**) auto-pauses then halts.
- **R6 contextual:** phases (`intake`/`analysis`/`drafting`/`ethics_review`/`delivery`) with per-phase tool grants; the current-phase row gates every tool call; transitions are explicit + audited.

**There is exactly one chokepoint on purpose** — a contributor adding a tool gets the brakes + telemetry for free and cannot route around them.

### Decision M4-4 (ADR 0013 D4): Memory model is *system-proposes, user-owns*

The agent **observes and proposes** memory entries; every entry is **user-visible, user-editable, user-deletable, and applied only after the user keeps it**. Default posture: proposals surface for review, **never silent write**.

### Decision M4-5 (ADR 0013 D5): Precedent board absorbed, distinct, per-user

Three distinct memory surfaces, all hard per-user-isolated:
- **Project context (§3.11):** user-authored, per-matter. *What this matter is.*
- **Autonomous memory (D4):** system-observed patterns about *the user's* preferences. *How this user likes to work.*
- **Precedent board (this milestone):** system-observed patterns about *documents/clauses across matters*, read-mostly, user-dismissable. *What we keep seeing in the documents.* The agent may **propose** promoting a precedent into a Project's context but never writes Project context directly.

### Decision M4-6 (ADR 0013 D6): The alignment contract is non-optional

OTel domain spans (counts/types only, never raw entity values), a closed-enum audit trail, and a per-session receipt are emitted by construction on every flow. Enforced by the privacy-guard test (M4-A3) mirroring `gateway/tests/test_anonymization_observability.py`. New autonomous code that does not emit these is not done.

### Decision M4-7 (resolves ADR 0013 open-Q1): Watch trigger = direct arq-enqueue from the ingest pipeline

The ingest pipeline **directly enqueues** an autonomous session on document arrival (it does not publish an event for a separate subscriber). The ingest worker already runs on arq; the autonomous executor is another arq job on the same Redis. Direct enqueue is the simplest shape that fits the substrate (ADR 0013's predicted answer). The watch-config row tells the ingest hook which KBs are watched and which playbook/skill to run. The pub/sub alternative (an event bus a separate scheduler subscribes to) is filed as a possible later refactor **only if** a non-arq trigger source appears — file as a DE if it surfaces.

### Decision M4-8 (resolves ADR 0013 open-Q2): Notification surface = email + in-app for v1

Email + in-app notifications ship in M4. The optional **webhook to the §3.15 Slack/Teams bridge is a deferred fold-in**, gated on the bridge's send-path landing ([DE-312](PRD.md#de-312)); it is **not** M4 scope. Notifications are emitted only through the `notify` tool intent at the `delivery` phase, so they pass the same chokepoint + audit as every other action.

### Decision M4-9 (resolves ADR 0013 open-Q3): Precedent board is per-user for v1

The precedent board is **per-user** (hard isolation, §3.10 NFR). A per-deployment (org-shared) precedent board is a possible later option; it is **not** v1 scope — file as a DE if an operator requests it. The isolation test (M4-B2) pins per-user.

### Decision M4-10 (dependency): LangGraph version is pinned; the langgraph major bump is evaluated as M4 dependency work

The autonomous executor uses LangGraph, the same runtime the Playbook executor pins (`langgraph ~= 0.2`). The open dependabot PR **#68** (langgraph → 1.3, currently failing CI as a breaking change) **intersects M4** and is evaluated in Task M4-0.1 as part of M4 dependency work — not merged in isolation, and not deferred silently. The pin lives in `api/pyproject.toml` and is SBOM-relevant.

---

## Phase 0 — Dependency prep (before any executor code)

The executor depends on LangGraph; the held major bump intersects it. Resolve the dependency posture before building on it, so the executor lands on a pinned, CI-green runtime.

### Task M4-0.1 — LangGraph dependency decision + pin (evaluate dependabot #68)

**Scope:**
- Evaluate dependabot PR **#68** (`langgraph` → `1.3`) against **both** the shipped Playbook executor (`api/app/playbooks/`) and the planned autonomous executor (the API surface this plan uses: `StateGraph`, typed-dict state, conditional edges). Identify the breaking changes that fail #68's CI.
- Decide one of: (a) **stay on `~= 0.2`** for M4 and re-pin (close #68 with a rationale comment + a DE to revisit post-M4), or (b) **migrate to `1.x`** as the first M4 task (update the playbook executor's graph construction in the same PR, since both executors share the runtime). The conservative posture (§1.9) and "don't break shipped code mid-milestone" favor (a) **unless** the autonomous executor needs a `1.x`-only API — document the determination here.
- Whichever path: pin an exact compatible range in `api/pyproject.toml`; record the SBOM rationale in the PR body (CLAUDE.md: new/changed deps need justification).
- If (a): the playbook executor's existing tests must still pass unchanged. If (b): the playbook executor's tests are the regression gate for the migration — they must pass green before the autonomous code lands on `1.x`.

**Dependencies:** None. First M4 task.

**Output:** A pinned, CI-green LangGraph version that both executors target; #68 resolved (merged or closed-with-rationale), not left dangling.

**Verification:**
- `cd api && ./.venv/bin/pytest api/tests/playbooks/ -q` passes on the chosen pin.
- `ruff check` + `ruff format --check` + `mypy` (api standard) clean on any changed playbook-executor code.
- The pin in `api/pyproject.toml` is an exact, justified range; #68's CI is green (if merged) or it is closed with a linked rationale + a revisit-DE filed in PRD §9.

**Effort:** 4–8 hours (lower if path (a); higher if the `1.x` migration is taken).

**References:** ADR 0013 D2; handoff §7 (langgraph #68 intersects M4); [PRD §3.7](PRD.md#37-playbooks) (the playbook executor that shares the runtime).

---

## Phase A — Substrate + the brakes (prove the chokepoint before any primitive)

Phase A lands the data model, the executor skeleton, the single `guarded_tool_call` chokepoint with all three brakes, and the halt/idle/receipt surface. **The four primitives in Phase B do not start until the chokepoint and its acceptance tests are green** — proving the substrate first is the whole point of the phasing (handoff §3).

### Task M4-A1 — Data model + Alembic migration + models + schemas

**Scope:**
- Single Alembic migration `api/alembic/versions/0039_autonomous_layer.py` (latest existing is `0038_teams_tenants.py`) creating **all five tables** up front (they are cheap; one migration minimizes the rebuild-all-workers cost — see Verification). All tables follow `docs/db-schema.md` conventions (UUID v7 PK, `TIMESTAMPTZ` `created_at`/`updated_at`, named FKs `fk_<table>_<col>`, named indexes `idx_<table>_<cols>`, snake_case, hard per-user isolation via a non-null `user_id` FK on every table):
  - **`autonomous_sessions`** — the run record carrying the brakes:
    - `id UUID PK`, `user_id UUID NOT NULL FK users ON DELETE CASCADE`, `project_id UUID NULL FK projects`,
    - `trigger_kind TEXT NOT NULL CHECK IN ('watch','schedule','suggestion','manual')`, `trigger_ref UUID NULL` (the watch/schedule row that spawned it),
    - `current_phase TEXT NOT NULL DEFAULT 'intake' CHECK IN ('intake','analysis','drafting','ethics_review','delivery')`,
    - `halt_state TEXT NOT NULL DEFAULT 'running' CHECK IN ('running','halt_requested','halted','paused')`,
    - `max_cost_usd NUMERIC(10,4) NULL` (null = use deployment default), `cost_total_usd NUMERIC(10,4) NOT NULL DEFAULT 0`, `cost_cap_reached BOOLEAN NOT NULL DEFAULT false`,
    - `idle_halt_minutes INT NOT NULL DEFAULT 5`, `last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now()`,
    - `status TEXT NOT NULL DEFAULT 'running' CHECK IN ('running','completed','halted','failed')`, `result JSONB NULL` (the partial-or-final result + receipt payload), `error TEXT NULL`,
    - `created_at`, `updated_at`, `completed_at TIMESTAMPTZ NULL`.
    - Indexes: `idx_autonomous_sessions_user_created (user_id, created_at DESC)`; `idx_autonomous_sessions_active (halt_state, last_activity_at) WHERE status = 'running'` (the idle-halt watchdog scans this).
  - **`autonomous_schedules`** — `id`, `user_id NOT NULL`, `project_id NULL`, `name TEXT`, `cron_expr TEXT NOT NULL`, `playbook_id UUID NULL FK playbooks`, `skill_ref TEXT NULL`, `target_kb_id UUID NULL FK knowledge_bases`, `enabled BOOLEAN NOT NULL DEFAULT true`, `last_run_at TIMESTAMPTZ NULL`, `next_run_at TIMESTAMPTZ NULL`, `deleted_at TIMESTAMPTZ NULL`, timestamps.
  - **`autonomous_watches`** — `id`, `user_id NOT NULL`, `project_id NULL`, `knowledge_base_id UUID NOT NULL FK knowledge_bases`, `playbook_id UUID NULL FK playbooks`, `skill_ref TEXT NULL`, `enabled BOOLEAN NOT NULL DEFAULT true`, `deleted_at TIMESTAMPTZ NULL`, timestamps. Index `idx_autonomous_watches_kb_enabled (knowledge_base_id) WHERE enabled AND deleted_at IS NULL` (the ingest hook looks up watches by KB).
  - **`autonomous_memory`** — `id`, `user_id NOT NULL`, `state TEXT NOT NULL CHECK IN ('proposed','kept','dismissed')`, `category TEXT NOT NULL` (e.g., `'preference'`, `'pattern'`), `content TEXT NOT NULL` (the human-readable entry), `source_session_id UUID NULL FK autonomous_sessions`, `kept_at TIMESTAMPTZ NULL`, `deleted_at TIMESTAMPTZ NULL`, timestamps. Index `idx_autonomous_memory_user_state (user_id, state)`.
  - **`precedent_entries`** — `id`, `user_id NOT NULL`, `pattern_kind TEXT NOT NULL` (e.g., `'counterparty_position'`, `'clause_language'`), `summary TEXT NOT NULL`, `observed_count INT NOT NULL DEFAULT 1`, `source_session_id UUID NULL FK autonomous_sessions`, `dismissed_at TIMESTAMPTZ NULL`, timestamps. Index `idx_precedent_entries_user_kind (user_id, pattern_kind) WHERE dismissed_at IS NULL`.
- SQLAlchemy models in `api/app/models/autonomous.py` (one module; mirror `api/app/models/playbook.py`).
- Pydantic schemas in `api/app/schemas/autonomous.py` matching the API surface (request/response models for sessions, schedules, watches, memory, precedents — built out per-endpoint in their phase tasks; the enums `Phase`, `HaltState`, `SessionStatus`, `MemoryState`, `ToolIntent` live here as `StrEnum`s so models and the executor share one definition).
- Update `docs/db-schema.md`: add an `## Autonomous layer (per [PRD §3.10](PRD.md#310-autonomous-layer-m4), M4)` section documenting all five tables. **Replace the sketched `### autonomous_tasks (M4)` block** (currently in the `## M4+ tables (sketched)` section, ~line 1282) with the real five-table model, and note in the migration-approach section that `autonomous_tasks` was a placeholder superseded by `autonomous_sessions`.

**Dependencies:** M4-0.1 (LangGraph pinned — not strictly required for the migration, but Phase A lands as one coherent runtime base).

**Output:** The autonomous-layer data substrate exists; no executor yet.

**Verification:**
- `alembic upgrade head` runs cleanly against a fresh DB; `alembic downgrade -1` then `upgrade head` round-trips.
- `cd api && DATABASE_URL="postgresql+asyncpg://lq_ai:<POSTGRES_PASSWORD>@127.0.0.1:15432/lq_ai" ./.venv/bin/pytest api/tests/models/test_autonomous_models.py -q` covers a CRUD round-trip on each table + the per-user FK isolation constraint.
- OpenAPI conformance test holds (no orphan schemas).
- **Migration-rebuild rule (memory):** after this migration lands, rebuild **api + arq-worker + ingest-worker together** (`docker compose build api arq-worker ingest-worker && docker compose up -d`) — stale sibling workers crash-loop with "Can't locate revision identified by …" after a daemon bounce.

**Effort:** 6–8 hours.

**References:** [PRD §3.10 Data model](PRD.md#310-autonomous-layer-m4); ADR 0013 D3/D5; `docs/db-schema.md` Conventions; memory `feedback_migration_rebuild_all_workers`.

---

### Task M4-A2 — Executor skeleton: LangGraph state machine + typed state + enums + phase transitions

**Scope:**
- Create `api/app/autonomous/` mirroring `api/app/playbooks/`:
  - `__init__.py`
  - `state.py` — `AutonomousSessionState` TypedDict (mirror `app.playbooks.state.PlaybookExecutionState`): `session_id`, `user_id`, `current_phase`, `halt_state`, `cost_total_usd`, `max_cost_usd`, `findings: list[dict]`, `proposed_memory: list[dict]`, `error: str | None`. JSONable values only (LangGraph serializes state).
  - `enums.py` (or reuse `app.schemas.autonomous`) — the closed enums:
    - `class Phase(StrEnum): intake, analysis, drafting, ethics_review, delivery`
    - `class ToolIntent(StrEnum): retrieve_chunks, run_skill, run_playbook, propose_memory, emit_finding, notify`
    - `class HaltState(StrEnum): running, halt_requested, halted, paused`
    - `PHASE_GRANTS: dict[Phase, set[ToolIntent]]` exactly per the alignment guide §3:
      `intake → {retrieve_chunks}`, `analysis → {retrieve_chunks, run_skill, run_playbook}`, `drafting → {run_skill, emit_finding, propose_memory}`, `ethics_review → {emit_finding}`, `delivery → {notify}`.
  - `executor.py` — `run_autonomous_session(session_id, db, gateway)` building a `StateGraph` over the phases; the typed transitions are LQ.AI's R3 posture. The graph walks `intake → analysis → drafting → ethics_review → delivery`; each phase node calls tools **only** through `guarded_tool_call` (added in M4-A3 — a stub here that raises `NotImplementedError` so the skeleton compiles and the graph wiring is testable).
  - `nodes.py` — the phase nodes (pure functions over the state dict, mirroring `app.playbooks.nodes`).
  - `phases.py` — `run_phase_transition(session, to_phase, db)` that sets `current_phase` and writes the `autonomous_session.phase_transition` audit row (per alignment guide §3).
- Wire the executor as an arq job: register `autonomous_session_job` in the arq `WorkerSettings.functions` list. **Decision:** add it to the existing playbook/tabular worker (`api/app/workers/arq_setup.py::WorkerSettings.functions`, alongside `easy_playbook_generation_job` + `tabular_execution_job`) on the `M3_PLAYBOOK_QUEUE_NAME` queue — autonomous work shares the same durable worker, at lower priority than interactive use (§3.10 NFR). Set a per-job `job_timeout` consistent with a single session's expected duration.

**Dependencies:** M4-A1.

**Output:** The executor graph compiles and the phase-transition skeleton runs end-to-end against a session row (tools stubbed); no brakes yet.

**Verification:**
- `pytest api/tests/autonomous/test_executor_skeleton.py -q`: a session row drives the graph through all five phases; each transition writes a `phase_transition` audit row in order; the stubbed `guarded_tool_call` raises `NotImplementedError` (proving no tool path bypasses the chokepoint-to-be).
- `ruff` + `mypy` (api standard) clean.

**Effort:** 8–12 hours.

**References:** ADR 0013 D2; alignment guide §2 + §3 + §4 ("How to leverage the existing backend"); patterns to mirror — `api/app/playbooks/{executor,nodes,state}.py`.

---

### Task M4-A3 — The `guarded_tool_call` chokepoint: R4 + R5 + R6 + OTel + audit (the load-bearing task)

This is the heart of the milestone. Every tool call routes through one function that reads the halt state (R5), checks the phase grant (R6), projects cost against the cap (R4), opens the OTel span, writes the audit row, dispatches the tool, then records cost + outcome. **TDD: write the brake tests first (they are the acceptance bar from DE-293), watch them fail, then implement.**

**Files:**
- Create: `api/app/autonomous/cost.py` (the R4 estimator wrapper)
- Create: `api/app/autonomous/guard.py` (the chokepoint + the exception types)
- Create: `api/app/autonomous/audit.py` (the closed-enum audit wrapper)
- Modify: `api/app/autonomous/executor.py` (replace the M4-A2 stub with the real `guarded_tool_call`)
- Test: `api/tests/autonomous/test_brakes.py`, `api/tests/autonomous/test_autonomous_observability.py`

**Scope:**

1. **R4 cost wrapper** — `api/app/autonomous/cost.py::estimate_tool_cost(intent, params, db) -> Decimal`. The M2-E2 estimator is judge-specific (`app.citation.cost.estimate_judge_call_cost_usd(db, *, judge_model)` returns `Decimal`); the wrapper delegates to it for inference-bearing intents and returns `Decimal("0")` for non-inference intents:
   ```python
   from decimal import Decimal
   from app.citation.cost import estimate_judge_call_cost_usd
   from app.autonomous.enums import ToolIntent

   _INFERENCE_INTENTS = {ToolIntent.run_skill, ToolIntent.run_playbook}

   async def estimate_tool_cost(intent: ToolIntent, params: dict, db) -> Decimal:
       """Project the USD cost of a tool call for the R4 pre-flight check.
       Inference-bearing intents reuse the M2-E2 rolling-average estimator;
       retrieval/memory/finding/notify are local-only → zero marginal cost."""
       if intent in _INFERENCE_INTENTS:
           model = params.get("judge_model") or params["model"]
           return await estimate_judge_call_cost_usd(db, judge_model=model)
       return Decimal("0")
   ```

2. **The closed-enum audit wrapper** — `api/app/autonomous/audit.py`. The action strings are a closed set (alignment guide §3): `autonomous_session.{started, phase_transition, tool_call, halted, cost_cap_reached, completed}`. Wrap the project helper `app.audit.audit_action(db, *, user_id, action, resource_type, resource_id, details)`:
   ```python
   from app.audit import audit_action
   from app.models.autonomous import AutonomousSession

   _ACTIONS = {"started", "phase_transition", "tool_call", "halted",
               "cost_cap_reached", "completed"}

   async def autonomous_audit(db, session: AutonomousSession, event: str, **details):
       assert event in _ACTIONS, f"undefined autonomous audit action: {event}"
       await audit_action(
           db, user_id=session.user_id,
           action=f"autonomous_session.{event}",
           resource_type="autonomous_session",
           resource_id=str(session.id),
           details=details,  # counts/types/IDs/costs/enums ONLY — never raw entity values
       )
   ```

3. **The chokepoint** — `api/app/autonomous/guard.py`. Exception types `SessionHalted`, `ToolNotGranted`, `CostCapReached` (subclasses of an `AutonomousBrake` base in `app.errors` — use the `lq_ai.errors` hierarchy per CLAUDE.md; do not raise bare `Exception`). The function, keyed to the real symbols:
   ```python
   from app.observability_helpers import get_tracer, record_attributes
   from app.autonomous.cost import estimate_tool_cost
   from app.autonomous.audit import autonomous_audit
   from app.autonomous.enums import ToolIntent, HaltState, PHASE_GRANTS

   tracer = get_tracer(__name__)

   async def guarded_tool_call(session, intent: ToolIntent, params, db, gateway):
       """The single chokepoint. Every tool call goes through here."""
       with tracer.start_as_current_span("autonomous.tool_call") as span:
           record_attributes(span, **{                  # COUNTS + TYPES ONLY
               "autonomous.session_id": str(session.id),
               "autonomous.phase": str(session.current_phase),
               "autonomous.tool": str(intent),           # the intent, not its payload
               "autonomous.halt_state": str(session.halt_state),
           })

           # R5 — external halt, read BEFORE the call
           await db.refresh(session, ["halt_state"])
           if session.halt_state == HaltState.halt_requested:
               session.halt_state = HaltState.halted
               await autonomous_audit(db, session, "halted", reason="external_halt")
               record_attributes(span, **{"autonomous.outcome": "external_halt"})
               raise SessionHalted(reason="external_halt")

           # R6 — is this tool granted in the current phase?
           if intent not in PHASE_GRANTS[session.current_phase]:
               await autonomous_audit(db, session, "tool_call", tool=str(intent),
                                      outcome="tool_not_granted")
               record_attributes(span, **{"autonomous.outcome": "tool_not_granted"})
               raise ToolNotGranted(intent=intent, phase=session.current_phase)

           # R4 — would this call exceed the cap?
           projected = session.cost_total_usd + await estimate_tool_cost(intent, params, db)
           if session.max_cost_usd is not None and projected > session.max_cost_usd:
               session.cost_cap_reached = True
               session.halt_state = HaltState.halted
               await autonomous_audit(db, session, "cost_cap_reached",
                                      projected_usd=float(projected))
               record_attributes(span, **{"autonomous.outcome": "cost_cap_reached"})
               raise CostCapReached(projected_usd=projected)

           # --- run the tool ---  (inference via the gateway → anonymization +
           #     tier enforcement + cost accounting apply automatically)
           await autonomous_audit(db, session, "tool_call", tool=str(intent), outcome="started")
           result = await _dispatch(intent, params, gateway=gateway, db=db, session=session)

           session.cost_total_usd += result.cost_usd
           record_attributes(span, **{"autonomous.cost_usd": float(result.cost_usd),
                                      "autonomous.outcome": "success"})
           await autonomous_audit(db, session, "tool_call", tool=str(intent),
                                  outcome="success", cost_usd=float(result.cost_usd))
           return result
   ```
   `_dispatch(intent, …)` routes each `ToolIntent` to its handler; inference-bearing intents call `gateway` (the `GatewayClient` + `ChatCompletionRequest` path the playbook nodes use — `api/app/playbooks/nodes.py`), never a provider SDK.

4. **Update `session.last_activity_at`** on every successful `guarded_tool_call` (feeds the R5 idle watchdog in M4-A4).

**The acceptance tests (write first — DE-293 bar):**
- **R4:** a session whose projected cost exceeds `max_cost_usd` halts with `cost_cap_reached=True`, `halt_state='halted'`, and the partial result preserved; `CostCapReached` raised; `cost_cap_reached` audit row written.
- **R5:** a session whose `halt_state` is set to `halt_requested` between tool calls stops on the **next** `guarded_tool_call` with `SessionHalted`; the `halted` audit row written.
- **R6:** a session in `Phase.ethics_review` calling `ToolIntent.retrieve_chunks` (granted only at `intake`/`analysis`) raises `ToolNotGranted`; the `tool_call` audit row records `outcome='tool_not_granted'`.
- **Privacy guard** (`test_autonomous_observability.py`, mirror `gateway/tests/test_anonymization_observability.py`): drive a session that sees a document containing a synthetic PERSON/MATTER_NUMBER through an in-memory OTel exporter; assert **no** `autonomous.*` span attribute and **no** audit `details` value contains any raw entity value — only counts/types/IDs/costs/enum labels.

**Dependencies:** M4-A2.

**Output:** Every tool call is brake-guarded and observable; the DE-293 acceptance bar (R4/R5/R6 + privacy guard) is green.

**Verification:**
- `pytest api/tests/autonomous/test_brakes.py api/tests/autonomous/test_autonomous_observability.py -q` — all four classes pass; each test fails first against the M4-A2 stub (TDD red→green).
- `ruff` + `mypy` (api standard) clean.
- Grep guard: no `import anthropic` / direct provider SDK anywhere under `api/app/autonomous/`.

**Effort:** 16–22 hours (the milestone's largest single task).

**References:** ADR 0013 D3 + D6; alignment guide §3 (the authoritative pseudo-code) + §5 (OTel rules) + §6 (the acceptance bar); real symbols — `app.observability_helpers.{get_tracer,record_attributes}`, `app.citation.cost.estimate_judge_call_cost_usd`, `app.audit.audit_action`, `app.clients.gateway.GatewayClient`; mirror test — `gateway/tests/test_anonymization_observability.py`.

---

### Task M4-A4 — Halt API + idle-halt watchdog cron + per-session receipt + sessions read API

**Scope:**
- **Halt switch (R5):** `POST /api/v1/autonomous/sessions/{id}/halt` — sets `halt_state='halt_requested'` (the running session reads it on its next `guarded_tool_call` and transitions to `halted`); idempotent; 404 if not the caller's session (per-user isolation). Audited.
- **Sessions read API (the receipt trail):** `GET /api/v1/autonomous/sessions` (the caller's sessions, paginated, newest first) + `GET /api/v1/autonomous/sessions/{id}` (one session + its full receipt). 404 (not 403) on another user's session id, to avoid existence disclosure.
- **Idle-halt watchdog (R5):** an arq cron job `autonomous_idle_watchdog` (register in `WorkerSettings.cron_jobs`, mirroring `document_pipeline._build_cron_jobs()` / `cron(job, minute=…)`) that runs every minute, scans `idx_autonomous_sessions_active` for `status='running'` sessions whose `last_activity_at` is older than `idle_halt_minutes`, transitions them `running → paused`, and after a second idle interval `paused → halted` (writes the `halted` audit row, reason `idle_timeout`).
- **Per-session receipt:** `api/app/autonomous/receipt.py::build_receipt(session, db) -> dict` — a human-readable structure ("what the agent did and why"): per tool call the phase, intent, inputs *seen* (counts/types/IDs, never raw values), cost, outcome, and every gate passed; the phase transitions; the terminal state + reason. Persisted into `autonomous_sessions.result` on completion and returned by `GET …/sessions/{id}`. This is the §1.3 transparency principle applied to actions — readable by the **user**, not just the operator.
- Update `docs/api/backend-openapi.yaml` for the three endpoints; schema-conformance tests.

**Dependencies:** M4-A3.

**Output:** A user can halt a running session, list their sessions, and read a per-session receipt; idle sessions auto-halt instead of bleeding resources.

**Verification:**
- `pytest api/tests/autonomous/test_sessions_api.py -q`: halt sets `halt_requested` and the next tool call halts cleanly (integration with the M4-A3 chokepoint); list/detail return only the caller's sessions; another user's id → 404.
- `pytest api/tests/autonomous/test_idle_watchdog.py -q`: a session with `last_activity_at` backdated past `idle_halt_minutes` transitions `running → paused → halted` across two watchdog ticks, with the `halted` audit row.
- Receipt renders every tool call's phase/intent/cost/outcome with **no raw entity values** (extends the M4-A3 privacy-guard assertion to the receipt payload).
- OpenAPI conformance + `ruff` + `mypy` clean.

**Effort:** 12–16 hours.

**References:** ADR 0013 D3 (R5); alignment guide §3 (idle-halt) + §7 (receipt checklist item); arq cron pattern — `api/app/workers/document_pipeline.py::_build_cron_jobs`.

---

## Phase B — The four primitives

With the brake-guarded executor proven, Phase B adds the four v1 primitives. Each reuses the chokepoint (so each gets the brakes + telemetry + audit for free) and ships its own API surface + isolation test.

### Task M4-B1 — Per-user memory (system-proposes, user-owns) + `/autonomous/memory` API

**Scope:**
- The `propose_memory` tool intent (granted at `Phase.drafting`): the agent writes an `autonomous_memory` row with `state='proposed'` and `source_session_id` — **never** `state='kept'` (no silent writes; ADR 0013 D4).
- API (per PRD §3.10):
  - `GET /api/v1/autonomous/memory` — the caller's entries, filterable by `state` (`proposed`/`kept`/`dismissed`).
  - `POST /api/v1/autonomous/memory/{id}/keep` — `proposed → kept`, sets `kept_at`. (Edit-on-keep: optional `content` override in the body.)
  - `POST /api/v1/autonomous/memory/{id}/dismiss` — `proposed|kept → dismissed`.
  - `DELETE /api/v1/autonomous/memory/{id}` — soft-delete (`deleted_at`).
- **Memory injection:** only `state='kept'` entries are read into an autonomous session's context (and, separately, surfaced to chat per §3.10 user story). Proposed entries are never auto-applied.
- Update `docs/api/backend-openapi.yaml`; schema-conformance tests.

**Dependencies:** M4-A3 (the `propose_memory` intent routes through the chokepoint).

**Output:** The agent proposes preference entries; the user reviews/keeps/edits/dismisses/deletes; only kept entries influence behavior.

**Verification:**
- `pytest api/tests/autonomous/test_memory.py -q`: the agent path can only create `proposed` rows (a test asserts no executor path writes `kept` directly); keep/dismiss/delete transitions work; only `kept` entries are injected.
- **Isolation test:** user A's `GET /autonomous/memory` never returns user B's entries; A cannot keep/dismiss/delete B's entry (404).
- OpenAPI conformance + `ruff` + `mypy` clean.

**Effort:** 10–14 hours.

**References:** ADR 0013 D4; [PRD §3.10 memory model](PRD.md#310-autonomous-layer-m4); §3.11 (the Project-context distinction the memory must not violate).

---

### Task M4-B2 — Precedent board (write/read/dismiss) + `/autonomous/precedents` API

**Scope:**
- The agent observes cross-matter patterns during a session and writes/increments `precedent_entries` rows (`pattern_kind`, `summary`, `observed_count++` on a recurring pattern). Read-mostly: the agent proposes; the user dismisses.
- API (per PRD §3.10):
  - `GET /api/v1/autonomous/precedents` — the caller's non-dismissed entries (filterable by `pattern_kind`).
  - `POST /api/v1/autonomous/precedents/{id}/dismiss` — sets `dismissed_at`.
  - (Promotion-to-Project is a **proposal only** — the agent may surface "promote this precedent into Project X's context" but never writes Project context directly, ADR 0013 D5. The promote action, if built, creates a Project-context *proposal*, not a write.)
- Update `docs/api/backend-openapi.yaml`; schema-conformance tests.

**Dependencies:** M4-A3.

**Output:** A per-user precedent board accumulates cross-matter patterns the user can read and dismiss; distinct from memory (about the user) and Project context (about the matter).

**Verification:**
- `pytest api/tests/autonomous/test_precedents.py -q`: recurring-pattern observation increments `observed_count`; dismiss hides the entry; the agent cannot write Project context directly (a test asserts the promote path produces a proposal, not a `projects` write).
- **Isolation test:** user A never sees or dismisses user B's precedents (per-user, Decision M4-9).
- OpenAPI conformance + `ruff` + `mypy` clean.

**Effort:** 10–14 hours.

**References:** ADR 0013 D5 + Decision M4-9; [PRD §3.10 precedent board](PRD.md#310-autonomous-layer-m4).

**Resolved at execution (2026-05-25, Kevin — these answer questions the plan/ADR left open; do not re-litigate):**
- **B2-a — Precedent write is a chokepoint tool intent.** Decision M4-3 forbids any agent write that routes around `guarded_tool_call`, so the precedent write is a new `ToolIntent.propose_precedent` (zero-cost local handler in `guard.py::_dispatch`, mirroring `propose_memory`): upsert-on-recurrence — find the caller's non-dismissed `precedent_entries` row with the same `pattern_kind` (+ matching `summary`) and `observed_count++`, else insert with `observed_count=1` and `source_session_id=session.id`. Add it to `cost.py`'s zero-cost/local set.
- **B2-b — `propose_precedent` is granted in BOTH `analysis` and `drafting`** in `PHASE_GRANTS` (precedent = document/clause patterns observed while reading docs AND recognized as recurring during synthesis). Update the alignment-guide §3 `PHASE_GRANTS` table comment to match (the guide's table predates Phase B; note the addition there).
- **B2-c — Promote-to-Project is BUILT NOW as a full proposal lifecycle (scope expansion past the 10–14h envelope, authorized).** New table `project_context_proposals` (migration **0041**, `down_revision=0040`) + ORM model + schemas, hard per-user (`user_id` FK `ON DELETE CASCADE`; `precedent_id` FK→`precedent_entries` `ON DELETE CASCADE`; `project_id` FK→`projects` `ON DELETE CASCADE`; `suggested_md` TEXT; `state` CHECK `proposed|accepted|rejected` via a `ProposalState` StrEnum in `schemas/autonomous.py`; `accepted_at`/`rejected_at`; `created_at`/`updated_at`; `chk_`/`fk_`/`idx_` naming per the A1 conventions). Endpoints: `POST /autonomous/precedents/{id}/promote` (body `{project_id}`; user-initiated — NOT an agent tool call, so no chokepoint intent — creates a `proposed` row carrying a server-derived `suggested_md` from the precedent's `summary`); `GET /autonomous/project-context-proposals` (caller's, filterable by `state`/`project_id`, paginated envelope); `POST …/{id}/accept` (the **user-authorized** write: append `suggested_md` to `projects.context_md`, set `state=accepted`+`accepted_at` — D5 is satisfied because the agent never writes context, the user accepting does); `POST …/{id}/reject`. The verification's "promote path produces a proposal, not a `projects` write" test asserts both that `propose_precedent`'s dispatch never touches `projects` AND that `/promote` creates a proposal row without mutating `context_md` (only `/accept` does).

---

### Task M4-B3 — Scheduled tasks (cron on arq) + `/autonomous/schedules` API

**Scope:**
- API (per PRD §3.10): `GET/POST /api/v1/autonomous/schedules` (create/list), `PATCH …/{id}` (enable/disable/edit), `DELETE …/{id}` (soft-delete). A schedule row carries a `cron_expr`, a target (playbook/skill + optional KB/project), and `enabled`.
- **Scheduler:** an arq cron job `autonomous_schedule_dispatcher` (register in `WorkerSettings.cron_jobs`, runs every minute) reads `enabled` schedules whose `next_run_at <= now()`, enqueues an `autonomous_session_job` (trigger_kind `'schedule'`, `trigger_ref` = the schedule id), and advances `next_run_at` from `cron_expr`. **Use a cron-expression parser already in the dep tree if one exists; otherwise** compute `next_run_at` with a minimal in-repo helper (CLAUDE.md: justify any new dependency — a full cron lib for a few fields is likely not warranted; document the determination in the PR).
- Each spawned session runs under the brakes exactly like a watch- or manually-triggered one (the trigger is the only difference).
- Update `docs/api/backend-openapi.yaml`; schema-conformance tests.

**Dependencies:** M4-A4 (the session executor + receipt exist to be scheduled).

**Output:** A user schedules a periodic run (e.g., weekly compliance scan); the dispatcher enqueues it on time; the run produces a receipt + notifications.

**Verification:**
- `pytest api/tests/autonomous/test_schedules.py -q`: a schedule with `next_run_at` in the past is picked up by one dispatcher tick and enqueues exactly one session; `next_run_at` advances; disabled schedules are skipped.
- **Isolation test:** a user manages only their own schedules.
- OpenAPI conformance + `ruff` + `mypy` clean.

**Effort:** 12–16 hours.

**References:** ADR 0013 D2; [PRD §3.10 user story 3](PRD.md#310-autonomous-layer-m4); arq cron pattern — `api/app/workers/document_pipeline.py::_build_cron_jobs`.

**Resolved at execution (2026-05-25, Kevin — do not re-litigate):**
- **B3-a — Trigger→target param seam = a `params` JSONB column on `autonomous_sessions`** (the recommended option). Migration **0042** adds `params JSONB NOT NULL DEFAULT '{}'`. Every trigger source populates it: the **B3 dispatcher** sets `session.params = {"kb_id": target_kb_id, "playbook_id": playbook_id, "skill_ref": skill_ref}` (only the non-null keys); B4's watch-enqueue and any manual/suggestion trigger do the same. The **executor** (`executor.py`) reads `session.params` into `initial_state` (replacing the hardcoded `kb_id=None`/`query=None`) — uniform across all trigger kinds, decoupled from the schedule/watch tables. This lands in B3 as shared infra; B4 reuses it. (Touches the load-bearing executor — keep the change minimal: read `params` into the existing state keys; the brake/commit contract is unchanged.)
- **B3-b — `autonomous_schedules` dispatcher index lands in migration 0042** (the A1-deferred index). Shape keyed to the dispatcher scan `WHERE enabled AND deleted_at IS NULL AND next_run_at <= now()`: a partial index `idx_autonomous_schedules_due (next_run_at) WHERE enabled AND deleted_at IS NULL`. Document the scan query the index serves in the migration comment.
- **B3-c — Cron parsing = a minimal in-repo helper, NO new dependency** (the plan's guidance: a full cron lib for five fields is not warranted; CLAUDE.md SBOM posture). Add `app/autonomous/cron.py` with `next_run_after(cron_expr: str, after: datetime) -> datetime` supporting the standard 5 fields (minute, hour, day-of-month, month, day-of-week) with `*`, lists (`1,2`), ranges (`1-5`), and steps (`*/5`); validate on schedule create/update (reject invalid `cron_expr` with 422). Unit-test the helper directly (next-run math + validation) alongside the dispatcher integration tests. Document the determination (why no dep) in the PR/commit.
- **B3-d — DELETE returns 200 with the soft-deleted entity** (never 204 — CLAUDE.md FastAPI pitfall), mirroring the memory/precedent DELETEs.

---

### Task M4-B4 — Watches (KB-arrival trigger, direct arq-enqueue from ingest) + `/autonomous/watches` API

**Scope:**
- API (per PRD §3.10): `GET/POST /api/v1/autonomous/watches`, `PATCH …/{id}`, `DELETE …/{id}`. A watch row binds a `knowledge_base_id` to a playbook/skill to run on document arrival.
- **Trigger plumbing (Decision M4-7 — direct arq-enqueue):** at the end of a successful ingest in `api/app/pipeline/ingest.py::ingest_file` (after the document is parsed + embedded + `ingest_status='ok'`), look up `enabled` watches for the document's `knowledge_base_id` (via `idx_autonomous_watches_kb_enabled`) and, for each, enqueue one `autonomous_session_job` (trigger_kind `'watch'`, `trigger_ref` = the watch id, the new document as the session target). The enqueue is best-effort and **must not** fail or retry the ingest itself (wrap in a guard that logs + emits an OTel event on enqueue failure but lets ingest commit).
- Each spawned session runs under the brakes; findings are notified (Phase C).
- Update `docs/api/backend-openapi.yaml`; schema-conformance tests.

**Dependencies:** M4-A4; touches `api/app/pipeline/ingest.py` (load-bearing M1 path — the enqueue is additive and non-blocking).

**Output:** New documents in a watched KB trigger a configured playbook/skill; the user is notified of findings (per PRD §3.10 user story 2).

**Verification:**
- `pytest api/tests/autonomous/test_watches.py -q`: ingesting a document into a watched KB enqueues exactly one session with the right `trigger_ref`; ingesting into an unwatched KB enqueues none; a watch-enqueue failure does **not** roll back or fail the ingest (regression test on the M1 ingest path).
- **Isolation test:** a user manages only their own watches; a watch only fires for sessions owned by the watch's user.
- OpenAPI conformance + `ruff` + `mypy` clean.

**Effort:** 12–16 hours.

**References:** ADR 0013 open-Q1 + Decision M4-7; [PRD §3.10 user story 2](PRD.md#310-autonomous-layer-m4); the ingest entry point — `api/app/pipeline/ingest.py::ingest_file`.

**Resolved at execution (2026-05-25, Kevin — corrects Decision M4-7's hook location; do not re-litigate):**
- **B4-a — The watch trigger hooks `attach_file`, NOT `ingest_file`.** Decision M4-7 named `ingest_file`, but the real ordering is **upload → `ingest_file` (→ `ingestion_status='ready'`) → `attach_file`**: `attach_file` (`api/app/api/knowledge_bases.py`) *requires* `ingestion_status=='ready'` before creating the `knowledge_base_files` join, so at `ingest_file` completion the file is in ZERO KBs and a hook there would never fire. The genuine "document arrives in a watched KB" event is `attach_file`. M4-7's *intent* (direct, best-effort, non-blocking arq-enqueue on KB arrival; trigger_kind `'watch'`) is preserved; only the location is corrected. **No new migration** — the `autonomous_watches` table and `idx_autonomous_watches_kb_enabled` exist from M4-A1 (migration 0039), and the `session.params` seam exists from M4-B3 (migration 0042).
- **B4-b — Trigger mechanics.** Add a testable core `fire_watches_for_kb(db, *, kb_id, file_id, enqueue=enqueue_autonomous_session_job) -> int` (mirrors `_run_schedule_sweep`'s injectable-enqueue testability). It selects `enabled AND deleted_at IS NULL` watches on `kb_id` (via `idx_autonomous_watches_kb_enabled`); for each, creates an `AutonomousSession(user_id=watch.user_id, project_id=watch.project_id, trigger_kind='watch', trigger_ref=watch.id, status='running', current_phase='intake', params={kb_id, playbook_id?, skill_ref?, file_id})`, commits the session rows, then enqueues each best-effort. **The session is owned by the watch's user** (`watch.user_id`), satisfying "a watch only fires for sessions owned by the watch's user." Call it from `attach_file` AFTER the join commits, wrapped in try/except (log + OTel event on failure) so a watch-trigger failure **never** fails or rolls back the attach (the load-bearing M1 path) — mirror the existing best-effort `enqueue_embed_job` block there. The B4 regression test asserts a watch-enqueue failure leaves the attach (204) + the `knowledge_base_files` join intact.
- **B4-c — `/autonomous/watches` CRUD** mirrors `/autonomous/schedules` (per-user 404-not-403; DELETE→200; `AutonomousWatchCreate`/`Update`/`ListResponse`; `AutonomousWatchRead` already exists from A1). `POST` validates the caller owns the target `knowledge_base_id` (404 if not theirs — you cannot watch a KB you can't see). 2 new OpenAPI paths (count 109 → 111).

---

## Phase C — Notifications + the web surface

### Task M4-C1 — Notification dispatch (email + in-app) via the `notify` tool intent

**Scope:**
- The `notify` tool intent (granted only at `Phase.delivery`): dispatches a notification summarizing the session's findings. Two channels for v1 (Decision M4-8):
  - **In-app:** a lightweight notifications surface (a `notifications` row keyed to `user_id`, read by the web app). If an in-app notification store already exists in the OpenWebUI fork, reuse it; otherwise add a minimal `autonomous_notifications` table.
  - **Email:** via the deployment's configured SMTP (reuse whatever email path the stack already has; if none, the email channel is config-gated and a no-op when SMTP is unset — honest "not configured" rather than a hard failure).
- The notification body carries **counts/types/IDs + a link to the receipt** — never raw entity values (the same hygiene as spans/audit).
- **Webhook to the Slack/Teams bridge is explicitly out of scope** (Decision M4-8 / [DE-312](PRD.md#de-312)) — leave a single documented seam (a `notify` channel enum with `webhook` reserved) so the fold-in is additive later.

**Dependencies:** M4-A4 (receipt to link to); M4-B3/M4-B4 (sessions that produce findings to notify on).

**Output:** A completed session notifies the user in-app (and by email if SMTP is configured), linking to the receipt.

**Verification:**
- `pytest api/tests/autonomous/test_notifications.py -q`: a delivery-phase `notify` call writes an in-app notification; the email channel is a clean no-op when SMTP is unconfigured; the notification body contains no raw entity values.
- `notify` is rejected by the chokepoint at any phase other than `delivery` (regression on M4-A3's R6).
- `ruff` + `mypy` clean.

**Effort:** 8–12 hours.

**References:** ADR 0013 open-Q2 + Decision M4-8; alignment guide §3 (`notify` at delivery).

**Resolved at execution (2026-05-25, Claude — defensible defaults anchored in the plan + CLAUDE.md; flag to Kevin, not blocking):**
- **C1-a — Email transport = stdlib `smtplib` via `asyncio.to_thread`, NO new dependency.** The api has no existing email path (no SMTP settings, no mailer). CLAUDE.md's dependency-justification + SBOM posture rules out `aiosmtplib` ("slightly more elegant" is not justification) when stdlib `smtplib` + `email.message.EmailMessage` run in a thread does the job. Add an `app/autonomous/notify_email.py` sender that is a **clean no-op when SMTP is unconfigured** (returns without error) — honest "not configured", never a hard failure.
- **C1-b — SMTP config = new api `Settings` fields** (`smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `smtp_from`, `smtp_use_tls`), all optional; email is enabled iff `smtp_host` is set. (api-side, not gateway.yaml — the `notify` handler is api-side.)
- **C1-c — One in-app row is the durable record; email is a best-effort TRANSPORT of it, not a second row.** The `notify` chokepoint handler (`guard.py`) keeps writing the single `autonomous_notifications` row (`channel='in_app'`); C1 adds a best-effort email send of that same counts/IDs/receipt-link body to the session user's `User.email` when SMTP is configured, wrapped so a send failure never breaks the session (logged + OTel event). `channel`'s `email`/`webhook` enum values stay the reserved seam (webhook = DE-312).
- **C1-d — Read/dismiss API uses the existing `read_at` column** (no schema change; `autonomous_notifications` has no `dismissed_at`). `GET /autonomous/notifications` (caller's, `?unread=true` filter, paginated, newest-first), `POST /autonomous/notifications/{id}/read` (sets `read_at`; idempotent) — "read" IS the dismiss action. Per-user 404-not-403; +2 OpenAPI paths (count 111 → 113). The deferred notifications read-index (0040's deferred `user_id, read_at, created_at` index) lands here now that the read query shape is concrete.
- **C1-e — R6 regression:** assert `notify` is rejected (`ToolNotGranted`) at every phase other than `delivery` (it's only in `PHASE_GRANTS[Phase.delivery]`).

---

### Task M4-C2 — Web dashboard: sessions + receipts + memory review + precedent board + schedule/watch config

> **STATUS: ✅ DONE** (2026-05-27). Design + 20-task plan in `docs/LQVern/m4-c2-dashboard-design.md` + `docs/LQVern/m4-c2-implementation-plan.md`. Shipped: backend opt-in slice (`users.autonomous_enabled` col + migration 0044, `/users/me/preferences` field, `AutonomousEnabledUser` gate on mutate endpoints with read+halt open, spawn-path opt-in guards, receipt per-entry timestamps) + the full SvelteKit dashboard (`autonomous.ts` client, opt-in Settings toggle, opt-in-gated top-tab + rail with redirect guard, sessions list + chronological receipt timeline + halt, memory review, precedent board + promote, proposals accept/reject, schedules + cron input, watches, notifications + unread badge) + Cypress E2E (`web/cypress/e2e/m4-autonomous.cy.ts`, 8 tests). 322 backend tests + 124 web unit tests + 8 E2E green; ruff/mypy clean; OpenAPI 113 paths unchanged. Deferred: DE-323 (proposals on Matter page), DE-324 (global notification bell). Branch HEAD ~`04c85e4`.

**Scope (web, SvelteKit — `web/src/routes/lq-ai/autonomous/`):**
- **Opt-in gate:** the Autonomous Layer is off by default, opt-in per user (§3.10) — a settings toggle; surfaces stay hidden until opted in.
- **Sessions list + receipt view** — the receipt rendered as "what the agent did and why": phases, per tool call (intent/cost/outcome/gates), terminal state. The headline UX: *you can audit exactly what the agent did.* A visible **Halt** button on a running session (calls `POST …/halt`).
- **Memory review** — proposed vs kept vs dismissed; keep/edit/dismiss/delete controls (D4 — the user owns it).
- **Precedent board** — read + dismiss; the "propose promotion into a Project" affordance (proposal only).
- **Schedules + watches config** — create/list/enable/disable/delete.
- Follow OpenWebUI/SvelteKit conventions + the project's design-system primitives (CLAUDE.md: no ad-hoc Tailwind, no React in `web/`). Cypress E2E in `web/cypress/e2e/m4-autonomous.cy.ts` covering opt-in → view a session receipt → halt → keep a memory entry → dismiss a precedent.

**Dependencies:** M4-A4, M4-B1, M4-B2, M4-B3, M4-B4 (the APIs the dashboard drives).

**Output:** A user can opt in, configure watches/schedules, read session receipts, halt a running session, and curate memory + precedents — all from the web app.

**Verification:**
- `cd web && npm run check` (svelte-check) passes; `npm run lint` clean.
- Cypress E2E passes against a running stack: opt-in, receipt view, halt, memory keep, precedent dismiss.
- Visual smoke: the autonomous surfaces are unreachable until opt-in.

**Effort:** 18–24 hours.

**References:** §3.10 (off-by-default, opt-in; the dashboard renders receipts, does not run the loop); ADR 0013 D2 (web layer is presentation only).

---

## Phase D — Learn viz + boundary-registers + acceptance

### Task M4-D1 — Learn-tab "Autonomous flow" visualization (build per the spec)

**Scope:** Build the visualization specified in **[`docs/LQVern/learn-tab-autonomous-flow-viz-spec.md`](LQVern/learn-tab-autonomous-flow-viz-spec.md)** (deliverable (b) of the planning session; the full contents — playground steps, controls, teaching point, honesty caveat, how/build-page wiring, and the data-residency + system-architecture updates — are in that spec). In summary:
- New **"Autonomous flow" playground** (`web/static/learn/playgrounds/autonomous-flow.html`) — self-contained single-file HTML, shared dark theme, controls + preview + copy-out, mirroring `otel-eval.html` / `test-landscape.html`. Steps through a single-agent session: phase transitions → guarded tool calls → the R4/R5/R6 brakes firing → the per-session receipt. **Headline teaching point:** *you can audit exactly what the agent did and why.* Marked as illustrating a **planned M4 capability** until the layer ships (honesty — §1.9).
- **How-it-Works** (`web/src/routes/lq-ai/learn/how/+page.svelte`) — a new section embedding the playground (verify section numbering at build time; otel-eval is §11).
- **Build page** (`web/src/routes/lq-ai/learn/build/+page.svelte`) — an "anatomy of an aligned agentic flow" element pointing at the alignment guide. (Note: `.gitignore build/` shadows this path — edits need `git add -f`.)
- **Existing viz updates:** `data-residency.html` + `system-architecture.html` gain the new `api/app/autonomous` arq node + its data stores (the five tables).

**Dependencies:** the spec doc (already written); ideally after M4-A3/M4-A4 so the playground's brake/receipt depiction matches the shipped span/attribute/receipt names (no doc-vs-code drift). May be specced anytime; **build** after the substrate so it stays honest.

**Output:** The public Learn tab explains the autonomous flow's alignment story — phases, brakes, receipt — without implying it is running before it ships.

**Verification:**
- `cd web && npm run check` passes; the playground renders at `/lq-ai/learn` and is reachable from the index.
- The playground's span/attribute/receipt labels match the names M4-A3/M4-A4 emit (no drift).
- The "planned M4 capability" caveat is present until §3.10 flips to shipped.

**Effort:** 12–16 hours.

**References:** handoff §4; the spec doc; playground convention — `web/static/learn/playgrounds/{otel-eval,test-landscape}.html`.

---

### Task M4-D2 — Boundary-registers flip + docs finalization + fresh-install acceptance

**Scope:**
- **Boundary-registers (DE-293):** in `docs/security/boundary-registers.md`, flip **R4 economic**, **R5 temporal**, and **R6 contextual** from "deferred-with-commitment" to **"shipped"**, each with **line-level source citations** into `api/app/autonomous/guard.py` (the chokepoint) + the brake tests. Update §1.8's register-state paragraph in the PRD.
- **PRD status flip:** §3.10 status from "Deferred-M4" to "SHIPPED (v0.4.0)"; the four primitives + the alignment contract marked shipped; the M4 changelog entry added. Resolve §3.10's "Dependencies" line ("OpenWebUI Pipelines framework") — it is stale per ADR 0013; correct it.
- **Alignment guide reconcile:** verify `docs/LQVern/agentic-flow-alignment-guide.md`'s pseudo-code matches the shipped `guard.py` (the guide is the contributor contract — drift is a bug); update the one helper-name note (`estimate_tool_cost` wraps `estimate_judge_call_cost_usd`).
- **API + schema docs:** every M4 endpoint reflected in `docs/api/backend-openapi.yaml` with passing conformance tests; `docs/db-schema.md` autonomous section matches the shipped migration; `grep -nE "M4-[A-Z0-9]" docs/PRD.md` returns non-empty for the shipped tasks.
- **New doc:** `docs/autonomous-layer.md` — operator + user guide (opt-in, the four primitives, the brakes, reading a receipt, the privacy posture).
- **HONEST-STATE.md:** move the Autonomous Layer from "not yet started" to shipped with the honest scope (single-agent v1; multi-agent deferred per DE-294; webhook-notify deferred per DE-312).
- **Fresh-install acceptance:** `docker compose down -v && docker compose up --build`; opt in; create a watch + a schedule; trigger a session (ingest a doc into the watched KB); confirm the brakes (force an overspend; hit Halt; let one idle out), the receipt, the notification, and the memory/precedent proposals all work end-to-end on a clean install. Reviewing-attorney walk-through of an autonomous session against a real document (legal-substance review per CLAUDE.md skills process — the maintainer team does not own legal review).
- File any blockers as DE-XXX **before** tagging v0.4.0.

**Dependencies:** all of Phases A–C; M4-D1 (the Learn viz is part of the honest public story).

**Output:** R4/R5/R6 are verifiably shipped in source; docs match implementation; a fresh-install validation passes; v0.4.0 is tagging-ready.

**Verification:**
- `docs/security/boundary-registers.md` R4/R5/R6 cite real `api/app/autonomous/` lines; the cited lines exist.
- Full suite green: `cd api && ./.venv/bin/pytest -m "unit or integration" -q`; `ruff format --check` + `ruff check` + `mypy` (api standard); `cd web && npm run check`.
- Fresh-install walkthrough completes every M4 surface without maintainer help; the four acceptance brakes demonstrably fire on a clean stack.
- `grep -nE "M4-[A-Z0-9]" docs/PRD.md` non-empty per shipped task.

**Effort:** 14–18 hours.

**References:** handoff §3 (boundary-registers flip, acceptance bar); `docs/security/boundary-registers.md`; CLAUDE.md §"What good output looks like" + memory `feedback_dry_run_value` (fresh-install before tag), `feedback_no_maintainer_legal_review`.

---

## Total effort estimate

| Phase | Tasks | Effort |
|---|---|---|
| **0 — Dependency prep** | 1 (M4-0.1) | ~4–8 hours |
| **A — Substrate + brakes** | 4 (A1–A4) | ~42–58 hours |
| **B — The four primitives** | 4 (B1–B4) | ~44–60 hours |
| **C — Notifications + web** | 2 (C1–C2) | ~26–36 hours |
| **D — Learn viz + acceptance** | 2 (D1–D2) | ~26–34 hours |
| **Total** | **13 tasks** | **~142–196 hours** |

This fits a **~4–5-week M4 build** for a single full-time contributor, or ~8–9 weeks part-time. The two largest tasks are M4-A3 (the chokepoint — the milestone's load-bearing piece) and M4-C2 (the web dashboard). Phase A is sequential and must complete green before Phase B; within Phase B the four primitives are largely independent and can run in parallel sessions once Phase A lands.

---

## How to use this with Claude Code

The recommended workflow mirrors the M1–M3 implementations:

1. **Hand Claude Code this document, plus ADR 0013, the PRD §3.10 build-out, the alignment guide, `docs/db-schema.md`, the OpenAPI sketches, `gateway.yaml.example`, and `CLAUDE.md`.**
2. **Pick the next task by ID:** "Implement Task M4-A1 — autonomous-layer data model."
3. **Work TDD (red→green).** The acceptance tests in M4-A3 / the isolation tests in M4-B1/B2 are the contract — write them first, watch them fail, then implement.
4. **Verify against the documented verification step** before moving on. Self-verification of "I think this works" is not sufficient (CLAUDE.md).
5. **Phase A is a gate.** Do not start Phase B primitives until the M4-A3 chokepoint + its acceptance tests are green. The four primitives (B1–B4) can then run in parallel sessions.
6. **Don't make architectural decisions mid-task.** Decisions M4-1 through M4-10 are locked. If a task surfaces a question they don't anticipate, stop, ask Kevin, document it here, resume.
7. **Surface ideas as DE-XXX** in PRD §9; don't expand the task to absorb them.
8. **Push branches to both remotes** (origin + tucuxi). **Never** delete merged feature branches (memory `feedback_branch_preservation`).
9. **Practicing-attorney review** applies to any legal-substance surface (the reviewing-attorney walk-through in M4-D2); agents do not attest.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| The chokepoint is bypassed by a tool added later, silently dropping a brake or the telemetry. | **One chokepoint by construction** (M4-A3): every tool routes through `guarded_tool_call`; adding a tool = adding a `ToolIntent` enum member + a `PHASE_GRANTS` entry. A grep-guard test asserts no `_dispatch` branch runs a tool outside the guard. The alignment-guide checklist (§7) is the PR gate. |
| Raw entity values leak into a span attribute, audit row, receipt, or notification. | The privacy-guard test (M4-A3, mirroring `test_anonymization_observability.py`) is the acceptance bar and extends to the receipt (M4-A4) + notification (M4-C1). Attribute hygiene is counts/types/IDs/costs/enums only. |
| The R4 estimator under-projects, letting a session overspend before the cap trips. | `estimate_tool_cost` reuses the M2-E2 rolling-average estimator; the cap is checked **pre-flight** (projected, not post-hoc) and the partial result is preserved on `cost_cap_reached`. The deployment default ($5) is conservative; operators can lower it in `gateway.yaml`. |
| The watch enqueue fails or retries the M1 ingest path, regressing a load-bearing surface. | Decision M4-7's enqueue is best-effort and non-blocking: a failure logs + emits an OTel event but lets ingest commit. A regression test (M4-B4) asserts a watch-enqueue failure does not roll back ingest. |
| The langgraph major bump (#68) breaks both executors mid-milestone. | M4-0.1 resolves the dependency posture **before** any autonomous code lands; the playbook executor's tests are the regression gate; the conservative default is to stay on `~= 0.2` for M4 unless a `1.x`-only API is needed. |
| Autonomous background work degrades interactive latency. | Sessions run on the existing arq-worker at lower priority than interactive use (§3.10 NFR); the idle-halt watchdog reclaims stalled sessions; per-session cost caps bound runaway cost. |
| Cross-user memory/precedent leakage (the §3.10 hard-isolation NFR). | Every table has a non-null `user_id` FK; every read/write API filters by the caller; isolation tests in M4-B1/B2 (and watches/schedules in B3/B4) are acceptance criteria, not optional. |
| The Learn viz implies the layer is running before it ships. | M4-D1 marks the playground as a **planned M4 capability** until §3.10 flips to shipped in M4-D2; the honesty caveat is a verification item. |

---

## What this plan does not cover

Deliberately out of scope for M4 v1; tracked for later milestones:

- **Multi-agent orchestration / cross-agent handoff validation** — Decision M4-1; stays deferred under [DE-294](PRD.md#de-294). M4 ships single-agent only.
- **Webhook notifications to the Slack/Teams bridge** — Decision M4-8; deferred fold-in gated on [DE-312](PRD.md#de-312). M4 ships email + in-app.
- **Per-deployment (org-shared) precedent board** — Decision M4-9; per-user only in v1. File a DE if an operator requests org-shared.
- **External side-effecting actions with approval gates** — the M4 single-agent interfaces are designed to extend to this (ADR 0013 D1 / [PRD §8.5](PRD.md#85-mcp-client-subsystem)); not v1 scope.
- **Contract Repository auto-relationship detection** ([PRD §3.16](PRD.md#316-contract-repository--auto-relationship-detection-m4)) — the other M4-slot capability; planned separately (this plan is the Autonomous Layer only).
- **A dedicated workflow engine (Temporal/Celery)** — rejected in ADR 0013 alternative B; arq is the substrate. Revisit only if cross-service saga orchestration becomes a requirement.

---

*Implementation plan maintained alongside the PRD. As tasks complete, mark them so the next contributor (or agent) sees current state. Tasks that need decomposition are split in-place and the document updated. The design is pinned in [ADR 0013](adr/0013-autonomous-layer-design-influences.md); this plan implements it.*
