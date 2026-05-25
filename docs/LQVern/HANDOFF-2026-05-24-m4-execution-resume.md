# Handoff — M4 / LQVern execution: resume at Task M4-A2

> **For:** the next Claude Code session, on branch **`feat/lqvern-m4-autonomous`** in **`~/Code/lq-ai`** (the canonical repo — never `~/Desktop/lq-ai`).
> **Where we are:** the M4 design is approved + on `main`; the implementation plan is written; **Phase A has begun** (M4-0.1 + M4-A1 done). **Resume at Task M4-A2.**
> **How to run it:** subagent-driven, one task per focused session, TDD, two-stage review (spec then code-quality). The plan is the task spec.

---

## 0. Start here (orientation, in order)

1. `CLAUDE.md` — conventions + decision routing (read if unfamiliar).
2. **`docs/M4-IMPLEMENTATION-PLAN.md`** — THE task list. Your next task is **M4-A2**; its full Scope/Dependencies/Output/Verification is there. Read the "Architectural decisions locked for M4" section (M4-1…M4-10) — **do not re-litigate these.**
3. **`docs/adr/0013-autonomous-layer-design-influences.md`** — the design (D1–D6). Now on `main`.
4. **`docs/LQVern/agentic-flow-alignment-guide.md`** — the chokepoint shape + OTel/audit rules. M4-A2 builds the skeleton that M4-A3's chokepoint plugs into.
5. The M4-A1 output you build on: `api/app/models/autonomous.py`, `api/app/schemas/autonomous.py` (the shared `StrEnum`s live here), `api/alembic/versions/0039_autonomous_layer.py`.
6. Patterns to mirror: `api/app/playbooks/{executor,nodes,state}.py` (the closest analog — M4-A2 mirrors it) and the arq worker `api/app/workers/arq_setup.py` (`WorkerSettings.functions`).

---

## 1. Status (as of 2026-05-24, end of the writing-plans + Phase-A-kickoff session)

- **Design on `main`:** PR **#100** merged (`main` HEAD `c1a4296`) — ADR 0013 + PRD §3.10 build-out + alignment guide. `de265.patch` was dropped (dead content = DE-289) and its references trimmed. `main` no longer lags the pinned design.
- **Plan + viz spec written** on the LQVern branch: `docs/M4-IMPLEMENTATION-PLAN.md` (13 tasks / 5 phases) + `docs/LQVern/learn-tab-autonomous-flow-viz-spec.md` (build sequenced as Task M4-D1; spec-only so far).
- **Branch `feat/lqvern-m4-autonomous` HEAD = `e40f945`**, pushed to **origin + tucuxi**, working tree clean.
- **M4-0.1 DONE** (`33c5d77`): langgraph held at `>=0.2.76,<0.3`. Dependabot **#68 closed** (its break is mypy-only — 1.x re-types `StateGraph` as generic so our `add_node` factories fail `[call-overload]`; runtime APIs unchanged; the autonomous executor needs no 1.x API). **DE-319** filed (migrate playbooks + tabular + autonomous executors to 1.x post-M4 — note `tabular/executor.py` is a *third* langgraph consumer the plan didn't originally name).
- **M4-A1 DONE** (`e40f945`): the 5-table data substrate. Migration `0039_autonomous_layer.py` (`down_revision=0038`): `autonomous_sessions` (+ brakes) / `autonomous_schedules` / `autonomous_watches` / `autonomous_memory` / `precedent_entries`, all per-user FK `ON DELETE CASCADE`. SQLAlchemy models + Pydantic schemas (shared `StrEnum`s = exact CHECK values) + `db-schema.md` section. **27 model tests pass; alembic round-trips; ruff + mypy clean.** Both review stages cleared.

## 2. The next task — M4-A2 (executor skeleton)

Build `api/app/autonomous/{__init__,executor,nodes,state,enums}.py` mirroring `api/app/playbooks/`:
- The `Phase` / `ToolIntent` / `HaltState` enums + the `PHASE_GRANTS` map (exact values in the plan + alignment guide §3). **Reuse the `StrEnum`s already defined in `api/app/schemas/autonomous.py` from M4-A1** — don't redefine `Phase`/`HaltState`; add `ToolIntent` + `PHASE_GRANTS`.
- The LangGraph `StateGraph` over a typed `AutonomousSessionState`, walking `intake → analysis → drafting → ethics_review → delivery`.
- `run_phase_transition(...)` writing the `autonomous_session.phase_transition` audit row.
- **`guarded_tool_call` is STUBBED here** (raises `NotImplementedError`) — the real chokepoint with R4/R5/R6 + OTel + audit is **M4-A3** (the load-bearing task). The skeleton test asserts the stub raises (proving no tool path bypasses the chokepoint-to-be).
- Register `autonomous_session_job` in `api/app/workers/arq_setup.py::WorkerSettings.functions` (shares the M3 playbook queue; lower priority than interactive use).

Full Scope/Verification: `docs/M4-IMPLEMENTATION-PLAN.md` → Task M4-A2.

## 3. Decisions locked in Phase A so far (honor; don't re-decide)

- UUID PK default is **`gen_random_uuid()` (v4)** — matches every shipped migration; the `uuid_generate_v7()` helper is not installed (db-schema's "v7" line is aspirational). Documented in the new db-schema section.
- CHECK-constraint names use the **`chk_`** prefix (the codebase ORM convention); FK `fk_…`, index `idx_…`.
- `project_id` FK is **`ON DELETE SET NULL`** across sessions/schedules/watches.
- `autonomous_schedules` index is **deferred to M4-B3** (when the scheduler's `next_run_at` scan query shape is concrete) — noted in the migration.
- langgraph stays **`>=0.2.76,<0.3`** for all of M4 (migration is DE-319, post-M4).
- **M4-A2 DONE** (`dad059e`): executor skeleton — LangGraph phase machine + typed state + `ToolIntent`/`PHASE_GRANTS` + `run_phase_transition`; `guarded_tool_call` stubbed (→ A3); arq `autonomous_session_job` on the shared `M3_PLAYBOOK_QUEUE_NAME`. Two-stage review fixed a real data-loss bug (happy path never committed → worker's `async with factory()` rolled back every successful run; row stuck at `running`) + the state-dict error path + `completed_at`. 37 tests pass. Pushed origin + tucuxi.
- **M4-A3 `_dispatch` scope = WIRE EVERYTHING REAL** (Kevin's call): all six `ToolIntent` handlers route to real downstreams in A3, not stubs — `retrieve_chunks`→`app.knowledge.hybrid_search`, `run_skill`/`run_playbook`→`GatewayClient`, `propose_memory`→real `autonomous_memory` row write (ahead of B1's API), `emit_finding`→session state/result.
- **`notify` in A3 = REAL IN-APP ONLY** (Kevin's call): A3 builds a notifications table + migration `0040` + model + an in-app persist handler so `notify` writes a durable artifact. **Email/SMTP transport + the read/dismiss API + web surface stay in M4-C1.** This is a deliberate, bounded C1 pull-forward (the in-app data model + write side only). C1's scope shrinks accordingly.
- **A3 is being executed as four reviewed sub-dispatches** (A3.1 errors+cost+audit ✅ `9774c33`; A3.2 notifications model+migration 0040 ✅ `df6f575`; A3.3a chokepoint guard.py + R4/R5/R6 brakes + OTel + audit + local handlers (emit_finding/propose_memory/notify) + brake tests ✅ `66da966`; **A3.3b NEXT** = real retrieve_chunks/run_skill/run_playbook handlers + executor wiring + privacy-guard test) — execution mechanics for an over-large task; the plan still treats A3 as one task.
- **A3.3b handler depth (anchored in the plan, not re-litigated):** inference intents `run_skill`/`run_playbook` make **GatewayClient chat-completion calls** (mirroring `api/app/playbooks/nodes.py`'s gateway path) — NOT nested playbook-executor sub-flows. `retrieve_chunks`→`app.knowledge.hybrid_search`. Handlers are **param-driven** (kb_id / model / messages / playbook_id arrive via `params`); the trigger→target resolution that POPULATES those params is Phase B (B3/B4). The privacy-guard test supplies a real KB+document with synthetic PII and asserts no raw value lands in any `autonomous.*` span attr or audit `details`.
- **Brake-commit contract (documented in guard.py + executor.py + nodes.py docstrings):** an `AutonomousBrake` mutates session + flushes an audit row then raises WITHOUT committing; the executor's terminal `except` commits. A node that catches a brake locally MUST commit or the latch+audit row are lost (the A2 data-loss class). A3.3b nodes let brakes propagate.
- **HONEST-STATE / #99 (separate branch):** issue #99 (dead `paddleocr` placeholder breaking `--profile local`; OCR never implemented) fixed on branch `fix/issue-99-local-profile-paddleocr` → **PR #101** to main. Filed **DE-320** (scanned-PDF OCR). Note: DE-320 is on that branch, not the M4 branch; DE-319 (langgraph 1.x migration) is on the M4 branch. No collision.

## 4. How to execute (the workflow Kevin chose)

- **Subagent-driven, per task** (`superpowers:subagent-driven-development`): dispatch a fresh implementer subagent with full task text + scene-setting (don't make it read the plan file — paste the task), then **spec-compliance review first, then code-quality review**; the implementer fixes any issues; re-review; mark complete. The controller (you) does not pause for "should I continue?" between *sub-steps* — but **Phase A is a hard gate before Phase B**, and the plan's "one task per focused session" means a natural checkpoint per task is fine.
- **TDD** (red→green). New endpoints (later tasks) get unit + integration + OpenAPI-conformance tests.
- **Gates:** `ruff format` AND `ruff check` (separately — CI runs both), `mypy` (api standard). **DCO sign-off** (`git commit -s`) + the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer. Repo git identity is already correct (`Kevin-Tucuxi <kevin@tucuxi.ai>`) — don't override it.
- **Push to BOTH remotes** after each task: `git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous`. Never delete merged branches.

## 5. Gotchas / environment

- **Local test DB:** read `POSTGRES_PASSWORD` from repo-root `.env`; `cd api && DATABASE_URL="postgresql+asyncpg://lq_ai:<pw>@127.0.0.1:15432/lq_ai" ./.venv/bin/pytest … -q` (conftest makes a throwaway test DB — safe). The venv is `api/.venv`.
- **Migration-rebuild rule:** migration `0039` is committed but **not yet deployed**. When it deploys to a running stack, rebuild **api + arq-worker + ingest-worker together** or the stale siblings crash-loop on "Can't locate revision `0039`."
- **Inference always goes through the gateway** (`app.clients.gateway.GatewayClient`) — never a provider SDK from `api/`. This is what gives autonomous flows anonymization + tier + cost for free.
- `.gitignore build/` shadows `web/src/routes/lq-ai/learn/build/` — edits there need `git add -f` (relevant only at M4-D1).

## 6. Precise kickoff message to paste into the next session

> Continue M4 / LQVern execution on LQ.AI in `~/Code/lq-ai` (canonical repo — never `~/Desktop/lq-ai`), on branch `feat/lqvern-m4-autonomous`. Read `docs/LQVern/HANDOFF-2026-05-24-m4-execution-resume.md` first — it has full state. Phase A is underway: M4-0.1 + M4-A1 are done and pushed (branch HEAD `e40f945`). **Resume at Task M4-A2** (executor skeleton) per `docs/M4-IMPLEMENTATION-PLAN.md`. Run it subagent-driven (implementer → spec review → code-quality review), TDD, honoring the locked decisions M4-1…M4-10 and the Phase-A decisions in the handoff §3. Push to both remotes (origin + tucuxi). Stop and ask me on any architectural question not anchored in the design (ADR 0013 / PRD §3.10 / alignment guide). Phase A is a hard gate before Phase B.

---

*Drafted 2026-05-24 at the Phase-A-kickoff checkpoint. Memory `project_lq_ai_status` carries the same state; this doc is the focused execution-resume brief.*
