# Platform Cohesion + Autonomous Operability — Design

> **Status:** Design (brainstorm output). Awaiting founder review before planning.
> **Date:** 2026-05-31 · **Branch:** `feat/lqvern-m4-autonomous` (this lands inside M4, ahead of the v0.4.0 tag).
> **Author lens:** subagent-driven ground-truth research over the six constructs + the founding docs (PRD, README, HONEST-STATE, CLAUDE.md). Every current-state claim below is source-cited in the research briefs that produced this doc.

## 1. Why this doc exists

A founder observation exposed a real gap: the M4 Autonomous Layer is shipped end-to-end (executor, brakes, receipts, dashboard) but is **effectively unreachable and unoperatable by a user** — the opt-in is buried behind a tiny settings gear, the top-tab is hidden until you find that toggle, there is no in-product education, and even once you reach it you can only point a schedule/watch at an existing skill or playbook (no way to author a task, no way to test before arming, no way to run one on demand).

Pulling that thread surfaced a larger truth: LQ.AI has **six user-facing constructs that are the same underlying thing wearing six different skins** — Skills, Playbooks, Tabular Review, Saved Prompts, Enhance Prompt, and Autonomous workflows. They are each "a prompt + attached context, optionally chained, deployed on-demand / on a schedule / on a trigger." The fragmentation is in **nomenclature and UX, not architecture** — the data model already implements the unified shape.

This doc does two things:
1. **States the organizing model** the platform should cohere around (recommendation + phased roadmap — *not* an immediate rewrite).
2. **Specifies Phase 1**, which is **built now, inside M4**: make the Autonomous Layer discoverable, learnable, and operable (including run-before-you-arm), plus a small honesty correction. Everything past Phase 1 is recommendation-only roadmap.

## 2. Grounding in the founding documents

The model below is not invented; it is **latent in the PRD and already partially implemented**:

- **Transparency is an architectural commitment, and skills are the substance.** PRD §1.3: "The skills *are* the product … Skills are not configuration; they are the substance of the product." PRD §7.1: "Skills are the canonical artifact of value." (`docs/PRD.md` §1.3, §7.1; `CLAUDE.md`.)
- **Three of the six are *already* skills-with-metadata, by explicit PRD design:**
  - **Enhance Prompt** "is *itself* a skill" (`skills/enhance-prompt/SKILL.md`; PRD §3.2).
  - **Organization Profile** is "a skill with special metadata … one extensibility surface, not two" (PRD §3.12).
  - **Tabular Review** is "mostly a new Skill output type plus a UI surface … output type is `table` not `report`" (PRD §3.14).
- **Playbooks and Autonomous *consume* skills.** Autonomous `schedule`/`watch` rows carry `skill_ref` **and** `playbook_id` targets; the executor's `ToolIntent` enum has `run_skill` and `run_playbook` as first-class intents (`api/app/autonomous/enums.py`; `api/app/schemas/autonomous.py`). The autonomous primitives "trigger a configured Playbook/skill" (PRD §3.10).
- **Saved Prompts is the off-taxonomy lightweight sibling** — "a lighter-weight alternative to skills" with a one-way promote→skill bridge (PRD §9 DE-013); it shipped in M1 but has no §3 capability section.

**Where the docs are silent:** no PRD section, ADR, or architecture doc ever names the unified model as a whole. The constructs were specified independently across milestones (M1 skills/enhance/org-profile/saved-prompts; M3 playbooks/tabular; M4 autonomous), each inventing its own data model, run-record noun, and vocabulary. The cohesion is inferable from the parts but nowhere asserted. **This doc asserts it.**

## 3. The organizing model: Skill = substrate, Deploy = axis

Two orthogonal axes.

### 3.1 Artifact axis — *what runs*

A single substrate (a prompt + declared inputs + attached context), with a complexity ladder:

```
Saved Prompt   — a skill with zero metadata (the on-ramp; promotes upward)
   ↓ promote
Skill          — prompt + inputs + context (the canonical unit)
   ↓
Playbook       — a multi-step skill applied to a single document
Tabular        — a table-output skill applied to many documents
[Enhance Prompt, Organization Profile — already skills with metadata]
```

This is a *conceptual* model: it does **not** require collapsing the tables or rewriting the executors. It says these constructs are points on one spectrum and should, over time, share vocabulary, a promotion ladder, and a deploy mechanism.

### 3.2 Deploy axis — *how it runs*

Orthogonal to the artifact. Any artifact can in principle be deployed three ways:

```
On-demand  — run it now (today: attach/apply/execute/use — fragmented verbs)
Scheduled  — cron (today: Autonomous "Schedules" only)
Triggered  — on an event, e.g. a document arriving in a KB (today: Autonomous "Watches" only)
```

**"Autonomous" is reframed as the deploy layer**, not a separate capability. The schema already proves this: a schedule/watch row *is* `(trigger) + (skill_ref | playbook_id) + (target_kb_id)` — exactly "a prompt-bearing artifact + attached context, deployed on a trigger." Today that deploy power is monopolized by the Autonomous tab; the north-star is that you can schedule/trigger an artifact from the artifact's own surface.

### 3.3 Vocabulary unification (north-star)

- **One run-record noun: "Run."** Today there are four — `playbook_executions`, `tabular_executions`, `enhance_prompt_interactions`, `autonomous_sessions`. (Conceptual target; not a code rename in this milestone.)
- **Matter == Project.** The UI says "Matters"; code/PRD say "Project" (`projects` table, route `/lq-ai/matters/[id]`). Pick one user-facing word and use it consistently.
- **Harmonized deploy verbs** (run now / schedule / add trigger) replacing attach/apply/execute/use.

## 4. Phase 1 — BUILT in M4 (this milestone, before the v0.4.0 tag)

Phase 1 is the minimum that makes the shipped Autonomous Layer genuinely usable, plus one honesty fix. It deliberately **excludes** custom free-text task authoring and a full test/dry-run harness (see §7). It reuses the existing executor and API; most of it is frontend plus one small backend spawn path.

### 4.1 Discoverability + opt-in (resolve the chicken-and-egg)

**Problem:** Autonomous is off by default → the top-tab is hidden until enabled (`tabs.ts` `isTabVisible` gates `autonomous` on `autonomousEnabled`) → the only enable path is Settings → Autonomous, reached via a small top-right gear → nothing links there → zero dashboard/onboarding/empty-state signposting (the sole in-product mention is a buried Learn→How section).

**Phase 1:**
- Add an in-product **signpost that the feature exists and how to turn it on** — surfaced where a new user actually looks (the Home dashboard / getting-started surface), pointing to the opt-in. (Exact placement decided in planning; it must not require already knowing the URL or the gear.)
- Ensure the opt-in itself is reachable from that signpost (a direct link to Settings → Autonomous, or an inline enable affordance), so enabling no longer depends on discovering the hidden gear.

### 4.2 A "Configure" / education tab inside Autonomous

- Add a tab/section in the Autonomous area that explains, in honest plain language: the **Off/On state** (off by default; what turning it off/on does); **what a Schedule is** (cron-driven run of a skill/playbook); **what a Watch is** (a run triggered when a document arrives in a chosen KB); how targets (skill/playbook) + scope (KB/matter) + the cost cap fit together; and where the results land (Sessions + receipt).
- Replace the bare one-line **empty states** on Sessions/Schedules/Watches/etc. with instructive empty-states that teach the first action.

### 4.3 Operability fixes in the create modals (low-risk, high-value)

- **Surface the per-trigger cost-cap field** in the New Schedule and New Watch modals. The cap exists in the API (`max_cost_usd` on `AutonomousScheduleCreate`/`AutonomousWatchCreate`) and is enforced (R4), but is **not exposed in the UI** today — so users can't set it and don't see the safety control.
- **Show human-readable target/KB/matter names instead of raw UUIDs** in the schedule/watch list rows (today the rows render the bare `playbook_id`/`skill_ref`/`kb_id`).

### 4.4 Run once now (test before you arm)

- Add a **"Run now"** path: spawn a one-off autonomous session for a chosen skill/playbook target (+ optional KB/matter, + cost cap), without creating a recurring schedule or watch. The user sees the resulting **Run + receipt**, then decides whether to arm it as a schedule/watch.
- This reuses the existing executor and is the lightweight "test before arming" the founder asked for. `trigger_kind='manual'` is already a defined-but-unused enum value in `api/app/schemas/autonomous.py`; Phase 1 wires the spawn path for it (a new `POST` endpoint + the matching UI), gated by the same opt-in + cost-cap + brakes as every other session. No new execution model — same `autonomous_session_job` / five-phase executor / R4-R5-R6 brakes / receipt.

### 4.5 Honesty correction (folded in with the v0.4.0 honesty work)

- The Tabular pages claim each cell is **"grounded by the Citation Engine"** (`web/src/routes/lq-ai/tabular/+page.svelte`, `.../tabular/new/+page.svelte`). In source, tabular emits **display-only synthetic citation IDs** (`uuid5(...)`) that never resolve against the M2 engine (DE-309). Correct the wording to "grounded by source-chunk references" (or equivalent honest phrasing). This is a genuine overclaim and belongs with the in-flight v0.4.0 docs-honesty work regardless of the rest of this milestone.

## 5. Phases 2+ — recommendation-only roadmap (NOT built now)

These are the doc's recommendations for subsequent milestones. They are deliberately *not* part of the M4 build.

- **P2 — Deploy-from-anywhere.** Add "Schedule…" / "Add trigger…" / "Run now" actions on the **Skills, Playbooks, and Tabular** surfaces, back-ended by the existing autonomous schedule/watch/manual seam — so a user can deploy an artifact from the artifact's own page, not only from the Autonomous tab. Add **Tabular as a deploy target** (today it is the one artifact absent from the autonomous target seam — schedule/watch only accept `skill_ref`/`playbook_id`).
- **P3 — Run-record + nomenclature unification.** Converge run-record naming on "Run"; reconcile Matter/Project; harmonize deploy verbs. Likely an ADR + staged migration; user-facing first, code/table names later (or never, if cost outweighs benefit).
- **P4 — Artifact ladder + input plumbing.** Make the Saved Prompt → Skill → Playbook promotion ladder explicit and bidirectional where it makes sense; **close DE-328** (skill inputs collected by the UI are silently dropped for non-templated skills) so the "inputs" half of the substrate actually reaches the model.
- **P5 — (optional, boldest) Umbrella IA.** If tab sprawl becomes a problem, collapse Skills/Playbooks/Tabular/Saved-Prompts/Autonomous into a smaller set (e.g. a "Workflows" surface with artifact sub-types + deploy modes, and a "Runs" surface). Largest IA churn; recommended only as a deliberately-phased end-state, not a near-term move.

## 6. The nomenclature evidence (for the strategy section of the doc)

The research produced a construct × {UI term, doc term, code term} matrix and a deploy-mode matrix. Key inconsistencies the doc will cite:
- **"Skill" is overloaded:** three constructs *are* skills but are never called skills in the UI; two more (Playbook, Saved Prompt) are adjacent "reusable prompt artifacts" with no shared vocabulary.
- **Four run-record nouns** for one concept (execution/session/interaction/run).
- **Matter (UI) vs Project (code/PRD)** — same construct, two names.
- **Deploy modes are monopolized by "Autonomous"** and named inconsistently; you cannot schedule a skill from the Skills tab.
- **Chaining vocab differs per construct** (phase / node / step).

## 7. Scope boundaries (YAGNI)

**In this milestone (Phase 1):** discoverability/opt-in signposting; Configure/education tab + empty-states; cost-cap field + readable names in modals; Run-now; the Tabular honesty fix.

**Explicitly NOT in this milestone:**
- Custom free-text **task/instruction authoring** for autonomous runs (targets stay: an existing skill or playbook).
- A full **test/dry-run harness** beyond Run-now (Run-now *is* the v1 "test").
- The **umbrella IA** rewrite (P5).
- **Renaming** tables / run-records / `trigger_kind` values in code, or the Matter/Project code rename (P3 — recommendation only).
- Adding **Tabular as a deploy target** (P2).

## 8. Success criteria for Phase 1

A new user, starting from a fresh login, can without prior knowledge:
1. **Discover** that the Autonomous Layer exists and **turn it on** (no need to know the gear or the URL).
2. **Understand** what a Schedule vs a Watch is and what to pick, from in-product education.
3. **Set a cost cap** and **see readable target names** when creating a schedule/watch.
4. **Run a skill/playbook once on demand** and inspect the resulting Run + receipt **before** committing to a schedule/watch.
5. Encounter **no overclaim** (the Tabular Citation-Engine wording is corrected).

The conceptual model (§3) is delivered as a *written, founder-approved strategy* with a phased roadmap — its near-term obligation is only Phase 1.

## 9. Open questions for planning

- Exact placement of the discoverability signpost (Home dashboard card vs getting-started checklist vs a global hint) — decided in planning against the existing Home components.
- Whether the "Configure/education" surface is a new sub-tab of Autonomous or an enhanced landing on the existing Sessions page.
- The Run-now endpoint shape (`POST /autonomous/sessions` with a manual body vs a dedicated `/autonomous/run-now`) — chosen in planning to fit the existing `api/app/api/autonomous.py` conventions and the opt-in/cost-cap gating.
