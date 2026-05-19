# M3 Implementation Plan — Playbooks, Word Add-In, Tabular Review, and Slack/Teams

> **Purpose:** Dependency-ordered task list for the M3 build. Each task is a discrete unit of work sized for a focused Claude Code session, with verifiable end-state. Follows the same conventions as [`M1-IMPLEMENTATION-ORDER.md`](M1-IMPLEMENTATION-ORDER.md) and [`M2-IMPLEMENTATION-PLAN.md`](M2-IMPLEMENTATION-PLAN.md).
>
> **Status:** Authoritative once committed. Updates land in the same release cadence as the PRD.
>
> **Audience:** Claude Code or any human contributor implementing M3. Hand this document along with the PRD, `db-schema.md`, the OpenAPI sketches, the gateway config example, and `CLAUDE.md`. Implementation flows from the order documented here.

The M3 milestone is the **feature-parity-and-surface-coverage** release. Four largely-independent tracks ship together:

1. **Playbook engine + 4 built-in playbooks** ([PRD §3.7](PRD.md#37-playbooks)) — Playbook schema, LangGraph executor, Easy Playbook auto-generation wizard, execution UI in web app. 4 built-ins: NDA, Generic SaaS MSA, DPA (GDPR-aligned), Commercial MSA.
2. **Word Add-In (Office.js)** ([PRD §3.9](PRD.md#39-word-add-in-m3)) — Chat against open document; apply skills to selection or whole doc; execute Playbooks against the doc; redlines as Word tracked changes; comments as Word comments; Inference Tier badge in the task pane; **signed manifest for enterprise sideload**.
3. **Tabular / Multi-Document Review** ([PRD §3.14](PRD.md#314-tabular--multi-document-review-m3)) — `output_format: table` skill mode; tabular UI surface; bulk operations; XLSX/CSV export; cost preview before execution.
4. **Slack / Teams Light Intake Bridge** ([PRD §3.15](PRD.md#315-slack--teams-light-intake-bridge-m3)) — OAuth install on Slack and Teams; `/lq` slash command (forward-as-chat) and `/lq ask` quick-skill flows; bot configuration in LQ.AI admin UI.

M3 ships in **~8 weeks of focused work** per [PRD §8 M3](PRD.md#m3--playbooks-word-add-in-tabular-review-and-slackteams-8-weeks-after-m2). The phase breakdown is **sequential by complexity**: the Playbook engine is the substrate that Word Add-In and Tabular both build on, and Slack/Teams is the smallest independent surface. Within each phase, parallel-execution slots are marked **[parallel]**.

This document supersedes any conflicting sequencing in earlier roadmap documents. The PRD §8 roadmap remains the canonical capability commitment; this document is the implementation contract.

---

## Architectural decisions locked for M3

Five architectural decisions are locked at the start of M3; subsequent tasks build on them. Documented here for the agent's clarity and so future contributors understand the reasoning.

### Decision M3-1: LangGraph runtime lives in `api/`, not a separate service

The Playbook executor and the Tabular Review workflow both run as LangGraph workflows. The LangGraph runtime lives **inside the existing `api/` FastAPI service** rather than as a separate `executor/` container.

The reasoning:

- Playbook and Tabular executions are first-class application operations, not background workers — they need synchronous access to skills, citations, knowledge bases, and project RBAC. A separate service would require duplicating auth context and RBAC enforcement.
- The existing `api/app/skills/` module is the natural home for skill orchestration; LangGraph is a substrate for the same orchestration shape. Co-location keeps the surface auditable.
- Long-running playbook executions (PRD §3.7 budgets < 3 min for a 50-page MSA) fit within the existing async-handler model. A worker queue (Celery/RQ) is not warranted at M3 volumes.

The alternative (separate `executor/` container) is documented as **DE-XXX (filed in M3-E2)** in PRD §9 for future consideration if execution-volume or operator-isolation requirements demand it.

### Decision M3-2: Word add-in JS bundle is served by the self-hosted deployment

Per [PRD §3.9 open question](PRD.md#39-word-add-in-m3), the Word add-in's JS bundle is **served by the LQ.AI deployment itself** (option a), not from a LegalQuants-controlled CDN (option b) or GitHub releases (option c).

The reasoning:

- Self-hosted deployments minimize external network dependencies; an add-in that fails when LegalQuants' CDN is down is a procurement-relevant flaw.
- The bundle is small (< 1 MB after Office.js dependencies); serving it from the existing `web/` SvelteKit app adds negligible operational surface.
- Updates ship with the LQ.AI release — the operator's deployment and the add-in are versioned together. No version-skew between a v0.3 backend and a v0.4 add-in.

The add-in manifest XML references the operator's deployment URL (`{deployment_origin}/word-addin/taskpane.html`); the manifest is generated at install time by an admin UI flow (covered in M3-B1).

### Decision M3-3: Tabular Review is a new Skill output type, not a parallel system

Per [PRD §3.14](PRD.md#314-tabular--multi-document-review-m3): Tabular Review is "mostly a new Skill output type plus a UI surface." This is locked.

Concretely:

- Skill frontmatter gets a new field: `output_format: report | table`. Default is `report` (the current behavior).
- A `table`-output skill specifies `columns: [...]` in its frontmatter — each column is a per-row extraction query.
- The Tabular LangGraph workflow walks documents × columns, runs each cell as a Citation-Engine-verified extraction, and produces a grid.
- Skill format and skill conventions ([PRD §3.4](PRD.md#34-skill-service), [docs/skill-authoring-guide.md](skill-authoring-guide.md)) are extended in-place; no parallel "tabular skill" system.

This keeps the Skill format as the single contract for work product and means Tabular's UI surface is decoupled from its execution model — the same `output_format: table` skill could later be invoked from the Word Add-In or from the API directly.

### Decision M3-4: Slack/Teams bridges ship as optional Docker Compose profiles

The `slack-bridge` and `teams-bridge` services are **optional Docker Compose profiles** (`docker compose --profile slack up` / `--profile teams up`), not core services in the default stack. Per the existing PRD §1569 reference (`docker-compose.yml.example`) and the M1 deployment posture.

The reasoning:

- Most deployments will not enable Slack or Teams bridges. Making them optional preserves the minimal-footprint default.
- OAuth credentials for Slack/Teams are deployment-specific and operator-acquired; the off-by-default posture matches the off-by-default posture for cloud LLM provider API keys.
- The bridges are net-new services with new external trust boundaries (Slack/Teams webhooks). Off by default reduces the default attack surface.

Bot configuration lives in the LQ.AI admin UI (M3-D4), not in environment variables, so operators don't need to redeploy to change Slack/Teams config.

### Decision M3-5: Signed Word manifest ships in v0.3, not a v0.3.1 follow-on

The Office.js add-in's manifest XML ships **signed for enterprise sideload** in v0.3. Per Kevin's call at M3 kickoff. The reasoning:

- The Word Add-In's primary procurement story is "deploy through Microsoft 365 Admin Center." A signed manifest is the procurement-ready posture. An unsigned-or-dev-only-manifest first release loses the procurement story for v0.3.
- Code-signing infrastructure (cert acquisition + CI signing job) is incremental engineering once; deferring it to v0.3.1 creates a release whose announcement is "the add-in you've been waiting for, but you can't deploy it yet."
- The signing work is sized for M3 (~12-16h in M3-B7); it does not bend the M3 critical path materially.

Cert acquisition is a procurement task that should begin at M3 kickoff in parallel with M3-A code work; cert turnaround can be multiple weeks.

---

## Phase 0 — Pre-M3 hardening (Week 1)

Three deferred enhancements surfaced during M2 land before the M3 tracks begin. They are small, isolated, and either (a) load-bearing for downstream M3 tracks (DE-276) or (b) easy wins worth shipping as the v0.2.x patch series before the M3 tracks open (DE-283, DE-277).

### Task M3-0.1 — DE-283: Fresh-install login UX (bootstrap-password surface)

**Scope:**
- Update the web app login surface so that a first-401 against the default admin credentials renders an informational panel pointing the operator at `docker compose logs api` for the bootstrap admin password.
- Add a `/api/v1/admin/bootstrap-status` endpoint (read-only) that returns `{ "default_password_active": bool, "logs_hint": str }` — the web app calls this on 401 to decide whether to surface the bootstrap-password hint.
- Update `docs/quickstart.md` to point at the new UX flow.
- Mark this task as community-friendly in PR template / README — first-contribution target.

**Dependencies:** None. First task in M3.

**Output:** Fresh-install operators see actionable guidance on the login screen instead of a generic 401.

**Verification:**
- Fresh-install reproduction: `docker compose down -v && docker compose up --build`; navigate to login; confirm informational panel renders correctly.
- The hint disappears once the operator has rotated the bootstrap password.
- Cypress E2E test in `web/cypress/e2e/m3-0-fresh-install-login.cy.ts` covers the first-401 path.

**Effort:** 3–4 hours.

**References:** [DE-283 in PRD §9](PRD.md#de-283--fresh-install-login-ux-surface-the-bootstrap-password-path-on-first-401).

---

### Task M3-0.2 — DE-277: Citation extractor chunk-boundary fallback

**Scope** (corrected to track [DE-277 in PRD §9](PRD.md#de-277--citation-extractor-fallback-to-document-scan-on-chunk-boundary-miss) verbatim — the plan's original task description placed the fix in `verification.py`, but the actual gap is in `extraction.py`'s locator):

- Extend `app/citation/extraction.py::extract_citations` with a full-document fallback. When the chunk-local locator (`_locate_in_chunk(quote, chunk.content)`) misses but the caller supplies the chunk's parent document's `normalized_content` (M2-A1 surface), retry the same exact-then-fuzzy locator against the full document.
- Resolved offsets from the document-level scan are document-absolute already (no `chunk.char_offset_start` arithmetic); the downstream verifier reads against `documents.normalized_content` so the Stage 1 / Stage 2 logic verifies spanning candidates with no change. **No new `verification_method` values are required.**
- Wire the chat-send pipeline (`app/api/chats.py::_persist_message_citations`) to pre-load documents for the retrieved-chunk doc_ids and pass the normalized-content map to `extract_citations`. The same loaded docs are reused by the verifier (no duplicate DB roundtrip).
- Emit a structured `citation_chunk_mismatch` warning when the fallback fires (per [DE-277](PRD.md#de-277--citation-extractor-fallback-to-document-scan-on-chunk-boundary-miss) option b) — the citation still verifies, but the mismatch signal is worth surfacing for aggregate observability.
- Unit tests in `api/tests/citation/test_chunk_boundary.py` covering: citation spanning two chunks; citation spanning three chunks (rare but possible for long quotes); citation entirely within one chunk (regression test — unaffected); chunk-mismatch warning emitted only on fallback path; backward compatibility when `document_contents` is not supplied.
- Flip the existing `test_edge_cases.py::test_chunk_boundary_spanning_citation_does_not_extract_today` to assert the new behavior (`verification_method='exact_match'`, document-absolute offsets persisted).

**Dependencies:** M2-A1 (normalized_content); M2-A2 (Stage 1); M2-B1 (Stage 2). All shipped at v0.2.0.

**Output:** Citations split across chunk boundaries no longer fall to Stage 3 (LLM judge) when they could be verified verbatim against the source document.

**Verification:**
- Test corpus includes citations deliberately authored across chunk boundaries; the spanning fallback resolves them.
- No regression in single-chunk verification (existing test suite passes unchanged).
- The `citation_chunk_mismatch` warning surfaces in logs / Langfuse spans when the fallback fires.

**Effort:** 4–6 hours.

**References:** [DE-277 in PRD §9](PRD.md#de-277--citation-extractor-fallback-to-document-scan-on-chunk-boundary-miss).

---

### Task M3-0.3 — DE-276: Ingest observability — surface silent embed/parse failures

**Scope:**
- Audit `api/app/pipeline/ingest.py` for paths where parse or embed failures are caught and logged without surfacing to the user or to a queryable surface.
- Add `documents.ingest_status TEXT NOT NULL DEFAULT 'ok'` and `documents.ingest_failure_reason TEXT NULL` columns via migration `0030_ingest_observability.py`. Status values: `'ok'`, `'parse_failed'`, `'embed_failed'`, `'partial'`.
- Surface ingest-status in the document list UI: failed documents render with a red error badge + click-through to the failure reason.
- Add an `/api/v1/admin/ingest-health` endpoint returning aggregate counts of `ok` / `parse_failed` / `embed_failed` / `partial` documents across the deployment.
- Wire OTel span on every parse and embed call so silent failures appear in Langfuse/observability.
- Update `docs/db-schema.md` for the new columns.
- Backfill: existing documents get `ingest_status = 'ok'` by default; operators may re-run ingest on flagged docs.

**Dependencies:** None directly; load-bearing for Phase C (Tabular Review) since silent embed failures would corrupt tabular outputs.

**Output:** Operators can see which documents in their KBs are partially or fully un-ingested. Silent failures surface as alarms, not as data corruption.

**Verification:**
- Deliberately corrupt a test PDF (truncate it); re-ingest; document appears with `ingest_status = 'parse_failed'` and the failure reason in the UI.
- `GET /api/v1/admin/ingest-health` returns nonzero `parse_failed` count.
- Existing healthy documents unchanged (`ingest_status = 'ok'`).

**Effort:** 6–8 hours.

**References:** [DE-276 in PRD §9](PRD.md#de-276--ingest-observability-surface-silent-embedparse-failures).

---

## Phase A — Playbook engine substrate (Weeks 2–3)

The Playbook engine is the load-bearing substrate for two M3 tracks (Word Add-In uses it to execute Playbooks against open documents; Tabular Review uses the same LangGraph runtime). Phase A lands the schema, the executor, the first built-in playbook end-to-end, the execution UI, then the remaining built-ins and the Easy Playbook wizard.

### Task M3-A1 — Playbook schema + DB migrations

**Scope:**
- Alembic migration `0031_playbooks.py` adds:
  - `playbooks` (id UUID, name TEXT, contract_type TEXT, description TEXT, version TEXT, created_by UUID FK users, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ).
  - `playbook_positions` (id UUID, playbook_id UUID FK playbooks, issue TEXT, description TEXT, standard_language TEXT, fallback_tiers JSONB, redline_strategy TEXT, severity_if_missing TEXT CHECK IN ('critical','high','medium','low'), detection_keywords TEXT[], detection_examples TEXT[], position_order INT).
  - `playbook_executions` (id UUID, playbook_id UUID FK, target_document_id UUID FK documents, user_id UUID FK users, project_id UUID FK projects NULL, status TEXT, results JSONB NULL, error TEXT NULL, created_at TIMESTAMPTZ, completed_at TIMESTAMPTZ NULL).
  - Indexes: `playbook_positions(playbook_id, position_order)`; `playbook_executions(user_id, created_at DESC)`; `playbook_executions(target_document_id)`.
- Pydantic schemas in `api/app/schemas/playbooks.py` matching [PRD §3.7](PRD.md#37-playbooks) (`Playbook`, `Position`, `FallbackTier`, `PlaybookExecution`).
- SQLAlchemy models in `api/app/models/playbooks.py`.
- Update `docs/db-schema.md` for the three new tables.

**Dependencies:** Phase 0 complete.

**Output:** Playbook data substrate exists; no executor yet.

**Verification:**
- `alembic upgrade head` runs cleanly against a fresh DB.
- `pytest api/tests/models/test_playbook_models.py` covers CRUD round-trip.
- OpenAPI conformance test holds (no schemas added that aren't referenced).

**Effort:** 4–6 hours.

---

### Task M3-A2 — LangGraph runtime + Playbook executor skeleton

**Scope:**
- Add `langgraph ~= 0.2` to `api/pyproject.toml`. Pin a version; SBOM-relevant.
- Create `api/app/playbooks/` module:
  - `__init__.py`
  - `executor.py` — LangGraph-based `PlaybookExecutor` class.
  - `nodes.py` — individual LangGraph nodes (retrieve, classify, redline, compile).
  - `state.py` — `PlaybookExecutionState` typed dict.
- Implement the four-step executor per [PRD §3.7 Playbook execution](PRD.md#37-playbooks):
  1. **Parse target contract** — fetch document via existing Document Pipeline; obtain chunks.
  2. **Retrieve matching clause(s)** — per Playbook position, hybrid-search the target contract for the position's `detection_keywords` + `detection_examples`. Return top-k chunks per position.
  3. **Classify** — for each position, run a structured-output LLM call: `matches_standard | matches_fallback_tier_N | deviates | missing`. Uses the same Inference Gateway as chat; respects the project's `minimum_inference_tier` and `ensemble_verification` flags.
  4. **Draft redlines** — for `deviates` results, draft a redline using the position's `redline_strategy` template. Structured output: `{old_text, new_text, justification}`.
- Citation Engine integration: every `matches_standard` / `matches_fallback_tier_N` / `deviates` classification cites the chunk(s) it matched against; the Citation Engine verifies them (Stages 1–4 as configured).
- Persist `PlaybookExecution.results` as JSONB with the full per-position outcome.
- API endpoints (subset, per [PRD §3.7](PRD.md#37-playbooks)):
  - `POST /api/v1/playbooks/{id}/execute` — kicks off execution; returns 202 with execution_id.
  - `GET /api/v1/playbook-executions/{id}` — returns execution state + results.
- Unit tests in `api/tests/playbooks/test_executor.py` against a small synthetic playbook and a tiny doc.
- Update `docs/api/backend-openapi.yaml` for the new endpoints.

**Dependencies:** M3-A1.

**Output:** Playbook executor runs end-to-end against synthetic inputs. No UI yet; tested via API.

**Verification:**
- Synthetic test: create a tiny NDA-shaped doc, a single-position playbook, kick off execution, poll for completion, verify the position is classified.
- Verify Citation Engine integration: classifications cite chunks, citations pass verification.
- Failed-execution path: missing document or unknown playbook returns 404 cleanly; in-flight error sets `status = 'error'` and persists `error` field.

**Effort:** 12–16 hours.

---

### Task M3-A3 — First built-in playbook: NDA (mutual + unilateral variants)

**Scope:**
- Author `skills/playbooks/nda/playbook.yaml` (mutual variant) and `skills/playbooks/nda-unilateral/playbook.yaml` (unilateral variant).
- Each playbook covers the standard NDA position set:
  - Definition of confidential information
  - Permitted disclosures (legal counsel, regulators, affiliates)
  - Duration / term
  - Survival of confidentiality obligations
  - Carveouts (independently developed, publicly known, lawfully obtained)
  - Remedies / injunctive relief
  - Governing law / venue
  - Return / destruction of confidential information
- Each position has `standard_language`, ≥2 `fallback_tiers`, `redline_strategy`, `severity_if_missing`, `detection_keywords`, `detection_examples`.
- Practicing-attorney attestation per [skills/CONTRIBUTING.md](../skills/CONTRIBUTING.md) — built-in playbooks follow the same attestation path as skills containing legal substance.
- Seed migration `0032_seed_builtin_playbooks_nda.py` inserts both NDA playbooks into the `playbooks` and `playbook_positions` tables at version `1.0.0`.
- Integration test: run NDA playbook against the sample NDA shipped in M1 fixtures; assert each position is classified.

**Dependencies:** M3-A2.

**Output:** First built-in playbook executes end-to-end. Validates the Playbook authoring conventions before scaling to 3 more.

**Verification:**
- Practicing-attorney attestation in PR description.
- Integration test passes.
- Manual walk-through: maintainer + reviewing attorney run NDA playbook on 3 real-world sample NDAs; outcomes are sensible.

**Effort:** 8–10 hours.

---

### Task M3-A4 — Playbook execution UI in web app — **SHIPPED at M3-A4**

**Scope:**
- New SvelteKit route in `web/src/routes/lq-ai/playbooks/` for:
  - Playbook list view: `/lq-ai/playbooks` — shows available playbooks with contract_type + version + author.
  - Playbook execution flow: from a document (or Project file), "Apply Playbook" action opens a playbook picker; selecting a playbook + confirming kicks off execution.
  - Execution result view: `/lq-ai/playbook-executions/[id]` — renders the per-position outcome with the standard language, the contract's language, the assessment, and the suggested redline. Citations render in the existing 5-state Citation Engine UI (M2-C2).
- Bulk position view: collapsed-by-default per-position cards; expand to see standard + actual + redline.
- Filter UI: filter positions by severity (`critical` / `high` / `medium` / `low`) and by outcome (`matches` / `deviates` / `missing`).
- Cost preview before execution (estimated tokens × per-model rate, per M2-E2 cost calibration surface): show "Estimated cost: $X.XX" and a confirm step.
- Cypress E2E test in `web/cypress/e2e/m3-a-playbook-execution.cy.ts` covers: select doc → select playbook → preview cost → confirm → see results.

**Dependencies:** M3-A3.

**Output:** Operators can run a built-in playbook against a document in the web app and see structured results with citations.

**Verification:**
- Cypress E2E passes.
- Visual review: result view is legible; the per-position card layout supports an attorney walking through a 30-position contract review without cognitive overload.
- WCAG 2.1 AA compliance for color/contrast on outcome badges.

**Effort:** 12–16 hours.

**Implementation deviations from original scope (recorded for M3 milestone summary):**
- §5.1 — `GET /api/v1/playbooks` + `GET /api/v1/playbooks/{id}` ship with M3-A4; `POST/PATCH/DELETE` defer to M3-A6 alongside the Easy Playbook wizard's create flow.
- §5.2 — Cost preview is client-side against a static `PER_MODEL_RATES` table (`web/src/lib/lq-ai/playbookCost.ts`); a server-side cost-estimate endpoint was not added.
- §5.3 — `PlaybookDisclaimerBanner.svelte` ships in M3-A4 (Decision F implication); CONTRIBUTING.md + PRD §1.3 attestation refresh still defer to the M3-close docs batch.
- §5.4 — Result view uses dense rows + expand-to-reveal (table-style), not full-width vertical cards.
- Apply-Playbook entry point is from `/lq-ai/playbooks` (playbook → pick doc), not from a document's context menu. Doc-context entry point deferred to M3-A6.
- Citation Engine integration: per-position `cited_chunk_ids` render as chunk-id pills; full Stage 1–4 5-state UI integration deferred (the existing Citation Engine UI uses continuous relevance percentage, not 5 discrete states — gap surfaced during reconnaissance).
- Backend follow-on: exposed `KBFileResponse.document_id` (the parsed-content row UUID, distinct from File id) so the modal's KB→file picker can resolve `target_document_id` client-side. 4-file change covering schema, query, TS type, OpenAPI.

**Deferred items filed as M3-A4 follow-ons** (track in M3 milestone summary):
- DE — Playbook position citations: open-in-document drilldown (Citation Engine 5-state coloring against `cited_chunk_ids`).
- DE — Apply-Playbook from document context menu (M3-A6 candidate).
- DE — Automated WCAG audit tooling (no a11y ESLint plugin in the codebase today; M3-A4 verified manually via browser devtools).

---

### Task M3-A5 — Remaining 3 built-in playbooks (MSA-SaaS, DPA, Commercial MSA)

**Scope:**
- Author `skills/playbooks/msa-saas/playbook.yaml` — Generic SaaS MSA playbook; covers SLA, security commitments, data handling, IP, limitation of liability, indemnification, termination, audit rights, payment terms, governing law, change management.
- Author `skills/playbooks/dpa-gdpr/playbook.yaml` — DPA (GDPR-aligned) playbook; covers Art. 28 (processor obligations), Art. 32 (security), Art. 33 (breach notification), international transfers (SCCs / TIA), sub-processor handling, audit rights, deletion / return of personal data, DSAR cooperation.
- Author `skills/playbooks/msa-commercial-purchase/playbook.yaml` — Commercial MSA from purchase side; covers acceptance, warranties, indemnification, limitation of liability, IP, change orders, payment, termination for cause/convenience, governing law.
- Each playbook carries the standard not-legal-advice disclaimer in its `description` field (Decision F locked at M3-A3 kickoff; the `test_description_includes_not_legal_advice_disclaimer` pattern from M3-A3 generalizes to each new playbook).
- Seed migration `0033_seed_builtin_playbooks_msa_dpa.py` inserts all three at version `1.0.0`, following the M3-A3 pattern of reading the YAML files at upgrade time.
- Each gets one integration test against a representative sample contract in `api/tests/fixtures/`. Sample contracts sourced from public-domain templates (Common Paper CC-BY-4.0, EU Commission SCCs, etc.) with attribution.

**Dependencies:** M3-A4 (validates the end-to-end flow before scaling).

**Output:** 4 built-in playbooks total are available out-of-the-box (NDA × 2 from M3-A3 + MSA-SaaS + DPA-GDPR + MSA-Commercial-Purchase).

**Verification:**
- Each playbook integration test passes.
- Each playbook's description includes the not-legal-advice disclaimer (pinned by test).
- Manual sanity check by Kevin against ≥1 representative sample contract per playbook; outcomes are plausible. Not a formal practicing-attorney attestation per Decision F — the disclaimer-in-description is the canonical posture and operators are expected to apply their own professional judgment.

**Effort:** 12–16 hours (~80% legal-content drafting, ~20% engineering scaffold).

---

### Task M3-A6 — Easy Playbook auto-generation wizard

**Scope:**
- New SvelteKit route `web/src/routes/lq-ai/playbooks/easy/` for the wizard:
  - Step 1: upload 5–20 prior agreements of the same contract type (limit to a single contract_type per wizard run).
  - Step 2: progress UI while the system extracts clauses, clusters by issue, identifies the user's most-common positions.
  - Step 3: review draft — wizard presents a draft playbook with suggested standard language and fallback tiers; user edits inline.
  - Step 4: approve — wizard creates a new Playbook in the operator's library.
- Backend: `POST /api/v1/playbooks/easy` starts generation; `GET /api/v1/playbooks/easy/{id}` polls status. Implementation:
  - Document parsing (existing Document Pipeline).
  - Clause extraction via a `playbook-easy-extract` skill (treats each contract as the input, returns structured clauses by issue type).
  - Clustering: embedding-based clustering of like-clauses across the corpus; identify the user's modal position per issue.
  - Draft assembly: standard_language from the modal position; fallback_tiers from neighboring cluster centers.
- Per [PRD §3.7 NFR](PRD.md#37-playbooks): "Easy Playbook generation from 10 prior agreements: < 10 minutes."
- Practicing-attorney review of the wizard's output quality on a curated test corpus before this task closes.

**Dependencies:** M3-A5.

**Output:** Users can upload prior agreements and get a drafted custom playbook for review and editing.

**Verification:**
- Generate a custom NDA playbook from a corpus of 10 sample NDAs; compare to the built-in NDA playbook; verify the output is plausible (similar position structure, sensible standard_language).
- Latency budget met: 10-doc generation completes in < 10 minutes against the dev-mode default model alias.
- Reviewing-attorney walk-through confirms the output is starting-point-quality (the user is expected to edit, not accept verbatim).

**Effort:** 14–18 hours.

---

## Phase B — Word Add-In (Weeks 4–5)

The Word Add-In brings LQ.AI capabilities into Microsoft Word as an Office.js task pane. It surfaces chat, skills, and playbook execution against the open document, with redlines as tracked changes and assessments as Word comments. Phase B ends with a **signed manifest distribution package** suitable for enterprise sideload via Microsoft 365 Admin Center.

**Note for the contributor:** the `word-addin/` directory does not yet exist. M3-B1 is the first task to create it. Office.js development tooling (Node 18+, the `office-addin-debugging` toolchain, a Word client for testing) must be set up before this phase begins.

### Task M3-B1 — Word add-in scaffold (manifest + task pane shell)

**Scope:**
- Create `word-addin/` directory with the Office.js standard structure:
  - `manifest.xml` — Office add-in manifest. Targets Word; declares OAuth scopes; references task pane HTML/JS at `{deployment_origin}/word-addin/taskpane.html`.
  - `src/taskpane/` — React 18 + TypeScript task pane shell. Office.js add-in convention is React; this is the **single allowed exception to the no-React-in-`web/` rule** ([CLAUDE.md](../CLAUDE.md)) because Word add-ins are Microsoft-conventionally React.
  - `src/commands/` — Office.js commands (toolbar buttons).
  - `webpack.config.js` — bundles the add-in JS.
  - `package.json` — pins Office.js, React, TypeScript versions.
- Task pane UI shell: header (LQ.AI logo + Inference Tier badge placeholder), tab strip (Chat / Skills / Playbooks), empty content area.
- Manifest generation: a new admin UI flow at `/lq-ai/admin/word-addin` produces a deployment-specific `manifest.xml` with the operator's deployment URL injected. This is the manifest the operator distributes via M365 Admin Center.
- `web/src/routes/word-addin/` SvelteKit route serves the task pane HTML + the bundled JS (per M3-2). The route is unauthenticated for the bundle JS; OAuth happens in M3-B2.
- Update `docker-compose.yml.example` to mount the `word-addin/dist/` directory into the web container's static-files path.
- Update `docs/architecture.md` with the Word add-in in the system diagram.

**Dependencies:** Phase 0 complete. Phase A is **not** a hard dependency — the Word add-in can scaffold in parallel with Phase A's Playbook engine work in calendar terms, but no code in B depends on A landing until M3-B5.

**Output:** The Word add-in loads in Word desktop with an empty task pane. Manifest can be generated per deployment.

**Verification:**
- Manual: sideload the dev manifest in Word desktop; task pane opens with the shell UI.
- The bundled JS is served by the LQ.AI deployment, not from any external host.
- Manifest XSD validates against Microsoft's schema (`office-addin-manifest validate`).

**Effort:** 10–12 hours.

---

### Task M3-B2 — Add-in ↔ backend authentication (OAuth)

**Scope:**
- Implement OAuth flow between the Word add-in and the LQ.AI deployment.
- The add-in opens an OAuth popup against `{deployment_origin}/oauth/authorize?client_id=word-addin&redirect_uri=...`; backend issues a token; add-in stores the token in `Office.context.officeRuntime.auth` (Microsoft's recommended pattern for add-ins).
- Backend changes:
  - Register `word-addin` as a built-in OAuth client (no client secret; uses PKCE).
  - Token issuance respects the user's existing LQ.AI identity (the add-in's OAuth flow logs the user into LQ.AI in the popup, then issues a token bound to that user).
  - Tokens are scoped (add-in can't access admin endpoints).
- Update `docs/api/backend-openapi.yaml` for the OAuth endpoints.
- E2E test: configure a test user; trigger the add-in's OAuth flow against a local dev deployment; verify the token works against `GET /api/v1/users/me`.

**Dependencies:** M3-B1.

**Output:** The add-in authenticates against the LQ.AI deployment as the same user who would log into the web app.

**Verification:**
- Manual E2E: sideload manifest → open task pane → click "Sign in" → OAuth popup → token stored → user-info request succeeds.
- Token-revocation path: revoke the token via the admin UI; subsequent add-in requests return 401; add-in surfaces a "sign in again" prompt.
- Security review per CODEOWNERS — touches auth.

**Effort:** 10–12 hours.

---

### Task M3-B3 — Chat against the open document

**Scope:**
- Task pane Chat tab: chat UI that mirrors the web app's chat UI, scaled for the narrower task pane.
- "Open document context" toggle: when on, the contents of the open Word document are passed as initial context to the chat (the document is treated as an attached file).
- Selection-only context: when text is selected in Word, a "Use selection" affordance attaches just the selected text as context.
- Chat backend: the add-in calls the same `/api/v1/chat/completions` endpoint as the web app; no new backend endpoint.
- Streaming responses render progressively in the task pane.
- Citations render with the same 5-state UI (verified / verified-tolerant / verified-paraphrase / unverified / system-error) as the web app — citation interaction in the add-in highlights the cited span in the Word document body via Office.js range APIs.

**Dependencies:** M3-B2.

**Output:** Users can chat with LQ.AI inside Word using the open document or a selection as context. Citations link back to spans in the doc.

**Verification:**
- Manual E2E: open a 5-page sample contract in Word; ask "what is the indemnification cap?"; verify the answer streams; verify citations highlight the right span when clicked.
- Selection-only path: select a single clause; ask "is this favorable to us?"; verify only the selected clause is in context.

**Effort:** 8–10 hours.

---

### Task M3-B4 — Skills in Word (apply skill to selection or document)

**Scope:**
- Task pane Skills tab: list of available skills (from `GET /api/v1/skills`).
- "Apply skill" flow:
  - User picks a skill (e.g., `nda-review`).
  - User chooses scope: whole document, or current selection.
  - Add-in calls `POST /api/v1/skills/{id}/execute` with the document (or selection) as input.
  - Result renders in the task pane with the same 5-state Citation Engine UI.
- Result post-processing for Word:
  - Skill-generated **redlines** → applied as Word **tracked changes** via Office.js (`Word.Range.insertText`, `Word.Range.delete` within a tracked-changes session).
  - Skill-generated **assessments** → applied as Word **comments** via `Word.Range.insertComment`.
  - Skill output that is descriptive text (not redline / not comment) renders in the task pane only.
- Inference Tier badge in the task pane: reflects the routed tier for the skill's underlying chat (per §3.13).

**Dependencies:** M3-B3.

**Output:** Skills run from Word against the open doc; redlines appear as tracked changes; comments appear as Word comments; users see citations in the task pane.

**Verification:**
- Manual E2E: open a sample NDA in Word; run the `nda-review` skill; verify tracked-changes appear for redline suggestions; verify comments appear for assessments; verify citations render correctly.
- The user can review/accept/reject the tracked changes using Word's native review tools.
- The Inference Tier badge reflects the actual tier used.

**Effort:** 12–16 hours.

---

### Task M3-B5 — Playbook execution in Word

**Scope:**
- Task pane Playbooks tab: list of playbooks (built-in + user-created).
- "Apply playbook" flow:
  - User picks a playbook.
  - User confirms cost preview.
  - Add-in calls `POST /api/v1/playbooks/{id}/execute` with the open document.
  - Progress UI updates as positions complete (the executor streams per-position results via SSE).
- Render Playbook results in Word:
  - Per-position assessment → Word comment at the matching clause location (using Office.js range APIs against the cited chunks).
  - Per-position suggested redline → Word tracked change.
  - Position summary card in the task pane: standard language vs. actual vs. assessment, with click-through to the in-doc comment.
- Filter / collapse positions by severity (matches web UI of M3-A4).

**Dependencies:** M3-A4 (Playbook execution UI in web app, validates the result-rendering surface); M3-B4 (tracked-changes + comments infrastructure).

**Output:** Operators can run a Playbook against the open Word document and see comments + tracked changes applied directly in Word.

**Verification:**
- Manual E2E with a reviewing attorney: open a sample MSA; run the MSA-SaaS playbook; verify position-level comments and tracked changes appear at the right locations; verify the per-position summary in the task pane matches what's in Word.

**Effort:** 10–12 hours.

---

### Task M3-B6 — Inference Tier badge in task pane [parallel with M3-B5]

**Scope:**
- Add Inference Tier badge to the task pane header (matches the web app's badge per [PRD §3.13](PRD.md#313-inference-tier-awareness)).
- Click-through opens the same tier-detail panel UI the web app uses (reuse the web app's component if practical; otherwise re-implement against the same `/api/v1/inference-tier-detail` endpoint).
- The badge reflects the active chat's effective tier (per [PRD §3.8 ensemble](PRD.md#38-multi-model-ensemble-verification): minimum tier across the ensemble).
- For Playbook executions and skill applications, the badge updates to reflect the tier for that operation.

**Dependencies:** M3-B4. Parallel with M3-B5 in calendar terms.

**Output:** Word add-in users see the same tier-awareness signal as web app users.

**Verification:**
- Switch the deployment's model routing between Tier 1 (local) and Tier 3 (cloud); verify the badge updates.
- Click-through opens the tier-detail panel correctly.

**Effort:** 4–6 hours.

---

### Task M3-B7 — Signed manifest + enterprise sideload distribution package

**Scope:**
- Acquire a code-signing certificate. Procurement task; **start at M3 kickoff** as cert turnaround can be multiple weeks. Track separately in PR template / project notes.
- Wire signing into CI:
  - GitHub Actions workflow `.github/workflows/word-addin-release.yml` signs `manifest.xml` and the bundled JS on every release tag.
  - Cert + private key stored as GitHub Actions secrets; manifest signing happens in a hardened workflow gated to the `release` environment.
- Produce a distribution package:
  - `word-addin-v0.3.zip` containing the signed manifest + a README with M365 Admin Center sideload instructions.
  - Released as a GitHub Release asset on the v0.3 tag.
- Update `docs/security/word-addin.md` (new doc) covering: signing chain of trust, what the operator should verify before deploying, threat model boundaries (the add-in runs in Office's web sandbox; it cannot access local files outside the document; it cannot call the LQ.AI backend without an OAuth token).
- Security review per CODEOWNERS — touches signing infrastructure.

**Dependencies:** M3-B6.

**Output:** Operators can download `word-addin-v0.3.zip`, verify the signature, and sideload via M365 Admin Center.

**Verification:**
- Manifest signature verifies against the issuing cert.
- Sideloaded add-in works against a real LQ.AI deployment in Word desktop, Word Online, and Word for iPad.
- Security reviewer signs off on the signing chain.

**Effort:** 12–16 hours.

---

### Task M3-B8 — Self-hosted add-in JS bundle serving + version handshake

**Scope:**
- Wire the add-in JS bundle to be served by the LQ.AI deployment's `web/` SvelteKit app at `{deployment_origin}/word-addin/taskpane.html` (per M3-2).
- Add a version-handshake on add-in load: the add-in fetches `/api/v1/version` and compares its bundled version against the deployment's; if mismatched, surfaces a "Reload the add-in" prompt (avoids the v0.3 add-in talking to a v0.4 backend).
- Update `docs/deploy/` operator guide for the Word Add-In: how to enable, how to generate the deployment-specific manifest, how to distribute via M365 Admin Center.

**Dependencies:** M3-B7.

**Output:** A self-hosted LQ.AI deployment serves its own Word add-in bundle. No external CDN dependency.

**Verification:**
- Fresh-install test: `docker compose down -v && docker compose up --build`; sideload the generated manifest; add-in loads, authenticates, and runs end-to-end.
- Version-skew test: deliberately serve a stale bundle; verify the handshake prompt appears.

**Effort:** 4–6 hours.

---

## Phase C — Tabular / Multi-Document Review (Week 6)

Tabular Review is the second consumer of the LangGraph runtime landed in Phase A. It introduces a new Skill `output_format: table` mode plus a tabular UI surface; bulk operations and XLSX/CSV export round it out.

### Task M3-C1 — `output_format: table` Skill mode

**Scope:**
- Extend the Skill frontmatter schema to support `output_format: report | table` (`report` is the existing default, backward-compatible).
- For `output_format: table` skills, frontmatter adds:
  - `columns: [{name: str, query: str, ensemble_verification: bool}]` — each column is a per-row extraction query; ensemble is optionally on by default for high-stakes columns.
- Update `docs/skill-authoring-guide.md` and [PRD §3.4](PRD.md#34-skill-service) to document the `table` mode.
- Update the skill-schema validator in `api/app/skills/validators.py` to enforce the new fields.
- Authoring conventions: a `table`-mode skill cannot specify `output_format` and `report`-mode output in the same skill — they are mutually exclusive.

**Dependencies:** Phase 0 + Phase A (LangGraph runtime).

**Output:** The Skill format supports a new `table` output mode. No execution yet; that's M3-C2.

**Verification:**
- Schema validator rejects malformed `table` skills (missing `columns`, columns without `query`).
- Existing `report` skills unchanged; regression test passes.

**Effort:** 6–8 hours.

---

### Task M3-C2 — Tabular Review LangGraph workflow

**Scope:**
- Create `api/app/tabular/` module:
  - `executor.py` — LangGraph workflow that walks documents × columns.
  - `nodes.py` — extraction node (per cell), aggregation node, citation-verification integration.
- Workflow:
  1. Input: a set of documents (Knowledge Base, Project files, or free selection) + a tabular skill (or ad-hoc columns).
  2. For each `(document, column)` pair, run the column's `query` as a citation-grounded extraction against the document. Returns `{value: str, citations: [Citation], confidence: 'high'|'medium'|'low', error: str|None}`.
  3. Aggregate into a grid: rows = documents, columns = column-names.
  4. Cells with failed extraction render as "not found" with a "verify" affordance — never as confident wrong text (matches Citation Engine state model).
- API endpoints:
  - `POST /api/v1/tabular/execute` — kicks off execution; returns 202 with `tabular_execution_id`.
  - `GET /api/v1/tabular/executions/{id}` — returns state + grid.
- Migration `0034_tabular_executions.py` adds `tabular_executions` table (id, user_id, status, document_ids JSONB, skill_id NULL, columns JSONB, results JSONB NULL, created_at, completed_at).
- Cost preview: before execution, return `{estimated_tokens, estimated_cost}` per the cost-calibration surface (M2-E2). User confirms before kickoff.

**Dependencies:** M3-C1.

**Output:** Tabular extractions run end-to-end against arbitrary document sets and column specs.

**Verification:**
- Sample: 5 NDAs × 4 columns (term, survival, carveouts, governing-law); execution completes; grid renders with citations per cell.
- Failed-cell path: deliberately ask a column-query that can't be answered from a doc; cell renders as "not found", not as confident wrong text.

**Effort:** 12–16 hours.

---

### Task M3-C3 — Tabular UI surface

**Scope:**
- New SvelteKit route `web/src/routes/lq-ai/tabular/`:
  - Selection step: pick documents (KB / Project files / individual files) and columns (saved tabular skill, or ad-hoc).
  - Cost preview step: shows estimated cost; user confirms.
  - Execution step: progressive grid renders as cells complete.
  - Result step: full grid view with each cell linking to the cited chunk(s) in the source document (opens the existing citation viewer side panel).
- Grid UX:
  - Sticky first column (document name) and first row (column names).
  - Cells render the extracted value + a confidence chip (matches Citation Engine's `high|medium|low` model).
  - Click a cell: side panel opens with the source document + highlighted citation spans.
- Cypress E2E test in `web/cypress/e2e/m3-c-tabular-review.cy.ts`.

**Dependencies:** M3-C2.

**Output:** Users run tabular extractions in the web app with a familiar grid + citation surface.

**Verification:**
- Cypress E2E passes.
- Visual review: 30-row × 5-column grid renders without performance regression.
- Cell-to-citation linkage works for all cell states (verified, partial, unverified).

**Effort:** 10–14 hours.

---

### Task M3-C4 — Bulk operations + XLSX/CSV export

**Scope:**
- Bulk operations from the tabular grid:
  - "Redline column N in all rows" — runs an `output_format: report` skill that produces redlines per row.
  - "Draft a memo summarizing column N" — runs a summary skill against the column's values.
- Export:
  - XLSX export — uses `openpyxl` (already in api deps? if not, pin a version). Each cell gets a comment with its citation source. Header row matches column names.
  - CSV export — citations are flattened to a separate "citation_links" column.
- Endpoint: `GET /api/v1/tabular/executions/{id}/export?format=xlsx|csv` — streams the file.

**Dependencies:** M3-C3.

**Output:** Operators can take the tabular result downstream in their existing Excel / spreadsheet workflows.

**Verification:**
- XLSX export opens cleanly in Excel desktop, Numbers (macOS), and Google Sheets.
- CSV export round-trips through `pandas.read_csv()`.
- Citation links in the XLSX comments resolve correctly when clicked (point at the deployment URL for the cited chunk).

**Effort:** 8–10 hours.

---

## Phase D — Slack / Teams Light Intake Bridge (Weeks 7–8)

The smallest and most independent track. Two bridges (Slack and Teams) ship as optional Docker Compose profiles. Two bot flows: `/lq` forwards a Slack/Teams message as the seed of a new LQ.AI chat; `/lq ask "..."` runs a short Org-Profile-configured skill and replies in-thread.

### Task M3-D1 — `slack-bridge` service + OAuth install flow

**Scope:**
- New service: `slack-bridge/` Python (FastAPI) service running on its own port.
- New Docker Compose profile in `docker-compose.yml.example`:
  ```yaml
  slack-bridge:
    profiles: ["slack"]
    image: lq-ai/slack-bridge:${VERSION}
    environment:
      SLACK_CLIENT_ID: ${SLACK_CLIENT_ID}
      SLACK_CLIENT_SECRET: ${SLACK_CLIENT_SECRET}
      SLACK_SIGNING_SECRET: ${SLACK_SIGNING_SECRET}
      LQ_AI_BACKEND_URL: http://api:8000
      LQ_AI_BRIDGE_TOKEN: ${LQ_AI_BRIDGE_TOKEN}
  ```
- OAuth flow:
  - Admin clicks "Install Slack bridge" in LQ.AI admin UI → opens Slack's OAuth consent page → callback to `/slack/oauth/callback` on the bridge → bridge persists the workspace's bot token in the LQ.AI backend (encrypted, per existing secret-management conventions).
- Permission model: bot can only post in channels it is invited to; bot does not read silent channels.
- Slack manifest YAML at `slack-bridge/manifest.yml` for the Slack App configuration.
- Security review per CODEOWNERS — touches auth and an external trust boundary.

**Dependencies:** Phase 0; **NOT** Phase A, B, or C — Slack/Teams bridge is largely independent.

**Output:** Operators can install the Slack bridge into their Slack workspace via OAuth.

**Verification:**
- Manual E2E: spin up a dev LQ.AI deployment; install the Slack app in a test workspace; verify the bot appears in the workspace and the workspace's bot token persists.
- Security reviewer signs off.

**Effort:** 8–12 hours.

---

### Task M3-D2 — `/lq` slash command + `/lq ask` quick-skill flow

**Scope:**
- Implement two Slack slash command flows in the `slack-bridge` service:
  - `/lq` (no arg) on a thread or message: forwards the thread's content as the seed of a new LQ.AI chat. The bot replies in-thread with a link to the chat in the LQ.AI web app.
  - `/lq ask "<question>"` — runs a configured Org-Profile quick-ask skill (configurable via the LQ.AI admin UI; default is a `quick-legal-question` skill) against the question. Replies in-thread with the answer + a link to open the chat in the web app for deeper engagement.
- The user-to-LQ.AI identity mapping: the Slack user's email must match an LQ.AI user's email; if no match, the bot replies in-thread with a "Your Slack account isn't linked to LQ.AI — ask your admin" message.
- Confidentiality: thread contents are stored in LQ.AI under the linked user's chat history, with the same RBAC as any other chat.

**Dependencies:** M3-D1.

**Output:** Slack users can summon LQ.AI from their existing thread workflows.

**Verification:**
- Manual E2E with two test users (one linked, one unlinked): both `/lq` flows; both reply in-thread; linked user sees a working LQ.AI chat; unlinked user sees the link-your-account message.
- Cost-accounting integration: replies through the bridge appear in the operator's cost dashboard tagged with `source: slack`.

**Effort:** 8–10 hours.

---

### Task M3-D3 — `teams-bridge` service + Teams OAuth + `/lq` flows

**Scope:**
- Mirror of M3-D1 + M3-D2 for Microsoft Teams:
  - New `teams-bridge/` service (Python, FastAPI).
  - Docker Compose `teams` profile.
  - Teams bot manifest at `teams-bridge/manifest.json`.
  - OAuth install flow using Microsoft Bot Framework auth.
  - `/lq` and `/lq ask` flows identical in behavior to Slack.
- Identity-mapping: Teams user's email (from M365) must match an LQ.AI user's email.
- Security review per CODEOWNERS.

**Dependencies:** M3-D2.

**Output:** Teams bridge parity with Slack bridge.

**Verification:**
- Same as M3-D2 but in a Teams test tenant.
- Confidentiality posture is symmetric with Slack: thread contents land in LQ.AI under the linked user's chat history.

**Effort:** 8–12 hours.

---

### Task M3-D4 — Bot configuration in LQ.AI admin UI

**Scope:**
- New SvelteKit admin route `web/src/routes/lq-ai/admin/intake-bridges/`:
  - Slack section: install/uninstall, workspace name, linked-user count, "configure quick-ask skill" dropdown.
  - Teams section: install/uninstall, tenant name, linked-user count, "configure quick-ask skill" dropdown.
  - Audit log: recent `/lq` invocations with user / channel / matched-skill / cost.
- Backend: `/api/v1/admin/intake-bridges` endpoints for the above.

**Dependencies:** M3-D3.

**Output:** Admins configure Slack/Teams bridges entirely from the LQ.AI admin UI; no env-var edits, no redeploys for config changes.

**Verification:**
- Admin UI walks through install → configure quick-ask skill → test invocation → see invocation in audit log.

**Effort:** 6–8 hours.

---

## Phase E — Acceptance + documentation finalization

### Task M3-E1 — Pre-tag fresh-install verification

**Scope:**
- Destroy all volumes and images; fresh clone; full `docker compose up --build` with all M3-relevant profiles (`--profile slack --profile teams`).
- Walk through each of the 4 M3 surfaces:
  - Playbook engine: run NDA playbook against sample NDA in web app; verify result.
  - Word Add-In: generate a manifest from admin UI; sideload in Word desktop; run a skill + a playbook; verify tracked changes + comments + citations.
  - Tabular Review: select 5 sample NDAs; run a 4-column tabular extraction; export XLSX; verify in Excel.
  - Slack bridge: install in test workspace; run `/lq ask "what is an MSA?"`; verify in-thread reply + chat-link works.
- Document any blockers found as deferred enhancements **before** tagging.
- Reviewing-attorney walk-through of the Playbook + Tabular surfaces against real-world contracts.

**Dependencies:** All of Phases A–D.

**Output:** Fresh-install validation passes; tagging-ready state confirmed.

**Verification:**
- All 4 surfaces work end-to-end on a fresh install.
- Any blockers either fixed or explicitly accepted as DE-XXX entries with severity.
- Reviewing-attorney signoff.

**Effort:** 6–8 hours.

---

### Task M3-E2 — Documentation finalization

**Scope:**
- New documents:
  - `docs/playbooks.md` — full Playbook engine documentation: schema, executor architecture, built-in playbooks, Easy Playbook wizard, authoring conventions, integration with Citation Engine.
  - `docs/word-addin.md` — Word Add-In documentation: architecture, installation (deployment-side + M365 Admin Center side), supported flows, manifest signing posture, threat model.
  - `docs/tabular-review.md` — Tabular Review documentation: skill `output_format: table` mode, LangGraph workflow, UI surface, export formats.
  - `docs/intake-bridges.md` — Slack and Teams bridge documentation: install flow, slash-command flows, configuration, security posture.
- Two new Learn-tab playgrounds (per the M2 documentation convention):
  - Playbook execution cascade — walks through how a playbook executes step-by-step against a sample contract.
  - Tabular Review playground — interactive grid against a small sample document set.
- Updated documents:
  - `docs/PRD.md` — changelog entry for M3 release; §3.7, §3.9, §3.14, §3.15 statuses flipped from "Deferred-M3" to "SHIPPED."
  - `docs/architecture.md` — Mermaid diagram updated with LangGraph runtime, Word add-in, tabular workflow, slack-bridge, teams-bridge components.
  - `docs/quickstart.md` — new sections for Playbook execution, Word add-in install, Tabular review, Slack/Teams bridges.
  - `README.md` — capability list updated to reflect M3 surfaces as shipped.
  - `docs/compliance/soc2-alignment.md` — controls updated for the new external trust boundaries (Word add-in OAuth, Slack/Teams bridges).
  - `docs/compliance/iso27001-alignment.md` — same.
  - `docs/procurement/sig-lite.md` — questions about Playbooks, Word add-in distribution, and Slack/Teams data-handling updated.
- New DE entries in `docs/PRD.md` §9:
  - DE-XXX (M3-1 alternative): separate `executor/` service for the LangGraph runtime.
  - DE-XXX: any other ideas surfaced during M3 build.
- File the §8 deferred-to-M4 carryovers (per M3-kickoff scope decision):
  - Per-skill prompt-injection detection rates — M4.
  - OpenSSF Silver Best Practices Badge — M4.
  - Mutation testing per release — M4.

**Dependencies:** M3-E1.

**Output:** Documentation matches implementation.

**Verification:**
- Reviewing-attorney walk-through against the quickstart passes.
- Cross-reference audit: `grep -rn` of internal links resolves cleanly.
- PRD changelog entry committed.

**Effort:** 10–14 hours.

---

## Total effort estimate

| Phase | Tasks | Effort |
|---|---|---|
| **0 — Pre-M3 hardening** | 3 | ~13–18 hours |
| **A — Playbook engine** | 6 | ~62–82 hours |
| **B — Word Add-In** | 8 | ~70–90 hours |
| **C — Tabular / Multi-Document Review** | 4 | ~36–48 hours |
| **D — Slack / Teams Light Intake Bridge** | 4 | ~30–42 hours |
| **E — Acceptance + docs** | 2 | ~16–22 hours |
| **Total** | **27** | **~227–302 hours** |

~265 hours fits in a focused **~8-week M3 build** by a single contributor working full-time (320 hours available), or ~12 weeks for someone working part-time. The estimate is *tight* — see Risks below. Parallel-execution opportunities (M3-B6 with M3-B5; M3-D track partially with C; cert acquisition for M3-B7 in parallel with all of Phase A) help.

---

## How to use this with Claude Code

The recommended workflow mirrors the M1 and M2 implementations:

1. **Hand Claude Code this document, plus `docs/PRD.md`, `docs/db-schema.md`, `docs/api/backend-openapi.yaml`, `docs/api/gateway-openapi.yaml`, `gateway.yaml.example`, and `CLAUDE.md`.**
2. **Pick the next task by ID:** "Implement Task M3-0.1 — DE-283 fresh-install login UX."
3. **Let Claude Code execute the full task in one session.** Each task is sized for a focused session.
4. **Verify against the documented verification step.** If verification fails, work with Claude Code to fix; do not move to the next task until current verifies.
5. **Move to the next task.** Tasks marked **[parallel]** can run concurrently in separate sessions if parallel agent execution is available.
6. **Don't let Claude Code make architectural decisions mid-task.** Decisions M3-1 through M3-5 are locked at the start; if a task surfaces a question those decisions don't anticipate, stop, decide, document.
7. **Surface ideas as DE-XXX entries.** When Claude Code surfaces useful ideas out of M3 scope, file them as deferred enhancements in PRD §9.
8. **Practicing-attorney attestation is required** for tasks that introduce or modify legal substance — built-in playbooks (M3-A3, M3-A5), the Easy Playbook wizard outputs (M3-A6), and the reviewing-attorney walk-throughs in M3-E1.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| M3 is genuinely 4 tracks in 8 weeks; scope creep would push v0.3 to v0.4 timing. | Decision B at M3-kickoff committed to "all four tracks must-ship." If mid-M3 a track is clearly slipping, surface as a scope-reframe decision to Kevin **before** tagging — not at release time. Build in a mid-M3 checkpoint (end of Phase B) for honest re-assessment. |
| Code-signing certificate acquisition has multi-week lead time and could block M3-B7. | Procurement task **starts at M3 kickoff**, in parallel with all Phase A work. If cert is not in hand by end of Phase B, M3-B7 becomes a v0.3.1 follow-on and the v0.3 release notes are honest about the temporarily unsigned manifest path. |
| LangGraph version churn breaks the Playbook executor between releases. | Pin LangGraph version in `api/pyproject.toml`. Bug-fix LangGraph upgrades land as patch releases with regression tests. |
| Word add-in development on a non-Windows primary dev machine (macOS-only contributor) limits coverage of Word desktop on Windows. | Office.js is cross-platform but Word Desktop on Windows is the dominant enterprise client. Test matrix in CI includes Word Desktop (macOS), Word Online, Word for iPad. Word Desktop (Windows) tested manually before tagging, with an explicit DE filed if a Windows-only issue is discovered. |
| Easy Playbook wizard produces low-quality drafts on small / inconsistent corpora. | Reviewing-attorney quality review on a curated 5-corpus before M3-A6 closes. UI explicitly frames the output as "starting-point draft — review before use." Document expected corpus characteristics (≥5 documents, same contract type). |
| Slack/Teams bridges introduce new external trust boundaries with new vulnerability classes. | Security review per CODEOWNERS on each bridge task (M3-D1, M3-D3). Bridges run as optional Docker Compose profiles; off by default. Audit log of every `/lq` invocation. |
| Tabular executions for large document sets (200 docs × 10 columns = 2,000 cells) could blow cost budgets. | Cost preview before execution **with confirm step** (M3-C2). Operators see the estimate before kickoff. Per-column ensemble verification is opt-in, not default. |
| Citation Engine load on the Playbook executor (every position-classification cites chunks; every citation runs the 4-stage cascade) could slow playbook execution beyond the 3-min budget. | Phase A integration tests measure P95 latency on a 50-page MSA against the budget. Ensemble verification is opt-in, not default, for playbook executions. If budget exceeded, single-judge fallback is acceptable for the position-classification surface (a position-level citation is lower-stakes than a chat-level citation). |

---

## What this plan does not cover

A few items deliberately out of scope for M3; tracked for M4 or later:

### Deferred to M4 (per M3-kickoff decision on §8 carryovers)

- **Per-skill prompt-injection detection rates** — PRD §1.9 commitment; deferred to M4. Tracked at PRD §9.
- **OpenSSF Silver Best Practices Badge** — was targeted at M2 release per PRD §1.8; deferred to M4. Tracked at PRD §9.
- **Mutation testing per release** — PRD §1.9 commitment; deferred to M4. Tracked at PRD §9.

### Existing M4 scope items

- **Autonomous Layer** — per [PRD §8 M4](PRD.md#m4--autonomous-layer-and-contract-repository-8-weeks-after-m3).
- **Contract Repository auto-relationship detection** — per [PRD §3.16](PRD.md#316-contract-repository--auto-relationship-detection-m4).
- **DE-279 — Case citation validation (Bluebook resolution)** — likely M4, citation-type-2 surface separate from M2's KB-quote engine.
- **DE-280 — Case-content accuracy (statement vs. judicial opinion)** — likely M4, hardest of the three citation surfaces.
- **DE-282 — Anonymization Layer empirical validation on legal document corpus** — community-friendly DE; M4 or community-led.

### Deferred forward-looking items

- **AppSource public listing of the Word Add-In** — enterprise sideload ships in M3-B7; the public AppSource listing is a M3.x or later follow-on (less procurement-critical than enterprise sideload).
- **Google Docs Add-On** — DE-083 in PRD §9; sister to Word Add-In, deferred.

---

*Implementation plan maintained alongside the PRD. As tasks complete, mark them so the next contributor (or agent) sees current state. Tasks that need decomposition are split in-place and the document updated.*
