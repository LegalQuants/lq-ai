# Autonomous Layer

> The Autonomous Layer is an opt-in (off by default) background
> executor that does real in-loop agentic work on a user's behalf —
> under hard brakes and with a full audit trail. Per PRD §1.3
> (transparency as a founding principle): an agent that acts on its
> own must be auditable after the fact. Every external action it takes
> flows through a single chokepoint, and every session emits an honest
> per-session receipt the user can read to see exactly what the agent
> did, what it cost, and why it stopped.

This doc describes the architecture (an arq job, not a standing
service), the five-phase executor, the single-chokepoint security
model, the three brakes, the four user-facing primitives and their API
surface, the receipt/transparency story, and the opt-in + cost-cap
posture. It is conservative about state: the ethics-review phase is a
light v1, a mid-analysis gateway error produces an honest "analysis
failed" finding rather than fabricated output, and the
Contract-Repository auto-relationship graph (a separate M4-roadmap
capability) is **not built**.

This is the per-feature companion to
[docs/HONEST-STATE.md §5](HONEST-STATE.md) (the shipped-vs-deferred
catalog).

---

## Honest state up front

| Aspect | State |
|---|---|
| Five-phase executor (intake → analysis → drafting → ethics_review → delivery) | **Shipped (M4).** Each phase calls real tools through the chokepoint — not a skeleton. |
| Single chokepoint enforcing R5 → R6 → R4 | **Shipped.** Every tool call routes through `guarded_tool_call`. |
| Four primitives (watches, schedules, per-user memory, precedent board) | **Shipped**, with API + web dashboard. |
| Honest per-session receipt (`terminal_reason`) | **Shipped.** Built only from audit rows (counts/types/IDs/enums — never raw values). |
| Per-user opt-in + per-session/per-trigger cost cap | **Shipped.** Off by default; mutate + spawn paths gated. |
| Document-grade artifacts from runs (Donna #8) | **Shipped, opt-in (default off).** Markdown/plain-text memos written into the run's target KB as real documents; no PDF/DOCX rendering, no artifact editing/versioning, and interactive chat/playbook paths are NOT covered. |
| Ethics-review phase | **Light v1.** Summarizes privilege/scope concerns surfaced upstream into one finding; a dedicated ethics LLM gate is a future enhancement. |
| Gateway error mid-analysis | **Honest path.** Produces one explanatory finding and a *completed* (not fabricated) receipt — no invented analysis. |
| Contract-Repository auto-relationship graph (PRD §3.16) | **Not built.** No `contract_relationships` table; roadmap (deferred-M4+). |

---

## Overview

A user who has opted in can attach **watches** (trigger a session when
a document arrives in a watched knowledge base), create **schedules**
(run on a cron expression), accumulate **per-user memory** (proposed
facts the user keeps or dismisses), and build a **precedent board**
(recurring document/clause patterns the agent observed). Each trigger
spawns one autonomous *session*: a single run of the five-phase
executor against a target (a KB, a query, an arriving file). The
session runs to completion, halts on a brake, or fails — and in every
terminal case it leaves an auditable row plus (on the expected stops) a
receipt.

The reason for the heavy brake machinery is the central design
constraint: an agent acting unattended is only acceptable if every
action it can take is bounded and recorded. The chokepoint is where
that boundedness lives.

---

## Architecture: an arq job, not a service

The executor is **not a standing service**. It is an arq job —
`autonomous_session_job` — run by the shared arq worker
(`api/app/workers/autonomous_worker.py`). A trigger enqueues a job
naming a session id; the worker dequeues it and calls
`run_autonomous_session` (`api/app/autonomous/executor.py`). There is
no long-lived autonomous process to operate, monitor, or scale
separately from the existing worker fleet.

Inside one job, the executor builds and runs a **LangGraph state
machine** (`StateGraph`, `api/app/autonomous/executor.py::_build_graph`).
The five phase nodes are added as sequential nodes with linear edges:

```
intake → analysis → drafting → ethics_review → delivery → END
```

There is no conditional branching in the graph. LangGraph is the
substrate (rather than a hand-rolled loop) because the node-level
decomposition keeps each phase testable in isolation and leaves room
for a future per-node checkpointing/resume pass without restructuring
the workflow.

The executor catches exceptions at the graph-invocation boundary and
persists a terminal `status` on the `autonomous_sessions` row, so a
polling caller always sees a terminal state:

- A node may populate `state["error"]` and return normally — LangGraph
  returns without raising — so the executor inspects the final state
  and writes `status='failed'` when `error` is set.
- A brake (subclass of `AutonomousBrake`) propagates to the terminal
  handler, which maps `SessionHalted` / `CostCapReached` → `halted`
  and `ToolNotGranted` → `failed`, then **commits** (the chokepoint
  flushes but never commits — see below).
- Any other in-graph exception is caught, logged, and persisted as
  `status='failed'` rather than re-raised (an uncaught exception would
  crash the worker process).

Session status values are `running` / `completed` / `halted` /
`failed` (`SessionStatus`, `api/app/schemas/autonomous.py`).

---

## The five-phase walk

Each phase is a node factory in `api/app/autonomous/nodes.py`. A node
transitions the session into its phase (an audited
`phase_transition`), does its work through the chokepoint, and returns
state deltas.

| Phase | What it does | Tools it may call (R6 grant) |
|---|---|---|
| **intake** | Scope the run. Fetches the arriving file's chunks (watch path: `file_id`) or chunks attached since the last run (schedule path: `kb_id` + `since`). | `retrieve_chunks` |
| **analysis** | Read the scoped material and run inference (skill/playbook) over it; record whether the inference succeeded or hit a gateway error. | `retrieve_chunks`, `run_skill`, `run_playbook`, `propose_precedent` |
| **drafting** | Synthesize findings. Parses the analysis output, emits one finding per item, optionally proposes memory/precedent, and forwards `privilege_concerns` / `scope_concerns` downstream. When the session opted in via `emit_artifacts`, also persists each parsed artifact (a markdown memo) into the target KB. | `run_skill`, `emit_finding`, `emit_artifact` (opt-in), `propose_memory`, `propose_precedent` |
| **ethics_review** | Light v1: emit one finding summarizing the privilege/scope concerns the drafting node forwarded, or one "no concerns flagged" info finding when both are empty. | `emit_finding` |
| **delivery** | Notify the user (durable in-app notification; best-effort email). On the expected-stop path the executor builds the receipt. | `notify` |

The per-phase grant sets are the authoritative `PHASE_GRANTS` map in
`api/app/autonomous/enums.py`; the table above is a readable view of
that map. The grant sets are `frozenset`s — immutable at runtime.

### The honest gateway-error path

If the analysis inference call returns a gateway transport/parse
error, the inference handler returns a `ToolResult` whose `outcome` is
`"gateway_error"` (the call is still charged its R4 estimate so a flaky
gateway can't game the budget accounting, but the audit trail records
the failure honestly rather than as a success). The drafting node sees
`analysis_outcome == "gateway_error"` and emits exactly one finding —
*"Autonomous analysis failed at the gateway. No findings, memories, or
precedents were produced."* — then proceeds to a normal `completed`
terminal state. The session does **not** fabricate analysis it could
not perform; it tells the user the gateway failed and stops cleanly.

---

## Single-chokepoint security model

Every external action the executor can take flows through one function:
`guarded_tool_call` (`api/app/autonomous/guard.py`). There is no other
path to a tool. The closed set of operations is the `ToolIntent`
enum (`api/app/autonomous/enums.py`):

`retrieve_chunks`, `run_skill`, `run_playbook`, `propose_memory`,
`propose_precedent`, `emit_finding`, `emit_artifact`, `notify`.

`guarded_tool_call` enforces the three brakes **in this order — R5 →
R6 → R4** — before dispatching, then records cost + outcome:

1. **R5 (temporal):** re-read `halt_state` from the DB (`db.refresh`)
   so an external signal that arrived after the executor started is
   honored at the next tool boundary. If `halt_requested`, transition
   to `halted`, write a `halted` audit row (`reason='external_halt'`),
   and raise `SessionHalted`.
2. **R6 (contextual):** if the requested `intent` is not in
   `PHASE_GRANTS[current_phase]`, write a `tool_call` audit row with
   `outcome='tool_not_granted'` and raise `ToolNotGranted`.
3. **R4 (economic):** estimate the call's USD cost once
   (`estimate_tool_cost`); if `max_cost_usd` is set and the projected
   total would exceed it, latch `cost_cap_reached`, transition to
   `halted`, write a `cost_cap_reached` audit row, and raise
   `CostCapReached`.

Only after all three pass does the chokepoint dispatch (`_dispatch`)
and then add the dispatched cost to `cost_total_usd`, stamp
`last_activity_at` (which feeds the R5 idle watchdog), and write the
final `tool_call` audit row.

**Commit boundary.** The chokepoint *flushes* audit rows and state
mutations but never *commits* — the caller (the executor's terminal
handler) owns the commit. This is load-bearing: when a brake raises, it
has already mutated the session (`halt_state` / `cost_cap_reached`) and
flushed an audit row; a caller that caught the brake and returned
without committing would silently drop both. The A3.3b nodes therefore
let brakes propagate to the executor's terminal handler, which commits.

The single R4 cost estimate is reused: the same `Decimal` value the cap
check computed is forwarded into `_dispatch`, so inference handlers
charge exactly what R4 approved — no double-charge, no divergence
between what was checked and what was billed.

**Dispatch detail.** Local intents (`emit_finding`, `emit_artifact`,
`propose_memory`, `propose_precedent`, `notify`) and `retrieve_chunks`
are zero-cost (`emit_artifact` writes to the DB and object storage but
makes no inference call — the artifact content comes from the analysis
phase's single inference response).
`propose_precedent` upserts race-safely via `INSERT ... ON CONFLICT`
against a partial unique index, incrementing `observed_count` on
recurrence — it **never** touches the `projects` table (promotion into
a Project's context is a separate, user-authorized proposal lifecycle).
`run_skill` / `run_playbook` route through the gateway with
`anonymize=True` by default (the autonomous flow may carry privileged
context).

---

## The three brakes

| Brake | Kind | What raises it | Exception | Terminal outcome |
|---|---|---|---|---|
| **R4** | Economic | Projected cost would exceed `max_cost_usd` (per-session cap; also a per-trigger cap on watches/schedules, migration `0045`) | `CostCapReached` | `halted`; receipt `terminal_reason='cost_cap_reached'` |
| **R5** | Temporal | External halt request (`POST /autonomous/sessions/{id}/halt`) honored at the next tool boundary; **or** the idle watchdog reaping a stalled session | `SessionHalted` | `halted`; receipt `terminal_reason='external_halt'` or `'idle_timeout'` |
| **R6** | Contextual | A node requested an intent not in its phase's `PHASE_GRANTS` set | `ToolNotGranted` | `failed` (a programming error, not an expected stop — no receipt) |

All three exceptions subclass `AutonomousBrake` (`app.errors`).
`SessionHalted` and `CostCapReached` are expected stops mapped to
`halted` and get an honest receipt; `ToolNotGranted` is treated as a
programming error mapped to `failed` (a failed-session receipt is a
separate, deferred decision).

### The R5 idle watchdog

R5's external-halt arm is complemented by an arq cron job —
`autonomous_idle_watchdog` (`cron(..., second=0)`, top of every
minute, `api/app/workers/autonomous_worker.py`). Its sweep
(`_run_idle_sweep`) runs two transitions per session, using the
per-session `idle_halt_minutes`:

1. `running` → `paused` when `last_activity_at` is older than
   `idle_halt_minutes`.
2. `paused` → `halted` (with a `halted` audit row,
   `reason='idle_timeout'`) when `last_activity_at` is older than
   `2 × idle_halt_minutes`.

---

## The four primitives and their API surface

All routes below are under the `/autonomous` prefix
(`api/app/api/autonomous.py`, `APIRouter(prefix="/autonomous")`) and
are gated behind the per-user opt-in (mutating routes require
`autonomous_enabled = true`). Ownership is enforced per row (a user
sees only their own sessions/memory/precedents/etc.).

### Sessions (the runs)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/autonomous/sessions` | List the user's sessions. |
| `GET` | `/autonomous/sessions/{session_id}` | Get one session (carries the receipt in `result`). |
| `GET` | `/autonomous/sessions/{session_id}/findings` | The run's persisted findings (stable `created_at, id` order). |
| `GET` | `/autonomous/sessions/{session_id}/artifacts` | The run's document-grade artifact references (same stable order; see the artifacts section below). |
| `POST` | `/autonomous/sessions/{session_id}/halt` | Request an external halt (R5). |

### Watches (KB-arrival triggers)

A watch fires when a file is **attached** to a watched KB
(`api/app/autonomous/watch_trigger.py::fire_watches_for_kb`, called by
`attach_file` after the attach commits). The session is owned by the
watch's `user_id`. Table `autonomous_watches` (migration `0039`;
per-trigger `max_cost_usd` added in `0045`).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/autonomous/watches` | Create a watch. |
| `GET` | `/autonomous/watches` | List the user's watches. |
| `PATCH` | `/autonomous/watches/{watch_id}` | Update a watch. |
| `DELETE` | `/autonomous/watches/{watch_id}` | Delete a watch. |

### Schedules (in-repo cron)

Schedules run on a five-field cron expression parsed by an in-repo
parser (`api/app/autonomous/cron.py` — `validate_cron_expr`,
`next_run_after`). The project deliberately did **not** take a cron
dependency (`croniter`/`apscheduler`) per the SBOM posture. Table
`autonomous_schedules` (migration `0039`; `due` index in `0042`).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/autonomous/schedules` | Create a schedule. |
| `GET` | `/autonomous/schedules` | List the user's schedules. |
| `PATCH` | `/autonomous/schedules/{schedule_id}` | Update a schedule. |
| `DELETE` | `/autonomous/schedules/{schedule_id}` | Delete a schedule. |

### Per-user memory (proposed → kept / dismissed)

The agent proposes memory rows (`state='proposed'`); the user curates
them. Table `autonomous_memory` (migration `0039`).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/autonomous/memory` | List the user's memory. |
| `POST` | `/autonomous/memory/{memory_id}/keep` | Keep a proposed memory. |
| `POST` | `/autonomous/memory/{memory_id}/dismiss` | Dismiss a proposed memory. |
| `DELETE` | `/autonomous/memory/{memory_id}` | Delete a memory. |

### Precedent board (+ promote-to-Project proposals)

Recurring document/clause patterns the agent observed, with
`observed_count`. A precedent can be *promoted* into a Project's
context — but promotion is a separate, user-authorized proposal
lifecycle, not a direct write. Tables `precedent_entries` (migration
`0039`) and `project_context_proposals` (migration `0041`).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/autonomous/precedents` | List the user's precedents. |
| `POST` | `/autonomous/precedents/{precedent_id}/dismiss` | Dismiss a precedent. |
| `POST` | `/autonomous/precedents/{precedent_id}/promote` | Open a promote-to-Project proposal. |
| `GET` | `/autonomous/project-context-proposals` | List promotion proposals. |
| `POST` | `/autonomous/project-context-proposals/{proposal_id}/accept` | Accept (write into the Project). |
| `POST` | `/autonomous/project-context-proposals/{proposal_id}/reject` | Reject. |

### Notifications (delivery output)

Durable in-app notifications are the record of truth; email is a
best-effort transport copy (a webhook channel value is reserved for a
future DE). Table `autonomous_notifications` (migration `0040`; read
index in `0043`).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/autonomous/notifications` | List the user's notifications. |
| `POST` | `/autonomous/notifications/{notification_id}/read` | Mark one read. |

---

## Document-grade artifacts (opt-in, Donna #8)

An opted-in run can persist **document-grade artifacts** — markdown
memos synthesized from its analysis — into its target knowledge base as
*real documents*: visible in the KB file list, chat/RAG-queryable
(embeddings are enqueued best-effort at emission; the lazy
embed-on-read path covers any gap), and downloadable like any upload.

**Opt-in, default off.** The `emit_artifacts` boolean on
`autonomous_schedules` / `autonomous_watches` (migration `0047`; also
on the `run-now` request body, since a manual run has no trigger row to
inherit from) is copied into `session.params` at spawn. Existing
automations see **zero** behavior or cost change: the artifact
instruction is appended to the analysis prompt only when the flag is
set, and the drafting node dispatches `emit_artifact` only when the
session's flag is truthy — even if the model emits the key unasked
(defense-in-depth; R6 additionally grants `emit_artifact` in `drafting`
only).

**Where artifacts come from.** The existing single analysis inference
call — when opted in, the structured-output JSON gains an optional
`artifacts: [{"name", "content_md"}]` list. There is no second
inference call; `emit_artifact` is a zero-cost local intent.

**The direct-write shape.** The chokepoint handler
(`guard.py::_handle_emit_artifact`) uploads the bytes to object storage
first, then writes a real `File` row + `Document` + chunks + KB attach
+ an `autonomous_artifacts` reference row — all through the normal
commit boundary (the executor commits). The PDF-only ingest pipeline is
not involved (markdown is already text); md/txt support for the general
ingest path is deferred as DE-332.

**Deletion semantics.** The `autonomous_artifacts` reference dies with
its session (`session_id` FK CASCADE); the KB document **outlives** the
session — it is the user's deliverable. A hard file-delete SET-NULLs
the reference's `file_id` while the name/size metadata survives.

**Loop/echo prevention.** The KB attach is a direct DB insert, not the
attach API — so an artifact arriving in a watched KB does **not** fire
the watch and spawn a new run. And mode-3 (`since`) retrieval excludes
artifact-referenced files, so a schedule's next tick does not re-analyze
the previous tick's memo. Query-mode retrieval and chat RAG deliberately
*keep* artifacts retrievable — that is the point of the direct-write
shape.

**Honest fallbacks.** A run with no target KB skips persistence and
emits one `info` finding saying why; a storage (MinIO) failure writes
**no** DB rows and emits one `warn` finding per failed artifact
(correlated-failure dedupe is deferred as DE-333). The delivery
notification's payload carries `artifact_count` next to
`finding_count`, and its body mentions documents only when the count is
non-zero.

**Read endpoint.** `GET /autonomous/sessions/{session_id}/artifacts`
mirrors the findings read: owner-gated (404 id-probing-safe), stable
order (`created_at ASC, id ASC` — one run's rows typically share
`created_at` because server-side `now()` is transaction-stable, so `id`
is the pagination tiebreaker; repeatable, not a guaranteed emission
sequence), limit clamped [1, 200]; `document_id` is enriched at read
time via the unique `documents.file_id` so a client can deep-link the
KB document.

**Honest scope.** Markdown/plain-text only — no PDF/DOCX rendering
(deferred), no artifact editing/versioning, and the interactive chat /
playbook-execution paths do **not** emit artifacts; this is an
autonomous-run capability.

---

## Receipts and transparency

Every expected-stop session produces a receipt
(`api/app/autonomous/receipt.py`), stored in
`autonomous_sessions.result` (JSONB). The builder is
`build_receipt`; the executor calls `build_receipt_safe`, a best-effort
wrapper that never raises (on any failure it logs and returns `None` so
a receipt-build error can neither crash the worker nor leave the
session non-terminal — the caller still persists the terminal status).

**Privacy contract.** The receipt is built **only** from audit
`details` fields, which by construction carry only counts / types /
IDs / costs / enum labels (enforced at write time by
`autonomous_audit`). The builder never pulls raw entity values or
document text from any table; it reads only safe scalar fields (IDs,
enums, costs, timestamps) off the session row. This is the same
discipline the chokepoint applies to its OTel spans — they record the
intent label and counts, never the params.

A receipt carries: top-level session scalars (`session_id`,
`trigger_kind`, `status`, `halt_state`, `current_phase`,
`cost_total_usd`, `max_cost_usd`, `cost_cap_reached`, timestamps); an
ordered `phase_transitions` list; an ordered `tool_calls` list (tool,
outcome, and `cost_usd` when present); and a `terminal_reason`.

**`terminal_reason` values** (derived from the first terminal audit row):

- `completed` — the delivery phase finished normally.
- `cost_cap_reached` — R4 latched the cost cap.
- `external_halt` — R5 honored an external halt request.
- `idle_timeout` — R5's idle watchdog reaped a stalled session.
- `None` — the session is still running (no terminal row yet).

(HONEST-STATE §5 lists the three primary stops — `completed` /
`cost_cap_reached` / `external_halt`; `idle_timeout` is the
watchdog-driven variant of the R5 halt and is surfaced the same way.)

### Web dashboard

The user-facing surface lives under
`web/src/routes/lq-ai/autonomous/` — `sessions/` (and
`sessions/[id]/` for the receipt + halt), `memory/`, `precedents/`,
`watches/`, `schedules/`, `notifications/`, and `proposals/`. The
opt-in toggle is at `web/src/routes/lq-ai/settings/autonomous/`.

A Learn visualization of the phase walk + the four brake scenarios
ships at `web/static/learn/playgrounds/autonomous-flow.html`; the four
*primitives* are not yet visualized (tracked in HONEST-STATE §11).

---

## Opt-in and the cost cap

The layer is **off by default**. The opt-in is the per-user
`User.autonomous_enabled` boolean (migration `0044`). The FastAPI
dependency `get_autonomous_enabled_user`
(`api/app/api/dependencies.py`, surfaced as `AutonomousEnabledUser`)
returns 403 unless the user has opted in; it gates the mutate endpoints
and the spawn paths. A user who has not opted in cannot create watches
or schedules and will not have sessions spawned on their behalf.

The cost cap is `max_cost_usd`:

- **Per session** — `autonomous_sessions.max_cost_usd`
  (`Numeric(10,4)`; `NULL` = no cap). R4 checks the projected total
  against it on every tool call.
- **Per trigger** — `autonomous_watches.max_cost_usd` and
  `autonomous_schedules.max_cost_usd` (both `Numeric(10,4)`, migration
  `0045`) — the cap a trigger stamps onto each session it spawns.

Inference cost is projected by `estimate_tool_cost`
(`api/app/autonomous/cost.py`), which reuses the M2-E2 rolling-average
estimator (`estimate_judge_call_cost_usd`) keyed by model name for
`run_skill` / `run_playbook`; all other intents are zero-cost for the
R4 pre-flight.

---

## Verification

Every claim above resolves to source. To verify:

- **Phase machine + graph:** `api/app/autonomous/executor.py`
  (`_build_graph`), `api/app/autonomous/nodes.py`. Phase enum:
  `api/app/schemas/autonomous.py` (`Phase`).
  `cd api && pytest tests/autonomous/test_executor_skeleton.py`
- **Real in-loop work (not a skeleton):**
  `cd api && pytest tests/autonomous/test_executor_real_work.py`
- **Chokepoint + R5→R6→R4 order:** `api/app/autonomous/guard.py`
  (`guarded_tool_call`); `ToolIntent` + `PHASE_GRANTS` in
  `api/app/autonomous/enums.py`.
  `cd api && pytest tests/autonomous/test_brakes.py tests/autonomous/test_guard_helpers.py`
- **No tool call bypasses the chokepoint:**
  `cd api && pytest tests/autonomous/test_executor_skeleton.py::test_no_tool_call_bypasses_chokepoint`
- **R4 per-trigger cap:** `api/app/autonomous/cost.py`, migration
  `0045`.
  `cd api && pytest tests/autonomous/test_r4_per_trigger_cap.py tests/autonomous/test_spawn_max_cost_usd.py`
- **R5 idle watchdog:** `api/app/workers/autonomous_worker.py`
  (`_run_idle_sweep`, `autonomous_idle_watchdog`).
  `cd api && pytest tests/autonomous/test_idle_watchdog.py`
- **Receipt + terminal_reason:** `api/app/autonomous/receipt.py`.
  `cd api && pytest tests/autonomous/test_receipt_build_safe.py tests/autonomous/test_terminal_reason_completed.py`
- **Honest gateway-error path:**
  `cd api && pytest tests/autonomous/test_executor_gateway_error.py`
- **Opt-in gate:** `api/app/api/dependencies.py`, `User.autonomous_enabled`
  (migration `0044`).
  `cd api && pytest tests/autonomous/test_optin_gate.py tests/autonomous/test_spawn_optin_guard.py`
- **Primitives (routes + tables):** `api/app/api/autonomous.py`;
  migrations `0039`–`0045` in `api/alembic/versions/`.
  `cd api && pytest tests/autonomous/test_watches.py tests/autonomous/test_schedules.py tests/autonomous/test_memory.py tests/autonomous/test_precedents.py tests/autonomous/test_notifications.py`
- **Observability (spans carry counts/types/IDs only):**
  `cd api && pytest tests/autonomous/test_autonomous_observability.py`
- **Web dashboard:** `web/src/routes/lq-ai/autonomous/`; opt-in toggle
  `web/src/routes/lq-ai/settings/autonomous/`.

---

## Known limitations and honest caveats

### Ethics review is a light v1

The `ethics_review` phase does not run a dedicated ethics LLM gate. It
summarizes the `privilege_concerns` / `scope_concerns` that the
upstream analysis/drafting nodes already surfaced (via structured
output) into a single `emit_finding`, or emits one "no concerns
flagged" info finding when both are empty. The node's own docstring
names a dedicated ethics LLM gate as a future enhancement. The phase is
a real, audited gate in the graph — but its v1 logic is summarization,
not independent judgment.

### Gateway errors produce honest findings, not fabricated output

A gateway transport/parse error during analysis does not crash the
session and does not produce invented analysis. It yields one
explanatory `warn` finding and a normal `completed` receipt (the call
is still charged its R4 estimate so the budget can't be gamed, but its
audit outcome is recorded as `gateway_error`). The user sees that the
analysis failed at the gateway, not a confident-looking wrong result.

### The Contract-Repository auto-relationship graph is not built

PRD §3.16's Contract-Repository auto-relationship detection (a separate
M4-roadmap capability) is **not** implemented — there is no
`contract_relationships` table in `api/alembic/versions/`. It is
tracked as deferred-M4+ in HONEST-STATE §6.

### Receipts cover expected stops, not `failed` sessions

`SessionHalted` and `CostCapReached` (expected stops → `halted`) get a
receipt. `ToolNotGranted` and other in-graph exceptions (→ `failed`)
intentionally do not — a failed-session receipt is a separate, deferred
decision.

---

## References

- PRD §3 (capability specifications) — Autonomous Layer; §3.16
  (Contract Repository, deferred)
- [docs/HONEST-STATE.md §5](HONEST-STATE.md) — shipped-vs-deferred
  catalog with verification paths
- [docs/M4-IMPLEMENTATION-PLAN.md](M4-IMPLEMENTATION-PLAN.md) — the M4
  task breakdown
- [docs/db-schema.md](db-schema.md) — `autonomous_sessions`,
  `autonomous_watches`, `autonomous_schedules`, `autonomous_memory`,
  `precedent_entries`, `project_context_proposals`,
  `autonomous_notifications`, `autonomous_findings`,
  `autonomous_artifacts`
- [docs/observability.md](observability.md) — autonomous spans
