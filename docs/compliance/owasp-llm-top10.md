# OWASP Top 10 for LLM Applications (2025) — LQ.AI Mapping

> **Status:** AI-drafted, pending professional review.

> **Framework version:** OWASP Top 10 for LLM Applications, **2025 edition** (risk IDs `LLM01:2025`–`LLM10:2025`).
> **LQ.AI state pinned to:** the fiduciary-grade agentic legal work milestone (ADRs 0018–0021; migration head `0064`), per [`docs/HONEST-STATE.md`](../HONEST-STATE.md).
> **Re-review triggers:** a new OWASP edition, or a change to any repo path cited below.

**Attribution and licensing.** This document references the [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/) by the OWASP GenAI Security Project, licensed [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Because LQ.AI is Apache-2.0-licensed, this document cites OWASP risks **by ID and short name only** and does not reproduce OWASP's descriptive text; every threat description and all analysis below is original work product written for LQ.AI's architecture. Read the official OWASP entries alongside this mapping for the framework's own definitions.

---

## Scope and limits

This is a **self-assessment by the project**, not an audit, an attestation, or a certification. It maps each 2025-edition risk to LQ.AI's architecture: what the codebase enforces structurally, what the operator configures, what risk remains, and what the operator must own. Every structural claim cites a repository path so a reviewer can verify it in source rather than take the claim on faith. Where a control does not exist, the row says so explicitly (`no evidence yet`) instead of gesturing at alignment — the project's conservative-posture rule ([CLAUDE.md](../../CLAUDE.md), [`docs/HONEST-STATE.md`](../HONEST-STATE.md)) applies to this document as much as to any release note.

Certifications attach to the operating organization, not to software. LQ.AI is software the operator deploys and runs; this mapping is the project's contribution to the operator's own AI-security review, not a substitute for it.

## How to read this document

Each risk section has five fields:

1. **Threat as it applies to LQ.AI** — self-authored description against the trust boundaries in [`docs/security/threat-model.md`](../security/threat-model.md).
2. **Structural controls (in code)** — enforced by the codebase as shipped; each claim cites a repo path.
3. **Operator-configured controls** — defaults and knobs the operator tunes; the control exists only if the operator turns it on or sets it correctly.
4. **Residual risk** — what is not mitigated today, with the deferred-enhancement (DE-XXX) reference where one exists.
5. **Operator responsibility** — what the operator must do to close or accept the residual risk.

Ownership vocabulary used throughout (per the project's compliance-pack taxonomy): **structural-in-code**, **operator-configured**, **shared**, **residual**, **out-of-scope**.

A load-bearing scope fact used in several rows: **LQ.AI trains and fine-tunes no models.** The repository contains no training pipeline, no fine-tuning jobs, and no model weights; all inference is bring-your-own-keys against operator-chosen providers (or operator-hosted Ollama at Tier 1), routed through the Inference Gateway — the only component holding provider keys and the only component making outbound calls ([`gateway/`](../../gateway/), [PRD §4](../PRD.md#4-the-lq-ai-inference-gateway)). Training-time risks therefore reduce to the operator's provider and model choice, governed by the Inference Tier model.

---

## LLM01:2025 — Prompt Injection

**Threat as it applies to LQ.AI.** LQ.AI's daily input is adversarial by profession: counterparty contracts, opposing filings, and third-party documents are ingested into knowledge bases, attached to chats, and run through skills. Any of these — plus external tool results (case-law text, MCP connector output) — can carry embedded instructions attempting to steer the analysis, exfiltrate chat context, or trigger tool calls. This is the risk PRD Appendix E names as "the genuinely-hard problem"; the project explicitly does not claim immunity.

**Structural controls (in code).**

- Skill prompt assembly uses bounded regex `{{var}}` substitution — no template engine, no expression evaluation ([ADR 0007](../adr/0007-skill-prompt-assembly.md); `gateway/app/skills/assembler.py`). Reference files are appended with explicit delimiters separating instructions from exhibit content.
- Skills are open-source work product (`skills/*/SKILL.md`, e.g. `skills/nda-review/SKILL.md`) — the entire instruction surface is readable, so a reviewer can audit exactly what the model is told before any untrusted content arrives.
- An injection that escalates to *action* hits the governed tool chokepoints: chat tool calls pass through `governed_tool_invocation` (`api/app/tools/governance.py`) and destructive/connector calls pause for explicit in-chat human approval before execution (`api/app/chat/tool_loop.py`; `web/src/lib/lq-ai/components/ToolGatePrompt.svelte`). Autonomous work passes through the single `guarded_tool_call` chokepoint under the R5/R6/R4 brakes (`api/app/autonomous/guard.py`).
- An injection that fabricates authority is bounded by the Citation Engine: unsupported citations fail the four-stage verification cascade and render as unverified (`api/app/citation/verification.py`), and the fiduciary gate records a FAIL verdict derived from the ledger (`api/app/citation/gate.py`).
- An injection that smuggles an exfiltration URL into a tool call is bounded by the SSRF-guarded egress allowlist — HTTPS-only, per-provider host allowlist, public-IP resolution check (`gateway/app/providers/tool/egress.py`).

**Operator-configured controls.** Tier policy (`allowed_tiers_global`, per-skill `minimum_inference_tier`; `gateway.yaml.example`, `gateway/app/tier_floor.py`) bounds which providers see sensitive context. Tool providers and MCP connectors are off by default and admin-enabled (`gateway.yaml.example` `tool_providers`; `api/app/api/admin_mcp.py`). The autonomous layer is per-user opt-in, off by default (`User.autonomous_enabled`).

**Residual risk.** There is **no injection-pattern detection shipped**: the prompt-injection pattern library is deferred ([DE-110](../PRD.md#9-deferred-enhancements-and-identified-future-work)) and no detection rates are measured ([DE-239](../PRD.md#9-deferred-enhancements-and-identified-future-work)) — `no evidence yet` on both. A sophisticated injection can still shape prose output that carries no citations and triggers no tool call; the verification layers do not catch that class.

**Operator responsibility.** Human-in-the-loop review of all work product (the profession's existing duty) is the operating mitigation for the residual class. Treat every counterparty document as untrusted input; keep the tool-confirmation gate on; vet MCP connectors before registering them.

---

## LLM02:2025 — Sensitive Information Disclosure

**Threat as it applies to LQ.AI.** The system processes the most disclosure-sensitive content a company holds: privileged communications, client-confidential contracts, matter files. Disclosure paths are: content leaving to an inference provider, secrets or content landing in logs and audit rows, cross-tenant reads inside the deployment, and provider-side retention.

**Structural controls (in code).**

- The gateway is the **sole egress point** — the backend holds exactly one outbound HTTP client, pointed at the gateway (`api/app/clients/gateway.py`); provider keys exist in plaintext only inside the gateway process ([`docs/security/threat-model.md`](../security/threat-model.md)).
- The Anonymization Layer is shipped and wired on the request path: pseudonymization before provider dispatch, streaming-aware rehydration on response (`gateway/app/anonymization/middleware.py`, wired in `gateway/app/api/inference.py`; recognizers in `gateway/app/anonymization/engine.py`). The pseudonym mapping is per-request, in-memory only — never persisted, never logged.
- Secrets at rest: provider API keys are Fernet-encrypted under an operator master key (`gateway/app/secrets.py`; [`docs/security/encrypted-keys.md`](../security/encrypted-keys.md)); per-user MCP OAuth tokens likewise (`api/app/security/encryption.py`).
- Audit and governance rows carry counts, types, IDs, and enums — never raw entity values, document text, or tool arguments (`api/app/audit.py`; `args_digest`-only in `api/app/models/tool_call_log.py`; the Citation Ledger references content by ID and character offset only, `api/app/citation/ledger.py`, per ADR 0016 P3).
- Tenancy: every data query is owner-scoped at the application layer (`WHERE owner_id = current_user.id`; see the api rows in [`docs/security/threat-model.md`](../security/threat-model.md)).

**Operator-configured controls.** Anonymization ships **disabled by default** (`anonymization.enabled: false` in `gateway.yaml.example`) — enabling it, choosing `apply_at_tiers`, and selecting entity types are operator decisions. Tier policy determines which provider terms (ZDR, no-training) govern outbound content; Tier 1 (local Ollama) keeps content in-deployment entirely.

**Residual risk.** Recognizer recall/precision on legal-document corpora is **empirically unmeasured** ([DE-282](../PRD.md#9-deferred-enhancements-and-identified-future-work)) — a recognizer miss is a silent confidentiality event, and no legal-corpus benchmark exists yet (`no evidence yet`). Source-document pseudonymization (DE-269) and per-request salting (DE-274) are open. By design, retrieval context is sent to the provider intact (anonymization retrieval-context skip) so citation grounding works — the operator's tier choice is the control for that content. A provider that has already received content is outside the trust envelope (threat model, out-of-scope threats).

**Operator responsibility.** Turn anonymization on where required and read [`docs/security/anonymization.md`](../security/anonymization.md) §"What's validated vs what's unvalidated" before relying on it; route privileged matters at Tier 1 or under enterprise ZDR terms; encrypt backups; manage TLS and key custody.

---

## LLM03:2025 — Supply Chain

**Threat as it applies to LQ.AI.** Four supply chains converge: Python/JS dependencies (including the forked OpenWebUI frontend), the models themselves, community-contributed skills, and external tool providers (MCP connectors, research sources).

**Structural controls (in code).**

- **BYO-keys removes the intermediary:** there is no project-operated service between the operator and their provider; the model supply chain is the operator's direct commercial relationship.
- Community skills are an **opt-in git submodule** (`skills/community/`, empty until initialized) and the loader gives built-in skills precedence on slug collision (`api/app/skills/loader.py`); the contribution path requires attorney attestation plus engineering review (`skills/CONTRIBUTING.md`; [`docs/security/external-contribution-vetting.md`](../security/external-contribution-vetting.md)).
- Tool egress is allowlisted per provider and SSRF-guarded (`gateway/app/providers/tool/egress.py`); every outbound tool call is audited in `tool_egress_log` (`api/app/models/tool_egress.py`). MCP connectors enter only through the admin registry (`api/app/api/admin_mcp.py`).
- Dependency posture is documented in [`docs/security/dependencies.md`](../security/dependencies.md).

**Operator-configured controls.** Which providers, models, connectors, and community skills are enabled is entirely operator-chosen; nothing external is on by default.

**Residual risk.** SLSA-3 provenance, Sigstore-signed images, and per-release SBOMs are **committed but not yet shipped as release artifacts** ([`docs/security/releases/README.md`](../security/releases/README.md); HONEST-STATE §8) — until they ship, image-to-commit verification is `no evidence yet`. Model weights and provider-side model supply chains are out-of-scope for the project and in-scope for the operator's provider due diligence. The OpenWebUI fork carries inherited upstream code (HONEST-STATE §8.1).

**Operator responsibility.** Run dependency scanning in the deployment environment; pin releases; perform provider and connector due diligence; review community skills before initializing the submodule.

---

## LLM04:2025 — Data and Model Poisoning

**Threat as it applies to LQ.AI.** Training-time poisoning is **largely out-of-scope, for a precise reason**: LQ.AI trains nothing — no training pipeline, no fine-tuning, no weights in the repository — so there is no project-side training corpus to poison. The applicable slice is *context* poisoning: a malicious or corrupted document planted in a knowledge base (or a poisoned community skill) skews retrieval-grounded output, and base-model poisoning risk transfers to the operator's provider/model choice.

**Structural controls (in code).**

- Uploaded files are content-addressed by SHA-256 (`files.sha256`, [ADR 0005](../adr/0005-file-storage-soft-delete-and-key-scheme.md)); the api re-verifies digests on privileged-Project download paths, so post-upload byte tampering is detectable (threat model, minio row).
- Ingestion is owner-scoped; a poisoned document can only affect the tenants that attached it (`api/app/workers/document_pipeline.py`; threat model tenancy posture).
- Citation verification compares model output against the actual source bytes (`api/app/citation/verification.py`) — a poisoned document cannot fake provenance *for other documents*; skills (the instruction-tuning analog) are reviewed work product, not learned parameters (`skills/CONTRIBUTING.md`).

**Operator-configured controls.** Upload rights follow the deployment's RBAC; KB curation and watch-triggered autonomous processing of new KB documents are operator/user choices (autonomous is opt-in).

**Residual risk.** There is **no content-level poisoning or anomaly detection on ingested documents** (`no evidence yet` — no scanner exists in `api/app/pipeline/`). Verification proves a quote *exists in the source*, not that the source is *true*: a poisoned document is faithfully and verifiably cited. Base-model poisoning is out-of-scope for the project.

**Operator responsibility.** Source hygiene for KB content (who may upload, from where); provider/model due diligence for the poisoning posture of the models selected.

---

## LLM05:2025 — Improper Output Handling

**Threat as it applies to LQ.AI.** Model output is rendered in a browser (XSS surface), can request tool execution, is exported to XLSX/CSV, and can be written back into knowledge bases as autonomous artifacts — each a channel where unvalidated output becomes an action or a stored payload.

**Structural controls (in code).**

- Rendering: assistant markdown passes through `marked` + `DOMPurify.sanitize` (`web/src/lib/lq-ai/components/MessageBubble.svelte`); SvelteKit default escaping covers non-message paths (threat model, web row).
- Output never executes directly: tool execution requests pass through the governed chokepoints with a human confirmation gate for destructive/connector calls (`api/app/tools/governance.py`, `api/app/chat/tool_loop.py`); autonomous actions pass through `guarded_tool_call` (`api/app/autonomous/guard.py`).
- Structured outputs are schema-parsed rather than free-form-interpreted (`api/app/autonomous/structured_output.py`); API responses are Pydantic-validated against the OpenAPI contract.
- Autonomous artifacts are opt-in (default OFF), markdown/plain-text only, and written through a single audited chokepoint (`emit_artifact` handling in `api/app/autonomous/guard.py`).

**Operator-configured controls.** `emit_artifacts` stays off unless enabled; connector approval gates what output-driven tool calls can reach.

**Residual risk.** Exports (XLSX/CSV from tabular review, `api/app/api/tabular.py`) carry model-generated content into downstream systems with no downstream sanitization guarantee. No measured coverage of output-handling paths exists (`no evidence yet` beyond the cited unit/E2E tests).

**Operator responsibility.** Treat exports as untrusted input to downstream systems; keep human review between model output and any filing, signature, or external communication.

---

## LLM06:2025 — Excessive Agency

**Threat as it applies to LQ.AI.** The Autonomous Layer and the chat tool-loop give the model real agency: running skills and playbooks, calling external research sources and MCP connectors, writing artifacts, spending money. The risk is action beyond user intent — in scope, in duration, or in cost.

**Structural controls (in code).**

- **Single chokepoints, by construction.** Every autonomous external action routes through `guarded_tool_call`, which enforces R5 (external halt + idle watchdog) → R6 (phase-gated tool grants, `PHASE_GRANTS` in `api/app/autonomous/enums.py`) → R4 (per-session and per-trigger cost caps, `api/app/autonomous/cost.py`) in order (`api/app/autonomous/guard.py`; pinned by `api/tests/autonomous/test_executor_skeleton.py::test_no_tool_call_bypasses_chokepoint`). Every chat tool call routes through `governed_tool_invocation` (`api/app/tools/governance.py`).
- **Human gate on consequential calls:** destructive and connector tool calls persist and pause for explicit in-chat approval before the turn resumes (`api/app/chat/tool_loop.py`; migration `0054`).
- **Hard exits:** external halt endpoint plus idle watchdog terminate sessions (`api/app/workers/autonomous_worker.py`); every session ends in an honest receipt naming the terminal reason (`api/app/autonomous/receipt.py`).
- **Bounded egress:** external reach is limited to allowlisted, SSRF-guarded providers (`gateway/app/providers/tool/egress.py`) and audited (`api/app/models/tool_egress.py`, `api/app/models/tool_call_log.py`).
- **Off by default:** autonomous is per-user opt-in (`User.autonomous_enabled`); tool providers require operator enablement.

**Operator-configured controls.** `max_cost_usd` caps per watch/schedule; which tool providers and connectors exist at all; who may opt in.

**Residual risk.** The ethics-review phase is a light v1 (a structured-output findings pass, not a dedicated LLM gate — HONEST-STATE §5 honesty notes). Read-only tool calls execute without per-call human approval (by design; the gate covers destructive/connector calls). Chat/autonomous fiduciary-gate verdict-tier parity is incomplete (DE-370, DE-371).

**Operator responsibility.** Keep opt-in deliberate and reviewed; set cost caps consistent with risk appetite; review session receipts and findings rather than treating autonomous output as pre-approved.

---

## LLM07:2025 — System Prompt Leakage

**Threat as it applies to LQ.AI.** LQ.AI inverts the usual posture: the "system prompts" — skills — are **published open-source work product** (`skills/*/SKILL.md`), so extraction of a built-in skill prompt discloses nothing that is not already in the repository. What remains sensitive is operator-authored content that enters prompt assembly: user-created skills, the Organization Profile's standards (`api/app/models/organization_profile.py`), and the per-session confidential context (documents, inputs).

**Structural controls (in code).**

- **No secrets in the prompt path by design:** prompt assembly composes skill body, inputs, and context (`gateway/app/skills/assembler.py`); provider credentials live only in gateway configuration (`gateway/app/secrets.py`) and are never part of any prompt or response.
- Logging discipline: routing and audit records carry metadata (provider, model, tier, token counts, cost — `gateway/app/routing_log.py`, `api/app/models/inference.py`), not assembled prompt bodies.

**Operator-configured controls.** What goes into the Organization Profile, user skills, and saved prompts is operator/user-authored content; its sensitivity is set by its authors.

**Residual risk.** Prompt-extraction attacks remain possible in principle; their impact reduces to the confidentiality class of the session's own context (an attacker who can converse in a chat already holds access to that chat's context), i.e. this collapses into LLM02:2025 handling rather than a distinct secret-leak channel. No dedicated anti-extraction control exists (`no evidence yet`), and none is claimed.

**Operator responsibility.** Never place credentials, keys, or regulated secrets in skills, the Organization Profile, or saved prompts; the prompt surface should be treated as user-visible.

---

## LLM08:2025 — Vector and Embedding Weaknesses

**Threat as it applies to LQ.AI.** Knowledge bases use hybrid BM25 + pgvector retrieval; risks are cross-tenant retrieval leakage, embedding exfiltration or inversion at the provider, and poisoned KB content dominating retrieval (the retrieval face of LLM04:2025).

**Structural controls (in code).**

- Vector queries join through the `files`/`documents` tables and re-apply owner-scoped predicates; embeddings with no owner row are unreachable from the api (threat model, postgres row; `api/app/api/knowledge_bases.py`, `api/app/workers/document_pipeline.py`).
- Embedding generation routes through the gateway like all inference ([ADR 0008](../adr/0008-embedding-model-and-openai-adapter.md)) — the same sole-egress, key-custody, and tier discipline applies.
- Retrieval provenance is preserved end-to-end: retrieved chunks are what citations verify against (`api/app/citation/verification.py`), so retrieval manipulation surfaces as verification behavior rather than silent context drift.

**Operator-configured controls.** Embedding model/provider choice (and therefore where document text goes to be embedded); Tier 1 keeps embedding in-deployment via Ollama; KB membership and attachment are user-curated.

**Residual risk.** By deliberate design, retrieval context bypasses anonymization so the model sees intact source quotes for citation grounding (HONEST-STATE §3.2) — provider-side exposure of retrieved text is governed only by tier choice. No adversarial evaluation of retrieval leakage or embedding-inversion resistance has been performed (`no evidence yet`).

**Operator responsibility.** Choose the embedding tier to match document sensitivity; curate who can add documents to shared knowledge bases.

---

## LLM09:2025 — Misinformation

**Threat as it applies to LQ.AI.** The signature professional risk: hallucinated authority, misquoted sources, wrong legal conclusions delivered confidently. In legal practice a fabricated citation is a sanctionable event, not an inconvenience.

**Structural controls (in code).** This is the project's most heavily built surface:

- **Four-stage citation verification cascade** — exact match → tolerant match → LLM paraphrase judge → multi-model ensemble (`api/app/citation/verification.py`; [`docs/citation-engine.md`](../citation-engine.md)). A citation that fails every stage renders as *unverified*, never as a confident wrong quote.
- **Citation Ledger** — a per-turn record of every source and passage actually read, traceable claim-to-entry (`api/app/citation/ledger.py`; migration `0058`).
- **Fiduciary gate** — a derive-don't-assert PASS/FAIL verdict per assistant message, computed from the ledger's own verification statuses (`api/app/citation/gate.py`; migration `0059`; [ADR 0018](../adr/0018-citation-ledger-and-fiduciary-grade-output.md)).
- **Treatment signal** — case-law treatment derived from citing opinions, explicitly labeled "derived, not editorial"; it never asserts good-law/bad-law (`api/app/citation/treatment.py`; [ADR 0019](../adr/0019-transparent-validity-treatment-layer.md)).
- **Provenance separation** — external-source retrieval provenance ("Sources consulted", `api/app/models/message_tool_source.py`) is architecturally distinct from character-verified quotes (`message_citations`) and the two are never conflated.

**Operator-configured controls.** Ensemble verification for high-stakes operations; judge-model selection (`citation_engine` block in `gateway.yaml.example`).

**Residual risk.** A quote spanning two retrieved chunks silently drops at extraction ([DE-277](../PRD.md#9-deferred-enhancements-and-identified-future-work)). Result-content accuracy judging for legal-research results is deferred ([DE-280](../PRD.md#9-deferred-enhancements-and-identified-future-work)); verdict-tier parity between chat and autonomous paths is incomplete (DE-370, DE-371). Most fundamentally: verification proves a quote exists in a source — it does not verify the correctness of unquoted reasoning. No confabulation-rate benchmark is published (`no evidence yet`; related measurement work is DE-239's eval-harness track).

**Operator responsibility.** Attorney review of all work product remains mandatory; the gate and cascade are decision support for that review, not a replacement. Treat "unverified" renderings as a stop sign.

---

## LLM10:2025 — Unbounded Consumption

**Threat as it applies to LQ.AI.** Runaway token spend and resource exhaustion: autonomous loops, tabular review across large corpora, treatment-derivation judge passes, ensemble verification fan-out, or plain request flooding — all ultimately billed to the operator's provider keys.

**Structural controls (in code).**

- **R4 economic brake:** hard per-session *and* per-trigger cost caps on all autonomous work, enforced at the chokepoint before dispatch (`api/app/autonomous/cost.py`, `api/app/autonomous/guard.py`); sessions that hit the cap terminate with an honest `cost_cap_reached` receipt.
- **R5 temporal brake:** external halt plus idle watchdog bound session lifetime (`api/app/workers/autonomous_worker.py`).
- Tabular review computes a cost preview (including ensemble premium) before execution (`api/app/tabular/cost.py`); the treatment layer's judge pass runs under a bounded budget (ADR 0019 D4) rather than reading citing opinions exhaustively.
- Per-request cost accounting: every inference is logged with tokens and cost (`gateway/app/routing_log.py`, `api/app/models/inference.py`), giving the operator a complete metering surface (also exported via OpenTelemetry, [`docs/observability.md`](../observability.md)).
- Request-level hygiene: authenticated routes, edge-rate-limited login, body-size ceilings (threat model, api row); tool-provider calls are rate-limited (`gateway/app/providers/tool/ratelimit.py`).

**Operator-configured controls.** `max_cost_usd` on watches/schedules; tier and provider selection (which price book applies); provider-side spend limits on the operator's own keys.

**Residual risk.** **There is no per-user or deployment-wide spend quota on interactive chat inference** — the gateway meters cost but does not enforce a spend ceiling on the chat path (`no evidence yet`; verified by absence of any quota enforcement in `gateway/app/`). Tabular's mid-run per-cell ensemble cost ceiling is deferred (DE-331, noted in `api/app/tabular/nodes.py`).

**Operator responsibility.** Set spend limits with the provider (the authoritative backstop under BYO-keys); wire cost telemetry into alerting; size autonomous cost caps deliberately rather than accepting defaults.

---

## Cross-references

- [`docs/security/threat-model.md`](../security/threat-model.md) — STRIDE-by-component substrate for the threat fields above.
- [`docs/HONEST-STATE.md`](../HONEST-STATE.md) — shipped-vs-deferred catalog; this mapping's honesty caveats are drawn from it.
- [PRD §1.8 Security Posture](../PRD.md#18-security-posture) and [PRD Appendix E](../PRD.md#appendix-e--pre-empted-procurement-objections) — the procurement-facing prose behind several rows.
- [`docs/compliance/README.md`](README.md) — the Compliance Alignment Pack this document belongs to.
- A MITRE ATLAS technique-level mapping is a planned sibling document (same table grammar, Apache-2.0-licensed source data); rows here will cross-link per-risk when it lands.

---

*Self-assessment maintained with the Compliance Alignment Pack. Re-review on each OWASP edition change or when any cited path moves. AI-drafted, pending professional review.*
