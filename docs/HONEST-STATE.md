# Honest State

> Catalog of what LQ.AI ships today, what is deferred, and how to verify each. Maintained per release. **Current as of the M4 close plus the post-v0.4.0 "Donna" run (#115–#139); migration head `0047`.**

## What this doc is

This document catalogs what LQ.AI ships today, what is deferred, and how an operator can verify each. We publish it in source because the verification path for an open-source project terminates in code, not in a vendor's marketing claims. If you find a discrepancy between this doc and the codebase, the codebase is canonical; please [open an issue](https://github.com/LegalQuants/lq-ai/issues).

## How to read this

Each table has three columns:

- **Capability** — what the operator gets.
- **Status** — `M1`/`M2`/`M3`/`M4` (shipped today, naming the milestone it landed in; a sub-tag like `M4` or `M3` may name a specific phase for context), `partial` (shipped with explicit caveats, named inline), `scaffold` (plumbing only, feature work deferred), or `deferred-Mx` / `deferred (community-friendly)` for roadmap or [PRD §9](PRD.md#9-deferred-enhancements-and-identified-future-work) items not yet wired in source.
- **Verification** — the file path, test command, or doc the operator can read to confirm the claim.

Status markers reference the roadmap milestones (M1 → M4) documented in [README.md](../README.md#project-status) and [PRD §8](PRD.md#8-roadmap).

## Where M1–M4 sit

**M1 — Foundation (shipped).** Self-hostable conversational legal AI on the starter skills, with the engineering surfaces (audit, tier enforcement, projects/matters, knowledge bases + ingestion, saved prompts, receipts, the skill-creator pipeline) that later milestones build on. Provider adapters: Anthropic, OpenAI, Ollama (local Tier 1).

**M2 — Citation Engine + Anonymization Layer (shipped).** The four-stage citation verification cascade (exact → tolerant → paraphrase judge → ensemble) and the gateway anonymization middleware (Presidio + custom legal recognizers, streaming-aware rehydration, privileged + retrieval skips) both ship operational. The Azure OpenAI provider adapter rounds out the provider set.

**M3 — Playbooks · Tabular Review · Word add-in · Slack/Teams intake bridge (shipped, with two honest caveats).**
- **Playbooks** and **Tabular / multi-document review** ship operational end-to-end (real execution against documents, with cost tracking and export).
- The **Word add-in** ships as a **scaffold** — installable, authenticatable, version-safe — but its substantive in-Word feature surfaces (chat, skills with tracked changes, playbook execution) are deferred ([DE-287](PRD.md#9-deferred-enhancements-and-identified-future-work)); today its tabs deep-link to the web app.
- The **Slack/Teams light intake bridge** ships **partial** — the bridge services, OAuth install flows, encrypted persistence, and admin management are wired and unit-tested, but the flows have **not been exercised end-to-end against live Slack/Microsoft endpoints** ([DE-312](PRD.md#9-deferred-enhancements-and-identified-future-work)), and the `/lq` slash-command surface is inert ([DE-288](PRD.md#9-deferred-enhancements-and-identified-future-work)).

**M4 — Autonomous Layer (shipped).** The background autonomous executor runs real in-loop work: a five-phase LangGraph state machine (intake → analysis → drafting → ethics_review → delivery) where every external action routes through a single `guarded_tool_call` chokepoint enforcing three brakes — R4 (per-session/per-trigger cost cap), R5 (external halt + idle watchdog), R6 (phase-gated tool grants). It ships the four primitives (watches, schedules, per-user memory, precedent board), honest per-session receipts, per-user opt-in, and a full web dashboard. The **Contract Repository auto-relationship graph** (a separate M4-roadmap capability) is **not** built.

**The honest reading:** an operator can deploy LQ.AI today for everyday in-house work on the starter skills, with character-verified citation grounding, operator-configurable pseudonymization, codified-position playbooks, multi-document tabular review, and an opt-in autonomous background layer with hard economic/temporal/contextual brakes. The deferred edges are: in-Word feature surfaces (scaffold today), live-verified chat-platform intake (plumbing today), the contract relationship graph, and the MCP client subsystem.

---

## 1. Conversational and workspace surface (M1)

The surface in-house counsel touches every day. Every row is wired end-to-end in M1.

| Capability | Status | Verification |
|---|---|---|
| Multi-turn chat with persistent history | M1 | `api/app/api/chats.py`; `web/cypress/e2e/chat.cy.ts` |
| Matter (project) workspace with attached files / skills / KBs | M1 | `api/app/api/projects.py`; `web/src/routes/lq-ai/matters/[id]/+page.svelte` |
| Slash-invoked skills with provenance pill | M1 | `web/cypress/e2e/wave-d2-skill-creator.cy.ts` Test 4 |
| Built-in starter skills | M1 | `skills/*/SKILL.md` (read every prompt — no hidden instructions) |
| Community skill catalog via [`LegalQuants/lq-skills`](https://github.com/LegalQuants/lq-skills) submodule | M1 (opt-in) | `skills/community/` is a git submodule, **empty until initialized** — run `git submodule update --init --remote skills/community` to populate it. The loader walks built-in + community paths with built-in winning on slug collision (`api/app/skills/loader.py`); on a fresh clone with no submodule checkout there are no community skills. |
| Skill capture / wizard authoring / fork / versions tab | M1 | `web/cypress/e2e/wave-d2-skill-creator.cy.ts` Tests 1–6 |
| Saved Prompts library with one-click "Use in chat" | M1 | `api/app/api/saved_prompts.py`; `web/cypress/e2e/wave-m1-final-surfaces.cy.ts` Test 1 |
| Knowledge bases — create, attach documents, ingest to `ready` (hybrid BM25 + vector retrieval) | M1 | `api/app/api/knowledge_bases.py`; `api/app/workers/document_pipeline.py` |
| Receipts drawer with per-event provenance | M1 | `api/app/api/chat_receipts.py`; `web/cypress/e2e/wave-m1-final-surfaces.cy.ts` Test 3 |
| Enhance Prompt (⌘E) | M1 | `api/app/api/enhance_prompt.py` |
| Audit log of all sensitive actions | M1 | `api/app/audit.py`; admin reads at `/lq-ai/admin/audit-log` |
| FTS over chat history | M1 | `api/app/api/chats.py` (search route); migration `0016_chat_messages_fts.py` |
| GDPR-aligned export and account deletion | M1 | `api/app/workers/user_export.py`; `api/app/workers/user_deletion.py`; `api/app/api/users.py` |
| Per-message ephemeral file attach (`MessageCreate.file_ids` → `applied_file_ids` echo; separate channel from `skill_inputs`, injected as document-context per Decision M2-1) | post-v0.4.0 (#116/#117) | `api/app/schemas/chats.py` (`file_ids`, `applied_file_ids`); `api/app/schemas/gateway.py` (`lq_ai_file_ids`) |
| Self-service profile edit (`PATCH /api/v1/users/me`, `display_name` only; email is [DE-329](PRD.md#9-deferred-enhancements-and-identified-future-work)) | post-v0.4.0 (#118) | `api/app/api/users.py` |
| Pending-deletion visibility (`deletion_scheduled_at` on `GET /users/me`; `/users/me/delete/cancel` clears it) | post-v0.4.0 (#120) | `api/app/api/users.py` |

---

## 2. Inference gateway and providers

The Inference Gateway is the security boundary — the only component holding privileged provider API keys and the only component making outbound calls to inference providers. Four provider adapters ship: Anthropic, OpenAI, Azure OpenAI, Ollama (local Tier 1). Google Vertex AI and AWS Bedrock are spec'd in PRD §9 as contributor-friendly work and remain deferred.

| Capability | Status | Verification |
|---|---|---|
| Inference gateway with provider routing | M1 | `gateway/app/router.py` |
| Anthropic / OpenAI / Ollama provider adapters | M1 | `gateway/app/providers/{anthropic,openai,ollama}.py`; Ollama via `docker compose --profile local` |
| Azure OpenAI provider adapter | M2 | `gateway/app/providers/azure_openai.py` ([DE-267](PRD.md#9-deferred-enhancements-and-identified-future-work), closed in M2) |
| Google Vertex AI / AWS Bedrock provider adapters | deferred (community-friendly) | Wire-format specs in PRD §9 (DE-034 / DE-035) |
| Tier enforcement (Tiers 1–5) + privileged-matter tier floor | M1 | `gateway/app/tier_floor.py` |
| Anonymization pre/post middleware | M2 | `gateway/app/anonymization/middleware.py` (wired on the request path at `gateway/app/api/inference.py`); see §3.2. Recognizer accuracy on a legal corpus is empirically unmeasured — [DE-282](PRD.md#9-deferred-enhancements-and-identified-future-work). |
| Routing log (per-inference) | M1 | `gateway/app/routing_log.py` |
| Provider-key encryption at rest (Fernet master-key) | M1 | `gateway/app/secrets.py`; `docs/security/encrypted-keys.md` |
| Hot-reload of gateway config via SIGHUP | M1 | `gateway/app/config_holder.py`; `docs/adr/0010-gateway-config-hot-reload.md` |
| Runtime provider keys / BYOK (gateway `/admin/v1/provider-keys` + backend is_admin proxy `/api/v1/admin/provider-keys`; GET masked last4/configured/source `env`\|`runtime`; POST Fernet-encrypts into `gateway.yaml` and hot-applies the adapter in-place with no restart; PATCH rotates, DELETE revokes; requires `LQ_AI_GATEWAY_MASTER_KEY` else 400 `failed_precondition`; env keys still work and show source `env`) | post-v0.4.0 (#128) | `gateway/app/provider_keys.py`, `gateway/app/api/admin.py`; `api/app/api/admin.py` (proxy); `api/app/clients/gateway.py` |

---

## 3. M2 — Citation Engine and Anonymization Layer (shipped)

### 3.1 Citation Engine — 4-stage cascade

Character-level verification of every model-emitted citation against source documents; failed citations surface as "unverified" rather than confident wrong text.

- **Cascade** (`api/app/citation/verification.py`): Stage 1 `verify_exact_match` → Stage 2 `verify_tolerant_match` (rapidfuzz ≥95 + normalization) → Stage 3 `verify_paraphrase` (LLM judge via gateway) → Stage 4 `verify_ensemble` (N-model parallel, strict/majority, cost-budget fallback to Stage 3).
- **Endpoint:** `GET /api/v1/chats/{chat_id}/messages/{message_id}/citations`; rows persist in `message_citations` (migrations `0025`–`0027`). Candidates that miss every stage are not persisted — the UI reads the absence as "unverified" (red).
- **Verify:** `cd api && pytest tests/citation/ tests/test_chat_citations.py`; full reference in [`docs/citation-engine.md`](citation-engine.md).
- **Known limitation:** a quote spanning two retrieved chunks silently drops at extraction ([DE-277](PRD.md#9-deferred-enhancements-and-identified-future-work); pinned by `api/tests/citation/test_edge_cases.py`).

### 3.2 Anonymization Layer — gateway middleware

Pseudonymizes named entities before requests leave for the provider; rehydrates originals on the response path (streaming-aware). **The middleware is wired and running** — `pre_anonymize_request` is called on the request path in `gateway/app/api/inference.py` after tier derivation, before provider dispatch.

- **Recognizers** (`gateway/app/anonymization/engine.py`): Presidio defaults (`PERSON`, `ORGANIZATION`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION` via spaCy `en_core_web_lg`) + custom `CaseNumberRecognizer` + `MatterNumberRecognizer`.
- **Skip conditions** (any one short-circuits): master switch off; Tier 1 (local); privileged chat; per-request opt-out (citation judge calls use this); per-message retrieval-context skip (so the model sees intact source quotes for citation grounding).
- **Mapper** is per-request, in-memory only — never persisted, never logged.
- **Verify:** `cd gateway && pytest tests/anonymization/ tests/test_inference_anonymization.py`; full reference in [`docs/security/anonymization.md`](security/anonymization.md). Open surfaces: pseudonymize-source-docs ([DE-269](PRD.md#9-deferred-enhancements-and-identified-future-work)), per-request salt ([DE-274](PRD.md#9-deferred-enhancements-and-identified-future-work)).

---

## 4. M3 — Playbooks · Tabular Review · Word add-in · Intake bridges

### 4.1 Playbooks — shipped

Codified legal positions with detection + redline strategy, plus an "easy" auto-generation pipeline from a document corpus.

| Capability | Status | Verification |
|---|---|---|
| Playbook CRUD + execute against a document | M3 | `api/app/api/playbooks.py` (`GET/POST/PATCH/DELETE /api/v1/playbooks`, `POST /playbooks/{id}/execute`, `GET /playbook-executions/{id}`); executor `api/app/playbooks/` |
| Built-in seeded playbooks (NDA mutual/unilateral, MSA, DPA) | M3 | migrations `0032`/`0033`; `cd api && pytest tests/test_builtin_nda_playbooks.py` |
| Easy playbook auto-generation (3-stage) | M3 | `POST /api/v1/playbooks/easy` + `GET /playbooks/easy/{id}`; migration `0035` |
| Tables: `playbooks`, `playbook_positions`, `playbook_executions`, `easy_playbook_generations` | M3 | migrations `0031`, `0035` |
| Learn viz | M3 | `web/static/learn/playgrounds/playbook-cascade.html` |

**Caveats (honest):** execution runs in-process via FastAPI BackgroundTasks (not arq) per the M3 architecture decision; soft-delete only; built-ins are immutable (admins fork to edit); tracked-changes rendering into Word is deferred ([DE-287](PRD.md#9-deferred-enhancements-and-identified-future-work)).

### 4.2 Tabular / multi-document review — shipped

Run a skill (or ad-hoc column spec) across a document corpus into a document × column grid with per-cell confidence + citations; export XLSX/CSV.

| Capability | Status | Verification |
|---|---|---|
| Cost preview · execute · list · get · cancel · soft-delete | M3 | `api/app/api/tabular.py`; arq job `api/app/workers/tabular_worker.py`; table `tabular_executions` (migration `0036`) |
| Export to XLSX (cell comments) / CSV (citation links) | M3 | `GET /api/v1/tabular/executions/{id}/export` |
| Column-spec snapshot at execution start (auditable invariant) | M3 | `api/app/models/tabular.py` (columns JSONB snapshot) |
| Navigable per-cell citations (read-side `source_file_id`/`source_page`/`source_text` enrichment on `GET /tabular/executions/{id}`, two batched IN-queries; existing executions included; NOT Citation-Engine-minted — [DE-309](PRD.md#9-deferred-enhancements-and-identified-future-work); untyped in gen:api — [DE-330](PRD.md#9-deferred-enhancements-and-identified-future-work)) | post-v0.4.0 (#125) | `api/app/api/tabular.py` (enrichment); `api/app/schemas/tabular.py` (`source_file_id`/`source_page`/`source_text`) |
| Per-column ensemble verification honored at execution (ensemble cells run one Stage-4 ensemble pass over cited chunks; `verification_method` `ensemble_strict`/`ensemble_majority`/None persisted on cells + mirrored onto citations; preview adds `ensemble_cells_count` + `ensemble_premium_usd`, included in `estimated_cost_usd`; precedence column > skill snapshot > deployment default; no mid-run ceiling — [DE-331](PRD.md#9-deferred-enhancements-and-identified-future-work)) | post-v0.4.0 (#127) | `api/app/tabular/nodes.py` (`_verify_cell_ensemble`), `api/app/tabular/cost.py`; `api/app/schemas/tabular.py` |
| Learn viz | M3 | `web/static/learn/playgrounds/tabular-review.html` |

**Caveat (honest):** tabular has unit/component backend coverage (`api/tests/tabular/` — nodes, cost, export, schemas, worker, executor-spans), but no per-endpoint integration test driving the handlers end-to-end against a live DB yet — a known gap. Bulk-op sibling infrastructure (`parent_execution_id`) is present but not yet exercised.

### 4.3 Word add-in (Office.js) — scaffold only

| Capability | Status | Verification |
|---|---|---|
| Installable Office.js add-in (manifest, task pane, React shell) | scaffold (M3) | `word-addin/manifest.xml`, `word-addin/src/taskpane/` |
| Admin manifest download + version handshake | M3 | `api/app/api/word_addin.py` (`GET /api/v1/admin/word-addin/manifest`, `GET /api/v1/word-addin/version`) |
| OAuth sign-in (reuses `/auth/login` + refresh) | M3 | `word-addin/src/taskpane/auth.ts`; `web/src/routes/lq-ai/word-addin/oauth-start/` |
| Learn viz | M3 | `web/static/learn/playgrounds/word-addin-flow.html` |
| In-Word chat / skills (tracked changes + comments) / playbook execution | **deferred** | The three tabs render deep-link cards to the web app, not in-Word feature surfaces — [DE-287](PRD.md#9-deferred-enhancements-and-identified-future-work) |

**Honest assessment:** the add-in is installable, authenticatable, and version-safe, but every substantive feature surface is a placeholder pointing to the web app. Do not market it as feature-shipped.

### 4.4 Slack / Teams light intake bridge — partial

| Capability | Status | Verification |
|---|---|---|
| Slack bridge service + OAuth install + encrypted persistence | partial (M3) | `slack-bridge/` (compose `--profile slack`, port 8002); table `slack_workspaces` (migration `0037`, Fernet-encrypted bot token under a distinct master key); `api/app/api/integrations_slack.py` |
| Teams bridge service + multi-tenant admin-consent OAuth | partial (M3) | `teams-bridge/` (compose `--profile teams`, port 8003); table `teams_tenants` (migration `0038`); `api/app/api/integrations_teams.py` |
| Admin intake-bridges management (list + soft-delete) | M3 | `api/app/api/admin_intake_bridges.py`; `web/src/routes/lq-ai/admin/intake-bridges/+page.svelte` |
| `/lq` slash-command intake surface | **deferred** | Webhook handler is signature-verified but inert — [DE-288](PRD.md#9-deferred-enhancements-and-identified-future-work) |
| End-to-end OAuth against live Slack/Microsoft | **unverified** | Never exercised against a live tunnel — [DE-312](PRD.md#9-deferred-enhancements-and-identified-future-work); see [`docs/intake-bridges.md`](intake-bridges.md) "Honest state up front" |

---

## 5. M4 — Autonomous Layer (shipped)

An opt-in background executor that does real in-loop agentic work under hard brakes. **Not a skeleton** — each phase calls real tools through the chokepoint. Full reference: [`docs/autonomous-layer.md`](autonomous-layer.md).

| Capability | Status | Verification |
|---|---|---|
| Five-phase executor (intake → analysis → drafting → ethics_review → delivery) | M4 | `api/app/autonomous/executor.py`, `nodes.py`; arq job `autonomous_session_job` |
| Real in-loop work: `run_skill`/`run_playbook` inference, `emit_finding`, `propose_memory`, `propose_precedent`, `notify` | M4 | `api/app/autonomous/guard.py` (`_dispatch`); `cd api && pytest tests/autonomous/test_executor_real_work.py` |
| Single chokepoint `guarded_tool_call` enforcing R5 → R6 → R4 | M4 | `api/app/autonomous/guard.py`; `tests/autonomous/test_executor_skeleton.py::test_no_tool_call_bypasses_chokepoint` |
| **R4** per-session **and** per-trigger cost cap (`max_cost_usd`) | M4 | `api/app/autonomous/cost.py`; migration `0045`; `tests/autonomous/test_r4_per_trigger_cap.py` |
| **R5** external halt (`POST /autonomous/sessions/{id}/halt`) + idle watchdog | M4 | `api/app/workers/autonomous_worker.py` (idle cron); `tests/autonomous/test_idle_watchdog.py` |
| **R6** phase-gated tool grants (`PHASE_GRANTS`) | M4 | `api/app/autonomous/enums.py`; `tests/autonomous/test_brakes.py` |
| Watches (KB-attach-triggered sessions) | M4 | `api/app/autonomous/watch_trigger.py`; `GET/POST/PATCH/DELETE /autonomous/watches`; table `autonomous_watches` (migration `0039`, `max_cost_usd` in `0045`) |
| Schedules (in-repo cron dispatcher) | M4 | `api/app/autonomous/cron.py`; `/autonomous/schedules`; table `autonomous_schedules` |
| Per-user memory (proposed → kept/dismissed) | M4 | `/autonomous/memory/*`; table `autonomous_memory` |
| Precedent board (race-safe upsert, observed_count) + promote-to-Project proposals | M4 | `/autonomous/precedents/*`, `/autonomous/project-context-proposals/*`; tables `precedent_entries` (migration `0039`), `project_context_proposals` (migration `0041`) |
| Honest per-session receipt (`terminal_reason`: completed / cost_cap_reached / external_halt / idle_timeout) | M4 | `api/app/autonomous/receipt.py` (`build_receipt` / `build_receipt_safe`); stored in `autonomous_sessions.result` |
| In-app notifications (durable; best-effort email transport) | M4 | `/autonomous/notifications/*`; table `autonomous_notifications` (migration `0040`) |
| Per-user opt-in (off by default) | M4 | `User.autonomous_enabled` (migration `0044`); spawn paths + mutate endpoints gated |
| Findings persistence (`autonomous_findings` written at the `emit_finding` chokepoint; `GET /autonomous/sessions/{id}/findings`; `?source_session_id=` filter on `GET /autonomous/memory`, precedents excluded — recurrence-aggregated) | post-v0.4.0 (#135) | `api/app/api/autonomous.py`; table `autonomous_findings` (migration `0046`) |
| Document-grade artifacts (opt-in `emit_artifacts`, default OFF; drafting `emit_artifact` chokepoint direct-writes a real KB document — MinIO upload-first, File `ready` + Document + chunks, direct KB attach bypassing watch-fire so no loop; markdown/plain only; `GET /autonomous/sessions/{id}/artifacts`, owner-gated; notification payload `artifact_count`) | post-v0.4.0 (#138) | `api/app/autonomous/guard.py` (`_handle_emit_artifact`), `api/app/api/autonomous.py`; table `autonomous_artifacts` (migration `0047`, session CASCADE / file SET NULL — the document outlives the session) |
| Matter binding on schedules/watches (`project_id` accepted on create + PATCH incl. clear-to-null; ownership validated at all five assignment sites — create_schedule/create_watch/run-now/two PATCHes — closing a pre-existing IDOR) | post-v0.4.0 (#133) | `api/app/api/autonomous.py` |
| Worker-side skill registry (shared `app/skills/bootstrap.py::install_skill_registry` from both the api lifespan and the arq-worker `on_startup`; uniform fail-fast on a missing/unreadable skills dir; arq-worker mounts `./skills:/skills:ro` + `LQ_AI_SKILLS_DIR`; SIGHUP reload stays api-only) | post-v0.4.0 (#139) | `api/app/skills/bootstrap.py`; `api/app/workers/arq_setup.py`; `docker-compose.yml` (arq-worker volume) |
| Web dashboard (sessions/receipt/halt, memory, precedents, watches, schedules, notifications, proposals) | M4 | `web/src/routes/lq-ai/autonomous/`; opt-in toggle at `settings/autonomous/` |
| Learn viz | M4 | `web/static/learn/playgrounds/autonomous-flow.html` (phase walk + the four brake scenarios; the four *primitives* are not yet visualized — see §11) |

**Honesty notes:** the ethics-review phase is a light v1 (emits a privilege/scope-concerns finding from the structured output; a dedicated ethics LLM gate is a future enhancement). A gateway error mid-analysis produces an honest "analysis failed at the gateway" finding and a completed (not fabricated) receipt. Audit rows carry counts/types/IDs/enums only — never raw entity values or document text.

---

## 6. Capabilities not yet started in source

Honest milestone deferrals — the subsystem does not yet exist (or only as plumbing). Verifiable by absence.

| Capability | Status | Verification |
|---|---|---|
| In-Word feature surfaces (chat/skills/playbooks in the add-in) | deferred (M4 / community) | `word-addin/` tabs are deep-link cards; [DE-287](PRD.md#9-deferred-enhancements-and-identified-future-work) |
| `/lq` Slack/Teams slash-command intake | deferred | Bridge webhook handlers inert; [DE-288](PRD.md#9-deferred-enhancements-and-identified-future-work) |
| Contract Repository auto-relationship detection (PRD §3.16) | deferred-M4+ | No `contract_relationships` table in `api/alembic/versions/` |
| MCP-client subsystem (M5+) | deferred-M5 | `grep -r "mcp" api/app gateway/app` is empty; PRD §8.5 |

---

## 7. Compliance and procurement state

The Compliance Alignment Pack at [`docs/compliance/`](compliance/) is a documented commitment; the per-framework alignment docs land incrementally. The pack is the project's contribution to the *operator's* certification work (pre-mapped control responses citing source), not a certification of the project itself.

| Document | Status | Verification |
|---|---|---|
| Threat model (STRIDE) / Architecture / Cryptography / Audit-logging / Encrypted-keys / Dependencies | M1 | `docs/security/*.md`, `docs/architecture.md` |
| Security policy + coordinated disclosure | M1 | [`SECURITY.md`](../SECURITY.md) |
| SOC2 / ISO 27001 / ISO 42001 / GDPR / HIPAA / FedRAMP alignment | stub | `docs/compliance/README.md` describes the format; per-framework docs land incrementally |
| OWASP LLM Top 10 / NIST AI RMF profiles | not yet (community-friendly) | mini-PRDs at `docs/contribute/mini-prds/` |
| Procurement Pack (SIG Lite + CAIQ) | starter | `docs/procurement/sig-lite.md`; full pack [DE-086](PRD.md#9-deferred-enhancements-and-identified-future-work) |

---

## 8. Engineering-discipline state

Engineering rigor is measurable, not asserted. Test **file** counts below are verifiable without standing up the stack (`find … | wc -l`); pass counts run in CI (`.github/workflows/ci.yml`).

| Practice | Status | Verification |
|---|---|---|
| Backend tests (pytest, live Postgres) | M1–M4 | 144 `test_*.py` files in `api/tests/` (incl. `tests/autonomous/` — 361 passing at M4 close, pre-Donna-run; refresh at next tag); `cd api && DATABASE_URL=… pytest` |
| Gateway tests (pytest) | M1–M4 | 41 `test_*.py` files in `gateway/tests/` (pre-Donna-run; refresh at next tag); `cd gateway && pytest` |
| Frontend unit tests (Vitest) | M1–M4 | 71 spec files in `web/src/`; `cd web && npx vitest run` |
| Cypress E2E (LQ.AI shell) | M1–M4 | 17 specs in `web/cypress/e2e/` |
| Ruff lint + format (Python) | M1–M4 | `.github/workflows/ci.yml`: `ruff check api scripts` + `ruff format --check` |
| mypy (api standard, gateway strict) | M1–M4 | CI `mypy app` per subsystem |
| svelte-check (LQ.AI-owned code) | M1–M4 | `cd web && npm run check:lq-ai` (0 errors on `src/{lib,routes}/lq-ai/**`); inherited OpenWebUI debt tracked as DE-262 (§8.1) |
| Coverage gate (target 80% api / 90% gateway) | not enforced | CI runs pytest but does not fail below threshold |
| Mutation / property-based testing, eval harness, Cypress-in-CI | not yet | On the engineering-discipline roadmap |
| OpenSSF Scorecard / Best Practices Badge | not yet (community-friendly) | mini-PRDs at `docs/contribute/mini-prds/` |
| SLSA-3 provenance / Sigstore-signed images / SBOM per release | committed | `docs/security/releases/README.md` |
| Annual third-party pen test + adversarial red-team | committed; not scheduled | First engagements targeted within 90 days of M1 release |

### 8.1 OpenWebUI fork — inherited TypeScript-check debt

The web frontend is a fork of OpenWebUI (ADR 0001). `npm run check` (full scope) surfaces ~9,359 TypeScript strict-mode signals, all in upstream files inherited at fork time; none in LQ.AI-owned code, none in the (separate Python) gateway. CI scopes the check to LQ.AI code (`npm run check:lq-ai`). Migration tracked as DE-262.

---

## 9. Operational state

| Surface | Status | Verification |
|---|---|---|
| Docker Compose reference deployment | M1–M4 | [`docker-compose.yml`](../docker-compose.yml) — always-on: postgres, redis, minio, gateway, api, ingest-worker, arq-worker, web |
| Local-only profile (Ollama) | M1 | `docker compose --profile local up` — adds the Ollama sidecar. Scanned-PDF OCR / PaddleOCR is not implemented (DE-320); the prior placeholder sidecar was removed. |
| Slack / Teams bridge profiles | M3 | `docker compose --profile slack up` / `--profile teams up` |
| Worker skill-registry bootstrap (operator-visible change, #139) | post-v0.4.0 | The api now **fails fast** on a missing/unreadable skills dir at startup (it previously logged a warning and booted with an empty registry); the arq-worker mounts `./skills:/skills:ro` and installs the same registry. `api/app/skills/bootstrap.py`; `docker-compose.yml` |
| Helm chart for Kubernetes | drafted | [`deploy/helm/lq-ai/`](../deploy/helm/lq-ai/) (worker-migration parity with the compose single-migrator fix is a community item — DE-327) |
| OpenTelemetry instrumentation (traces + metrics + domain spans) | M1 baseline + M3 domain spans + M4 autonomous spans | [`docs/observability.md`](observability.md) |
| Reverse-proxy/TLS recipes · backup tooling · runbooks · SLOs · status page · postmortem · DR cadence | not yet | mini-PRDs / deferred |

---

## 10. How to verify everything in this doc

1. Clone the repo and follow the [Quickstart](../README.md#quickstart) to stand the stack up (`docker compose up -d --build` — the api runs migrations 0001→0047 on boot).
2. Browse the file path or run the test command in the Verification column.
3. To read source without running the stack, the cited paths are all in the repository.

If a claim does not check out, the codebase is canonical — please [open an issue](https://github.com/LegalQuants/lq-ai/issues). The point of publishing this in source is that verification runs through readable code, not a vendor's representation of it.

---

## 11. Known doc/Learn gaps (this maintenance pass)

- **Learn visualizations to add** (shipped capabilities not yet visualized): intake-bridges (Slack/Teams OAuth + workspace lifecycle); the autonomous **four primitives** (watches/schedules/memory/precedent lifecycle — `autonomous-flow.html` covers phases + brakes only); projects/matters + org-profile + privilege tiers; KB hybrid retrieval (BM25 + vector). Tracked in the M4-D2 doc/Learn alignment plan.
- **Resolved this session (DEs):** DE-325 (`build_receipt_safe` hardening), DE-326 (fresh-install worker alembic-migration race). DE-327 (Helm worker-migration parity) is open as a community-suitable item.

## 12. Maintenance note

Maintained per release. Last rewritten at the **M4 close** (Autonomous Layer shipped end-to-end; fresh-install acceptance passed), then reconciled against the post-v0.4.0 "Donna" run (#115–#139; migration head `0047`). Substantive content drivers: [PRD §3](PRD.md#3-capability-specifications) (capabilities), [PRD §8](PRD.md#8-roadmap) (roadmap), [PRD §9](PRD.md#9-deferred-enhancements-and-identified-future-work) (deferrals), and the per-feature docs (`docs/citation-engine.md`, `docs/playbooks.md`, `docs/tabular-review.md`, `docs/word-addin.md`, `docs/intake-bridges.md`, `docs/autonomous-layer.md`).
