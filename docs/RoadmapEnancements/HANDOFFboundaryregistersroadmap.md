# Boundary registers — roadmap proposal

> **Audience:** Claude Code on the receiving machine (continuation of the Lavern-evaluation work). This document proposes specific PRD edits and new DE entries that close the gaps in the six-register boundary catalog described by Dazza Greenwood (May 2026, "The Most Interesting Thing in Claude for Legal Is the Lawyer/Agent Boundary"), sequenced against LQ.AI's existing M3 / M4 / M5+ milestones. It is a planning document, not a commitment — Kevin should review the framing in §0 before any of it lands.
>
> **Companion to:** `HANDOFF-lavern-evaluation.md` (the Lavern evaluation session-handoff), and the unpushed DE-265 commit on `claude/evaluate-lavern-integration-YMMJi`.
>
> **External references:**
> - Greenwood's article (source of the 6-register framework). Not URL-citable from this session — Kevin has the draft.
> - [AnttiHero/lavern](https://github.com/AnttiHero/lavern) — Lavern's implementations of R3, R4, R5, R6 are the most concrete prior art available.
> - [anthropics/claude-for-legal](https://github.com/anthropics/claude-for-legal) — Claude for Legal's implementations of R1, R2, R3 (its conversational plugins ship empty hooks because the lawyer-in-the-loop carries R4/R5/R6 implicitly).

---

## 0. The framing question that needs Kevin's call before this lands

The six-register catalog is a useful framework. Adopting it verbatim as PRD language has two costs worth naming:

1. **Vocabulary attribution.** "Registers of restraint" is Greenwood's coinage. Using the term in PRD prose either (a) cites him, which roots LQ.AI's posture in a specific external author's framing, or (b) doesn't cite him, which is borderline. The PRD's existing prose ("transparency posture," "conservative posture," "Inference Choice Spectrum") is the project's own. **Recommendation:** cite him once on first use in a new posture subsection, then use the term naturally afterward. Same posture as the PRD's existing reference to ABA Formal Opinion 512.
2. **Six is not load-bearing.** The number 6 is the union of two open-source codebases' designs as of May 2026. Future systems may add registers (cryptographic restraint? jurisdictional restraint?). If the PRD adopts "six registers" as a fixed catalog, it inherits the fragility of that count. **Recommendation:** structure the new posture material as "the boundary-register catalog is the framework we use to organize this work; today it has six entries we recognize; the catalog is expected to grow." Treats the catalog as a living artifact, not a closed list.

Both choices are Kevin's. The proposals in this document assume both recommendations are accepted; if not, the receiving CC should rephrase before committing.

---

## 1. Where LQ.AI sits today (the honest count)

Reproduced from the chat reply Kevin sent to Greenwood, with the conservative-posture rule (CLAUDE.md §1.9) applied. **State as of mid-M3, post-M2.**

| Register | LQ.AI state | Concrete evidence |
|---|---|---|
| **R1 — Prompt/workflow (normative)** | **Yes** | Skill format (§3.4) carries normative behavior. Organization Profile (§3.12) binds org-wide voice to every skill prompt. Citation Engine (§3.3, shipped M2) enforces cite-or-flag at the verification stage. Skill-authoring guide (`docs/skill-authoring-guide.md`) has prompt-isolation conventions. *Gap:* no canonical "rules of restraint" enumerated in one place; the rules exist scattered across the guide and individual skills. |
| **R2 — Capability (tool-grant)** | **Yes, on an adapted layer** | Inference Tier model (§1.5.2 / §3.13 / §4.4) is a capability boundary on the inference path: `minimum_inference_tier` declared by skill, Project, or request; gateway returns 403 with `tier_below_minimum` on violation. Privileged Projects (§3.11) force a tier floor and disable anonymization. *Gap:* no agent-to-agent tool-grant model because there are no agents-calling-agents yet (M3/M4 territory). |
| **R3 — Code (handoff validation)** | **Adjacent today; not yet for agent handoffs** | The Inference Gateway (§4) is a code-enforced security boundary in a separate process. Citation Engine Stage 2 (M2) is code-level deterministic substring verification — no LLM grading itself. Anonymization Layer (§4.7, M2-target) is code-level entity rewriting. *Gap:* no `orchestrate.py`-equivalent validating cross-agent handoffs against typed templates, because cross-agent handoffs don't exist. |
| **R4 — Economic** | **Partial** | Per-call cost tracking (§5.5). M2's ensemble verification has a per-message cost-budget pre-flight that falls back to single-judge if a per-model rolling-average estimate would exceed cap (§3.8). *Gap:* no hard per-session / per-loop cap for autonomous flows. |
| **R5 — Temporal** | **Not yet** | No autonomous loops to halt. §3.10 commits the architectural slot. DE-265 names Clawern's `haltCheckHook` / heartbeat / 5-min auto-halt as design reference. |
| **R6 — Contextual** | **Not yet** | No phase-modulated tool access. Inference Tier is a resource-class boundary, not a workflow-phase boundary. M3 Playbook execution and M4 autonomous flows are where this register attaches. |

**Headline:** 2 of 6 fully, 2 partial, 2 deferred-with-architectural-commitment. The two "not yet" registers are missing not because LQ.AI chose normative-only — they are missing because the surfaces they restrain (autonomous loops, phase-aware tool access) do not yet exist. Pre-building the brakes for a vehicle that isn't on the road is exactly the kind of premature abstraction the CLAUDE.md ethos warns against. The right time to land R5 and R6 is when M4 starts; the right time to land R3-for-agent-handoffs and the agent-tool-grant facet of R2 is when M3's Playbook executor lands.

---

## 2. Proposed PRD edits and new DE entries (the actual work)

Six discrete changes, sequenced. Land them in this order — earlier items inform later ones.

### 2.1. New §1.8.X — Boundary-register posture (PRD §1.8 addition)

**Where:** add a new subsection at the end of §1.8 Security Posture, before the "Detailed cross-cutting security and compliance concerns are covered in §5…" closer paragraph.

**Why §1.8:** the six-register catalog is a posture statement (how LQ.AI restrains agent behavior across consequence classes), not a capability spec. It belongs with the other posture commitments — Inference Choice Spectrum, source verifiability, OpenSSF Scorecard.

**Proposed text:**

```markdown
**The boundary-register catalog as the framework for restraint.** A useful framing of professional-services agent design, articulated by Dazza Greenwood in May 2026, classifies the restraints a serious agentic legal system needs into six registers — three describing *how* a boundary is enforced (prompt-and-workflow, capability/tool-grant, code) and three describing *what else needs restraining* once autonomy exists (economic, temporal, contextual). LQ.AI adopts this catalog as the organizing framework for its boundary-enforcement work and tracks each register's state in `docs/security/boundary-registers.md` (per DE-266, M2 deliverable). The catalog is expected to grow as community practice matures; the goal is not to ship "six of six" as a marketing claim but to make every register's state — implemented, partial, deferred-with-commitment, or rejected-with-reasoning — verifiable in source. Today the project ships R1 fully, R2 in an adapted form (the Inference Tier model is a capability boundary on inference path rather than on per-agent tool grants), R3 at the gateway and Citation Engine layers (the agent-handoff facet lands with the Playbook executor in M3), and partial R4. R5 and R6 attach to the autonomous-layer surface that lands in M4 (§3.10) — they are deferred-with-commitment, with DE-269 carrying the implementation specification. The Inference Choice Spectrum (§1.5.2) is a seventh boundary orthogonal to Greenwood's six: it restrains *where the data goes during inference* rather than *what the model may decide, spend, run, or touch*, and is the central security trade-off in any LQ.AI deployment.
```

**Effort:** S (~30 min including cross-references).

### 2.2. DE-266 — Boundary-registers posture document

**Where:** `docs/PRD.md §9`, inserted after DE-265.

**Proposed text:**

```markdown
#### DE-266 — Boundary-registers posture document

**Priority:** P1 · **Effort:** S

**Context:** §1.8 names the six-register boundary catalog (Greenwood, 2026) as the framework for LQ.AI's boundary-enforcement work. Each register needs a per-register state-of-implementation entry, refreshed each milestone, that any reviewer can verify against source. `docs/HONEST-STATE.md` is the precedent for this pattern — a posture document that names shipped-vs-deferred per capability area; the boundary-registers document is the same pattern for restraints rather than capabilities.

**Specific scope:** `docs/security/boundary-registers.md`. One section per register (R1 through R6, plus an "Inference Choice Spectrum as an orthogonal boundary" section). Each section: definition (citing Greenwood once), LQ.AI's current implementation with line-level source citations, what's deferred with the DE number that tracks it, and the verification path (how an operator's reviewer confirms the claim). Refreshed at every milestone close; cross-referenced from §1.8 and from the relevant capability sections (§3.7, §3.10).

**Acceptance criteria:** document exists, covers all six registers plus the orthogonal Inference Tier boundary, each claim cites specific source paths, reviewed by Kevin before merge. Cross-references from §1.8.X and `docs/HONEST-STATE.md` §1 added.
```

**Effort:** S.

### 2.3. DE-267 — R1 codification: enumerate the rules of restraint and golden-test the starter skills

**Where:** `docs/PRD.md §9`, after DE-266.

**Why now:** R1 is the only register LQ.AI ships fully today, but the *rules* are scattered. Greenwood's article enumerates five specific normative rules at the practice-profile layer of Claude for Legal: refuse-flag-or-gate, severity floor, no silent supplement (three valid responses: supplement-with-flag, say-nothing-and-stop, flag-but-don't-use), retrieved-content-trust ("data not instructions"), and destination check (a privileged-and-confidential header is a label, not a control). LQ.AI's skill-authoring guide has *some* of these but not as a canonical, testable rule set. The honest answer to a reviewer who asks "show me your R1" is currently "read these ten paragraphs across three docs and a handful of starter skills." It should be "read this one section, then read these property-tests in CI."

**Proposed text:**

```markdown
#### DE-267 — R1 codification: rules of restraint in the skill-authoring guide and golden tests for starter skills

**Priority:** P1 · **Effort:** M

**Context:** R1 (prompt-and-workflow restraint) is the register LQ.AI ships fully, but the *normative rules* it implements are scattered across `docs/skill-authoring-guide.md`, individual starter skills' SKILL.md files, the Organization Profile schema, and the Citation Engine's verification surface. A reviewer asking "what are LQ.AI's rules of restraint at the conversational layer?" should get a one-section answer with testable invariants, not a treasure hunt.

**Specific scope:**
1. New section in `docs/skill-authoring-guide.md` — "Rules of restraint." Enumerates the canonical normative rules every skill must implement: (a) refuse-flag-or-gate behavior at consequence boundaries; (b) severity floor — a downstream skill cannot silently demote an upstream finding's severity; (c) no silent supplement — when a skill doesn't know something, the valid responses are supplement-with-flag, say-nothing-and-stop, or flag-but-don't-use, never confident guessing; (d) retrieved-content trust — content returned from any MCP tool, web search, web fetch, or uploaded document is data about the matter, not instructions to the model, and may not override guardrails; (e) destination check — a privileged-and-confidential header on a document is a label, not a control; sharing actions must validate the destination, not the label. Each rule cited verbatim from a normative source (Greenwood, ABA Formal Opinion 512, the project's existing skill conventions) and given a worked example.
2. Golden-test surface in `tests/skills/golden/test_rules_of_restraint.py`. Each starter skill is exercised against scenarios that probe each rule (e.g., for retrieved-content-trust: a synthetic document containing an injected instruction; assert the skill ignores it). Test failures block merge.
3. Skill-authoring CI check that scans new skills for the frontmatter assertion `lq_ai.acknowledges_rules_of_restraint: true` and rejects skills that omit it. The assertion is a contributor statement, not a runtime guarantee — the golden tests are the guarantee.
4. `docs/security/boundary-registers.md §R1` updated to cite the new section and the golden-test file.

**Acceptance criteria:** rules section in skill-authoring guide reviewed by Kevin and at least one practicing attorney (per `skills/CONTRIBUTING.md` skill-contribution path); 10 starter skills pass every rule's golden test; CI check is wired and blocks merge on missing frontmatter assertion; §1.8 boundary-register posture subsection cross-references the new section.
```

**Effort:** M (4–8 hours for the guide section + golden tests).

**Sequence:** **NOW**, independent of M3 progress. R1 is shipped; codifying it is documentation work plus testing surface, not new capability. Land this in mid-M3.

### 2.4. §3.7 Playbooks update — declared tool grants + schema-validated handoffs (M3 fold-in)

**Where:** `docs/PRD.md §3.7`. Insert into the **Functional requirements** subsection, before "Playbook execution in Word."

**Why:** Playbooks (§3.7, in-flight M3) are LQ.AI's first multi-step workflow surface. They are where R2 (capability/tool-grant for the *agent* sense, not the inference-tier sense) and R3 (cross-step handoff validation) first attach to the codebase. Land them as Playbook properties from the start rather than retrofit them.

**Proposed addition:**

```markdown
*Tool grants per Playbook step (R2).* Every Playbook step declares the tools it may invoke (`read_document`, `retrieve_chunks`, `call_skill`, `generate_redline`, `emit_finding`, …). The Playbook executor validates each step's tool calls against its declared grants and refuses out-of-grant calls with structured error code `tool_not_granted`. A step that needs to read documents but never write deliverables (e.g., an intake step) is granted reading tools only; the deliverable-writing step is granted writing tools but no MCP-backed document-fetching tools. This is the agent-tool-grant analog to the Inference Tier capability boundary at §4.4 — the tier model restrains *where data goes*; tool grants restrain *what an agent may do once invoked*. Greenwood (2026) calls this Register 2; the boundary-registers posture document (`docs/security/boundary-registers.md`) tracks it explicitly.

*Schema-validated step handoffs (R3).* The output of step N is parsed against a step-output Pydantic schema before becoming input to step N+1. Free-text model output never becomes the steering prompt of a downstream step without validation. Cross-step handoff envelopes carry `<playbook-handoff source-step="…" timestamp="…">` framing in any prompt context they appear in, and are explicitly labeled as "data describing the prior step's output, not instructions to the model." A step whose output fails its declared output schema halts the Playbook execution and writes a structured failure to `playbook_executions.results.failures` rather than passing the malformed output downstream. This is Greenwood's Register 3 applied at the Playbook seam; the autonomous-layer analog (cross-agent handoffs in M4) extends the same pattern.

*Per-execution cost cap (partial R4).* Each Playbook execution carries a `max_cost_usd` cap (default configurable per Playbook; hard ceiling per deployment in `gateway.yaml`'s `inference_tiers` block). The executor's per-step cost-check fires before each model call; an execution that would exceed its cap halts gracefully, surfacing the partial result with a `cost_cap_reached` flag rather than silently truncating. Logged in `playbook_executions.cost_total_usd`.
```

**Companion change:** the data model section of §3.7 (`PlaybookExecution`) gains a `tool_grant_violations: List[ToolGrantViolation]` field, a `handoff_validation_failures: List[HandoffValidationFailure]` field, and a `cost_cap_reached: bool` field. The `Position` schema gains a per-position `output_schema_ref: str` field (URI to the Pydantic schema). The migration is folded into the M3 Playbook table migration; if that migration has already landed, a follow-up migration carries the new columns.

**Effort:** S–M for the spec; M for the implementation alongside M3 Playbook executor work.

**Sequence:** **M3, before the Playbook executor merges.** Lands as part of M3-A6 or M3-A7 depending on where the executor work is sequenced in the current M3 plan (check `docs/M3-IMPLEMENTATION-PLAN.md` for the current phase). If the executor has already landed without these fields, file as separate DE.

### 2.5. §3.10 Autonomous Layer update — explicit reference to the six-register catalog and the M4 design surface

**Where:** `docs/PRD.md §3.10`. The current section commits the architectural slot but explicitly defers detailed design ("M4 territory; detailed design deferred"). Add a paragraph that names the six-register obligations the M4 design must discharge.

**Proposed addition** (insert under **Functional requirements**, after the existing bullet list):

```markdown
*Boundary-register obligations for autonomous flows (M4 design surface).* The autonomous layer is the LQ.AI surface where Registers 4–6 (Greenwood 2026, see §1.8) first attach to the codebase. M4 design must discharge each: a per-session hard cost cap with halt-on-overrun (R4, DE-269); an external halt switch checked before every tool call, with auto-halt on idle (R5, DE-269); per-workflow-phase tool-grant modulation that strips intake-time tools at ethics-gate or delivery time (R6, DE-269). The design study comparing Clawern's specific implementations (Lavern's autonomous-mode pipeline) to LQ.AI's planned approach is tracked by DE-265 Phase 1; the design-influences ADR it produces is the input to the M4 implementation plan. The boundary-registers posture document (`docs/security/boundary-registers.md`) tracks each register's M4 implementation against acceptance criteria.
```

**Effort:** S.

**Sequence:** lands with DE-266 (the posture document) since they cross-reference each other.

### 2.6. DE-269 — Autonomous-layer restraints: cost caps, halt switch, dynamic permissions (M4 fold-in)

**Where:** `docs/PRD.md §9`, after DE-267.

**Why a separate DE rather than absorbed into M4 scope:** the three Tier-2 registers (R4, R5, R6) are independently scoped enough — and have concrete prior art in Lavern — that they deserve their own implementation specification rather than burial inside a single M4 catchall. They also have a near-equal claim to being implementation requirements (the M4 plan should treat them as load-bearing) and design-study outputs (the ADR from DE-265 Phase 1 names tradeoffs Kevin should review before implementation starts). Splitting them into a DE lets the implementation specification mature in parallel with M4's broader design work.

**Proposed text:**

```markdown
#### DE-269 — Autonomous-layer restraints (R4 economic, R5 temporal, R6 contextual)

**Priority:** P1 · **Effort:** L (folds into M4; tracked as a discrete unit so the implementation specification can mature before M4 design freezes)

**Context:** The autonomous layer (§3.10, M4) is where Registers 4–6 of the boundary-register catalog (§1.8) first attach. Lavern (per DE-265) provides the most concrete public prior art: `cost-tracker.ts` enforces a $5-default per-session budget; `haltCheckHook` ("the red button") fires before every tool call and respects an external halt signal, with five-minute idle auto-halt; dynamic permissions strip search/read tools at the ethics gate and delivery phases. LQ.AI's M4 design must discharge each register; the implementation specification below is the concrete bar, derived from the design-influences ADR that DE-265 Phase 1 produces.

**Specific scope:**

1. **R4 — economic.** Per-autonomous-session `max_cost_usd` cap, declared at session creation, defaulting to a per-deployment value in `gateway.yaml` (suggested initial default $5, matching Lavern's posture). Before every tool call the executor checks projected cost against remaining budget; if the call would exceed the cap, the session halts with a `cost_cap_reached` final state. Per-tool cost estimates use the rolling-average mechanism already shipped in M2-E2. Cost is logged per-session in `autonomous_sessions.cost_total_usd`.

2. **R5 — temporal.** Liveness primitive `autonomous_sessions.halt_state` (enum: `running`, `halt_requested`, `halted`, `paused`). Before every tool call, the executor reads `halt_state`; if `halt_requested`, the executor transitions to `halted` and writes the partial state to the session record. Operators halt sessions via `POST /api/v1/autonomous/sessions/{id}/halt` (UI button surfaced in the autonomous-layer dashboard). A session idle for more than `idle_halt_minutes` (suggested default 5, matching Lavern) auto-transitions to `paused` and then `halted`. A halted session's next-attempted tool call fails fast.

3. **R6 — contextual.** Workflows declare phases (`intake`, `analysis`, `drafting`, `ethics_review`, `delivery`) and per-phase tool grants. The executor's current-phase row gates each tool call: a session in `ethics_review` phase with a search-tool grant only at `intake` phase has the search tool stripped at runtime. Phase transitions are explicit (declared in the workflow definition) and audited (`audit_log.action = autonomous_session.phase_transition`).

4. **Posture-document update.** `docs/security/boundary-registers.md` §R4 / §R5 / §R6 updated to reference the new tables, endpoints, and configuration; "deferred" status updated to "shipped" with line-level citations.

**Dependencies:** §3.10 Autonomous Layer scaffolding; the DE-265 Phase 1 ADR; the M2 cost-tracking infrastructure (`inference_routing_log.cost_usd`, M2-E2 rolling-average estimator).

**Acceptance criteria:** all three registers implemented per the spec; integration tests exercise each (a session that tries to overspend halts; a session that receives an external halt signal stops on its next tool call; a session in `ethics_review` cannot invoke a tool granted only at `intake`); posture document refreshed; cross-references from §3.10 and §1.8 added.
```

**Effort:** L (folds into M4; the implementation specification is the M4-design-time deliverable; the implementation is part of M4 scope).

**Sequence:** the DE entry lands now (this proposal). The implementation lands with M4.

### 2.7. DE-268 — `orchestrate.py`-equivalent for autonomous multi-agent flows (M4 fold-in; deferred-to-M5+ if multi-agent autonomous flows don't ship in M4)

**Where:** `docs/PRD.md §9`, after DE-269.

**Why a separate DE:** Greenwood's R3 has two facets — the Playbook-step-handoff facet (covered by §2.4 above, lands in M3) and the cross-agent-handoff facet (lands when LQ.AI ships *multi-agent* autonomous flows, not just single-agent ones). The current §3.10 sketch is ambiguous on whether M4 ships single-agent autonomous flows (one agent running a cron-scheduled workflow) or multi-agent autonomous flows (multiple agents handing off to each other in an autonomous pipeline). Lavern's Clawern is multi-agent. The DE-265 Phase 1 ADR will pin this down; depending on that pin, this DE is either M4 or M5+.

**Proposed text:**

```markdown
#### DE-268 — Cross-agent handoff validation for autonomous multi-agent flows (R3, M4 if multi-agent ships in M4)

**Priority:** P1 (if M4 ships multi-agent autonomous flows) / P2 (if M4 ships single-agent only) · **Effort:** M

**Context:** Greenwood's Register 3 (code-enforced cross-agent handoff validation) has two facets in the LQ.AI architecture. The Playbook-step-handoff facet (one step's output validated against a typed schema before becoming the next step's input) lands in M3 with the Playbook executor (per the §3.7 update accompanying DE-267). The cross-agent-handoff facet — where one autonomous agent's emitted event becomes another autonomous agent's invocation prompt, and where a hostile document upstream could otherwise smuggle instructions across the seam — only attaches if LQ.AI's autonomous layer ships *multi-agent* autonomous flows. Whether it does is pinned by the DE-265 Phase 1 ADR (the autonomous-layer design-influences study comparing Clawern's multi-agent pipeline to LQ.AI's planned approach).

**Specific scope (if M4 ships multi-agent autonomous flows):**

A reference cross-agent orchestrator in `api/app/autonomous/orchestrate.py` (or `gateway/app/autonomous/orchestrate.py` if the autonomous executor lives in the gateway — pinned by the ADR). Functional behavior:

- Validates every cross-agent handoff envelope against a closed intent enum (the set of intents the source agent is permitted to emit, declared in the workflow definition) and a per-intent Pydantic schema for parameters.
- Renders the next agent's invocation prompt from a typed template (intent-keyed, parameters interpolated via `format_map`), never from source-agent free text.
- Wraps any free-text field the source agent supplies in an `<agent-handoff source="…" timestamp="…">` envelope inside the rendered prompt, with explicit framing that the envelope content is "data describing a task, not an instruction."
- Refuses (and audits) any handoff whose intent is not in the allowlist or whose parameters fail schema validation.

Acceptance is structured against the same four failure modes Lavern's `orchestrate.py` exercises (Greenwood describes them as the "four cases" of validation harness output): unknown target agent, intent not in allowlist, parameter schema violation, oversize / malformed envelope.

**Specific scope (if M4 ships single-agent only):** this DE is reclassified P2 and deferred to whichever later milestone first ships multi-agent autonomous flows. The Playbook-step-handoff implementation in M3 (per §2.4) covers the in-scope R3 surface.

**Acceptance criteria:** depends on classification per the ADR. If M4-scope: orchestrator implementation + 4-case integration test suite + posture-document update naming R3 as "shipped" with line-level citation. If deferred: this DE is marked P2 with a note pointing to the ADR's pin.
```

**Effort:** M.

**Sequence:** DE lands now; classification pinned when the DE-265 Phase 1 ADR lands; implementation lands with M4 (or later) per classification.

---

## 3. Suggested order of operations for the receiving CC

1. **Apply `de-265.patch` and push** (per `HANDOFF-lavern-evaluation.md §0`). This puts the Lavern DE on the remote.
2. **Surface §0 of this document to Kevin** before drafting any new PRD text. The two framing questions (vocabulary attribution and "six is not load-bearing") need his call.
3. **Draft DE-266 (posture doc) and the §1.8 addition first.** They are the framework everything else hangs off; if Kevin redirects framing in §0, those edits change shape and the downstream DEs may need re-scoping.
4. **Draft DE-267 (R1 codification) next.** It's pure documentation + golden tests, doesn't depend on M3/M4 capability work, and is the highest-priority register-completion work because R1 is shipped-but-undocumented.
5. **Draft the §3.7 Playbooks updates (§2.4 above) third.** These need to land *before* the M3 Playbook executor merges. Check `docs/M3-IMPLEMENTATION-PLAN.md` for current M3 phase; if the executor is already in code review, these become a follow-up DE rather than a §3.7 edit.
6. **Draft DE-269 and DE-268 last.** They are M4-implementation specifications; the DE entries land now to lock the design surface; implementation lands with M4. Both DEs reference the DE-265 Phase 1 ADR; that ADR is the prerequisite for finalizing them.
7. **Draft the §3.10 update (§2.5 above) alongside DE-269.** They cross-reference.

Each step lands as a separate commit on `claude/evaluate-lavern-integration-YMMJi`. Push after each. PR-ready when all are landed.

**Suggested PR title:** `DE-265–269: Lavern design study and boundary-register roadmap — autonomous layer, Playbook handoffs, R1 codification`.

**Suggested PR body:** restates §1 (the honest count), links to DE-265 and the new DE-266 through DE-269, restates the M3/M4 sequencing, calls out the two §0 framing questions for reviewer (Kevin) attention.

---

## 4. What this proposal explicitly does not do

Per the conservative-posture rule, named here so a future reader can verify scope was held:

- **No implementation in this PR.** The Playbook executor changes (§2.4) are PRD updates only; the implementation lands when the M3 executor merges. DE-269's three registers are implementation specifications; the implementation lands with M4.
- **No re-scoping of existing milestones.** M1 is shipped. M2 is shipped. M3 is in flight; the Playbook updates fold in but don't lengthen M3 (the work that wasn't going to happen anyway becomes the work that does happen, with the brakes added). M4 is committed but not started; DE-269 and DE-268 are inputs to M4 design.
- **No new vocabulary outside Greenwood's catalog.** The PRD already has Inference Tier, Inference Choice Spectrum, conservative posture, transparency posture, etc. Adding "boundary registers" extends a small vocabulary; adding more terms beyond that hits diminishing returns. The boundary-register catalog is a framework, not a brand.
- **No marketing claims.** The honest count is 2 of 6 fully, 2 partial, 2 deferred-with-commitment. The §1.8 text in §2.1 reflects that count and does not state "LQ.AI implements six registers." If Kevin wants stronger language *after* DE-267 / DE-269 implementation work lands, the PRD edit comes then.
- **No assumption that Greenwood's six is the final catalog.** §0's recommendation is to treat the catalog as a living artifact. The §1.8 text in §2.1 explicitly names this ("The catalog is expected to grow as community practice matures").

---

*Drafted in the Claude Code web session on 2026-05-20 as a companion to the Lavern evaluation handoff. Receiving CC: read §0 first, surface the framing questions to Kevin, then proceed in the order of §3. Source of the six-register framework is Dazza Greenwood's May 2026 article "The Most Interesting Thing in Claude for Legal Is the Lawyer/Agent Boundary" — Kevin has the draft.*
