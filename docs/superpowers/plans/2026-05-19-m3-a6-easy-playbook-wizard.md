# M3-A6 Easy Playbook Wizard — Prep Notes

> **Note on plan style:** Largest Phase A task by far. Mixes substantial new infrastructure (ARQ job queue), substantial new backend (clustering algorithm + new skill), substantial new frontend (4-step wizard with full inline editor), and three previously-deferred CRUD endpoints. The plan is therefore an architectural outline organized by phase, not an M3-A4-style mechanical task list. Algorithm specifics decided during implementation; per Decision F + the 2026-05-19 reframe, the user-attorney validates wizard output (not the maintainer team), so structural correctness is the bar.

**Goal:** Operators upload 5–20 prior agreements of the same contract type and get a drafted playbook covering their organization's typical positions, with inline editing before save. Per [PRD §3.7 NFR](../../PRD.md#37-playbooks): generation from 10 prior agreements completes in <10 minutes.

**Branch:** `m3-a6-easy-playbook-wizard` off `m3-development` (currently at `7e42f41`).

**Effort estimate:** 30–50 hours (PRD says 14–18; my read is higher given ARQ infrastructure + full inline editor + clustering algorithm + 3 CRUD endpoints all in one PR).

---

## Design decisions locked at kickoff (2026-05-19)

| Q | Decision |
|---|---|
| Async execution model | **Introduce ARQ now.** Redis-backed job queue + worker container. M3-A2's BackgroundTasks remain on BackgroundTasks for now; consolidating M3-A2 onto ARQ is a follow-on (filed as DE). The 10-minute generation pipeline is the natural forcing function; future Tabular Review (Phase C) benefits too. |
| CRUD endpoint landing | **In M3-A6 PR.** POST + PATCH + DELETE for `/api/v1/playbooks` land alongside the wizard. Matches the §5.1 deferral language; gives the wizard somewhere to save and the user somewhere to edit post-save. |
| Document persistence | **Persisted to user's library** (via existing Document Pipeline). Default behavior; uploaded contracts land in the user's files. Enables "add more docs and regenerate" workflow; reuses RBAC + audit. Consider adding a UI hint that documents persist (transparency posture). |
| Inline editor depth | **Full editor.** Step 3 surfaces every field per position: `issue`, `description`, `standard_language`, `redline_strategy`, `severity_if_missing`, `detection_keywords[]`, `detection_examples[]`, `fallback_tiers[]` (each with `rank`, `description`, `language`). Significant UI surface; matches the "attorney edits to taste before saving" workflow. |

---

## Quality bar (per Decision F + 2026-05-19 reframe)

Wizard output is itself a **starting point that the user-attorney validates**, not maintainer-curated content. The verification reduces to:

1. **Structural correctness** — wizard produces YAML that validates against `PlaybookCreate` and that the executor can run end-to-end.
2. **Gross sensibility** — generated positions are recognizable as the requested contract type (e.g., a wizard run on 10 NDAs produces positions that look NDA-like; not random text).
3. **Latency** — <10 minutes for 10 docs on the default model alias.
4. **Operator can edit** — full inline editor; saves via POST /playbooks.

What we explicitly do NOT verify: that the generated standard language is legally sound, that the fallback tiers are sensibly ranked, or that the redline strategy is correct. The user-attorney evaluates all of that during Step 3 inline editing.

---

## File structure (new)

### Backend

```
api/
  pyproject.toml                          # add arq>=0.26 dependency
  app/
    workers/
      __init__.py                         # new package
      arq_setup.py                        # WorkerSettings + redis connection
      easy_playbook_worker.py             # the generation pipeline
    api/
      playbooks.py                        # extend with CRUD + /easy endpoints
    playbooks/
      easy/
        __init__.py                       # new sub-package
        extractor.py                      # playbook-easy-extract orchestration
        clustering.py                     # embedding clustering + modal detection
        assembly.py                       # draft playbook assembly
    schemas/
      playbooks.py                        # extend with EasyPlaybookGenerationCreate, EasyPlaybookGeneration
  alembic/
    versions/
      0034_easy_playbook_generations.py   # new table tracking generation jobs
  tests/
    test_playbook_crud_endpoints.py       # POST/PATCH/DELETE coverage
    test_easy_playbook_extractor.py
    test_easy_playbook_clustering.py
    test_easy_playbook_assembly.py
    test_easy_playbook_endpoints.py
    test_easy_playbook_worker.py
skills/
  playbook-easy-extract/
    SKILL.md                              # skill metadata + prompt
    examples/                             # 1-2 worked examples
deploy/
  docker-compose.yml                       # add `arq-worker` service entry
```

### Frontend

```
web/src/
  lib/lq-ai/api/playbooks.ts              # extend with CRUD + easy-playbook helpers
  lib/lq-ai/components/
    PlaybookEditor.svelte                 # NEW — reusable position-array editor
    PlaybookEditorPosition.svelte         # NEW — single position editor
    PlaybookEditorFallbackTier.svelte     # NEW — single fallback-tier editor
  routes/lq-ai/playbooks/easy/
    +page.svelte                          # wizard shell with step state
    step1-upload.svelte                   # step 1
    step2-progress.svelte                 # step 2 (polling)
    step3-review.svelte                   # step 3 (full inline editor)
    step4-approve.svelte                  # step 4 (final save)
    page-helpers.ts                       # state machine + validators
    __tests__/page-helpers.test.ts
web/cypress/e2e/m3-a6-easy-playbook-wizard.cy.ts
```

---

## Implementation phases (sequential commits)

### Phase 1 — ARQ infrastructure

- Add `arq>=0.26` to `api/pyproject.toml`.
- Create `app/workers/arq_setup.py` with `WorkerSettings` class binding to the existing Redis (already running in compose for chat-stream cancellation).
- Add a new `arq-worker` service to `docker-compose.yml` that runs `arq app.workers.arq_setup.WorkerSettings`. Sister container to `ingest-worker`; same image.
- Add a tiny no-op task + smoke test (`test_arq_smoke.py`) that enqueues a task and verifies the worker executes it. This is the "ARQ is wired up" gate.
- Update `gateway.yaml.example` if needed (probably not — ARQ doesn't go through the gateway).
- Update `docs/architecture.md` to mention the new worker.
- **Commit 1** ships this; intentionally small and independently verifiable.

### Phase 2 — Playbook CRUD endpoints

- Add to `app/api/playbooks.py`:
  - `POST /api/v1/playbooks` — create. Body is `PlaybookCreate` (already exists). Returns the created `Playbook` with positions. Sets `created_by` to caller's id; non-admins can only create for themselves.
  - `PATCH /api/v1/playbooks/{playbook_id}` — update. Body is `PlaybookUpdate` (new — all fields optional). Only the playbook owner or admins can update. Updates header fields + replaces the positions array atomically (simpler than per-position diff).
  - `DELETE /api/v1/playbooks/{playbook_id}` — soft delete. Only the playbook owner or admins. Positions cascade.
- Tests: `test_playbook_crud_endpoints.py` covers all three with owner-visibility + cross-user 404 + admin-can-edit-builtins (or not — decision: admins can create new playbooks but cannot edit the built-ins at v1.0.0 since they're shared deployment-level content; admin-fork-then-edit is the path).
- OpenAPI sketch update.
- **Commit 2** ships this; clean diff, no wizard yet.

### Phase 3 — `playbook-easy-extract` skill

- Create `skills/playbook-easy-extract/SKILL.md` with the prompt and output format.
- Prompt design: takes a contract's full text (or chunks thereof), returns a structured JSON list of `{issue, clause_text, source_offsets}`. Issue is free-form (LLM picks descriptive names from common contract issue vocabulary; clustering normalizes downstream).
- For long contracts (>~10K tokens), chunk and call per-chunk; merge.
- Wrapped by `app/playbooks/easy/extractor.py::extract_clauses_from_document(document) -> list[ExtractedClause]`.
- Tests: `test_easy_playbook_extractor.py` — golden-file test using a sample NDA fixture; the test asserts structural correctness (returns N clauses, each with the required fields) but does NOT assert specific clause content (LLM nondeterminism). Use a deterministic stub for the executor pattern.
- **Commit 3** ships this skill + extractor module.

### Phase 4 — Clustering algorithm + draft assembly

- `app/playbooks/easy/clustering.py`:
  - Input: list of `(document_id, clause)` tuples across the corpus.
  - Embed each clause via the existing embedding service (used by KB retrieval).
  - Cluster by issue label first (LLM-given names like "Definition of Confidential Information") — clauses with identical or near-identical labels group together. Sub-cluster within label by embedding-distance for variant detection.
  - Output: `list[Cluster(issue_label, clauses[], modal_clause, neighbor_clauses[])]`.
- `app/playbooks/easy/assembly.py`:
  - Input: clusters.
  - For each cluster: modal_clause becomes `standard_language`; neighbor_clauses become candidate fallback tiers (top 2 by distance).
  - One LLM call per cluster to write the `description`, `redline_strategy`, and severity guess from the clause set. This is the "describe this position" round.
  - For each fallback tier: one LLM call to write the tier `description` (why this is an acceptable alternative).
  - `detection_keywords` derived from the issue label + top-frequency nouns in the cluster. `detection_examples` taken from the modal + neighbor clauses verbatim.
- Output: `PlaybookCreate` Pydantic object ready to validate.
- Tests: `test_easy_playbook_clustering.py` (synthetic clause corpora → expected cluster groupings) + `test_easy_playbook_assembly.py` (mock LLM responses; verify the assembled playbook validates against `PlaybookCreate`).
- **Commit 4** ships clustering + assembly modules.

### Phase 5 — Easy-playbook endpoints + ARQ worker

- `alembic/versions/0034_easy_playbook_generations.py`:
  - New table `easy_playbook_generations`: `id`, `user_id`, `contract_type`, `status` (pending/running/completed/error), `document_ids[]`, `draft_playbook` (JSONB; the assembled PlaybookCreate-shape), `error_message`, `created_at`, `started_at`, `completed_at`.
- Add to `app/api/playbooks.py`:
  - `POST /api/v1/playbooks/easy` — accepts `{document_ids[], contract_type, persist_documents_after_generation?: bool}`. Validates the caller owns all the doc ids. Enqueues an ARQ job; returns the generation-row id immediately.
  - `GET /api/v1/playbooks/easy/{generation_id}` — polls the status row + returns the `draft_playbook` JSON when complete.
- `app/workers/easy_playbook_worker.py`:
  - The actual pipeline: fetch documents → extract clauses per doc → cluster → assemble → write `draft_playbook` to the generation row → mark status='completed'.
  - Error handling: any unhandled exception sets status='error' + records the message.
- Tests: `test_easy_playbook_endpoints.py` (endpoint contract tests with mock ARQ enqueue) + `test_easy_playbook_worker.py` (worker integration test with mocked LLM that runs the full pipeline end-to-end against a small synthetic corpus).
- **Commit 5** ships endpoints + worker + migration.

### Phase 6 — Frontend wizard

- `web/src/lib/lq-ai/api/playbooks.ts` extended with: `createPlaybook`, `updatePlaybook`, `deletePlaybook`, `startEasyPlaybookGeneration`, `getEasyPlaybookGeneration`. Vitest specs follow the existing M3-A4 pattern.
- `PlaybookEditor.svelte`: reusable component taking a `PlaybookCreate`-shaped object as a prop, surfacing all editable fields with reactive change events. Composed of `PlaybookEditorPosition.svelte` (one per position) which is composed of `PlaybookEditorFallbackTier.svelte`. Validates inline as the user types (issue non-empty, ≥2 fallback tiers per position, severity in enum, etc.).
- Route `web/src/routes/lq-ai/playbooks/easy/+page.svelte`:
  - State machine: `step: 'upload' | 'progress' | 'review' | 'approve'` + the wizard data (`documents`, `generation_id`, `draft_playbook`).
  - Step 1: multi-file dropzone, contract_type selector, "Start generation" button. Uploads via existing upload API + collects document_ids.
  - Step 2: polls `GET /playbooks/easy/{id}` every 5 seconds; renders progress UI ("Extracting clauses from doc 3 of 10..."). Auto-advances to step 3 on completion.
  - Step 3: `<PlaybookEditor bind:playbook={state.draft_playbook} />` — the full inline editor; "Save playbook" button calls `POST /playbooks` with the edited state and advances to step 4.
  - Step 4: success screen with link to the new playbook's detail view.
- Disclaimer banner from M3-A4 renders on every step (Decision F transparency).
- Add a new tab entry in `TopTabBar` if needed — but probably just a button in the existing playbooks list page ("Generate from prior agreements").
- **Commit 6** ships the wizard frontend + extended API client.

### Phase 7 — Cypress E2E + verification

- `web/cypress/e2e/m3-a6-easy-playbook-wizard.cy.ts`:
  - Mocks every API call. Login → /lq-ai/playbooks/easy → upload 3 stub files → mock generation flow with two poll cycles → see draft in step 3 → edit one field → save → land on the saved playbook detail view.
- Manual UI smoke: real run against the live stack with the seeded NDA corpus from `docs/quickstart/`.
- Backend smoke: full test suite + `ruff format` + `ruff check` + svelte-check.
- **Commit 7** ships the E2E + opens PR.

---

## Phase-to-PR strategy

**Single PR** for all 7 commits. The wizard's phases are tightly coupled (Phase 5 needs Phases 1+2+3+4; Phase 6 needs Phases 1+2+3+4+5). Splitting mid-way leaves the branch in a transient state where backend exists without UI or vice versa.

If the PR gets too large for review, candidate splits:
- **Split A**: PR-1 ships Phases 1+2 (ARQ infra + CRUD endpoints). PR-2 ships the wizard. Two review cycles.
- **Split B**: PR-1 ships Phases 1+2+3+4+5 (all backend). PR-2 ships frontend (Phase 6+7). Cleaner backend/frontend separation but PR-2 can't be tested without PR-1 merged.

Default to single PR; switch to Split A if PR-1 review feedback signals "this is too much to review at once."

---

## Out-of-scope (defer)

1. **Migrating M3-A2's BackgroundTasks executor to ARQ** — consistency win but scope creep. File as DE post-M3-A6.
2. **Regeneration after editing** — the spec describes a one-shot generation. "Add 3 more contracts and regenerate" is a natural follow-on but requires re-extraction + re-clustering logic; defer.
3. **Multi-user playbook sharing** — current model is user-owned; "share with team" is a future enhancement.
4. **Real-time progress events (WebSocket)** — Step 2 uses HTTP polling. WebSocket would be smoother but adds infra complexity.
5. **LLM provider selection per generation** — uses the deployment's default judge model alias (same as M3-A2 executor). Per-generation provider override is a future config.
6. **Bulk position deletion in inline editor** — Step 3 supports per-position edit; bulk operations defer to a future iteration.

---

## Source-of-truth references

- PRD §3.7 (Playbooks) — capability spec including the <10 min NFR
- M3-A2 executor (`api/app/playbooks/executor.py`) — reference for async pipeline shape
- M3-A4 list-page (`web/src/routes/lq-ai/playbooks/+page.svelte`) — UI pattern for the editor
- M3-A5 playbook YAMLs — structure the wizard's draft must produce
- `feedback_no_maintainer_legal_review.md` — the "wizard output is itself a starting point" framing

---

*End of prep notes. Implementation begins with Phase 1 (ARQ infrastructure).*
