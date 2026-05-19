# Session Handoff — 2026-05-18 — M3 Phase 0 complete + Phase A halfway → M3-A4 kickoff next

> **Purpose:** Context transfer for the M3-A4 session. **M3 Phase 0 is complete** (3 PRs landed on `m3-development`); **Phase A is 3-of-6 done** with M3-A1, M3-A2 merged + M3-A3 in flight. The next session opens M3-A4 — Playbook execution UI in the web app. This handoff captures everything M3-A4 needs without re-reading 6 PRs from scratch.
>
> Read time: ~10 minutes. Decisions Kevin already made (with context): §3 + §5.

---

## 1. State at handoff

### Branch state

| Branch / Tag | SHA | Meaning |
|---|---|---|
| `main` | `7b20746` | M3 plan + M3-0.1 + this handoff (when merged) |
| `m3-development` | `d08bd51` | Phase 0 (3 PRs) + Phase A M3-A1 + M3-A2; M3-A3 merges next |
| `v0.2.0` (tag) | `8a1b3fc` | M2 release point; unchanged |

`m3-development` is **5 commits ahead of `main`** (the 5 listed in §2 below). The convention from M2 holds: intermediate branches live on `origin` only; mirror sync to `tucuxi` happens at tag time.

### PR state at handoff

| PR | Title | Branch | Status |
|---|---|---|---|
| #44 | M3 implementation plan | `docs/m3-implementation-plan` | Merged to main |
| #45 | M3-0.1 — DE-283 login UX | `m3-0-1-de-283-login-ux` | Merged to m3-development AND main |
| #46 | M3-0.2 — DE-277 citation chunk-boundary | `m3-0-2-de-277-citation-chunk-boundary` | Merged to m3-development |
| #47 | M3-0.3 — DE-276 ingest observability | `m3-0-3-de-276-ingest-observability` | Merged to m3-development |
| #48 | M3-A1 — Playbook substrate | `m3-a1-playbook-schema` | Merged to m3-development |
| #49 | M3-A2 — Playbook executor | `m3-a2-playbook-executor` | Merged to m3-development |
| #50 | M3-A3 — NDA built-ins | `m3-a3-nda-playbook` | **Open** as of this handoff |
| (this PR) | M3-A4 kickoff handoff | `handoff/m3-phase-a-progress-a4-kickoff` | Docs-only; targets main |

### Test deltas across M3 Phase 0 + Phase A so far

| Suite | M2 baseline (v0.2.0) | After M3-A3 (PR #50) | Delta |
|---|---|---|---|
| `api/` | 1013 | 1089 | **+76** (Phase 0: +33; Phase A: +43) |
| `gateway/` | 515 | 515 | 0 (no gateway changes yet) |
| `web/` vitest | 456 | 465 | +9 (M3-0.3's KB-detail helper extensions) |
| Cypress E2E suites | 7 | 8 | +1 (M3-0.1 fresh-install login) |

Per-PR test additions:
* PR #45 (M3-0.1): +6 backend + 9 vitest + 4 Cypress
* PR #46 (M3-0.2): +7 backend + 1 integration flip
* PR #47 (M3-0.3): +10 backend
* PR #48 (M3-A1): +15 backend
* PR #49 (M3-A2): +21 backend
* PR #50 (M3-A3): +17 backend

All CI gates green at every merge.

### M3 Phase 0 — complete (3-of-3)

| Task | DE | PR | Surface |
|---|---|---|---|
| M3-0.1 | DE-283 | #45 | `/api/v1/admin/bootstrap-status` + login-screen hint panel |
| M3-0.2 | DE-277 | #46 | Citation extractor full-document fallback + chunk-mismatch warning |
| M3-0.3 | DE-276 | #47 | `documents.ingest_status` + `/api/v1/admin/ingest-health` + KB-detail badge |

**M3 plan's Phase 0 stated goal** ("pre-M3 hardening; DE-276 load-bearing for Phase C Tabular Review") **is met.**

### M3 Phase A — 3-of-6 done

| Task | PR | What landed |
|---|---|---|
| M3-A1 — Playbook substrate | #48 | Migration 0031 (3 tables, 2 CHECK enums, 3 indexes); ORM module; Pydantic schemas |
| M3-A2 — Playbook executor | #49 | `app/playbooks/` module (state + nodes + executor); LangGraph runtime (`langgraph>=0.2,<0.3` pinned); 4-node workflow; 2 endpoints (`POST /playbooks/{id}/execute` + `GET /playbook-executions/{id}`); FastAPI BackgroundTasks for async kick-off |
| M3-A3 — NDA built-ins | #50 | 2 playbook YAMLs (mutual + unilateral, 8 positions each, ≥2 fallback tiers per position) + seed migration 0032 |
| **M3-A4 — Execution UI** | **next session** | SvelteKit route at `/lq-ai/playbooks/`; doc-list + cost preview + per-position result card; Cypress E2E |
| M3-A5 — 3 more built-ins | future | MSA-SaaS, DPA, Commercial MSA; seed migration 0033 |
| M3-A6 — Easy Playbook wizard | future | Multi-doc upload + clustering + draft assembly |

---

## 2. Commits on m3-development ahead of main (read these for context)

```
d08bd51 feat(api,m3-a2): Playbook executor — LangGraph runtime + 4-node workflow + 2 endpoints (#49)
21cdbc4 feat(api,m3-a1): Playbook substrate — migration 0031 + ORM + Pydantic schemas + CRUD tests (#48)
0ec499c feat(api,web,m3-0-3): DE-276 ingest observability — documents.ingest_status + /admin/ingest-health + UI badge (#47)
af19958 feat(api,m3-0-2): DE-277 citation extractor — full-document fallback for chunk-boundary spanning quotes (#46)
9d70972 feat(api,web,m3-0-1): DE-283 fresh-install login UX — surface bootstrap-password path on first 401 (#45)
```

(M3-A3 / #50 lands as a 6th commit once it merges; this handoff is intentionally written so it stays accurate either way.)

---

## 3. Architectural decisions Kevin locked during Phase 0 + Phase A

These are decisions the next session inherits without needing to re-litigate. Each links to where it's recorded.

### Decision A — M3-0.2 fix lives in `extraction.py`, not `verification.py`

The M3 plan's M3-0.2 task description placed the chunk-boundary fix in `verification.py` with new `verification_method` enum values. Reading the actual code revealed the gap is upstream in `extraction.py`'s locator — once the extractor emits document-absolute offsets, the verifier verifies them via existing Stage 1/2 logic. PRD §9 / DE-277's spec is authoritative. **M3 plan's M3-0.2 task description was corrected in PR #46** (docs/M3-IMPLEMENTATION-PLAN.md). No new `verification_method` enum values landed.

### Decision B — M3-0.3 broader scope than PRD §9 / DE-276's specific-scope

PRD's DE-276 specific-scope sketched a narrower fix (`documents.embedding_status` enum: pending|embedded|failed). The M3 plan committed broader: 4-value `ingest_status` enum (`ok|parse_failed|embed_failed|partial`) with `parse_failed` reserved for forward-compat. **PR #47 ships the broader scope; PRD §9 / DE-276 is marked `SHIPPED at M3-0.3` with the deferred CI-guard option (PRD option c) called out.**

### Decision C — Async execution via FastAPI BackgroundTasks for v0.3

The Playbook executor (M3-A2) runs async via `BackgroundTasks` rather than ARQ. Restarts kill in-flight executions; clients re-poll and see stuck-in-`running` rows. **Known limitation**, documented in PR #49. ARQ migration is the candidate future enhancement. The executor interface accepts the same shape either way.

### Decision D — `fallback_tiers` as JSONB on `playbook_positions`, not a third normalized table

Per-position list is small (typically 2-3 alternatives), always fetched together with the position, and never queried independently. **Locked in migration 0031** (M3-A1). Reviewer pushback welcome but absent at PR #48 merge.

### Decision E — `contract_type` is free-form text per PRD §3.7

No enum constraint on `playbook.contract_type`. Operators can define new contract types without a migration. **Locked in migration 0031.**

### Decision F — Attestation reframed as user professional judgment (BIG ONE)

Kevin's call at M3-A3 kickoff:

> Any user of the system needs to apply their own professional judgment about the skills. We disclaim that we are providing legal advice and state that the skills shouldn't be considered legal advice or relied upon without review by a legal professional licensed to provide legal advice in the given jurisdiction. We lean into transparency and giving people the power to use the portions of this application that they professionally are OK with.

Implications already carried in PR #50:
* Each built-in playbook's `description` field includes the not-legal-advice disclaimer + professional-judgment language.
* Test `test_description_includes_not_legal_advice_disclaimer` pins the requirement so M3-A5's built-ins (and any community-contributed playbooks) inherit the same posture.
* The migration's docstring documents the reframe.

**Implications NOT yet carried** (folded into the M3-close docs batch — see §5):
* `skills/CONTRIBUTING.md` attestation paragraph (lines 163-174) is technically out of step with the v0.3 policy; needs softening to the judgment-and-disclaimer framing.
* `docs/PRD.md` §1.3 Transparency-as-a-Founding-Principle should explicitly call out that built-in skills/playbooks carry disclaimers, not warranties.
* UI disclaimer surfaces — chat / playbook-execution / Word add-in views need the standard banner. **Filed as M3-A4 follow-on** (which the next session can decide to include or defer).
* Skill generator/editor disclaimer field — M3-A6 follow-on.

### Decision G — Seed migration reads YAML at upgrade time

`0032_seed_builtin_playbooks_nda.py` reads `skills/playbooks/{slug}/playbook.yaml` at upgrade time (path walks four `.parent` from migration file to repo root). YAML files are the single source of truth; the migration is thin. Drift risk is mitigated by the `test_migration_seeded_positions_match_yaml` test. **Locked in PR #50.** Future M3-A5 seed migration (0033) follows the same pattern.

---

## 4. M3-A4 — the next task

### Spec (from M3-IMPLEMENTATION-PLAN.md)

> **Task M3-A4 — Playbook execution UI in web app**
>
> **Scope:**
> - New SvelteKit route in `web/src/routes/lq-ai/playbooks/` for:
>   - Playbook list view: `/lq-ai/playbooks` — shows available playbooks with contract_type + version + author.
>   - Playbook execution flow: from a document (or Project file), "Apply Playbook" action opens a playbook picker; selecting a playbook + confirming kicks off execution.
>   - Execution result view: `/lq-ai/playbook-executions/[id]` — renders the per-position outcome with the standard language, the contract's language, the assessment, and the suggested redline. Citations render in the existing 5-state Citation Engine UI (M2-C2).
> - Bulk position view: collapsed-by-default per-position cards; expand to see standard + actual + redline.
> - Filter UI: filter positions by severity (`critical` / `high` / `medium` / `low`) and by outcome (`matches` / `deviates` / `missing`).
> - Cost preview before execution (estimated tokens × per-model rate, per M2-E2 cost calibration surface): show "Estimated cost: $X.XX" and a confirm step.
> - Cypress E2E test in `web/cypress/e2e/m3-a-playbook-execution.cy.ts` covers: select doc → select playbook → preview cost → confirm → see results.
>
> **Dependencies:** M3-A3.
>
> **Output:** Operators can run a built-in playbook against a document in the web app and see structured results with citations.
>
> **Verification:**
> - Cypress E2E passes.
> - Visual review: result view is legible; the per-position card layout supports an attorney walking through a 30-position contract review without cognitive overload.
> - WCAG 2.1 AA compliance for color/contrast on outcome badges.
>
> **Effort:** 12–16 hours.

### What's already wired for M3-A4 to consume

The next session does NOT need to build any of this — it's all landed:

* **Two API endpoints to call** (from PR #49):
  * `POST /api/v1/playbooks/{playbook_id}/execute` — returns 202 + `PlaybookExecution` row at `status='pending'`
  * `GET /api/v1/playbook-executions/{execution_id}` — poll for status updates + final results
* **Pydantic wire shapes** (`api/app/schemas/playbooks.py`): `Playbook`, `PlaybookExecution`, `Position`, `FallbackTier`, `PlaybookExecutionStatus`, `PositionSeverity`
* **OpenAPI sketch** with both endpoints + the `PlaybookExecution` component (`docs/api/backend-openapi.yaml`)
* **Two built-in playbooks seeded at v1.0.0** (mutual NDA + unilateral NDA) — they exist in the DB after migrations run; the UI's list view should show both
* **The `results` JSONB schema** is `{ "schema_version": "m3-a2-v1", "positions": [...], "summary": {...} }` — see `app/playbooks/nodes.py::_shape_results_payload` for the exact structure

### What M3-A4 needs to NEW-build

* SvelteKit route + components (parallels the existing `/lq-ai/knowledge/[id]/` pattern for layout + sort/filter helpers)
* TypeScript client functions in `web/src/lib/lq-ai/api/playbooks.ts` (new file)
* Per-position card component with collapsed/expanded states
* Severity badge component (matches the existing trust-pill style)
* Outcome badge component (matches the M2-C2 citation-state visual language)
* Cost-preview modal (calls a new endpoint OR estimates client-side; **see open question §5.2**)
* Cypress E2E spec

### What's likely NOT needed in M3-A4 (deferrable)

* CRUD endpoints for playbooks (`GET /playbooks`, `POST /playbooks`, `PATCH`, `DELETE`) — the M3-A2 spec deferred these to M3-A4 by implication, but a list view can read from a NEW `GET /api/v1/playbooks` endpoint. **Decision point** — see §5.1.
* Easy Playbook wizard — that's M3-A6.
* Citation Engine end-to-end wiring — the per-position `cited_chunk_ids` is already in the executor's results payload; the UI can render the existing 5-state citation visual against it. **No new backend work expected** — confirm by reading PR #49.

---

## 5. Open questions for the next session to surface to Kevin

These are the choice points M3-A4 will hit. The next session should AskUserQuestion before committing the design.

### §5.1 — Does M3-A4 also ship the playbook CRUD endpoints?

The M3-A2 PR (#49) deliberately deferred CRUD to "M3-A4 alongside the UI." The UI list view needs SOMETHING to list playbooks. Options:

* **A.** Add `GET /api/v1/playbooks` only (read-only list + detail) for M3-A4. CRUD `POST` / `PATCH` / `DELETE` defer to M3-A6 (alongside the Easy Playbook wizard's create flow).
* **B.** Add full CRUD in M3-A4. Tighter Phase A scope; bigger PR.
* **C.** UI lists only the seeded built-ins (no API call; hardcoded slug list). Smallest M3-A4 scope; clearly stopgap.

Recommended: **A**. Matches PR #49's deferral language; minimal scope expansion; M3-A6 owns the create surfaces naturally.

### §5.2 — Cost preview: client-side estimate or new endpoint?

The M3 plan's M3-A4 spec mentions "Estimated cost: $X.XX" + a confirm step. Two paths:

* **Client-side estimate** — UI computes `n_positions × estimated_tokens_per_call × per-model-rate`. Per-model rates are visible in the gateway's config; client fetches them. Roughly accurate, requires no new endpoint.
* **New backend endpoint** — `GET /api/v1/playbooks/{id}/cost-estimate?target_document_id=X` returns `{ estimated_cost_usd, estimated_token_count, judge_model }`. Per-position cost computed server-side using the M2-E2 rolling-average calibration.

Recommended: **client-side**. M2-E2's per-model rolling-average lives in api/, but the inputs are static enough that the client can do the math. New endpoint = new auth surface + new test surface + new OpenAPI entry; cost-preview is informational only (it doesn't gate execution).

### §5.3 — UI disclaimer banner: M3-A4 scope or defer?

Per Decision F, the attestation reframe requires a UI disclaimer banner on playbook-execution views. Options:

* **A.** M3-A4 ships the banner alongside the execution result view. Tight integration with the surface.
* **B.** Defer to the M3-close docs/policy batch (where CONTRIBUTING.md refresh + PRD §1.3 update live).

Recommended: **A**. The banner is just text + a CSS box; sub-hour effort; landing it inline with the execution view means operators see it from day one of M3-A4. The CONTRIBUTING.md / PRD refresh can still bundle at M3-close.

### §5.4 — Per-position card layout density

The plan says "supports an attorney walking through a 30-position contract review without cognitive overload" — accessibility-driven design ask. Options:

* **Dense rows** — table-style; one row per position; expand-to-reveal details
* **Card grid** — 2-column or 3-column card layout
* **Vertical card list** — one card per position, full-width, collapsed by default

Recommended: **dense rows + expand-to-reveal**. Matches the existing knowledge-detail page's file-list pattern operators are familiar with. Cypress E2E can pin the interaction.

---

## 6. Deferred work explicitly NOT being carried into M3-A4

The next session should mention these in their handoff at end-of-session, but should NOT pick them up unless explicitly directed:

### From the M3-close docs/governance batch (see `memory/project_m3_deferred_machinery.md`)

* `docs/ROADMAP.md` — single index pointing at PRD §8 + open DEs + active M-plan + HONEST-STATE
* `skills/CONTRIBUTING.md` attestation-paragraph refresh (Decision F implication)
* `docs/PRD.md` §1.3 transparency-callout update (Decision F implication)
* CI check: PRs touching `#### DE-XXX` in PRD §9 must add `Status: SHIPPED at MX-X.Y` marker
* `scripts/generate_release_notes.py` — auto-emit `docs/RELEASE-NOTES-vX.Y.md` from DE status markers
* **Estimated total effort:** ~6-8 hours across two PRs (docs first, then CI + scripts)

### From M3-A2's deferred-from-scope list

* Citation Engine end-to-end integration (per-position results carry `cited_chunk_ids`; full Stage 1-4 wiring is "M3-A4 work" per PR #49's body — surface to Kevin if M3-A4 should include or defer further)
* Ensemble verification activation through the executor (M2-D1 surface)
* OTel spans on classify + redline LLM calls (filed as a follow-on DE)

### From M3-A3's deferred-from-scope list

* Manual walk-through of NDA-mutual playbook against 3 real-world NDAs (the M3-A3 verification spec called for this; Kevin's eyes on the legal content first, then the walk-through)
* Skill-editor disclaimer field (M3-A6 follow-on)

---

## 7. Next-session entry point

After this handoff merges, the next session opens with this prompt:

> Start M3-A4. Read `docs/SESSION-HANDOFF-2026-05-18-m3-phase-a-progress-a4-kickoff.md` first. §3 has the architectural decisions already locked; §5 has the open questions to surface before writing code. Begin with the §5 questions, then proceed with the SvelteKit route + Cypress E2E.

The new session should:
1. Sync `m3-development` (where the next feature branch will be based)
2. Read this handoff in full
3. Surface §5.1–§5.4 to Kevin via `AskUserQuestion`
4. Open `m3-a4-playbook-execution-ui` off `m3-development`
5. Build per the answered design choices

If PR #50 has not yet merged by the time the next session opens, M3-A4 should still proceed — the schemas + endpoints are stable, the only blocker is having seeded built-ins to show in the list view (and the next session can seed them locally for development via the migration or hand-insert two rows).

---

## 8. Open PRs at handoff time

| PR | What | Decision needed |
|---|---|---|
| #50 | M3-A3 NDA built-ins | Review the legal content; merge to m3-development |
| (this PR) | M3-A4 kickoff handoff | Review; merge to main |

---

## 9. Memory state at end-of-session

The persistent memory at `~/.claude/projects/.../memory/` reflects:

* `project_m3_deferred_machinery.md` — **updated** with the three new follow-on items from Decision F (CONTRIBUTING.md refresh, PRD §1.3 update, UI disclaimer banner, skill-editor disclaimer field). Total estimated effort bumped 4-6h → 6-8h.
* `MEMORY.md` — index entry for the updated deferred-machinery file unchanged (still points at the same file; the file's content grew).
* `project_lq_ai_status.md` — should be updated by the next session at M3-A4 close, or here if Kevin wants. Currently still says "M2 SHIPPED, M3 is next" which is technically true but understates Phase 0 + Phase A progress.

The next session should re-read `project_m3_deferred_machinery.md` before any decision about disclaimer / docs work — the policy reframe (Decision F) is captured there.

---

## 10. Loose ends explicitly NOT being carried into M3-A4

* **Per-skill prompt-injection detection rates** (PRD §1.9 commitment) — deferred to M4 per M3 plan §8 carryovers
* **OpenSSF Silver Best Practices Badge** — deferred to M4 per same
* **Mutation testing per release** — deferred to M4 per same

These are public commitments documented in the M3 plan's "What this plan does not cover" section. The next session does not need to think about them; they surface at M4 kickoff.

---

*End of handoff. The next session begins at §5 with the four design questions for Kevin, then opens `m3-a4-playbook-execution-ui` and ships the execution UI.*
