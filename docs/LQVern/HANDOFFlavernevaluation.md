# Session handoff — Lavern evaluation and integration into the LQ.AI roadmap

> **Audience:** Claude Code running on **a different machine from the one where this work was drafted**. The originating session was a Claude Code web session (Anthropic-hosted ephemeral container) that could not push to the remote due to GitHub App permission scope. That container's local git state is unreachable from here — everything needed to continue is in this document and the accompanying `de-265.patch` file, both of which Kevin will hand to you.
>
> **Branch:** `claude/evaluate-lavern-integration-YMMJi` — created in the web session, **never pushed to the remote**, and the web session's container is gone. You will create the branch fresh on the receiving machine.
>
> **External reference:** [AnttiHero/lavern](https://github.com/AnttiHero/lavern) — Apache 2.0, TypeScript/Fastify/SQLite, open-source multi-agent legal review system.

---

## 0. What's already done (and how to recover it on a fresh machine)

A web Claude Code session evaluated Lavern against the LQ.AI PRD and roadmap, drafted DE-265 in `docs/PRD.md`, and committed it as `4bf2c0c` on `claude/evaluate-lavern-integration-YMMJi`. The push was blocked: the git proxy returned 403 (`Permission to LegalQuants/lq-ai.git denied to Kevin-Tucuxi`) despite Kevin-Tucuxi being admin on the repo, and the GitHub MCP returned `Resource not accessible by integration` (Claude GitHub App installation scope on this repo is insufficient). Because the web session's container is ephemeral, the commit object `4bf2c0c` exists nowhere except inside that (now-discarded) container — it cannot be fetched from anywhere on the network. The substantive content of the commit travels with this handoff as `de-265.patch`.

**To recover the work on the receiving machine** (which has its own clone of `legalquants/lq-ai` — or needs one):

```bash
# 1. If you don't yet have a clone on this machine:
git clone https://github.com/legalquants/lq-ai.git
cd lq-ai

# 2. If you do, make sure you have the latest main:
cd /path/to/lq-ai
git fetch origin
git checkout main
git pull origin main

# 3. Create the branch fresh, off origin/main (matches what the web session did):
git checkout -b claude/evaluate-lavern-integration-YMMJi origin/main

# 4. Apply the patch Kevin handed you alongside this document.
#    On most systems Kevin will have downloaded it to ~/Downloads/de-265.patch
#    or similar — adjust the path to wherever the file actually lives:
git am ~/Downloads/de-265.patch

# 5. Verify the result:
git log --oneline -2            # should show your new commit on top of origin/main
git diff origin/main -- docs/PRD.md | head -50

# 6. Push to the remote and continue with §5 of this handoff.
git push -u origin claude/evaluate-lavern-integration-YMMJi
```

**If `git am` fails** (e.g., because Kevin's local git identity differs from the patch's, or the patch is malformed in transit), fall back to recreating the commit manually: the full text of DE-265 is reproduced verbatim in §3 below — open `docs/PRD.md`, find the line "### How to add to this list" inside §9, paste DE-265's content immediately before that subsection (after DE-264's "**Acceptance criteria — Phase A:** …" closing line), and commit with the same message:

```
Add DE-265: Lavern as design reference for Autonomous Layer, ensemble, MCP
```

Either path lands the same final state. Then push and proceed with §5–§9 below.

---

## 1. What Lavern is (factual summary)

From `https://github.com/AnttiHero/lavern` (README + repo metadata, observed 2026-05-20):

- **License:** Apache 2.0.
- **Stack:** TypeScript (~93% of LOC), React dashboard, Fastify API with WebSocket support, SQLite (FTS5 for full-text), Docker deploy. 1,677 tests across 105 files.
- **Tagline:** "An agentic law firm" emphasizing evidence-based reasoning over single-pass LLM answers.
- **Composition:**
  - 67 specialist agent prompts (59 specialists + 8 orchestrators) coordinated through an adversarial debate protocol.
  - Three-layer verification pipeline: evaluator gates, adversarial debate, 10-pass verification (context, clarity, accuracy, risk, …).
  - 21 MCP tools (debate, scoring, verification, knowledge management).
  - 9 workflow templates ranging from single-specialist consultation to full adversarial review.
  - 5 bundled legal datasets: CUAD, MAUD, ACORD, UNFAIR-ToS, LEDGAR.
  - Persistent "precedent board" tracking recurring patterns across documents.
  - Mandatory human approval gates before critical findings deliver.
- **Operating modes:**
  - **Interactive** — web dashboard, real-time agent observation, human gates.
  - **Clawern (autonomous)** — 30-min heartbeat monitoring, email/Telegram alerts, precedent accumulation, cost forecasting.
  - **EU mode** — routes through Mistral instead of Anthropic.
- **Providers:** Anthropic, Mistral (EU), local Ollama.
- **Stated limitations** (from the README itself): no independent public benchmark; no vector/dense retrieval for knowledge search; no durable task queue; counsel deliveries range 5–10 minutes.

---

## 2. The strategic conclusion (and why)

**Lavern is not directly integrable** into LQ.AI as code:

- **Stack mismatch.** TypeScript/Fastify/SQLite vs. LQ.AI's Python/FastAPI/Postgres/SvelteKit. Apache 2.0 permits vendoring, but the integration cost is the architecture, not the license.
- **LQ.AI's substrate is strictly stronger** for the same goals: pgvector + Postgres FTS hybrid retrieval (§3.5), char-precise deterministic citation verification (§3.3, shipped M2), Redis-backed durable task queue, OpenWebUI Pipelines framework as the autonomous substrate (§3.10).
- **Lavern's quality claims are unvalidated** — no independent benchmark. Per LQ.AI's §1.9 conservative-posture principle, claims-by-agent-count are not adopted as quality signals.

**Lavern is the closest public prior art** for several LQ.AI roadmap commitments that are currently underdesigned in the PRD:

| LQ.AI section | Lavern's contribution |
|---|---|
| §3.10 Autonomous Layer (M4) | Clawern pipeline = working pattern for the open questions in §3.10 |
| §3.8 Ensemble Verification (full-chat-path extension, deferred) | Debate-and-evaluator shape candidate |
| §8.5 M5+ MCP-client subsystem | 21-tool catalog = starting categorization |
| §3.7 Playbooks / §3.14 Tabular | Workflow-template spectrum = complexity-dial framing |

**Treatment:** design reference, not dependency. Study, write up the influences as ADRs/mini-PRDs, fold concrete increments into existing M3/M4/M5+ scope. Do not import code, do not bulk-import the 67-agent prompt corpus (skill-contribution path applies per skill per §7.5).

---

## 3. DE-265 — the entry already drafted

Committed locally as `4bf2c0c`, inserted into `docs/PRD.md` after DE-264, before the "How to add to this list" subsection of §9. **Full text below** in case the patch is unavailable:

````markdown
#### DE-265 — Lavern as design reference for the Autonomous Layer, full-path ensemble, and MCP catalog

**Priority:** P2 · **Effort:** S (this entry — design study + ADRs) plus downstream impact on M3/M4/M5+ work already scoped

**Context:** [AnttiHero/lavern](https://github.com/AnttiHero/lavern) is an Apache 2.0, TypeScript/React/Fastify/SQLite, open-source "agentic law firm" for document review. It ships 67 specialist agent prompts coordinated through an adversarial debate protocol, a 3-layer verification pipeline (evaluator gates + adversarial debate + 10-pass verification), 21 MCP tools, 9 workflow templates (single-specialist → full adversarial review), 5 bundled legal datasets (CUAD, MAUD, ACORD, UNFAIR-ToS, LEDGAR), a persistent "precedent board," and an autonomous mode ("Clawern") with 30-minute heartbeat monitoring, email/Telegram alerts, precedent accumulation, and cost forecasting. It supports Anthropic, Mistral (EU mode), and local Ollama.

Lavern is the closest public prior art for several LQ.AI roadmap commitments that are currently underdesigned in the PRD, particularly **§3.10 Autonomous Layer (M4)**, the deferred "full chat path" extension of **§3.8 Multi-Model Ensemble Verification**, the MCP tool catalog shape implied by **§8.5 M5+ MCP-client subsystem**, and a possible "complexity dial" on **§3.7 Playbooks (M3)** and **§3.14 Tabular Review (M3)**. Studying Lavern's design choices and writing them up against ours before M3/M4 design freezes is much cheaper than re-deriving the same shape from scratch.

**Stack mismatch makes direct integration uneconomical.** Lavern is TypeScript/React/Fastify/SQLite; LQ.AI is Python/FastAPI/Postgres/SvelteKit (OpenWebUI fork). Apache 2.0 permits code vendoring, but the architecture surface (sync wire formats, single-process SQLite, no vector retrieval, no durable task queue) is strictly weaker than what LQ.AI has already built or specified — re-implementing the ideas natively in the existing services is the right path. Lavern's quality claims also lack independent benchmarks; treat the design as inspiration, not as validated implementation.

**Specific overlap map.**

| Lavern feature | LQ.AI section | Treatment |
|---|---|---|
| 67 specialist agent prompts | §3.4 Skill Library | Already the model. The 67-prompt corpus is potentially seed material for community skills under `skills/community/` (DE-001, DE-219), subject to the skill-contribution path's attorney-attestation gate (§7.5 / `skills/CONTRIBUTING.md`). |
| Adversarial debate protocol with mandatory citations | §3.3 Citation Engine (shipped M2) + §3.8 Ensemble Verification (shipped narrowly on Stage 4 of Citation Engine) | LQ.AI's deterministic substring verification and char-precise offsets are stronger than Lavern's "agents must cite or be discarded." Lavern's contribution is a candidate execution shape for the deferred "full chat path ensemble" framing flagged in §3.8 — N agents debate, an evaluator gates, the user sees the disagreement structure rather than only the reconciled answer. |
| 10-pass verification (context, clarity, accuracy, risk, …) | §3.7 Playbooks (§3.7), §3.14 Tabular Review | Suggests a complexity dial on Playbook execution: single specialist → small panel → full adversarial. Worth scoping as an option on `POST /api/v1/playbooks/{id}/execute` rather than a separate capability. |
| 9 workflow templates | §3.7 Playbooks | The template taxonomy (cost vs. rigor) is a useful framing for how operators choose Playbook execution modes. |
| 21 MCP tools (debate, scoring, verification, knowledge management) | §8.5 M5+ MCP-client subsystem | Concrete prior art for tool categorization and the registration surface. Worth comparing against the MCP-client subsystem skeleton planned for M5 before that work starts. |
| Clawern autonomous mode (30-min heartbeat, alerts, cost forecast, precedent accumulation) | §3.10 Autonomous Layer (M4) | **Highest-value overlap.** §3.10 has committed the architectural slot but explicitly deferred detailed design ("M4 territory; detailed design deferred"). Lavern's Clawern is a working pattern for several of the open questions: how the heartbeat loop interacts with cost budgets, how alerts surface across email and chat, how precedent accumulation contrasts with Project context (§3.11) and user-curated memory. |
| Persistent precedent board | §3.10 vs. §3.11 | A third framing — system-curated cross-matter patterns visible to the user — that sits between Project context (user-curated, per-matter) and autonomous memory (system-curated, system-visible). Worth deciding explicitly whether M4 absorbs this, rejects it, or files it as a separate construct. |
| Bundled legal datasets (CUAD/MAUD/ACORD/UNFAIR-ToS/LEDGAR) | `docs/acceptance-testing-framework.md`; DE-237 eval harness | Useful eval corpora for the Citation Engine and Playbooks, independent of Lavern's runtime. Licensing of each dataset to be verified before any bundling. |
| EU mode (routes through Mistral) | §1.5.2 Inference Tier Spectrum + Provider Compliance Matrix | Already addressed structurally by the Tier model. Lavern's framing as a single switch is worth borrowing as UX language ("EU residency mode") even though the underlying mechanism is the same provider routing. |

**Specific scope (this DE):**

*Phase 1 — design study (before M4 kickoff; ~1 day of reading + writing):*
- Read Lavern's Clawern pipeline source (TypeScript) and write `docs/adr/00XX-autonomous-layer-design-influences.md` comparing it to the §3.10 sketch — naming what LQ.AI adopts, what it adapts, and what it rejects, with the open questions in §3.10 ("Open questions") answered or explicitly punted.
- Read Lavern's debate protocol and write a short note in §3.8 (or an ADR cross-referenced from it) on whether the "full chat path ensemble" extension should adopt the debate-and-evaluator shape; if yes, file a follow-up DE with concrete scope.
- Read Lavern's MCP tool catalog and capture the categorization in `docs/contribute/mini-prds/mcp-client-subsystem.md` (creating that mini-PRD if it does not yet exist) so the M5 design starts with prior art rather than a blank page.

*Phase 2 — feature increments (folded into existing milestones, not net-new work):*
- **M3 — Playbook execution-mode dial (§3.7).** Add `execution_mode: "single" | "panel" | "adversarial"` to the `POST /api/v1/playbooks/{id}/execute` body, defaulting to `single`. Panel and adversarial route through the same ensemble surface §3.8 already builds on. Cost preview surfaces the mode's expected token spend per §5.5. Estimated +S work on top of M3 §3.7.
- **M4 — Autonomous Layer informed by Clawern (§3.10).** No new line items; the existing M4 scope absorbs the Phase 1 ADR's conclusions. Particular focus areas: heartbeat-loop cost-budget integration; alert surface (email + in-app + optional webhook to align with §3.15 Slack/Teams Bridge once it ships); precedent-board vs. autonomous-memory disambiguation.
- **M5+ — MCP catalog seeded from Lavern (§8.5).** Phase 1 ADR's tool categorization becomes the starting catalog for the MCP-client subsystem's first iteration.

**What is explicitly out of scope:** direct code reuse from Lavern (stack mismatch); bulk import of the 67-agent prompt corpus (skill-contribution path applies per skill); adoption of Lavern's SQLite/Fastify/no-vector-retrieval architecture choices (strictly weaker than LQ.AI's existing substrate); marketing claims about agent counts or verification-pass counts as a quality signal in their own right (§1.9 conservative-posture principle).

**Acceptance criteria — Phase 1:** the autonomous-layer ADR is merged and cross-referenced from §3.10; the §3.8 follow-up note is merged and cross-referenced from §3.8; the MCP-client mini-PRD exists and references Lavern's tool catalog. **Acceptance criteria — Phase 2:** revisit when M3/M4/M5 design freezes for each milestone.
````

---

## 4. Open framing questions Kevin flagged but did not resolve

When DE-265 was drafted, four framing choices were called out for Kevin to redirect or accept. **Carry these into the next session and surface them explicitly before locking in downstream work:**

1. **Priority P2 vs. P1.** DE-265 is currently P2 (design study influencing existing committed milestones). If Kevin wants to signal "must-be-done-before-M4-design-freeze," it should be P1.
2. **Effort framing.** DE itself marked S (the design study). Phase 2 increments are folded into existing M3/M4/M5+ scope without separate hour estimates. Alternative framing: split each Phase 2 increment into its own DE so the work is trackable independently of the parent milestone.
3. **Bulk-import question on the 67-agent corpus.** Currently rejected in DE-265 as "out of scope" because the skill-contribution attestation gate (§7.5) applies per-skill. A lighter-weight alternative worth considering: bulk-port to `skills/community/lavern-port/` as a *batch* draft, with attorney attestation as a follow-up DE that gates the directory's eligibility for default-install. Decide before any port work starts.
4. **Tone on Lavern's quality claims.** Currently called "unvalidated" verbatim from the §1.9 conservative-posture principle. Soften, keep, or sharpen — Kevin's call.

---

## 5. The Phase 1 deliverables (next session's work)

The DE specifies three Phase 1 design-study deliverables. **Land them as separate commits on the same branch** (`claude/evaluate-lavern-integration-YMMJi`), each with its own short PR-ready commit message.

### 5.1. ADR — Autonomous-layer design influences from Clawern

**File:** `docs/adr/00XX-autonomous-layer-design-influences.md` (pick the next number after the highest existing in `docs/adr/`).

**Source material:** read Lavern's TypeScript source for Clawern. Specifically:
- The heartbeat loop (search the repo for `heartbeat`, `30 minute`, or the cron entrypoint).
- Cost forecasting logic (search for `forecast`, `budget`, `cost cap`).
- Alert dispatch (email/Telegram — search for `nodemailer`, `telegram`, `alert`).
- Precedent-board read/write (search for `precedent` in src/ paths).

**Structure the ADR as:**
- **Context.** Restate §3.10's stated scope and open questions verbatim (the §3.10 text already names what's deferred).
- **Decision drivers.** What §3.10 needs from the design that the current sketch doesn't yet name.
- **Considered alternatives.** Clawern-shaped (Lavern), Temporal/Celery-shaped, naive cron-job-shaped. For each, state the costs and what §3.10's open questions look like under that shape.
- **Decision.** What LQ.AI adopts from Clawern, what it adapts, what it rejects.
- **Open questions remaining.** Anything §3.10 still needs to resolve before M4 design freezes.
- **Cross-references.** Link from §3.10's "Open questions" subsection to the new ADR, and from the ADR back to §3.10 and to DE-265.

**Estimated effort:** 4–6 hours including the source-read.

### 5.2. §3.8 follow-up note on full-chat-path ensemble

**File:** edit `docs/PRD.md` §3.8 directly, OR create `docs/adr/00XX-full-chat-path-ensemble.md` and cross-reference from §3.8.

**Content:** §3.8 currently states that the "full chat path ensemble" framing is **not built** and that operators wanting it configure parallel chat sessions manually. The follow-up note evaluates whether Lavern's debate-and-evaluator shape is the right execution surface if/when LQ.AI implements the full-chat-path extension. Specifically:

- Does the debate-with-citations protocol degrade gracefully in Mode 2 (local Ollama only)? §3.8's existing fallback says it degrades to "diversified prompts on the same model" — Lavern's protocol assumes multiple distinct agent personas, which may or may not work with a single local model.
- Where does the evaluator gate live — in the gateway (where ensemble currently lives) or in the backend (where it would need to coordinate with the citation engine)?
- What does the UI show: only the reconciled answer (current §3.8 framing) or the disagreement structure (Lavern's user-facing innovation)?

**Outcome:** either land a "yes, file DE-266 with concrete scope" recommendation, or land a "no, the current §3.8 framing is sufficient and the M2 narrow scope stands" recommendation with reasoning.

**Estimated effort:** 2–3 hours.

### 5.3. MCP-client mini-PRD seeded from Lavern's tool catalog

**File:** `docs/contribute/mini-prds/mcp-client-subsystem.md`. Create if it does not exist (`ls docs/contribute/mini-prds/` to check first; the existing mini-PRD template in that directory shows the house style).

**Content:**
- Restate §8.5's commitment that the MCP-client subsystem is the integration substrate for M5+.
- Enumerate the categories of tools that the MCP-client subsystem needs to host, **seeded by Lavern's 21-tool catalog**. Group as: debate/coordination, scoring/evaluation, verification, knowledge management. Add LQ.AI-specific categories that Lavern doesn't have (matter-scoped retrieval, privilege flags, tier enforcement).
- Sketch the registration surface (config? auto-discovery? explicit registration in `gateway.yaml`?).
- Sketch the per-tool security envelope: which tier can call which tools, what audit-log fields apply, how privilege flags propagate.
- Acceptance criteria for the mini-PRD itself: "any community contributor can read this and start work on a specific tool integration."

**Estimated effort:** 3–4 hours.

---

## 6. Phase 2 — what folds into M3/M4/M5+ (NOT next session's work)

Recorded here only so the local CC instance has full context. **Do not start Phase 2 work in the same session as Phase 1 deliverables.**

- **M3 work:** add `execution_mode` field to Playbook execution. Wave-into the existing M3 plan (`docs/M3-IMPLEMENTATION-PLAN.md` — check whether Phase A/B/C/etc. has a natural slot for this, or file as a new task within M3).
- **M4 work:** the autonomous-layer ADR's conclusions inform M4 design. M4 has not started; carry the ADR's open questions into the M4-IMPLEMENTATION-PLAN drafting (whenever that begins).
- **M5+ work:** the MCP-client mini-PRD seeds the M5 build. M5 is community-driven per §8.5; the mini-PRD is the contributor brief.

---

## 7. Files in `lq-ai` the next session should read first

Roughly in priority order:

| Path | Why |
|---|---|
| `docs/PRD.md §3.10` (lines ~866–899) | Autonomous Layer scope and open questions — primary input for the ADR in §5.1 |
| `docs/PRD.md §3.8` (lines ~792–822) | Ensemble Verification current state and the "full chat path" deferral — primary input for §5.2 |
| `docs/PRD.md §8.5` (lines ~1848–1877) | M5+ Workflow Intelligence and MCP-client subsystem — primary input for §5.3 |
| `docs/PRD.md §3.7` (lines ~712–790) | Playbooks (M3) — for Phase 2 M3 work |
| `docs/PRD.md §9 DE-265` (newly added) | Self-reference; the brief for everything else |
| `docs/PRD.md §9 DE-263, DE-264` | House style for DE entries that wrap external projects |
| `docs/adr/` directory | House style for ADRs (pick the most recent for tone calibration) |
| `docs/contribute/mini-prds/` directory | House style for mini-PRDs |
| `CLAUDE.md` | Project orientation; decision-routing rules — read first if unfamiliar with the codebase |
| `docs/HONEST-STATE.md` | What's shipped vs. deferred — useful sanity check before claiming anything about current state |

---

## 8. Constraints carried forward (from `CLAUDE.md`)

The next session must obey these — they materially affected DE-265's framing:

- **Decisions are explicit, not implicit.** If a Phase 1 deliverable surfaces an architectural decision not anchored in §3.10/§3.8/§8.5, stop and ask Kevin rather than guess.
- **Don't expand scope.** Phase 1 deliverables are studies and ADRs, not implementation. Don't draft migration files, don't add API endpoints, don't start Phase 2 prematurely.
- **Surface ideas as DE-XXX.** If reading Lavern's source surfaces useful adjacencies not covered by DE-265, file them as new DE entries in `docs/PRD.md §9` rather than expanding DE-265.
- **Conservative posture extends to engineering.** Don't claim Clawern's design "works" — claim only what its source code demonstrates. The §1.9 principle and Lavern's lack of independent benchmarks both apply.

---

## 9. What to send Kevin back after Phase 1 lands

Three deliverables on `claude/evaluate-lavern-integration-YMMJi`:

1. `docs/adr/00XX-autonomous-layer-design-influences.md` (new file).
2. `docs/PRD.md §3.8` updated, OR `docs/adr/00XX-full-chat-path-ensemble.md` (new file).
3. `docs/contribute/mini-prds/mcp-client-subsystem.md` (new file).

Plus the DE-265 commit already on the branch (`4bf2c0c`).

PR title: `DE-265: Lavern design study — autonomous layer ADR, ensemble note, MCP mini-PRD`.

PR body should resolve the four framing questions in §4 above (Kevin will weigh in during review if any need adjustment).

---

*Drafted in a Claude Code web session on 2026-05-20. Hand this document plus `de-265.patch` to a Claude Code instance on a different machine (the web session's container is gone; nothing of the work survives outside these two files). The receiving machine needs its own clone of `legalquants/lq-ai` and a GitHub identity with push access to it — see §0 for the recovery procedure.*
