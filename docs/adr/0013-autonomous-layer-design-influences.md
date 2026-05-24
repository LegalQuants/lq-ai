# ADR 0013 — Autonomous Layer design influences (M4 / LQVern)

**Status:** Proposed
**Date:** 2026-05-24
**Owner:** M4 / LQVern kickoff (feature branch `feat/lqvern-m4-autonomous`)

## Context

PRD [§3.10 Autonomous Layer](../PRD.md#310-autonomous-layer-m4) commits the architectural slot for long-running per-user agents that observe activity, learn patterns, take proactive actions, and run scheduled/triggered work — but explicitly defers the detailed design ("This is M4 territory; detailed design deferred. The PRD commits to the capability and the architectural slot, not to the full design"). M4 is where **Tier 2 of the boundary-register catalog** ([§1.8](../PRD.md#18-security-posture), [`docs/security/boundary-registers.md`](../security/boundary-registers.md)) — R4 economic, R5 temporal, R6 contextual — first attaches to running code. [DE-293](../PRD.md#de-293) carries the implementation spec for those restraints; [DE-294](../PRD.md#de-294) carries cross-agent handoff validation **if** M4 ships multi-agent flows.

[DE-289](../PRD.md#de-289) names [AnttiHero/lavern](https://github.com/AnttiHero/lavern) (Apache-2.0, TypeScript/Fastify/SQLite "agentic law firm") as the closest public prior art, and its **Clawern** autonomous mode as the most concrete working pattern for the §3.10 open questions and the Tier-2 brakes. This ADR is **DE-289 Phase 1**: it compares Clawern's pattern to LQ.AI's substrate, **pins the single-agent-vs-multi-agent question** (which gates DE-294 classification), answers §3.10's open questions, and is the input to the M4 implementation plan.

**Provenance note.** Lavern's mechanisms cited here are as extracted in DE-289/DE-293 from Lavern's README and source-file names (`cost-tracker.ts`, `haltCheckHook`, the dynamic-permissions layer, `orchestrate.ts`). This ADR reasons about Clawern's *pattern*, not a line-by-line re-derivation; a deeper source read is available to a contributor who wants to refine a specific mechanism, but the load-bearing facts are stable and sufficient to pin the decisions below. Per the §1.9 conservative-posture principle and Lavern's own stated lack of an independent benchmark, Clawern is treated as a **design reference, not validated implementation** — we adopt shapes, not quality claims.

## Decision drivers

What §3.10 needs from the design that the current sketch does not yet name:

1. **An execution substrate** for long-running, resumable, scheduled/triggered agent work that does not interfere with interactive use.
2. **The Tier-2 brakes wired in, not bolted on** — a per-session cost cap (R4), an external halt switch + idle timeout (R5), and per-phase tool-grant modulation (R6), checked *before every tool call*.
3. **A transparency/audit posture** for autonomy consistent with the rest of the product: a user must be able to read, after the fact, exactly what an agent did and why (the §1.3 transparency principle applied to actions, not just prompts).
4. **A memory model** that resolves §3.10's internal tension (functional reqs say memory is "user-curated"; the open questions and §3.11 say it is "system-curated").
5. **A disambiguation** of the precedent board from Project context (§3.11) and from per-user memory.
6. **A single-agent-vs-multi-agent pin** that gates DE-294.

## Considered alternatives (execution substrate)

### A. Clawern-shaped, re-implemented natively on the api/arq substrate — **chosen**

Clawern's pattern: a heartbeat loop wakes periodically, evaluates watched state, runs an agent that calls tools under a cost tracker (`cost-tracker.ts`, default ~$5/session), a halt hook (`haltCheckHook` — "the red button", checked before every tool call, with a ~5-minute idle auto-halt), and a dynamic-permissions layer that strips tool grants at phase boundaries (e.g., removes search/read at the ethics gate). LQ.AI **re-implements this pattern natively** in `api/app/autonomous/` as a LangGraph state machine on the existing **arq-worker**, mirroring the shipped Playbook executor (`api/app/playbooks/`).

- **Cost:** new module + tables; the brakes are real engineering (DE-293).
- **Why it wins:** LQ.AI already has every substrate piece Clawern lacks — a **durable task queue** (arq/Redis), **Postgres** for session/memory/precedent state, **pgvector + FTS** retrieval, **char-precise citation verification** (M2), the **anonymization layer** (M2), a **cost estimator** (M2-E2 rolling average), and the **gateway** as the inference boundary. The executor reuses the Playbook executor's proven LangGraph + Pydantic-typed-state pattern, so the brakes and audit attach the same way DE-292 attaches them to playbooks. Under this shape every §3.10 open question has a concrete home (below).

### B. Temporal / Celery-shaped (dedicated workflow engine)

A purpose-built durable-workflow engine (Temporal, or Celery beat) for the scheduling + resumability story.

- **Cost:** a new heavyweight dependency and operational surface; a second queue alongside arq; SBOM + supply-chain expansion (CLAUDE.md: new deps need justification).
- **Rejected:** arq already provides durable, Redis-backed scheduled + enqueued execution and is what the Playbook/ingest/tabular workers run on. A second engine fragments the backend for no capability we lack. Revisit only if cross-service saga orchestration becomes a requirement (not an M4 need).

### C. Naive cron job (OS cron → one-shot script)

- **Rejected:** no resumability, no per-session state, no place to attach the brakes/audit/OTel, no halt switch. Fails decision drivers 2 and 3 outright. Named only to reject it explicitly.

> **Note on §3.10's "runs as OpenWebUI Pipelines" wording.** That phrasing predates this ADR. OpenWebUI Pipelines is a TypeScript/web-layer plugin surface; the autonomous executor's work — legal agent loops, cost/halt/phase brakes, Postgres-backed memory, citation/anonymization integration, OTel domain spans — is backend (Python) territory. This ADR supersedes the "Pipelines" framing: the executor lives in `api/`, and the PRD §3.10 build-out on this branch corrects the wording. (The web layer still renders the dashboard + receipts; it does not run the agent loop.)

## Decision

### D1. Single-agent for M4 v1, designed to extend — **pins DE-294**

M4/LQVern v1 ships **single-agent** autonomous flows: one agent per `autonomous_session`, running the §3.10 user stories (watches, scheduled scans, skill suggestions). This **delivers every committed §3.10 user story** without the agent-to-agent handoff surface, and lets the brakes + audit + OTel substrate be proven before any multi-agent orchestration. **DE-294 stays P2/deferred** (cross-agent handoff validation attaches to whichever later milestone first ships multi-agent flows). The executor's interfaces (typed session state, closed tool-intent enum) are designed so a multi-agent orchestrator can later wrap single-agent sessions without redesign — Clawern's debate protocol is the reference for that future increment, not a v1 deliverable.

### D2. Execution substrate: alternative A (api/arq, LangGraph, mirrors playbooks)

`api/app/autonomous/` on the arq-worker. Scheduled work via arq's cron; event-triggered work (watches) enqueued by the existing ingest pipeline on document arrival. Inference via the gateway client, exactly as playbooks call it.

### D3. The Tier-2 brakes, adopted from Clawern's shape (DE-293)

| Register | Clawern reference | LQ.AI adoption |
|---|---|---|
| **R4 economic** | `cost-tracker.ts`, ~$5 default per-session budget | `autonomous_sessions.max_cost_usd` (deployment default in `gateway.yaml`, suggested $5), checked before every tool call against `cost_total_usd` using the M2-E2 estimator; overrun → `cost_cap_reached` terminal state + partial result preserved. **Adopt the shape and the $5 default.** |
| **R5 temporal** | `haltCheckHook` ("red button") + ~5-min idle auto-halt | `autonomous_sessions.halt_state` (`running`/`halt_requested`/`halted`/`paused`); read before every tool call; `POST /api/v1/autonomous/sessions/{id}/halt`; idle > `idle_halt_minutes` (default 5) auto-pauses then halts. **Adopt directly.** |
| **R6 contextual** | dynamic permissions strip tools at ethics gate / delivery | Workflows declare phases (`intake`/`analysis`/`drafting`/`ethics_review`/`delivery`) with per-phase tool grants; the executor's current-phase row gates every tool call; transitions are explicit + audited. **Adopt the shape; the phase set is LQ.AI's, not Lavern's.** |

### D4. Memory model — *system-proposes, user-owns* (resolves the §3.10 tension)

The agent **observes and proposes** memory entries (so the source is system-derived), but every entry is **user-visible, user-editable, user-deletable, and applied only after the user keeps it**. Default posture: proposals surface for review, not silent write. This reconciles "user-curated" (the user holds authority and ownership) with "system-curated" (the system derives the candidates). It also satisfies R-class restraint by keeping a human in the loop on what the agent is allowed to remember about them.

### D5. Precedent board — *absorbed into M4 v1, distinct from the other two memory surfaces*

§3.10's open "absorb / reject / separate" question is resolved as **absorb, as a distinct construct**:

- **Project context (§3.11):** user-authored, per-matter, user-owned. *What this matter is.*
- **Autonomous memory (D4):** system-observed patterns about **the user's preferences/behavior**, user-owned. *How this user likes to work.*
- **Precedent board (this ADR):** system-observed patterns about **documents/clauses across matters** (recurring counterparty positions, clause-language patterns), read-mostly, user-dismissable. *What we keep seeing in the documents.* The agent may **propose** promoting a precedent into a Project's context but never writes Project context directly.

Hard per-user isolation applies to all three (no cross-user leakage, §3.10 NFR).

### D6. The transparency/audit/OTel alignment contract is non-optional

Every autonomous flow, by construction, emits OTel domain spans (`autonomous.session` + `autonomous.tool_call` children, attributes = cost/halt/phase/tool/outcome, **counts and types only, never raw entity values** — the M2 anonymization-span guarantee extends here), writes a closed-enum audit trail, and produces a human-readable per-session receipt ("what the agent did and why"). This is specified for contributors in [`docs/LQVern/agentic-flow-alignment-guide.md`](../LQVern/agentic-flow-alignment-guide.md) and is the heart of keeping autonomy aligned with the §1.3 transparency principle. New autonomous code that does not emit these is not done.

## §3.10 open questions — resolved

- **Detailed design deferred?** No longer — this ADR + the PRD §3.10 build-out on this branch are the design. M4 implementation follows the writing-plans output.
- **Distinction from Projects (§3.11)?** Resolved in D5 (three-way distinction).
- **Forward extension to M5+?** D1's single-agent interfaces are designed so multi-agent orchestration (Clawern's debate protocol; DE-294) and external-side-effecting actions with approval gates extend without redesign. The memory + scheduled-pipeline substrate is the M5+ workflow-intelligence foundation per §8.5.

## Open questions remaining (for the implementation plan / contributor)

1. **Watch trigger plumbing:** does the ingest pipeline enqueue the autonomous session directly, or publish an event the autonomous scheduler subscribes to? (Pin in the implementation plan; the simpler direct-enqueue is the likely answer given arq.)
2. **Notification surface:** email + in-app are committed; the optional webhook to the §3.15 Slack/Teams bridge is a fold-in once that bridge's send-path exists (DE-312 gates the bridge's E2E).
3. **Precedent-board scope:** per-user vs per-deployment. D5 pins per-user for isolation; a per-deployment (org-shared) precedent board is a possible later option — file as a DE if it surfaces.

## Cross-references

- PRD [§3.10](../PRD.md#310-autonomous-layer-m4) (build-out on this branch links back here from "Open questions"), [§1.8](../PRD.md#18-security-posture), [§3.8](../PRD.md#38-multi-model-ensemble-verification), [§8.5](../PRD.md#85-mcp-client-subsystem).
- [DE-289](../PRD.md#de-289) (this ADR is its Phase 1 deliverable), [DE-293](../PRD.md#de-293) (the R4/R5/R6 spec D3 discharges), [DE-294](../PRD.md#de-294) (deferred per D1), [DE-292](../PRD.md#de-292) (the Playbook-executor retrofit whose pattern D2 mirrors).
- [`docs/security/boundary-registers.md`](../security/boundary-registers.md) (R4/R5/R6 flip to "shipped" when DE-293 lands).
- [`docs/LQVern/agentic-flow-alignment-guide.md`](../LQVern/agentic-flow-alignment-guide.md) (the D6 contract, for contributors).
- Provenance: [`docs/LQVern/HANDOFFlavernevaluation.md`](../LQVern/HANDOFFlavernevaluation.md). (This work began as a "DE-265" PRD patch, since re-landed and renumbered on `main` as DE-289.)
