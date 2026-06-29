# WS-D PR1 — governed agentic loop + matter intake (design)

**Date:** 2026-06-28
**Milestone:** Fiduciary-grade agentic legal work — Phase 2, WS-D (agentic legal-matter sessions).
**ADR:** [0020](../../adr/0020-governed-agentic-legal-matter-sessions.md) — this spec implements its PR1 (D1 the governed loop, D2 agency confined to analysis, D3 matter intake, D4 step cap, D5 transparent plan, D7 reuse the rails). Resolves the PR1 §Open-questions.
**Builds on:** the autonomous layer (`api/app/autonomous/`) — `guarded_tool_call`, the closed `ToolIntent` set, `PHASE_GRANTS`, R4/R5/R6, the LangGraph `intake → analysis → drafting → ethics_review → delivery` backbone, the `audit_log` + receipt.
**Security-gated:** yes — `api/app/autonomous/**` is the governance chokepoint. Security/maintainer merges; mirror `origin/main → tucuxi` after.
**Migration:** likely none (the loop runs in-node; `state["query"]` already exists) — **but verify** the `audit_log` (and any tool-intent-bearing column) does not persist `ToolIntent` under a DB CHECK constraint; if it does, adding `plan` needs a migration to extend that CHECK. The plan's Task 1 must check this first. **If a migration is needed it is `0063`; otherwise next migration stays `0063`. Next DE = DE-368.**

---

## 1. What this delivers

Today's autonomous `analysis` phase is a **single `run_skill` LLM call**. PR1 turns it into a **governed `plan → act → observe → replan` loop** for **matter-scoped** sessions: the planner picks the next `ToolIntent` from `PHASE_GRANTS[analysis]`, each step runs through the existing `guarded_tool_call` (R5→R6→R4 unchanged), observations fold back compactly, and a final synthesis produces the structured findings the rest of the graph already consumes. A plain-language matter (the `params["query"]` seam, currently unread) becomes the planner's goal.

PR1 produces the session's **existing** outputs — `emit_finding` / `emit_artifact` / `propose_precedent` — over an *adaptively planned* research arc. **No WS-A ledger / WS-B gate** (that is PR2, ADR 0020 D6).

### In scope
- A new `ToolIntent.plan` (closed-set extension) + `PHASE_GRANTS[analysis]` grant.
- The planner prompt + parser (next-intent + args + rationale, or done).
- The `while` loop inside `analysis_node` (no LangGraph change), step-capped, every step through `guarded_tool_call`.
- A pure per-intent observation `summarize(...)` formatter (compact, P3-clean).
- The final-synthesis `run_skill` call that preserves the `analysis_content` → `drafting.parse_structured_output` contract.
- Receipt/audit surfacing of the plan trace + cap-halt reason.

### Out of scope (deferred)
- **WS-A ledger / WS-B gate integration** → WS-D PR2.
- **A WS-D session UI** → later PR.
- **The WS-E source registry** the planner reasons over → WS-E.
- **An LLM-structured matter-intake step** (decompose the matter into sub-questions before the loop) — the planner does this adaptively; revisit only if needed.
- **Looping in intake/drafting** — ADR 0020 D2 keeps the backbone scripted; only analysis loops in PR1.
- **DE-344 metered-source cost** — the loop is bounded by R4's inference-cost estimate + the step cap today; metered external-tool cost lands in WS-E.

---

## 2. The backward-compat gate (load-bearing)

The planner loop engages **only when `state["query"]` is non-empty** — a matter-scoped session. Sessions with no query (today's cron / watch / schedule triggers) take the **unchanged** single-`run_skill` path. PR1 is **strictly additive**: every existing autonomous session is byte-identical (same intents, same audit rows, same outputs). The branch in `analysis_node`:

```
if not (state.get("query") or "").strip():
    return <today's single-call analysis result, unchanged>
# else: run the governed planner loop (§3)
```

This is the invariant the tests pin: a query-less session's audit trail and outputs do not change.

---

## 3. The governed loop

In `analysis_node` (the phase is already transitioned to `analysis`; `PHASE_GRANTS[analysis]` applies to every step):

```
goal = state["query"]
observations: list[str] = []          # compact summaries, oldest→newest
max_steps = int(session.params.get("max_analysis_steps", DEFAULT_MAX_ANALYSIS_STEPS))
steps = 0
halt_reason = None

while steps < max_steps:
    decision = await guarded_tool_call(session, ToolIntent.plan,
                  {"goal": goal, "observations": observations,
                   "allowlist": _planner_allowlist(), "model": model}, db, gateway)
    plan = parse_planner_decision(decision.data)        # parse-or-stop
    if plan is None or plan.done:
        halt_reason = "planner_done" if (plan and plan.done) else "planner_unparseable"
        break
    if plan.next_intent not in _planner_allowlist():     # defense-in-depth (R6 also guards)
        halt_reason = "planner_out_of_set"
        break
    result = await guarded_tool_call(session, plan.next_intent, plan.args, db, gateway)
    observations.append(summarize_observation(plan.next_intent, plan.rationale, result))
    steps += 1
else:
    halt_reason = "step_cap"

# Final synthesis — always runs; preserves the drafting contract (§4).
synth = await guarded_tool_call(session, ToolIntent.run_skill,
            {"model": model, "messages": assemble_synthesis_messages(session, goal, observations, db),
             "anonymize": True}, db, gateway)

return {
    "current_phase": str(Phase.analysis),
    "analysis_content": (synth.data or {}).get("content"),
    "analysis_outcome": synth.outcome,
    "analysis_plan_trace": _plan_trace(observations, steps, halt_reason),   # for the receipt (D5)
}
```

- **`_planner_allowlist()`** = `PHASE_GRANTS[Phase.analysis]` minus `plan` itself and minus the emit/side-effect intents the planner shouldn't drive in the research arc (`propose_precedent` stays an analysis grant but is not a planner action in PR1 — the synthesis/drafting path emits). The exact set is fixed in the plan; the research/observe intents are `retrieve_chunks`, `retrieve_caselaw`, `call_mcp_tool`, plus `run_skill` if the planner wants an interim analysis pass.
- **Every step is a `guarded_tool_call`** — R5 (halt), R6 (phase grant), R4 (budget) fire per step; `session.cost_total_usd` accrues in-place, so R4 throttles a runaway loop **and** the step cap bounds iteration. No new brake machinery (ADR 0020 D4).
- **Args are model-generated, handler-validated.** The planner emits `args` for the chosen intent (e.g. a `retrieve_caselaw` query); the intent's existing handler validates them (the closed-set boundary, ADR 0015). A malformed/oversized arg fails in the handler as a non-fatal tool outcome, summarized as a failed observation — it never escapes the governed path.

## 4. The synthesis contract (load-bearing)

`drafting` reads `analysis_content` and calls `parse_structured_output` (expects the fenced-JSON `findings/…` shape). PR1 **preserves this**: regardless of how the loop terminates (`planner_done`, `step_cap`, `planner_unparseable`, `planner_out_of_set`), a **final `run_skill` synthesis call** turns the goal + accumulated observations into that structured-findings JSON, which becomes `analysis_content`. A cap-halt therefore yields a **partial-but-honest** structured result, not a fabricated-complete one. `assemble_synthesis_messages` reuses `assemble_analysis_messages`'s skill/playbook system prompt + structured-output instruction, with the observations rendered as the user content instead of (or alongside) the baseline chunks.

## 5. New components

| Component | File | Responsibility |
|---|---|---|
| `ToolIntent.plan` | `api/app/autonomous/enums.py` (+ `schemas/autonomous.py` enum + CHECK if persisted in audit) | closed-set planner intent; granted in `PHASE_GRANTS[analysis]` |
| planner dispatch | `api/app/autonomous/guard.py` (`_dispatch`) | a `plan` handler: build planner messages → gateway inference → return `ToolResult(data={"content": ...})`; cost via R4 like `run_skill` |
| planner prompt + parser | `api/app/autonomous/planner.py` (new) | `build_planner_messages(goal, observations, allowlist)`, `parse_planner_decision(data) -> PlannerDecision \| None` (next_intent ∈ allowlist + args + rationale, or done; parse-or-None) |
| observation summarizer | `api/app/autonomous/planner.py` | `summarize_observation(intent, rationale, result) -> str` — compact, P3-clean (counts/ids/case-names/short snippets; never full opinion text) |
| synthesis messages | `api/app/autonomous/prompts.py` | `assemble_synthesis_messages(session, goal, observations, db)` reusing the analysis system prompt + structured-output instruction |
| the loop | `api/app/autonomous/nodes.py` (`make_analysis_node`) | the §3 loop; the §2 backward-compat gate; the plan trace in the return dict |
| step-cap constant | `api/app/config.py` or `enums.py` | `DEFAULT_MAX_ANALYSIS_STEPS` (≈6), `params["max_analysis_steps"]` override |
| receipt surfacing | `api/app/autonomous/receipt.py` | include the plan trace (step count, intents, rationales, halt reason) — counts/types only (P3) |

## 6. Data flow

```
matter session (params["query"] set; project-scoped)
  └─ executor → state["query"]                                  [exists]
  └─ intake (baseline retrieve_chunks)                          [unchanged]
  └─ ANALYSIS node:
       ├─ no query?  → single run_skill (today's path)          [§2 additive]
       └─ query?     → planner loop:                            [§3]
            plan(guarded) → act(guarded) → summarize → replan   (≤ max_steps, R4-bounded)
            → final run_skill synthesis → analysis_content      [§4 preserves contract]
  └─ drafting parse_structured_output(analysis_content)         [unchanged]
  └─ ethics_review → delivery                                   [unchanged, deterministic]
  └─ receipt: + plan trace (intents/rationales/steps/halt)      [D5]
```

## 7. Error handling & invariants
- **Strictly additive:** query-less sessions unchanged (§2). The graph backbone, ethics_review, and delivery are untouched (ADR 0020 D2).
- **Every loop step governed:** no tool call bypasses `guarded_tool_call`; R4/R5/R6 fire per step. A mid-loop `SessionHalted` / `CostCapReached` propagates exactly as today (the executor's `except AutonomousBrake` handles it; a partial plan trace is still on the session).
- **Parse-or-stop:** an unparseable / out-of-set planner decision stops the loop conservatively (no execution of an invalid intent) and proceeds to synthesis — never raises, never fabricates.
- **Bounded:** `max_steps` + R4 `$5`. The loop cannot run unbounded.
- **Transparent:** every plan decision (intent + rationale) is audited (the `plan` intent's `guarded_tool_call` rows) + in the receipt (D5).
- **P3:** observations + the plan trace hold counts/ids/case-names/short snippets — never full opinion/chunk payloads.

## 8. Testing
- **Backward-compat (the load-bearing test):** a query-less session produces byte-identical audit rows + outputs to today (single `run_skill`, no `plan` intent emitted).
- **Loop happy path:** a matter session where a stub planner returns e.g. `retrieve_caselaw` then `done` → asserts the act ran through `guarded_tool_call`, the observation was summarized, the final synthesis produced `analysis_content`, and the plan trace is in the return/receipt.
- **Step cap:** a stub planner that never says done → loop stops at `max_steps`, `halt_reason="step_cap"`, synthesis still runs (partial result).
- **Parse-or-stop:** planner returns malformed / out-of-set intent → loop stops (`planner_unparseable` / `planner_out_of_set`), no invalid intent dispatched, synthesis runs.
- **R4 throttle:** a low `max_cost_usd` → the loop halts via `CostCapReached` mid-iteration (existing brake), partial trace recorded.
- **Planner intent + grants:** `plan` ∈ `PHASE_GRANTS[analysis]`; `plan` dispatched outside analysis → `ToolNotGranted` (R6).
- **Observation summarizer (unit):** each intent's result → compact P3-clean string (no full payloads).
- **CI gate (twice-burned LESSON):** `ruff check api scripts` + `ruff format --check api scripts` + `ruff check gateway` + formats from **repo root**; `mypy app` whole-app; both full suites.

## 9. Decisions log
- **Planner intent:** a dedicated `ToolIntent.plan` (closed-set extension), not reused `run_skill` — the planner decision is audited distinctly (ADR 0020 D5).
- **Observations:** compact structured summaries fed back to the planner; full payloads only to the final synthesis (bounded cost; P3).
- **Loop topology:** a `while` inside `analysis_node` — no LangGraph change (the backbone stays scripted, ADR 0020 D2).
- **Backward-compat:** the loop engages only for `state["query"]` sessions; query-less sessions unchanged.
- **Synthesis contract:** a final `run_skill` synthesis always produces the structured `analysis_content` `drafting` expects, even on a cap-halt (partial-but-honest).
- **Matter intake:** deterministic pass-through (`query` → planner goal); no separate intake-LLM step; matter = project.
- **Step cap:** `DEFAULT_MAX_ANALYSIS_STEPS ≈ 6`, `params["max_analysis_steps"]` override; plus R4. No new brake machinery.
- **No migration; no ledger/gate** (PR2).
