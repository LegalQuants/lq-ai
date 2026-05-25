# Building aligned agentic flows in LQ.AI (M4 / LQVern contributor guide)

> **Audience:** anyone implementing an autonomous flow on the M4 Autonomous Layer (`api/app/autonomous/`). Read [ADR 0013](../adr/0013-autonomous-layer-design-influences.md) and [PRD §3.10](../PRD.md#310-autonomous-layer-m4) first — this guide is the *how*, those are the *what* and *why*.
>
> **The one rule this guide exists to enforce:** an autonomous agent acts without a human watching each step, so the human must be able to read, afterward, **exactly what it did and why** — and the agent must be unable to overspend, run away, or use a tool it wasn't granted in its current phase. Transparency and the brakes are not features you add at the end; they are the shape of the loop. Code that omits them is not done.

---

## 1. Why autonomy raises the bar

LQ.AI's founding principle (PRD §1.3) is transparency: every artifact that shapes the user's experience is visible work product. For chat, that's the Skill Inspector + receipts. For an **autonomous** flow, the model takes actions the user did not individually approve — so the transparency obligation moves from "you can read the prompt" to "you can audit the **behavior**." Concretely, three surfaces are mandatory for every flow:

1. **OTel domain spans** — so an operator can trace what ran, how long, what it cost, and whether the brakes fired.
2. **A closed-enum audit trail** — so there is a durable, queryable record of every consequential action.
3. **A human-readable per-session receipt** — so the *user* (not just the operator) can read "what the agent did and why."

Plus the three brakes from the boundary-register catalog (PRD §1.8, [DE-293](../PRD.md#de-293)): **R4 cost cap**, **R5 halt switch + idle timeout**, **R6 phase-gated tool grants** — checked **before every tool call**.

---

## 2. The shape of an aligned flow

An autonomous flow is a **LangGraph state machine** (mirroring `api/app/playbooks/executor.py`) running on the **arq-worker**, with one `autonomous_session` row as its durable state. Every tool call passes through a single chokepoint — `guarded_tool_call` — that enforces all three brakes, emits the span, and writes the audit row. **There is exactly one chokepoint on purpose:** a contributor adding a new tool gets the brakes + telemetry for free and cannot accidentally route around them.

```
arq schedule/watch trigger
        │
        ▼
 create autonomous_session(user_id, max_cost_usd, phase="intake", halt_state="running")
        │
        ▼
 LangGraph loop ── for each step ──▶ guarded_tool_call(session, tool, intent, params)
        │                                   │  1. read halt_state            (R5)
        │                                   │  2. check phase grants tool    (R6)
        │                                   │  3. project cost vs remaining  (R4)
        │                                   │  4. open OTel span + audit row
        │                                   │  5. run tool (inference via gateway, retrieval, etc.)
        │                                   │  6. record cost, outcome; close span + audit row
        │                                   ▼
        │                            (any check fails → halt cleanly, write partial result + reason)
        ▼
 emit per-session receipt; notify; persist session terminal state
```

The phases are a closed enum (`intake → analysis → drafting → ethics_review → delivery`); transitions are explicit and audited. Tool grants are declared **per phase**, so a tool available at `intake` (e.g. broad retrieval) can be stripped by `ethics_review` (ADR 0013 D3, R6).

---

## 3. The mandatory contract — pseudo-code

> Illustrative. The authoritative patterns to copy are `api/app/playbooks/executor.py` + `nodes.py` + `state.py` (LangGraph + Pydantic-typed state), `api/app/observability_helpers.py` (`get_tracer` / `record_attributes` / `@traced`), the `audit_log` write pattern in `api/app/api/*.py`, and the M2-E2 cost estimator in `api/app/citation/cost.py`. Do not invent new helpers where these exist.

```python
# api/app/autonomous/executor.py  (illustrative)
from app.observability_helpers import get_tracer, record_attributes

tracer = get_tracer(__name__)

# Closed enum — the ONLY tools a flow may call. Adding a tool = adding an enum member.
class ToolIntent(StrEnum):
    retrieve_chunks = "retrieve_chunks"
    run_skill = "run_skill"
    run_playbook = "run_playbook"
    propose_memory = "propose_memory"
    propose_precedent = "propose_precedent"   # M4-B2: write/increment precedent_entries
    emit_finding = "emit_finding"
    notify = "notify"

# Per-phase grants: phase -> allowed intents (R6).
# M4-B2 (Decision B2-b): propose_precedent granted at BOTH analysis and drafting
# — patterns are observed while reading docs (analysis) AND recognized as
# recurring during synthesis (drafting).
PHASE_GRANTS: dict[Phase, set[ToolIntent]] = {
    Phase.intake:        {ToolIntent.retrieve_chunks},
    Phase.analysis:      {ToolIntent.retrieve_chunks, ToolIntent.run_skill, ToolIntent.run_playbook, ToolIntent.propose_precedent},
    Phase.drafting:      {ToolIntent.run_skill, ToolIntent.emit_finding, ToolIntent.propose_memory, ToolIntent.propose_precedent},
    Phase.ethics_review: {ToolIntent.emit_finding},          # retrieval/skills stripped here
    Phase.delivery:      {ToolIntent.notify},
}

async def guarded_tool_call(session: AutonomousSession, intent: ToolIntent,
                            params: ToolParams, db, gateway) -> ToolResult:
    """The single chokepoint. Every tool call goes through here."""
    with tracer.start_as_current_span("autonomous.tool_call") as span:
        record_attributes(
            span,
            # COUNTS + TYPES ONLY — never raw entity values, never document text.
            **{
                "autonomous.session_id": str(session.id),
                "autonomous.phase": session.current_phase,
                "autonomous.tool": intent,                 # the intent, not its payload
                "autonomous.halt_state": session.halt_state,
            },
        )

        # R5 temporal — external halt switch, checked BEFORE the call.
        await db.refresh(session, ["halt_state"])
        if session.halt_state == HaltState.halt_requested:
            session.halt_state = HaltState.halted
            await _audit(db, session, "autonomous_session.halted", reason="external_halt")
            raise SessionHalted(reason="external_halt")

        # R6 contextual — is this tool granted in the current phase?
        if intent not in PHASE_GRANTS[session.current_phase]:
            await _audit(db, session, "autonomous_session.tool_call",
                         tool=intent, outcome="tool_not_granted")
            record_attributes(span, **{"autonomous.outcome": "tool_not_granted"})
            raise ToolNotGranted(intent=intent, phase=session.current_phase)

        # R4 economic — would this call exceed the cap? (M2-E2 estimator)
        projected = session.cost_total_usd + estimate_tool_cost(intent, params)
        if session.max_cost_usd is not None and projected > session.max_cost_usd:
            session.cost_cap_reached = True
            session.halt_state = HaltState.halted
            await _audit(db, session, "autonomous_session.cost_cap_reached",
                         projected_usd=float(projected))
            record_attributes(span, **{"autonomous.outcome": "cost_cap_reached"})
            raise CostCapReached(projected_usd=projected)

        # --- run the tool ---  (inference goes through the gateway → anonymization +
        #     citation verification apply automatically, same as playbooks)
        await _audit(db, session, "autonomous_session.tool_call", tool=intent, outcome="started")
        result = await _dispatch(intent, params, gateway=gateway, db=db, session=session)

        session.cost_total_usd += result.cost_usd
        record_attributes(span, **{
            "autonomous.cost_usd": result.cost_usd,        # the real post-call cost
            "autonomous.outcome": "success",
        })
        await _audit(db, session, "autonomous_session.tool_call",
                     tool=intent, outcome="success", cost_usd=float(result.cost_usd))
        return result
```

```python
async def run_phase_transition(session, to_phase: Phase, db) -> None:
    session.current_phase = to_phase
    await _audit(db, session, "autonomous_session.phase_transition", to_phase=to_phase)
    # idle-halt (R5): a watchdog arq job auto-transitions sessions idle past
    # idle_halt_minutes (default 5) to paused, then halted.
```

The audit action strings are a **closed set** — `autonomous_session.{started, phase_transition, tool_call, halted, cost_cap_reached, completed}`. Don't add free-form actions; extend the enum in one place if you genuinely need a new one.

---

## 4. How to leverage the existing backend (don't rebuild)

| You need to… | Use | Source of truth |
|---|---|---|
| Run the flow on a durable queue / on a cron | the **arq-worker** (the same worker playbooks/ingest run on) | `api/app/workers/`, the `arq` redis settings; cron via arq's `cron_jobs` |
| Call a model | the **gateway client** (POST `/v1/chat/completions`) — inference through the gateway gets **anonymization + tier enforcement + cost accounting for free** | the playbook executor's gateway call path |
| Verify a quote / ground a finding | the **Citation Engine** | `api/app/citation/verification.py` |
| Retrieve from a KB | **pgvector + FTS hybrid retrieval** | `api/app/knowledge/` |
| Estimate a call's cost (for R4) | the **M2-E2 rolling-average estimator** | `api/app/citation/cost.py` |
| Emit telemetry | `get_tracer` / `record_attributes` / `@traced` (**no-op when OTel disabled**) | `api/app/observability_helpers.py` |
| Write an audit row | the `audit_log` table + the project's audit-write helper | the `audit_action(...)` pattern in `api/app/api/*.py` |
| Model multi-step state | **LangGraph + Pydantic-typed state** (typed transitions are LQ.AI's R3 posture) | `api/app/playbooks/{executor,nodes,state}.py` |

**Inference always goes through the gateway.** Never call a provider SDK directly from `api/`. Routing through the gateway is what gives an autonomous flow the same anonymization, tier-floor enforcement, and cost accounting the chat path has — and it's why the autonomous executor lives in `api/` (the orchestration) while the gateway stays the key-holding boundary.

---

## 5. OpenTelemetry rules for new autonomous code

The F-phase OTel work (PRD §5.4, `docs/observability.md`) is the standard. New autonomous code MUST:

- **Use the helpers, never raw OTel.** `get_tracer(__name__)` + `record_attributes(span, **attrs)`. They no-op when OTel is disabled, so they're always safe to call.
- **Span names:** `autonomous.session` (one per run, the root of the flow's subtree) and `autonomous.tool_call` (one per guarded call). Per-skill/per-playbook work invoked by a tool re-uses the existing `skill.execute` / `playbook.execute` spans — don't duplicate them.
- **Attribute hygiene — the hard rule:** attributes carry **counts, types, IDs, costs, outcomes, enum labels** — **never raw entity values, document text, prompt bodies, or model responses.** This extends the M2 anonymization-span guarantee (enforced for the gateway by `gateway/tests/test_anonymization_observability.py`); the autonomous layer needs the equivalent guard test. If you're tempted to put the *content* of a finding in a span attribute, put its `finding_id` and `severity` instead.
- **The brakes are observable:** `cost_usd`, `halt_state`, `phase`, and `outcome` (`success` / `tool_not_granted` / `cost_cap_reached` / `external_halt`) are span attributes so an operator can answer "did the brakes fire, and which one?" from the trace alone.

---

## 6. Testing expectations (the acceptance bar, from DE-293)

Integration tests must exercise each brake — these are the acceptance criteria, not optional:

- **R4:** a session whose projected cost exceeds its `max_cost_usd` halts with `cost_cap_reached=True` and preserves the partial result.
- **R5:** a session that receives an external halt (`POST …/halt`) stops on its **next** tool call; an idle session auto-pauses past `idle_halt_minutes`.
- **R6:** a session in `ethics_review` cannot invoke a tool granted only at `intake` (raises `ToolNotGranted`, audited).
- **Privacy guard:** an autonomous-span test (mirror `test_anonymization_observability.py`) asserts no raw entity value ever lands in an `autonomous.*` attribute.
- **Isolation:** user A's session can never read user B's memory/precedents (per-user hard isolation, §3.10 NFR).

Standard project gates apply (CLAUDE.md): TDD, `ruff` + `mypy` (api standard mode), the new endpoints get unit + integration + OpenAPI-conformance tests, and the repo-root `tests/` cross-cutting suite if you add a privacy-guard contract test there.

---

## 7. "Is my agentic flow aligned?" — checklist

Before you open the PR:

- [ ] Every tool call goes through the single `guarded_tool_call` chokepoint (no tool bypasses it).
- [ ] R4 cost cap, R5 halt-state read, R6 phase-grant check all happen **before** the tool runs.
- [ ] `autonomous.session` + `autonomous.tool_call` spans emitted via the helpers; attributes are counts/types/IDs/costs only.
- [ ] Closed-enum audit rows written for started / phase_transition / tool_call / halted / cost_cap_reached / completed.
- [ ] A per-session receipt renders "what the agent did and why" (every tool call, inputs seen, cost, phase, gates) — readable by the **user**, not just the operator.
- [ ] Inference goes through the gateway (anonymization + tier + cost), never a direct provider call.
- [ ] Per-user isolation holds; memory writes follow *system-proposes, user-owns* (no silent writes).
- [ ] The R4/R5/R6 + privacy-guard + isolation tests pass.
- [ ] The Learn-tab "Autonomous flow" visualization (see the Learn-tab plan) reflects any new phase or tool so the public explainer stays honest.

If every box is checked, the flow is aligned with LQ.AI's transparent, auditable posture — which is the whole point of doing autonomy this way.

---

*Companion docs: [ADR 0013](../adr/0013-autonomous-layer-design-influences.md) (design + decisions), [PRD §3.10](../PRD.md#310-autonomous-layer-m4) (the capability spec), [DE-293](../PRD.md#de-293) (the brakes spec), [`docs/security/boundary-registers.md`](../security/boundary-registers.md) (R4/R5/R6 definitions), [`docs/observability.md`](../observability.md) (the OTel operator guide). The implementation plan + Learn-tab viz spec follow via the writing-plans step.*
