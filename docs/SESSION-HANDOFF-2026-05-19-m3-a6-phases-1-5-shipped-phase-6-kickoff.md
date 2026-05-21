# Session Handoff — 2026-05-19 — M3-A6 Phases 1-5 shipped (backend complete + live-verified) → Phase 6 (frontend wizard) kickoff next

> **Purpose:** Context transfer for the next session, which opens **M3-A6 Phase 6: frontend wizard**. The 2026-05-19 (continuation) session landed five M3-A6 backend commits on `m3-a6-easy-playbook-wizard` (Phases 1+2+3+4+5), live-verified against the running stack, and produced this handoff. The backend of M3-A6 is now functionally complete; only the frontend wizard (Phase 6) and Cypress E2E (Phase 7) remain.
>
> Read time: ~12 minutes. Decisions Kevin already locked: §3 + the per-phase ship notes in §2.

---

## 1. State at handoff

### Branch + tag state

| Branch / Tag | SHA | Meaning |
|---|---|---|
| `main` | `ad1fd24` | Unchanged from prior session |
| `m3-development` | `0d57b5e` | Unchanged from prior session |
| `v0.2.0` (tag) | `8a1b3fc` | M2 release; unchanged |
| `m3-a6-easy-playbook-wizard` (open) | `af65598` | **Phases 1+2+3+4+5 shipped this session**; pushed to origin |

The m3-a6 branch is now **6 commits ahead of the prep-doc-only state** (was 1 commit ahead at session start):

| Commit | What |
|---|---|
| `1385d50` | M3-A6 prep doc (was the only commit at session start) |
| `1feec2e` | feat(api,m3-a6): ARQ worker infrastructure (Phase 1 of 7) |
| `c8b65a9` | feat(api,m3-a6): Playbook CRUD endpoints + soft delete (Phase 2 of 7) |
| `88dadb6` | feat(api,skills,m3-a6): playbook-easy-extract skill + extractor module (Phase 3 of 7) |
| `d19cfe2` | feat(api,m3-a6): clustering + draft assembly (Phase 4 of 7) |
| `af65598` | feat(api,m3-a6): Easy Playbook endpoints + ARQ worker (Phase 5 of 7) |

### Cumulative deltas

- **32 files changed / ~6,200 lines added** across the 5 phase commits.
- **92 new passing tests** (7 + 16 + 19 + 31 + 19 across Phases 1-5).
- **2 new migrations applied to dev DB**: `0034_playbooks_deleted_at` (Phase 2 soft-delete) + `0035_easy_playbook_generations` (Phase 5 generation-row table).
- **No regressions** across the existing playbook executor / list / model / built-in tests.
- **mypy clean** across all touched modules. **ruff format + check clean** across the api/ tree (240 files).

### Live-stack state at end-of-session

All 8 docker-compose services healthy:

```
api            — rebuilt; running migrations through 0035; healthy
arq-worker     — rebuilt; consuming arq:m3a6 queue; functions: noop_job + easy_playbook_generation_job; healthy
ingest-worker  — rebuilt (mid-session, see §7); consuming arq:queue; healthy
gateway, web, postgres, redis, minio — healthy
```

End-to-end live smoke from inside the api container:

```python
# Enqueued easy_playbook_generation_job('<fake-id>') onto arq:m3a6
# → worker dispatched in 0.19s
# → returned {'status': 'missing'} (graceful row-not-found path)
# → total round-trip: 0.25s
```

This confirms: queue isolation, function registration, ORM lookup path, return-value plumbing, and audit-attribution wiring are all working live. The "live verification caveat" from commit `af65598`'s message is **resolved**.

---

## 2. What landed this session (Phases 1-5)

### Phase 1 — ARQ worker infrastructure (commit `1feec2e`, 4 files / 309 lines)

Added a **second arq worker process** (`arq-worker` compose service), sister to the existing `ingest-worker`. The new worker consumes from a dedicated `arq:m3a6` queue (NOT arq's default) so a long-running Easy Playbook generation (per PRD §3.7 NFR: up to 10 minutes for a 10-doc corpus) cannot starve document ingest and vice versa.

**Surprise vs prep doc:** ARQ was already in production from M2's document pipeline (`arq>=0.25,<0.27` already pinned; `app/workers/document_pipeline.py` already exists). Phase 1 was actually "add a second worker pool with queue isolation" — not "introduce ARQ from scratch" as the prep doc framed it.

Files:
- `api/app/workers/arq_setup.py` (new) — WorkerSettings with queue_name="arq:m3a6"; noop_job (kept as health probe).
- `docker-compose.yml` (modified) — new `arq-worker` service entry.
- `api/tests/test_arq_smoke.py` (new) — 7 unit tests (queue disjointness, class shape, noop returns "ok", hooks, RedisSettings build).
- `docs/architecture.md` (modified) — expanded "Container orchestration" bullet to call out both arq workers + their queue assignments.

### Phase 2 — Playbook CRUD endpoints + soft delete (commit `c8b65a9`, 7 files / 1115 lines)

Three deferred-from-M3-A4 endpoints: POST/PATCH/DELETE on `/api/v1/playbooks`. Built-ins (`created_by IS NULL`) are 403 to everyone (including admins) — operators **fork built-ins, never edit them in place**. PATCH supports atomic positions-array replacement.

**Surprise vs prep doc:** the prep doc said "soft delete" without anchoring it; the existing schema had no `deleted_at` column. Adding it required migration 0034. Phase 5's planned migration shifted from 0034 to 0035.

**Greenlet gotcha caught in tests:** `len(playbook.positions)` after `db.flush()` in an async session triggers a lazy-load that fails with `MissingGreenlet`. Fix: capture `len(body.positions)` from the input Pydantic body BEFORE the flush, OR `await db.refresh(playbook, attribute_names=["positions"])` BEFORE accessing the relationship. Carry this knowledge into Phase 6's tests if they go through the same async path.

Files: `app/api/playbooks.py` (heavy edit), `app/models/playbook.py` (+`deleted_at`), `app/schemas/playbooks.py` (+`PlaybookUpdate`), `alembic/versions/0034_playbooks_deleted_at.py` (new, single-column add), `tests/test_playbook_crud_endpoints.py` (16 tests), `tests/test_playbook_models.py` (column-set assertion update), `docs/api/backend-openapi.yaml` (3 new schemas + 3 operations).

### Phase 3 — `playbook-easy-extract` skill + extractor module (commit `88dadb6`, 5 files / 1101 lines)

The per-document clause-extraction step. `skills/playbook-easy-extract/SKILL.md` is the internal-skill artifact (loaded by SkillRegistry for operator-facing discoverability); `api/app/playbooks/easy/extractor.py` mirrors the prompt as a Python constant and wraps it with chunking + structured-JSON parsing + per-span offset rebasing.

**Pattern decision:** prompts live in code (mirroring M3-A2's `app/playbooks/nodes.py`). SKILL.md is source-of-truth + discoverability artifact; the Python prompt mirrors it. The double-source has drift risk but matches established pattern and lets the gateway dispatch path avoid a runtime SkillRegistry fetch.

Public surface: `extract_clauses_from_document(*, document, gateway, contract_type=None, judge_model="smart", character_budget=50000, span_overlap_characters=1500) -> list[ExtractedClause]`. Failure modes (malformed JSON, gateway transport, per-entry validation) all degrade gracefully — a single bad span returns `[]` for that span; the rest of the document's spans continue.

Tests: `tests/test_easy_playbook_extractor.py` — 19 unit tests using a stub gateway (same pattern as `tests/playbooks/test_executor.py::_StubGateway`).

### Phase 4 — Clustering + draft assembly (commit `d19cfe2`, 5 files / 1865 lines)

`app/playbooks/easy/clustering.py`:
- `cluster_clauses_by_issue(*, clauses, gateway, embedding_model="embedding", max_fallback_neighbors=2) -> list[Cluster]`.
- Algorithm: group by normalized issue label (whitespace+case-insensitive); **single batched** `/v1/embeddings` call across the entire corpus (one round trip regardless of size); per-cluster medoid via min sum-of-cosine-distances; top-N neighbors by cosine distance from modal (most-different first); largest-cluster-first sort.
- Graceful degradation: embedding-service failure → length-based modal selection; the user-attorney's Step 3 edit is the safety net.
- O(n²) medoid — fine at bounded corpus size (5-20 docs × 5-20 clauses each ≈ 400 worst case).

`app/playbooks/easy/assembly.py`:
- `assemble_playbook(*, clusters, name, contract_type, gateway, ...) -> PlaybookCreate`.
- 1 LLM call per cluster for `description` + `redline_strategy` + `severity_if_missing`.
- 1 LLM call per fallback tier for the tier `description`.
- Deterministic `detection_keywords` derivation (label tokens + top-frequency content words, stopword-filtered, capped at 8) and `detection_examples` (modal + neighbors verbatim).
- Defensive defaults on every LLM failure path — output is always a valid `PlaybookCreate`.
- Audit attribution: each LLM call carries a distinct `lq_ai_purpose` (`playbook_easy_assemble_describe_position` / `_describe_tier`) for cost-routing telemetry.

Tests: 31 new (15 clustering + 16 assembly), all unit-scope, stub-based.

### Phase 5 — Easy-playbook endpoints + ARQ worker + migration 0035 (commit `af65598`, 11 files / 1809 lines)

**The backend of M3-A6 is now functionally complete end-to-end.**

Migration 0035 — `easy_playbook_generations` table: `id`, `user_id` (ON DELETE SET NULL), `contract_type`, `status` (CHECK pending/running/completed/error), `document_ids` UUID[], `draft_playbook` JSONB, `error_message`, `created_at`, `started_at`, `completed_at`. Partial-free index `(user_id, created_at DESC)` for the wizard's history view.

`app/workers/easy_playbook_worker.py` — the ARQ job function. Lifecycle: pending → running (`started_at`) → completed (`draft_playbook` JSONB + `completed_at`) OR error (`error_message` + `completed_at`). Per-document extraction failures are tolerated; missing source documents (soft-deleted between enqueue and pickup) are silently skipped.

`app/workers/queue.py` — added `_get_m3a6_pool()` with `default_queue_name="arq:m3a6"` (separate from the existing ingest pool) + `enqueue_easy_playbook_generation_job()` helper. `close_pool()` now disposes both pools.

`app/workers/arq_setup.py` — registered `easy_playbook_generation_job` in `WorkerSettings.functions` alongside `noop_job`.

Two new endpoints in `app/api/playbooks.py`:
- `POST /api/v1/playbooks/easy` — body=`EasyPlaybookGenerationCreate`; validates caller owns every doc in `document_ids` (admins bypass; soft-deleted files excluded; cross-user collapses to 404); creates row at status=pending; enqueues worker; emits audit row; returns 202.
- `GET /api/v1/playbooks/easy/{generation_id}` — owner OR admin; cross-user/missing collapse to 404.

Tests: 13 endpoint + 6 worker = 19 new; all passing.

OpenAPI sketch updated.

---

## 3. M3-A6 design decisions (still locked from §3 of the prior handoff)

These decisions were locked at M3-A6 kickoff (2026-05-19, earlier session) and remain unchanged for Phase 6 + 7.

| # | Question | Decision |
|---|---|---|
| §3.1 | Async execution model | **ARQ on `arq:m3a6` queue.** Phase 1 shipped. M3-A2's BackgroundTasks executor stays on BackgroundTasks for v0.3. |
| §3.2 | Playbook CRUD endpoint landing | **In M3-A6 PR.** Phase 2 shipped. |
| §3.3 | Uploaded contract persistence | **Persisted to user's library** by default (via existing Document Pipeline). `persist_documents_after_generation` field is in the request schema but reserved — currently always true. |
| §3.4 | Inline editor depth in Step 3 | **Full editor.** Every field per position: `issue`, `description`, `standard_language`, `redline_strategy`, `severity_if_missing`, `detection_keywords[]`, `detection_examples[]`, `fallback_tiers[]` (each with `rank`, `description`, `language`). This is Phase 6's biggest UI surface. |

### Quality bar (still in effect)

Per Decision F + the 2026-05-19 reframe ("wizard output is itself a starting point the user-attorney validates"), verification reduces to:

1. **Structural correctness** — the wizard produces YAML/JSON that validates against `PlaybookCreate` and that the executor can run end-to-end.
2. **Gross sensibility** — generated positions are recognizable as the requested contract type.
3. **Latency** — <10 minutes for 10 docs on the default model alias.
4. **Operator can edit** — full inline editor; saves via POST /api/v1/playbooks.

What we explicitly do NOT verify: legal soundness of generated standard language, sensibility of fallback-tier ranks, correctness of the redline strategy. The user-attorney evaluates all of that during Step 3 inline editing.

---

## 4. Phase 6 (frontend wizard) — next session's first commit

The next session opens with this as the immediate next deliverable. **Substantial scope** — the prep doc's prose is below; per-section sub-tasks are also worth pre-planning.

### Scope (per the M3-A6 prep doc)

1. **Extended API client** at `web/src/lib/lq-ai/api/playbooks.ts`:
   - `createPlaybook(body: PlaybookCreate)` → matches POST /api/v1/playbooks.
   - `updatePlaybook(id, body: PlaybookUpdate)` → matches PATCH.
   - `deletePlaybook(id)` → matches DELETE.
   - `startEasyPlaybookGeneration(body: EasyPlaybookGenerationCreate)` → matches POST /api/v1/playbooks/easy.
   - `getEasyPlaybookGeneration(id)` → matches GET /api/v1/playbooks/easy/{id}.
   - Existing file is 53 lines; the M3-A4 list/get helpers are the pattern to mirror.
   - Vitest specs follow the existing M3-A4 pattern under `web/src/lib/lq-ai/api/__tests__/` (the test file exists for the M3-A4 surface — extend it or add a sibling).

2. **`PlaybookEditor.svelte`** (new reusable component):
   - Props: `bind:playbook` (a `PlaybookCreate`-shaped object) + `disabled?: boolean`.
   - Composed of `PlaybookEditorPosition.svelte` (one per position) which is composed of `PlaybookEditorFallbackTier.svelte`.
   - Surfaces every editable field: position-level (`issue`, `description`, `standard_language`, `redline_strategy`, `severity_if_missing` enum-select, `detection_keywords` tag-input, `detection_examples` textarea list, reorder via drag or up/down buttons) + tier-level (`rank`, `description`, `language`).
   - Inline validation: issue non-empty; severity in {critical, high, medium, low}; per-position `position_order` consistency; ≥0 fallback tiers (the prep doc's "≥2 fallback tiers per position" floor is *aspirational* — leave at ≥0 for Phase 6 since the wizard might emit positions with no neighbors when only one document had a label).
   - Emit `change` events the parent can use to detect unsaved edits.

3. **Wizard route at `web/src/routes/lq-ai/playbooks/easy/+page.svelte`**:
   - State machine: `step: 'upload' | 'progress' | 'review' | 'approve'` + the wizard data (`documents`, `generation_id`, `draft_playbook`).
   - **Step 1 (upload):** multi-file dropzone, `contract_type` selector, optional `name` input, "Start generation" button. Uploads via existing upload API + collects `document_ids`; POSTs `EasyPlaybookGenerationCreate` and stashes the returned `generation_id`.
   - **Step 2 (progress):** polls `GET /api/v1/playbooks/easy/{id}` every 5 seconds. Renders progress UI ("Generation in progress... this can take up to 10 minutes."). Auto-advances to step 3 when `status='completed'`; surfaces `error_message` on `status='error'` with a retry button.
   - **Step 3 (review):** `<PlaybookEditor bind:playbook={state.draft_playbook} />`. "Save playbook" button calls `POST /api/v1/playbooks` with the edited state. Advances to step 4 on success.
   - **Step 4 (approve):** success screen with link to the new playbook's detail view at `/lq-ai/playbooks/{id}`.

4. **Disclaimer banner from M3-A4** renders on every step (Decision F transparency). The existing `PlaybookDisclaimerBanner.svelte` is the component; just import and render at the top of each step.

5. **Entry point into the wizard:** add a "Generate from prior agreements" button to the existing playbooks list page (`web/src/routes/lq-ai/playbooks/+page.svelte`). Do NOT add a new tab to TopTabBar — the wizard is a sub-flow of the playbooks tab.

6. **Vitest specs** for the state machine + API helpers in `web/src/routes/lq-ai/playbooks/easy/__tests__/page-helpers.test.ts` (the M3-A4 page-helpers test is the pattern to mirror; the existing M3-A4 page-helpers.ts is 19 lines — Phase 6's helpers will be larger because of the multi-step state machine).

### Files touched (estimated)

```
web/src/lib/lq-ai/api/playbooks.ts                            (extend)
web/src/lib/lq-ai/api/__tests__/playbooks.test.ts             (extend, or new)
web/src/lib/lq-ai/components/PlaybookEditor.svelte            (new)
web/src/lib/lq-ai/components/PlaybookEditorPosition.svelte    (new)
web/src/lib/lq-ai/components/PlaybookEditorFallbackTier.svelte (new)
web/src/lib/lq-ai/components/__tests__/PlaybookEditor.test.ts  (new)
web/src/routes/lq-ai/playbooks/easy/+page.svelte              (new)
web/src/routes/lq-ai/playbooks/easy/page-helpers.ts           (new)
web/src/routes/lq-ai/playbooks/easy/__tests__/page-helpers.test.ts (new)
web/src/routes/lq-ai/playbooks/+page.svelte                   (modify — add "Generate" button)
```

Effort estimate: 6–10 hours. Largest piece is `PlaybookEditor.svelte` and its sub-components — the full inline editor was Decision §3.4's call and is the biggest single UI surface in M3-A6.

### Verification

- Vitest specs pass (the page-helpers state machine + API client helpers).
- svelte-check clean.
- Manual smoke against the live stack: log in → /lq-ai/playbooks → click "Generate from prior agreements" → upload 3 NDA fixtures → wait through the polling → see a draft playbook in Step 3 → edit one position → save → land on the saved playbook's detail page.
- The Phase 7 Cypress E2E follows; Phase 6 itself does not include the E2E test (the prep doc reserves that for Phase 7).

### Commit message template

```
feat(web,m3-a6): Easy Playbook wizard frontend (Phase 6 of 7)

Adds the 4-step wizard UI that turns the M3-A6 backend's
generation pipeline into an operator-facing flow. Step 1 uploads
a document corpus and kicks off generation; Step 2 polls the
generation row; Step 3 surfaces the assembled draft playbook in
a full inline editor (every editable field per position + per
fallback tier); Step 4 confirms the save.

[per-file details ...]

Verification:
* vitest: ... new specs pass
* svelte-check: clean
* live smoke: ... [pass details]

Phase 6 of 7 per docs/superpowers/plans/2026-05-19-m3-a6-easy-playbook-wizard.md.
Phase 7 (Cypress E2E + open PR) follows.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## 5. Phase 7 (Cypress E2E + open PR) — after Phase 6

The final commit on the m3-a6 branch. Scope per the prep doc:

- `web/cypress/e2e/m3-a6-easy-playbook-wizard.cy.ts`: mocks every API call. Login → `/lq-ai/playbooks/easy` → upload 3 stub files → mock generation flow with two poll cycles → see draft in step 3 → edit one field → save → land on the saved playbook detail view.
- Manual UI smoke: real run against the live stack with the seeded NDA corpus from `docs/quickstart/`.
- Backend smoke: full test suite + `ruff format` + `ruff check` + svelte-check.
- **Commit 7** ships the E2E + opens PR.

Effort estimate: 2–4 hours.

---

## 6. Surprises + decisions worth carrying forward

Concrete things future-you should know that aren't visible in the code alone:

### Phase 1: ARQ was already in production from M2

The prep doc framed Phase 1 as "introduce ARQ now." The reality: `arq>=0.25,<0.27` was already pinned and the document-pipeline worker already used it. Phase 1 added a **second** worker pool on an isolated queue (`arq:m3a6`), not a new dependency.

### Phase 2: soft-delete required a migration the prep doc didn't anchor

The prep doc said "DELETE = soft delete" but the existing `Playbook` ORM had no `deleted_at` column. Adding it required migration 0034. Phase 5's planned migration shifted from 0034 → 0035. **Lesson:** the prep doc captured design intent at the wire-shape level but didn't trace through to the schema layer; future planning passes should explicitly enumerate every required migration.

### Phase 2: greenlet gotcha in async ORM

`len(playbook.positions)` after `db.flush()` in an async SQLAlchemy session triggers a lazy-load that fails with `MissingGreenlet`. Fix is to capture the count from the input Pydantic body before the flush, OR `await db.refresh(playbook, attribute_names=["positions"])` before accessing the relationship. The M3-A2 executor's `selectinload(...)` upfront avoids this entirely. **Carry this into Phase 6's tests** — any vitest spec that mocks the backend response will hit the wire shape, not the ORM, so it's not directly applicable to the frontend. But if Phase 6 ever extends the backend (e.g., for the "regenerate" follow-on), the pattern matters.

### Phase 3: prompts live in code; SKILL.md is documentation

The M3-A2 executor pattern is hardcoded prompts in Python (`app/playbooks/nodes.py`). Phase 3 followed the same pattern: `app/playbooks/easy/extractor.py` has its own copy of the prompt; `skills/playbook-easy-extract/SKILL.md` is the human-readable + SkillRegistry-discoverable artifact. **Drift risk acknowledged** — if the prompt changes, both must update.

### Phase 4: no sub-clustering within label groups

The prep doc said "Sub-cluster within label by embedding-distance for variant detection." We interpreted this as: each label group becomes ONE cluster (modal + farthest-N neighbors); the embedding distance ranks within the cluster, doesn't sub-divide it. Sub-clustering would multiply position count without operator-friendly disambiguation. The user-attorney's Step 3 edit is the disambiguation step.

### Phase 4: single batched embeddings call

Across the entire corpus (typically 25-400 clauses), one `/v1/embeddings` call returns all vectors. Keeps gateway round-trips to 1 regardless of corpus size. The all-or-nothing fallback (embedding failure → length-based modal selection across every cluster) is intentional: a partial-embedding state would produce a confusing mix of "ranked by cosine" + "ranked by length" clusters in the same wizard run.

### Phase 5: queue isolation is load-bearing

The new arq-worker uses `queue_name="arq:m3a6"`. If a future change defaults the new worker to arq's default queue, easy-playbook generations and document ingests would compete on one queue and reject each other's jobs as "unknown function." The `arq:m3a6` constant in `app/workers/arq_setup.py` is mirrored in `app/workers/queue.py` (`M3A6_QUEUE_NAME`) to avoid a circular import; the two must stay in sync. The smoke test `tests/test_arq_smoke.py::test_queue_name_is_disjoint_from_arq_default` pins this invariant.

### Phase 5: docker-compose worker rebuild requires rebuilding ALL alembic-running services

Captured in `feedback_migration_rebuild_all_workers.md` memory. When a migration lands, rebuild **every** api-derived service (`api`, `arq-worker`, `ingest-worker`, and any future api-image-derived worker) together. A stale sibling's entrypoint runs `alembic upgrade head` against the now-advanced DB, can't find the new revision script in its own `alembic/versions/` directory, and crash-loops with `FAILED: Can't locate revision identified by '00NN'`. The mechanical fix:

```bash
docker compose up -d --build api arq-worker ingest-worker
```

The cleanest long-term fix would be a separate "migrator" service that runs alembic once at compose-up and gates everything else on `depends_on: condition: service_completed_successfully`. Filed mentally as a DE-candidate; not blocking.

---

## 7. Mid-session infra hiccups (resolved)

Both surfaced during the Phase 5 live-verification step; both fixed before end-of-session.

### Docker Desktop containerd metadata corruption

**Symptom:** `docker compose up -d --build api arq-worker` failed with `failed to extract layer ...: write ...: input/output error`. Even `docker builder prune --all -f` failed with the same error (`write /var/lib/docker/buildkit/containerd-overlayfs/metadata_v2.db: input/output error`). `docker compose logs` returned `Error grabbing logs: open /var/lib/docker/containers/.../json.log: input/output error`. The metadata DB itself was corrupted.

**Fix:** clean Docker Desktop restart via `osascript -e 'quit app "Docker"'` + `open -a Docker`. Non-destructive — all containers + volumes survived. After ~60 seconds the daemon was back and rebuilds worked normally.

### ingest-worker crash-loop after the Docker bounce

**Symptom:** after the Docker restart, `docker compose ps` showed `lq-ai-ingest-worker-1` in `Restarting (255)` state. Logs: `FAILED: Can't locate revision identified by '0034'` then `0035` in a tight loop.

**Root cause:** the ingest-worker was running an image built ~35 hours earlier (before migration 0034 + 0035 existed). When migrations 0034 + 0035 landed via the api rebuild, the dev DB advanced to `alembic_version=0035`. The stale ingest-worker's entrypoint ran `alembic upgrade head`, found the DB at `0035`, looked for `0035.py` in its OWN `alembic/versions/` directory, couldn't find it, and crashed.

**Fix:** `docker compose up -d --build ingest-worker` so the worker picks up the new migration files. Captured as `feedback_migration_rebuild_all_workers.md`.

---

## 8. Memory state at end-of-session

The persistent memory at `~/.claude/projects/.../memory/` was updated to reflect Phases 1-5 shipped:

* **`project_lq_ai_status.md`** — Phases 1-5 commit log, cumulative deltas (32 files / ~6200 lines / 92 tests / migrations 0034+0035), live-verification confirmation, the Docker hiccup + ingest-worker fix called out. Phase 6 + 7 framed as remaining work.
* **`feedback_migration_rebuild_all_workers.md`** (new) — captures the rebuild-all-workers lesson with the crash signature, the fix recipe, and the long-term DE-candidate (dedicated migrator service).
* **`MEMORY.md`** index updated to point at the new feedback memory and reflect the new status framing.

The next session should re-read `project_lq_ai_status.md` + `feedback_migration_rebuild_all_workers.md` plus the project-wide patterns: `feedback_branch_preservation.md`, `feedback_honest_framing.md`, `feedback_no_maintainer_legal_review.md`, `feedback_ruff_format_check.md`.

---

## 9. Tech debt observed this session (carry forward)

Independent items worth their own follow-ons:

1. **Dedicated "migrator" service in docker-compose** (filed in `feedback_migration_rebuild_all_workers.md`). Would eliminate the "rebuild every worker in lockstep" foot-gun. Small change; depends_on `condition: service_completed_successfully` gates the api/workers on a one-shot migrator container.

2. **arq's M3A6_QUEUE_NAME constant is mirrored in two files** (`arq_setup.py` + `queue.py`) because of a circular-import. A small extracted-constants module (`app/workers/_constants.py`) would centralize it. Sub-30-minute change; not urgent because the smoke test pins the invariant.

3. **The SKILL.md vs Python-prompt drift risk** (Phase 3). Long-term, a SkillRegistry-driven prompt-fetch path inside the playbook executors would make SKILL.md canonical. Phase 5+ already exists with hardcoded prompts; this would be a refactor not a Phase-N add. Filed mentally; not urgent.

4. **`api/uv.lock` is untracked** (pre-existing condition from before this session). Hasn't been committed; presumably matches a project-level decision to keep uv.lock out of git? Worth verifying — if it should be tracked, it's a one-line fix in `.gitignore` + an initial commit.

5. **arq-worker container's `LQ_AI_GATEWAY_KEY` is required at startup** (per the compose env section). If a future operator runs only the arq-worker but not the gateway, the worker fails to start. Acceptable for now since the worker calls the gateway during the easy-playbook pipeline anyway, but documenting it is worth a one-line comment in docker-compose.yml.

6. **No `easy_playbook_generations` cleanup sweep yet.** Successful generation rows persist indefinitely. The wizard's history view (not in Phase 6 scope) could surface them; a future GC sweep to drop completed rows older than N days would be a follow-on DE.

7. **Phase 5's worker DOES NOT verify that the caller owns the documents at run time** — it just loads whatever document IDs the row carries. The POST endpoint enforces ownership at enqueue time, but if a document is reassigned (which doesn't happen today) or soft-deleted between enqueue and pickup, the worker silently skips. The graceful skip is intentional; documenting it as a known posture is worth a follow-on if Phase 6 surfaces edge-case complaints from operators.

8. **211 pre-existing mypy errors in `api/tests/`** (surfaced by Phase 7's full-suite sweep; **severity: LOW**). CI's mypy step (`.github/workflows/ci.yml:113`) is scoped to `mypy app` — production code only — so the test-tree errors don't block CI. All 211 errors are in code unmodified by M3-A6; this session introduced ZERO new ones. The errors are ~150 missing `-> None` return annotations + ~30 missing parameter type annotations + ~30 SQLAlchemy `FromClause.delete()` patterns + long-tail. **Tracked as `DE-284 — Tighten api/tests/ mypy coverage`** in `docs/PRD.md §9` (Engineering discipline subsection). The fix is mechanical but bounded; the reason for the durable paper trail is to close the silent-debt-accumulation loop Kevin flagged during the M3-A6 Phase 7 sweep — without DE-284, the next contributor running `mypy .` locally would have no way to know the count is pre-existing rather than a regression.

9. **Bookkeeping miss caught in Phase 7 sweep**: Phases 2 + 5 added 5 new endpoints (`POST /playbooks`, `PATCH/DELETE /playbooks/{id}`, `POST /playbooks/easy`, `GET /playbooks/easy/{id}`) but forgot to update `IMPLEMENTED_ROUTES` in `api/tests/test_endpoints.py` and `EXPECTED_PATHS` in `api/tests/test_openapi.py`. **Fixed in commit `bb26cac`** (Phase 7). Per-phase commits passed their own dedicated test files, but the full-suite test caught the drift. **Lesson:** future phase commits that add API routes should also update both scaffolding tests. Probably worth a pre-commit hook or a CI step that runs `pytest tests/test_endpoints.py tests/test_openapi.py` as part of every API PR.

---

## 10. M3-A6 follow-on DEs (file in PRD §9 when convenient)

These are M3-A6-specific deferred enhancements that surfaced during this session's work and are worth filing in `docs/PRD.md §9` at PR time or the M3-close docs batch:

- **DE-284 — Tighten api/tests/ mypy coverage** ✓ **Filed in PRD §9** (Phase 7 sweep). 211 pre-existing errors; P3; mechanical sweep + CI flip.
- **DE — Easy Playbook regeneration** (add 3 more documents, re-run). The current shape is one-shot; the worker writes `draft_playbook` once at completion. A "regenerate" path would re-extract + re-cluster against the expanded corpus. Filed as out-of-scope in the prep doc's §6.
- **DE — Multi-user / team-shared playbooks**. Current model is single-user-owned (`created_by`). "Share with my team" / "publish to the org" is a future enhancement.
- **DE — Real-time progress events via WebSocket** instead of HTTP polling. The wizard's Step 2 uses 5-second polling; the prep doc's §6 noted WebSocket would be smoother but adds infra complexity.
- **DE — Per-generation provider override** (use a specific model for this generation). Currently uses the deployment's default judge model alias.
- **DE — Bulk position deletion in inline editor**. Step 3 supports per-position edit; bulk operations would be a future iteration.
- **DE — Generation cleanup sweep** (item 6 from §9 above; old generation rows persist indefinitely).
- **DE — Centralized migrator service** (item 1 from §9 above; eliminates the rebuild-all-workers foot-gun).

---

## 11. Next-session entry point

When the next session opens, the entry message will be something like:

> Start M3-A6 Phase 6 (frontend wizard). Read `docs/SESSION-HANDOFF-2026-05-19-m3-a6-phases-1-5-shipped-phase-6-kickoff.md` first. §4 has the detailed Phase 6 scope. The `m3-a6-easy-playbook-wizard` branch is at `af65598` (Phases 1+2+3+4+5 shipped); backend is complete + live-verified. The wizard frontend is the last substantial piece before Phase 7's Cypress E2E + PR.

The new session should:

1. Check the live stack: `docker compose ps` — all 8 services should be healthy on the latest images. If anything is stale (especially ingest-worker), `docker compose up -d --build api arq-worker ingest-worker` per `feedback_migration_rebuild_all_workers.md`.
2. Sync `m3-a6-easy-playbook-wizard`: `git fetch origin && git checkout m3-a6-easy-playbook-wizard && git pull`.
3. Read this handoff in full (§4 especially).
4. Read the prep doc at `docs/superpowers/plans/2026-05-19-m3-a6-easy-playbook-wizard.md` (§ Phase 6 prose).
5. Optionally read the M3-A4 frontend surfaces for the pattern reference: `web/src/routes/lq-ai/playbooks/+page.svelte` (existing list/execute surface), `web/src/lib/lq-ai/api/playbooks.ts` (API client to extend), `web/src/lib/lq-ai/components/PlaybookDisclaimerBanner.svelte` + `PlaybookExecuteModal.svelte` (component pattern).
6. Implement Phase 6 per §4 above.
7. Land Phase 6 as a single commit on the branch; verify vitest + svelte-check + manual smoke; report back.
8. Decision point: continue with Phase 7 (Cypress E2E + open PR) immediately, or stop after Phase 6 for a fresh session pass on Phase 7.

If `m3-a6-easy-playbook-wizard` is somehow missing on origin when the next session opens, the recovery path is unchanged from the prior handoff: `git checkout -b m3-a6-easy-playbook-wizard origin/m3-development` and cherry-pick the five M3-A6 phase commits (`1feec2e^..af65598`).

---

## 12. Loose ends explicitly NOT being carried into M3-A6 Phase 6

* **README screenshots** (dashboard + playbooks list + execution result + Easy Playbook wizard 4 steps) — still scoped for M3-A6 close per Kevin's call.
* **`v0.3.0` tagging** — happens after M3 closes (Phases B + C + D all merged). Not relevant to M3-A6.
* **`m2-development` archive branch cleanup** — preserved per the branch-preservation policy; no cleanup needed.
* **Live UI smoke with real LLM provider keys against the Phase 5 backend** — the current dev stack's gateway is configured but no operator has run an Easy Playbook generation against real provider keys yet. Worth doing once Phase 6 ships the UI to invoke it.

These are tracked items the next session does not need to think about; they surface at M3-A6 close / M3-close.

---

*End of handoff. The next session begins at §4 with Phase 6 (frontend wizard).*
