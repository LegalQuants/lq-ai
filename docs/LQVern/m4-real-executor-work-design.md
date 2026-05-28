# M4 — Wire real in-loop agentic work into the Autonomous executor (design)

> **Date:** 2026-05-27 · **Status:** approved, awaiting implementation plan · **Branch:** `feat/lqvern-m4-autonomous` · **Companion to:** [`docs/M4-IMPLEMENTATION-PLAN.md`](../M4-IMPLEMENTATION-PLAN.md), [ADR 0013](../adr/0013-autonomous-layer-design-influences.md), [`agentic-flow-alignment-guide.md`](agentic-flow-alignment-guide.md), [PRD §3.10](../PRD.md#310-autonomous-layer-m4).
>
> **Why this exists.** The M4 fresh-install acceptance on 2026-05-27 confirmed the *autonomous substrate is real and shipped* (chokepoint, R4/R5/R6 brakes, audit, receipt, opt-in gate, schedules + watches + memory + precedents + notifications + dashboard, all wired end-to-end on a clean build), but the *executor is an intended walking skeleton*: the analysis/ethics-review nodes are explicit no-ops, the drafting node emits a hardcoded `{"phase":"drafting","status":"oriented"}` finding, and no node ever calls `run_skill`/`run_playbook`/`propose_memory`/`propose_precedent`. The tool intents are plumbed and brake-tested at the chokepoint, but the agent's *actual work* is not wired. This design wires it — bounded, honest, brake-safe — so v0.4.0 ships a genuinely working single-agent Autonomous Layer rather than a substrate release.

---

## 1. Context: what's already real (and why this is scoped work, not a rebuild)

The 2026-05-27 acceptance + a read of `api/app/autonomous/guard.py` established:

- The **chokepoint tool handlers are fully implemented**:
  - `_handle_retrieve_chunks` → real hybrid KB search returning chunks for LLM use + a counts-only summary for audit.
  - `_handle_gateway_inference` (handles both `run_skill` and `run_playbook`) → real anonymized gateway chat-completion with cost accounting, `gateway_error` outcome on transport failure, mirroring `app.playbooks.nodes._dispatch_structured_call`.
  - `_handle_propose_memory` / `_handle_propose_precedent` / `_handle_notify` / `_handle_emit_finding` → real DB writes of `proposed` rows / notifications / findings.
- The **brakes (R4/R5/R6) are real**: enforced in order R5→R6→R4 at the chokepoint, with closed-enum audit + OTel span on every call, all proved by `api/tests/autonomous/test_brakes.py` (10 tests) and `test_idle_watchdog.py` (10 tests).
- The **trigger surfaces are real**: the arq cron sweep dispatches due schedules and the ingest-pipeline hook (`fire_watches_for_kb` at `api/app/api/knowledge_bases.py:539`) spawns watch sessions on document attach.

What is **not** wired (and what this design adds):

- The executor *nodes* (`api/app/autonomous/nodes.py`) do not invoke `retrieve_chunks` with the right scope, do not invoke `run_skill`/`run_playbook` at all, and do not invoke `propose_memory`/`propose_precedent`. They walk the phase machine and emit a hardcoded finding + a completion notify.
- Spawn paths (`watch_trigger.fire_watches_for_kb`, `autonomous_worker._run_schedule_sweep`) do not set `max_cost_usd` on the spawned session, so sessions get `None` (no cap → R4 cannot trip in production).
- The delivery node sets `session.status = "completed"` but never writes an `autonomous_session.completed` audit row, so `build_receipt`'s `terminal_reason` stays `None` for the receipts a user actually sees on the dashboard.

Because the inference and tool plumbing is already real, this is **node-orchestration work plus two small enabling changes plus two minor bug fixes** — bounded.

## 2. Decisions locked (from the 2026-05-27 brainstorm)

1. **Work model.** **Watch** → run the bound `skill_ref`/`playbook_id` on the *arriving document*. **Schedule** → run it over documents added to the target KB since the schedule's `last_run_at` (a "what changed since I last looked" digest). Both triggers do real work; schedule semantics are bounded by `last_run_at`.
2. **Skill/playbook execution path.** The executor makes its inference calls through its **own** `guarded_tool_call(run_skill | run_playbook, ...)` so the autonomous chokepoint's R4/R5/R6 brakes apply to every call. **Naively nesting the existing Playbook executor is forbidden** — its internal gateway calls would route around the autonomous chokepoint and break the brake guarantee. Full multi-step playbook fidelity inside the autonomous loop (decompose playbook steps into autonomous tool calls) is **out of scope** → DE.
3. **Finding + proposal extraction.** A **single structured-output call.** The skill/playbook is instructed to return JSON `{findings[], suggested_memories[], suggested_precedents[]}`. The drafting node parses it and dispatches each item as its own guarded `emit_finding`/`propose_memory`/`propose_precedent` call (so each is independently brake-checked + audited). Tolerant fallback: unparseable response → one `emit_finding` with the raw text.
4. **Cost cap.** Add optional `max_cost_usd` to watch + schedule create schemas (and update). Spawn path **always sets** the spawned session's `max_cost_usd` — per-trigger value if set, else global config default (`~$5`, mirroring `gateway.yaml`). Closes the no-cap runaway, makes R4 live-demonstrable.
5. **Ethics-review phase stays light for v1.** It emits a single `emit_finding` summarizing the structured-output call's privilege/scope self-check (a field in the structured output). A dedicated ethics LLM gate is a DE.
6. **Model selection.** The analysis `run_skill`/`run_playbook` call uses the deployment's default chat model (a new `autonomous.default_model` config, falling back to the existing `default_chat_model`), unless the skill/playbook pins a model in its definition.

## 3. Architecture: the five nodes after wiring

Mapping the existing `PHASE_GRANTS` to real work (all calls go through `guarded_tool_call`; every call is brake-checked + audited):

| Phase | Grants (from `api/app/autonomous/enums.py`) | What the node now does |
|---|---|---|
| **intake** | `{retrieve_chunks}` | Resolve the work target. **Watch:** `retrieve_chunks` scoped to the triggering `file_id`. **Schedule:** `retrieve_chunks` scoped to documents in the target KB with `created_at > last_run_at` (the "new since I last ran" set). |
| **analysis** | `{retrieve_chunks, run_skill, run_playbook, propose_precedent}` | One `run_skill` or `run_playbook` guarded call (the structured-output call). System prompt = the skill `SKILL.md` body or playbook definition; context = the chunks from intake; instruction tail = the structured-output schema (§4 below). The returned content is stored in state for drafting. |
| **drafting** | `{run_skill, emit_finding, propose_memory, propose_precedent}` | Parse the structured output. For each `findings[i]` → guarded `emit_finding`. For each `suggested_memories[i]` → guarded `propose_memory` (writes `state='proposed'` — never `'kept'`, per ADR 0013 D4). For each `suggested_precedents[i]` → guarded `propose_precedent` (uses the existing upsert-on-recurrence at the handler). On unparseable response → one `emit_finding` with the raw content (graceful degradation). |
| **ethics_review** | `{emit_finding}` | Light v1: one `emit_finding` summarizing the `privilege_concerns` / `scope_concerns` fields of the structured output. If those fields are missing or empty, emit a single "no privilege/scope concerns flagged" finding. (A dedicated ethics LLM call is a DE.) |
| **delivery** | `{notify}` | `notify` with finding count + a short summary (already wired). **New:** write `autonomous_session.completed` audit row via `autonomous_audit(db, session, "completed", cost_total_usd=str(...))` BEFORE `build_receipt`, so `terminal_reason="completed"` is populated. Set `status="completed"`, `completed_at`, `result = build_receipt(...)`, commit. |

### 3.1 Brake interaction (unchanged contract, now exercised in production)

- **R4 cost cap** trips when the projected cost of the analysis `run_skill`/`run_playbook` call would exceed `session.max_cost_usd`. With per-trigger caps + a safe default, a low cap is now a one-line user setting → R4 is **live-demonstrable**. Latches `cost_cap_reached`, halts, preserves partial state.
- **R5 external halt** trips when `POST /autonomous/sessions/{id}/halt` arrives between tool calls (already proved live in the 2026-05-27 acceptance).
- **R6 phase-grant** trips if a node ever requests an out-of-phase intent (still primarily a defensive check; the node mapping above stays in-grant by construction).
- **R5 idle** unchanged (arq watchdog at `api/app/workers/autonomous_worker.py`, two-tick paused→halted).

### 3.2 Single-source-of-truth: the `gateway_error` outcome propagation

If the analysis `run_skill`/`run_playbook` returns `outcome="gateway_error"`, the drafting node MUST NOT pretend the call produced findings — it emits ONE `emit_finding` containing the error type + a fixed "the autonomous run failed at the analysis step" message, then proceeds to ethics_review (which sees no findings and emits "no findings to validate") and delivery (which notifies and completes honestly). The session still completes (not halted) — the brake-commit contract is honored and the receipt is honest about what happened.

## 4. The structured-output contract

The analysis call instructs the model to return JSON of this shape, appended to whatever the skill/playbook already requests:

```json
{
  "findings": [
    {"title": "...", "summary": "...", "severity": "info|warn|critical", "source_chunk_ids": ["..."]}
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
```

- All arrays may be empty; the node treats absence as empty.
- The handlers (`propose_memory`, `propose_precedent`, `emit_finding`) carry only the fields shipped code requires; the schema above is a superset (extra fields are dropped silently).
- **Tolerant parser:** strip Markdown code fences (```json … ```), attempt `json.loads`. On `JSONDecodeError`, fall back to a single `emit_finding` carrying `{"title": "Unstructured autonomous output", "summary": <raw_content>, "severity": "info"}` and proceed.
- The structured-output schema is documented once in `docs/LQVern/agentic-flow-alignment-guide.md` (the contributor contract) so future skills/playbooks intended to drive autonomous flows know what shape to return.

## 5. Schema changes (one Alembic migration: 0045)

New columns (`NULL`-able with safe defaults):

- `autonomous_watches.max_cost_usd NUMERIC(10,4) NULL` — per-trigger cost cap; `NULL` → fall back to config default at spawn.
- `autonomous_schedules.max_cost_usd NUMERIC(10,4) NULL` — same.

Schema additions (Pydantic):

- `AutonomousWatchCreate` + `AutonomousWatchUpdate` + `AutonomousScheduleCreate` + `AutonomousScheduleUpdate` gain `max_cost_usd: Decimal | None = None`. The Read schemas surface it for the dashboard. Naming/constraint conventions match the A1 migration set.

Spawn-path enforcement (`watch_trigger.fire_watches_for_kb` + `autonomous_worker._run_schedule_sweep`):

```python
session.max_cost_usd = trigger.max_cost_usd or settings.autonomous_default_max_cost_usd  # never None
```

Config addition: `settings.autonomous_default_max_cost_usd: Decimal = Decimal("5.00")` in `api/app/config.py` (env-overridable `LQ_AI_AUTONOMOUS_DEFAULT_MAX_COST_USD`).

## 6. `retrieve_chunks` scope extension (no new tool)

`_handle_retrieve_chunks` in `api/app/autonomous/guard.py` accepts two **new optional** params (keeps the existing semantic-query path working):

- `file_id: str | uuid.UUID | None` — restrict the search to chunks of this specific file. When set, the handler bypasses hybrid search and returns the file's chunks directly in `created_at`-order (paginated by `top_k`). The privacy-safe summary still carries only counts + IDs + offsets.
- `since: datetime | str | None` — restrict to chunks of documents with `KnowledgeBaseFile.created_at > since`. Combined with `kb_id`, this is the "new since `last_run_at`" path.

These are additive — existing callers (`query`-only hybrid search) keep working. Intake passes one of the new params depending on trigger type. The structured params remain in the node's input; the chokepoint's audit row still records counts/types only.

## 7. The two bug fixes (Q2 "fix both now")

### 7.1 `terminal_reason=None` on completed sessions

**Root cause:** `make_delivery_node` in `api/app/autonomous/nodes.py` sets `session.status = "completed"` and `session.completed_at` but never writes an `autonomous_session.completed` audit row. `build_receipt` derives `terminal_reason` from the first terminal audit row (`halted` / `cost_cap_reached` / `completed`); with no `completed` row, the field stays `None`. The headline-transparency artifact (the receipt) lies by omission.

**Fix:** in `make_delivery_node`, immediately before `session.result = await build_receipt(session, db)`, call `await autonomous_audit(db, session, "completed", cost_total_usd=str(session.cost_total_usd or "0"))`. The audit's closed-enum already accepts `"completed"` (see `api/app/autonomous/audit.py:_ACTIONS`). Add a regression test: a session driven through to delivery produces a receipt with `terminal_reason == "completed"`.

### 7.2 Watch-trigger live verification gap

**Cause:** the 2026-05-27 acceptance attempted multipart upload to `POST /knowledge-bases/{kb}/files`, which is an attach-by-`file_id` endpoint (JSON body), not a multipart upload. Returned 422; the watch-trigger live path was therefore not exercised end-to-end during fresh-install acceptance. The chain is provably wired (schedule path exercised the same spawn→walk→receipt chain), but watches specifically were not live-tested.

**Fix:** during re-acceptance after this design lands, follow the correct ingestion flow — POST the file to the files-upload endpoint, capture `file_id`, then POST `/knowledge-bases/{kb_id}/files` with `{"file_id": "..."}` to attach. The attach commit fires `fire_watches_for_kb`, which spawns the autonomous session. Confirm: a spawned session with `trigger_kind="watch"`, `trigger_ref=watch.id`, `params={"kb_id":..., "file_id":...}`, that walks the new real-work nodes and produces real findings + memory/precedent proposals against the dropped document.

## 8. Out of scope (DEs to file as part of M4 closeout)

- **DE — Multi-step Playbook fidelity inside the autonomous loop.** Decompose Playbook executor steps into autonomous tool calls (each guarded). The current design runs a playbook as a single guarded call; a follow-up wires the multi-step review through the autonomous chokepoint.
- **DE — Dedicated ethics LLM gate.** A guarded `run_skill` call dedicated to ethics validation (privilege/scope/conflict-of-interest checks against a small ethics skill), replacing the v1 light "emit a self-check finding."
- **DE — Schedule analyzes incremental docs only.** This design's schedule path already restricts to `created_at > last_run_at`; document the semantics + idempotency story (what happens if `last_run_at` is `NULL`? for v1: process nothing — first cron tick just sets `last_run_at`).
- **DE — Per-deployment precedent board.** Per ADR 0013 D6 + the M4 plan Decision M4-9, the precedent board is per-user for v1. Re-confirmed.

## 9. Testing strategy

Throwaway-DB pytest (the existing safe pattern; no host-side alembic against the dev DB):

- **`test_intake_scopes_retrieve_chunks`** — watch run intake-calls `retrieve_chunks` with `file_id` set; schedule run intake-calls it with `since=last_run_at`.
- **`test_analysis_structured_output_dispatch`** — gateway is mocked to return well-formed JSON; drafting dispatches the right number of `emit_finding` + `propose_memory` + `propose_precedent` calls; each goes through `guarded_tool_call` (audit rows + spans visible).
- **`test_drafting_tolerant_parse_fallback`** — gateway mock returns malformed text; drafting emits one `emit_finding` with the raw content, the session completes.
- **`test_terminal_reason_completed_audit_row`** — delivery node writes the `completed` audit row; `build_receipt` shows `terminal_reason="completed"`.
- **`test_spawn_sets_max_cost_usd`** — watch and schedule with `max_cost_usd` set thread it to the spawned session; with `NULL`, the session takes the config default.
- **`test_r4_trips_with_per_trigger_cap`** — a watch with `max_cost_usd=0.001` plus a gateway mock returning a positive cost makes R4 latch `cost_cap_reached` on the analysis call (an existing brake test pattern; the new piece is the per-trigger spawn).
- **`test_gateway_error_completes_honestly`** — analysis returns `outcome="gateway_error"`; the session completes (not halted), the receipt shows one error-explanation finding, `terminal_reason="completed"`.

Keep green: the 31-test brake/idle/opt-in suite (no API behavior change at the chokepoint).

## 10. Fresh-install acceptance (Phase D2 gate)

After this design ships, re-run the destructive `docker compose down -v && up --build` acceptance:

1. Clean build + migrations 0001 → 0045.
2. Bootstrap admin, change password, opt in.
3. Create a KB + a watch on it bound to the seed `nda-review-mutual` playbook (or equivalent), with `max_cost_usd=0.10`.
4. Upload an NDA PDF via the files endpoint, attach to the KB (the correct upload-then-attach flow — fix 7.2).
5. Verify the watch spawned a session; it walks intake → analysis (real gateway call) → drafting (real `emit_finding`/`propose_memory`/`propose_precedent` calls) → ethics_review (validation finding) → delivery (notify + completed audit).
6. The session's receipt now shows: phase_transitions = all five, tool_calls with real `cost_usd > 0`, `terminal_reason="completed"`.
7. The dashboard's Findings + Memory (proposed) + Precedents pages now have real content.
8. Live R4 demo: create a second watch with `max_cost_usd=0.001`; drop another doc; the session halts with `outcome="cost_cap_reached"`, partial state preserved, receipt's `terminal_reason="cost_cap_reached"`.
9. Live R5 demo: trigger a session, hit `POST /halt` between phases (the existing live R5 path) — confirm `terminal_reason="external_halt"`.

A fresh-install pass + the attorney legal-substance walk-through (which remains Kevin's, per `feedback_no_maintainer_legal_review`) is the v0.4.0 tag gate.

## 11. Honest framing after this lands

`docs/PRD.md` §3.10 status flips from `Deferred-M4` to **`SHIPPED (v0.4.0)`** with the **honest scope** named explicitly: aligned autonomous substrate + R4/R5/R6 brakes + four-primitive lifecycle + a working single-agent executor that runs the bound skill/playbook against the triggering work, emits real findings, and proposes durable memories/precedents the user reviews. Out-of-scope items (multi-agent — DE-294; multi-step playbook fidelity in-loop — new DE; dedicated ethics gate — new DE) are listed in §9 with the same precision M4 used for DE-293 / DE-289. `docs/security/boundary-registers.md` R4/R5/R6 flip to **shipped** with line-level citations into `api/app/autonomous/guard.py` + the brake tests (unchanged by this design — the brakes were always real; this design closes the executor-skeleton honesty gap that would otherwise force a hedged §3.10 status).

---

*Author: Claude Opus 4.7 (1M context) under Kevin's direction. Brainstormed + locked 2026-05-27. Companion to the M4 implementation plan. Implementation plan written as the next step (skill: `superpowers:writing-plans`).*
