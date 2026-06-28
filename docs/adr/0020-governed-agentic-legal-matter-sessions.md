# ADR 0020 — Governed agentic legal-matter sessions (WS-D)

**Status:** Proposed (2026-06-28) — awaiting maintainer acceptance. Implementation PRs (WS-D PR1+) carry **security review** per CODEOWNERS (the autonomous governance chokepoint; the citation/audit/ledger surface in PR2).
**Date:** 2026-06-28
**Owner:** Fiduciary-grade agentic legal work milestone — Phase 2 (WS-D), feature branch `docs/adr-0020-agentic-matter-sessions`
**Supersedes / relates to:** [ADR 0013](0013-project-context-and-memory.md) (project context is the only thing the autonomous layer may write back), [ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md) (where external retrieval egresses), [ADR 0015](0015-governed-tool-calling-model.md) (the closed-set governed tool-calling model this ADR builds the loop on), [ADR 0016](0016-transparency-and-governance-invariants.md) (P3 no-raw-payload, P6 one governance path), [ADR 0018](0018-citation-ledger-and-fiduciary-grade-output.md) (the WS-A ledger + WS-B fiduciary gate this session produces in PR2), and the [fiduciary-grade mini-PRD](../proposals/fiduciary-grade-agentic-legal-work.md) WS-D.

## Context

WS-D is the milestone's headline user capability: *"describe a matter in plain language and have LQ.AI pursue the right inquiry."* A lawyer states a matter — "Does our Delaware NDA's assignment clause survive a change-of-control? Find controlling authority." — and LQ.AI runs a **matter-scoped agentic session** that plans, retrieves authoritative content, adapts as it learns, and produces a work product (WS-B) backed by a one-click-traceable citation ledger (WS-A).

A codebase verification pass (2026-06-28) established what exists and what is net-new:

- **Reusable — the governance is solid.** The autonomous layer (`api/app/autonomous/`) already has the `guarded_tool_call` chokepoint, the **closed** `ToolIntent` set, `PHASE_GRANTS` (per-phase allowlists), the R5→R6→R4 brakes (temporal halt / phase-grant / economic), a per-session `max_cost_usd` cap (default **$5**, always armed), the idle watchdog, the `audit_log` + receipt model, and the `emit_finding` / `emit_artifact` / `propose_precedent` output handlers. Sessions are project-scoped, spawned via cron / watch / `run-now`, and run as an arq job over a LangGraph.
- **Net-new — there is no agency.** The current LangGraph is **scripted**: a fixed `intake → analysis → drafting → ethics_review → delivery` edge sequence whose entire "planning" is **a single LLM call** in the analysis node emitting structured output. There is **no plan→act→observe→replan loop**, no dynamic next-tool selection, no mid-workflow adaptation. There is **no plain-language matter intake** — a `query` field exists in session state but **no node reads it** (a reserved seam). And the autonomous loop has **zero WS-A/WS-B hookup**: it never writes the citation ledger or runs the fiduciary gate (those are chat-path-only today).

The central tension WS-D must resolve: an *agentic* session that "adapts mid-workflow" against ADR 0015's *closed-set, governed, deterministic* posture. The wrong move is to reach for open function-calling. This ADR pins how to get genuine adaptation **inside** the existing governance, what stays deterministic, how a matter enters the system, how the session is bounded and made transparent, and how it produces a fiduciary-grade work product — phased so the agentic loop lands before the ledger/gate integration.

It does **not** specify endpoint shapes, the planner prompt, schemas, or step-cap values — those land in the per-PR specs/plans after acceptance.

## Decision drivers

1. **Governance is non-negotiable (ADR 0015).** Adaptation must never become open function-calling. Every action the session takes must remain a closed-set `ToolIntent`, brake-checked at the one chokepoint. The model may choose *which* governed tool and *when*; it may never invent a tool or escape the allowlist.
2. **Safety-critical phases must be guaranteed, not modeled.** In a fiduciary context, a model must not be able to decide it is "done" and skip ethics review, or self-deliver an un-gated work product. The phase backbone that enforces "ethics review always runs; delivery is always last" must stay deterministic.
3. **Transparency is the product (PRD §1.3).** An agentic session's *plan and reasoning* are visible work product, not a hidden chain-of-thought. Every planner decision — the chosen intent and *why* — must be auditable and surfaced.
4. **Reuse the substrate; do not fork it (ADR 0016 P6).** WS-D reuses `guarded_tool_call`, `PHASE_GRANTS`, the brakes, the audit model, and (in PR2) the chat-path citation cascade + ledger + gate. It adds a planner loop and an intake, not a parallel governance or a parallel ledger.
5. **Bounded by construction.** An agentic loop fans out tool calls; unbounded, it burns budget and latency. The existing R4 economic brake bounds spend; a new **step cap** bounds iteration. No new *brake machinery* — the strategy commits WS-D to reusing R4/R5/R6.
6. **Conservative posture (PRD §1).** A matter the session cannot pursue within its grants/budget halts honestly with a partial, traceable result — never a fabricated or over-claimed answer. The fiduciary gate (PR2) is what lets a work product be *labeled* fiduciary-grade.

## Decisions

### D1 — A governed agentic loop, inside the closed-set chokepoint (the binding model)

WS-D adds a `plan → act → observe → replan` loop. Each iteration: a **planner** (an LLM call) proposes the **next `ToolIntent`** to run **and a one-line rationale**, selecting only from the **current phase's `PHASE_GRANTS` allowlist**; the chosen intent is dispatched through the **existing `guarded_tool_call`** (R5→R6→R4, unchanged); the result is appended to the planner's observation context; the planner either proposes a next step or signals the phase is complete. The planner's output is a **closed enum choice + rationale**, parsed with the same parse-or-halt discipline the citation judges use — it is **not** open function-calling and the model **cannot** emit a tool outside the allowlist (an out-of-set proposal is rejected, not executed; ADR 0015). This is the entire net-new "agency": adaptive *selection and sequencing* over a fixed, governed tool vocabulary.

### D2 — Scripted phase backbone; agency confined to the analysis phase

The `intake → analysis → drafting → ethics_review → delivery` **phase backbone stays deterministic** (the LangGraph edge sequence is unchanged). The agentic loop (D1) operates **within the `analysis` phase** — where the planner adapts the *research*: which sources to consult, which follow-ups a finding warrants, when enough authority has been gathered. The planner signals "analysis complete"; the deterministic graph then advances `analysis → drafting → ethics_review → delivery`. `ethics_review` and `delivery` **remain guaranteed** — a session can **never** skip ethics review or self-deliver. This bounds the agency to the research arc (where adaptation has real value) while keeping every safety-critical transition outside the model's control. `intake` and `drafting` may run a bounded loop in a later iteration if warranted, but the backbone and the guarantees do not move.

### D3 — Plain-language matter intake; "matter" = project

A session gains a **plain-language matter description** as input. The reserved `query` seam in session state is made real: the `intake` phase consumes the description and produces the planner's **goal** (the objective the analysis loop pursues), recorded on the session. **"Matter" maps to the existing project** (`project_id`) — there is **no new `Matter` model**; a matter-scoped session is a project-scoped session with a stated objective. The intake step is where the plain-language ask becomes a structured goal the governed loop can plan against; it does not itself retrieve or egress.

### D4 — Bounded by a step cap + the existing R4 budget; no new brake machinery

The loop is bounded by **(a)** the existing R4 economic brake (`max_cost_usd`, default $5, every `guarded_tool_call` pre-checks it) and **(b)** a new **per-phase step cap** — the only new bound this ADR introduces. Reaching the step cap halts the phase honestly (it advances to drafting/ethics with what was gathered, or halts the session) — it does not fabricate completion. **No new brake class** is added (R5/R6/R4 are reused verbatim, per the mini-PRD). The exact cap value and whether it is operator-tunable are fixed in the PR1 plan.

### D5 — The plan is transparent, auditable work product

Every planner decision is recorded: the **chosen `ToolIntent`, the rationale, the phase, the step index**, and the tool's outcome — through the **existing `audit_log`** (each `guarded_tool_call` already writes started/outcome rows; WS-D adds the planner rationale alongside). The session **receipt** surfaces the full plan-and-act trace (counts, types, intents, rationales, costs — never raw payloads, ADR 0016 P3). A reviewer can read *what the session decided to do and why* at every step. This is the founding transparency principle (PRD §1.3) applied to agency: no hidden chain-of-thought drives a legal work product.

### D6 — Phased build: agentic loop first, fiduciary integration second

This ADR pins the full methodology; the build phases it (mirroring ADR 0019's graph-first/judge-second).

- **WS-D PR1 — the governed agentic loop + matter intake.** The planner loop (D1) within the analysis phase (D2), plain-language intake (D3), the step cap (D4), and the transparent plan trace (D5). It produces the session's existing outputs — `emit_finding` / `emit_artifact` / `propose_precedent` — over an *adaptively planned* multi-step research arc. **No ledger/gate yet** — the work product is the findings/artifacts, honestly un-gated.
- **WS-D PR2 — WS-A ledger + WS-B fiduciary gate integration.** Route the session's retrieved authoritative sources (and the drafted work product) through the **existing chat-path citation cascade → `assemble_ledger_entries` → `compute_and_record_gate`** (ADR 0018), so a session produces a matter-scoped ledger and a fiduciary-grade verdict. **Reuse, do not fork** (ADR 0016 P6): the autonomous session writes the *same* ledger/gate rows the chat path does. The work product is labeled **fiduciary-grade only when every citation is ledger-backed** (ADR 0018 D3).

Subsequent PRs (a WS-D session UI; the WS-E source registry the planner reasons over) follow, each in its own spec/plan.

### D7 — The session reuses, and never bypasses, the existing governance and output rails

The loop dispatches **only** through `guarded_tool_call`; it adds no second tool path. Output stays on the existing handlers — `emit_finding` (findings), `emit_artifact` (the full ingest pipeline; the document outlives the session), `propose_precedent`/`propose_memory` (curation-gated; ADR 0013 D5 — the only project-context write path is still user-accepted proposals). The agentic loop changes *how the session decides*, not *what it is permitted to do or write*.

## Consequences

- **The autonomous layer gains genuine agency without leaving its governance.** A new planner loop sits between the analysis node and `guarded_tool_call`; everything downstream (brakes, audit, output) is unchanged. The deterministic phase graph and its safety guarantees are intact.
- **A model never controls a safety-critical transition.** Ethics review always runs; delivery is always last and (after PR2) always gated. The agency is bounded to research adaptation.
- **One new bound, no new brake class.** A per-phase step cap is added; R4/R5/R6 are reused. The session is bounded in both spend (R4) and iteration (step cap).
- **Cost is real and metered.** A multi-step planned loop makes more inference + retrieval calls than today's single analysis call; R4 (and, when WS-E lands metered sources, [DE-344](../PRD.md#de-344)) is what keeps it bounded. WS-D is a forcing function for R4 being real on external tools.
- **Fiduciary-grade output is reuse, not a fork (PR2).** The autonomous session produces the same ledger/gate artifacts as chat; a reviewer traces a session's citations exactly as they trace a chat turn's. No parallel ledger.
- **The plan is auditable.** The transparency claim extends to agency — every planner choice is in the audit log and the receipt.

## Open questions (resolve in the WS-D PR specs/plans)

- **Planner prompt + completion signal (PR1).** The planner's structured-output contract (next intent + rationale, or "phase complete"), its calibration, and how "analysis complete" is recognized vs. forced by the step cap.
- **Step-cap value + tunability (PR1).** The per-phase cap, whether it is operator-configurable, and how a cap-halt is surfaced (partial result + "halted: step cap").
- **Observation-context management (PR1).** How prior step results are summarized back into the planner's context within the inference budget (the loop's context grows each step).
- **Matter-intake shape (PR1).** Whether intake is a deterministic pass-through of the description into the goal, or an LLM step that structures the matter into sub-questions — and how much it may presume before the analysis loop runs.
- **Ledger/gate wiring point (PR2).** Exactly where in the session lifecycle the citation cascade runs (per-retrieval vs. at drafting), how the session's sources become citable, and how `compute_and_record_gate` is scoped to the session's work product.
- **R4 / DE-344 dependency (PR1/PR2).** How much WS-D's loop cost is bounded by R4 today (inference-only, via the judge-cost estimator) vs. needs WS-E's DE-344 metered-source cost model before pointing the loop at metered providers.
