# ADR 0015 — Governed tool-calling model (closed-intent posture extended, not abandoned)

**Status:** Proposed
**Date:** 2026-06-16
**Owner:** Legal-research + MCP milestone kickoff (feature branch `feat/legal-research-mcp-plan`)

## Context

Bringing CourtListener and MCP to LQ.AI means, for the first time, **letting the model call tools** — both in interactive chat and in the autonomous layer. The closest prior art, [MikeOSS](https://github.com/willchen96/mike), gives the model an **open, per-user function-calling surface** that egresses directly from the backend. That is the single most consequential divergence from LQ.AI's posture, which is built on **bounded, closed-set tool intents**: the autonomous layer already enforces a closed `ToolIntent` enum gated by `PHASE_GRANTS` and the R5→R6→R4 brakes (`api/app/autonomous/enums.py`, `api/app/autonomous/guard.py`, [ADR 0013](0013-autonomous-layer-design-influences.md)).

The question this ADR pins: **how does the model invoke research / MCP tools, and how is each invocation governed**, in a way that delivers interactive-research parity *without* abandoning the closed-set posture. It is the companion to [ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md) (which pins *where egress lives*); this ADR pins *how a tool call is decided, authorized, audited, and surfaced*. It is load-bearing for mini-PRD WS4 and WS5.

A correctness note carried from the verification pass: the autonomous brakes execute **R5 (temporal/halt) → R6 (contextual/phase-grant) → R4 (economic/cost)**, in that order. Earlier proposal text said "R4/R5/R6"; the governed loop here adopts the brakes in their real execution order.

## Decision drivers

1. **Interactive research needs a real tool-calling loop.** Citation verification, case lookup, and "find in this opinion" are inherently multi-step and model-driven within a turn. A pure closed-intent batch call is too weak for the interactive parity target.
2. **The closed-set posture is the product, not overhead.** Transparency and governability come from the operator knowing *exactly* which tools the model may call. An open function-calling surface forfeits that.
3. **Chat and the autonomous layer should share one governed substrate.** The autonomous layer already has brakes + audit + closed intents. Re-deriving a parallel governance path for chat would fork the posture and double the security surface.
4. **Destructive tools need a human gate.** MCP tools carry `read_only` / `destructive` / `requires_confirmation` metadata. A destructive tool must never fire un-approved in chat, and must never be auto-granted to the autonomous layer in v1.
5. **Every tool call must be auditable and inspectable.** The transparency differentiator (§1.3) applied to tool use: which tool, which provider, which tier, the result provenance, an audit row, and a UI provenance pill.

## Considered alternatives

### A. Governed hybrid loop on an operator-enabled allowlist — **chosen**

A gateway-mediated function-calling loop for chat, **restricted to an operator-enabled allowlist** of research + enabled MCP tools (not open function-calling). Each proposed call is, per invocation: tier-checked, audited (`tool_call_log`), cost-accounted, and **confirmation-gated** when the tool is `destructive`. The *same* tools are exposed to the autonomous layer as **new bounded `ToolIntent`s** (`retrieve_caselaw`, `call_mcp_tool`) under the existing `PHASE_GRANTS` + R5→R6→R4 brakes.

- **Cost:** a chat tool-loop module, a `tool_call_log` table, two new `ToolIntent` members + phase-grant wiring, and confirmation-gate plumbing through to the UI.
- **Why it wins:** it gives interactive research the loop it needs while keeping the surface closed — the allowlist *is* the closed set, just operator-configured rather than hard-coded. Chat and autonomous share one governance substrate (the brakes/audit/closed-intent machinery already exists and is proven). The model picks *among* allowed tools; it cannot reach beyond them.

### B. Closed-intents-only (no interactive loop)

Expose research only as fixed, single-shot intents (the existing autonomous pattern), no in-turn model-driven loop.

- **Rejected:** too weak for the interactive parity target. "Verify these citations, then read the cluster the model found, then search within it" is a loop; flattening it to one batched intent either over-fetches or fails the use case. Keeps the posture but misses the capability.

### C. Open model-driven function-calling (the MikeOSS shape)

Let the model call any discovered tool, backend-direct.

- **Rejected:** abandons the closed-set posture that is the product's governance story. No operator allowlist, no per-call tier ceiling, an un-bounded egress surface. This is the divergence §1.8 and ADR 0013's closed `ToolIntent` enum exist to prevent. Named to reject it explicitly.

## Decision

### D1. Chat tool-calling is a gateway-mediated loop over an operator allowlist — chosen alternative A

The chat send path (`api/app/api/chats.py`) gains a tool-calling loop: the gateway exposes the **operator-enabled allowlist** of tools to the model; the model proposes a call; the backend governs and executes it via the ADR 0014 egress boundary; the result is fed back; the loop continues until the model emits a final answer or a per-turn tool-call cap is hit. The allowlist is operator-configured (research tools when CourtListener is enabled; MCP tools per `mcp.yaml` + per-tool enable/disable). The model may only call tools on the allowlist — there is no open function-calling.

### D2. Per-call governance: tier check, audit, cost, confirmation

Every proposed tool call passes, before execution:
- **Tier check** — the tool provider's data-egress tier (ADR 0014 D4) vs. the matter/skill minimum; refuse + audit if exceeded.
- **`tool_call_log` audit row** — tool, provider, tier, request_id, outcome, cost; counts/types only, never raw payloads.
- **Cost accounting** — folded into the same estimator the inference path and autonomous R4 brake use.
- **Confirmation gate** — if the tool is `destructive` (or `requires_confirmation`), the model *proposes* the call, the loop pauses, the user approves, then it executes. `read_only` tools execute without a gate.

### D3. Two new bounded `ToolIntent`s for the autonomous layer

`retrieve_caselaw` and `call_mcp_tool` are added to `ToolIntent` (`api/app/autonomous/enums.py`) and to `PHASE_GRANTS`:
- `retrieve_caselaw` → granted in the `analysis` phase (alongside `retrieve_chunks`), conservative elsewhere.
- `call_mcp_tool` → granted **per-phase, conservative default** (most phases: not granted), and only for tools the operator has enabled.

Both are enforced by the existing `guarded_tool_call` R5→R6→R4 brakes — no new brake machinery. The autonomous layer reuses the *same* allowlist and the *same* egress boundary as chat; the only difference is the additional R-class restraint envelope.

### D4. Destructive / confirmation-required tools are never auto-granted to the autonomous layer in v1

A tool whose metadata is `destructive` or `requires_confirmation` is **excluded from `PHASE_GRANTS` in all phases** for the autonomous layer in v1. The autonomous layer cannot fire a human-gated tool without a human, and v1 does not build an async approval channel for autonomous sessions (defer to a DE if demanded). Interactive chat (D2) is the only place a destructive tool can fire, and only behind the confirmation gate.

### D5. Tool use is transparent by construction

Mirroring ADR 0013 D6: every tool call emits an OTel span (`chat.tool_call` / `autonomous.tool_call`, attributes = tool/provider/tier/outcome/cost, counts and types only), writes a `tool_call_log` row, and surfaces in the UI as a **provenance pill** (which tool, which provider, which tier). Case-law answers additionally carry external-source citation provenance (ADR 0014 D5 + the citation engine), so a research answer is reproducible, not a bare chat bubble. A skill that uses tools **declares** that usage and its `minimum_inference_tier` in SKILL.md frontmatter — note that frontmatter is authored today but **not yet parsed/validated in code**, so WS5 must build the parser before the declaration is load-bearing.

## Open questions (for the implementation plan / contributor)

1. **Per-turn tool-call cap.** What is the default cap on tool calls per chat turn (cost + latency bound)? Pin in WS4 (a small integer, operator-overridable).
2. **Confirmation-gate transport.** How does the pause/approve round-trip render over the existing SSE chat stream — a special event the UI renders as an approve/deny prompt, resuming the loop on POST? Pin the event shape in WS4 alongside the chat-stream contract.
3. **Allowlist source of truth.** Research tools key off CourtListener-enabled; MCP tools off `mcp.yaml` + per-tool enable/disable. Confirm whether the allowlist is assembled in the backend or surfaced by the gateway; likely backend-assembled, gateway-enforced. Pin in WS2/WS4.

## Cross-references

- [ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md) (the egress boundary this loop invokes), [ADR 0013](0013-autonomous-layer-design-influences.md) (the closed `ToolIntent` enum, `PHASE_GRANTS`, and R5→R6→R4 brakes this extends).
- PRD [§1.8 security posture](../PRD.md#18-security-posture), [§3.6 research](../PRD.md#36-research), [§3.10 autonomous layer](../PRD.md#310-autonomous-layer-m4), [§8.5 / DE-200](../PRD.md#de-200).
- [`docs/security/boundary-registers.md`](../security/boundary-registers.md) (R4/R5/R6).
- Mini-PRD: [`docs/proposals/legal-research-and-mcp.md`](../proposals/legal-research-and-mcp.md) (WS4 + WS5 discharge this ADR).
- Reference (the divergence we reject): [MikeOSS](https://github.com/willchen96/mike) open per-user function-calling.
