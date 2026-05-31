# Design — Honest alignment: docs + Learn (post-M4 close)

> **Status:** approved 2026-05-30. **Next:** implementation plan (writing-plans).
> **Goal in one line:** every *current-facing* artifact honestly reflects what is actually built, and every shipped capability is represented in the Learn tab.

---

## 1. Why

M4 (the Autonomous Layer) is code-complete and acceptance-passed, but the current-facing documentation and the Learn-tab visualizations have drifted from the codebase across M1→M4. Concrete known drift:

- `docs/HONEST-STATE.md` still says "M3 and M4 not yet started in source" and cross-references autonomous at §3.11/§3.12 (now Projects/Org-Profile; autonomous is §3.10).
- `web/static/learn/playgrounds/data-residency.html` claims anonymization is "not running" — false (M2 shipped it).
- `docs/security/boundary-registers.md` carries R4/R5/R6 as not-yet-shipped; PRD §3.10 describes the autonomous layer as forward-looking.
- Several shipped capabilities (intake-bridges, the autonomous brakes + four primitives, etc.) may have no Learn visualization at all.

The project's founding principle is **transparency** (PRD §1.3). Documentation and the Learn tab are part of the user-facing surface; when they overstate or understate reality they violate that principle. This effort reconciles them to ground truth.

## 2. Scope

### 2.1 In scope — reconcile to *current* reality

**Anchor (done first):**
- `docs/HONEST-STATE.md` — rewritten from a ground-truth codebase read. Becomes the **single source of truth** the rest of the sweep conforms to.

**Docs:**
- `README.md` (repo root)
- `docs/PRD.md` — flip shipped capabilities to SHIPPED (esp. §3.10 Autonomous Layer + the R4/R5/R6 brake registers); reconcile section cross-refs; file deferred-enhancements DE-325, DE-326, DE-327 in §9.
- `docs/architecture.md`
- `docs/db-schema.md` (verify against migrations 0001→0045)
- `docs/observability.md`
- `docs/security/boundary-registers.md` — R4/R5/R6 → SHIPPED with live citations.
- Per-feature docs: `docs/citation-engine.md`, `docs/playbooks.md`, `docs/tabular-review.md`, `docs/word-addin.md`, `docs/intake-bridges.md`, `docs/skill-authoring-guide.md`, `docs/quickstart.md`.
- **New:** `docs/autonomous-layer.md` — the M4 feature doc (executor phases, the guarded-tool-call chokepoint, R4/R5/R6 brakes, the four primitives, receipts, opt-in).
- **Current handoff only:** align the active M4 handoff (`docs/LQVern/HANDOFF-2026-05-29-m4-real-executor-mid-execution.md`) to HONEST-STATE. (Already largely current.)

**Learn tab (`web/static/learn/playgrounds/` + `web/src/routes/lq-ai/learn/`):**
- **Audit all 14 existing playgrounds** for factual accuracy against the codebase; fix every stale/false claim (e.g. `data-residency.html`). Existing: anonymization-layer, autonomous-flow, citation-engine-cascade, data-residency, otel-eval, playbook-cascade, request-lifecycle, skill-composition, skill-format, system-architecture, tabular-review, test-landscape, tier-system, word-addin-flow.
- **Audit the 4 Learn pages** (landing / how / use / build) for accuracy.
- **Build new visualizations** for shipped capabilities not yet represented. Final gap list is produced by the analysis; candidate gaps to confirm/deny: intake-bridges (Slack/Teams), the autonomous brakes (R4/R5/R6) + four primitives (watches/schedules/memory/precedent), projects/org-profile, KB hybrid retrieval.
- **Coverage bar: comprehensive** — every shipped capability ends up both honestly documented and represented in Learn.

DE filing: DE-327 = Helm/k8s worker-migration parity (the compose DE-326 fix), framed as a community-suitable ("good first issue") deferred enhancement — we do not implement it ourselves.

### 2.2 Explicitly out of scope (preserved as historical artifacts)

- All past `docs/SESSION-HANDOFF-*.md` (every one except the active M4 handoff).
- `docs/M1-IMPLEMENTATION-ORDER.md`, `docs/M1-PROGRESS.md`, `docs/M2-IMPLEMENTATION-PLAN.md`, `docs/M3-IMPLEMENTATION-PLAN.md`, `docs/M4-IMPLEMENTATION-PLAN.md`, and the `docs/LQVern/` plan/design docs.

These are point-in-time artifacts that honestly show where the project was at each development stage. They are **not** edited — retroactively rewriting them would destroy their value as a record. (Their dates make them self-evidently historical; HONEST-STATE is the canonical current-truth pointer.)

- Code changes of any kind. This is a docs + Learn-viz effort only. (Any code drift discovered is *recorded* in HONEST-STATE / filed as a DE — not fixed here.)
- The skill-inputs assembler change (Donna's request) — separately deferred to after the v0.4.0 tag.

## 3. Approach — one continuous pass, HONEST-STATE as the spine

Per the agreed structure: a single combined pass (no inter-phase approval gate), but internally ordered so it stays self-consistent.

1. **Ground-truth analysis.** Read the codebase comprehensively — `api/`, `gateway/`, `web/`, `skills/`, Alembic migrations 0001→0045, the test suites, and (critically) what is *wired and reachable* vs. stubbed/skeleton. Parallel exploration is appropriate given the breadth. The output is captured directly as the rewritten `HONEST-STATE.md`, structured as a capability map: **capability × shipped-status × which doc(s) describe it × which Learn viz covers it × any stale/false claim flagged.** This doubles as the first deliverable and the internal truth-map.
2. **Doc sweep.** Reconcile every in-scope doc against the truth-map, editing in place. Write the new `docs/autonomous-layer.md`. File the DEs in PRD §9.
3. **Learn sweep.** Audit + fix the 14 playgrounds and 4 pages; build the new viz identified in step 1. New viz follow the existing playground conventions (self-contained offline HTML, the established Learn design-system / no new color palette, honest "PLANNED" badges only where something genuinely isn't shipped).

## 4. Truth discipline (the core quality bar)

- **Every claim is verified against code before it is written.** No claim ships on memory or inference. Span attributes, audit action strings, outcome labels, receipt fields, endpoint paths, table/column names, config keys, and capability status are each grepped/read in the source.
- **Conservative honesty (PRD principle):** if something works for case A but not case B, the doc says exactly that. No overclaiming ("handles all document types") and no understating shipped work.
- **Consistency:** a capability is described the same way everywhere; HONEST-STATE is authoritative on any conflict.

## 5. Verification & delivery

- **Self-check:** after each cluster, re-grep the specific facts asserted; confirm Learn viz claims against the same source the docs cite.
- **Build check for Learn:** new/edited playgrounds load and render (the Learn build pipeline — `web/static/learn/` is served; the SvelteKit `learn/` routes pass `svelte-check`/lint where touched).
- **Commits in reviewable clusters**, not 50 micro-commits and not one mega-commit: (a) HONEST-STATE truth-map; (b) core docs (README/PRD/architecture/db-schema/observability/boundary-registers); (c) per-feature docs + new autonomous-layer.md; (d) Learn playground accuracy fixes; (e) new Learn viz. DCO `-s` + the `Co-Authored-By: Claude Opus 4.7 (1M context)` trailer per branch convention. Push both remotes (origin + tucuxi) after each cluster.
- **Branch:** this work proceeds on the **M4 branch `feat/lqvern-m4-autonomous`** — it is effectively the **M4-D2 doc-finalization** phase. Rationale: the docs must describe M4, and M4 is not yet merged to `main`; a branch off `main` would lack the code to read and cite. M4 code + honest docs + Learn viz therefore merge to `main` and tag **v0.4.0** together as one milestone. (The Helm DE-327 stays a community item; the skill-inputs change stays post-tag.)

## 6. Success criteria

- `HONEST-STATE.md` accurately maps every capability's true shipped status (M1→M4) with no "not started" lies about shipped layers.
- README, PRD, architecture, per-feature docs, boundary-registers contain no claim that contradicts the codebase; shipped capabilities read as shipped, unshipped as unshipped.
- `docs/autonomous-layer.md` exists and accurately describes the M4 layer.
- All 14 Learn playgrounds + 4 pages are factually accurate; no surviving false "not running"/"planned" claims about shipped features.
- Every shipped capability is represented by a Learn visualization (new viz built for the confirmed gaps).
- All historical artifacts (§2.2) are untouched.
- DE-325/326/327 filed in PRD §9.

## 7. Open items to resolve at plan time

- Final confirmed Learn-viz gap list (emerges from the §3.1 analysis).
- Whether `data-residency.html` / `system-architecture.html` need structural rework or just claim-fixes (decided per-file during the audit).
