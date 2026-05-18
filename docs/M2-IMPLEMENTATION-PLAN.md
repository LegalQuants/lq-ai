# M2 Implementation Plan — Citation Engine, Anonymization Layer, and Azure Adapter

> **Purpose:** Dependency-ordered task list for the M2 build. Each task is a discrete unit of work sized for a focused Claude Code session, with verifiable end-state. Follows the same conventions as [`M1-IMPLEMENTATION-ORDER.md`](M1-IMPLEMENTATION-ORDER.md).
>
> **Status:** Authoritative once committed. Updates land in the same release cadence as the PRD.
>
> **Audience:** Claude Code or any human contributor implementing M2. Hand this document along with the PRD, `db-schema.md`, the OpenAPI sketches, the gateway config example, and `CLAUDE.md`. Implementation flows from the order documented here.

The M2 milestone hardens the trust layer of the product. Three deliverables ship together:

1. **Citation Engine verification** ([PRD §3.3](PRD.md#33-citation-engine-exact-quote)) — every citation produced by the model is verified against source before rendering. Failed verifications surface as "unverified" rather than as confident wrong text. Four verification stages (exact-match, tolerant-match, paraphrase judge, ensemble) catch claims of decreasing literal-fidelity.
2. **Anonymization Layer** ([PRD §4.7](PRD.md#47-anonymization-layer-m2)) — pseudonymization of sensitive entities in the gateway pipeline before requests leave to the model provider, with rehydration on the return path. Pseudonyms are typed (`PERSON_0001`, `ORG_0042`, etc.), stable within a request, and discarded after.
3. **Azure OpenAI adapter** ([DE-267](PRD.md#de-267--azure-openai-provider-adapter)) — small but strategically important; unblocks Azure-shop enterprise deployments.

M2 ships in **~6 weeks of focused work**. The week-by-week breakdown organizes tasks for both sequential and modest parallelization. Tasks marked **[parallel]** can run concurrently with their predecessor once it completes.

This document supersedes any conflicting sequencing in earlier roadmap documents. The PRD §8 roadmap remains the canonical capability commitment; this document is the implementation contract.

---

## Architectural decisions locked for M2

Two architectural decisions are locked at the start of M2; subsequent tasks build on them. Documented here for the agent's clarity and so future contributors understand the reasoning.

### Decision M2-1: Anonymization preserves source-document retrieval (Option B)

When anonymization is enabled, the layer pseudonymizes the **user's chat content, conversation context, and skill inputs**. Source documents retrieved into the model's context **stay un-pseudonymized**.

The trade-off this accepts: the model sees source document content as the operator stored it. The reasoning:

- Source documents are already in the operator's environment as retrieved data; they are part of the retrieval index that operator security controls govern. Pseudonymizing on retrieval would require re-pseudonymizing on every retrieval, which is expensive and bug-prone for citation integration.
- Anonymization's primary value is in the **chat content path** — the user's prompts, the chat history, the inferred matter context. This is the new content per request; this is what an upstream LLM provider would see in their logs that wasn't already known.
- The citation engine operates on un-pseudonymized text on both sides (model's claim and source), simplifying the integration significantly.

The alternative (Option A — pseudonymize source documents in retrieval too) is documented as DE-269 in `docs/PRD.md` §9 for future consideration if a specific deployment requires it.

### Decision M2-2: Ensemble verification ships in M2 baseline

Stage 4 of the Citation Engine pipeline (ensemble verification with parallel judge models) ships in M2 rather than as a follow-on. The reasoning:

- The procurement story for M2 explicitly includes "verified by multiple models in parallel for high-stakes operations." Marketing this and not having it is worse than the engineering cost of building it.
- The architectural slot is the same as the single-judge path with a fanout step; engineering cost is incremental.
- Skill frontmatter `ensemble_verification: true` is the activation; default off keeps cost bounded.

---

## Phase A — Foundation (Week 1)

Lays the data substrate Citation Engine and Anonymization both need. By end of Phase A, the document pipeline records normalized full text alongside chunks, and the gateway has the Anonymization module scaffold loaded.

### Task M2-A1 — Add normalized content + OCR flag to documents

**Scope:**
- Alembic migration `0008_normalized_content.py` (or next sequential number) adds:
  - `documents.normalized_content TEXT NOT NULL DEFAULT ''` — the full extracted text, single field, used by verification re-reading.
  - `documents.was_ocrd BOOLEAN NOT NULL DEFAULT FALSE` — flag indicating whether the source went through OCR, used to enable OCR-artifact normalization in tolerant-match.
- Update `api/app/pipeline/ingest.py` to populate both fields during document processing.
- One-time backfill script `scripts/backfill_normalized_content.py` reconstructs `normalized_content` for existing documents from their chunks.
- Update `docs/db-schema.md` to document both columns.

**Dependencies:** None. First task in M2.

**Output:** New documents have populated `normalized_content` and `was_ocrd`. Existing documents are backfilled.

**Verification:**
- `psql` query against the dev DB shows both columns populated on a sample document.
- Re-extraction from `normalized_content` at the offsets in a `document_chunks` row reproduces that chunk's content byte-for-byte.
- Backfill script idempotent (re-running doesn't corrupt data).

**Effort:** 4–6 hours.

---

### Task M2-A2 — Citation Engine Stage 1 (exact-match verification)

**Scope:**
- Create `api/app/citation/` module.
- Implement `verify_exact_match(citation, document)` in `api/app/citation/verification.py`.
- Pipeline integration: after the chat message-completion path receives citations from the model, run Stage 1 on each citation **before persisting**.
- Persist verification results to `message_citations` table:
  - `verified BOOLEAN` — set if any stage passes.
  - `verification_method TEXT` — `'exact_match'` for Stage 1 success.
  - `verification_confidence NUMERIC(3,2)` — `1.0` for exact-match.
- Migration `0009_citation_verification_fields.py` adds `verification_method` and `verification_confidence` to `message_citations`.
- Unit tests in `api/tests/citation/test_exact_match.py` covering:
  - Byte-for-byte match returns verified=True.
  - Off-by-one offset returns verified=False.
  - Slight modification (whitespace, casing) returns verified=False (this falls through to Stage 2 later).

**Dependencies:** M2-A1.

**Output:** Citations with verbatim text from source pass Stage 1; others fall through (rendered as unverified for now until later stages land).

**Verification:**
- Run a chat with NDA Review against the sample NDA; inspect the audit log; verify each citation has `verification_method = 'exact_match'` or `NULL` (not yet verified).
- Unit tests pass.

**Effort:** 6–8 hours.

---

### Task M2-A3 — Anonymization module scaffold [parallel with M2-A2]

**Scope:**
- Add dependencies to `gateway/pyproject.toml`:
  - `presidio-analyzer ~= 2.2`
  - `presidio-anonymizer ~= 2.2`
  - `spacy ~= 3.7`
- Add to deployment Docker image (or via init script) the spaCy `en_core_web_lg` model download.
- Create `gateway/app/anonymization/` module:
  - `__init__.py`
  - `engine.py` — top-level Anonymizer class
  - `mapper.py` — PseudonymMapper class (request-scoped pseudonym assignment)
  - `recognizers/` — directory for custom recognizers (populated in Phase B)
- Implement `PseudonymMapper`:
  - `assign(entity_type, original) -> pseudonym` — stable assignment, request-scoped.
  - `reverse() -> dict[str, str]` — pseudonym → original mapping for rehydration.
  - Mapping is in-process only; never persisted, never logged.
- Smoke test in `gateway/tests/anonymization/test_mapper.py`:
  - Same original → same pseudonym across calls.
  - Different originals → different pseudonyms.
  - Counter increments correctly per entity type.

**Dependencies:** None (parallel with M2-A2).

**Output:** Anonymization module loadable; PseudonymMapper class tested in isolation.

**Verification:**
- Unit tests pass.
- `python -c "from app.anonymization.mapper import PseudonymMapper; m = PseudonymMapper(); print(m.assign('PERSON', 'John Smith'))"` returns `PERSON_0001`.

**Effort:** 4–6 hours.

---

## Phase B — Verification depth + custom recognizers (Week 2)

Citation Engine gets tolerant-match for OCR-affected sources. Anonymization gains legal-domain recognizers and is wired into the gateway pipeline.

### Task M2-B1 — Citation Engine Stage 2 (tolerant-match)

**Scope:**
- Add `rapidfuzz ~= 3.5` to `api/pyproject.toml`.
- Implement `normalize()` in `api/app/citation/normalization.py`:
  - Whitespace normalization: collapse runs of whitespace, normalize line breaks (`\r\n` → `\n`), strip leading/trailing whitespace.
  - Quote normalization: smart quotes (`"`, `"`, `'`, `'`) → straight quotes (`"`, `'`).
  - OCR-aware normalization (only when `document.was_ocrd = True`): replace common OCR confusions:
    - `rn` → `m` (when in mid-word position)
    - `cl` → `d` (specific contexts)
    - `O` ↔ `0`, `l` ↔ `1` when adjacent to digits
    - Document the conservative-substitution rules in code comments.
- Implement `verify_tolerant_match(citation, document)`:
  - Normalize both source-at-offsets and citation-text per the same rules.
  - `rapidfuzz.fuzz.ratio(normalized_source, normalized_cited)` — threshold ≥ 95 passes.
  - Confidence = score / 100.
- Wire into verification pipeline: Stage 2 runs only if Stage 1 fails.
- Persist with `verification_method = 'tolerant_match'`.
- Unit tests for each normalization rule + integration tests for end-to-end tolerant matching.

**Dependencies:** M2-A2.

**Output:** Citations with minor formatting differences (smart quotes, whitespace, OCR cleanup) pass Stage 2.

**Verification:**
- Test corpus includes documents with deliberate formatting variance; Stage 2 catches them.
- Threshold calibration documented; document why 95 was chosen and where it landed in testing.

**Effort:** 6–8 hours.

---

### Task M2-B2 — Anonymization custom legal recognizers

**Scope:**
- Create `gateway/app/anonymization/recognizers/case_number.py`:
  - `CaseNumberRecognizer` extending `PatternRecognizer`.
  - Patterns for federal case citations (`Smith v. Jones, 123 F.3d 456 (9th Cir. 2024)`), state case citations, and loose case-caption mentions (lower confidence).
- Create `gateway/app/anonymization/recognizers/matter_number.py`:
  - `MatterNumberRecognizer` extending `PatternRecognizer`.
  - Patterns for common matter-numbering conventions: alpha-year-sequence (`LQ-2026-0042`), dotted (`2026.0042`), other operator-configurable patterns.
  - Document that matter-number patterns are operator-specific and should be calibrated to the deployment's actual numbering convention.
- Register both recognizers with the Analyzer in `engine.py`.
- Configure Presidio's default-recognizer list:
  - **Enabled:** PERSON, ORG, EMAIL_ADDRESS, PHONE_NUMBER, US_BANK_NUMBER (mapped to ACCOUNT_NUMBER), LOCATION (mapped to ADDRESS), CASE_NUMBER (custom), MATTER_NUMBER (custom).
  - **Disabled:** US_PASSPORT, US_DRIVER_LICENSE, US_SSN (false-positive-prone in legal docs), CRYPTO, IBAN_CODE, IP_ADDRESS, MEDICAL_LICENSE — these are noise for legal corpus and increase false-positive rate.
  - Document the disabled list and reasoning in `gateway/app/anonymization/engine.py` comments.
- Unit tests in `gateway/tests/anonymization/test_recognizers.py`:
  - Each custom recognizer catches its target patterns.
  - Each custom recognizer doesn't catch obvious non-targets.
- Documentation: `docs/security/anonymization.md` — operator's guide to customizing recognizers for their specific matter-numbering convention or other domain-specific entities.

**Dependencies:** M2-A3.

**Output:** Custom recognizers integrated; Analyzer configured for legal-document corpus.

**Verification:**
- Test corpus of 10 sample legal documents; recognition catches expected entities; false-positive rate ≤ 5% on a clean run.

**Effort:** 8–10 hours.

---

### Task M2-B3 — Gateway pre/post middleware integration

**Scope:**
- Create `gateway/app/anonymization/middleware.py`.
- Pre-middleware (`pre_anonymize_request`):
  - Operates on the incoming request payload.
  - Walks the `messages` array — for each message with role `user`, `assistant`, `system`: extract content, run through Analyzer + AnonymizerEngine, replace content with pseudonymized version.
  - Walks `skill_inputs` if present — recursively pseudonymizes string values.
  - Constructs `PseudonymMapper` for the request; stores in request context.
  - **Skips entirely** if:
    - `gateway.yaml` `anonymization.enabled = false`, OR
    - The request's routed tier is NOT in `anonymization.apply_at_tiers`, OR
    - The request indicates `privileged: true` (which the backend passes through from the chat's privileged-flagged Project), OR
    - The request indicates `anonymize: false` (per-request opt-out).
- Post-middleware (`post_anonymize_response`):
  - Operates on the streaming or completed response.
  - For streaming responses: rehydrate each delta as it arrives.
  - For complete responses: rehydrate the full message + each citation's `source_text` field.
  - After rehydration, the mapping is discarded (the request context is destroyed).
- Wire into gateway pipeline at the position specified in PRD §4.3:
  - `Auth → Router → Rate Limit → Tier Derivation → Anonymization-Pre → Provider Adapter → Anonymization-Post → Cost Tracker → Telemetry`.
- Update `gateway.yaml.example` with the `anonymization` block (already documented; ensure values match what middleware reads).
- Integration tests in `gateway/tests/anonymization/test_middleware.py`:
  - Pre-middleware pseudonymizes chat content.
  - Post-middleware rehydrates correctly.
  - Privileged-flagged requests skip anonymization.
  - Tier-based gating works (e.g., Tier 1 requests don't trigger anonymization).

**Dependencies:** M2-A3, M2-B2.

**Output:** Anonymization is operationally integrated in the gateway pipeline.

**Verification:**
- End-to-end test: send a chat with `anonymize: true` containing person names → gateway logs show pseudonymized version sent to provider → response rehydrated correctly.
- Audit log entry includes `anonymization_applied: true` in the `inference_routing_log`.

**Effort:** 10–12 hours.

---

## Phase C — LLM judge + UI rendering (Week 3)

Stage 3 lands (paraphrase judge); failed-citation rendering becomes visible in the chat UI; Anonymization round-trip is tested for correctness invariants.

### Task M2-C1 — Citation Engine Stage 3 (paraphrase judge)

**Scope:**
- Implement `verify_paraphrase(citation, document)` in `api/app/citation/verification.py`.
- Judge prompt construction in `api/app/citation/judge_prompts.py`:
  - Variables: `claim_text` (the model's cited claim), `chunks` (the source chunks the citation references, with offsets).
  - Structured JSON output: `{"verdict": "yes" | "partial" | "no", "confidence": "high" | "medium" | "low", "justification": "..."}`.
  - Calibration: prompt explicitly biases toward "no" / "partial" on uncertainty; document this in the prompt.
- Judge model selection:
  - Read from `gateway.yaml` `citation_engine.judge_model` (new config section).
  - Default: a different model from the citation-generating model when possible (e.g., if model is `smart` → judge with `fast`).
  - When the same provider must judge its own output (single-provider deployments), use a smaller/different model from the same family.
- Wire as Stage 3: runs only if Stages 1 and 2 fail.
- Persist with `verification_method = 'paraphrase_judge'` and `verification_confidence` derived from judge's confidence response.
- A `partial` verdict persists as `verified = TRUE` but with a `partial = TRUE` field on `message_citations` (or via verification_method = 'paraphrase_judge_partial'). UI renders these distinctly per M2-C2.
- Handle judge-call failures gracefully:
  - Malformed JSON output → fall through to unverified (don't crash).
  - Judge timeout → fall through to unverified.
  - Log judge errors but don't surface to user.
- Unit tests against a tagged test corpus.

**Dependencies:** M2-B1.

**Output:** Paraphrased citations are evaluated by an LLM judge; verified-with-caveats is a first-class state.

**Verification:**
- Test corpus includes citations with paraphrased claims; Stage 3 produces sensible verdicts.
- Judge-call failures don't crash the pipeline.
- Judge-call cost is bounded (uses configured judge model, not the larger primary model).

**Effort:** 10–12 hours.

---

### Task M2-C2 — Failed-citation UI rendering

**Scope:**
- Update chat-message rendering in `web/` (the OpenWebUI fork's message component).
- Implement five citation states with distinct visual treatment:

| State | Visual | Click behavior | Tooltip |
|---|---|---|---|
| Verified-exact | Green checkmark + underline | Highlights span in source viewer | "Verified verbatim against source." |
| Verified-tolerant | Green checkmark + underline | Highlights span in source viewer | "Verified against source (minor formatting differences)." |
| Verified-paraphrase | Yellow checkmark + underline | Highlights cited chunks; surfaces judge justification | `Verified by judge ({confidence}): "{justification}"` |
| Unverified | Greyed text + inline "[unverified]" marker | Not clickable | "Could not verify this citation against the source. The model may have produced a claim that doesn't follow from the cited content." |
| System error | Yellow warning icon + greyed text | Not clickable | "Verification could not complete due to a system error. Treat as unverified." |

- The visual treatment is **load-bearing for procurement reviews**. Verified citations look distinctly different from unverified ones. The procurement-reviewer test: scrolling the report, a reviewer should be able to identify unverified citations without reading the tooltips.
- Update `docs/quickstart.md` "Walk through the output" section to describe the visual states and the procurement context.
- Update `docs/architecture.md` Citation Engine section to reflect the five-state UI.
- Visual-regression tests: snapshot tests in `web/tests/citation-render.test.tsx` covering each state.

**Dependencies:** M2-C1.

**Output:** Verified, partially-verified, and unverified citations are visibly distinct in the chat UI.

**Verification:**
- Manual walk-through: chat with citations of each state present; each renders distinctly.
- Snapshot tests pass.
- Color choices accessible (WCAG AA compliance for color contrast).

**Effort:** 8–10 hours.

---

### Task M2-C3 — Anonymization round-trip correctness tests

**Scope:**
- Test suite in `gateway/tests/anonymization/test_round_trip.py`.
- Invariants to verify:
  1. **Byte-for-byte round-trip**: pseudonymize a document; rehydrate; result is byte-identical to original.
  2. **Cross-conversation stability**: same entity referenced in multiple messages within the same request gets the same pseudonym in all messages.
  3. **Per-request isolation**: pseudonyms in request A do not leak into request B's mapping (request-scoped only).
  4. **In-process-only persistence**: after request completes, the pseudonym mapping is not findable in logs, DB, MinIO/S3, or any persistent surface.
- Entity-overlap handling:
  - Test case: `John Smith Jr.` — both `John Smith` (PERSON) and the full name span are candidates; the longer overlap wins.
  - Test case: nested entities — handled per Presidio's `AnonymizerEngine` resolution.
- Edge cases:
  - Empty text → no-op.
  - Text with no recognized entities → unchanged.
  - Text shorter than a single entity → no-op.
  - Text containing existing pseudonym patterns (`PERSON_0001` in source) — see note below.
- **Note on pseudonym collisions**: if a source document happens to contain a string matching the pseudonym pattern (e.g., a contract that literally references "PERSON_0001"), this is an extremely rare edge case but worth documenting. Solution: in v1, log the occurrence and accept the resulting (minor) data leak to the user side (the user sees the literal string back); document as a known edge case. In a future iteration, pseudonym generation could use a per-request random salt to make collisions essentially impossible.

**Dependencies:** M2-B3.

**Output:** Anonymization round-trip is correct on the test corpus; round-trip correctness is part of the CI suite.

**Verification:**
- All invariants verified.
- Tests run in CI on every PR touching `gateway/app/anonymization/`.
- `grep` of logs for pseudonym strings on completed requests returns empty (mapping not leaked).

**Effort:** 6–8 hours.

---

## Phase D — Ensemble verification + integration (Week 4)

Stage 4 lands (ensemble verification); the two systems are integrated; edge cases swept.

### Task M2-D1 — Citation Engine Stage 4 (ensemble verification)

**Scope:**
- Implement `verify_ensemble(citation, document)` in `api/app/citation/verification.py`.
- Activation conditions:
  - The skill's frontmatter has `ensemble_verification: true`, OR
  - The chat's project has `ensemble_verification: true`, OR
  - The `gateway.yaml` `citation_engine.ensemble_verification.default_enabled: true`.
- Implementation:
  - Run paraphrase judge in parallel against `n` models (where `n` is configurable in `gateway.yaml`, default 3).
  - Models selected per `gateway.yaml` `citation_engine.ensemble_verification.judge_models` list — typically: primary judge + 2 alternate models from different provider families.
  - Aggregation rule (configurable in `gateway.yaml`):
    - **Strict (default)**: all judges must verdict "yes" → verified. Any disagreement → "verified-with-caveats" / partial state.
    - **Majority**: simple majority verdict wins; document the privacy-tier implication (the verification minimum tier becomes the maximum across the ensemble).
- Persist with `verification_method = 'ensemble_strict'` or `'ensemble_majority'`.
- UI rendering: disagreement appears as the verified-paraphrase yellow checkmark with a tooltip noting "Models disagreed: 2 of 3 verified."
- **Important privacy note**: ensemble verification implies the citation/claim is sent to `n` providers. The privacy posture for the request becomes the *minimum* tier across the ensemble (e.g., if one judge is Tier 4 commercial-cloud while the primary is Tier 3 ZDR-enterprise, the request as a whole is Tier 4). The gateway's tier-derivation logic must reflect this for ensemble-verified messages. Update tier-derivation accordingly.
- Configurable cost-budget: `gateway.yaml` `citation_engine.ensemble_verification.max_cost_per_message_usd`. If exceeded, fall back to single-judge with a warning logged.
- Unit tests against test corpus with deliberate-disagreement cases.

**Dependencies:** M2-C1.

**Output:** Ensemble verification is operational for skills with `ensemble_verification: true`.

**Verification:**
- Test with `ensemble_verification: true` on NDA Review against the sample NDA; verify all citations are evaluated by multiple judges.
- Test disagreement case: a citation where judges produce different verdicts surfaces as "verified-with-caveats" in UI.
- Tier-derivation correctly accounts for ensemble: an ensemble that includes a Tier 4 judge produces a Tier 4 routing decision overall.
- Cost-budget enforcement works.

**Effort:** 10–12 hours.

---

### Task M2-D2 — Citation Engine ↔ Anonymization integration

**Scope:**
- Confirm the architecture: per Decision M2-1, source documents in retrieval are NOT pseudonymized. Citations operate on un-pseudonymized text on both sides.
- Verify the integration in practice:
  - Chat with both Citation Engine and Anonymization enabled.
  - User's chat content includes entities → pseudonymized in pre-middleware.
  - Retrieval pulls source chunks → un-pseudonymized.
  - Model sees pseudonymized chat content + un-pseudonymized source chunks.
  - Model's citations reference un-pseudonymized source — citation verification operates correctly.
  - Model's chat response may reference pseudonyms (`PERSON_0001`) — post-middleware rehydrates these to original.
- Document this flow in `docs/security/anonymization.md` and `docs/citation-engine.md` (new file).
- Note Option A (source documents also pseudonymized) as DE-269 in PRD §9.
- Integration test: end-to-end chat with both layers active; verify no entity leakage to provider AND correct citation verification.

**Dependencies:** M2-C3, M2-D1.

**Output:** Both systems coexist correctly; the integration is documented and tested.

**Verification:**
- Provider log inspection: pseudonymized chat content visible; un-pseudonymized source content visible (in the operator's deployment, where this is expected and acceptable per the architecture).
- Citations resolve correctly to un-pseudonymized source.
- Rehydrated response is byte-identical in entity-mention sections.

**Effort:** 4–6 hours.

---

### Task M2-D3 — Privileged-project handling [parallel with M2-D2]

**Scope:**
- Verify anonymization is skipped for projects with `privileged: true` (already implemented in M2-B3; this task is verification).
- Verify Citation Engine continues to operate normally — no special handling for privileged projects on citation verification side.
- Audit log verification: privileged-project requests show:
  - `privilege_marked: true`
  - `privilege_basis: project_privileged_flag` (or matter-specific basis if set)
  - `anonymization_applied: false`
  - `routed_inference_tier`: whatever the chat actually routed against (with project-level `minimum_inference_tier` enforced).
- Update procurement-readiness documents:
  - `docs/security/anonymization.md` — explicit note that privileged projects skip anonymization by default and the rationale (Tier 1 / local is the preferred posture for privileged content; anonymization complicates privilege analysis).
  - `docs/procurement/sig-lite.md` — relevant SIG Lite question responses updated to reflect this.

**Dependencies:** M2-B3.

**Output:** Privileged-flagged projects have clean, auditable handling.

**Verification:**
- Test scenario: privileged project + Anonymization globally enabled + chat sent. Audit log shows expected values. Provider receives un-pseudonymized content (because privileged projects skip the pre-middleware).
- The combination "privileged: true + minimum_inference_tier: 1" works correctly — local Ollama inference, no anonymization, fully sealed.

**Effort:** 4–6 hours.

---

### Task M2-D4 — Edge case sweep

**Scope:**

**Citation Engine edge cases:**
- Citations spanning chunk boundaries:
  - Test: model produces a citation whose offsets span chunks 4 and 5. Verification should re-read across the boundary in `documents.normalized_content`.
- Empty source documents:
  - Test: empty `documents.normalized_content` with citation offset references → fall through to unverified gracefully (not crash).
- Cross-document citations:
  - Test: a message with citations from multiple source documents. Each verification call resolves correctly to its document.
- Failed retrieval:
  - Test: citation references a `source_file_id` that was deleted between message creation and verification. Surface as system-error state.

**Anonymization edge cases:**
- Long entity names (>200 chars): truncate gracefully; document as a limitation.
- Entities in cited spans: rehydration must walk citations too (already implemented in M2-B3; this is a verification test).
- Pseudonym collisions: source text containing a literal pseudonym pattern. Log occurrence; accept minor leak; document.
- Multi-line entities: entity spans crossing line boundaries (rare but possible). Verify Presidio handles this.
- Foreign-language entities: out of scope for v1 (Anonymization is English-only); document as a known limitation.

**Integration edge cases:**
- Ensemble verification + Anonymization: ensemble runs against pseudonymized content. Rehydration after ensemble verification. Verify cost-budget enforcement still works.
- Streaming response + Anonymization rehydration: rehydration must occur per-chunk as the stream arrives. Test streaming explicitly.

Document edge cases and the system's behavior in `docs/citation-engine.md` and `docs/security/anonymization.md` (the "known limitations" sections).

**Dependencies:** All of Phase C and M2-D1/D2.

**Output:** Edge cases are tested and documented; no surprises before public release.

**Verification:**
- Each edge case has at least one regression test.
- The "known limitations" sections in the two documents enumerate every documented limitation.

**Effort:** 8–10 hours.

---

## Phase E — Azure adapter + ensemble tuning (Week 5)

The Azure OpenAI adapter lands (small but strategically important); ensemble verification gets a final calibration pass against the test corpus.

### Task M2-E1 — Azure OpenAI provider adapter (DE-267)

**Scope:**
- Implement `AzureOpenAIAdapter` in `gateway/app/providers/azure_openai.py`.
- Follow the existing `OpenAIAdapter` pattern; differences are:
  - Authentication: API key + endpoint + deployment name + API version.
  - Model is identified by Azure "deployment name" rather than model name.
  - URL construction: `{base_url}/openai/deployments/{deployment_name}/chat/completions?api-version={api_version}`.
- Use the `openai` Python SDK's `AzureOpenAI` class (already in dependencies; no new dependency).
- Update `gateway.yaml.example` with a complete Azure provider example:
  ```yaml
  - name: azure-openai
    type: azure_openai
    base_url: https://${AZURE_OPENAI_RESOURCE}.openai.azure.com
    api_key_env: AZURE_OPENAI_API_KEY
    api_version: '2024-08-01-preview'
    deployments:
      - name: gpt-4-turbo
        azure_deployment: prod-gpt4
      - name: gpt-4o
        azure_deployment: prod-gpt4o
    tier: 3  # Azure OpenAI under operator's Azure subscription
  ```
- Add `azure_deployment` field to the provider config schema; the gateway resolves model → deployment when routing.
- Tier-derivation rules:
  - Azure OpenAI under operator's Azure subscription with standard commercial terms → Tier 3 (Azure's terms exclude training; this is consistent with operator-account inference).
  - If operator has ZDR add-on or specific contract excluding logging → Tier 2.
  - Tier 3 is the documented default; the operator overrides if they have stricter terms.
- Unit tests with mocked Azure responses.
- Provider-integration test (gated behind `pytest -m provider`).
- Update `docs/architecture.md` provider list.

**Dependencies:** None directly (parallel-able with Phase D).

**Output:** Azure OpenAI is a configurable provider; tier-derivation reflects Azure's contractual posture.

**Verification:**
- Unit tests pass.
- Provider-integration test (against a real Azure OpenAI deployment) passes.
- `gateway.yaml.example` documents the configuration cleanly.

**Effort:** 8–12 hours.

---

### Task M2-E2 — Ensemble verification calibration pass

**Scope:**
- Run ensemble verification against the M1 acceptance-testing corpus.
- Measure:
  - Disagreement rate (how often do the 3 models disagree?).
  - Per-skill disagreement rate.
  - Cost per ensemble verification (USD per message).
- Calibrate the strict-vs-majority default based on results:
  - If strict produces too many "verified-with-caveats" surfaces (frustrating users), majority may be preferable.
  - If majority is too permissive (false positives that strict would catch), keep strict as default and surface ensemble cost.
- Document calibration findings in `docs/citation-engine.md`.
- Update `gateway.yaml.example` with calibrated default values for the ensemble config.

**Dependencies:** M2-D1, M2-D4.

**Output:** Ensemble verification has empirically-calibrated defaults rather than guessed values.

**Verification:**
- Calibration report documents the measurement and the chosen defaults.
- Defaults in `gateway.yaml.example` match the calibrated values.

**Effort:** 6–8 hours.

---

## Phase F — Acceptance testing + documentation (Week 6)

The trust-layer documentation lands. Acceptance test corpora are built for both Citation Engine and Anonymization. Procurement docs reflect M2 capabilities.

### Task M2-F1 — Citation Engine acceptance test corpus — ✓ Closed (scope reframe, 2026-05-17)

**Status:** **✓ Closed via scope reframe** rather than separate corpus build. During M2-F1 kickoff Kevin clarified the three-type citation taxonomy:

1. **KB-quote accuracy** — verify the model's response accurately represents the cited KB document.
2. **Case citation validation** — verify a case citation refers to a real opinion. *Not in M2 scope; tracked at [PRD §9 DE-279](PRD.md#de-279--case-citation-validation-bluebook-resolution-via-courtlistener).*
3. **Case-content accuracy** — verify a statement about a case matches the holding. *Not in M2 scope; tracked at [PRD §9 DE-280](PRD.md#de-280--case-content-accuracy-statement-vs-judicial-opinion).*

M2 shipped type 1 across Phases A–D. Verification of type-1 behavior already lives in:

- `api/tests/citation/test_extraction.py` + `test_verification.py` + `test_verify_ensemble.py` — unit coverage for Stages 1–4 (exact-match, tolerant-match, paraphrase-judge, ensemble).
- `api/tests/test_chat_citations.py` — integration coverage for the full chat-emits-citation → engine-verifies → message_citations row persisted path, including the privileged-project audit-trail integration test.
- `api/tests/citation/test_round_trip_correctness.py` — round-trip invariants (M2-C3, 17 slow-marked tests).
- `web/cypress/e2e/m2-c2-citation-states.cy.ts` — UI rendering states across the four verification verdicts.
- `api/tests/citation/test_edge_cases.py` + `gateway/tests/anonymization/test_edge_cases.py` — M2-D4 edge-case sweep (14 tests; closed Phase D).
- Real-stack browser verification on uploaded NDAs during M2-C2 (cascade fixes for ingest-worker env + entrypoint surfaced and merged).

A separate annotated corpus + eval runner would duplicate the existing pin coverage for type-1 behavior and would not move the project closer to types 2 or 3 (those are different surfaces; see DE-279 / DE-280 for their distinct architectures). The plan-stated targets (Stage 1 ≥40%, Stage 1+2 ≥75%, FP <2%, FN <10%) are claims the existing tests assert at the per-case level rather than aggregate metrics — operators reading the test fixtures can see exactly what behaviors are pinned.

**Original scope (preserved for historical reference; not built):**

- Curate 30–50 documents with ground-truth citation annotations.
- Build runner: `scripts/run_citation_engine_eval.py` reporting per-stage pass rates, false-positive rate, false-negative rate, cost per evaluation.
- Baseline targets: Stage 1 ≥40%, Stage 1+2 ≥75%, Stage 3 +~15%, FP <2%, FN <10%.
- Document corpus + runner + baseline in `docs/citation-engine.md`.
- Add eval to CI as a nightly job (not blocking; informational).

This original scope can be revisited if/when type-2 or type-3 validation lands — at that point an aggregate empirical baseline across all three types makes sense.

**Closeout sequence updated** (Kevin, 2026-05-17): M2-E1 ✓ → ~~M2-F1~~ ✓ (scope reframe) → **M2-E2 (next)** → M2-F2 → M2-F3.

---

### Task M2-F2 — Anonymization acceptance test corpus — ✓ Closed (transparency-first deferral, 2026-05-17)

**Status:** **✓ Closed via transparency-first deferral.** Unlike [M2-F1](#task-m2-f1--citation-engine-acceptance-test-corpus--closed-scope-reframe-2026-05-17) where the existing test coverage made the corpus redundant, M2-F2's underlying question is **genuinely open**: Presidio default-recognizer recall + precision on legal-document corpus is empirically unmeasured, and the maintainer team does not have the practice-specific judgment needed to author ground-truth annotations across the diversity of in-house legal workflows the project serves.

The chosen response, per Kevin's framing on 2026-05-17:

> "What we're shooting for is if we don't do something to the highest level of transparency, confidentiality and privilege we note it and ask for the community to contribute to accomplish it — honest, transparent and lets the user know where to trust and where to be careful — for example, absent this, a user might choose to use local inference to hedge against the risk — let's give them all the information they need to make the right professional decision — we win on transparency."

Specifically:

1. **`docs/security/anonymization.md` gained a top-level "What's validated vs what's unvalidated" section** that explicitly enumerates what the existing test coverage measures (custom recognizers, middleware integration, round-trip correctness, edge cases) and what it does not measure (Presidio default-recognizer recall + precision on legal corpus, disabled-recognizer trade-offs per practice area).
2. **The risk framing is explicit**: a recognizer miss is a silent confidentiality incident, distinct from citation-verification misses which surface in the UI. Operational telemetry cannot recover the leak post-hoc — pre-deployment empirical validation is the right shape of work, but the project does not have the data to produce it.
3. **Actionable guidance is provided**: practicing attorneys who cannot accept the unvalidated risk for a given matter are pointed to Tier 1 (fully local) inference, the explicit "disable anonymization" posture, pre-redaction at upload, or manual per-message review. The user has all the information they need to make the right professional decision.
4. **The work is invited from the community via [PRD §9 / DE-282](PRD.md#de-282--anonymization-layer-empirical-validation-on-legal-document-corpus)**, structured to combine bounded technical work (runner + metrics + CI wiring) with practice-specific judgment work (entity-type prioritization, ground-truth annotations, recognizer-set re-evaluation per practice area). Personal-injury, employment, immigration, benefits, healthcare, and international-practice contributors are explicitly welcomed.

The original M2-F2 scope (curate ~50 docs, build runner, hit baseline targets) is preserved verbatim in DE-282 — a contributor picking up the DE can execute against the same plan.

**Original scope (preserved at DE-282 for contributors; not built by the maintainer team in v0.2):**

- Curate ~50 legal documents with ground-truth entity annotations.
- Build runner: `scripts/run_anonymization_eval.py` reporting per-entity-type recall, precision, F1.
- Baseline targets: PERSON / ORG ≥95% / ≥90%; EMAIL / PHONE ≥98% / ≥98%; ADDRESS ≥85% / ≥80%; CASE_NUMBER / MATTER_NUMBER ≥70% / ≥75%.
- Document the baseline in `docs/security/anonymization.md`.

**Closeout sequence final** (Kevin, 2026-05-17): M2-E1 ✓ → ~~M2-F1~~ ✓ (scope reframe; existing coverage is sufficient) → M2-E2 ✓ (cost calibration shipped) → ~~M2-F2~~ ✓ (transparency-first deferral; DE-282 invites community contribution) → **M2-F3 (next, final)**.

---

### Task M2-F3 — Documentation finalization

**Scope:**
- New documents:
  - `docs/citation-engine.md` — full Citation Engine documentation: architecture, 4 stages, UI states, judge prompt design, ensemble configuration, edge cases, acceptance-test baseline.
  - `docs/security/anonymization.md` — full Anonymization documentation: pipeline, entity types, custom recognizers, operator customization guide, privileged-project handling, integration with Citation Engine, edge cases, acceptance-test baseline.
- Updated documents:
  - `docs/PRD.md` — changelog entry for M2 release; capability sections §3.3 and §4.7 updated to reflect actual implementation (close any "as-planned" deltas).
  - `docs/architecture.md` — Mermaid diagram updated if M2 introduced new components (it didn't substantially, but verify); Inference Gateway pipeline diagram updated with Anonymization-Pre / Anonymization-Post positions confirmed.
  - `docs/quickstart.md` — Step 5 "Walk through the output" updated to describe the 5 citation states; Step 7 "Inference Tier badge" updated to mention `anonymization_applied` indicator if present.
  - `README.md` — capability list updated to reflect Citation Engine and Anonymization as shipped.
  - `docs/compliance/soc2-alignment.md` — relevant controls updated.
  - `docs/compliance/iso27001-alignment.md` — same.
  - `docs/procurement/sig-lite.md` — questions about citation verification and data minimization updated with M2 capabilities.
- New DE entries in `docs/PRD.md` §9:
  - DE-269: Option A anonymization (pseudonymize source documents in retrieval).
  - DE-XXX: any other ideas surfaced during M2 build.
- Release-readiness check: a reviewing attorney walks through the quickstart against an M2 deployment and confirms the experience matches the documentation.

**Dependencies:** All of Phase A–E.

**Output:** Documentation matches implementation.

**Verification:**
- Reviewing-attorney walk-through passes.
- Cross-reference audit: `grep -rn` of internal links resolves cleanly.

**Effort:** 8–12 hours.

---

## Total effort estimate

| Phase | Tasks | Effort |
|---|---|---|
| **A — Foundation** | 3 | ~16 hours |
| **B — Verification depth + custom recognizers** | 3 | ~26 hours |
| **C — LLM judge + UI** | 3 | ~26 hours |
| **D — Ensemble + integration** | 4 | ~28 hours |
| **E — Azure + calibration** | 2 | ~18 hours |
| **F — Acceptance + docs** | 3 | ~36 hours |
| **Total** | 18 | ~150 hours |

150 hours fits in a focused 6-week M2 build by a single contributor working full-time, or ~8 weeks for someone working part-time. Parallel-execution opportunities (M2-A2 / M2-A3, M2-D2 / M2-D3, M2-E1 alongside Phase D) compress to ~5 weeks if the contributor has parallel agent execution available.

---

## How to use this with Claude Code

The recommended workflow mirrors the M1 implementation:

1. **Hand Claude Code this document, plus `docs/PRD.md`, `docs/db-schema.md`, `docs/api/backend-openapi.yaml`, `docs/api/gateway-openapi.yaml`, `gateway.yaml.example`, and `CLAUDE.md`.**
2. **Pick the next task by ID:** "Implement Task M2-A1 — Add normalized content + OCR flag to documents."
3. **Let Claude Code execute the full task in one session.** Each task is sized for a focused session.
4. **Verify against the documented verification step.** If verification fails, work with Claude Code to fix; do not move to the next task until current verifies.
5. **Move to the next task.** Tasks marked **[parallel]** can run concurrently in separate sessions if parallel agent execution is available.
6. **Don't let Claude Code make architectural decisions mid-task.** Decisions M2-1 and M2-2 are locked at the start; if a task surfaces a question those decisions don't anticipate, stop, decide, document.
7. **Surface ideas as DE-XXX entries.** When Claude Code surfaces useful ideas out of M2 scope, file them as deferred enhancements in PRD §9.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| LLM judge produces inconsistent verdicts | Lock judge model version in `gateway.yaml`; calibrate prompt against test corpus; track judge agreement over time via Langfuse. |
| Anonymization recognizes too aggressively (false positives) | Calibrate threshold (Presidio score threshold) against legal corpus; disable noise-prone default recognizers; operator-customizable per deployment. |
| Anonymization recognizes too cautiously (false negatives) | Provide custom-recognizer pattern for matter-specific entities; document customization path; track recall in acceptance-test eval. |
| Ensemble verification cost overruns | Configurable cost budget per message; fall back to single-judge with warning when exceeded; track cost-per-message in admin dashboard. |
| Privileged-project handling has subtle bug (anonymization-applied when it shouldn't be, or tier-routing wrong) | Dedicated test coverage (M2-D3); periodic audit-log review by security reviewer. |
| Citation Engine verification creates a perf bottleneck | Stages 1 and 2 are sub-millisecond; Stage 3+ are LLM calls (already async). Pipeline runs in parallel with response streaming where possible. P95 latency tracked via OTel spans on `verify()` / `verify_ensemble()` in production rather than via a synthetic corpus run. |
| OpenAI / Anthropic SDK changes break adapters | Pin SDK versions; track upstream releases; bug-fix releases for SDK updates ship as patch versions. |

---

## What this plan does not cover

A few items deliberately out of scope for M2; tracked for M3 or later:

- **Tabular / Multi-Document Review** — M3, builds on M2 Citation Engine substrate.
- **Playbooks** — M3, also builds on M2 Citation Engine.
- **Word Add-In** — M3, the surface coverage that lands once verified-citations are stable.
- **Slack/Teams Bridge** — M3.
- **Autonomous Layer** — M4.
- **Contract Repository auto-relationship detection** — M4.
- **Option A Anonymization (pseudonymize source documents)** — DE-269, future consideration.
- **Multi-language Anonymization** — DE-XXX, future consideration; English-only in M2.

---

*Implementation plan maintained alongside the PRD. As tasks complete, mark them so the next contributor (or agent) sees current state. Tasks that need decomposition are split in-place and the document updated.*
