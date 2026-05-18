# Honest State

> Catalog of what LQ.AI ships today, what is deferred, and how to verify each. Maintained per release.

## What this doc is

This document catalogs what LQ.AI ships today, what is deferred, and how an operator can verify each. We publish it in source because the verification path for an open-source project terminates in code, not in a vendor's marketing claims. If you find a discrepancy between this doc and the codebase, the codebase is canonical; please [open an issue](https://github.com/LegalQuants/lq-ai/issues).

## How to read this

Each table has three columns:

- **Capability** — what the operator gets.
- **Status** — `M1` or `M2` (shipped today), `M2-XX` (shipped today, naming a specific M2 phase task like `M2-D3` for context), `deferred-Mx` (named in the roadmap; not yet wired in source), or `deferred (community-friendly)` for items on the [PRD §9](PRD.md#9-deferred-enhancements-and-identified-future-work) backlog ready for contribution.
- **Verification** — the file path, test command, or doc the operator can read to confirm the claim.

Status markers reference the roadmap milestones (M1 → M4) documented in [README.md](../README.md#project-status) and [PRD §8](PRD.md#8-roadmap).

## Where M1 and M2 sit

**M1 — Foundation (shipped).** Self-hostable release that delivers conversational legal AI on top of the ten starter skills, with the engineering surfaces (audit, tier enforcement, projects, knowledge bases, saved prompts, receipts, the skill-creator pipeline) that the M2–M4 capability work builds on. Three provider adapters: Anthropic, OpenAI, Ollama (local Tier 1).

**M2 — Citation Engine + Anonymization Layer (shipped).** Closes the two flagship M1-described capabilities whose architectural slots existed without running pipelines:

- **Citation Engine** — four-stage verification cascade (exact match → tolerant match → paraphrase judge → ensemble) ships operational. Every model-emitted citation gets verified character-by-character against the source document before rendering; failed citations surface as "unverified" rather than as confident-looking wrong text. §3.1 below catalogs the cascade and what an operator can verify in source today.
- **Anonymization Layer** — pre/post middleware in the gateway pseudonymizes named entities (Presidio defaults + custom legal recognizers for case + matter numbers) before requests leave for the model provider; streaming-aware rehydration restores originals on the response path. Privileged-project chats skip the layer entirely; retrieved source documents stay un-pseudonymized so citation grounding is direct. §3.2 below catalogs the middleware and the decisions it implements.
- **Azure OpenAI provider adapter** rounds out the M2 provider set, unblocking Azure-tenant enterprise deployments via the operator's existing Azure agreement.

**M3 and M4 not yet started in source.** Playbooks, the Word add-in, Tabular / Multi-Document Review, the Slack/Teams light-intake bridge, the Autonomous Layer, and the Contract Repository auto-relationship graph remain deferred milestone capabilities — the architectural slots will land when each milestone's work starts. §4 below catalogs them with the verification path (current absence in source) for each.

The honest reading is that an operator can deploy LQ.AI today for the everyday in-house work the ten starter skills cover, with character-verified citation grounding and operator-configurable pseudonymization, with the knowledge that the broader product surface (Playbooks, Word integration, multi-doc review, Slack/Teams bridge, autonomous background agents, contract relationship graph) lands across M3 and M4. The sections below catalog each capability so the operator can make that assessment with the same information the maintainer team has.

---

## 1. Conversational and workspace surface

This is the surface an in-house counsel touches every day: chat, matter workspaces, skills, knowledge bases, saved prompts, receipts. Every row below is wired end-to-end in M1 and covered by at least one Cypress E2E spec.

| Capability | Status | Verification |
|---|---|---|
| Multi-turn chat with persistent history | M1 | `api/app/api/chats.py`; `web/cypress/e2e/chat.cy.ts` |
| Matter (project) workspace with attached files / skills / KBs | M1 | `api/app/api/projects.py`; `web/src/routes/lq-ai/matters/[id]/+page.svelte` |
| Slash-invoked skills with provenance pill | M1 | `web/cypress/e2e/wave-d2-skill-creator.cy.ts` Test 4 |
| Community skill catalog via [`LegalQuants/lq-skills`](https://github.com/LegalQuants/lq-skills) submodule | M1 | `skills/community/` (30+ skills); loader walks both built-in + community paths with built-in winning on slug collision (`api/app/skills/loader.py`); operator refreshes via `git submodule update --remote skills/community` |
| Skill capture from a chat reply | M1 | `web/cypress/e2e/wave-d2-skill-creator.cy.ts` Test 1 |
| Wizard-based skill authoring (from scratch) | M1 | `web/cypress/e2e/wave-d2-skill-creator.cy.ts` Test 2 |
| Fork built-in or team skills | M1 | `web/cypress/e2e/wave-d2-skill-creator.cy.ts` Test 3 |
| Skill versions tab + per-version audit log | M1 | `web/cypress/e2e/wave-d2-skill-creator.cy.ts` Test 6 |
| Try-it sandbox per skill (component-state) | M1 | `web/cypress/e2e/wave-d2-skill-creator.cy.ts` Test 5; cross-tab conversation persistence in the sandbox is deferred (read the M1 limitation in `web/src/lib/lq-ai/components/SkillTryItPane.svelte`) |
| Saved Prompts library with one-click "Use in chat" | M1 | `web/cypress/e2e/wave-m1-final-surfaces.cy.ts` Test 1; `api/app/api/saved_prompts.py` |
| Knowledge bases — create, attach documents, ingest to `ready` | M1 | `web/cypress/e2e/wave-m1-final-surfaces.cy.ts` Test 2; `api/app/api/knowledge_bases.py`; `api/app/pipeline/ingest.py`; `api/app/workers/document_pipeline.py` |
| Receipts drawer with per-event provenance | M1 | `web/cypress/e2e/wave-d1-power-features.cy.ts` Test 4 + `wave-m1-final-surfaces.cy.ts` Test 3; `api/app/api/chat_receipts.py` |
| Tier-floor refusal with admin override | M1 | `web/cypress/e2e/wave-d1-power-features.cy.ts` Test 3 + Test 5; `gateway/app/tier_floor.py` |
| Admin model-alias CRUD (create / edit / delete) | M1 with one known UX gap | `web/src/routes/lq-ai/admin/models/+page.svelte` + `AliasForm.svelte`; **known issue in M1:** the edit modal's Model dropdown shows only the currently-saved model (the autocomplete prop `providerModels` is not populated by the parent — the field remains free-text-editable but autocomplete is missing). Tracked as [DE-272](PRD.md#de-272--admin-aliasform-model-dropdown-autocomplete-population). The light/dark color-contrast issue originally reported alongside this was fixed pre-tag — the `dark:` Tailwind variants were removed so the form matches the surrounding admin chrome |
| Enhance Prompt (⌘E) | M1 | `web/cypress/e2e/wave-d1-power-features.cy.ts` Test 1; `api/app/api/enhance_prompt.py` |
| KB attach modal from the composer | M1 | `web/cypress/e2e/wave-d1-power-features.cy.ts` Test 2 |
| Audit log of all sensitive actions | M1 | `api/app/audit.py`; admin reads at `/lq-ai/admin/audit-log` |
| FTS over chat history | M1 | `api/app/api/chats.py` (search route); migration `0016_chat_messages_fts.py` |
| GDPR-aligned export and account deletion | M1 | `api/app/workers/user_export.py`; `api/app/workers/user_deletion.py`; `api/app/api/users.py` |

---

## 2. Inference gateway and providers

The Inference Gateway is the security boundary — the only component holding privileged provider API keys, the only component making outbound calls to inference providers. Four provider adapters ship after M2: Anthropic, OpenAI, Azure OpenAI (M2-E1), and Ollama (local Tier 1). Google Vertex AI and AWS Bedrock are spec'd in PRD §9 with wire-format detail and acceptance criteria; they are contributor-friendly work units and remain on the deferred-enhancement list.

| Capability | Status | Verification |
|---|---|---|
| Inference gateway with provider routing | M1 | `gateway/app/router.py` |
| Anthropic provider adapter | M1 | `gateway/app/providers/anthropic.py` |
| OpenAI provider adapter | M1 | `gateway/app/providers/openai.py` |
| Ollama provider adapter (local, Tier 1) | M1 | `gateway/app/providers/ollama.py`; `docker-compose.yml` `--profile local` |
| Azure OpenAI provider adapter | M2-E1 | `gateway/app/providers/azure_openai.py`; PRD entry [DE-267](PRD.md#de-267--azure-openai-provider-adapter) (closed in M2) |
| Google Vertex AI provider adapter | deferred (community-friendly) | Wire-format spec in [PRD §9 DE-034](PRD.md#de-034--google-vertex-ai-provider-adapter-anthropic-on-vertex) ready for a contributor to pick up |
| AWS Bedrock provider adapter | deferred (community-friendly) | Fully spec'd in [PRD §9 DE-035](PRD.md#de-035--aws-bedrock-provider-adapter-anthropic-on-bedrock) with AWS Event Stream parser + SigV4 acceptance criteria |
| Tier enforcement (Tiers 1 – 5) | M1 | `gateway/app/tier_floor.py` |
| Privileged-matter tier floor enforcement | M1 + M2-D3 (verification) | `web/cypress/e2e/wave-d1-power-features.cy.ts` Test 3 + Test 5; M2-D3 added end-to-end audit-trail integration test at `api/tests/test_chat_citations.py::test_chat_send_privileged_project_full_audit_trail` |
| Anonymization pre/post middleware | M2 (recognizer accuracy on legal corpus: empirically unmeasured — see [PRD §9 DE-282](PRD.md#de-282--anonymization-layer-empirical-validation-on-legal-document-corpus) and [`docs/security/anonymization.md` §"What's validated vs what's unvalidated"](security/anonymization.md#whats-validated-vs-whats-unvalidated)) | `gateway/app/anonymization/middleware.py`; see §3.2 below |
| Routing log (per-inference) | M1 | `gateway/app/routing_log.py` |
| Citation Engine config endpoint (`GET /v1/citation-engine/config`) | M2-C1 + M2-D1 | `gateway/app/api/inference.py::citation_engine_config` — returns judge_model + ensemble block with server-computed `envelope_tier` |
| Provider-key encryption at rest (Fernet-wrapped master-key path) | M1 | `gateway/app/secrets.py`; `docs/security/encrypted-keys.md` |
| Hot-reload of gateway config via SIGHUP | M1 | `gateway/app/config_holder.py`; `gateway/app/config_loader.py`; `docs/adr/0010-gateway-config-hot-reload.md` |
| Per-skill prompt-injection detection rates published | not yet | No published numbers; see §6 below for the engineering-discipline plan |

---

## 3. M2-shipped capabilities — Citation Engine and Anonymization Layer

These are the two flagship M2 capabilities that landed Phase D of the M2 build. Both were architectural slots in M1 with explicit "M2 deferred" stubs; both are now operational and exercised by integration tests against a live Postgres + mocked-gateway stack. They are called out individually rather than in the tables above because they materially change what an M2 deployment promises its users — and because the same "verification path runs through readable code" framing now applies to the shipped pipeline rather than to a deferred stub.

### 3.1 Citation Engine — shipped M2 (4-stage cascade)

The PRD ([§3.3](PRD.md#33-citation-engine-exact-quote)) describes a Citation Engine with character-level verification of every claim against source documents — a pipeline that guarantees character-fidelity from document → model context → cited output → rendered viewer, and that renders failed citations as "unverified" rather than as confident wrong citations. **In M2, the full four-stage cascade is operational.**

The endpoint at `GET /api/v1/chats/{chat_id}/messages/{message_id}/citations` returns one row per verified citation from the `message_citations` table; the row carries `verification_method`, `verification_confidence`, the byte-precise source offsets, and (for ensemble runs) a `tier_envelope` audit field. Candidates that miss every stage are NOT persisted — the M2-C2 chat UI consumes the absence of a row as the "unverified" signal and renders the marker red.

**The four-stage cascade** (implemented in `api/app/citation/verification.py`):

1. **Stage 1 — `verify_exact_match`** (M2-A2). Byte-for-byte equality at the candidate's offsets against `documents.normalized_content`. Trivially fast; pure Python.
2. **Stage 2 — `verify_tolerant_match`** (M2-B1). Normalizes both the source slice and the candidate text via `app.citation.normalization.normalize` (smart-quote folding, whitespace collapse, OCR-confusion rules when `document.was_ocrd=True`) and compares with `rapidfuzz.fuzz.ratio` at threshold 95. Catches formatting drift without accepting genuine paraphrases.
3. **Stage 3 — `verify_paraphrase`** (M2-C1). LLM judge call through the gateway (model configured via `gateway.yaml` `citation_engine.judge_model`, default `fast`). Returns `yes` / `partial` / `no` with `high` / `medium` / `low` confidence mapped to 0.90 / 0.70 / 0.50. `partial` verdicts persist with a `partial=true` flag so the M2-C2 UI renders them distinctly.
4. **Stage 4 — `verify_ensemble`** (M2-D1). Replaces Stage 3 when activated. Dispatches the paraphrase judge in parallel across N models via `asyncio.gather`; aggregates verdicts under `strict` (all-agree) or `majority` (simple-majority) rules. Activation is the OR of skill frontmatter (`lq_ai.ensemble_verification: true`), the project's `ensemble_verification` column, and the gateway's `default_enabled` flag. Pre-flight cost-budget check falls back to single-judge Stage 3 if the estimated spend exceeds `max_cost_per_message_usd`.

**What an operator can verify today:**

- Read the cascade implementation: [`api/app/citation/verification.py`](../api/app/citation/verification.py).
- Read the persistence + activation logic: `api/app/api/chats.py::_persist_message_citations` and `::_resolve_ensemble_config`.
- Read the gateway config endpoint: [`gateway/app/api/inference.py`](../gateway/app/api/inference.py) `GET /v1/citation-engine/config` (computes the ensemble's `envelope_tier` server-side from the configured `judge_models` list).
- Read the schema: migration [`0025_create_message_citations.py`](../api/alembic/versions/0025_create_message_citations.py) + extensions in `0026_paraphrase_judge_and_partial.py` (M2-C1) and `0027_ensemble_method_values.py` (M2-D1).
- Read the full integration walkthrough: [`docs/citation-engine.md`](citation-engine.md) — cascade, UI states (4 chip variants with tooltip variance per method), configuration surface, cost-budget enforcement, privacy implications of Stage 4, integration with Anonymization Layer, known limitations.
- Run the unit test suite: `cd api && pytest tests/citation/` (95 tests covering extraction, normalization, exact match, tolerant match, paraphrase judge, ensemble strict/majority/tier-envelope/budget-fallback, cascade routing).
- Run the integration test suite: `cd api && pytest tests/test_chat_citations.py` (12 tests against live Postgres covering verbatim quotes, tolerant matches, paraphrase verdicts, partial flag, multi-doc citations, deleted-doc handling, retrieval-context skip, privileged-project full audit trail).

**What this means for an M2 deployment:**

- The model cannot produce confidently-rendered text that wasn't traceable to source. Every emitted `"..." (Source: [N])` pair gets verified through the cascade; only verified candidates persist as `message_citations` rows; the UI distinguishes verified (green / yellow) from unverified (red) cleanly.
- Operators with high-stakes operations (regulatory filings, board materials) opt in to Stage 4 ensemble verification for additional confidence. The privacy envelope (max tier across the configured judge models) persists per row so the operator can audit which chats had citations sent to weaker tiers.
- The `verification_method` enum (`exact_match` / `tolerant_match` / `paraphrase_judge` / `ensemble_strict` / `ensemble_majority` / `failed`) is queryable for compliance reporting: `SELECT method, count(*) FROM message_citations GROUP BY verification_method` shows the verification distribution across the deployment's chat history.
- One known limitation persists, tracked as [DE-277](PRD.md#de-277--citation-extractor-fallback-to-document-scan-on-chunk-boundary-miss): a citation quote that spans the boundary between two retrieved chunks (neither chunk's content alone contains the full quote) silently drops at extraction and renders as "unverified." Documented in [`docs/citation-engine.md` §Known limitations](citation-engine.md#chunk-boundary-spanning-quotes--silently-drop-today); pinned by `api/tests/citation/test_edge_cases.py::test_chunk_boundary_spanning_citation_does_not_extract_today` so a future DE-277 implementation has a failing test to flip.

### 3.2 Anonymization Layer — shipped M2 (middleware + custom recognizers + privileged-skip + retrieval-skip)

The PRD ([§4.7](PRD.md#47-anonymization-layer-m2)) describes an Anonymization Layer that swaps named entities for stable placeholders on the request path and rehydrates them on the response path — the privacy fallback for Tier 3+ inference paths when local (Tier 1) inference is impractical but defensible privacy posture is still required. **In M2, the full middleware is wired end-to-end with custom legal recognizers, streaming-aware rehydration, privileged-project carve-out, and a retrieval-context skip for direct citation grounding.**

**Pipeline:** `gateway/app/anonymization/middleware.py::pre_anonymize_request` runs after tier derivation and before provider dispatch (per the request path in `gateway/app/api/inference.py:614`). It walks user/assistant/system messages plus skill inputs, pseudonymizes each detected entity via `app.anonymization.engine.Anonymizer`, and returns a `PseudonymMapper` carrying the pseudonym→original mapping. The response path calls `post_anonymize_response` (non-streaming) or feeds chunks through `StreamingRehydrator` (streaming) to substitute originals back. The mapper is per-request and in-memory only — never persisted, never logged, dropped on function exit.

**Recognizer set** (configured in `gateway/app/anonymization/engine.py::get_analyzer_engine`):

- Presidio defaults: `PERSON`, `ORGANIZATION`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION` (via spaCy `en_core_web_lg` baked into the gateway Dockerfile per M2-B2).
- Custom legal recognizers: `CaseNumberRecognizer` (matches docket-number formats; M2-B2) and `MatterNumberRecognizer` (matches internal matter-tracking identifiers; M2-B2).

**Skip conditions** (any one short-circuits to no-op):

1. `config.enabled is False` — master switch.
2. `routed_tier not in config.apply_at_tiers` — Tier 1 (local) doesn't benefit.
3. `chat_request.lq_ai_privileged is True` — privileged chats are never rewritten (Decision A: rewriting privileged work product risks corrupting it).
4. `chat_request.anonymize is False` — per-request opt-out (the Citation Engine's judge calls use this).
5. `message.lq_ai_skip_anonymization is True` — per-message opt-out, set by the api/ on the retrieval-context system message so the model sees intact source quotes for citation grounding (Decision M2-1).

**What an operator can verify today:**

- Read the middleware: [`gateway/app/anonymization/middleware.py`](../gateway/app/anonymization/middleware.py) — `pre_anonymize_request`, `post_anonymize_response`, `StreamingRehydrator` with bounded-tail-buffer semantics.
- Read the mapper: [`gateway/app/anonymization/mapper.py`](../gateway/app/anonymization/mapper.py) — `PseudonymMapper.assign` (stable per-`(entity_type, original)` assignments within a request), `reverse` (rehydration substitution table).
- Read the custom recognizers: [`gateway/app/anonymization/recognizers/case_number.py`](../gateway/app/anonymization/recognizers/case_number.py) and `matter_number.py`.
- Read the request-path wiring: `gateway/app/api/inference.py:614-619` (pre-middleware call) and `:673` (post-middleware call); streaming counterparts at `:1107` and onwards.
- Read the full middleware contract: [`docs/security/anonymization.md`](security/anonymization.md) — recognizer set, decision basis, audit-log shape, privileged-chat carve-out, retrieval-context skip, known limitations.
- Run the unit + integration test suite: `cd gateway && pytest tests/anonymization/ tests/test_inference_anonymization.py` (93+ tests covering analyzer, mapper, engine integration, recognizers, middleware skip conditions, round-trip correctness with the real Presidio engine, edge cases).

**What this means for an M2 deployment:**

- Operators on Tier 3+ paths can configure pseudonymization as a defense-in-depth control on top of the provider's contractual privacy posture. The provider sees pseudonymized entity strings (`PERSON_0001`, `COMPANY_0001`); the user sees originals (rehydrated on the response path).
- Privileged matters work as expected: setting `Project.privileged=True` causes the gateway middleware to skip the entire request, so privileged work product reaches the configured inference target verbatim. The combination "privileged + Tier 1 (Ollama)" produces fully sealed local inference with no outbound network and no anonymization rewriting — the recommended posture for the most sensitive matters per [`docs/security/anonymization.md` §Privileged chats](security/anonymization.md#privileged-chats--why-we-skip-m2-b3--m2-d3).
- Retrieved source documents stay un-pseudonymized so the Citation Engine's quote verification works directly against the original document text (Decision M2-1). The alternative (Option A: pseudonymize sources too) is tracked as [DE-269](PRD.md#de-269--anonymization-option-a-pseudonymize-source-documents-too).
- One forward-looking surface remains: per-request salting of the pseudonym format to close the cross-mapper collision surface, tracked as [DE-274](PRD.md#de-274--anonymization-pseudonym-collision-in-source-documents). The current `{ENTITY_TYPE}_{NNNN}` format is operator-readable and deterministic by design; the salt would add ~5 chars per pseudonym and close the structural distinctness gap. Pinned by the M2-C3 round-trip test suite so the gap is visible in CI.

---

## 4. Capabilities not yet started in source

These are PRD-committed capabilities where the directory or subsystem does not yet exist in the codebase. They are honest milestone deferrals, not partial implementations — the milestone target is firm, and the architectural slot will land when the milestone work starts.

| Capability | Status | Verification |
|---|---|---|
| Word add-in (Office.js) | deferred-M3 | `ls word-addin/` — directory absent. Spec in [PRD §3.9](PRD.md#39-word-add-in-m3) |
| Playbooks (codified legal positions, auto-generation wizard) | deferred-M3 | No `playbooks` table in `api/alembic/versions/` (M2 head is 0028). Spec in [PRD §3.7](PRD.md#37-playbooks-m3) |
| Tabular / multi-document review (M3) | deferred-M3 | No grid surface; spec in [PRD §3.8](PRD.md#38-tabular-multi-document-review-m3) |
| Slack / Teams light intake bridge (M3) | deferred-M3 | No `/lq` slash command surface; spec in [PRD §3.10](PRD.md#310-slack--teams-light-intake-bridge-m3) |
| Autonomous Layer (cron tasks, watches, per-user memory) | deferred-M4 | No `autonomous_tasks` table; spec in [PRD §3.11](PRD.md#311-autonomous-layer-m4) |
| Contract Repository auto-relationship detection (M4) | deferred-M4 | No `contract_relationships` table; spec in [PRD §3.12](PRD.md#312-contract-repository--auto-relationship-detection-m4) |
| MCP-client subsystem (M5+) | deferred-M5 | `grep -r "mcp" api/app gateway/app` is empty; spec in [PRD §8.5](PRD.md#m5m7--forward-looking-workflow-intelligence-community-driven-not-committed) |

---

## 5. Compliance and procurement state

The Compliance Alignment Pack at [`docs/compliance/`](compliance/) is a documented commitment whose individual framework documents are stubs at v1 launch. The pack format is documented in [`docs/compliance/README.md`](compliance/README.md); per-framework alignment docs land as M1 and M2 ship. The pack is not a certification — LQ.AI is open-source software the operator deploys and operates, and the operator's deployment is what gets certified, not the project itself. The pack is the project's contribution to the operator's certification work: pre-mapped control responses with citations into source so the operator's compliance team has a substantive starting point.

Some of the highest-value compliance documents (OWASP LLM Top 10 mapping, NIST AI RMF 1.0 Profile, the procurement-readiness pack itself) are scoped as contributor-friendly work and have mini-PRDs published at [`docs/contribute/mini-prds/`](contribute/mini-prds/). They are off the maintainer's critical path because the foundation is in source and the work is reading the foundation and producing the framework-mapped document on top of it.

| Document | Status | Verification |
|---|---|---|
| SOC 2 Type II alignment | stub (target M1) | `docs/compliance/README.md` describes the format; `soc2-alignment.md` not yet authored |
| ISO/IEC 27001:2022 alignment | stub (target M1) | Same |
| ISO/IEC 42001:2023 alignment | stub (target M2) | Same |
| GDPR readiness | stub (target M1) | Same |
| HIPAA Security + Privacy Rule alignment | stub (target M2) | Same |
| FedRAMP Moderate alignment | stub (target M2) | Same |
| OWASP LLM Top 10 mapping | not yet | [Mini-PRD open](contribute/mini-prds/owasp-llm-top10-mapping.md) — contributor-friendly |
| NIST AI RMF 1.0 Profile | not yet | [Mini-PRD open](contribute/mini-prds/nist-ai-rmf-profile.md) |
| Procurement Pack (SIG Lite + CAIQ pre-fills) | M2-D3 starter (privileged-matter scope only) | [`docs/procurement/sig-lite.md`](procurement/sig-lite.md) — 4 SIG Lite questions covering data classification + privileged work-product + audit-log integrity. Full pack (every SIG Lite domain + CAIQ Lite + cover letter) tracked as [DE-086](PRD.md#de-086--procurement-readiness-pack); [mini-PRD open](contribute/mini-prds/procurement-readiness-pack.md) |
| Threat model (STRIDE) | M1 | [`docs/security/threat-model.md`](security/threat-model.md) |
| Architecture document | M1 | [`docs/architecture.md`](architecture.md) |
| Cryptography reference | M1 | [`docs/security/cryptography.md`](security/cryptography.md) |
| Dependency-management posture | M1 | [`docs/security/dependencies.md`](security/dependencies.md) |
| Audit-logging policy | M1 | [`docs/security/audit-logging.md`](security/audit-logging.md) |
| Encrypted-keys ADR (master-key workflow) | M1 | [`docs/security/encrypted-keys.md`](security/encrypted-keys.md) |
| Security policy + coordinated disclosure | M1 | [`SECURITY.md`](../SECURITY.md) |

---

## 6. Engineering-discipline state

The project's commitment is that engineering rigor is measurable, not asserted. The signals below are the M1 snapshot — what is in CI, what is in the test suite, what is in the release pipeline, and which engineering practices are on the roadmap but not yet enforced. Where a discipline is not yet shipped, the path is named so a reviewer can confirm both what is and what is not in place.

| Practice | Status | Verification |
|---|---|---|
| Frontend unit tests (Vitest) | M1 + M2 | `cd web && npx vitest run` — 56 spec files; **456 tests passing** as of M2 close |
| Backend tests (pytest) | M1 + M2 | 70+ test files in `api/tests/`; **1001 tests passing, 1 skipped** against live Postgres after M2 close (`cd api && DATABASE_URL=... pytest`) |
| Gateway tests (pytest) | M1 + M2 | 30+ test files in `gateway/tests/`; **497 tests passing, 2 skipped** after M2 close (`cd gateway && pytest`) |
| Cypress E2E (LQ.AI shell) | M1 | 6 LQ.AI specs in `web/cypress/e2e/` (`wave-a-chrome`, `wave-b-surfaces`, `wave-c-matters`, `wave-d1-power-features`, `wave-d2-skill-creator`, `wave-m1-final-surfaces`) plus 4 upstream OpenWebUI specs |
| Documented E2E coverage matrix per surface (`docs/test-strategy.md`) | not yet | CLAUDE.md notes `docs/test-strategy.md` as an M1 deliverable; the file does not yet exist. The coverage signal today is the spec inventory above and the "tests as documentation" framing in PRD §5.8; the explicit per-surface coverage matrix (smoke / happy path / edge cases) with milestone tags is deferred. Closes the criticism that "tests as documentation" is overstated when 6 specs cover the M1 LQ.AI surfaces without an explicit per-surface contract. |
| Coverage gate (PRD §5.8 target: 80% api / 90% gateway) | not enforced | `.github/workflows/ci.yml` runs pytest but does not fail below threshold; the gap is documented |
| Ruff lint + format (Python) | M1 | `.github/workflows/ci.yml`; configured in each subsystem |
| mypy type-checking (api: standard, gateway: strict) | M1 | Same |
| svelte-check (web, LQ.AI-owned code) | M1 | `cd web && npm run check:lq-ai` — 0 errors on all LQ.AI-owned paths (`src/lib/lq-ai/**`, `src/routes/lq-ai/**`). Full-scope check (`npm run check`) shows ~9,359 inherited errors from upstream OpenWebUI files; see §6.1 below. |
| Mutation testing | not yet | Out of M1 scope; on the engineering-discipline roadmap |
| Property-based tests (Hypothesis) | not yet | Same |
| Eval harness with held-out test sets | not yet | Per-skill `test-plan.md` exists for the 10 starter skills; eval execution is deferred. [Mini-PRD for skill acceptance tests](contribute/mini-prds/skill-acceptance-tests.md) is the contributor-friendly path |
| Cypress in CI | not yet | E2E suite runs locally; CI integration is on the engineering-discipline roadmap |
| OpenSSF Scorecard | not yet | [Mini-PRD open](contribute/mini-prds/openssf-scorecard-and-badges.md) |
| OpenSSF Best Practices Badge | not yet (target Passing at M1, Silver at M2) | Same mini-PRD |
| Accessibility audit (WCAG 2.1 AA + axe-core CI gate) | not yet (axe-cli scans in dev; CI gate deferred) | The design target is WCAG 2.1 AA per [`README.md`](../README.md#accessibility); CI enforcement deferred |
| Air-gap install verification in CI | not yet | [Mini-PRD open](contribute/mini-prds/air-gap-install-verification.md) |
| Per-skill prompt-injection detection rates | not yet | Out of M1 scope; on the engineering-discipline roadmap |
| Per-skill PII leakage measurement | not yet | Depends on Anonymization Layer (§3.2 above) |
| Annual third-party penetration test | committed; not scheduled | First engagement targeted within 90 days of M1 release |
| Annual adversarial-AI red-team engagement | committed; not scheduled | Same posture |
| Signed commits enforced on `main` | not yet | DCO sign-off is required ([CONTRIBUTING.md](../CONTRIBUTING.md)); cryptographic commit signing is on the engineering-discipline roadmap |
| SLSA-3 build provenance | committed | Documented in [`docs/security/releases/README.md`](security/releases/README.md); verified on release builds |
| Sigstore-signed container images | committed | Same |
| SBOM with every release | committed | Same |

### 6.1 OpenWebUI fork — inherited TypeScript-check debt

The LQ.AI web frontend is a fork of OpenWebUI (per ADR 0001). When `svelte-check` runs against the full codebase (`npm run check`), approximately 9,359 TypeScript errors surface — all in upstream OpenWebUI files inherited at fork time. None are in LQ.AI-owned code (`src/lib/lq-ai/**`, `src/routes/lq-ai/**`).

**Why these are not critical bugs:**

- They are TypeScript strict-mode signals (implicit `any`, missing property declarations on legacy `.js` files, narrowing issues in upstream Svelte components) — not runtime errors. The application runs correctly; these are static-analysis warnings about upstream code we did not author.
- None affect the Inference Gateway, which is the security boundary. The gateway is a separate Python service with its own clean typecheck (mypy strict mode, CI-enforced).
- None affect the LQ.AI surfaces an operator interacts with. Those are the `/lq-ai/*` routes and `src/lib/lq-ai/**` components, which pass strict typecheck with 0 errors.
- Vitest unit tests (400 tests, 53 spec files) and Cypress E2E tests exercise the actual runtime behavior and are 100% passing on M1.

**What ships in M1:** CI scopes `svelte-check` to LQ.AI-owned code via `npm run check:lq-ai` (using `tsconfig.lq-ai.json`) so the typecheck signal stays meaningful for new contributions. Operators or auditors who want the full picture can run `npm run check` for the unscoped check, see the upstream errors, and verify they are confined to upstream paths.

**Migration plan (deferred to post-M1):** Tracked as DE-262. Path: clean up the highest-impact upstream files first (auth, chat shell, settings), then long-tail. Target Silver OpenSSF Best Practices Badge tier requires no strict-mode noise; the migration is a stepping stone toward that badge.

---

## 7. Operational state

The deployment story in M1 is Docker Compose plus a drafted Helm chart. The supporting operational artifacts — reverse-proxy + TLS recipes, backup tooling, runbooks, SLOs — are partially shipped or deferred. The operator is the running organization; the project provides the artifacts that make running it tractable, and surfaces honestly where additional operator work is required today.

| Surface | Status | Verification |
|---|---|---|
| Docker Compose reference deployment | M1 | [`docker-compose.yml`](../docker-compose.yml) — 7 services in the default profile |
| Local-only profile (Ollama + PaddleOCR) | M1 | `docker compose --profile local up` |
| Helm chart for Kubernetes | drafted (M1) | [`deploy/helm/lq-ai/`](../deploy/helm/lq-ai/) |
| Reverse-proxy + TLS recipes (Caddy, Traefik, nginx) | not yet | [Mini-PRD open](contribute/mini-prds/reverse-proxy-tls-deployment-recipes.md) |
| Backup + restore tooling (`pg_dump` + MinIO snapshot wrapper) | not yet | `ls scripts/` — no backup tooling |
| Runbooks for operational tasks | not yet | `ls docs/` — no `runbooks/` directory |
| SLO / SLI publication | not yet | OpenTelemetry instrumentation ships at M1; service-level objectives are deferred |
| Public status page (for any LegalQuants-hosted artifacts) | not yet | No hosted service in M1; the project ships as software the operator runs |
| Public postmortem template + commitment | not yet | No incidents in operator-facing infrastructure yet; the publication commitment lands with the engineering-discipline roadmap |
| Quarterly DR test cadence | not yet | Deployment recipes ship at M1; test cadence is operator-side and not yet documented |

---

## 8. How to verify everything in this doc

The general protocol is the same for every row:

1. Clone the repository: `git clone https://github.com/legalquants/lq-ai.git`.
2. Follow the [Quickstart](../README.md#quickstart) in the README to stand the stack up.
3. Browse the file path or run the test command cited in the Verification column.
4. If you want to read the source without standing the stack up, the cited paths are all in the repository and any file viewer (GitHub web UI, `cat`, an editor) is sufficient.

If a claim in this document does not check out — a path does not exist, a test does not pass, a status marker is wrong — the codebase is canonical. Please [open an issue](https://github.com/LegalQuants/lq-ai/issues) and the maintainer team will reconcile the doc. The point of publishing the doc in source is that the verification path runs through readable code, not through a vendor's representation of the code.

---

## 9. What an operator's evaluation can confirm in source

Because LQ.AI is open-source and self-hosted, an operator's evaluation does not terminate in a vendor's representation of the product. The list below is a sample of the verifications that are available in source today and are not available from a closed-source vendor at any price:

- **Read the inference gateway's routing logic** and confirm the operator's tier policy is enforced as documented: `gateway/app/router.py` plus `gateway/app/tier_floor.py`.
- **Read the audit logger** and confirm what is captured: `api/app/audit.py`. Every sensitive action — login, MFA setup, skill execution, tier override, account deletion — produces a structured event.
- **Read every built-in skill** and confirm what each skill instructs the model to do: `skills/*/SKILL.md` plus the supporting reference and example files. There are no hidden prompts.
- **Read the provider adapters** and confirm what is sent to each inference provider and how authentication is handled: `gateway/app/providers/{anthropic,openai,ollama}.py`.
- **Read the routing log writer** and confirm what is recorded per inference: `gateway/app/routing_log.py`.
- **Read the secrets layer** and confirm provider-key encryption at rest: `gateway/app/secrets.py` plus `docs/security/encrypted-keys.md`.
- **Read the threat model** and confirm the STRIDE analysis is current: `docs/security/threat-model.md`.
- **Read the M2 Citation Engine implementation** end-to-end: `api/app/citation/verification.py` (cascade), `api/app/citation/extraction.py` (extractor), `api/app/api/chats.py::_persist_message_citations` (persistence + activation), `gateway/app/api/inference.py::citation_engine_config` (gateway endpoint), `docs/citation-engine.md` (full reference). Failed citations surface as "unverified" — read [`api/tests/citation/test_edge_cases.py`](../api/tests/citation/test_edge_cases.py) for the pinned edge-case behaviors and one known limitation ([DE-277](PRD.md#de-277--citation-extractor-fallback-to-document-scan-on-chunk-boundary-miss)).
- **Read the M2 Anonymization Layer implementation** end-to-end: `gateway/app/anonymization/middleware.py` (pre/post + StreamingRehydrator), `gateway/app/anonymization/engine.py` (Presidio AnalyzerEngine config), `gateway/app/anonymization/recognizers/` (custom legal recognizers), `docs/security/anonymization.md` (full reference). The privileged-skip carve-out + retrieval-context skip are explicit in the skip conditions at `middleware.py:81-110`.
- **Run the test suite** and read the results: `cd web && npx vitest run` (456 passing); `cd api && DATABASE_URL=... pytest` (1001 passing); `cd gateway && pytest` (497 passing); `cd web && npx cypress run`.
- **Read the capabilities that are not yet started in source** — the symmetric verification: `ls word-addin/` (empty; M3 add-in not yet started), `grep -r "playbooks" api/alembic/versions/` (no Playbooks table; M3), `grep -r "autonomous_tasks" api/alembic/versions/` (no Autonomous Layer table; M4), `grep -r "contract_relationships" api/alembic/versions/` (no Contract Repository relationship graph; M4). What is shipped is in source; what is deferred is verifiable by its absence.

The verification budget is the operator's to set, on a timeline the operator chooses, with a scope the operator defines. None of those properties is true for closed-source attestation.

## 10. Maintenance note

This document is maintained per release. Items leave the deferred lists when they ship; items join when they are scoped. Last updated alongside the M2 closeout chain — Phase D + E1 + E2 shipped, F1 closed via scope reframe, F2 closed via transparency-first deferral (DE-282 invites community contribution for empirical PII-recognition validation on legal corpus); 2026-05-17.

The substantive content that drives this doc lives in:

- [PRD §3 Capability Specifications](PRD.md#3-capability-specifications) — what each capability is.
- [PRD §8 Roadmap](PRD.md#8-roadmap) — when each milestone lands.
- [PRD §9 Deferred Enhancements](PRD.md#9-deferred-enhancements-and-identified-future-work) — what is deferred and why.
- [`docs/compliance/`](compliance/) and [`docs/security/`](security/) — compliance and security artifacts.
- [`docs/contribute/EASIEST-CONTRIBUTIONS.md`](contribute/EASIEST-CONTRIBUTIONS.md) — the contributor-friendly path for items this doc surfaces as gaps.
