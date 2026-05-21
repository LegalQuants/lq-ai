# Boundary Registers — Restraint Catalog

> **Status:** Posture document. Per-register state-of-implementation refreshed at every milestone close, with line-level source citations a reviewer can verify in seconds. Read alongside [PRD §1.8](../PRD.md#18-security-posture) (which names this catalog as the framework) and [HONEST-STATE.md](../HONEST-STATE.md) (which catalogs shipped vs. deferred capabilities).
>
> **Audience:** operators evaluating LQ.AI, security reviewers reading the codebase, and contributors authoring skills or roadmap work that attaches to one of the registers.

## What this document is (and is not)

A useful framing of professional-services agent design, articulated by Dazza Greenwood in May 2026 ("[The Most Interesting Thing in Claude for Legal Is the Lawyer/Agent Boundary](https://dazzagreenwood.substack.com/)"), classifies the restraints a serious agentic legal system needs into a small catalog of *registers* — three describing **how** a boundary is enforced (prompt-and-workflow, capability/tool-grant, code) and three describing **what else** needs restraining once autonomy exists (economic, temporal, contextual). LQ.AI adopts this catalog as the organizing framework for its boundary-enforcement work.

A few things this document is **not**:

- **Not a marketing claim.** The goal is not to ship "six of six" as a positioning statement. The goal is to make every register's state — implemented, partial, deferred-with-commitment, or rejected-with-reasoning — verifiable in source. The honest count today is 2 fully, 2 partial, 2 deferred-with-architectural-commitment.
- **Not a fixed enumeration.** The number six is the count of registers observed in the two open-source codebases Greenwood ran (Claude for Legal and Lavern, both Apache 2.0) as of May 2026. Future systems may add registers — cryptographic restraint, jurisdictional restraint, others not yet articulated. This document treats the catalog as a living artifact; the framework is the durable contribution, not the count.
- **Not a re-derivation of Greenwood's analysis.** Where this document uses "registers of restraint," "Tier 1 vs. Tier 2," and the R1–R6 numbering, the vocabulary follows Greenwood's coinage. Detailed framework rationale lives in the source article; this document captures only what an LQ.AI operator needs to verify the project's current state against the framework.

The Inference Choice Spectrum (PRD §1.5.2) is a **seventh, orthogonal** boundary, not a seventh register. It restrains *where data goes during inference* rather than *what the model may decide, spend, run, or touch*. The two axes interact (a privileged Project forces both an inference-tier floor and a normative posture on what skills may do) but they are not the same dimension. The Inference Choice Spectrum is documented separately in PRD §1.5.2 / §3.13 / §4.4 and gets a short cross-reference at the end of this document rather than its own register entry.

---

## Update cadence

Refreshed at every milestone close. Each register's "Current implementation" subsection cites specific file paths and PRD sections so a reviewer can verify the claim against current code without reading the section's prose first.

| Refresh | Trigger | Where |
|---|---|---|
| Per-milestone close | Each milestone PR that flips a capability from "Deferred" → "Shipped" updates the relevant register's entry | This file |
| When a register moves status | "Not yet" → "Partial" or "Partial" → "Fully" requires a PR explicitly updating this file with line-level citations | This file + PRD §9 DE entry tracking the work |
| When a new register is recognized | If community practice surfaces a useful seventh register (e.g. cryptographic, jurisdictional), a PR adds a new section with same structure | This file |

---

## Tier 1 — How the boundary is enforced

The first three registers answer **how** a restraint is enforced. Greenwood's framing: the type of enforcement should vary with the type of risk. Lawyer-in-the-loop conversational work can be gated normatively; headless cron jobs cannot; agent-to-agent handoffs need code-level validation. This is the escalation rule: **the more autonomous the action, the harder the gate must be**.

### R1 — Prompt-and-workflow restraint (normative)

**Definition.** The model is instructed, in the practice-profile context every skill reads before acting, to refuse, flag, or gate at consequence boundaries. The gate travels with the model, not with the interpreter. Used for conversational work where a lawyer is reading every output.

**Current implementation: SHIPPED (fully).**

- **Skill format carries normative behavior.** Every skill is an inspectable artifact in `skills/` (PRD §3.4) with frontmatter and prompt text the operator can read. The Organization Profile singleton (PRD §3.12; configured per deployment) is prepended to skill prompts and binds org-wide voice, jurisdictional posture, and standard positions to every skill execution.
- **Citation Engine enforces cite-or-flag at the verification stage.** The four-stage verification cascade in `api/app/citation/verification.py` (M2 — exact match → tolerant match → paraphrase judge → ensemble) rejects unverified citations rather than rendering them as confident-looking text. The cascade is documented in PRD §3.3.
- **Built-in playbook descriptions carry the Decision F framing.** All built-in playbooks in `skills/playbooks/` (M3-A3 NDA mutual + unilateral, M3-A5 MSA-SaaS + DPA-GDPR + MSA-Commercial-Purchase) carry "starting point, not a vetted template" framing in their `description` field, naming the user-attorney as the validator. Easy Playbook wizard output (M3-A6) is treated identically.
- **Skill-authoring guide names conventions.** `docs/skill-authoring-guide.md` enumerates prompt-isolation and severity-handling conventions skills should adopt.

**Gap.** The normative rules R1 implements are scattered. A reviewer asking "what are LQ.AI's rules of restraint at the conversational layer?" should get a one-section answer with testable invariants, not a treasure hunt across the skill-authoring guide, individual skills' SKILL.md files, the Organization Profile schema, and the Citation Engine's verification surface. Codification + golden tests are tracked by **DE-291**.

**Verification path.**

```bash
# Read the canonical surfaces:
less docs/skill-authoring-guide.md            # R1 rule conventions today
less skills/playbooks/nda/playbook.yaml       # Built-in disclaimer framing
less api/app/citation/verification.py         # Cite-or-flag enforcement
```

### R2 — Capability / tool-grant restraint

**Definition.** The boundary is not a normative instruction but a tool grant. An agent that doesn't have a tool cannot bypass not having it; a model jailbreak that convinces an agent to "ignore previous instructions and use tool X" fails because the tool is not in the agent's grant.

**Current implementation: SHIPPED (in an adapted form).**

LQ.AI's first capability boundary attaches to the **inference path** rather than to agent-to-agent tool grants. The Inference Tier model (PRD §1.5.2, §3.13, §4.4) lets a skill, Project, or request declare `minimum_inference_tier`; the gateway returns a structured 403 with `tier_below_minimum` when a routing decision would violate that floor.

- **Code path.** `gateway/app/tier_floor.py` (refusal envelope), `gateway/app/router.py` (annotation in B4 stage), `gateway/app/errors.py` (`CODE_TIER_BELOW_MINIMUM`).
- **Privileged Projects force a tier floor.** PRD §3.11 — privileged Projects disable anonymization and require a tier matching the privilege posture.
- **Per-purpose tagging (M2-E2).** `gateway/app/routing_log.py` adds `lq_ai_purpose` tagging so cost-estimation and the ensemble pre-flight budget (R4-partial) can differentiate judge calls from chat calls and embeddings.

**Gap.** Agent-to-agent tool grants don't exist as a model today because LQ.AI doesn't yet have agents-calling-agents. The Playbook executor (M3-A2, `api/app/playbooks/executor.py`) runs single-agent multi-step workflows with implicit tool capabilities (read document, retrieve chunks, emit findings); each step does not declare its tools explicitly. A retrofit that adds declared per-position tool grants is tracked by **DE-292**.

**Verification path.**

```bash
less gateway/app/tier_floor.py                # Tier refusal envelope
less gateway/app/router.py                    # Annotation + decision
less gateway/app/errors.py                    # tier_below_minimum code
```

### R3 — Code restraint

**Definition.** Used at the boundary between agents (and between agents and external destinations) — where a hostile document upstream could otherwise smuggle instructions across the seam. The seam is Python (or equivalent), with target allowlists, closed intent enums, per-intent regex/JSON-Schema parameter validation, and typed-template prompt rendering that never derives steering-prompt text from agent output. Every accept and reject is audited.

**Current implementation: PARTIAL.**

- **The Inference Gateway is a code-enforced security boundary in a separate process.** Privileged provider API keys live only inside `gateway/` (PRD §4); the backend cannot reach them. Every request crosses the process boundary.
- **Citation Engine Stage 2 is code-level deterministic substring verification, not an LLM grading itself.** `api/app/citation/verification.py` runs exact-match + rapidfuzz-tolerant-match before any LLM judge is invoked.
- **Anonymization Layer is code-level entity rewriting.** `gateway/app/anonymization/` (`engine.py` + `mapper.py` + `middleware.py` + `recognizers/`) handles pre/post pseudonymization with streaming-aware rehydration.
- **Playbook executor handoffs are Pydantic-typed.** `api/app/playbooks/state.py` (LangGraph state) + `api/app/playbooks/nodes.py` + `api/app/playbooks/executor.py` together enforce typed transitions between executor steps. Failed schema validation surfaces as a structured failure rather than malformed output passed downstream.
- **Easy Playbook generation is a code-orchestrated multi-step pipeline.** `api/app/playbooks/easy/extractor.py` + `clustering.py` + `assembly.py` (M3-A6) similarly run as code-orchestrated steps with Pydantic-validated outputs at each seam.

**Gap.** The Lavern `orchestrate.py` pattern — closed intent allowlist + per-intent JSON-Schema parameter validation with regex patterns + typed-template prompt rendering + JSONL audit log of every accept and reject — is not yet wired into either the Playbook executor (single-agent today) or any cross-agent surface (no cross-agent surface exists yet). Two retrofits are tracked:

- **DE-292** — retrofit the existing Playbook executor with declared per-position tool grants + schema-validated step handoffs + per-execution cost cap (the R3 facet for in-Playbook step seams).
- **DE-294** — `orchestrate.py`-equivalent for autonomous multi-agent flows, if/when M4 ships multi-agent autonomous flows; pinned by the design-influences ADR from DE-289 Phase 1.

**Verification path.**

```bash
# Gateway as security boundary:
less gateway/app/main.py                      # Separate-process entrypoint
# Citation Engine deterministic verification:
less api/app/citation/verification.py
# Anonymization middleware:
less gateway/app/anonymization/middleware.py
# Playbook executor typed transitions:
less api/app/playbooks/state.py
less api/app/playbooks/executor.py
```

---

## Tier 2 — What else needs restraining

Once autonomy exists — once the system runs without a lawyer reading every output — three further restraints attach. They answer **what else** needs a brake: money, time, and workflow phase. These registers don't apply to conversational work where a human reads every reply; they apply when the system runs unattended.

### R4 — Economic restraint

**Definition.** A per-session or per-execution cost cap that halts the run rather than overspend. An agent running in a loop can quietly burn a fortune in API credits; the brake checks projected cost against a remaining budget before every tool call and halts gracefully if a call would exceed the cap.

**Current implementation: PARTIAL.**

- **Per-call cost tracking (M1).** `inference_routing_log` table captures `cost_estimate` per provider call (PRD §5.5).
- **Per-purpose tagging (M2-E2).** `gateway/app/routing_log.py` adds `lq_ai_purpose` so judge-call cost can be differentiated from chat-call cost.
- **Rolling-average cost estimator (M2-E2).** `api/app/citation/cost.py::estimate_judge_call_cost_usd` queries per-model rolling averages from `inference_routing_log` with cold-start defaults.
- **Per-message ensemble pre-flight budget (M2-D1).** Pre-flight check in `chats.py::_resolve_ensemble_config` falls back from ensemble to single-judge Stage 3 when projected `n_citations × n_judges × per-judge-cost` exceeds the per-message cap.

**Gap.** No hard per-session or per-execution `max_cost_usd` cap that halts an autonomous flow on overrun. The Playbook executor today does not surface a cost cap to the operator at execution time. The Easy Playbook generation pipeline has an ARQ `job_timeout` of 900 seconds (temporal, not economic) but no spend cap.

Two follow-ons:

- **DE-292** retrofits a per-execution `max_cost_usd` cap on Playbook executions (M3 follow-on; folds into the executor's pre-flight cost-check).
- **DE-293** specifies the per-autonomous-session cap for the M4 autonomous layer — defaults to a configurable value in `gateway.yaml` (suggested $5 initial default, matching Lavern's posture).

**Verification path.**

```bash
less api/app/citation/cost.py                 # Rolling-average estimator
less gateway/app/routing_log.py               # Per-purpose tagging
less api/app/api/chats.py                     # Pre-flight cost budget (M2-D1)
```

### R5 — Temporal restraint

**Definition.** A liveness primitive checked before every tool call: external halt signal, idle-timeout auto-halt. An agent that runs unattended needs a stop that an operator can hit from outside the agent's loop.

**Current implementation: NOT YET (marginal).**

A hard temporal brake exists in the form of ARQ `job_timeout` (currently 900s for `easy_playbook_generation_job`; configurable per-job), which kills a worker after the timeout elapses. This is *a* temporal brake but not the Lavern `haltCheckHook` pattern — it is a hard kill (the worker process is terminated, partial state may not be preserved cleanly) rather than a graceful halt that flushes the session's partial state, audits the halt cause, and surfaces a structured "halted" result to the operator. There is no external halt switch checked before every tool call; an operator cannot intervene mid-run to halt a generation that is otherwise going to complete.

The graceful halt pattern attaches to the autonomous layer (PRD §3.10, M4). Implementation specification tracked by **DE-293** (the R5 facet): liveness primitive on the autonomous-session table, before-every-tool-call check, idle-halt timeout (suggested 5 minutes, matching Lavern), structured `halted` final state.

**Verification path.**

```bash
grep -n "job_timeout" api/app/workers/        # Current hard-kill brake
```

### R6 — Contextual restraint

**Definition.** Tool access is not granted once and left. The agent's permissions modulate as the workflow advances — search/read tools available during intake, stripped at the ethics gate or delivery. Capability is scoped to where you are in the work.

**Current implementation: NOT YET.**

The Inference Tier model (R2) is a *resource-class* boundary, not a workflow-phase boundary. The Playbook executor (M3-A2) runs all positions with the same implicit capability set throughout the execution; there is no phase concept yet, no per-phase tool grant, no runtime tool-stripping at phase transitions.

R6 attaches to the autonomous layer (PRD §3.10, M4) and to multi-phase Playbook workflows. Implementation specification tracked by **DE-293** (the R6 facet): workflows declare phases (`intake`, `analysis`, `drafting`, `ethics_review`, `delivery`); the executor's current-phase row gates each tool call; phase transitions are explicit (declared in the workflow definition) and audited.

**Verification path.**

```bash
# No code path today — verification path lands with DE-293 / M4 implementation.
```

---

## Orthogonal boundary — the Inference Choice Spectrum

The Inference Choice Spectrum (PRD §1.5.2) is a **seventh boundary** that runs along a different axis from R1–R6. R1–R6 restrain *what the model may decide, spend, run, or touch*. The Inference Choice Spectrum restrains *where the data goes during inference*.

- The five tiers (PRD §1.5.2): local-only (Tier 1), customer-hosted cloud inference (Tier 2), enterprise managed inference with ZDR / no-training commitments (Tier 3), standard cloud API (Tier 4), consumer or free tier (Tier 5).
- Skills, Projects, and requests can require a minimum tier (R2-adapted, above); the gateway refuses routing decisions that violate the floor (`tier_below_minimum`).
- The audit log records every routing decision (`inference_routing_log` per PRD §5.5).
- Tier 3 is recommended for most pragmatic enterprise deployments; Tier 1 is recommended for the most sensitive privileged work.

This boundary is documented separately in:

- PRD §1.5.2 (the spectrum's five-tier definition)
- PRD §3.13 (the Inference Tier badge in the UI)
- PRD §4.4 (gateway configuration of tier mapping)
- PRD §1.8 (security posture; calls the spectrum "the central security trade-off")

It is named here so a reader doesn't conflate the two boundaries: a deployment can ship full R1 + R2 + R3 + R4 + R5 + R6 and still expose customer data to a weaker tier through configuration choices, or vice-versa.

---

## Summary table

| Register | Tier | State | Code path / DE |
|---|---|---|---|
| R1 — prompt/workflow | Tier 1 (how) | Fully | `docs/skill-authoring-guide.md`, `api/app/citation/verification.py`, built-in skills; codification by **DE-291** |
| R2 — capability/tool-grant | Tier 1 (how) | Fully (adapted) — inference tier; agent-tool-grant facet retrofit by **DE-292** | `gateway/app/tier_floor.py`, `gateway/app/router.py` |
| R3 — code | Tier 1 (how) | Partial — gateway + Citation Engine + Anonymization + Playbook executor typed transitions; closed-intent-enum + audit-log retrofit by **DE-292**, cross-agent handoff by **DE-294** | `gateway/`, `api/app/citation/verification.py`, `gateway/app/anonymization/`, `api/app/playbooks/` |
| R4 — economic | Tier 2 (what else) | Partial — per-call cost tracking + per-message ensemble budget; per-execution + per-session caps by **DE-292** / **DE-293** | `api/app/citation/cost.py`, `gateway/app/routing_log.py` |
| R5 — temporal | Tier 2 (what else) | Not yet — ARQ `job_timeout` is a hard-kill brake; graceful halt by **DE-293** | (DE-293 implementation path) |
| R6 — contextual | Tier 2 (what else) | Not yet — phase-modulated tool grants by **DE-293** | (DE-293 implementation path) |
| **Orthogonal** | Inference Choice Spectrum (where data goes) | Fully (per tier model) | `gateway/app/tier_floor.py`, PRD §1.5.2 |

---

## Cross-references

- [PRD §1.8 Security Posture](../PRD.md#18-security-posture) — names this catalog as the framework for restraint work.
- [PRD §3.10 Autonomous Layer (M4)](../PRD.md#310-autonomous-layer-m4) — names Tier 2 (R4 + R5 + R6) as load-bearing for M4 design.
- [PRD §9 DE-289](../PRD.md#de-289--lavern-as-design-reference-for-the-autonomous-layer-full-path-ensemble-and-mcp-catalog) — Lavern as design reference (the codebase Tier 2 framing draws from).
- [PRD §9 DE-291](../PRD.md#de-291--r1-codification-rules-of-restraint-in-skill-authoring-guide-and-golden-tests-for-starter-skills) — R1 codification + golden tests.
- [PRD §9 DE-292](../PRD.md#de-292--playbook-executor-retrofit-declared-tool-grants--schema-validated-step-handoffs--per-execution-cost-cap) — Playbook executor R2-agent + R3-step + R4-execution retrofit.
- [PRD §9 DE-293](../PRD.md#de-293--autonomous-layer-restraints-r4-economic-r5-temporal-r6-contextual) — autonomous-layer Tier 2 implementation spec.
- [PRD §9 DE-294](../PRD.md#de-294--cross-agent-handoff-validation-for-autonomous-multi-agent-flows) — cross-agent `orchestrate.py`-equivalent.
- [HONEST-STATE.md](../HONEST-STATE.md) — the parallel posture document for capabilities (this file is the same pattern for restraints).

---

*Source-of-framework citation: Dazza Greenwood, "The Most Interesting Thing in Claude for Legal Is the Lawyer/Agent Boundary," May 2026. The "registers of restraint" vocabulary and the R1–R6 numbering follow that article; LQ.AI adopts the framework as the organizing structure for restraint work and does not claim authorship of it.*
