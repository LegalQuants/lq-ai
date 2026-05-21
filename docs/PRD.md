# LQ.AI — Product Requirements Document

**Project:** LQ.AI
**Stewarded by:** LegalQuants
**License:** Apache 2.0
**PRD Version:** 0.2 (Competitive Research and Security Posture Absorption)
**Authored by:** Kevin Keller, contributed to LegalQuants
**Date:** May 7, 2026
**Status:** Draft for review

**Changelog from v0.1:** Absorbed competitive-research and security-posture recommendations from a separate research session. Added five new top-level concepts: Projects (matter-scoped containers, M1), Organization Profile (org-wide voice/standards skill, M1), Inference Tier model (five-tier security spectrum), Inference Tier Awareness UI (M1), and Anonymization Layer (Inference Gateway middleware, M2). Added §1.8 Security Posture as a new top-level section. Added Tabular/Multi-Document Review (M3), Slack/Teams Light Intake Bridge (M3), Contract Repository auto-relationship detection (M4). Expanded the competitor list in §1.2. Added M5–M7 Forward-Looking Roadmap (workflow-aware context layer; community-driven; not committed). Added MCP-client subsystem as an architectural slot in M1–M2 to leave room for M5+ workflow intelligence. Added approximately 40 new deferred enhancements across new "Capability extensions," "Security and compliance," and "Workflow intelligence" subsections. Added Appendix E (Pre-Empted Procurement Objections, 17 entries).

---

## Table of Contents

1. [Product Overview](#1-product-overview) (§1.1 Vision · §1.2 Positioning · §1.3 Transparency · §1.4 Target Users · §1.5 Deployment Modes and the Inference Choice Spectrum · §1.6 Out of Scope · §1.7 Success Criteria · §1.8 Security Posture · §1.9 Engineering Discipline Posture)
2. [Architecture](#2-architecture)
3. [Capability Specifications](#3-capability-specifications) (§3.1–3.10 plus new §3.11 Projects · §3.12 Organization Profile · §3.13 Inference Tier Awareness · §3.14 Tabular / Multi-Document Review · §3.15 Slack/Teams Light Intake Bridge · §3.16 Contract Repository — Auto-Relationship Detection)
4. [The LQ.AI Inference Gateway](#4-the-lq-ai-inference-gateway) (now includes Anonymization Layer middleware)
5. [Cross-Cutting Concerns](#5-cross-cutting-concerns) (§5.1–5.7 plus §5.8 Testing and Quality Engineering · §5.9 Reliability and Operations)
6. [Deployment](#6-deployment)
7. [Open Source Posture](#7-open-source-posture)
8. [Roadmap](#8-roadmap) (M1–M4 plus M5+ Forward-Looking)
9. [Deferred Enhancements and Identified Future Work](#9-deferred-enhancements-and-identified-future-work)
10. [Appendices](#10-appendices) (A Glossary · B License Matrix · C Known Risks · D Companion Documents · E Pre-Empted Procurement Objections)

---

## 1. Product Overview

### 1.1 Vision

LQ.AI is an open-source AI platform purpose-built for legal teams. It delivers the core capabilities of commercial legal AI products — fast, accurate contract drafting and review, verifiable citations, reusable workflow skills, playbook-driven contract analysis, and a Microsoft Word integration — as a fully self-hostable system that runs on a laptop, an internal server, or a cloud VM.

The project's reason for existing is simple: legal teams should not have to choose between AI assistance and data sovereignty. Every other capable tool in this category is a closed-source SaaS that requires sending privileged information to a third-party vendor. LQ.AI runs in the customer's environment, with the customer's keys, against the customer's choice of model — including fully air-gapped deployments using local inference.

The longer-term ambition extends beyond the core capability set. Over time, LQ.AI is intended to evolve from a tool the user reaches for into a workflow-aware context layer that integrates with the email, calendar, task systems, and document stores the user already lives in — surfacing the right matter at the right moment, with rationale, with one-click actions, with full transparency about what the system is doing on the user's behalf. That evolution is forward-looking and out of scope for v1; the M5+ Forward-Looking Roadmap (§8.5) names the trajectory so that v1 architectural choices leave room for it rather than painting the project into a corner.

### 1.2 Positioning

> **LQ.AI** — open-source AI for legal teams. Bring your own keys, run it where you want, own your data.

The product positions against three categories:

- **Commercial in-house legal AI:** the category is more crowded than a three-name list (GC.AI, Spellbook, Legora) suggests. Direct competitors include GC.AI, Ivo, Legalfly (Belgian, "legal operating system for corporates"), Spellbook, Legora, Harvey-for-in-house, Eudia, and ContractPodAi (rebranded Leah). Robin AI was a fourth-tier-product structure player but collapsed in late 2025; its features are documented for reference in the deferred-enhancement list. A separate adjacent category — in-house workflow / matter management — includes Streamline AI, Checkbox, LawVu, and Dazychain; the boundary with that category is addressed in §1.6. LQ.AI matches the analytical-AI core capability set, runs on the customer's infrastructure, costs nothing in license fees, and ships every shaping artifact as inspectable open source — a posture no closed-source competitor can match without abandoning their architectural assumptions.
- **Generalist AI (ChatGPT, Claude, Microsoft Copilot, etc.):** LQ.AI is purpose-built for legal workflows, ships with a curated skill library for legal tasks, and produces verifiable citations. It also addresses the privilege-and-confidentiality concerns that have made generalist tools a liability for legal practice (per *U.S. v. Heppner*).
- **Internal tools / DIY stacks:** LQ.AI is a turn-key alternative to building it yourself, with a coherent architecture, a maintained skill format, and a community.

For procurement and security teams evaluating LQ.AI: the security-posture story is consolidated in §1.8 Security Posture, with detailed responses to common procurement objections in Appendix E (Pre-Empted Procurement Objections). The forward-looking trajectory toward workflow-aware context (§8.5) describes the project's longer-term differentiation beyond feature parity.

### 1.3 Transparency as a Founding Principle

LQ.AI's commercial competitors treat their prompt engineering as proprietary moat. The skills, playbooks, citation logic, and verification heuristics that shape what the user sees are hidden inside closed-source applications, presented as "AI" but functionally indistinguishable from "a system prompt the vendor refuses to show you." This is smoke and mirrors. Much of the time, the emperor has no clothes — what looks like advanced legal AI is a moderately well-tuned prompt that the vendor charges hundreds of dollars per seat per month to keep secret.

LQ.AI inverts this. **Every artifact that shapes the user's experience is visible work product.** The skills are open source. The playbooks are open source. The citation engine's verification logic is open source. The Enhance Prompt rewriter is open source. The autonomous-agent instructions are open source. The Organization Profile (§3.12) — the org-wide voice, templates, and "what good looks like" reference that shapes every output — is open source. When a user clicks "view this skill" on any active skill, they see the actual SKILL.md and supporting files, formatted for human reading, with provenance and the ability to fork. There is no hidden layer between the user's prompt and the model's output that the user cannot inspect.

This commitment shapes three concrete product decisions:

1. **No proprietary "secret sauce" in the open-source release.** Optimizations that depend on undisclosed prompt engineering, undisclosed routing rules, or undisclosed verification heuristics are not part of LQ.AI. If we use a clever technique, the technique is in the repo, documented, and contributable.
2. **Skill inspectability is a first-class application feature** (§3.4), not a developer-debug affordance. Every active skill is one click away from being readable. Users learn the patterns, build trust through verification, and disagree-fork-replace when the skill is wrong.
3. **The skills *are* the product.** The value of LQ.AI comes from the curation and authoring of skills — which the community can read, contribute to, and improve — not from hiding them behind a paywall. Skills written for LQ.AI work in any agentskills.io-compatible runtime; users are not locked in.

The position implied by all of this is uncomfortable for the rest of the legal-AI category, and that is intentional. Customers who have been paying significant per-seat fees for software whose only real innovation is a hidden system prompt are entitled to see what they have actually been buying. When the curtain is pulled back, some of those products will hold up. Many will not. LQ.AI's bet is that an open, transparent product built on community-curated skills is better than a closed, opaque product built on the assumption that the user cannot see what is happening — and that the resulting trust is worth more than the marketing.

Practical implication for contributors and operators: treat skills as the canonical artifact. When something in the system produces a wrong answer, the answer to "why" is almost always in a SKILL.md somewhere. When the right answer is something we want the system to do consistently, the way to get there is to write or improve a skill. Skills are not configuration; they are the substance of the product.

### 1.4 Target Users

**Primary user:** in-house counsel at organizations of any size, from solo General Counsel to enterprise legal departments. The product assumes legal training and aims to extend the user's capacity, not replace judgment.

**Operator:** the person or team deploying LQ.AI within an organization. Could be the legal team itself (technical GC, legal-ops manager) or IT/SRE deploying on legal's behalf. The operator cares about deployment ergonomics, key management, audit trails, and integration with existing identity providers.

**Contributor:** the open-source community. Skill authors, playbook authors, plugin developers, and engineers extending the platform. The product must be friendly to contribution.

### 1.5 Deployment Modes and the Inference Choice Spectrum

LQ.AI's deployment posture has two dimensions. The first dimension is the **deployment mode** — where the application itself runs and how inference is reached. The second dimension is the **Inference Choice Spectrum** — what kind of trust relationship the operator has with whichever party is actually running the model. The two dimensions are orthogonal: a single deployment mode can map to multiple tiers depending on what the operator configures inside the gateway.

#### 1.5.1 Two deployment modes

Both modes use the same Docker Compose deployment. The Inference Gateway routes to whichever providers are configured.

**Mode 1: Self-hosted with cloud LLM keys.** The operator deploys LQ.AI on their infrastructure (laptop, server, or cloud VM) and configures it with API keys for one or more cloud LLM providers (Anthropic, OpenAI, Google, Cohere, Azure OpenAI, Bedrock). Inference happens at the cloud provider; the rest of the system stays in the operator's environment.

**Mode 2: Self-hosted with local inference (air-gap-capable).** The operator deploys LQ.AI alongside Ollama (or any OpenAI-compatible local inference endpoint) and runs all inference locally. This mode supports fully air-gapped deployments with no outbound network traffic.

#### 1.5.2 The Inference Choice Spectrum: five tiers

In practice, the security posture varies along a five-tier spectrum. The tiers are first-class concepts in the configuration and are surfaced to the user in real time via the Inference Tier Awareness UI (§3.13). Skills and Projects can require minimum tiers; deployments can disallow tiers globally. The tier spectrum is the central organizing concept of §1.8 Security Posture and Appendix E.

**Tier 1 — Local-only inference (air-gap-capable).** Inference runs on operator hardware via Ollama, vLLM, llama.cpp, or any OpenAI-compatible local endpoint. No outbound network is required. Customer data, prompts, and model outputs never leave the deployment. This is Mode 2. Suitable for the most sensitive work product (privileged communications, strategic-deal information, regulated-data deployments). The trade-off is performance: a model that fits on local hardware is, today, smaller and slower than the best cloud-hosted models.

**Tier 2 — Customer-hosted cloud inference.** Inference runs on infrastructure the operator owns: vLLM/llama.cpp on the operator's VPC, AWS Bedrock under the operator's AWS account, Azure OpenAI under the operator's Azure tenant, or Google Vertex AI under the operator's GCP project. Customer data leaves the LQ.AI deployment but stays inside the operator's cloud account boundary. No third-party processor is introduced. This tier offers near-Tier-3 performance with stronger custody than direct API access because the operator's cloud-provider DPA covers the data flow.

**Tier 3 — Enterprise managed inference with ZDR / no-training commitments.** Inference runs against a cloud provider's enterprise tier with explicit zero-data-retention or no-training contractual terms (Anthropic with a ZDR addendum, OpenAI Enterprise, Google Vertex AI, AWS Bedrock under Commercial Terms, Cohere Enterprise). The provider processes customer data per the enterprise DPA, does not use it for model training, and either does not retain it after the response is returned (ZDR) or retains it for a narrow safety/abuse window (commonly 7–30 days). This tier is what most pragmatic enterprise deployments use; this is where LQ.AI's posture matches what closed-source commercial in-house legal AI products provide today.

**Tier 4 — Standard cloud API under default commercial terms.** Inference runs against a cloud provider's standard commercial API without the enterprise ZDR addendum. The provider does not train on customer data (under standard commercial terms across major providers as of May 2026), but data is retained for the provider's default window (commonly 30 days, going to 7 days for some providers in late 2025/2026 changes). Suitable for many in-house deployments; less defensible for the most sensitive work product.

**Tier 5 — Consumer or free tier.** Inference runs against a consumer-tier endpoint (e.g., a personal Anthropic Pro account, a personal OpenAI account) where the provider's consumer terms may permit training-on-data unless explicitly opted out. As of August–September 2025, several major providers shifted consumer terms toward training-by-default-with-opt-out. This tier is unsuitable for client-confidential legal work; the application warns prominently when configured to use it.

When customer data privacy is a requirement but Tier 1 / Tier 2 is impractical, the Anonymization Layer (§4) offers a privacy fallback for Tier 3+: sensitive entities are pseudonymized prior to processing and rehydrated after. The Provider Compliance Matrix (`docs/compliance/provider-compliance-matrix.md`) details each supported provider's terms, certifications, and data-residency options for tier classification.

**Floor semantics — how `minimum_inference_tier` works.** Tier values are security levels, not integer ranks. When a request, project, or skill declares `minimum_inference_tier: N`, the Inference Gateway requires at least Tier N security — allowing Tier N and any lower-numbered (stronger) tier, refusing any higher-numbered (weaker) tier. Concretely: `minimum_inference_tier: 2` allows Tier 1 (local Ollama, air-gapped) and Tier 2 (operator-hosted cloud), and refuses Tier 3–5 (managed enterprise cloud, standard commercial cloud, consumer). The combiner across multiple declarations (request + project + skill) is `min(all declared values)` — the declaration requiring the strongest (lowest-numbered) tier governs. The gateway refuses when `resolved_tier > floor.value`, i.e., the routed model's tier is weaker (higher-numbered) than the floor. This means a privileged project with `minimum_inference_tier: 2` can route to Tier 1 (local) as well as Tier 2 (VPC) — air-gap is always allowed when any secure floor is set, consistent with "air-gap is the most restrictive operational posture and satisfies any minimum tier requirement" (see PRD §1.8).

### 1.6 Out of Scope (v1)

Explicitly not in scope for v1, to keep the initial release focused:

- **Hosted SaaS offering.** No legalquants.com-hosted instance. Self-hosted only.
- **Tucuxi cognitive-architecture integration** (Director RNN, Cognitive Compilation Engine, RSH framework, Wisdom Database/GUD). These remain proprietary to Tucuxi and are not part of the open-source LQ.AI release.
- **Mobile applications.** Web UI is responsive, but no native iOS/Android apps.
- **E-discovery or litigation-specific workflows.** Focus is in-house counsel work: contracts, policies, regulatory matters, advice. Litigation tools are a separate product category.
- **Direct integrations with CLM systems** (Ironclad, Concord, etc.). Out of scope for v1; potential v2 work.
- **Billing / time tracking.** Not a feature of in-house legal work.
- **Full intake / triage / matter-management workflow** (request portal, SLAs, approvals, escalations, dashboards). LQ.AI is the analytical AI layer; Streamline AI and Checkbox occupy the operational-workflow layer. They are complementary; v1 stays on the analytical side. Light intake bridges (§3.x Slack/Teams Bridge in M3) are in scope; full operational workflow is not.

### 1.7 Success Criteria for v1 (M1 Release)

- Operator can go from `git clone` to a working chat with files and skills in under 15 minutes on a laptop with Docker installed.
- Documented Mode 1 (cloud keys) and Mode 2 (Ollama) deployments both work on first attempt for a competent technical user.
- 10 starter skills ship with the release and produce useful output on real contracts.
- The Inference Gateway successfully routes to all v1 supported providers (Anthropic, OpenAI, Google, Cohere, Ollama, Azure OpenAI, Bedrock).
- Project clears 1,000 GitHub stars within 90 days of public release (community-traction proxy).
- At least 5 external contributors land merged PRs within 90 days (contribution-friendliness proxy).
- At least 3 deployed instances (across any organizations) report having created at least one Project (§3.11) and one Organization Profile (§3.12) within 60 days, indicating the matter-context model is being used as designed (adoption-quality proxy).

### 1.8 Security Posture

LQ.AI's security posture is structurally different from the closed-source commercial alternatives in the category. Three principles shape it.

**The operator chooses the deployment's posture.** LQ.AI does not run a SaaS that holds your data on our infrastructure; you run it on yours. The most consequential security decisions — where the deployment lives, what inference provider it routes to, how the audit log is retained, who has access — are yours, and the application makes the implications of each decision explicit. A closed-source vendor's compliance posture is only as strong as the audit reports they will hand over and the contractual commitments they will sign. LQ.AI's compliance posture is verifiable in source.

**The Inference Choice Spectrum is the central security trade-off.** Inference is where customer data leaves the deployment, if it does. The five-tier spectrum (§1.5.2) maps the choice across local-only inference (Tier 1), customer-hosted cloud inference (Tier 2), enterprise managed inference with ZDR / no-training commitments (Tier 3), standard cloud API (Tier 4), and consumer or free tier (Tier 5). Tier 3 is recommended for most pragmatic enterprise deployments and matches what closed-source commercial in-house legal AI products provide. Tier 1 is recommended for the most sensitive privileged work. The application surfaces the routed tier in the chat UI in real time (§3.13); Skills and Projects can require minimum tiers; deployments can disallow tiers globally; the audit log captures every routing decision.

**Transparency replaces opacity.** Every artifact that shapes the user's experience is open source and inspectable: skills, playbooks, the Citation Engine's verification logic, the Enhance Prompt rewriter, autonomous-agent instructions, the Organization Profile (§3.12), the prioritization logic in any future workflow-context features. Every release ships with an SBOM (Software Bill of Materials), signed container images (Sigstore/cosign), SLSA-3 build provenance attestations, and a published threat model (`docs/security/threat-model.md`). Every framework an operator's auditor will ask about — SOC 2, ISO 27001, ISO 42001, GDPR, HIPAA, FedRAMP — has a corresponding alignment document (`docs/compliance/`) mapping our design choices to the framework's controls and identifying which controls are project-provided, operator-provided, or joint. Where LQ.AI does not yet match a specific commercial competitor's control, it is named on the public deferred-enhancements list (§9) with a roadmap rather than glossed over in marketing.

Procurement-defense materials, including a structured Pre-Empted Procurement Objections appendix (Appendix E) and the Compliance Alignment Pack (referenced above), are maintained in the repository and updated each release.

**Additional security-posture commitments (Wave 9.C additions).** The three principles above are extended by three explicit commitments. They are recorded here so that each is independently verifiable against source rather than asserted in marketing copy.

**Source verifiability as a complement to compliance attestation.** Compliance attestation — SOC 2 Type II, ISO 27001, ISO 42001, HIPAA, FedRAMP, and the EU AI Act conformity assessment — is one layer of assurance: a paid third party reviews the operator's controls against a framework during an observation window. The Compliance Alignment Pack (`docs/compliance/README.md`, with per-framework documents arriving across M1 and M2) is the project's contribution to that layer. Source inspectability is a second, structurally independent layer: every claim in every alignment document is verifiable against the source code in this repository, by the operator's security team or any third party the operator hires, on a timeline the operator sets, with no paid intermediary in the verification path. Compliance attestation in the absence of source verifiability is a single point of failure; the two layers reinforce each other. The Compliance Alignment Pack tells the operator's procurement team what to look for; the open-source release lets the operator's security team confirm what those documents claim. This dual posture is what `docs/HONEST-STATE.md` operationalizes for the M1 release.

**OpenSSF Scorecard and OpenSSF Best Practices Badge.** The OpenSSF Scorecard tool computes objectively-measurable security-and-practice signals (branch protection, signed releases, dependency-update automation, fuzzing, etc.) and produces a score that any reviewer can independently verify in seconds. The OpenSSF Best Practices Badge encodes a layered checklist at Passing, Silver, and Gold tiers. Both badges presuppose source visibility — they are structurally unavailable to closed-source competitors. The project's commitment is the Passing tier at M1 release, the Silver tier at M2, and the Gold tier at M4, with the Scorecard score published in the README and refreshed continuously by automation. The contributor-friendly path to shipping the badges is documented at `docs/contribute/mini-prds/openssf-scorecard-and-badges.md`. **M1 status:** not yet shipped; see `docs/HONEST-STATE.md` §6.

**Annual third-party review program (M1 commitment; first engagement targeted within 90 days of M1 release).** The project commits to two recurring third-party engagements: (a) an annual application penetration test by a recognized firm covering the FastAPI backend, the Inference Gateway, the OpenWebUI fork, the Word add-in (once shipped), and the reference deployment recipes; (b) an annual adversarial-AI red-team engagement against the inference path, the Citation Engine, the Anonymization Layer, and skill execution. Executive summaries are published in the repository (in `docs/security/releases/`) with finding count by severity, remediation status, and remediation timeline. Detailed findings are coordinated-disclosure-cycled per `SECURITY.md` before publication. Both engagements are funded by LegalQuants as a project investment; they are not contingent on community contribution. The first engagement of each kind is targeted within 90 days of the M1 release. This commitment is the structurally verifiable answer to the procurement objection "what independent review has this had?" — see Appendix E.

**The boundary-register catalog as the framework for restraint.** A useful framing of professional-services agent design, articulated by Dazza Greenwood in May 2026 ("The Most Interesting Thing in Claude for Legal Is the Lawyer/Agent Boundary"), classifies the restraints a serious agentic legal system needs into a small catalog of registers — three describing **how** a boundary is enforced (prompt-and-workflow, capability/tool-grant, code) and three describing **what else** needs restraining once autonomy exists (economic, temporal, contextual). LQ.AI adopts this catalog as the organizing framework for its boundary-enforcement work and tracks each register's state in [`docs/security/boundary-registers.md`](security/boundary-registers.md) (per DE-290), refreshed at every milestone close with line-level source citations. The catalog is expected to grow as community practice matures; the goal is not to ship "six of six" as a marketing claim but to make every register's state — implemented, partial, deferred-with-commitment, or rejected-with-reasoning — verifiable in source. Today the project ships R1 fully (the prompt-and-workflow surface, codification tracked by DE-291), R2 in an adapted form (the Inference Tier model is a capability boundary on the inference path rather than on per-agent tool grants; the agent-tool-grant facet retrofits the Playbook executor under DE-292), R3 partially (the gateway as a code-enforced security boundary in a separate process, the Citation Engine's deterministic substring verification, the Anonymization Layer's code-level entity rewriting, and the Playbook executor's Pydantic-typed step transitions; the closed-intent-enum + audit-log validation pattern retrofits under DE-292 for in-Playbook seams and DE-294 for any future multi-agent autonomous flows), and R4 partially (per-call cost tracking + the M2 ensemble per-message pre-flight budget; per-execution and per-session caps are tracked by DE-292 and DE-293 respectively). R5 (temporal) and R6 (contextual) attach to the autonomous-layer surface that lands in M4 (§3.10) — they are deferred-with-commitment, with DE-293 carrying the implementation specification. The Inference Choice Spectrum (§1.5.2) is a seventh boundary orthogonal to Greenwood's six: it restrains *where the data goes during inference* rather than *what the model may decide, spend, run, or touch*, and is the central security trade-off in any LQ.AI deployment.

Detailed cross-cutting security and compliance concerns are covered in §5; deployment-mode and inference-tier configuration in §1.5 and the Inference Gateway specification in §4; the deferred security and compliance enhancement roadmap in §9 (Security and Compliance subsection); the engineering-discipline posture in §1.9 with its testing-and-quality and reliability-and-operations workstreams in §5.8 and §5.9.

### 1.9 Engineering Discipline Posture

LQ.AI's engineering posture is the corollary of its security posture: the same source visibility that makes the security claims verifiable makes the engineering claims verifiable. Three principles shape this posture; each is operationalized in §5.8 (testing and quality engineering) and §5.9 (reliability and operations), with the deferred-enhancement roadmap in §9.

**Engineering rigor is verifiable, not asserted.** The CI configuration that enforces coverage gates is in `.github/workflows/`; the test directories are in `api/tests/`, `gateway/tests/`, and `web/src/lib/lq-ai/__tests__/`; the release pipeline that produces signed container images is in `release.yml`. Where a closed-source vendor's marketing copy says "we test rigorously," LQ.AI shows the test report — the actual one, generated by CI on the actual code path. The OpenSSF Scorecard is computed continuously against the repository (§1.8 addition; mini-PRD at `docs/contribute/mini-prds/openssf-scorecard-and-badges.md`) and renders as a badge in the README a reviewer can click and verify. The mutation-testing score (§5.8) is published per release. Reviewers do not have to trust the project's representation of its engineering practices; they verify them in source. **M1 status:** the test surfaces are in place (`docs/HONEST-STATE.md` §6 catalogs counts and CI flags); the published-scoring practices (Scorecard badge, mutation score, per-release eval scores) are deferred enhancements (§9, Engineering Discipline subsection).

**AI-specific quality is a measured discipline, not a hope.** Legal AI fails in ways traditional software does not: hallucinated citations, prompt injections that exfiltrate context from a malicious counterparty document, drift in skill output quality when a foundation model is upgraded, PII leakage through embeddings, jailbreak responses that violate the operator's risk posture. PRD §3.3 addresses the citation-hallucination failure mode structurally (a verification step that re-reads the cited substring against the source). This section commits to measuring the other failure modes — published per-skill eval scores against held-out test sets, published prompt-injection detection rates against industry attack corpora (Garak, PyRIT, MITRE ATLAS), published PII leakage rates per inference tier and per anonymization configuration, regression suites that block release when a model upgrade causes a skill's structural-output score to drop below threshold. The numbers are public per release; the methodology is documented; the test corpora are in the repository. **M1 status:** these measurement surfaces are not yet running — see `docs/HONEST-STATE.md` §6 for the gap catalog and §9 (Engineering Discipline subsection) for the roadmap. Operators evaluating M1 should read what is measured today (the unit and integration test suites; the Cypress E2E suites) and what is not (per-skill quality, prompt-injection detection rates, PII leakage rates).

**Independent review is invited, not avoided.** Per §1.8's third commitment, the project budgets an annual application penetration test and an annual adversarial-AI red-team engagement, both with public executive summaries. Past disclosures and their fixes are published with credit to reporters (per §7.6). The OpenSSF Best Practices Badge requires public attestation of practices that any reviewer can independently challenge. OWASP ASVS Level 2 third-party verification is committed within 12 months of M1 (see §9). This is the structural inverse of the closed-source SaaS posture, where independent review is contractually restricted, the pen-test report is gated behind an NDA, the safe-harbor language for good-faith research is absent or narrow, and the operator must take the vendor's word for what was tested. The verification budget is the operator's to set; the verification scope is the operator's to define; the verification cadence is the operator's choice.

Detailed testing and quality engineering commitments are in §5.8; reliability and operations commitments in §5.9; the deferred engineering-quality enhancement roadmap in §9 (Engineering Discipline subsection); pre-empted engineering-quality procurement objections in Appendix E.

---

## 2. Architecture

### 2.1 Reference Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         CLIENT SURFACES                              │
│   Web App (OpenWebUI fork)    │    Word Add-In (Office.js)           │
│   - Chat, skills, files        │    - Redlining                      │
│   - Skill Library UI            │    - Playbook execution             │
│   - Playbook Manager            │    - Inline comments                │
└──────────────────┬─────────────┴────────────────┬────────────────────┘
                   │                              │
                   │  OpenAPI 3.1 over HTTPS      │
                   ▼                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                  LQ.AI Backend (FastAPI)                        │
│                                                                      │
│   Authn/Authz  │  Audit Log  │  RBAC  │  OpenAPI Surface              │
└──────┬───────────────┬─────────────┬────────────┬───────────────┬────┘
       │               │             │            │               │
       ▼               ▼             ▼            ▼               ▼
┌─────────────┐ ┌─────────────┐ ┌───────────┐ ┌────────────┐ ┌─────────┐
│ Inference   │ │   Skill     │ │  Playbook │ │  Document  │ │Knowledge│
│  Gateway    │ │  Service    │ │  Service  │ │  Pipeline  │ │ Service │
│             │ │             │ │           │ │ Docling +  │ │ Hybrid  │
│ Multi-      │ │agentskills  │ │ Schema +  │ │ PyMuPDF +  │ │ search: │
│ provider    │ │ format      │ │ Easy      │ │ Mistral    │ │ vector  │
│ router with │ │             │ │ Playbook  │ │ OCR        │ │ + FTS   │
│ fallback,   │ │ Skill       │ │ generator │ │            │ │         │
│ rate limit, │ │ Library +   │ │           │ │ Citation   │ │ pgvector│
│ cost track  │ │ Creator     │ │ LangGraph │ │ Engine     │ │         │
│             │ │             │ │ executor  │ │            │ │         │
└──────┬──────┘ └──────┬──────┘ └─────┬─────┘ └──────┬─────┘ └────┬────┘
       │               │              │              │            │
       └───────────────┴──────────────┴──────────────┴────────────┘
                                      │
                ┌─────────────────────┼─────────────────────┐
                ▼                     ▼                     ▼
        ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
        │ PostgreSQL   │      │    Redis     │      │   MinIO /    │
        │ + pgvector   │      │  (sessions,  │      │   S3-compat  │
        │              │      │   queues,    │      │   (files)    │
        │ App data,    │      │   pubsub)    │      │              │
        │ vectors,     │      │              │      │              │
        │ FTS, audit   │      │              │      │              │
        └──────────────┘      └──────────────┘      └──────────────┘

LLM PROVIDERS (any combination, configured by operator):
  Cloud:  Anthropic │ OpenAI │ Google Vertex │ Cohere │ Azure OpenAI │ AWS Bedrock
  Local:  Ollama │ vLLM │ llama.cpp │ any OpenAI-compatible endpoint

OBSERVABILITY (optional):
  OpenTelemetry → Grafana / Tempo / Loki     │     Langfuse (LLM-specific tracing)
```

### 2.2 Technology Decisions and Rationale

**Application shell: OpenWebUI.** Chosen over LibreChat because: 9 vector DB backends, native SCIM 2.0, built-in OpenTelemetry, mature RBAC, Pipelines plugin framework (which we use for the autonomous agent layer in M4), Redis-backed multi-worker scaling, Google Drive/OneDrive integration. Branding clause is acceptable since LQ.AI is open-source itself; we follow OpenWebUI's branding requirements and document the relationship clearly. We fork at the latest stable version and pull updates regularly rather than diverging.

**Backend: FastAPI.** OpenAPI 3.1 by construction, async-native, Pydantic models for request/response validation, excellent ecosystem. Aligns with operator expectations for a Python-backend AI product.

**Agent runtime: LangGraph.** Stateful, graph-based agent workflows are the right shape for legal work — contract review is multi-step (parse → classify → playbook-match → redline → cite-verify). State persists across long-running operations. MIT-licensed, production-tested.

**Skill format: agentskills.io / Anthropic Claude Skills.** Open standard, interoperable with Claude Code and Hermes Agent ecosystems. A skill is a folder containing a `SKILL.md` (with YAML frontmatter for metadata) plus optional supporting files. Skills are version-controllable, shareable, and human-readable.

**Inference Gateway: built in-house.** LiteLLM has had a meaningful security history (proxy auth bypasses, SSRF vulnerabilities, sprawling codebase). For an open-source project where users may run our gateway with privileged API keys, that surface area is unacceptable. We build a focused, auditable gateway in ~3,000 lines of Python. Full spec in §4.

**Document pipeline: Docling + PyMuPDF + Mistral OCR.** Docling for structure-aware parsing, PyMuPDF for character-precise byte offsets (server-side use only — AGPL is not contagious through HTTP API boundaries), Mistral OCR API as a paid fallback for scanned documents. Operators who want fully air-gapped deployments use PaddleOCR-VL instead of Mistral OCR.

**Vector store: pgvector.** Same Postgres instance we already have for app data — one less moving part, no separate vector DB to operate. Hybrid search via PostgreSQL's full-text search alongside vector similarity. Operators with scale needs can swap in Qdrant via configuration.

**Auth/RBAC: OpenWebUI built-in for v1.** OpenWebUI's auth supports LDAP/AD, SCIM 2.0, OAuth, trusted-header SSO, and granular RBAC. Sufficient for v1. Operators with complex IdP needs can front the deployment with Authentik or Keycloak via reverse proxy.

**Observability: OpenTelemetry + Langfuse.** OTel for app traces/metrics/logs to standard sinks, Langfuse for LLM-specific tracing, prompt versioning, and evaluation. Both optional, both self-hostable, both Apache 2.0 / MIT.

### 2.3 Data Isolation Model

Single-tenant by deployment. There is no cross-tenant isolation problem because each deployment serves one organization. Within a deployment, RBAC scopes data to users and groups:

- **Personal scope:** chats, files, skills, and playbooks owned by the user.
- **Group scope:** shared with explicitly-named groups; group membership controlled by admin.
- **Organization scope:** available to all users in the deployment.

All scopes share the same database; access control is enforced at the API layer with explicit scope checks on every read/write. Operators who need stronger isolation between business units run multiple LQ.AI deployments.

### 2.4 Deployment Topology

**Mode 1 — Self-hosted with cloud LLM keys (default):**

```
Operator's Environment
├── docker compose up
│   ├── lq-ai-web (OpenWebUI fork, port 3000)
│   ├── lq-ai-api (FastAPI, port 8000)
│   ├── lq-ai-gateway (Inference Gateway, port 8001)
│   ├── postgres (with pgvector)
│   ├── redis
│   └── minio (or S3-compatible)
└── Outbound HTTPS to cloud LLM providers
    ├── Anthropic API (operator's key)
    ├── OpenAI API (operator's key)
    └── ...
```

**Mode 2 — Fully local inference (air-gap-capable):**

```
Operator's Environment
├── docker compose up (with --profile local)
│   ├── lq-ai-web
│   ├── lq-ai-api
│   ├── lq-ai-gateway
│   ├── ollama (with locally-pulled models)
│   ├── postgres (with pgvector)
│   ├── redis
│   ├── minio
│   └── paddleocr-vl (replaces Mistral OCR API)
└── No outbound network required
```

Both modes use the same images. The difference is which `--profile` flag is passed to Compose and which environment variables are set in `.env`.

---

## 3. Capability Specifications

This section specifies each major capability. Every capability section follows the same structure:
- **Description** — what the capability does.
- **User stories** — how users invoke it.
- **Functional requirements** — what the system must do.
- **Non-functional requirements** — performance, accuracy, reliability targets.
- **API surface** — relevant FastAPI endpoints.
- **Data model** — primary entities.
- **Dependencies** — what other capabilities this relies on.
- **Open questions** — decisions deferred.

### 3.1 Conversational Core

**M1 status:** Shipped. Multi-turn chat with persistent history, full-text search over chat history, streaming SSE responses, and matter (project) workspace at `/lq-ai/matters/[id]` are all wired end-to-end. An operator can verify the backend at `api/app/api/chats.py` and `api/app/api/projects.py`; the Cypress E2E suite covers the surface in `web/cypress/e2e/wave-a-chrome.cy.ts` and `web/cypress/e2e/wave-c-matters.cy.ts`. Note: share-with-group and playbook attachment are deferred; the section below describes the full v1 design. See [HONEST-STATE.md §1](HONEST-STATE.md#1-conversational-and-workspace-surface) for the per-capability verification table.

**Description.** Multi-turn chat with persistent history, organized in a sidebar grouped by recency. Users can rename, delete, search, and share chats. Each chat is associated with the user who created it and optionally shared with groups or the whole organization. Chats can have files, skills, and playbooks attached.

**User stories.**
- As a user, I start a new chat by clicking "New Chat" in the sidebar.
- As a user, I attach skills to a chat with `+ → Skills`.
- As a user, I attach files to a chat by drag-and-drop or `+ → Files`.
- As a user, I search across all my chat history by keyword.
- As a user, I share a chat with a teammate or my whole organization.
- As a user, I create a chat inside a Project (§3.11) and the chat inherits the Project's attached files, skills, playbooks, and free-form context document.
- As an admin, I see audit logs of all chat activity in my organization.

**Functional requirements.**
- Chats persist across sessions and are restored on login.
- Each chat carries a list of attached resources (skills, files, playbooks).
- Each chat has an optional `project_id` (FK to Project per §3.11); chats in a Project inherit the Project's resources and context.
- Users can rename, delete, archive, pin, and share chats.
- Full-text search across chat content (own chats + chats shared with user).
- Streaming model responses (SSE).
- Markdown rendering, including LaTeX and code blocks.
- Copy-as-Markdown, Copy-as-Plain-Text, Export-to-DOCX.

**Non-functional requirements.**
- First token latency < 2s for cloud providers, < 5s for local Ollama on reasonable hardware.
- Chat list loads in < 500ms for users with up to 1,000 chats.
- Search across 10,000 chats returns results in < 1s.

**API surface.**
- `POST /api/v1/chats` — create chat.
- `GET /api/v1/chats` — list user's chats.
- `GET /api/v1/chats/{id}` — get chat with messages.
- `POST /api/v1/chats/{id}/messages` — post message, stream response.
- `PATCH /api/v1/chats/{id}` — update chat (rename, archive, pin, share).
- `DELETE /api/v1/chats/{id}` — delete chat.
- `GET /api/v1/chats/search?q=...` — search chats.

**Data model.**
- `Chat`: id, owner_id, title, created_at, updated_at, archived, pinned, shared_with_groups, shared_with_org, project_id (nullable — links to an enclosing Project per §3.11).
- `Message`: id, chat_id, role (user|assistant|system|tool), content, created_at, token_counts, model_used, routed_inference_tier (per §3.13).
- `ChatAttachment`: chat_id, resource_type (skill|file|playbook), resource_id.

**Dependencies.** Inference Gateway (§4), Skill Service (§3.4), Knowledge Service (§3.5), Playbook Service (§3.7), Project Service (§3.11, optional — chats can be created inside or outside a Project).

**Open questions.** Should chat-level fork/branch be a v1 feature? OpenWebUI supports it; recommend keeping it.

### 3.2 Enhance Prompt

**M1 status:** Shipped. The ⌘E button and the expand-before-submit flow are wired end-to-end. An operator can verify at `api/app/api/enhance_prompt.py`; the Cypress E2E suite covers the surface in `web/cypress/e2e/wave-d1-power-features.cy.ts` Test 1. The reasoning-visibility preference (`reasoning_visibility`) is wired and stored per §3.2.1. See [HONEST-STATE.md §1](HONEST-STATE.md#1-conversational-and-workspace-surface).

**Description.** A prompt-rewriting skill that runs as an optional pre-step. The user types a short, natural-language question; Enhance Prompt expands it into a structured legal prompt (role, jurisdiction, audience, scope, output format, constraints, citation expectations) and shows the user the expanded version before submission. The user can edit the expansion, submit as-is, or skip and submit the original. The skill is *itself* inspectable — the user can view the SKILL.md and supporting files driving the enhancement at any time.

**User stories.**
- As a user, I type "review this NDA for unusual provisions" and click Enhance Prompt; the system rewrites my prompt into a detailed legal review prompt and shows it to me before submitting.
- As a user, I edit the Enhance Prompt output before submitting.
- As a user, I skip Enhance Prompt and submit my original prompt as-is.
- As a user, I click "view this skill" on the review screen and read the actual instructions driving the enhancement, so I can decide whether I trust them.
- As a user, I configure my account-level preference for whether reasoning is shown by default, hidden behind a disclosure, or always visible.

**Functional requirements.**
- Enhance Prompt runs as a separate, fast model call (typically a smaller/cheaper model).
- The expansion uses the user's recently-attached skills as context, not just the raw input.
- The expansion includes a *reasoning section* explaining why each addition was made (so users learn the prompt-engineering moves).
- The skill correctly identifies prompts that should *not* be expanded (follow-up questions, conversational turns, already-structured prompts, operational asks) and returns a skip decision.
- When an attached skill has a missing required input, Enhance Prompt surfaces the missing input as a structured form-like prompt rather than expanding the prompt's text — see §3.4 on the skill-input-form pattern.
- Enhance Prompt is a toggle; off by default for power users. Per-prompt invocation also available via button.
- **Reasoning visibility:** account-level setting with three modes — `always_show` (reasoning visible by default), `disclosure` (reasoning collapsed behind a "why these changes?" disclosure, default), `on_request` (reasoning hidden until user opens the skill inspector).
- **Skill inspectability:** the review-before-sending screen includes a "view this skill" affordance that opens the actual SKILL.md and supporting files in a side panel. This is the general skill-inspectability pattern (§3.4) applied to Enhance Prompt specifically.

**Non-functional requirements.**
- Enhance Prompt expansion completes in < 3s.
- Skill inspector opens in < 500ms.

**API surface.**
- `POST /api/v1/enhance-prompt` — accepts raw user input plus chat context, returns expanded prompt + reasoning + skip decision (structured per the SKILL.md output schema).
- `GET /api/v1/skills/{id}/contents` — returns the skill's full contents (SKILL.md + supporting files) for inspection. Used by the skill inspector; see §3.4.

**Data model.**
- `EnhancePromptInteraction`: id, user_id, raw_input, expansion_applied (bool), expanded_output, reasoning, skip_reason, used (bool), edited_before_use (bool), created_at. Used for telemetry and improvement.

**Dependencies.** Inference Gateway, Skill Service.

**Open questions.** None blocking.

### 3.2.1 User personalization preferences (M1)

**M1 status:** Shipped. All five preference columns (`reasoning_visibility`, `featured_tools`, `workspace_layout`, `trust_pills`, `provenance_pills`) are in the `users` table with CHECK constraints and server defaults. The `GET /api/v1/users/me/preferences` and `PATCH /api/v1/users/me/preferences` endpoints are live. An operator can verify at `api/app/api/users.py` and migrations `0015` and `0019`. See [HONEST-STATE.md §1](HONEST-STATE.md#1-conversational-and-workspace-surface).

**Description.** LQ.AI's default experience is calibrated to teach: reasoning is disclosed, tools are prominent, all provenance context is visible. Personalization preferences are the mechanism by which veteran users dial back that explicitness without the platform assuming everyone is an expert. The five preferences shipped in M1 (one from §3.2 Wave A, four new in Wave B v2) are stored as columns on `users`, queryable at the relational level, and exposed through a single partial-update endpoint. They are per-user, not per-org — the operator cannot suppress them. Spec reference: frontend design §4.3 (Wave B v2).

**Preference fields.**

| Field | Type | Values | Default | Surface |
|---|---|---|---|---|
| `reasoning_visibility` | text | `always_show`, `disclosure`, `on_request` | `disclosure` | Enhance Prompt reasoning section (§3.2) |
| `featured_tools` | text | `prominent`, `inline` | `prominent` | Dashboard — Enhance Prompt, Skill Creator, KB, Apply Skill shown as prominent cards vs. inline toolbar only |
| `workspace_layout` | text | `three_pane`, `two_pane`, `one_pane` | `three_pane` | Matter workspace composition (Wave C surfaces) |
| `trust_pills` | text | `labels`, `dots` | `labels` | Ambient trust pill format — full label `● self-hosted` vs. minimal dot only |
| `provenance_pills` | text | `always`, `collapsed` | `always` | Per-message skill / tier / provider pill row visibility |

**Non-functional requirements.**
- All five columns are `NOT NULL` with a `server_default` equal to the "brave choice" default. New users get the full-disclosure experience without any explicit write.
- Each column carries a DB-level `CHECK` constraint (named `chk_users_<field>_enum`) that mirrors the Pydantic `Literal` type enforcement in the API layer. This is defense-in-depth: invalid values are rejected at the storage layer even if they bypass the API validator.
- Preferences are readable immediately after login via `GET /users/me` (full user profile) or `GET /users/me/preferences` (preferences slice only).
- A `PATCH` that supplies the same value as the existing value is idempotent: it returns 200 but does not write an audit row.

**API surface.**
- `GET /api/v1/users/me/preferences` — returns all five preference fields for the calling user.
- `PATCH /api/v1/users/me/preferences` — partial update; only supplied fields move. Writes a `user.preferences_updated` audit row (action on `audit_log`) when at least one field changes, with `details.changes` listing before/after for every changed field. A single PATCH call that changes multiple fields produces exactly one audit row.

**Data model.** All five fields are columns on the `users` table — not a separate `user_preferences` table. This keeps the preferences queryable alongside auth fields (e.g., `WHERE role = 'member' AND workspace_layout = 'three_pane'`) without a join, and makes migration straightforward (add column + CHECK constraint per migration 0015 and 0019).

**Future extensions.** Later milestones may add preferences for default jurisdiction, default model, notification frequency, and citation display density. These will ride the same `PATCH /users/me/preferences` endpoint without a new route — the endpoint is intentionally forward-compatible.

### 3.3 Citation Engine (Exact Quote)

**M2 status: SHIPPED.** The full 4-stage verification cascade is wired end-to-end as of M2-A through M2-D:

* **Stage 1 — `exact_match`** (M2-A2): byte-for-byte equality against `documents.normalized_content[offset_start:offset_end]`. Free; pure Python.
* **Stage 2 — `tolerant_match`** (M2-B1): rapidfuzz ratio ≥ 95 after normalization (whitespace, smart quotes, OCR confusions on `was_ocrd=true` docs). Free.
* **Stage 3 — `paraphrase_judge`** (M2-C1): LLM judge call through the gateway returning `yes` / `partial` / `no` with `high` / `medium` / `low` confidence mapped to 0.90 / 0.70 / 0.50. One judge call per citation; per-judge cost calibrated against the routing log per M2-E2.
* **Stage 4 — `ensemble_strict` / `ensemble_majority`** (M2-D1): parallel judge dispatch across N configured models with strict (unanimous) or majority aggregation. Activated via `any()` across skill frontmatter, project flag, and gateway default; cost-budget pre-flight falls back to single-judge Stage 3 when the per-model estimate would exceed the cap. Tier envelope (max tier across the ensemble) persists per row.

The verification entry point is [`api/app/citation/verification.py::verify`](../api/app/citation/verification.py); the M2-C2 UI rendering states are documented in [`docs/citation-engine.md`](citation-engine.md). Failed citations render as "unverified" rather than silently disappearing. The Anonymization Layer integration (M2-D2) skips pseudonymization on the retrieval-context system message so source quotes reach the model intact for citation grounding; see [§4.7](#47-anonymization-layer-m2) and [`docs/security/anonymization.md`](security/anonymization.md). Privileged-project audit-trail invariants are pinned in [`api/tests/test_chat_citations.py::test_chat_send_privileged_project_full_audit_trail`](../api/tests/test_chat_citations.py).

The body of this section describes the design contract; deviations from the as-shipped pipeline (none currently known) would surface as PRD §9 entries.

**Scope clarification (2026-05-17).** The Citation Engine validates **KB-quote accuracy** — the model's response is an accurate representation of cited knowledge-base documents. Two related citation-checking surfaces are explicitly out of scope and tracked separately: **case citation validation** (Bluebook resolution via CourtListener) at [DE-279](#de-279--case-citation-validation-bluebook-resolution-via-courtlistener), and **case-content accuracy** (statement vs judicial opinion) at [DE-280](#de-280--case-content-accuracy-statement-vs-judicial-opinion). The three are architecturally distinct; see [`docs/citation-engine.md` §Scope](citation-engine.md#scope) for the taxonomy.

**Description.** End-to-end pipeline that guarantees character-fidelity from document → model context → cited output → rendered viewer. When the model produces a claim with a citation, the system can highlight the exact substring in the source document, in the original page, with character precision. Includes a verification step that fails the citation if the cited substring does not appear verbatim in the source.

This is the single most differentiated capability in the product. Specified in detail.

**User stories.**
- As a user, I upload a contract and ask a question; the answer includes inline citations like `[Doc1, p.3]` that I can click.
- As a user, clicking a citation slides in a side-panel viewer showing the original document page with the cited passage highlighted.
- As a user, I am confident the cited passage is verbatim — the system has verified it.
- As a user, I see a clear failure mode (citation marked as "unverified") if the system could not verify a citation, rather than silent error.

**Functional requirements.**

*Ingestion.*
- Documents are parsed by Docling for structural understanding and PyMuPDF for character offsets.
- Output is a *citable chunk schema*:
  ```python
  class CitableChunk(BaseModel):
      chunk_id: UUID
      doc_id: UUID
      page_number: int
      char_start: int       # offset within doc
      char_end: int         # offset within doc
      bbox: List[float]     # [x0, y0, x1, y1] for rendering overlay
      text: str             # the verbatim text in this chunk
      structural_role: str  # "heading"|"paragraph"|"clause"|"footnote"|"table_cell"|...
      hierarchy: List[str]  # ["Section 4", "4.2", "4.2(b)"] for clause-level docs
  ```
- Chunks are sized for retrieval (target ~500 tokens, soft boundaries on structural breaks).
- Both vector embeddings and full-text indexing are computed per-chunk.

*Retrieval.*
- Hybrid retrieval: vector similarity + BM25 full-text + structural-role filtering.
- Top-k retrieval returns chunks with full citation metadata, not just text.

*Generation.*
- The system prompt requires the model to cite *only* chunk IDs from the retrieved set.
- Structured output enforces a JSON shape:
  ```json
  {
    "answer_with_citations": [
      {"text": "Section 4 limits liability to fees paid in the prior 12 months.", "citations": ["chunk-uuid-1"]},
      {"text": "However, Section 4(c) carves out willful misconduct.", "citations": ["chunk-uuid-2"]}
    ]
  }
  ```

*Verification.*
- A secondary, cheap model (or deterministic check) verifies that the asserted claims are supported by the cited chunks.
- A deterministic check verifies that any verbatim quote in the answer appears verbatim in at least one cited chunk.
- Failed verifications are flagged in the rendered output ("citation unverified — review source").

*Rendering.*
- Inline citations are clickable in the chat UI.
- Clicking opens a side-panel PDF viewer (PDF.js).
- The viewer scrolls to the right page and overlays a bounding-box highlight at the chunk's bbox coordinates.
- Multiple citations to the same document open the same viewer with sequential highlights.

**Non-functional requirements.**
- Document ingestion: < 30s for a 50-page PDF on reasonable hardware.
- Citation verification: < 500ms per cited claim.
- Side-panel viewer renders in < 1s.

**API surface.**
- `POST /api/v1/documents` — upload document.
- `GET /api/v1/documents/{id}` — document metadata.
- `GET /api/v1/documents/{id}/chunks?query=...` — retrieve relevant chunks.
- `POST /api/v1/citations/verify` — verify a list of cited claims against cited chunks.
- `GET /api/v1/documents/{id}/render?page={n}&highlight={bbox}` — render page with highlight overlay (returns PNG or PDF page).

**Data model.**
- `Document`: id, owner_id, filename, mime_type, page_count, ingestion_status, created_at.
- `CitableChunk`: as specified above. Stored in pgvector + FTS index.
- `Citation`: id, message_id, chunk_id, claim_text, verification_status, verified_at.
- `WorkProductAttribution` (new in v0.2): id, message_id, user_id, chat_id (with optional project_id), routed_inference_tier, provider, model, model_version, skill_ids (array), playbook_id (nullable), timestamp, content_hash. This is the chain of custody for legal work product. The metadata is exposed in the per-user export bundle (§5.3) and is pre-requisite for the privilege-and-custody story in §1.8 and the deferred cryptographic-timestamping enhancement (§9 Security and Compliance).

**Dependencies.** Document Pipeline, Knowledge Service, Inference Gateway.

**Open questions.**
- Should the verifier be a dedicated cheap model (Haiku, Gemini Flash) or a deterministic substring check, or both? Recommend both: deterministic substring check first (catches verbatim quotes), LLM judge for paraphrased claims.
- Side-panel viewer: PDF.js is the obvious choice for PDFs. For DOCX sources, do we render a synthesized PDF or a styled HTML view? Recommend HTML view for DOCX with span-level offset markers.

### 3.4 Skill Library and Skill Creator

**M1 status:** Shipped. The Skill Library (browse built-in, user, and team scopes), Skill Creator (capture / wizard / fork), skill versions tab, per-version audit, Try-It sandbox, and slash-invoked skills with provenance pill are all wired end-to-end in Wave D.2. An operator can verify at `api/app/api/skills.py`; Cypress E2E coverage is in `web/cypress/e2e/wave-d2-skill-creator.cy.ts` (Tests 1–6). Skill script execution (`scripts/`) and autonomous skill self-improvement are deferred (M4). See [HONEST-STATE.md §1](HONEST-STATE.md#1-conversational-and-workspace-surface).

**Description.** Skills are reusable, structured prompt artifacts that users attach to chats. They follow the agentskills.io / Claude Skills format: a folder containing `SKILL.md` (with YAML frontmatter) and optional supporting files. Three tiers: built-in skills (ship with the product), user skills (created by the user), and shared skills (shared by other users in the organization).

The Skill Creator is itself a skill — a meta-skill the user invokes to build new skills via conversation.

**User stories.**
- As a user, I open the Skill Library and browse skills by category.
- As a user, I attach one or more skills to a chat.
- As a user, I chain multiple skills (e.g., "review this contract" + "rewrite in plain language") and the system applies both.
- As a user, I invoke the Skill Creator via conversation to build a new skill, and it produces a valid skill folder.
- As a user, I save any chat as a skill ("turn this into a skill").
- As a user, I share a skill with my team or organization.
- As a user, I edit a skill's content directly via a built-in editor.
- As a user, I ask the system to update a skill based on what I just did in this chat.

**Functional requirements.**

*Skill format.* Each skill is a folder with this structure:

```
my-skill/
├── SKILL.md              # Required. Main instruction file with YAML frontmatter.
├── reference/            # Optional. Reference material the skill cites.
│   └── ...
├── examples/             # Optional. Worked examples.
│   └── ...
└── scripts/              # Optional. Executable helpers (Python).
    └── ...
```

`SKILL.md` frontmatter:

```yaml
---
name: nda-review
title: NDA Review
description: Review a non-disclosure agreement for unusual provisions and risks.
version: 1.0.0
author: LegalQuants
tags: [contracts, nda, review]
trigger_examples:
  - "review this NDA"
  - "what should I watch for in this confidentiality agreement"
  - "redline this NDA"
inputs:
  required:
    - document
  optional:
    - jurisdiction
    - perspective  # "discloser"|"recipient"|"mutual"
lq_ai:
  output_format: report   # "report" | "table" | "issue_list" (table reserved for §3.14 Tabular Review)
  minimum_inference_tier: 2   # optional; if set, skill refuses to run below this tier (per §3.13)
  is_organization_profile: false   # optional; true marks this skill as the singleton Org Profile (per §3.12)
---
```

The `lq_ai:` namespace fields are the project-specific extensions to the agentskills.io standard frontmatter. Skills authored against the open standard work without them; the LQ.AI application uses them when present. See §3.13 for the inference-tier model and §3.14 for the tabular output mode.

*Skill chaining.* When multiple skills are attached, their `SKILL.md` instructions are concatenated in the order attached, with clear delimiters. The model is instructed to apply all skills.

*Skill Creator.* A built-in skill that, when attached, drives a structured conversation:
1. What does the skill do?
2. When should it trigger?
3. What inputs does it need?
4. What output format?
5. What edge cases should it handle?
6. What examples can you give?

The output is a complete `SKILL.md` file plus optional supporting files.

*Save chat as skill.* The user invokes "Turn this into a skill" — the system distills the conversation into a skill folder.

*Skill self-improvement.* The user can attach an instruction to a skill: *"After execution, ask the user if any improvements are needed and update this skill accordingly."* This makes the skill a learning artifact.

**Non-functional requirements.**
- Skill Library loads in < 500ms.
- Skill creation via Skill Creator completes in < 2 minutes for a simple skill.

**API surface.**
- `GET /api/v1/skills` — list available skills (built-in + user's + shared).
- `POST /api/v1/skills` — create skill (accepts skill folder as a tarball or JSON-serialized form).
- `GET /api/v1/skills/{id}` — get skill content.
- `PATCH /api/v1/skills/{id}` — update skill.
- `DELETE /api/v1/skills/{id}` — delete skill.
- `POST /api/v1/skills/{id}/share` — share with users/groups/org.
- `POST /api/v1/skills/from-chat/{chat_id}` — generate a skill from a chat.

**Data model.**
- `Skill`: id, name, title, description, version, author, tags, frontmatter (JSONB), content, owner_id, scope (personal|group|org|builtin), created_at, updated_at.
- `SkillFile`: skill_id, path, content_blob_id.
- `SkillAttachment`: chat_id, skill_id, attached_at, order.

**Dependencies.** Inference Gateway, Knowledge Service.

**Skill inspectability (cross-cutting principle).** Every skill that affects a chat must be inspectable by the user. When a skill is attached to a chat, when Enhance Prompt is acting on the user's input, when an autonomous-layer agent (M4) reads a skill to decide an action — in every case the user can click through to read the actual SKILL.md and its supporting files. This is a foundational transparency principle of the project, not an Enhance-Prompt-specific feature. The skill inspector renders the skill's contents in a side panel with:

- The full SKILL.md (frontmatter + body).
- Each supporting file as a separate tab.
- A "where this came from" line: builtin / authored by [user] / shared by [user/group/org] / forked from [parent skill].
- A "fork this skill" affordance for users who want to create their own version.

The corresponding API endpoint is `GET /api/v1/skills/{id}/contents`, which returns all files in the skill folder. Skills are not opaque artifacts; they are open-source work product the user can read, modify, and replace.

**Skill-input-form pattern.** Skills declare their required and optional inputs in the `lq_ai:` frontmatter namespace (see §3.4 skill format). When a skill is attached to a chat and required inputs are not yet provided, the application surfaces those inputs as a structured form-like prompt rather than letting the model ask for them in the response. This pattern is used by Enhance Prompt (§3.2) and by any other skill author who wants their skill to feel form-driven rather than purely conversational. The application:

- Reads `inputs.required` and `inputs.optional` from the skill's frontmatter.
- Identifies which required inputs have not been provided (via prior conversation, attached files, or explicit user input).
- Renders the missing inputs as form elements (single-select for enums, text fields for free text, file pickers for documents).
- Submits the prompt with structured input values once the user provides them.

The API endpoint `GET /api/v1/skills/{id}/inputs` returns the skill's input schema for use by the application UI.

**Open questions.**
- Should skills support arbitrary code execution (`scripts/`)? Recommend: yes, but sandboxed, opt-in, and permission-gated. Not in v1; defer to M4.

### 3.5 Files / Knowledge Bases

**M1 + M2 status:** Shipped. Knowledge base create, document attach, PDF upload, and ingest-to-`ready` (pgvector + FTS hybrid retrieval) wired end-to-end in M1; the Citation Engine's byte-level verification step landed in M2-A through M2-D and now runs against every model-emitted citation per [§3.3](#33-citation-engine-exact-quote). An operator can verify at `api/app/api/knowledge_bases.py`, `api/app/pipeline/ingest.py`, `api/app/workers/document_pipeline.py`, and `api/app/citation/verification.py`; Cypress E2E coverage in `web/cypress/e2e/wave-m1-final-surfaces.cy.ts` Test 2 (M1 retrieval) and `web/cypress/e2e/m2-c2-citation-states.cy.ts` (M2 citation-rendering states). See [HONEST-STATE.md §1](HONEST-STATE.md#1-conversational-and-workspace-surface) and [HONEST-STATE.md §3](HONEST-STATE.md#3-m2-shipped-capabilities--citation-engine-and-anonymization-layer).

**Description.** Persistent collections of documents accessible across chats. Files are uploaded once, ingested into the citation pipeline, and made available for retrieval. Knowledge Bases group files for shared access (e.g., "Privacy Compliance Library," "Standard Templates").

**User stories.**
- As a user, I upload my company's standard MSA template once and reference it across many chats.
- As a user, I create a "GDPR Reference" Knowledge Base with the regulation, guidelines, and our internal policies.
- As a user, I share a Knowledge Base with my team.
- As a user, I ask a question and the system retrieves from the relevant Knowledge Base automatically.

**Functional requirements.**
- File upload via drag-and-drop or file picker.
- Supported formats v1: PDF, DOCX, TXT, MD, RTF, HTML.
- Document ingestion runs the Citation Engine pipeline (§3.3).
- Knowledge Bases can have multiple files; files can belong to multiple Knowledge Bases.
- Per-file and per-KB sharing controls (personal, group, org).
- `#` command in chat to attach a file or KB inline.

**Non-functional requirements.**
- Upload progress visible to user.
- Ingestion happens asynchronously; chat is usable immediately, citations from this file become available when ingestion completes.

**API surface.**
- `POST /api/v1/files` — upload file.
- `GET /api/v1/files` — list files.
- `GET /api/v1/files/{id}` — file metadata.
- `DELETE /api/v1/files/{id}` — delete file.
- `POST /api/v1/knowledge-bases` — create KB.
- `POST /api/v1/knowledge-bases/{id}/files` — add file to KB.

**Data model.**
- `File`: id, owner_id, filename, mime_type, size, storage_path, ingestion_status, scope, created_at.
- `KnowledgeBase`: id, owner_id, name, description, scope, created_at.
- `KnowledgeBaseFile`: kb_id, file_id.

**Dependencies.** Document Pipeline (§3.3), Knowledge Service.

**Open questions.** None blocking.

### 3.6 Research

**M1+M2 status:** Not yet started in code. No web-search backend or legal-source connector exists in the codebase. `grep -r "research" api/app/api/` returns no research-specific handler; `api/alembic/versions/` has no `research_queries` migration. The Citation Engine pipeline dependency (§3.3) was met when M2 shipped — Research is now unblocked for contribution. The capability is fully spec'd here and in [PRD §9](PRD.md#9-deferred-enhancements-and-identified-future-work); a contributor picking it up should open a discussion before starting because the integration surface (citation-aware retrieval + ephemeral-document handling) is substantial. See [HONEST-STATE.md §4](HONEST-STATE.md#4-capabilities-not-yet-started-in-source).

**Description.** Real-time legal information retrieval from authoritative sources, with the same Citation Engine fidelity as document-based citations. Web sources are fetched, parsed, and treated as ephemeral documents in the citation pipeline.

**User stories.**
- As a user, I ask "what does GDPR Article 28 require for processors?" and receive an answer with citations to the official EUR-Lex source.
- As a user, I ask about a recent SEC rule and the system fetches the relevant Federal Register entry.
- As a user, I see clear source attributions and can click through to the original.

**Functional requirements.**
- Web search via configured providers: SearXNG (default, self-hosted, MIT), Tavily, Brave, Google PSE, Kagi (operator-configurable).
- *Legal source connectors* with direct fetchers and source-specific parsing:
  - CourtListener (US case law, free)
  - GovInfo (US federal documents)
  - Congress.gov
  - Federal Register
  - EUR-Lex (EU law)
  - SEC EDGAR
- Fetched content runs through the document pipeline; citations work the same way as for uploaded files.
- Source-priority configurable: operator can boost certain domains (e.g., "always prefer .gov over secondary commentary").

**Non-functional requirements.**
- Research query end-to-end latency: < 15s for a typical question.

**API surface.**
- `POST /api/v1/research` — run a research query, return answer with citations.
- `GET /api/v1/research/sources` — list configured search providers and legal source connectors.

**Data model.**
- Research results are stored as ephemeral documents in the citation pipeline; standard `Document` and `CitableChunk` entities.
- `ResearchQuery`: id, user_id, query, sources_used, results_summary, created_at.

**Dependencies.** Document Pipeline, Knowledge Service.

**Open questions.**
- Should research results be cached? Recommend: yes, with a configurable TTL (default 24h), and the cache is queryable as a "Research Cache" knowledge base.

### 3.7 Playbooks

**M1+M2 status:** Deferred-M3. No `playbooks` table exists in `api/alembic/versions/`; no `playbook_executions` endpoint is registered. The `word-addin/` directory is absent. The Citation Engine dependency (§3.3) was met when M2 shipped; the remaining dependency is the LangGraph executor landing in M3. See [HONEST-STATE.md §4](HONEST-STATE.md#4-capabilities-not-yet-started-in-source).

**Description.** Structured, reusable contract-review automation. A Playbook codifies an organization's standard positions and fallback positions on common contract issues. When applied to a contract, the Playbook produces a per-position assessment: matches standard, deviates (with severity), or missing entirely. Includes redline suggestions.

**User stories.**
- As a user, I select "Apply NDA Playbook" against an uploaded NDA; the system produces a structured review report.
- As a user, I see for each position: the standard language, what the contract says, the assessment, and a suggested redline.
- As a user, I create a custom Playbook by uploading 5–10 prior negotiated agreements; the system clusters typical positions and drafts a Playbook for my approval.
- As a user, I edit Playbook positions via a structured editor.
- As a user, I run a Playbook from inside Microsoft Word against the open document.

**Functional requirements.**

*Playbook schema.*

```python
class Playbook(BaseModel):
    id: UUID
    name: str
    contract_type: str  # "NDA"|"MSA-SaaS"|"MSA-Commercial"|"DPA"|...
    description: str
    version: str
    positions: List[Position]

class Position(BaseModel):
    id: UUID
    issue: str  # "Limitation of Liability"
    description: str
    standard_language: str  # the org's preferred clause
    fallback_tiers: List[FallbackTier]  # ranked acceptable alternatives
    redline_strategy: str  # how to redline if deviating
    severity_if_missing: Literal["critical", "high", "medium", "low"]
    detection_keywords: List[str]  # to find this issue in a contract
    detection_examples: List[str]  # example clauses for embedding-based matching
```

*Built-in playbooks (M3 release).*
- Generic SaaS MSA Playbook
- NDA Playbook (mutual + unilateral variants)
- DPA Playbook (GDPR-aligned)
- Commercial MSA Playbook (purchase-side)

*Easy Playbook (auto-generation).* Wizard:
1. Upload 5–20 prior agreements of the same contract type.
2. System extracts clauses, clusters by issue, identifies the user's most-common positions.
3. System drafts a Playbook with suggested standard language and fallback tiers.
4. User reviews, edits, approves.

*Playbook execution.* LangGraph workflow:
1. Parse target contract via Document Pipeline.
2. For each Playbook position, retrieve the matching clause(s) in the target contract via hybrid search.
3. Classify: matches standard / matches fallback tier N / deviates / missing.
4. For deviations, draft a redline using the redline_strategy.
5. Compile into a structured review report with citations.

*Playbook execution in Word.* The same LangGraph workflow runs against the Word document via the Office.js add-in, with redlines applied as Word tracked changes and assessments as Word comments.

**Non-functional requirements.**
- Playbook execution against a 50-page MSA: < 3 minutes.
- Easy Playbook generation from 10 prior agreements: < 10 minutes.

**API surface.**
- `GET /api/v1/playbooks` — list playbooks.
- `POST /api/v1/playbooks` — create playbook.
- `POST /api/v1/playbooks/easy` — start Easy Playbook generation.
- `GET /api/v1/playbooks/easy/{id}` — check generation status.
- `POST /api/v1/playbooks/{id}/execute` — execute against a target document.
- `GET /api/v1/playbook-executions/{id}` — get execution result.

**Data model.**
- `Playbook` and `Position` as schemas above.
- `PlaybookExecution`: id, playbook_id, target_document_id, user_id, status, results (JSONB), created_at, completed_at.

**Dependencies.** Document Pipeline, Inference Gateway, Knowledge Service.

**Open questions.**
- How granular are the redline suggestions? Recommend: redlines are structured ({old_text, new_text, justification}) so they can be applied either as Word tracked changes or rendered as a diff in the web UI.

### 3.8 Multi-Model Ensemble Verification

**M2 status: SHIPPED.** Ensemble verification ships as Stage 4 of the Citation Engine cascade — see [§3.3](#33-citation-engine-exact-quote). Activation `any()`s across the project's `ensemble_verification` column, any applied skill's `ensemble_verification: true` frontmatter, and the gateway's `citation_engine.ensemble_verification.default_enabled` config. Aggregation rule (`strict` requires unanimous agreement across N judges; `majority` needs N/2+1) is configurable in `gateway.yaml`. The per-message cost-budget pre-flight (M2-D1) falls back to single-judge Stage 3 if the per-model rolling-average estimate (M2-E2) would exceed the cap. The privacy envelope across the judges is computed eagerly at config-load and persisted per row as `message_citations.tier_envelope` so operators can audit which chats had citations sent to weaker tiers.

The scope-as-shipped is narrower than the original "ensemble runs on the whole answer" framing: ensemble runs on Citation Engine verification specifically (the load-bearing high-stakes surface), not on every chat response. The "ensemble runs the full chat path with N parallel reconciled completions" surface is **not built** — operators wanting cross-model answer reconciliation today configure parallel chat sessions with different aliases.

**Description.** GC.AI markets "multi-model RAG (calls 5 different AI models)" as an accuracy feature. LQ.AI implements this as an *optional* ensemble step where multiple models are queried in parallel and their outputs are reconciled. Off by default (cost reasons); on for specific high-stakes operations like Playbook execution and Citation Engine verification.

**User stories.**
- As an operator, I configure ensemble mode for the Citation Engine verification step.
- As a user, I see a confidence score on the answer reflecting agreement across models.
- As an operator running Mode 2 (local Ollama only), the ensemble degrades gracefully to "diversified prompts on the same model" rather than failing.

**Functional requirements.**
- Ensemble runs N parallel model calls (configurable, default N=3 in cloud mode, N=1 in pure-local mode).
- Models can be different providers (Anthropic + OpenAI + Google) or the same provider with different models, or in local mode the same model with different temperatures and prompt phrasings.
- Reconciliation step: a final model call (or deterministic logic) resolves disagreements.
- Cost tracking: ensemble calls are tagged so operators see ensemble vs single-model spend.

**Non-functional requirements.**
- Ensemble adds at most 30% latency over the slowest single call (parallelism, not sequential).

**API surface.**
- Ensemble is invoked internally by other capabilities; not a user-facing endpoint. Configuration via:
- `GET /api/v1/admin/ensemble-config` and `PATCH /api/v1/admin/ensemble-config`.

**Dependencies.** Inference Gateway.

**Open questions.**
- Reconciliation strategy: voting (for classification tasks), LLM judge (for open-ended), or both? Recommend: configurable per-capability, with sensible defaults.
- **Inference tier exposure for multi-tier ensembles.** When the ensemble spans multiple Inference Tiers (a chat using Tier 3 cloud + Tier 1 local for cross-verification), how is the chat's effective tier represented in the UI (§3.13)? Recommended resolution: surface the *minimum* tier across the ensemble as the chat's effective tier, since that is the privacy posture that actually applies — every model in the ensemble has seen the data, so the chat's effective tier is the floor.

### 3.9 Word Add-In (M3)

**M1 status:** Deferred-M3. The `word-addin/` directory is absent from the repository (`ls word-addin/` returns no such directory). No Office.js manifest, no Word-side JS bundle, no add-in-specific backend wiring. See [HONEST-STATE.md §4](HONEST-STATE.md#4-capabilities-not-yet-started-in-source).

**Description.** Microsoft Office.js add-in that brings LQ.AI capabilities directly into Word. Users can run skills, execute Playbooks, get redlines, ask questions about the document, and act on the assistant's suggestions — all without leaving Word.

**User stories.**
- As a user editing an MSA in Word, I open the LQ.AI pane and click "Apply MSA-SaaS Playbook"; the system reviews the document and applies tracked changes + comments.
- As a user, I select a clause and ask "make this more favorable to us as the customer"; the redline appears as a tracked change.
- As a user, I ask a question about the document and the answer appears in the side pane with citations to specific clauses.
- As an admin, I distribute the add-in to my organization via the Microsoft 365 Admin Center.

**Functional requirements.**
- Word add-in (manifest XML + hosted JS bundle) communicates with the same FastAPI backend as the web app.
- Add-in authenticates via OAuth with the LQ.AI deployment.
- Supported Word clients: Desktop (Win/Mac), Word Online, Word for iPad.
- Capabilities exposed in Word:
  - Chat against the open document
  - Apply skills to selection or whole document
  - Execute Playbooks against the document
  - Generate redlines as Word tracked changes
  - Generate comments as Word comments
  - Insert AI-drafted clauses at cursor
  - **Inference Tier badge** in the task pane mirroring the web UI (per §3.13). Click opens the same tier-detail panel the web UI uses.
- The task pane is structured to accept a future "Today view" compact equivalent (per §8.5 forward-looking M5+ workflow intelligence) without architectural change; the M3 task pane reserves the slot.

**Non-functional requirements.**
- Add-in pane loads in < 2s.
- Playbook execution renders progressive results (don't block on full completion).

**API surface.**
- The Word add-in uses the same OpenAPI surface as the web app. No Word-specific backend endpoints.

**Distribution.**
- Enterprise sideload first (manifest + hosted JS distributed via Microsoft 365 Admin Center).
- AppSource public listing as a follow-up.

**Dependencies.** All backend capabilities. Office.js (Microsoft, free).

**Open questions.**
- Hosting of the add-in JS bundle: where does it live for self-hosted deployments? Options: (a) bundled with the LQ.AI deployment and served by it; (b) hosted on a LegalQuants-controlled CDN; (c) downloadable from GitHub releases. Recommend (a) — self-hosted deployment serves its own add-in, minimizing external dependencies.

### 3.10 Autonomous Layer (M4)

**M1 status:** Deferred-M4. No `autonomous_tasks`, `autonomous_schedules`, or `autonomous_watches` table exists in `api/alembic/versions/`. No per-user memory store. The architectural slot is committed; detailed M4 design is deferred. See [HONEST-STATE.md §4](HONEST-STATE.md#4-capabilities-not-yet-started-in-source).

**Description.** Long-running per-user agents that observe activity, learn patterns, take proactive actions, and create skills autonomously. Runs as OpenWebUI Pipelines, off by default, opt-in per user.

**User stories.**
- As a user, I opt in to "autonomous skill suggestions"; after I review my fifth SaaS DPA, the system asks if I'd like it to draft a custom DPA Playbook based on my reviews.
- As a user, I configure a watch on a Knowledge Base; when new documents arrive, the autonomous agent runs a configured Playbook and notifies me of issues.
- As a user, I schedule a weekly compliance scan against our standard contract repository.
- As a user, I see a "memory" view showing what the autonomous agent has learned about my preferences.

**Functional requirements.**
- Autonomous agents run as background pipelines, not user-facing requests.
- Per-user persistent memory store (separate from chat history) tracks patterns, preferences, and past actions.
- Memory is *user-curated* — the user can view, edit, delete entries.
- Cron scheduling for periodic tasks.
- Notifications via email, Slack, or in-app.
- Hard isolation between users — no cross-user memory leakage.

**Boundary-register obligations for autonomous flows (M4 design surface).** The autonomous layer is the LQ.AI surface where Tier 2 of the boundary-register catalog (R4 economic, R5 temporal, R6 contextual — see §1.8 and [`docs/security/boundary-registers.md`](security/boundary-registers.md)) first attaches to running code. M4 design must discharge each: a per-session hard cost cap with halt-on-overrun and a structured `cost_cap_reached` final state (R4); an external halt switch checked before every tool call, with an idle-halt timeout that auto-transitions a paused session rather than bleeding resources (R5); per-workflow-phase tool-grant modulation that strips intake-time tools at the ethics-gate or delivery-phase boundary (R6). The implementation specification is tracked by DE-293. The design study comparing Lavern's `Clawern` pipeline (the most concrete prior art for all three Tier 2 registers) to LQ.AI's planned approach is tracked by DE-289 Phase 1; the design-influences ADR it produces is the input to the M4 implementation plan. If M4 ships *multi-agent* autonomous flows rather than only single-agent ones, the R3-for-cross-agent-handoffs facet (an `orchestrate.py`-equivalent with closed intent allowlist + typed-template prompt rendering + JSONL audit log) attaches alongside the Tier 2 work, tracked by DE-294; the single-agent vs. multi-agent pin is the first deliverable of DE-289 Phase 1.

**Non-functional requirements.**
- Autonomous activity must not interfere with interactive use; runs at lower priority.

**API surface.**
- `GET/POST /api/v1/autonomous/memory` — view and edit user memory.
- `GET/POST /api/v1/autonomous/schedules` — manage scheduled tasks.
- `GET/POST /api/v1/autonomous/watches` — manage watches.

**Dependencies.** All other capabilities. OpenWebUI Pipelines framework.

**Open questions.**
- This is M4 territory; detailed design deferred. The PRD commits to the capability and the architectural slot, not to the full design.
- **Distinction from Projects (§3.11).** Autonomous-layer memory is system-curated and observed; Project context is user-curated and matter-scoped. Both serve different purposes; one informs the other. The autonomous layer can *propose* additions to a Project's context, but the user owns the Project.
- **Forward extension to M5+ (§8.5).** The autonomous layer's memory and scheduled-pipelines substrate is the foundation on which the M5+ workflow-intelligence direction extends. M4 design choices should anticipate that extension — particularly multi-step agents that take external-side-effecting actions with human approval gates, since retrofitting that into a memory-and-watches-only autonomous layer is harder than designing for it from the start.

---

### 3.11 Projects (M1)

**M1 status:** Shipped. Matter (project) workspaces are wired end-to-end: create, list, detail view at `/lq-ai/matters/[id]`, attached files/skills/knowledge bases, the `privileged` flag, and `minimum_inference_tier`. An operator can verify at `api/app/api/projects.py`; Cypress E2E coverage is in `web/cypress/e2e/wave-c-matters.cy.ts`. Note: playbook attachment lands when Playbooks ship (M3). See [HONEST-STATE.md §1](HONEST-STATE.md#1-conversational-and-workspace-surface).

**Description.** A Project is a user-curated container that scopes a set of chats, files, skills, playbooks, and a free-form context document around a single matter — a deal, a counterparty, a regulatory question, a policy refresh. Chats inside a Project automatically inherit the Project's attached files and skills. The Project's free-form context document ("we are the customer; counterparty is Acme; their counsel is Smith Crowell; we agreed to a 12-month liability cap last round") is read into every chat in the Project as context. Projects are the operational answer to the question "what about *this matter*?" — distinct from per-chat attachments (which solve "this conversation") and from autonomous-layer memory (which is system-curated rather than user-authored).

Persistent matter memory is the single most-cited capability across in-house users in the competitive research and is the reason GC.AI customers cite stickiness. Projects are the single most consequential capability addition to v1.

**Distinction from autonomous memory (§3.10).** Autonomous-layer memory is system-curated, derived from observed user activity, and runs as background pipelines. Project context is user-curated, explicitly authored, and matter-scoped. They complement: the autonomous layer can *propose* additions to a Project's context, but the user owns the Project.

**User stories.**
- I create a Project for "Acme MSA renewal," attach the prior MSA, our standard MSA template, and the MSA Playbook. Three chats later, the latest chat still knows we are the customer and what was negotiated last round.
- I share a Project with a teammate; both of us see the same matter context.
- I archive a Project when the matter closes; it is searchable but does not clutter the active list.
- I mark a Project as `privileged: true`. The application enforces a minimum inference tier (default Tier 2), disables anonymization (which complicates a privilege analysis), and marks every chat and audit-log entry in the Project as privileged for later e-discovery filtering.

**Functional requirements.**
- Project as a top-level resource with name, description, free-form context document (Markdown), attached files, attached skills, attached playbooks, default model alias, owner, share scope, optional `privileged` flag, optional `minimum_inference_tier`.
- Chats can be created inside or outside a Project; chats inside a Project inherit its attachments and context.
- A user can move a chat into or out of a Project.
- Project context document is editable as Markdown.
- Search across Projects and search within a Project are both supported.
- Skill inspectability extends naturally — viewing a skill in a Project context shows the skill itself plus the Project's note "this skill is attached at the Project level."

**API surface.**
- `POST /api/v1/projects` — create.
- `GET /api/v1/projects` — list (filter by owner, share scope, archived).
- `GET /api/v1/projects/{id}` — fetch with attachments and context.
- `PATCH /api/v1/projects/{id}` — update name, description, context, attachments, privileged flag, minimum_inference_tier.
- `DELETE /api/v1/projects/{id}` — delete (soft-delete with retention per audit policy).
- `POST /api/v1/projects/{id}/chats` — create a chat inside this Project.
- `POST /api/v1/projects/{id}/share` — share with another user or group.

**Data model.**
- `Project` table: id, name, description, context_markdown, owner_id, share_scope, privileged (bool), minimum_inference_tier (int, nullable), archived_at (nullable), created_at, updated_at.
- `ProjectAttachment` table: project_id, attachment_type (file / skill / playbook), attachment_id.
- `Chat` table gains a nullable `project_id` field (FK to Project).

**Dependencies.** Conversational Core (§3.1), Files / Knowledge Bases (§3.5), Skill Service (§3.4), Playbooks (§3.7), RBAC (§5.2), Audit Logging (§5.3).

**Architectural placement.** No new service required. Fits within the existing FastAPI backend. Reference architecture diagram in §2.1 should show Projects as a top-level resource alongside Files / Skills / Playbooks.

---

### 3.12 Organization Profile (M1)

**M1 status:** Shipped. The singleton skill pattern with `lq_ai: { is_organization_profile: true }` frontmatter is enforced by the Skill Service. Admins can create or edit the Organization Profile through the same Skill Library surface as any other skill. An operator can verify the singleton constraint at `api/app/api/skills.py`. See [HONEST-STATE.md §1](HONEST-STATE.md#1-conversational-and-workspace-surface).

**Description.** A singleton skill that captures the organization's voice, templates, and "what good looks like" reference, available as ambient context to every chat and skill execution in the deployment. The Organization Profile is implemented as a skill with `lq_ai: { is_organization_profile: true }` frontmatter — same skill format as everything else, same inspectability, same fork-and-replace pattern, but treated as a singleton by the Skill Service. Single-instance per deployment; admin-edited; user-readable.

**Why a singleton skill (rather than a separate construct).** Treating the Organization Profile as a skill with special metadata preserves the architectural simplicity (one extensibility surface, not two) and the transparency principle (the Organization Profile is open source and inspectable like every other shaping artifact — see §1.3).

**User stories.**
- As an admin, I create the Organization Profile capturing our company's tone of voice, our standard contract preferences, our key clauses, our typical counterparty types, and our internal escalation paths.
- As a user, every chat I open implicitly reads the Organization Profile as context. The same NDA Review skill produces output calibrated to our standards.
- As a contributor, I can fork the Organization Profile, propose changes through the standard skill PR flow, and version it.

**Functional requirements.**
- Organization Profile is a skill (same SKILL.md format).
- The skill is marked as singleton via frontmatter — the Skill Service ensures only one Organization Profile exists per deployment.
- The Organization Profile is admin-editable but user-readable; the Skill Inspector (§3.4) shows it like any other skill.
- The Organization Profile is automatically applied as ambient context to every chat unless the user explicitly opts out for that chat.
- First-run onboarding (§6.2) prompts the operator to create or import an Organization Profile (or skip and create later).

**Data model.** Reuses Skill Service tables; the singleton constraint is enforced at the application layer.

**API surface.** Reuses Skill Service endpoints with the singleton constraint.

**Dependencies.** Skill Service (§3.4). No new architectural component.

---

### 3.13 Inference Tier Awareness (M1)

**M1 status:** Shipped. The Inference Gateway annotates every request with `routed_inference_tier` (1–5) and enforces tier-floor refusal. The tier badge is present in the chat UI; admin tier-floor override is wired. An operator can verify the gateway enforcement at `gateway/app/tier_floor.py` (124 LOC) and `gateway/app/router.py`; Cypress E2E coverage is in `web/cypress/e2e/wave-d1-power-features.cy.ts` Tests 3 and 5. Note: `GET /api/v1/inference/current-tier` is not yet in code at M1 (it is in the gateway OpenAPI sketch as a deferred endpoint). See [HONEST-STATE.md §2](HONEST-STATE.md#2-inference-gateway-and-providers).

**Description.** A persistent badge in the chat UI shows the current Inference Tier (1–5) and the specific provider routing for the current chat. A click on the badge opens a panel explaining what the tier implies: where the data is going, what the provider's retention policy is, whether the prompt is being logged in the operator's audit log, whether anonymization (§4) is on, and whether the deployment is air-gapped. The same panel is available in the Word add-in. This is the most important security-posture feature of the entire project and one of the smallest pieces of code: every chat already routes against an inference provider; the application already knows which one; surfacing that to the user is a UI affordance away. The transparency philosophy in §1.3 requires it.

**User stories.**
- I look at my chat header and see "Tier 3 — Anthropic Enterprise (ZDR)." I know what that means.
- I have a privileged communication to draft. I look at the badge and see "Tier 4 — OpenAI standard." I downgrade my chat to the local Tier 1 model before continuing, or I cancel and use a Project that requires Tier 1–2.
- I am an admin. I configure the deployment to refuse Tier 4–5 routing globally; users see a "Tier 4 not allowed by your administrator" message if they try.
- I author a skill. I declare in the skill's frontmatter `lq_ai: { minimum_inference_tier: 2 }`. The application refuses to run the skill if the routed tier is below 2 and shows the user why.

**Functional requirements.**
- A `Tier` enum (1–5) with rules for derivation from the routed provider/model and the gateway's configuration.
- The Inference Gateway annotates every routed request with its derived tier; the backend includes the tier in the chat metadata.
- The web UI displays the tier badge in the chat header and in the prompt-input area.
- The Word add-in displays the tier in its task pane.
- Skills can declare `minimum_inference_tier` in their frontmatter (default: none).
- Projects (§3.11) can declare `minimum_inference_tier`.
- The deployment configuration can declare `allowed_inference_tiers` globally and per-group.
- Tier-violation attempts are logged in the audit log.
- The tier-detail panel renders provider-specific compliance facts pulled from the Provider Compliance Matrix (`docs/compliance/provider-compliance-matrix.md`).

**API surface.**
- `GET /api/v1/inference/current-tier?provider={provider}&model={model}` — returns derived tier and human-readable explanation.
- `GET /api/v1/inference/tier-config` — returns the deployment's allowed-tier configuration.
- `PATCH /api/v1/admin/inference/tier-config` — admin-only configuration update.

**Data model.**
- Existing `Message` row gains a `routed_inference_tier` field.
- Existing `Skill` and (per §3.11) `Project` rows gain `minimum_inference_tier`.
- Configuration adds `inference_tiers` block to `gateway.yaml` and global config.

**Dependencies.** Inference Gateway (§4), Skill Service (§3.4), Conversational Core (§3.1), Provider Compliance Matrix (documentation deliverable in M1).

**Architectural placement.** The tier derivation is a small piece of Inference Gateway code. The UI rendering is a header component in the OpenWebUI fork and a corresponding panel in the Word add-in. No new service required.

**Open questions.**
- How do we handle ensemble verification (§3.8) where the ensemble spans multiple tiers? Recommended resolution: surface the *minimum* tier across the ensemble as the chat's effective tier, since that is the privacy posture that actually applies.
- Do we expose tier downgrade prompts ("the model you have access to is Tier 1; the answer would be better at Tier 3 — would you like to switch and re-run?") proactively? Recommend: yes, but only when the user has already explicitly opted in to the upgrade in their account preferences. Do not nudge by default.

---

### 3.14 Tabular / Multi-Document Review (M3)

**M1+M2 status:** Deferred-M3. No grid surface, no LangGraph Tabular Review workflow, and no `output_format: table` skill-mode handling. The Citation Engine dependency (§3.3) was met when M2 shipped; the remaining dependency is the Playbook/LangGraph executor (§3.7) which lands in M3. See [HONEST-STATE.md §4](HONEST-STATE.md#4-capabilities-not-yet-started-in-source).

**Description.** A view that takes (a) a set of documents (a Knowledge Base, a Project's files, a free selection) and (b) a set of questions or clauses to extract, and produces a row-per-document, column-per-question grid. Each cell is a citation-grounded answer that opens the side-panel viewer (§3.3) on click. The "compare clauses across N contracts in a grid" pattern (Legora Tabular Review, Harvey Vault, Ivo Repository columns) is a different UI shape than chat. In-house teams use it for due diligence, audits, portfolio-wide policy checks, and "what is market across the deals we have signed."

**User stories.**
- I select 30 NDAs and ask "what is the term length, the survival period, the carveouts, and the governing law for each?" — I get a 30-row, 4-column table with citations.
- I select a Project's files and ask "show me defined-terms inconsistencies across these documents."
- I export the table as XLSX or CSV.

**Functional requirements.**
- Tabular Review runs as a LangGraph workflow: for each document × column, run a skill-like extraction with the Citation Engine.
- Columns can be specified ad hoc, saved, and reused (a "Tabular Review skill" — same skill format, output type is `table` not `report`).
- Cells link to the cited chunk(s) in the source document.
- Failed extractions render as "not found" with a "verify" affordance, never as a confident wrong answer.
- Bulk operations: "redline column 3 in all rows," "draft a memo summarizing column 5."
- Cost preview before execution; user confirms (200 docs × 10 columns = 2,000 model calls is non-trivial).

**Architectural fit.** This is mostly a new Skill output type plus a UI surface. The Citation Engine (§3.3), Document Pipeline, Knowledge Service (§3.5), and LangGraph runtime all already exist for it. Update §3.4 (Skill format) to document the `output_format: table` mode.

**Open questions.**
- Should ensemble verification (§3.8) be on by default for tabular cells, given the volume? Recommended: yes for high-stakes columns, configurable per-column.

**Dependencies.** Citation Engine (§3.3), Skill Service (§3.4), Files / Knowledge Bases (§3.5), Inference Gateway (§4), LangGraph runtime.

---

### 3.15 Slack / Teams Light Intake Bridge (M3)

**M1 status:** Deferred-M3. No `/lq` slash-command handler, no bot manifest, no `slack-bridge` or `teams-bridge` Docker Compose service exists at M1. See [HONEST-STATE.md §4](HONEST-STATE.md#4-capabilities-not-yet-started-in-source).

**Description.** A Slack and Teams bot that supports two flows: (1) **forward as a chat** — a user `/lq` slash-command on a message thread creates an LQ.AI chat with the thread's content as initial context; (2) **quick ask** — `/lq ask "is this an MSA or an order form?"` runs a short skill (configurable via Org Profile) and replies in-thread. Replies render in the Slack/Teams thread; deeper engagement opens the web app. No matter management, no triage, no SLA tracking — that is the boundary with Streamline AI's category, which is explicitly out of scope per §1.6.

In-house teams report (across the competitive research) that the majority of incoming requests arrive via Slack, Teams, or email — not via direct visits to the legal portal. A web-only product structurally underweights the channels users live in. A *light* Slack/Teams bridge — not full intake/triage like Streamline AI — closes this gap with bounded scope.

**Functional requirements.**
- OAuth-based install on the org's Slack or Teams.
- Permission model: bot can only post in channels it is invited to; bot does not read silent channels.
- Confidentiality: thread contents are stored in LQ.AI under the user's chat history, with the same RBAC as any other chat.
- Bot configuration is in the LQ.AI admin UI, not in Slack.

**Architectural fit.** Optional service in the Docker Compose (`slack-bridge`, `teams-bridge` with `--profile slack` etc.). Reuses Conversational Core, Auth/RBAC, Skill Service. No new core architecture.

**Dependencies.** Conversational Core, Auth/RBAC, Skill Service.

---

### 3.16 Contract Repository — Auto-Relationship Detection (M4)

**M1+M2 status:** Deferred-M4. No `contract_relationships` table exists in `api/alembic/versions/`; no relationship-detection pipeline or graph-query surface. Both upstream dependencies are met: the Knowledge Service pgvector+FTS baseline shipped in M1; the Citation Engine pipeline (§3.3) shipped in M2. See [HONEST-STATE.md §4](HONEST-STATE.md#4-capabilities-not-yet-started-in-source).

**Description.** A pipeline that runs over a Knowledge Base of contracts and produces a relationship graph: amendments (modifies-X), restatements (replaces-X), references (cross-references-X), and master/sub (parent-of-X) edges. The graph is queryable and visible in the UI as a sidebar on each document. Contracts about a counterparty rarely stand alone, and answering questions like "which liability cap actually governs?" requires knowing which document supersedes which. This is Ivo's positioning — that contracts are not isolated documents but a graph — and is not currently addressed in the PRD's flat Knowledge Base model.

**Functional requirements.**
- Detection runs as a Knowledge Base post-ingestion step or on demand.
- A skill or LangGraph workflow analyzes each new document's references and signals (effective date, "this Amendment Number 3 to the MSA dated ..."), proposing edges.
- Edges are user-confirmable; not all detections are correct.
- When asked a question scoped to a Knowledge Base, the system uses the graph to determine the operative document chain ("for this question about liability caps, the operative documents are the MSA + Amendment 2 + the side letter, but not Amendment 1 which Amendment 2 superseded").

**Architectural fit.** Mostly a new resource type (contract-relationship edges) plus skills that produce and consume them. Edges stored in the existing Postgres (a graph extension is a deferred enhancement candidate; not required for v1). No new external dependencies.

**Dependencies.** Document Pipeline, Knowledge Service (§3.5), Skill Service (§3.4).

---

## 4. The LQ.AI Inference Gateway

### 4.1 Why We Build This

Every other component in this stack is something we adopt from the OSS ecosystem. The Inference Gateway is the one component we build ourselves, for two reasons:

1. **Security surface.** This is the component holding privileged API keys for cloud LLM providers. Operators deploying LQ.AI will trust it with significant credentials. The candidate alternative (LiteLLM) has a non-trivial vulnerability history including proxy auth bypasses and SSRF in document loaders. For an open-source project where users may run with our defaults, that surface is unacceptable.
2. **Scope match.** We need a focused subset of functionality — about 15% of LiteLLM's feature surface. Building it ourselves yields ~3,000 lines of code that is fully auditable, has zero supply-chain risk, and ships without features we don't need carrying maintenance burden.

The Inference Gateway is a separate container, importable as a standalone service, with its own OpenAPI specification. Other open-source projects can use it independently.

### 4.2 Functional Scope

**In scope.**
- OpenAI-compatible API surface (`/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/models`).
- Streaming responses (SSE pass-through).
- Provider adapters for: Anthropic, OpenAI, Google Vertex, Cohere, Azure OpenAI, AWS Bedrock, Ollama, vLLM, llama.cpp (any OpenAI-compatible local endpoint).
- Provider routing rules (per-model, per-tag, per-capability).
- Fallback chains (provider A fails → try B → try C).
- Rate limiting per-key and per-model (Redis-backed token bucket).
- Cost tracking per-request (tokens × per-model rates from a config file).
- Model aliases (operator can define "fast", "smart", "cheap" → resolves to specific provider+model).
- Health checks per provider.
- Structured logging.
- OpenTelemetry instrumentation.
- **Tier derivation** (new in v0.2): every request is annotated with its derived Inference Tier (1–5 per §1.5.2 and §3.13) based on the routed provider/model and the gateway's configuration. The tier is included in the response metadata for the application to display.
- **Anonymization middleware** (new in v0.2; M2): an optional pre/post middleware stage that pseudonymizes sensitive entities before the model call and rehydrates them after. See §4.7 for detail.

**Out of scope.**
- Prompt caching (defer to v2).
- Fine-tuning management (out of scope entirely; that's the operator's relationship with the provider).
- Vector search (handled by the Knowledge Service, not the Gateway).
- Multimodal beyond what providers natively support.

### 4.3 Architecture

```
                         OpenAI-compatible API
                                    │
                                    ▼
                         ┌──────────────────┐
                         │  FastAPI surface │
                         └────────┬─────────┘
                                  │
                ┌─────────────────┼──────────────────┐
                ▼                 ▼                  ▼
        ┌─────────────┐    ┌──────────────┐   ┌─────────────┐
        │  Auth       │    │   Router     │   │  Rate Limit │
        │ (API key    │    │ (provider    │   │  (Redis     │
        │  resolution)│    │  selection,  │   │  token      │
        │             │    │  fallback)   │   │  bucket)    │
        └─────────────┘    └──────┬───────┘   └─────────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │  Tier Derivation │  (annotates request
                         │  (per §1.5.2 /   │   with routed_inference_
                         │   §3.13)         │   tier; refuses if below
                         │                  │   skill/Project minimum)
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │  Anonymization   │  (M2; optional pre/post
                         │  (§4.7) — pre    │   middleware; pseudonymizes
                         │                  │   PII before provider call,
                         │                  │   rehydrates on return)
                         └────────┬─────────┘
                                  │
                ┌─────────────────┼──────────────────┐
                ▼                 ▼                  ▼
        ┌─────────────┐    ┌──────────────┐   ┌─────────────┐
        │  Provider   │    │  Cost        │   │   Telemetry │
        │  Adapters   │    │  Tracker     │   │   (OTel)    │
        │             │    │              │   │             │
        │ Anthropic / │    │              │   │             │
        │ OpenAI /    │    │              │   │             │
        │ Vertex /    │    │              │   │             │
        │ Cohere /    │    │              │   │             │
        │ Azure /     │    │              │   │             │
        │ Bedrock /   │    │              │   │             │
        │ Ollama /    │    │              │   │             │
        │ vLLM        │    │              │   │             │
        └──────┬──────┘    └──────────────┘   └─────────────┘
               │
               ▼
       (provider HTTP/gRPC APIs)
               │
               ▼
        ┌──────────────────┐
        │  Anonymization   │  (post — rehydrates pseudonyms in
        │  (§4.7) — post   │   response and citations)
        └──────────────────┘
```

### 4.4 Configuration

Configuration via a single YAML file (`gateway.yaml`), reloadable without restart.

```yaml
# gateway.yaml
providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    base_url: https://api.anthropic.com
    timeout_s: 60
    rate_limit:
      requests_per_minute: 1000
      tokens_per_minute: 200000
  openai:
    api_key_env: OPENAI_API_KEY
    base_url: https://api.openai.com/v1
    timeout_s: 60
  ollama:
    base_url: http://ollama:11434
    timeout_s: 300

models:
  # Operator-defined model registry
  - alias: smart
    provider: anthropic
    model: claude-opus-4-7
    cost_per_1k_input_tokens_usd: 0.015
    cost_per_1k_output_tokens_usd: 0.075
    fallback: [smart-openai]
  - alias: smart-openai
    provider: openai
    model: gpt-4-turbo
    cost_per_1k_input_tokens_usd: 0.01
    cost_per_1k_output_tokens_usd: 0.03
  - alias: fast
    provider: anthropic
    model: claude-haiku-4-5-20251001
    cost_per_1k_input_tokens_usd: 0.0008
    cost_per_1k_output_tokens_usd: 0.004
  - alias: local
    provider: ollama
    model: qwen3.5:9b

routing:
  default: smart
  capabilities:
    embeddings: openai-text-embedding-3-large
  rules:
    - when: { tag: "verification" }
      use: fast
    - when: { tag: "ensemble" }
      use: [smart, smart-openai, local]

api_keys:
  # Operator-issued keys for clients of this gateway
  - id: lq-ai-backend
    key_hash: <sha256 of the actual key>
    allowed_models: ["*"]
    rate_limit_override: null

# --- Inference Tier configuration (new in v0.2; per §1.5.2 / §3.13) ---
inference_tiers:
  # Map each provider/model to a tier so the application can surface it.
  # Operators can override per-deployment to reflect their contractual posture
  # (e.g., "anthropic" set to Tier 3 if the operator has a ZDR addendum).
  defaults:
    anthropic: 4         # Tier 4 by default; override to 3 if ZDR addendum is in place
    anthropic_enterprise: 3
    openai: 4
    openai_enterprise: 3
    google_vertex: 3
    aws_bedrock: 3        # under operator's AWS account → Tier 2 if customer-hosted
    azure_openai: 3       # under operator's Azure tenant → Tier 2 if customer-hosted
    cohere_enterprise: 3
    ollama: 1
    vllm: 1
    "llama.cpp": 1
  allowed_tiers_global: [1, 2, 3, 4]   # disallow Tier 5 globally; warn on Tier 4
  allowed_tiers_per_group:
    privileged-matters: [1, 2]          # privilege-flagged Projects
    privacy-sensitive: [1, 2, 3]
  warn_on_tiers: [4]                    # surface a banner when routing at this tier or below
  refuse_on_tiers: [5]                  # block the request with a clear error

# --- Anonymization Layer (new in v0.2; M2; per §4.7) ---
anonymization:
  default: disabled       # "disabled" | "preferred" | "required"
  fail_closed: true       # if anonymization fails and tier > 2, refuse the request
  entity_types:
    - persons
    - organizations
    - locations
    - monetary_amounts
    - account_numbers
    - email_addresses
    - phone_numbers
  custom_patterns:
    - name: internal_employee_id
      regex: 'EMP-\d{6}'
      replacement: 'EMPLOYEE_{N}'
  ner_backend: "spacy"     # "spacy" | "small_llm" | "hybrid"
  llm_fallback_alias: "fast"  # used for ambiguous spans when ner_backend is "hybrid"
```

#### 4.4.1 Tier derivation and surface (B4)

Tier derivation runs in the Router (per §4.3 architecture diagram) for
every routed chat-completion request. The derived tier is exposed on
three surfaces, populated atomically:

1. **HTTP response header** `X-LQ-AI-Routed-Inference-Tier: <1-5>` —
   header-only consumers (HTTP-tracing proxies, front-end
   instrumentation) read this without parsing the body. The provider
   name is mirrored at `X-LQ-AI-Routed-Provider` for the same audience.
2. **Response body extension field** `routed_inference_tier` — the
   default surface for backend code that's already deserializing the
   OpenAI-shaped response. For streaming responses, every
   `chat.completion.chunk` envelope also carries the field (and
   `routed_provider`) so a consumer that only sees the tail of the
   stream still gets the tier.
3. **`inference_routing_log` audit row** — the persisted audit trail
   per §5.3. One row per routed request (successful or failed). On
   failure the row still carries the tier (the Tier-Derivation choke
   point invariant) plus a `refusal_reason` capturing the upstream
   error code; this lets operators analyze tier distribution
   independent of success/failure.

Resolution order for tier derivation, first match wins:

1. `inference_tiers.overrides["<provider_name>/<model>"]` — most specific.
2. `inference_tiers.overrides["<provider_name>"]` — provider-wide override.
3. `inference_tiers.defaults["<provider_type>"]` — per-type default
   (anthropic, openai, vertex, ...).
4. The provider entry's own `tier:` field — the simplest configuration.

The `inference_tiers` block is optional. With it omitted, every routed
request takes its tier from the provider entry's `tier:` field.

**Fallback chain semantics (B4 skeleton):** when the primary provider
fails with a fallback-eligible error (network failure, upstream 5xx,
or upstream 429), the router walks the alias's configured `fallback`
list in declaration order. Auth errors and 4xx (non-429) are *not*
fallback-eligible — they surface immediately so a misconfigured key
or a malformed request doesn't waste the fallback budget. With only
the Anthropic adapter shipped, the fallback path is dead code in
production today; B6 activates it by adding more adapters.

### 4.5 OpenAPI Surface

OpenAI-compatible (so OpenWebUI and any OpenAI-SDK-using client just works):

- `POST /v1/chat/completions`
- `POST /v1/completions`
- `POST /v1/embeddings`
- `GET /v1/models`

Plus admin endpoints under `/admin/v1`:

- `GET /admin/v1/providers/health` — per-provider health.
- `GET /admin/v1/usage` — per-key, per-model usage and cost.
- `POST /admin/v1/config/reload` — reload `gateway.yaml`.
- `GET /admin/v1/tier-config` — return current Inference Tier configuration (defaults, allowed tiers globally and per-group, warn/refuse settings). New in v0.2 (per §3.13 / §1.5.2).
- `PATCH /admin/v1/tier-config` — admin-only update to tier configuration.
- `GET /v1/inference/current-tier?provider={provider}&model={model}` — return the derived tier and a human-readable explanation; used by the application to surface the tier badge (per §3.13).
- `GET /admin/v1/anonymization-config` — return current anonymization configuration. New in v0.2 (per §4.7).
- `PATCH /admin/v1/anonymization-config` — admin-only update.

### 4.6 Implementation Plan

- ~3,000 lines of Python (anonymization adds ~600 lines; tier derivation adds ~100 lines).
- httpx for HTTP (async), tenacity for retries.
- Pydantic for config schema validation.
- pytest with provider-mock fixtures.
- Per-provider integration tests behind environment-variable-gated marks.
- Fuzzed compliance tests against the OpenAI API spec to ensure compatibility.

### 4.7 Anonymization Layer (M2)

**M2 status: SHIPPED.** The pre/post middleware runs in the Inference Gateway request pipeline as of M2-B3 and integrates with the Citation Engine per M2-D2:

* **Pre-anonymization** (`pre_anonymize_request`) substitutes detected entities with stable per-request pseudonyms (`{ENTITY_TYPE}_{NNNN}`) before the request leaves the gateway. Custom legal recognizers (`CaseNumberRecognizer`, `MatterNumberRecognizer`) layer on Presidio + spaCy `en_core_web_lg`. The retrieval-context system message is marked with `lq_ai_skip_anonymization=True` so source quotes reach the model intact for citation grounding (M2-D2).
* **Post-rehydration** (`post_anonymize_response` for unary, `StreamingRehydrator` for SSE) restores originals on the way back; the pseudonym table is held in process memory for the duration of the request and is never persisted.
* **Privileged-project handling** (M2-D3) routes through the tier-floor enforcement so privileged matters retain Tier ≥ 3 routing alongside the pseudonymization.
* **Audit-row stamp** sets `inference_routing_log.anonymization_applied = true` for every request that exercised the middleware.

Implementation at [`gateway/app/anonymization/`](../gateway/app/anonymization/) — engine, mapper, middleware, streaming rehydrator, custom recognizers; integration end-to-end via [`api/tests/test_chat_citations.py::test_chat_send_privileged_project_full_audit_trail`](../api/tests/test_chat_citations.py). Configuration surface is documented in [`docs/security/anonymization.md`](security/anonymization.md).

**Honest validation posture (per [DE-282](#de-282--anonymization-layer-empirical-validation-on-legal-document-corpus)).** The custom recognizers, middleware integration, round-trip correctness, and edge cases are exercised by ~24 unit + integration tests. The Presidio default-recognizer recall and precision **on legal-document corpus specifically** is empirically unmeasured — Presidio's published metrics target general English (news, social media), not legal prose. A miss is a silent confidentiality incident, not a visible failure mode. Operators with high-confidentiality requirements should read [`docs/security/anonymization.md` §"What's validated vs what's unvalidated"](security/anonymization.md#whats-validated-vs-whats-unvalidated) and consider Tier 1 (Ollama local) routing for matters where the unvalidated risk is unacceptable. Empirical validation on a curated legal-document corpus is welcomed as a community contribution per DE-282; the path is bounded and the contribution surface is documented.

A pre-processing step in the Inference Gateway pipeline (per the architecture diagram in §4.3): configurable patterns and an entity-recognition pass identify sensitive spans, replace them with stable pseudonyms, send the anonymized text to the model, then post-process the response to rehydrate the pseudonyms. The mapping is held only in the deployment's process memory for the duration of the request and never persists.

**Why include in v1.** Mode 2 (full local inference, Tier 1) is one answer to the data-sovereignty question; an anonymization-then-rehydrate layer for Mode 1 with Tier 3+ is the other answer, and it is what privacy-conscious enterprises that still want cloud-LLM quality reach for. Including it positions LQ.AI's Mode 1 at parity with privacy-first commercial tools without sacrificing the cloud-LLM choice. Legalfly built a defensible category position around this; the architectural placement is straightforward middleware in the Gateway.

**Functional requirements.**
- Configured per-skill, per-Project, or per-deployment via a flag (`anonymization: required | preferred | disabled`).
- Default `disabled`. When enabled, the gateway refuses to forward to non-Tier-1/2 providers if anonymization fails (fail-closed).
- Handles common entity types: persons, organizations, locations, monetary amounts, account numbers, email addresses, phone numbers. Plus regex-based custom patterns for org-specific identifiers (employee IDs, internal codes).
- Pseudonyms are stable within a single request (the same name maps to the same pseudonym across multiple occurrences) but unique across requests.
- The mapping table for a request is logged in the audit log as hash-of-pseudonym → hash-of-original; the originals are never logged.
- Rehydration on the response side restores pseudonyms inside cited chunks too, so the citation experience stays correct.
- Inspectable: users can view the anonymized prompt the model actually saw via a "view what was sent" affordance in the chat UI.

**Backend choices.**
- Default `ner_backend: spacy` — fast, offline, deterministic; occasional misses on ambiguous spans.
- `ner_backend: small_llm` — slower, more accurate; uses the Inference Gateway's `fast` model alias for the anonymization pass.
- `ner_backend: hybrid` — spaCy first, LLM fallback only on ambiguous spans; default for production.

**Architectural placement.** Between the Router and the Provider Adapters in the Gateway pipeline (per §4.3). The Gateway already has the pieces for a pre/post middleware step.

**Open questions.**
- How does anonymization interact with the Citation Engine's character-fidelity guarantee? Verbatim substring verification operates on the original text, not the anonymized text — verification happens after rehydration. Confirmed feasible.
- Should anonymization be allowed on Tier 1 (where it adds processing without privacy benefit)? Recommend: configurable but default off for Tier 1, since the entity is staying local anyway and rehydration adds an extra failure mode.

**Privilege interaction.** Per §3.11 and §1.8, Projects flagged `privileged: true` disable anonymization by default. Anonymization rehydration introduces an additional process step that complicates a privilege analysis; for privileged content, the operator is better served by Tier 1 with no third-party touch.

**Dependencies.** Inference Gateway core (§4.1–§4.6), Citation Engine (§3.3).

---

## 5. Cross-Cutting Concerns

### 5.1 Authentication and Authorization

The LQ.AI **backend (FastAPI) owns authentication**. The web client (the OpenWebUI fork) and the Word add-in are configured to delegate to the backend's auth surface rather than running OpenWebUI's built-in auth. There is one identity store, one session model, and one audit-log trail across all surfaces. (Earlier PRD drafts described "v1 uses OpenWebUI's built-in auth" — that direction was reversed during M1 planning when the OpenAPI surface and the backend's audit-log requirements made backend-owned auth the simpler architecture. The decision is recorded in `docs/adr/0002-backend-owned-auth.md`.)

**Identity and credentials.**
- Local accounts with bcrypt-hashed passwords as the v1 baseline. Email and display name on every account.
- OAuth (Google, Microsoft, GitHub), SAML 2.0, LDAP / Active Directory, SCIM 2.0, and trusted-header SSO are first-class IdP integrations. The backend implements each as a pluggable auth provider; the OpenWebUI fork does not do its own IdP integration.
- Operators with complex IdP needs front the deployment with Authentik or Keycloak via reverse proxy; the backend trusts the proxy's authenticated headers. Documented integration recipe.

**Sessions and tokens.**
- Web client (OpenWebUI fork) and Word add-in use short-lived JWT access tokens (~15 min) plus longer-lived refresh tokens (default 7 days, hashed at rest in the `user_sessions` table). Refresh tokens are rotated on each refresh.
- Programmatic clients use API tokens with scoped permissions; tokens are listable and revocable per-user.
- Every API request authenticates via `Authorization: Bearer <jwt>` in the standard FastAPI dependency.

**MFA-mandatory option** (M1): operators can configure the deployment to require multi-factor authentication for all logins. The backend implements TOTP via `pyotp` (M1) with WebAuthn as a tracked enhancement (DE-### TBD). Recovery codes are single-use, hashed at rest, and rotated when the user re-enrolls. Configuration is documented in the deployment guide as a recommended default for any deployment handling client-confidential data.

**Session timeouts** (M1): configurable absolute and idle timeouts; default 8 hours absolute, 30 minutes idle. Both are enforced in the backend; the OpenWebUI client respects them by 401-on-expired-token.

**Role-bounded admin actions audit** (M1): admin actions on the audit log itself, RBAC changes, and tier-config changes are logged with elevated detail and cannot be silently dropped.

### 5.2 RBAC

- Three default roles: **Admin**, **Member**, **Viewer**.
- Permissions on every resource: read, write, share, delete.
- Custom roles supportable via OpenWebUI's existing role system.
- All API endpoints enforce permissions via FastAPI dependency injection.

### 5.3 Audit Logging

- Every state-changing API call writes to an `audit_log` table.
- Read-only access to audit log via `/api/v1/admin/audit-log` (admin role only).
- Audit log entries: timestamp, actor_user_id, action, resource_type, resource_id, before_state_hash, after_state_hash, ip_address, user_agent, **`privilege_marked`** (boolean — set when the action affects a privilege-flagged Project per §3.11; new in v0.2), **`privilege_basis`** (free-text reference to the matter or instruction that establishes privilege; new in v0.2), **`routed_inference_tier`** (where the action involved an inference call; populated from the Gateway's tier annotation per §4 and §3.13).
- Audit log export to JSON or CSV.
- Optional log streaming to operator's SIEM via syslog or HTTP webhook.
- **Per-user data export (M1).** A user can download all their chats, files, skills, and Project content as a portable bundle via `POST /api/v1/users/{id}/export`. Includes the WorkProductAttribution metadata (per §3.3) for chain-of-custody.
- **Per-user data deletion (M1).** A user can delete their account and all associated content (chats, files, skills, autonomous-layer memory, Projects they own) via `DELETE /api/v1/users/{id}`. This is a GDPR Article 17 minimum for any deployment serving EU data subjects.
- **Tamper-evidence and cryptographic timestamping** are deferred enhancements (per §9 Security and Compliance), not v1 commitments. The v1 audit log relies on the operator's database integrity; tamper-evidence layers come later.

### 5.4 Observability

- OpenTelemetry instrumentation in every service.
- Default OTel exporter: OTLP/HTTP. Operator points it at their backend (Grafana Tempo, Honeycomb, etc.).
- Langfuse self-hosted alongside the deployment for LLM-specific tracing (optional, off by default).
- `/health` and `/ready` endpoints on every service.
- Prometheus-format metrics on `/metrics`.

### 5.5 Cost Tracking

- Inference Gateway tags every request with the originating user, capability, and chat (when applicable).
- Cost per request computed from configured per-model rates.
- Aggregations exposed via `/api/v1/admin/usage` with filters (user, date range, capability).
- Operator-facing cost dashboard in the admin UI.

### 5.6 Encryption

- TLS in transit (operator provides certificates; documented Let's Encrypt recipe via Caddy or Traefik reverse proxy).
- At rest: pgcrypto-backed column encryption for sensitive fields (API keys, audit log payload).
- Storage volumes encrypted at the operator's infrastructure level (their responsibility).
- **HSM and external-secrets-manager integration** (HashiCorp Vault, AWS Secrets Manager, Azure Key Vault, Google Secret Manager) is a deferred enhancement (per §9 Security and Compliance). v1's pgcrypto column encryption is sufficient for most operators; high-assurance deployments will want pluggable secrets backends, which the v1 architecture leaves room for.

### 5.7 No Telemetry by Default

- The deployment emits no telemetry to LegalQuants or any third party by default.
- Optional opt-in anonymous usage stats (version, deployment mode, capability counts; no content) via a clearly-disclosed flag.
- Documented in privacy.md.

### 5.8 Testing and Quality Engineering

The Cross-Milestone Workstreams entry in §8 commits to "Pytest coverage target 80%, integration tests for every API endpoint, end-to-end tests for happy paths in every capability, fuzzing for the Inference Gateway's OpenAI compatibility." This section extends that commitment into the engineering-discipline practices that distinguish a maintainable production codebase from a working prototype. Many items below are deferred to later milestones; each has an explicit status marker so the M1 reader can tell what is running today and what is on the roadmap. The deferred-enhancement entries in §9 (Engineering Discipline subsection) are the unit of contributor pickup.

**Coverage gates enforced as CI merge gates.** The target is 80% pytest coverage on the `api/` package and 90% on the `gateway/` package — the gateway's position in the trust path justifies the higher floor. Coverage is reported per-package and per-file in CI artifacts; the `coverage.xml` is uploaded to Codecov (or equivalent) for trend visibility across PRs. **Status: M1 partial — the test suites exist (70 backend pytest files; 27 gateway pytest files; 53 vitest specs; 10 Cypress specs per `docs/HONEST-STATE.md` §6) but `.github/workflows/ci.yml` does not yet fail builds below threshold. The CI gate is on the engineering-discipline roadmap (see §9, Engineering Discipline subsection).**

**Property-based testing for invariants.** The Citation Engine, the Anonymization Layer, and the Inference Gateway router are the three components whose invariants are load-bearing for the product's correctness and security story. Property-based testing with Hypothesis expresses those invariants as properties tested across generated inputs: every claim emitted by the Citation Engine resolves to a verbatim quote in the cited chunk; every entity anonymized on the request path is rehydrated on the response path; every tier-routing decision is consistent with the operator's tier policy; no fallback path can promote a request above its allowed tier. Properties find the edge cases example-based tests miss. **Status: deferred (see §9 DE entry — Property-based testing). The architectural slots for the Citation Engine and Anonymization Layer are not yet wired (§3.3 M1 status; §4.7 M1 status); property tests land alongside the pipelines they exercise.**

**Mutation testing with per-release scores published.** Mutation testing (mutmut for Python, Stryker for the TypeScript portions of the OpenWebUI fork) runs nightly against the critical-path packages and reports the mutation score per release. Mutation testing is the answer to the criticism that high coverage numbers can be achieved without meaningful assertions; a mutation-tested suite proves that the tests catch real defects, not just that the lines are executed. The mutation score is published per release in the security advisory feed and rendered as a badge alongside the OpenSSF Scorecard. **Status: deferred (see §9 DE entry — Mutation testing). M1 ships unit and integration tests; mutation testing lands on the roadmap.**

**Snapshot / golden testing for skill outputs across the documented model matrix.** Every built-in skill ships with a held-out test corpus of input documents and structural-output golden snapshots (not exact wording, which varies with model and seed). The skill execution test runs against the documented multi-model matrix (Anthropic Claude latest two majors; OpenAI GPT latest two majors; one open-weight reference local model) and compares structural output to the snapshots with a documented similarity threshold — JSON-schema validity for tabular skills, section presence and ordering for report skills, issue count and category coverage for review skills. A drop below threshold on a model upgrade blocks release and files an issue. **Status: M1 partial — each starter skill ships with a `test-plan.md` in `skills/<skill>/test-plan.md`, but the harness that executes the plans is deferred (see `docs/HONEST-STATE.md` §6 and the mini-PRD at `docs/contribute/mini-prds/skill-acceptance-tests.md`).**

**Performance regression with historical tracking.** Latency benchmarks (p50, p95, p99) for the conversational core, the Citation Engine, the Inference Gateway routing decision, and skill execution run per PR; results are committed to a benchmark history; regressions of more than a documented threshold are merge-blocked. Memory profiling runs nightly with leak detection. This catches the class of defects where a refactor functionally works but materially regresses production behavior — the class of defects that erodes operator trust over time. **Status: deferred (see §9 DE entry — Performance regression tracking). M1 ships OpenTelemetry instrumentation (§5.4) that supports operator-side measurement; project-side benchmark tracking is on the roadmap.**

**Chaos and fault injection for the gateway and document pipeline.** The Inference Gateway is tested with provider-fault injection: provider returns 500; provider returns 429; provider hangs; provider returns malformed JSON; provider returns partial response. The tests assert that fallback behavior is correct, that the audit log records the fault accurately, that the operator's tier policy is preserved (no silent tier upgrade on fallback), and that cost accounting is consistent. The Document Pipeline is tested against a corpus of malformed documents (truncated PDFs, malformed DOCX, PDFs with embedded JavaScript, documents with unicode-direction-override attacks). **Status: deferred for the gateway-and-pipeline fault matrix as a structured suite (see §9 DE entry — Chaos and fault injection). The gateway's provider adapters have unit-level error-path tests today in `gateway/tests/`; a structured fault-injection suite is on the roadmap.**

**Contract testing between services.** The boundary between `web/` (OpenWebUI fork), `api/` (FastAPI backend), `gateway/` (Inference Gateway), and the Word add-in (M3) is tested with consumer-driven contract tests (Pact or equivalent), versioned and committed to source. A breaking change at any of these boundaries is caught at PR time rather than at deployment time. This is especially important given the OpenWebUI fork relationship: contract tests ensure that an upstream OpenWebUI change cannot silently break a backend assumption. **Status: M1 partial — the OpenAPI 3.1 schema at `docs/api/backend-openapi.yaml` and `docs/api/gateway-openapi.yaml` is the source of truth and is verified against handler signatures by OpenAPI conformance tests in `api/tests/` and `gateway/tests/`. Consumer-driven contract testing (Pact) is on the roadmap — see §9 DE entry.**

**Visual regression and accessibility testing.** The web UI ships with Playwright visual regression tests on a documented browser matrix and with axe-core accessibility tests enforcing WCAG 2.1 AA compliance as a merge gate. Accessibility is increasingly a procurement requirement in legal and regulated industries; shipping with verifiable WCAG 2.1 AA from M1 closes that objection. The accessibility audit report is published per release. **Status: M1 partial — design targets WCAG 2.1 AA per README; CI enforcement via axe-core merge gate is deferred (see §9 DE entry — WCAG 2.1 AA accessibility audit and CI gate, and `docs/HONEST-STATE.md` §6).**

**Fuzz testing extended to document parsers and anonymization paths.** The Inference Gateway's OpenAI-compatibility surface is fuzzed at PR time. The Document Pipeline parsers are additionally fuzzed nightly against malformed-document corpora (libFuzzer-style harnesses for Docling input, PyMuPDF input, and OCR API response handling). The Anonymization Layer's regex and NER paths are fuzzed for ReDoS and adversarial-tokenization inputs. **Status: M1 partial — fuzzing of the OpenAI-compatibility surface is committed in the Cross-Milestone Workstreams. Document-parser fuzzing and anonymization-path fuzzing are deferred (see §9 DE entry — Fuzz testing extended).**

**Adversarial-AI testing as a release gate.** A documented adversarial test suite runs per release against the inference path: prompt injection from a malicious counterparty document (covering the published Garak, PyRIT, and MITRE ATLAS attack corpora); jailbreak attempts targeting Tier 1 local-inference profiles; PII extraction attempts against the Anonymization Layer; citation-hallucination attempts (asking the model to cite a document that does not exist). Detection rates and mitigation effectiveness are published per release per skill. This is the AI-product-specific analog of a security regression suite — see also DE-110 (Prompt-injection pattern library) and the §9 DE entries for prompt-injection detection rates and PII leakage testing. **Status: deferred. The honest answer is that no public detection rates are measured for the M1 release; the path to shipping is in `docs/HONEST-STATE.md` §6.**

### 5.9 Reliability and Operations

PRD §5.4 commits to observability and §5.3 to audit logging. This section adds the reliability-engineering commitments operators of regulated production systems expect. As with §5.8, many items are deferred to later milestones; each has an explicit status marker. The deferred-enhancement entries in §9 are the unit of contributor pickup.

**Published Service Level Objectives and Indicators.** The project publishes recommended SLOs and the corresponding SLIs for a reference deployment, with documented measurement methodology. The SLO set covers: API availability (target 99.9% monthly); p99 latency by capability (documented per capability in §3); inference-fallback success rate; audit-log durability (target zero loss). For each SLO, the SLI calculation is documented and the OpenTelemetry metrics that feed it (per §5.4) are named explicitly. Operators can use the published SLOs as starting points and tune to their own risk appetite. **Status: deferred (see §9 DE entry — Published SLOs / SLIs). OpenTelemetry instrumentation ships at M1; the SLO catalog is on the roadmap.**

**Error budget policy.** A documented error budget policy describes how the project handles SLO breaches in releases: a budget breach triggers a release freeze on non-critical changes until the budget recovers. The policy is illustrative for operators who want to adopt the same discipline internally and operative for any future LegalQuants-managed-service offering. **Status: deferred (see §9 DE entry — Error budget policy). Conditional on the SLO catalog above.**

**Public postmortems within 14 days.** Incidents in any LegalQuants-operated infrastructure (the project's hosted demo, the GitHub-issued artifacts, the LegalQuants-managed-service offering once it exists) are postmortem'd publicly within 14 days, in a documented template (timeline, root cause, contributing factors, remediation, action items, lessons learned). This is the discipline mature OSS projects (PostgreSQL, Kubernetes) and mature SaaS vendors (Stripe, Cloudflare) follow; publishing postmortems is a credibility multiplier. For self-hosted operator deployments, incident response is the operator's responsibility — the project supports the operator's investigation through the disclosure channel in `SECURITY.md` and through the audit log and OpenTelemetry traces (§5.3 and §5.4). **Status: deferred (see §9 DE entry — Public postmortems). No incidents in LegalQuants-operated infrastructure have occurred yet because no LegalQuants-operated infrastructure has been published; the template and the publication commitment land alongside the first hosted artifact.**

**Disaster recovery test cadence.** The reference deployment recipes ship with a documented DR procedure (backup restore, secret rotation, key rotation, failover to a secondary region). The procedure is exercised quarterly against a clean test environment by the LegalQuants-managed-service operations function (when that function exists), with the test report published. The DR procedure is operator-runnable for any self-hosted deployment. **Status: deferred (see §9 DE entry — Disaster recovery test cadence). The Docker Compose deployment is documented at M1; the Helm chart is drafted (see `deploy/helm/` per `docs/HONEST-STATE.md` §7); a tested DR procedure is on the roadmap.**

**Runbooks for every operational task.** Every operational task an operator might perform (deploying, upgrading, rotating credentials, responding to a security advisory, recovering from a corrupted vector index, migrating to a different inference provider, ingesting a backlog of documents) ships with a runbook in `docs/runbooks/`. Runbooks include estimated time, prerequisites, the exact commands, success-verification steps, and rollback procedure. This is the operational-maturity signal that lets a procurement security team check the box on "the vendor has documented operational procedures" — for an OSS project, the runbooks are the evidence. **Status: deferred. `ls docs/` shows no `runbooks/` directory at M1; the directory and the first runbooks are on the engineering-discipline roadmap (see §9 DE entry — Runbooks for operational tasks).**

**Public status page for hosted artifacts.** When LegalQuants ships hosted artifacts (the project's hosted demo, the docs site, the container registry, the managed-service offering), each is tracked on a public status page with documented severity definitions and incident-response procedures. **Status: deferred. No hosted artifacts published yet at M1 — the project ships as software the operator runs; the status page lands with the first hosted artifact.**

---

## 6. Deployment

### 6.1 Reference Docker Compose

Single `docker-compose.yml` with profiles for the two modes.

```yaml
# docker-compose.yml (excerpt)
services:
  web:
    image: legalquants/lq-ai-web:latest
    ports: ["3000:3000"]
    depends_on: [api]
    environment:
      LQ_AI_API_URL: http://api:8000

  api:
    image: legalquants/lq-ai-api:latest
    ports: ["8000:8000"]
    depends_on: [postgres, redis, gateway]
    env_file: .env

  gateway:
    image: legalquants/lq-ai-gateway:latest
    ports: ["8001:8001"]
    volumes: ["./gateway.yaml:/etc/gateway.yaml:ro"]
    env_file: .env

  postgres:
    image: pgvector/pgvector:pg16
    volumes: ["pgdata:/var/lib/postgresql/data"]
    env_file: .env.db

  redis:
    image: redis:7-alpine
    volumes: ["redisdata:/data"]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    volumes: ["miniodata:/data"]
    env_file: .env.minio

  # --- Mode 2 (local inference) profile ---
  ollama:
    image: ollama/ollama:latest
    profiles: ["local"]
    volumes: ["ollamadata:/root/.ollama"]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  paddleocr:
    image: legalquants/paddleocr-vl:latest
    profiles: ["local"]

  # --- Slack / Teams Light Intake Bridge (M3); optional, off by default ---
  slack-bridge:
    image: legalquants/lq-ai-slack-bridge:latest
    profiles: ["slack"]
    depends_on: [api]
    env_file: .env.slack
    # Configure Slack OAuth in the LQ.AI admin UI; this service exposes
    # only the Slack Events API endpoint for bot interactions.

  teams-bridge:
    image: legalquants/lq-ai-teams-bridge:latest
    profiles: ["teams"]
    depends_on: [api]
    env_file: .env.teams
    # Configure Microsoft Teams app in the LQ.AI admin UI.

volumes:
  pgdata:
  redisdata:
  miniodata:
  ollamadata:
```

### 6.2 First-Run Experience

```bash
git clone https://github.com/legalquants/lq-ai.git
cd lq-ai
cp .env.example .env
# Edit .env with at least one LLM provider API key (or use local profile)
docker compose up -d              # Mode 1
# OR
docker compose --profile local up -d   # Mode 2
```

After ~2 minutes (first run pulls images, runs migrations, seeds skills):

```
✓ LQ.AI is ready at http://localhost:3000
✓ First-run admin account: see logs for password
✓ API documentation: http://localhost:8000/docs
✓ Inference Gateway: http://localhost:8001/docs

Next steps shown in the web UI:
1. Create your Organization Profile (§3.12) — your team's voice, templates,
   and "what good looks like." Or skip and create later.
2. Configure Inference Tier policy (§3.13) — which tiers are allowed for
   your deployment; what is the minimum for privileged work.
3. Optionally enable MFA (§5.1) and review session timeout settings.
4. Create your first Project (§3.11) and try the starter skills.
```

### 6.3 Production Deployment

- **Helm chart** for Kubernetes: `helm install lq-ai legalquants/lq-ai -f values.yaml`.
- **Reverse proxy recipes**: Caddy (simplest, automatic TLS), Traefik (production-grade), nginx.
- **Reference architectures** documented: small (single-node Docker), medium (single-node K8s with HA Postgres), large (multi-node K8s with horizontal API scale, external Postgres).

### 6.4 Air-Gapped Deployment

- All container images can be mirrored to a private registry.
- Models pulled to Ollama once, then deployment runs without internet.
- No outbound calls in Mode 2 (verified by integration test).
- Documented air-gap install guide.
- **Tier 1 framing.** An air-gapped deployment is the canonical Tier 1 deployment per §1.5.2 and §3.13. The Inference Tier badge in the chat UI shows "Tier 1 — local inference (air-gapped)" for every chat in this configuration. Skills that declare `minimum_inference_tier` are unaffected; air-gap is the most restrictive operational posture and satisfies any minimum tier requirement.

### 6.5 Backup and Restore

- Documented `pg_dump` + MinIO snapshot recipe.
- Reference cron job for nightly backups.
- Restore tested in CI.
- **Backup encryption** is a deferred enhancement (per §9 Security and Compliance): backup bundles are unencrypted by default in v1; operators are responsible for encrypting backup volumes at rest at the infrastructure level. A configurable backup-encryption-with-rotation path is on the roadmap.

---

## 7. Open Source Posture

### 7.1 Project Philosophy

LQ.AI is open source because the alternative — closed-source legal AI built on hidden prompt engineering — does not deserve the trust of the legal profession. Lawyers are licensed because their judgment is accountable to clients, courts, regulators, and ethics boards. The tools that shape that judgment should be accountable in kind. A skill that produces a wrong answer should be readable, debuggable, and forkable by the lawyer who relies on it. A playbook that codifies a position should be inspectable by the team that signed off on it. A citation engine that asserts verbatim quotes should be auditable by anyone who cares to check.

Open source is therefore not a distribution choice. It is a fitness-for-purpose requirement. A closed-source legal AI is structurally unsuited to the work it claims to do, in the same way that a black-box statute would be unsuited to law. We did not build LQ.AI as an open-source project as a marketing posture; we built it open because we could not see how to do this work honestly any other way.

This philosophy carries operational consequences worth naming explicitly:

- **Substantive contributions are welcome and credited.** Skills, playbooks, jurisdictional adaptations, and verification heuristics contributed by practicing lawyers carry the same weight in the project as code contributed by engineers. Both are work product. Both deserve attribution.
- **No "open core" gating.** Features useful to legal teams are in the open-source release. We will not move features behind a paid offering as the project matures. (LegalQuants may build commercial *services* — hosted deployments, custom skill authoring, training, support — but the software itself stays whole.)
- **Forks are encouraged, not resisted.** If a customer or a community wants to build a derivative product that incorporates their proprietary improvements, the Apache 2.0 license permits it. We treat that as ecosystem health, not competition.
- **Skills are the canonical artifact of value.** When the project produces a wrong answer, the answer to "why" is almost always in a SKILL.md. Improving LQ.AI is mostly improving skills, which is mostly within reach of any practicing lawyer with a few hours and a clear view of what the right answer should have been.

### 7.2 License

**Apache License 2.0** for the LQ.AI codebase.

Rationale: patent-grant clause (important given LegalQuants' ecosystem), explicit trademark protection, enterprise-friendly, compatible with most other OSS licenses for ecosystem integration.

OpenWebUI fork (the `web` component) inherits OpenWebUI's license. We follow OpenWebUI's branding requirements and document the relationship in the README.

PyMuPDF (AGPL) is used server-side only and not redistributed as a library; the AGPL boundary is the HTTP API. Documented.

### 7.3 Trademark and Naming

- **LQ.AI** is the project name, descriptive enough that strong trademark protection is unlikely.
- **LegalQuants** is the protectable mark; remains LegalQuants' property.
- Tagline: *"LQ.AI — open-source AI for legal teams, by LegalQuants."*

### 7.4 Governance

- **Initial model: BDFL.** Kevin Keller is the initial maintainer.
- LegalQuants stewards the project (owns the GitHub org, controls trademark, employs maintainer).
- Documented commitment to community contribution: "LQ.AI welcomes contributions from any lawyer, legal-ops practitioner, or engineer who wants to advance open legal AI."
- Path to broader governance documented but not implemented in v1: as the project matures, consider transition to a maintainer team and formal governance (see CNCF or Apache Software Foundation models).

### 7.5 Contribution Model

- **DCO sign-off**, not CLA. Industry-standard, lightweight, sufficient legal cover.
- `CONTRIBUTING.md` documents:
  - How to set up a development environment.
  - How to run tests.
  - PR process and expectations.
  - Code style (ruff + mypy for Python; Prettier + ESLint for JS).
  - Commit message conventions.
  - Sign-off requirement.
- `CODE_OF_CONDUCT.md` based on the Contributor Covenant.

### 7.6 Security Disclosure

- `SECURITY.md` documents:
  - Email address for security reports (security@legalquants.com or similar).
  - GPG key for encrypted disclosures.
  - Response time commitments (acknowledge within 72h, fix critical issues within 30d).
  - Public disclosure policy after fix.
  - **Explicit scope** — what is in-scope versus out-of-scope for security reports (added in v0.2).
  - **Safe-harbor language** — clear good-faith research protections for reporters (added in v0.2).
  - **Published list of past disclosures** with credit attribution to reporters (added in v0.2).
- GitHub Security Advisories used for coordinated disclosure.
- A formal Vulnerability Disclosure Program (VDP) on a recognized platform (HackerOne, Intigriti, or self-hosted) is a deferred enhancement (per §9 Security and Compliance).

### 7.7 Project Channels

- **GitHub Issues** for bugs and feature requests.
- **GitHub Discussions** for community Q&A.
- **Discord** (LegalQuants-hosted) for synchronous community.
- **Blog** at legalquants.com/blog for releases and roadmap updates.

### 7.8 Release Cadence and Supply-Chain Transparency

- Semantic versioning (semver).
- Releases tagged on GitHub with full changelog.
- Targeted cadence: minor release every 6–8 weeks, patch releases as needed.
- Long-term-support (LTS) designation for one minor version per year, with security backports for 12 months.

**Supply-chain transparency commitments (M1, per §1.8 and Appendix E).**

Every release ships with the following artifacts, which an operator's security team can verify before deployment:

- **Software Bill of Materials (SBOM).** Every release container image and Python wheel is accompanied by an SPDX or CycloneDX SBOM, generated automatically by Syft or equivalent and published as a release artifact. Documented at `docs/security/sbom.md`.
- **Signed container images.** Container images are signed with Sigstore/cosign; release tags are GPG-signed; signing keys and verification commands are documented at `docs/security/verifying-releases.md`.
- **SLSA-3 build provenance.** GitHub Actions workflows produce SLSA-3-aligned provenance attestations for each release, linking each image to the specific GitHub commit and Actions run that produced it. Documented at `docs/security/build-provenance.md`.
- **Public threat model.** A `docs/security/threat-model.md` document covering principal data flows: a user prompt → backend → inference gateway → provider → response → citation render. Identifies trust boundaries, threats, and mitigations. Reviewed annually; updated when major architecture changes land.
- **Continuous dependency security.** Trivy / Grype scan every container image; Dependabot or Renovate watches all dependency manifests; CodeQL or similar SAST runs on every PR; results are visible in GitHub Security tab. Documented at `docs/security/dependency-security.md`.
- **Reproducible builds.** A v1.x deferred enhancement (see §9 Security and Compliance); the v1 commitment is the SLSA-3 provenance, with reproducibility as a follow-on hardening step.

These commitments collectively answer the procurement objection "but it's open source — how do we know what's in it?" Closed-source vendors typically cannot provide SBOMs for their internal builds because their dependency surface is opaque; an open-source project's supply-chain story is structurally stronger.

---

## 8. Roadmap

Milestone-based delivery. Each milestone is a public release.

### M1 — Foundation (~6 weeks)

**Theme:** Working open-source release that operators can deploy and use for everyday legal Q&A, with the matter-context substrate (Projects + Organization Profile) and procurement-defense apparatus that distinguish LQ.AI from a generic OSS chat-with-skills product.

**Deliverables:**
- OpenWebUI fork with LQ.AI customization (logo, colors, default skills loaded).
- FastAPI backend with full OpenAPI 3.1 surface.
- Inference Gateway (cloud + Ollama, fallback, rate limiting, cost tracking).
- **Inference Tier derivation in the Gateway and Tier Awareness UI** (per §3.13 and §1.5.2). Tier badge in chat header and Word task pane; Skills/Projects can require minimum tiers; deployment can disallow tiers globally.
- RBAC with three default roles.
- **MFA-mandatory option and session-timeout defaults** documented (per §5.1).
- Files / Knowledge Bases.
- Hybrid retrieval (pgvector + FTS).
- Chat with persistent history.
- **Projects** as matter-scoped containers (per §3.11), including the optional `privileged` flag and `minimum_inference_tier` field.
- **Organization Profile** as a singleton skill (per §3.12); first-run onboarding prompts the operator to create or skip.
- **Privilege-aware audit log fields** (`privilege_marked`, `privilege_basis`, `routed_inference_tier`) per §5.3.
- **Per-user data export and deletion** (`POST /api/v1/users/{id}/export`, `DELETE /api/v1/users/{id}`) per §5.3 — GDPR Article 17 baseline.
- **Work-product attribution metadata** on every model-generated artifact (per §3.3).
- Enhance Prompt.
- Skill Library framework (with `lq_ai:` namespace including `minimum_inference_tier`, `output_format`, `is_organization_profile`).
- 10 starter skills (drafted in parallel; see skill list below).
- Docker Compose deployment for both modes.
- Quickstart, configuration, and contribution documentation.
- Apache 2.0 license, CONTRIBUTING.md, SECURITY.md (with safe-harbor language and explicit scope, per §7.6), CODE_OF_CONDUCT.md.

**Compliance Alignment Pack documentation deliverables (M1, per §1.8 and Appendix E).** The following documents ship in `docs/compliance/` with the M1 release; they are documentation deliverables, not code:

- `docs/compliance/soc2-alignment.md` — SOC 2 Type II Trust Services Criteria mapped to LQ.AI design choices, identifying project-provided / operator-provided / joint controls (Customer Responsibility Matrix style).
- `docs/compliance/iso-27001-alignment.md` — ISO 27001 Annex A controls mapped to LQ.AI design choices.
- `docs/compliance/iso-42001-alignment.md` — ISO 42001 (AI management system) controls mapped to LQ.AI design (competitive parity with Legora and Legalfly).
- `docs/compliance/gdpr-readiness.md` — Article-by-article readiness analysis (Articles 6, 25, 28, 30, 32, 35, 15–22).
- `docs/compliance/hipaa-readiness.md` — Walks the operator through deploying LQ.AI in a HIPAA-eligible configuration: BAA with the inference provider, Tier 1–3 only, Citation Engine PHI handling, audit logging guidance.
- `docs/compliance/provider-compliance-matrix.md` — Per-provider table of compliance facts (ZDR availability, training-on-data policy, retention windows, certifications, data residency, government cloud). Updated each release. *This is the document users see when they click the tier badge in the UI.*

**Code & Supply-Chain Transparency deliverables (M1, per §7.8 and §1.8).** Documented above in §7.8: SBOM in CI, signed container images, SLSA-3 build provenance, public threat model, dependency security scanning.

**Not in M1, despite earlier drafts:** the MCP-client subsystem architectural slot. Originally targeted for M1; moved to M2 during M1 planning. M2 is the natural landing spot — it overlaps with the Citation Engine and Anonymization Layer work, which is when the gateway/backend extensibility surfaces are already being shaped.

**Starter skills shipped in M1:**
1. NDA Review (mutual + unilateral variants)
2. MSA Review — SaaS
3. MSA Review — Commercial Purchase
4. DPA Checklist Review
5. Vendor Privacy Policy First Pass
6. Contract QA
7. Action Items from Client Alert
8. Comms Improver (plain-language rewriter)
9. Enhance Prompt (the prompt-rewriter)
10. Skill Creator (meta-skill for building skills via conversation)

**MCP-client subsystem (architectural slot, M2).** A pluggable MCP-client module lands in the FastAPI backend in M2 — even though no MCP servers ship and no connectors land in M1–M4. The cost is ~2 weeks of architectural work and documentation; the value is that the M5+ Forward-Looking Roadmap (§8.5) does not require retrofitting MCP into a v1 architecture that did not anticipate it. **Originally targeted for M1; deferred to M2 during M1 planning** — M1 is already fully scoped at ~210 hours with the things that ship in the quickstart, and the architectural slot is small enough that landing it during M2 alongside the Citation Engine work creates no retrofit risk. Per §8.5 / I.5.

**Acceptance criteria:** A new operator can `docker compose up`, sign in, optionally create an Organization Profile and a Project, attach the NDA Review skill, upload an NDA, get a useful review with citations to the right tier-aware provider, and search prior chats — all within 15 minutes of starting from `git clone`.

### M2 — Citation Engine and Anonymization (~6 weeks after M1)

**Theme:** Verifiable citations with character-level fidelity, plus the privacy fallback for cloud-LLM use.

**Deliverables:**
- Document Pipeline (Docling + PyMuPDF + Mistral OCR / PaddleOCR-VL).
- Citable Chunk schema and storage.
- Citation Engine: structured generation, deterministic verification, LLM-judge verification.
- Side-panel PDF.js viewer with bbox highlighting.
- Skill Creator UI (graphical wizard built on the Skill Creator skill from M1).
- Skill chaining UI.
- Skill self-improvement instructions.
- Research feature (web search + legal source connectors: CourtListener, GovInfo, Federal Register, EUR-Lex, SEC EDGAR).
- Multi-Model Ensemble Verification (configurable, off by default except for Citation Engine verification).
- **Anonymization Layer** in the Inference Gateway (per §4.7). Hybrid spaCy + small-LLM NER backend; configurable entity types and custom regex patterns; rehydration in responses and citations; fail-closed when required and tier > 2.
- **MCP-client subsystem (architectural slot).** Pluggable MCP-client module in the FastAPI backend; no MCP servers ship and no connectors land in M2–M4. The slot exists so the M5+ Forward-Looking Roadmap (§8.5) can extend without retrofitting. Originally targeted for M1; deferred to M2 during M1 planning to keep the M1 scope focused on what ships in the quickstart.

### M3 — Playbooks, Word Add-In, Tabular Review, and Slack/Teams (~8 weeks after M2)

**Theme:** Feature parity with commercial legal AI; surface coverage beyond the web.

**Deliverables:**
- Playbook schema and execution engine (LangGraph workflow).
- Easy Playbook auto-generation wizard.
- 4 built-in playbooks: Generic SaaS MSA, NDA, DPA (GDPR-aligned), Commercial MSA.
- Playbook execution UI in web app.
- Word Add-In (Office.js):
  - Chat against the open document
  - Apply skills to selection or whole document
  - Execute Playbooks against the document
  - Generate redlines as Word tracked changes
  - Generate comments as Word comments
  - **Inference Tier badge** in the task pane (per §3.13).
- Enterprise sideload distribution package for the add-in.
- **Tabular / Multi-Document Review** (per §3.14). New `output_format: table` skill mode; tabular UI surface; bulk operations; XLSX/CSV export; cost preview before execution.
- **Slack / Teams Light Intake Bridge** (per §3.15). OAuth install on Slack and Teams; `/lq` slash command (forward-as-chat) and `/lq ask` quick-skill flows; bot configuration in LQ.AI admin UI.

### M4 — Autonomous Layer and Contract Repository (~8 weeks after M3)

**Theme:** Beyond GC.AI; the analytical layer maturing into temporal and relational awareness.

**Deliverables:**
- OpenWebUI Pipelines integration for background agents.
- Per-user persistent memory store with user-curation UI.
- Cron-scheduled tasks.
- Watch mechanism (trigger on KB changes, document arrivals, calendar events).
- Autonomous skill suggestion ("you've reviewed five SaaS DPAs; want a custom DPA Playbook?").
- Notification system (email, Slack, in-app).
- **Contract Repository — Auto-Relationship Detection** (per §3.16). Pipeline produces relationship graph (amendments, restatements, references, master/sub) over a Knowledge Base; user-confirmable edges; operative-document-chain reasoning when answering scoped questions.
- **M5+ readiness.** M4 design explicitly accommodates multi-step agents that take external-side-effecting actions with human approval gates, since the M5+ Workflow Intelligence direction (§8.5) extends this substrate.

**After M4:** community-driven roadmap. The M5+ Forward-Looking Roadmap below names the trajectory.

### M5–M7 — Forward-Looking Workflow Intelligence (community-driven; not committed) {#section-8.5}

> **Status: forward-looking.** This section names the project's longer-term ambition. It is not a v1–v4 commitment. The maintainer team's bandwidth is the M1–M4 critical path; M5+ is the right scope for a maturing community to contribute to, with the maintainer team coordinating direction. The architectural slots needed to support M5+ (the MCP-client subsystem; the autonomous-layer extensibility) are committed in M1–M4 so that this work is community-extensible rather than requiring core refactoring.

The M5+ direction extends LQ.AI from a tool the user reaches for into a workflow-aware context layer. The core capability sketch: signal aggregation across email, calendar, task systems, and document stores; a Workspace Concierge that produces a ranked Today view with rationales; agent dispatch with human-in-the-loop guardrails; voice and ambient modes. Privacy and security implications are dominant — most of M5+ benefits from Tier 1 / Tier 2 inference and the Anonymization Layer; granular consent per signal source and per scope is a hard requirement. The full sketch is captured in §9 (Workflow Intelligence subsection).

**M5 — Workflow Intelligence Foundation (~10 weeks after M4).**
- MCP-client subsystem operationalized; Signal Aggregation Service skeleton.
- Read-only connectors via MCP for: Gmail / Outlook / IMAP email; Google Calendar / Outlook Calendar; one task system (Linear or Asana, community-driven choice).
- Today view (basic): chronologically-ordered list of pending items from connected sources; no prioritization yet.
- Email Triage Skill: reads incoming, classifies (legal-relevant / not), proposes folder routing or task creation. No auto-actions; user approves.
- Calendar Prep Skill: each morning, surfaces upcoming meetings with relevant Project context.

**M6 — Workflow Intelligence Active (~10 weeks after M5).**
- Prioritization Engine (LangGraph workflow with rule + LLM + autonomous-memory hybrid scoring; the engine itself is an inspectable skill).
- Today view advanced: ranked priorities with rationales; groupings; one-click actions.
- Agent Execution Framework: multi-step background agents with approval gates; agent run history; intervention UI.
- Email Triage Agent (background mode with hourly digests).
- Negotiation Tracker Agent.
- Voice mode for the Today view.

**M7 — Workflow Intelligence Mature (community-driven post-M6).**
- Cross-matter pattern recognition and proactive skill suggestion.
- Counterparty intelligence (aggregate prior interactions across emails, contracts, calls).
- Negotiation-state tracking as a first-class entity (drafting → out-for-review → counter-received → in-progress → executed → terminated).
- Personal decision history view ("you decided X about counterparty Y last June; the same question is being asked now").
- Time-blocked work mode ("you have 90 minutes open at 2 PM; tackle these three items?").
- Async team handoff briefs (one-click "prepare a coverage brief for my deputy while I'm OOO").

**Boundary with Tucuxi proprietary work.** This M5+ direction overlaps conceptually with Kevin's Tucuxi research (Director RNN, Cognitive Compilation Engine, RSH framework, Wisdom Database / GUD). Per §1.6, Tucuxi internals are excluded from the OSS release; the M5+ descriptions deliberately use prosaic OSS-implementable techniques (LLM-based scoring, LangGraph workflows, simple ML for pattern detection) so the OSS version stands fully on its own. Tucuxi-flavored implementations of the same capabilities can layer on for the proprietary product without affecting the OSS implementation.

### Cross-Milestone Workstreams

These run in parallel with all milestones:

- **Documentation.** Every release ships with documentation parity. Quickstart, configuration reference, capability guides, skill-authoring guide, playbook-authoring guide, deployment recipes, troubleshooting, FAQ.
- **Testing.** Pytest coverage target 80%, integration tests for every API endpoint, end-to-end tests for happy paths in every capability, fuzzing for the Inference Gateway's OpenAI compatibility.
- **CI/CD.** GitHub Actions for testing, linting, container builds, multi-arch (amd64 + arm64), nightly integration tests, automated releases.
- **Community.** Triage GitHub issues weekly, monthly community call, blog posts at each milestone release.

---

## 9. Deferred Enhancements and Identified Future Work

This section captures features, refinements, and enhancements that have been identified during PRD authoring and skill drafting but were intentionally deferred from the v1 release in order to ship a focused MVP. Each entry is structured for community pickup: a contributor can read an entry, understand the scope, and propose an implementation without recovering the original context.

The intent is twofold. First, future maintainers (including ourselves at v1.5 or v2) have a record of what was deliberately scoped out and why. Second, community contributors have a pre-populated backlog of meaningful work — these are not "good first issues" in the trivial sense, but they are well-defined enhancements where the architectural slot exists and the implementation is bounded.

Entries are tagged with priority (P1 = should be addressed in v1.5; P2 = good for community contribution any time; P3 = nice-to-have, may never happen) and effort estimate (S = days; M = weeks; L = months).

### Skill ecosystem expansions

#### DE-001 — Additional starter skills beyond the M1 set

**Priority:** P1 · **Effort:** M (one skill at a time)

**Context:** M1 ships with 10 starter skills. Many other recurring in-house legal workflows would benefit from purpose-built skills.

**Specific candidates identified during skill authoring:**
- **Board Minutes Generator** — produced as the example skill in `skill-creator/examples/example_session.md`; could be shipped as an actual skill given the example is essentially a complete v1.0.0.
- **HIPAA BAA Review** as a separate skill from DPA Checklist Review's HIPAA mode (some users prefer single-purpose skills).
- **Multi-state US Privacy DPA Review** — a harmonized multi-state skill versus the single-regime selection in DPA Checklist Review.
- **Settlement Agreement Review.**
- **Employment Offer Letter Review** (in-house counsel reviewing for the company).
- **SOC 2 / Audit Response Drafter.**
- **Regulatory Filing Drafter** (state-by-state corporate filings).
- **Patent License Review.**
- **Trademark License Review.**
- **Open Source License Compatibility Checker** (which OSS licenses can coexist in this project given dependencies?).

**Acceptance criteria:** Each candidate skill follows the established skill format, has frontmatter with all `lq_ai:` fields, includes at least one worked example, and is reviewed by at least one practicing attorney before merge.

#### DE-002 — Additional regimes for DPA Checklist Review

**Priority:** P2 · **Effort:** M

**Context:** DPA Checklist Review v1.0.0 covers GDPR, US state privacy, HIPAA BAA, and general commercial. Several other regimes were identified as in-scope for the skill's structure but out-of-scope for v1 substantive coverage.

**Specific regimes to add as reference files:**
- Canada PIPEDA / provincial laws (Quebec Bill 64 / Law 25, BC PIPA, Alberta PIPA).
- Brazil LGPD.
- China PIPL.
- Singapore PDPA.
- Australia Privacy Act.
- India DPDP Act.
- South Korea PIPA.

**Acceptance criteria:** Each regime added as `reference/<regime>_requirements.md`, the `regulatory_regime` input expanded to accept the new value, the SKILL.md workflow's Pass 2 references the new file, and at least one worked example added under that regime.

#### DE-003 — Additional worked examples for DPA Checklist Review

**Priority:** P3 · **Effort:** S

**Context:** v1.0.0 ships with two worked examples (GDPR controller, US state privacy processor). HIPAA BAA, general commercial, and multi-state scenarios are not exemplified.

**Acceptance criteria:** Each new example follows the established output format, demonstrates a different combination of perspective and regime, and shows the skill's calibration on a clean vs. non-compliant document.

#### DE-004 — NDA Review redlined-document output mode

**Priority:** P2 · **Effort:** M

**Context:** NDA Review v1.0.x produces suggested redline language inside its markdown report. A redlined-document output mode (producing actual tracked-changes DOCX or structured diff) was deliberately scoped out and assigned to the Word add-in workflow (M3).

**Open question for resolution:** Does the redline-document output belong in the chat workflow or only the Word add-in workflow? The chat workflow currently surfaces redline language as text; users wanting a redlined document open it in Word and apply the suggestions manually. A direct redlined-document output from chat is feasible but adds complexity.

**Acceptance criteria:** Decide whether to add to chat workflow; if yes, define the output format (structured diff vs. tracked-changes DOCX vs. markdown comparison) and update the SKILL.md `output_format` and workflow.

#### DE-005 — Defined-Terms Consistency Check (skill)

**Priority:** P2 · **Effort:** S

**Context:** Across the in-house contract review category (Ivo, Spellbook, Robin AI, Luminance), checking that defined terms are used consistently — defined in one place, used as defined, no shadow definitions, no orphan capitalizations — is a recurring feature. Well-shaped as a skill rather than a capability; it ships once, anyone can fork.

**Specific scope:** A skill that takes a contract, identifies defined terms (capitalized terms in quotes, "(the X)" patterns), extracts their definitions, and reports inconsistencies, undefined uses, and unused definitions.

**Acceptance criteria:** Skill follows the established format, has a worked example demonstrating each failure mode, and produces an inspectable report referencing each finding with citations.

#### DE-006 — Cross-Document Comparison (skill)

**Priority:** P2 · **Effort:** S

**Context:** Common in-house request: "compare this draft NDA to the prior 5 we have signed with similar counterparties; flag where it diverges." The Files / Knowledge Bases capability (§3.5) and Citation Engine support this; a packaged skill makes the pattern discoverable.

**Specific scope:** Skill takes one target document and a set of comparison documents (or a Knowledge Base), produces a structured diff focused on key clauses, and surfaces unusual deviations.

**Acceptance criteria:** Skill produces a readable diff report with citations into both target and comparison documents.

#### DE-007 — Issue List Generator (skill output mode)

**Priority:** P2 · **Effort:** S

**Context:** Many commercial competitors produce an explicit "issues list" output type — structured rows with severity, recommendation, and citation. The NDA Review starter skill produces a markdown report; a structured-output variant suitable for piping into a tracker (Jira, Linear, GitHub Issues) is a different use case.

**Specific scope:** Skill produces JSON output following an `issues_list` schema (issue, severity, recommendation, source citation). The web UI renders it as a sortable table with bulk export.

**Acceptance criteria:** Schema documented in the skill-authoring guide; at least one starter skill has an `issue_list` output mode in addition to its default markdown.

#### DE-008 — Self-serve business-user contract generation (skill family)

**Priority:** P3 · **Effort:** M

**Context:** Robin AI and others let business users (sales, procurement) self-serve standard agreements (NDAs, sales-side order forms) from templates with bounded customization. For an in-house team, this offloads routine work without legal having to draft each one.

**Specific scope:** A pattern (not a single skill) where a templated skill walks a non-attorney user through structured inputs (counterparty name, term, jurisdiction, etc.) and produces a draft agreement plus a "request legal review" affordance. Requires the skill-input-form pattern (DE-010) implemented first.

**Acceptance criteria:** Reference business-user NDA generator skill, with documentation for skill authors on how to build similar.

#### DE-219 — Wave G community-skill installer + first port batch

**Priority:** P1 · **Effort:** L

**Context:** Per `docs/research/2026-05-12-claude-for-legal-review.md` §9 (Q6 decision), LQ.AI will adopt a `legal-builder-hub`-style community-skill installation surface in a v1.1+ Wave G. The pattern: allowlist via `gateway.yaml`, raw-Markdown display in `web/`, license-gate UI, `skills-qa`-style frontmatter + trigger-example evaluator before install commits the skill to disk.

**Specific scope:**
- **G.1 Installer infrastructure:** allowlist source registry, web skill-source browser, install/preview gate, raw-display viewer, license-gate UI, `skills-qa`-style evaluator (frontmatter validation + trigger-example sanity + body lint).
- **G.2 First port batch:** the 10 skills identified in the research doc §5. Verbatim-with-attribution port (per Q4 decision), each going through the existing claim → draft → attest → review → merge pipeline. Skipped from this batch: HEAVY-effort `internal-investigation`, `worker-classification` (v1.2+); audience-mismatch `law-student`, `legal-clinic`, `cocounsel-legal`.
- **G.3 NOTICES + attestation conventions** (per Q7 decision): `NOTICES.md` at repo root tracking upstream provenance per ported file; `lq_ai.author = "Anthropic PBC (upstream) and LegalQuants (adaptation)"` in ported-skill frontmatter; CONTRIBUTING.md adjustment with ported-skill attestation paragraph template.

**Out of scope:** Tool-using skills that depend on MCP connectors (Ironclad, DocuSign, iManage, etc.) — per Q8 decision, those stay pinned to the deferral list and unblock alongside the broader tool-call ADR work.

**Acceptance criteria:** Installer ships with the allowlist gated to `anthropics/claude-for-legal` initially; first port batch (10 skills) lands through the standard skill-authoring pipeline; `NOTICES.md` populated; updated `docs/skill-authoring-guide.md` reflects ported-skill conventions.

### Application UI enhancements

#### DE-010 — Skill input form rendering for any skill

**Priority:** P1 · **Effort:** M

**Context:** PRD §3.4 defines the skill-input-form pattern: when a skill is attached and required inputs are missing, the application surfaces them as form elements rather than letting the model ask conversationally. Enhance Prompt's third example demonstrates the pattern. The pattern is not yet implemented for skills generally — only specified.

**Specific scope:**
- Read `lq_ai.inputs.required` and `lq_ai.inputs.optional` from any attached skill's frontmatter.
- Render single-select inputs as radio buttons or dropdowns, free-text as input fields, document inputs as file pickers.
- When the user submits, populate the prompt with structured input values before the model call.

**Acceptance criteria:** Any skill in M1 with required inputs (NDA Review, DPA Checklist Review, etc.) shows the form on attachment; the form appears in both the standalone chat input and the Enhance Prompt review screen.

#### DE-011 — Reasoning visibility configuration for Enhance Prompt

**Priority:** P2 · **Effort:** S

**Context:** PRD §3.2 specifies three reasoning-visibility modes (`always_show`, `disclosure`, `on_request`). Implementation deferred to OpenWebUI fork integration.

**Specific scope:** Account-level setting; UI surface in OpenWebUI settings panel; cookie/preference persistence; reasoning-section rendering responsive to the setting.

**Acceptance criteria:** All three modes function on the Enhance Prompt review screen; the default is `disclosure`.

#### DE-012 — Skill inspector side panel

**Priority:** P1 · **Effort:** M

**Context:** PRD §3.4 specifies skill inspectability as a cross-cutting transparency principle. The side-panel UI is specified but not implemented in v1 backend scope.

**Specific scope:**
- Side panel triggered by "view this skill" button on any active skill or Enhance Prompt review screen.
- Renders SKILL.md (with frontmatter formatted readably) and supporting files as tabs.
- Shows provenance line (built-in / authored by / shared by / forked from).
- "Fork this skill" affordance creates a copy under the user's scope.

**Acceptance criteria:** Side panel opens in <500ms; all attached skills are inspectable; fork creates editable copy.

#### DE-013 — Saved Prompts Library

**Priority:** P3 · **Effort:** S

**Context:** Skills are heavyweight (folder, frontmatter, supporting files, semver). For quick personal reuse — "the way I always ask for an executive summary" — a lighter-weight saved-prompt list complements skills the way browser bookmarks complement OpenWebUI's Knowledge Bases. GC.AI ships both; the gap is real.

**Specific scope:** Per-user saved prompts (text + name + optional tags), accessible from a sidebar in the chat input. Prompts can be promoted to skills via "save as skill."

**Acceptance criteria:** Saved-prompt CRUD; sidebar quick-insert; promote-to-skill flow tested.

#### DE-014 — Tone / Audience Settings on Skills

**Priority:** P3 · **Effort:** S

**Context:** Audience-calibrated outputs (peer attorney vs CRO vs board) is a recurring competitor feature. The Comms Improver starter skill addresses one direction post-hoc; making `audience` a standard optional input on skills (per DE-020) propagates the pattern across the skill library.

**Specific scope:** Standardize an `audience: peer_attorney | business_executive | board | client | non_legal_layperson` optional input across skills that produce written output. Skill-authoring guide documents the pattern.

**Acceptance criteria:** Pattern documented; M1 starter skills retrofit where applicable.

#### DE-015 — Voice / Dictation Input

**Priority:** P3 · **Effort:** S

**Context:** GC.AI offers built-in dictation. Modern browsers expose Web Speech API; this is mostly a UI addition.

**Specific scope:** Dictation toggle on the chat input, visible per-prompt waveform, accuracy disclaimer. No server-side STT in v1; rely on browser API.

**Acceptance criteria:** Dictation works in Chrome and Safari; clearly disclaimed as browser-side.

#### DE-265 — In-app "unverified citation" badging until Citation Engine ships

**Priority:** P1 · **Effort:** S · **Target milestone:** M1 polish or M2 with Citation Engine

**Context:** M1 ships the Citation Engine architectural slot but not the byte-level verification pipeline (`docs/HONEST-STATE.md` §3.1). Without an explicit in-app indicator, users may see model-generated text resembling a citation and assume it has been verified against source material when it has not. The HONEST-STATE doc is upfront about the gap; the chat UI is not.

**Specific scope:** A visual "unverified" badge rendered next to any text in chat output that resembles a citation (a `[chunk-id]`-like reference, a quoted span attributed to a document, or a parenthesized section reference). The badge is hoverable / focusable with explanatory text — e.g., "This text looks like a citation but has not been verified. The Citation Engine ships in M2 (see HONEST-STATE.md §3.1). Until then, treat apparent citations as suggestions to verify, not as verified provenance." The badge is removed automatically when M2 Citation Engine renders verification metadata alongside the span. Implemented client-side on the rendered output; no backend schema change needed.

**Acceptance criteria:** Citation-like spans show the badge in M1 chat output; the badge is keyboard-focusable and screen-reader-accessible (`role="status"` or `aria-label` + tooltip pattern); Cypress E2E exercises the badge on at least one starter-skill output that historically produces citation-like text.

#### DE-272 — Admin AliasForm: model dropdown autocomplete population

**Priority:** P2 · **Effort:** S

**Context:** The admin "Edit alias" form (`web/src/lib/lq-ai/components/AliasForm.svelte`, used in `/lq-ai/admin/models`) ships with one known UX gap at M1: the Model dropdown shows only the currently-configured model, not the full list of models the selected provider supports. The form already supports per-provider model autocomplete via `<datalist>` and a `providerModels: Record<string, string[]>` prop, but the parent admin page (`web/src/routes/lq-ai/admin/models/+page.svelte`) does not populate this map. The dropdown therefore lists only the model already saved on the alias being edited — changing models requires typing the model id from memory, which is brittle in practice. The field is still a free-text input so editing is *possible*, but the autocomplete is effectively missing. (A related light/dark color-contrast issue in the same form was fixed pre-tag — the `dark:` Tailwind variants were removed so the form matches the surrounding admin chrome.)

**Specific scope:** Expose each provider's `models` list (already declared in `gateway.yaml.example` under `providers[].models`) via a new admin endpoint (or extend `GET /api/v1/admin/config` if it exists). The parent admin page builds the `providerModels` map from the response and passes it to `AliasForm`. The autocomplete then surfaces real choices per the currently-selected provider; the field remains free-text for partial / out-of-config models.

**Acceptance criteria:** Model field offers autocomplete with the actual provider's model list when the provider is selected; the field remains free-text-editable; one Cypress E2E covers the admin Edit-alias modal exercising the autocomplete.

### PRD-process and capability refinements

#### DE-020 — Standardize the optional-input pattern across skills

**Priority:** P1 · **Effort:** S

**Context:** During skill authoring (NDA Review v1.0.0 → v1.0.1, DPA Checklist Review v1.0.0), a pattern emerged: optional inputs that change *analytical depth* not just *report format* are particularly valuable. NDA Review uses `deal_type` and `prior_agreements`; DPA Checklist Review uses `party_role`, `data_categories`, `international_transfer_context`, `prior_agreements`.

**Recommendation:** Document this pattern in the skill-authoring guide so future skills (community-contributed and otherwise) follow it deliberately. Optional inputs should be evaluated against the test: "does providing this input change the substance of the analysis, not just the presentation?"

**Acceptance criteria:** Skill-authoring guide section "Designing optional inputs" is added; existing skills are reviewed against the pattern.

#### DE-021 — Skill versioning and publishing flow

**Priority:** P1 · **Effort:** M

**Context:** Skills carry version numbers in frontmatter (semver). The mechanics of skill versioning across community use (forks, upstream updates, conflict resolution when a community version diverges from the maintained version) are not specified.

**Specific questions:**
- What happens when a community-curated skill (e.g., a jurisdiction-specific NDA Review variant) is updated upstream? Does the user's fork inherit changes? Is there a merge mechanism?
- How are breaking changes (major-version bumps) communicated to users with the skill attached?
- Is there a `skills.legalquants.com` registry for discovering community-published skills?

**Acceptance criteria:** Versioning policy documented; if a registry is built, it follows the same open-source posture as the rest of the project (no telemetry, optional, federated).

#### DE-022 — Skill performance and quality measurement

**Priority:** P2 · **Effort:** L

**Context:** Skills are the unit of value in LQ.AI. There is no current mechanism for measuring how well a skill performs against its intended use, comparing skill versions, or evaluating community contributions.

**Specific scope:**
- Eval harness that runs a skill against a held-out set of representative inputs and grades outputs against expected behavior.
- Per-skill metrics dashboard (when telemetry is enabled with operator opt-in).
- Skill-comparison tool for evaluating proposed updates.

**Acceptance criteria:** Eval harness can execute against any skill; the m1 starter skills have eval suites; community contributions can include eval suites alongside skill content.

#### DE-023 — External-Counsel Collaboration Boundary

**Priority:** P3 · **Effort:** L

**Context:** Many legal teams' real workflow includes a law firm partner. Legora's Portal addresses this. The PRD's positioning is "open-source AI for legal teams" — covering in-house, firm, and solo practitioners — but the firm/in-house collaboration boundary is a real workflow.

**Specific recommendation:** Treat as an open question for the project's future direction, not a v1 commitment. The simplest path is per-user external-collaborator licensing within an LQ.AI deployment (the firm's lawyer is granted scoped access to a Project, per §3.11). The harder path is a federation protocol between two LQ.AI deployments.

**Acceptance criteria:** Decision captured in a future PRD revision; no v1 implementation expected; community demand observed before commitment.

#### DE-024 — ISO 42001 (AI Management System) Alignment Documentation

**Priority:** P3 · **Effort:** M

**Context:** Legora and Legalfly hold or are pursuing ISO 42001 certification (AI governance). For an open-source project, certification is the operator's responsibility, but *alignment* (publishing a mapping of how LQ.AI's design choices satisfy ISO 42001 controls) helps operators argue for adoption inside ISO-aligned organizations. The Compliance Alignment Pack (per §1.8 / M1) commits to shipping `docs/compliance/iso-42001-alignment.md`; this DE captures the ongoing maintenance and refinement of that document beyond M1.

**Specific scope:** Maintain `docs/compliance/iso-42001-alignment.md` mapping each control to relevant PRD sections and configuration choices; update each release; reviewed by an information-security professional.

**Acceptance criteria:** Document published with first GA release; reviewed by an information-security professional; updated each minor release.

### Deployment and infrastructure

#### DE-030 — Helm chart for Kubernetes deployment

**Priority:** P1 · **Effort:** M

**Context:** PRD §6.3 specifies a Helm chart for production K8s deployment. Reference docker-compose is in M1; Helm chart is a follow-on.

**Acceptance criteria:** `helm install lq-ai legalquants/lq-ai -f values.yaml` produces a working deployment; HA Postgres reference architecture documented; horizontal API scaling tested.

#### DE-031 — Reverse proxy / TLS recipes

**Priority:** P2 · **Effort:** S

**Context:** PRD §6.3 mentions Caddy/Traefik/nginx recipes. Concrete configurations not yet written.

**Acceptance criteria:** Each recipe is a documented `docker-compose` overlay or standalone configuration; Let's Encrypt automation works; recipes tested end-to-end.

#### DE-032 — Air-gap install verification

**Priority:** P2 · **Effort:** S

**Context:** PRD §6.4 specifies air-gapped deployment is supported and that Mode 2 has no outbound calls. Verified by integration test mentioned but not detailed.

**Acceptance criteria:** CI test confirms zero outbound network calls in Mode 2 across all v1 capabilities; documented air-gap install guide tested by external user.

#### DE-033 — Backup and restore tooling

**Priority:** P2 · **Effort:** M

**Context:** PRD §6.5 references documented backup recipe and tested restore. Tooling not yet provided.

**Specific scope:** CLI tool that runs `pg_dump` plus MinIO snapshot, generates a versioned backup bundle, and a corresponding restore tool that handles version migration if needed.

**Acceptance criteria:** Backup-restore round-trip tested in CI; documented procedure for upgrade-with-restore.

#### DE-267 — Azure OpenAI provider adapter — ✓ Closed in M2-E1 (2026-05-17)

**Status:** **✓ Closed in M2-E1** (2026-05-17). Shipped as `gateway/app/providers/azure_openai.py` (subclass of `OpenAIAdapter`) wired into the lifespan dispatch in `gateway/app/main.py`, with example configuration in `gateway.yaml.example` under the `azure-openai` provider entry. Unit-test parity with the OpenAI adapter lives at `gateway/tests/test_azure_openai_adapter.py` (14 tests); the mocked end-to-end gateway-integration test lives at `gateway/tests/test_inference_azure_openai.py` (routes a chat request through the full FastAPI stack to a respx-mocked Azure upstream). API-key auth ships; the Azure AD path (managed identity / service principal) was scoped out to keep M2-E1 at ~4 hr and is tracked at [DE-278](#de-278--azure-openai-ad-authentication-managed-identity--service-principal).

**Historical context (pre-M2-E1):** Three provider adapters shipped in M1 (Anthropic, OpenAI, Ollama); Vertex AI (DE-034) and AWS Bedrock (DE-035) remained on the deferred-enhancement list as community-friendly work units. Microsoft Azure OpenAI was a significant gap: many enterprise legal teams hold existing Azure commitments (Azure's HIPAA BAA via the Online Services Subscription Agreement; FedRAMP High authorization; the EU AI Act-relevant DPA/SCC documentation Azure provides; an Enterprise Agreement that already covers their procurement budget). The Provider Compliance Matrix referenced Azure but no adapter shipped in M1; operators on Microsoft-only procurement contracts could not route through their existing stack until M2-E1.

**Scope as shipped:** `gateway/app/providers/azure_openai.py` mirrors the OpenAI wire format (request bodies, SSE streaming, error mapping, LQ.AI extension-key strip) via subclass inheritance, overriding only the differences: `api-key` auth header (vs OpenAI's `Authorization: Bearer`); deployment-scoped URL (`/openai/deployments/<deployment-id>/chat/completions?api-version=<version>`); required `api_version` field in the provider config (no silent default — Azure rolls features per api-version, so operators pin a version explicitly). The gateway's existing model-alias mechanism doubles as the deployment-id resolver: each alias's `model` field is the Azure deployment-id (operator-named), and the adapter substitutes it into the URL path. Default tier in `gateway.yaml.example` is Tier 3 (Azure OpenAI under enterprise agreement carries ZDR + BAA terms).

**Acceptance criteria met:** Adapter passes the gateway test suite shape used by the OpenAI adapter (chat completions, embeddings, streaming, error mapping for 401/500/network failures, health check); documented in the gateway provider entry; example configuration appears in `gateway.yaml.example`; one mocked gateway-integration test (`test_chat_completions_routes_to_azure_via_passthrough`) exercises an end-to-end Azure call through the running FastAPI lifespan.

#### DE-034 — Google Vertex AI provider adapter (Anthropic on Vertex)

**Priority:** P1 · **Effort:** M

**Context:** PRD §4 calls for Vertex AI support as one of the v1 providers (per the supported-provider list and `gateway.yaml.example`'s `vertex-anthropic` entry). M1 ships the Anthropic, OpenAI, and Ollama adapters; the Vertex adapter is the Tier-3 path for operators who want Anthropic-quality models routed through their own GCP project under their existing Google Cloud DPA, with no third-party processor introduced between LQ.AI and the model.

The architectural slot exists: `ProviderType` already accepts `"vertex"` (`gateway/app/config.py`), `gateway.yaml.example` documents the `vertex-anthropic` entry (provider name → type, base_url, project_id, region, tier), and `gateway/app/main.py`'s adapter dispatch already has a branch placeholder ("B6 lands the remaining adapters"). The work is the adapter implementation itself.

**Wire format (Anthropic-on-Vertex specifically).** Vertex serves Anthropic models via the publisher-models surface. Endpoint shape:

```
POST https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{REGION}/publishers/anthropic/models/{MODEL_ID}:rawPredict
POST https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{REGION}/publishers/anthropic/models/{MODEL_ID}:streamRawPredict
```

The `MODEL_ID` is the Vertex-specific suffixed form (e.g., `claude-opus-4-7@anthropic`). The request body is the Anthropic Messages body shape (`messages`, `system`, `max_tokens`, etc.) **with the `model` field removed** (Vertex derives the model from the URL path) and `anthropic_version: "vertex-2023-10-16"` added at the body root (not the same as the Anthropic-direct `anthropic-version` header). The response body is identical to Anthropic Messages. SSE streaming uses the same event names (`message_start`, `content_block_delta`, `message_delta`, `message_stop`).

**Auth.** Vertex uses Google IAM, not API keys. The flow is:

1. Read a service-account JSON file from the path in `GOOGLE_APPLICATION_CREDENTIALS` (or the value of `provider.api_key_env` in `gateway.yaml`).
2. Build a JWT bearer assertion with claims `{iss: <service-account-email>, scope: "https://www.googleapis.com/auth/cloud-platform", aud: "https://oauth2.googleapis.com/token", exp: now+3600, iat: now}` signed with the service account's private key (RS256).
3. Exchange the JWT for an access token: `POST https://oauth2.googleapis.com/token` with `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=<jwt>`.
4. Use the returned `access_token` in `Authorization: Bearer <token>`. Tokens are valid for 1h; cache and refresh.

Hand-rolled implementation needs: `cryptography` for RSA signing (already a gateway dep for Fernet), a small JWT builder (~30 LOC), and a token cache with proactive refresh at T-5min. Alternative: depend on `google-auth` to handle the JWT-exchange flow (adds two heavyweight transitive dep trees but is the canonical implementation). Project decision punted to implementation time; the PRD §4 "no LLM-SDK dep" posture argues hand-rolled.

**Error mapping.** Vertex returns `403 PERMISSION_DENIED` (treat as `ProviderAuthError`), `404 NOT_FOUND` (model not enabled in this region — map to `invalid_model`), `429 RESOURCE_EXHAUSTED` (treat as `ProviderHTTPError` upstream_status=429 for fallback eligibility), `5xx` (treat as `ProviderHTTPError`). Errors come back in the Google standard envelope `{"error": {"code": int, "message": str, "status": str}}`.

**Tier handling.** Vertex is Tier 3 by default (operator's GCP project, ZDR by GCP terms) per `gateway.yaml.example`. The tier resolver already supports this; no changes needed.

**Acceptance criteria:**
- `VertexAdapter` in `gateway/app/providers/vertex.py` implementing `ProviderAdapter` contract: `chat_completion` (unary + streaming via `:rawPredict` / `:streamRawPredict`), `embeddings` raises `ProviderUnsupportedError` (Vertex does not serve Anthropic embeddings).
- `health_check` probes `GET /v1/projects/{project}/locations/{region}/publishers/anthropic/models/{model}` (cheapest authenticated GET).
- JWT-bearer auth flow with token caching; service-account JSON loaded via `GOOGLE_APPLICATION_CREDENTIALS` env var.
- Unit tests with mocked httpx covering: happy path (unary + streaming), 403 auth error, 404 model-not-found, 429 rate-limit, network error, token refresh on expiry, no-key-leak invariant.
- `gateway/app/main.py` lifespan handles `provider.type == "vertex"` and instantiates `VertexAdapter`; missing creds at startup is a warning, not fatal (matches Anthropic adapter pattern).
- Live smoke verified against a real GCP project with Vertex AI Anthropic enabled in at least one region (us-central1 or us-east5).

**Estimated effort:** 8–12 hours including JWT auth + tests + live smoke. Existing AnthropicAdapter is the template for request/response translation; the JWT/token-exchange flow is the new work.

#### DE-035 — AWS Bedrock provider adapter (Anthropic on Bedrock)

**Priority:** P1 · **Effort:** M

**Context:** PRD §4 calls for Bedrock support as one of the v1 providers. M1 ships the Anthropic, OpenAI, and Ollama adapters; the Bedrock adapter is the Tier-3 path for operators who want Anthropic-quality models routed through their own AWS account under their existing AWS DPA, with no third-party processor introduced.

The architectural slot exists: `ProviderType` already accepts `"bedrock"`, `gateway.yaml.example` documents the `bedrock` provider entry (type, base_url with region template, aws_region, aws_access_key_env, aws_secret_key_env, tier), and `gateway/app/main.py`'s adapter dispatch has a placeholder branch. The work is the adapter implementation itself.

**Wire format (Anthropic-on-Bedrock specifically).** Bedrock-Runtime hosts Anthropic models at:

```
POST https://bedrock-runtime.{AWS_REGION}.amazonaws.com/model/{MODEL_ID}/invoke
POST https://bedrock-runtime.{AWS_REGION}.amazonaws.com/model/{MODEL_ID}/invoke-with-response-stream
```

Where `MODEL_ID` is the Bedrock-specific identifier (e.g., `anthropic.claude-opus-4-7-v1:0` from `gateway.yaml.example`). The request body is the Anthropic Messages body shape **with the `model` field removed** (Bedrock derives it from the URL) and `anthropic_version: "bedrock-2023-05-31"` added at the body root. The response body for `/invoke` is identical to Anthropic Messages.

**Streaming protocol — critical departure from Anthropic-direct.** Bedrock's `/invoke-with-response-stream` does **not** use SSE. It uses the AWS Event Stream binary protocol — a length-prefixed framing format where each frame has a header block (HTTP/2-style key/value pairs) plus a payload. For Anthropic streams, each frame's payload is a JSON object of shape `{"bytes": "<base64>"}` and the base64-decoded bytes are an Anthropic SSE event payload (the same `message_start` / `content_block_delta` / etc. payload that the direct Anthropic API emits in `data:` lines).

Frame parser shape (hand-rolled per the AWS Event Stream spec — ~100 LOC):

```
Frame := TotalLength(4B) HeadersLength(4B) PreludeCRC(4B) Headers(...) Payload(...) FrameCRC(4B)
Header := NameLen(1B) Name(...) Type(1B) ValueLen(2B) Value(...)
```

The relevant header is `:event-type` (`chunk` for data frames, `exception` for errors). On a `chunk` frame, parse the JSON payload, base64-decode the `bytes` field, then translate the inner Anthropic SSE event into an OpenAI-shaped `ChatCompletionChunk` (the existing `gateway/app/providers/anthropic.py:_anthropic_stream_iter` already has this translation; refactor to be reusable).

**Auth.** Bedrock uses AWS SigV4 request signing. The signing flow per signature:

1. Build the canonical request: `<HTTPVerb>\n<URI-encoded-path>\n<canonical-query-string>\n<canonical-headers>\n<signed-header-names>\n<hex(sha256(body))>`.
2. Build the string-to-sign: `AWS4-HMAC-SHA256\n<ISO8601-UTC>\n<credential-scope>\n<hex(sha256(canonical-request))>`. Credential scope is `<date>/<region>/bedrock/aws4_request`.
3. Derive signing key: HMAC chain `kSecret -> kDate -> kRegion -> kService -> kSigning`.
4. Sign: `signature = hex(HMAC-SHA256(kSigning, string-to-sign))`.
5. Set headers: `Authorization: AWS4-HMAC-SHA256 Credential=<access-key>/<scope>, SignedHeaders=<names>, Signature=<sig>`, plus `x-amz-date`, `x-amz-content-sha256`, and (if STS session) `x-amz-security-token`.

Hand-rolled implementation needs: `hmac` and `hashlib` from stdlib (no new deps). ~200 LOC. Alternative: depend on `boto3` purely for the signer (adds large transitive tree but is canonical). PRD §4 "no LLM-SDK dep" posture argues hand-rolled, especially because the SigV4 implementation is small and well-specified.

**Error mapping.** Bedrock returns `403 AccessDeniedException` (auth error), `404 ResourceNotFoundException` (model not enabled in this region — map to `invalid_model`), `424 ModelStreamErrorException` (mid-stream model failure — surface as `ProviderHTTPError`), `429 ThrottlingException` (rate-limit, fallback-eligible), `5xx` (`ServiceUnavailableException` etc., fallback-eligible). Errors come back in the AWS standard JSON envelope.

**Tier handling.** Bedrock is Tier 3 by default (operator's AWS account, ZDR by AWS terms) per `gateway.yaml.example`. The tier resolver already supports this; no changes needed.

**Acceptance criteria:**
- `BedrockAdapter` in `gateway/app/providers/bedrock.py` implementing `ProviderAdapter` contract: `chat_completion` (unary via `/invoke` + streaming via `/invoke-with-response-stream` with AWS Event Stream frame parsing), `embeddings` raises `ProviderUnsupportedError` (Bedrock has separate embedding models; out of scope for this DE).
- `health_check` probes `GET /foundation-models` on the Bedrock control-plane (cheapest authenticated GET against the region) — note this is `bedrock.{region}.amazonaws.com`, not `bedrock-runtime`. Health probe signs SigV4 for service `bedrock` not `bedrock-runtime`.
- Hand-rolled SigV4 signer in `gateway/app/providers/_sigv4.py` (or inlined); covers the path-encoding, query-canonicalization, and STS-session-token cases.
- AWS Event Stream binary frame parser supporting `chunk` and `exception` event types.
- Refactor: extract Anthropic SSE-event-to-OpenAI-chunk translation from `gateway/app/providers/anthropic.py` into a shared helper so both `AnthropicAdapter` and `BedrockAdapter` use it.
- Unit tests with mocked httpx covering: happy path (unary + streaming with crafted event-stream frames), 403/404/429/5xx error mapping, SigV4 signature determinism (canonical-request fixtures match AWS-spec test vectors), no-key-leak invariant.
- `gateway/app/main.py` lifespan handles `provider.type == "bedrock"` and instantiates `BedrockAdapter`; missing creds at startup is a warning, not fatal.
- Live smoke verified against a real AWS account with Bedrock Claude access enabled in at least one region.

**Estimated effort:** 12–16 hours including SigV4 signer + event-stream parser + tests + live smoke. The event-stream parser is the most novel piece; the SigV4 signer is small but exacting (AWS provides spec test vectors that the implementation can hit exactly).

### Capability extensions

#### DE-060 — Multi-document Q&A for Contract QA

**Priority:** P2 · **Effort:** L

**Context:** Contract QA v1.0.0 operates against a single document. Multi-document Q&A — questions across a knowledge base of contracts ("which of our SaaS agreements have unlimited liability carve-outs?", "compare this MSA against our standard form") — was identified as genuinely useful but deliberately scoped out of v1 because it raises distinct issues around retrieval scoring, cross-document scope ambiguity, and citation rendering when the answer spans multiple documents.

**Specific scope:**
- Extend Contract QA's `document` input to accept either a single document or a knowledge base reference.
- When operating across multiple documents, retrieval pulls candidate chunks across all in-scope documents.
- Citation format adds a document identifier prefix (e.g., `[MSA-Acme §4.2]` rather than `[§4.2]`).
- The answer rendering shows results grouped by document where applicable.
- The skill needs to handle "scope ambiguity" cases — when the user asks a question that has different answers in different documents, the answer surfaces the variance rather than picking one.

**Open questions for resolution:**
- How does the skill scope a multi-document question? Knowledge-base reference is one mechanism; user-selected document set is another.
- How does the user verify answers when the citation engine is rendering multiple documents in the side panel?
- Does this become a separate skill (`contract-qa-multi`) or stay in Contract QA with a mode flag?

**Acceptance criteria:** Multi-document Q&A produces accurate answers grouped by document; the side-panel viewer handles multi-document citations; the skill correctly identifies and surfaces scope-ambiguous cases.

#### DE-061 — Contract QA acceptance testing

**Priority:** P1 · **Effort:** S

**Context:** Contract QA v1.0.0 includes worked examples but has not been stress-tested against real-world contracts and the full range of question shapes in the wild. Acceptance testing should validate behavior across the six question types and a representative document corpus.

**Specific scope:** Test corpus of 5–10 anonymized real contracts (mix of NDAs, MSAs, employment agreements, vendor agreements). For each, a set of representative questions across all six types (A, B, C, D, E, F). Run Contract QA against each question and grade outputs against expected behavior.

**Acceptance criteria:** Test corpus exists; each starter document has acceptance results documented; identified issues addressed before public release.

#### DE-070 — Dedicated Order Form / SOW Review skill

**Priority:** P2 · **Effort:** M

**Context:** MSA Review — SaaS v1.0.0 accepts an Order Form as optional input and surfaces MSA-vs-Order-Form conflicts (Pass 6 of the workflow). A dedicated Order Form Review skill — focused entirely on Order Form review and its relationship to a referenced MSA — was scoped out of v1.

**Specific scope:**
- Order Form Review skill that reviews Order Form / SOW / Service Schedule documents on their own terms.
- Pricing analysis (rate sheet sanity, term-pricing alignment, discount transparency).
- Service-scope analysis (commitments specific to the order, customer-specific service levels, in-scope vs. out-of-scope features).
- MSA conflict analysis when the user provides both Order Form and MSA.
- Calibration to common Order Form templates (vendor-prepared, customer-prepared, intermediary forms).

**Acceptance criteria:** new skill `order-form-review` follows the established skill format; produces structured findings; works alongside (not duplicating) MSA Review.

#### DE-071 — Additional MSA review variants

**Priority:** P2 · **Effort:** L (multiple skills, one at a time)

**Context:** MSA Review — SaaS covers software-as-a-service master agreements specifically. Other MSA categories share structural similarities but have distinct substantive considerations.

**Specific candidates:**
- **MSA Review — Professional Services:** for consulting, implementation, integration, and managed-services agreements without a SaaS substrate.
- **MSA Review — Hardware-as-a-Service:** for IoT-platform agreements, equipment-bundled-with-service models.
- **MSA Review — AI / ML Services:** for agreements where the service is access to a model provider's offering, with distinct issues around training data, output IP, model versioning, and inference confidentiality.
- **MSA Review — Government Services:** SaaS for federal or state procurement, with FedRAMP, FAR, and procurement-statute overlays.
- **Channel Partner / Reseller Agreement Review:** distinct from MSA but adjacent.

**Acceptance criteria:** each new skill follows the established format and references shared infrastructure (severity rubric structure, perspective-lens approach) for consistency across the contract-review skill family.

#### DE-072 — MSA Review acceptance testing against real document corpus

**Priority:** P1 · **Effort:** M

**Context:** MSA Review — SaaS is the largest contract-review skill in the M1 set. Acceptance testing against a corpus of real-world MSAs (vendor-favorable, customer-favorable, balanced; SMB and enterprise; various industries) is essential before relying on the skill's output for actual deals.

**Specific scope:** anonymized corpus of 10-15 real SaaS MSAs across the dimensions above. For each, expected behavior documented (which issues should be flagged at which severity from each perspective). Run MSA Review against each in `comprehensive` and `quick_triage` modes; grade outputs.

**Acceptance criteria:** corpus exists and is reviewed by external counsel for accuracy of expected behavior; MSA Review acceptance results documented; identified issues addressed before public release.

#### DE-080 — Shared infrastructure for contract-review skill family

**Priority:** P2 · **Effort:** M

**Context:** During authoring of NDA Review, DPA Checklist Review, MSA Review — SaaS, and MSA Review — Commercial Purchase, a recurring pattern emerged: the *infrastructure* of contract review (severity rubric, perspective-lens approach, report structure, recommended-language conventions) is consistent across skills, while the *substance* (issue checklist, red flags, regime-specific requirements) is fresh per skill.

In v1, each contract-review skill carries its own copy of the shared infrastructure. This is duplicative — when we update the severity rubric or report structure, we must update every contract-review skill independently — but acceptable for the M1 release because the duplication is explicit and reviewable.

**Specific scope for v1.5 or later:**
- Hoist shared infrastructure to a project-level reference: `skills/_shared/contract_review/{severity_rubric.md, report_structure.md, perspective_lens_pattern.md, recommended_language_conventions.md}`.
- Update each contract-review skill's `SKILL.md` to reference the shared infrastructure rather than duplicating it.
- Each skill retains its own `issue_checklist.md` and `red_flags.md` (the substantive content) plus a thin local extension to the shared infrastructure where the skill needs calibrations specific to its document type.
- Document the pattern in the skill-authoring guide so future contract-review skills (and community contributions) follow it.

**Why deferred:** doing this in v1 would have required the pattern to be designed *before* it was discovered. By authoring four contract-review skills with the duplication in place, the actual shape of the shared infrastructure becomes visible and the abstraction is grounded rather than speculative. This is the right time to extract the pattern, but only after enough skills exist to verify it.

**Acceptance criteria:** shared infrastructure files exist; existing contract-review skills updated to reference rather than duplicate; skill-authoring guide documents the pattern; one new community-contributed contract-review skill demonstrates the pattern works.

**Generalizes beyond contract review.** The same pattern likely applies to any skill family — research skills will share research-process infrastructure; drafting skills will share voice-and-style conventions; review skills generally will share severity calibration. Document the meta-pattern in the skill-authoring guide.

#### DE-081 — Obligation Tracking / Renewal Calendar

**Priority:** P3 · **Effort:** L

**Context:** Robin AI and CLM-with-AI products (Ironclad, Evisort) provide obligation tracking — auto-renewal dates, deadline alerts, milestone notifications. The PRD does not address the post-signature life of contracts, which is correct for a v1 focus on the analytical work, but worth flagging for a future direction.

**Specific recommendation:** Probably a separate capability (or a sister project) rather than a core feature; obligation tracking is a fundamentally different shape of work (temporal, calendar-driven, notification-heavy) than analytical AI. The autonomous layer (§3.10) could host the underlying mechanism (cron schedules, watches) with a domain-specific UI on top.

**Acceptance criteria:** Decision captured (in-scope for LQ.AI vs. sister project); if in-scope, reference implementation ships in a later milestone.

#### DE-082 — Regulatory Monitoring with Proactive Alerts

**Priority:** P3 · **Effort:** L

**Context:** Legalfly's "Legal Radar" continuously monitors regulatory feeds across 60+ jurisdictions and flags items relevant to the user's industry/business. This is a watch-on-the-Research-feed analog of the autonomous-layer KB watches (§3.10).

**Specific scope:** An autonomous-layer pattern where the user subscribes a Project to relevant regulatory feeds (Federal Register, SEC EDGAR releases, EUR-Lex publications, state AG announcements), the autonomous agent runs daily, and notifies on items that match the Project's defined relevance criteria.

**Acceptance criteria:** Reference subscription pattern documented; first regulatory-watch skill ships demonstrating it.

#### DE-083 — Google Docs Add-On (M3 sister to the Word Add-In)

**Priority:** P3 · **Effort:** L

**Context:** PRD §3.9 specifies a Word add-in via Office.js. Many startups, smaller in-house teams, and increasingly some larger ones draft in Google Docs. Several competitors (Ivo, Spellbook for Docs) cover both surfaces.

**Specific recommendation:** Defer to M5 or community. A Google Workspace add-on using the same backend OpenAPI surface is feasible but adds significant engineering and OAuth-flow complexity. Worth flagging as a deferred capability rather than ignoring.

**Acceptance criteria:** Decision captured in a future PRD revision; community demand observed before commitment.

#### DE-084 — Email-as-Intake Bridge

**Priority:** P3 · **Effort:** M

**Context:** Forwarding `legal@company.com` emails into a system that creates structured chats is the front-door pattern most in-house teams actually adopt. Streamline AI builds this; an OSS LQ.AI without it leaves a real gap. Sister to the Slack/Teams Light Intake Bridge (§3.15).

**Specific scope:** A configured incoming email address (per deployment) that creates a chat from the email body, attaches any documents, and assigns to a configured user or group based on rules. Deliberately *not* full triage/SLA/approval workflow — that is Streamline AI's category (per §1.6).

**Acceptance criteria:** Email-to-chat flow works end-to-end; documented IMAP / SMTP / Postfix configuration recipe.

#### DE-085 — Operational Analytics for Legal Ops

**Priority:** P3 · **Effort:** M

**Context:** Streamline AI, Checkbox, and others surface metrics on legal-team throughput, SLA hit rate, request volume by team, and time-at-stage. The PRD has cost tracking (§5.5) but not legal-work analytics.

**Specific scope:** A dashboard surface (admin role) showing chat volume by user/team, time-to-first-token, time-to-final-answer, skills usage, and Project activity. Builds on existing OpenTelemetry instrumentation (§5.4).

**Acceptance criteria:** Dashboard ships with at least 5 default metrics; metrics exportable; documented for operators.

#### DE-086 — Procurement-Readiness Pack

**Priority:** P2 · **Effort:** S

**Context:** Operators deploying LQ.AI inside an enterprise will face an internal procurement / security review. Commercial competitors ship pre-filled SIG, CAIQ, and security-questionnaire responses to short-cut this. For an open-source self-hosted product, the operator owns the answers, but a starter pack would dramatically lower the friction. The Compliance Alignment Pack (per §1.8 / M1) plus Pre-Empted Procurement Objections appendix (Appendix E) cover much of this; the Procurement-Readiness Pack adds the questionnaire templates.

**Specific scope:** Templates in `docs/procurement/` covering: SIG Lite responses, CAIQ responses, security architecture summary, data-flow diagram, supported deployment topologies for various enterprise constraints, third-party dependencies and their licenses (already partially covered in Appendix B).

**Acceptance criteria:** Templates ship with the M1 release; reviewed by an enterprise-buyer sample before publishing.

#### DE-040 — Direct CLM integration

**Priority:** P3 · **Effort:** L

**Context:** PRD §1.6 lists "direct integrations with CLM systems (Ironclad, Concord, etc.)" as out of scope for v1.

**Specific scope:** API integrations or MCP tool adapters for the major CLMs, allowing LQ.AI to read contracts from CLMs, post review reports back, and trigger workflow updates.

**Acceptance criteria:** At least one CLM integration shipped with documentation; pattern for adding others.

#### DE-041 — E-discovery capabilities

**Priority:** P3 · **Effort:** L

**Context:** PRD §1.6 lists e-discovery as out of scope. Some users will request it; structurally distinct from in-house work.

**Recommendation:** Probably should remain a separate project rather than merging into LQ.AI. Track community demand and revisit if a fork or sister project is warranted.

#### DE-042 — Mobile applications

**Priority:** P3 · **Effort:** L

**Context:** PRD §1.6 lists mobile native apps as out of scope; web UI is responsive.

**Recommendation:** Wait for community demand. If demand materializes, consider PWA before native.

#### DE-220 — Organization Profile singleton skill (per-firm playbook)

**Priority:** P1 · **Effort:** M

**Context:** Per `docs/research/2026-05-12-claude-for-legal-review.md` §9 (Q5 decision), Anthropic's `claude-for-legal` skills heavily reference a team-specific `CLAUDE.md` playbook (GREEN/YELLOW/RED thresholds, escalation rules, house style). LQ.AI's nearest analog is the Organization Profile — a singleton skill that shapes every other skill's behavior. The Profile was deferred from M1; this entry surfaces it as a v1.1+ candidate that unblocks calibration-driven skills (`nda-review`, `msa-review`, etc.) and is a prerequisite for substantive fold-in from upstream (DE-219).

**Specific scope:** Author the Organization Profile singleton skill (synthesized YAML, prepended to every other skill's system message at assembly time per ADR 0007). Authoring surface in `web/` (Settings → Organization Profile editor): house-style fields, jurisdiction defaults, escalation matrix, GREEN/YELLOW/RED threshold defaults, attorney-of-record. Per the input-default convention in `docs/skill-authoring-guide.md`, skills opt out via `lq_ai.use_organization_profile: false`; the Profile itself opts out so the assembler never recurses.

**Acceptance criteria:** Profile is authorable through a web UI; renders correctly in every applicable skill's assembled system prompt; first ported skill (DE-219 G.2) that depends on calibration (e.g., `nda-review`) demonstrably reflects the Profile's GREEN/YELLOW/RED thresholds.

#### DE-221 — Managed-Agents-equivalent (scheduled-agent runtime)

**Priority:** P2 · **Effort:** L

**Context:** Per `docs/research/2026-05-12-claude-for-legal-review.md` §9 (Q3 decision), several `claude-for-legal` plugins presuppose a scheduled-agent runtime that LQ.AI does not have: `renewal-watcher`, `docket-watcher`, `reg-feed-watcher`, `dataroom-watcher`, `launch-watcher`. The reference design exists in Anthropic's `managed-agent-cookbooks/` (`agent.yaml` + `subagents/*.yaml` + `steering-examples.json`). Per the decision, this is out of M1 scope and unlikely to land before v1.2+; filed here so the architectural shape can be referenced when scheduled-watcher demand materializes.

**Specific scope:** A scheduled-agent surface in LQ.AI is a cron + recurrence + handoff layer on top of the existing Inference Gateway. Multi-Wave investment, not a fold-in. Out of scope for the v1.1+ Wave G (which is the skill-installer + first port batch).

**Acceptance criteria:** Reference the Anthropic `managed-agent-cookbooks/` design for scope-shaping when this lands; LQ.AI's surface should support headless agents with cron triggers, recurrence rules, and a structured handoff format. The ported `*-watcher` skills from `claude-for-legal` are the natural first inhabitants.

### Process and project management

#### DE-050 — Skill quality bar / review process for community contributions

**Priority:** P1 · **Effort:** S

**Context:** The repository will accept community-contributed skills. The quality bar — what makes a skill mergeable, who reviews, how legal-substance accuracy is verified — is not yet documented.

**Specific scope:**
- Skill contribution guide.
- Required elements (SKILL.md, at least one worked example, frontmatter completeness).
- Required attestation that the skill's substantive content is accurate to the contributor's knowledge.
- Review process (at least one practicing attorney + one engineer reviewer for skills containing legal substance).
- Versioning and conflict-resolution rules.

**Acceptance criteria:** Process documented in `CONTRIBUTING.md` and `skills/CONTRIBUTING.md`; first community-contributed skill merged following the process.

#### DE-051 — Acceptance testing for the M1 skill set against real documents

**Priority:** P1 · **Effort:** M

**Context:** The 10 starter skills shipping in M1 have been authored but not extensively tested against real-world documents. Pre-launch acceptance testing should validate behavior on a corpus of real contracts.

**Specific scope:** Curated test corpus (anonymized real NDAs, MSAs, DPAs, etc.) with expected behavior documented. Run each skill against each relevant document in the corpus; compare actual output to expected.

**Acceptance criteria:** Test corpus exists; each starter skill has acceptance results documented; identified issues filed as bugs and addressed before public release.

### Security and compliance

This subsection consolidates security and compliance enhancements deferred from v1. Most are operationally important for specific verticals (federal contractors, regulated industries, high-assurance deployments) and were deliberately scoped out of v1 to keep the M1 release focused. The §1.8 Security Posture and Appendix E Pre-Empted Procurement Objections describe how the v1 baseline plus the Compliance Alignment Pack already match what closed-source commercial competitors offer; the items below are the next layer of hardening.

#### DE-100 — Tamper-evident audit log

**Priority:** P2 · **Effort:** M

**Context:** PRD §5.3 specifies a comprehensive audit log. For high-assurance deployments and litigation-readiness, the audit log should be tamper-evident: each entry is hash-chained to the prior entry (Merkle structure or signed-chain), and the chain root is published or anchored periodically.

**Specific scope:** Per-entry SHA-256 chain; periodic chain-root signing with a deployment key; verifier tool; documentation for incorporating the chain root into the operator's broader audit trail (e.g., publish to an internal blockchain, RFC 3161 timestamp, or public transparency log).

**Acceptance criteria:** Verifier confirms an unbroken chain across a sample audit log of >1M entries; documented procedure for the operator to detect and respond to a chain break.

#### DE-101 — Cryptographic timestamping of work product

**Priority:** P2 · **Effort:** M

**Context:** Legal work product has temporal significance: when did the analysis exist? When was the redline drafted? Cryptographic timestamping creates evidence that is admissible in litigation. Builds on the WorkProductAttribution metadata already captured in v1 (per §3.3).

**Specific scope:** Each model-generated artifact (chat response, redline, Playbook execution) is signed with a deployment key and accompanied by an RFC 3161 timestamp (or alternative — a signed entry in a transparency log such as Sigstore Rekor). Verifier confirms timestamp.

**Acceptance criteria:** Each artifact in the export bundle includes a verifiable timestamp; verifier tool ships with the project; documented procedure for using timestamps as evidence.

#### DE-102 — Hardware Security Module (HSM) and Vault integration

**Priority:** P2 · **Effort:** M

**Context:** PRD §5.6 specifies pgcrypto column-level encryption for sensitive fields including API keys. High-assurance deployments will require keys stored in an HSM or external secrets manager (HashiCorp Vault, AWS Secrets Manager, Azure Key Vault, Google Secret Manager).

**Specific scope:** Pluggable secrets backend in the Inference Gateway and main backend; reference adapters for HashiCorp Vault, AWS Secrets Manager, Azure Key Vault, Google Secret Manager. Documented key-rotation procedure.

**Acceptance criteria:** Reference deployments documented for each major secrets backend; key rotation tested in CI without service interruption.

#### DE-103 — IP allowlisting and geo-restriction

**Priority:** P2 · **Effort:** S

**Context:** Many enterprise deployments require IP-based access controls and geographic restrictions on user access.

**Specific scope:** Configurable IP allowlist applied at the web app and Word add-in entry points; configurable geo-IP-based restrictions with an integrated geo database (MaxMind or alternative). Operator chooses backend.

**Acceptance criteria:** Documented configuration; tested in CI; admin UI surfaces current rules.

#### DE-104 — Just-in-time admin elevation

**Priority:** P3 · **Effort:** M

**Context:** Modern privileged-access management practice requires admin elevation be explicit, time-bounded, and audited rather than persistent.

**Specific scope:** Admin role with short-lived elevation tokens; users with admin permissions must request elevation; elevations are logged with reason; auto-expiry after configurable period (default 60 minutes).

**Acceptance criteria:** Elevation flow tested; audit log captures elevations; no admin action permitted without active elevation.

#### DE-105 — Outbound proxy support

**Priority:** P2 · **Effort:** S

**Context:** Many enterprise networks require outbound traffic to traverse a corporate inspection proxy.

**Specific scope:** Inference Gateway supports `HTTPS_PROXY` / `NO_PROXY` configuration; documented integration with common corporate proxies (Zscaler, Palo Alto Networks, etc.); TLS interception trust handled gracefully.

**Acceptance criteria:** Documented configuration; tested against at least one corporate proxy implementation.

#### DE-106 — Configurable retention policies

**Priority:** P1 · **Effort:** M

**Context:** Operator should configure auto-purge schedules per resource type to satisfy data-minimization principles and storage management.

**Specific scope:** Configuration UI for retention by resource type (chats, files, audit log, autonomous-layer memory) and scope (personal, group, org). Background job applies policies. Litigation-hold flag suspends auto-purge for specified resources (see DE-109).

**Acceptance criteria:** Default policies documented; admin UI shows current policies and pending purges; litigation hold tested.

#### DE-107 — Operator-side data subject rights tooling

**Priority:** P1 · **Effort:** L

**Context:** A GDPR Article 15 (access) or Article 17 (deletion) request from a data subject who is *referenced* in chats, files, or audit entries (rather than being an LQ.AI user) requires the operator to find and produce or delete that subject's data across resources. Per-user export/delete (in v1, §5.3) handles users; this DE handles the harder case.

**Specific scope:** Admin tool that takes an entity (name, email, identifier) and surfaces all resources mentioning that entity, with options to redact (replace with pseudonym), delete (remove the resources), or export (produce as a bundle).

**Acceptance criteria:** Tool finds references at recall >95% on a test corpus; redaction does not break audit log integrity; export bundle is GDPR-compliant.

#### DE-108 — Backup encryption with rotation

**Priority:** P1 · **Effort:** M

**Context:** PRD §6.5 specifies pg_dump + MinIO snapshot backups. Production-grade backup requires encryption at rest with separate keys from the live deployment, key rotation, and restore-with-key-rotation testing.

**Specific scope:** Backup CLI tool encrypts bundles with operator-provided KMS key; restore tool handles key-rotation scenarios; documented key-management procedure.

**Acceptance criteria:** Backup-restore round-trip tested in CI with key rotation; documented procedure.

#### DE-109 — Litigation hold support

**Priority:** P2 · **Effort:** S

**Context:** When a matter is on litigation hold, auto-purge and certain user-deletion actions must be suspended to preserve evidence.

**Specific scope:** Admin-set litigation-hold flag at the resource or matter level; suspends auto-purge; warns users attempting to delete held resources; logged and audited.

**Acceptance criteria:** Held resources cannot be auto-purged; user-deletion attempts produce explicit blocked-by-hold messages with audit log entries.

#### DE-110 — Prompt-injection pattern library

**Priority:** P2 · **Effort:** M

**Context:** Documents from counterparties or external sources may contain prompt-injection attacks intended to manipulate the model. A community-maintained library of known patterns, scanned by the Inference Gateway, raises the bar.

**Specific scope:** Pattern library shipped as an inspectable skill; Inference Gateway middleware scans incoming context for matching patterns; matches are flagged in the response with a "potential injection detected" banner; severe matches can be configured to refuse.

**Acceptance criteria:** Library covers a baseline of published prompt-injection patterns; scanner adds <100ms latency; community contribution process documented.

#### DE-111 — Output-validation guardrails (generalized)

**Priority:** P2 · **Effort:** S

**Context:** Skills with structured output schemas (PRD §3.3 Citation Engine, JSON outputs in §3.7 Playbooks) already validate against schema. Generalize so any skill can declare an output schema and the application validates / refuses out-of-schema outputs.

**Specific scope:** Skill frontmatter `output_schema` field; runtime validator; failure modes (refuse, retry, surface partial).

**Acceptance criteria:** Pattern documented in skill-authoring guide; reference implementations on starter skills.

#### DE-112 — Model checksum verification for local models

**Priority:** P2 · **Effort:** S

**Context:** When Ollama pulls a model, supply-chain integrity for the model itself matters. Verify checksums against a known-good registry.

**Specific scope:** Configurable model-checksum allowlist; the deployment refuses to use models whose checksum is not on the list; documented procedure for adding new models to the allowlist with attestation.

**Acceptance criteria:** Reference allowlist provided; checksum verification adds <5s to first model-load; documented procedure.

#### DE-113 — FedRAMP-aligned deployment recipe

**Priority:** P2 · **Effort:** L

**Context:** Federal users (and federal contractors) require FedRAMP authorization. While the project itself does not pursue authorization, an alignment document and reference deployment recipe support operators pursuing FedRAMP Moderate (or aspirationally High) for their environment.

**Specific scope:** `docs/compliance/fedramp-alignment.md`; reference deployment recipe targeting FedRAMP Moderate baseline (Tier 1 or Tier 2 inference required, FedRAMP-authorized cloud provider, specific configuration of audit log, encryption, and access controls); SCAP / OSCAL artifacts where applicable.

**Acceptance criteria:** Document published; reference recipe deployable; gap analysis identifies items requiring operator implementation.

#### DE-114 — Reproducible builds

**Priority:** P2 · **Effort:** M

**Context:** Verifying that a deployed image matches the source requires reproducible builds: any party rebuilding from the release tag produces a bit-identical image. Builds on the SLSA-3 build provenance committed in v1 (§7.8); reproducibility is the next layer.

**Specific scope:** Container build configuration deterministic (pinned base images, deterministic timestamps, deterministic dependency installation); CI verifies reproducibility on each release.

**Acceptance criteria:** Two independent builds at the same release tag produce identical image digests; verification tool ships with the project.

#### DE-115 — Formal Vulnerability Disclosure Program (VDP)

**Priority:** P3 · **Effort:** S

**Context:** PRD §7.6 specifies coordinated disclosure via SECURITY.md. A formal bug bounty or VDP with published scope, safe-harbor language, and (optionally) monetary rewards encourages security research.

**Specific scope:** Published VDP under a recognized framework (HackerOne, Intigriti, or self-hosted); safe-harbor language; published past disclosures with attribution; optional rewards for critical findings.

**Acceptance criteria:** VDP published; safe-harbor reviewed by counsel; first reported and fixed disclosure referenced.

#### DE-266 — Tier-floor warning surface for privileged matters

**Priority:** P2 · **Effort:** M

**Context:** `Project.privileged=true` forces a minimum inference tier (default Tier 2; configurable to Tier 1 — see §3.11). Tier 2 in PRD §1.5.2 means "enterprise managed inference with ZDR / no-training commitments." But "Tier 2" is shorthand for whichever provider the operator has configured as their Tier-2 routing target — and that provider may or may not have a BAA signed, may or may not have a confirmed ZDR commitment, and may or may not be configured in a HIPAA-eligible mode. Without an explicit warning surface, the operator can mark a Project `privileged: true` and assume the configured Tier 2 satisfies the implied compliance posture when the provider was in fact misconfigured. The audit log captures the routing but not the inconsistency.

**Specific scope:** Admin-side warning in Project settings when a Project marked `privileged: true` would route to a provider whose Tier-2 configuration is incomplete: no `baa: true` flag in the provider config block; no `zdr_confirmed: true` annotation; no documented HIPAA-eligible operating mode (where relevant). The warning is a soft signal, not a block — the operator may have compensating controls (BAA executed out-of-band, for example) — but the warning surfaces the inconsistency so the operator can resolve it knowingly. Audit log captures the warning's display + the operator's acknowledgement with reason.

**Acceptance criteria:** Warning fires for each misconfiguration pattern above; admin can acknowledge with a captured reason; audit log records both the warning event and the acknowledgement; documented in `docs/security/privileged-matter-configuration.md`; Cypress E2E covers the warning surface.

#### DE-268 — Skill-capture prompt-injection sanitization

**Priority:** P1 · **Effort:** M

**Context:** M1's skill-capture flow (per `web/cypress/e2e/wave-d2-skill-creator.cy.ts` Test 1) takes a user-selected chat message and persists it as a new user-scope skill. If the message originated from a counterparty document ingested into the chat (a PDF, DOCX, or pasted text), prompt-injection content embedded in that document could be captured into the user's persistent skill library — a quiet backdoor across sessions. The user-confirmation step exists but does not surface the injection pattern; the capture happens at face value.

**Specific scope:** Capture-confirmation UI integrates the prompt-injection pattern library (DE-110) — when the captured text matches any high-confidence injection pattern (instruction-overriding phrases, role-hijack templates, encoded-instruction patterns from the Garak / PyRIT / MITRE ATLAS corpora), the confirmation dialog highlights the match and asks the user to review before saving. Optional structured-output gate: if the captured text contains content the schema would not validate (embedded `system:` markers, JSON instruction blocks), the capture is paused with a structured warning. Audit log row per capture event records a SHA-256 hash of the captured content + the injection-pattern match list (if any).

**Acceptance criteria:** Capture of a chat reply containing a known injection pattern triggers the warning; the warning is keyboard-focusable; audit log captures the event with content hash + pattern matches; Cypress E2E covers both the clean-capture happy path and the warning-triggered review path.

#### DE-269 — Anonymization Option A: pseudonymize source documents too

**Priority:** P3 · **Effort:** M

**Context:** Per **Decision M2-1** (M2 plan kickoff), the Anonymization Layer (§4.7) pseudonymizes only chat and skill content sent to the model; retrieved source documents stay un-pseudonymized so the model sees intact source quotes for citation grounding (§3.3). M2-D2 implements this by marking the retrieval-context system message with `lq_ai_skip_anonymization=True` so the gateway's pre-middleware leaves the content unchanged. The provider therefore sees:

- Pseudonymized user/assistant chat content (`PERSON_0001` etc.)
- Un-pseudonymized retrieved source chunks (`John Smith ...` from the source file)

If the source-document corpus contains entities the operator considers sensitive (counterparty names, deal amounts, regulated identifiers), those entities reach the provider in cleartext as part of the retrieval payload. **Option A** is the alternative architecture: pseudonymize the source-document corpus too, on a copy used only for inference; render originals to the user via the rehydrator on the response path.

**Specific scope:** Trade-offs to resolve:

- **Citation grounding.** Stage 1 (exact-match) and Stage 2 (tolerant-match) verifiers read `documents.normalized_content` (un-pseudonymized) and compare against the model's emitted quote. Under Option A the model would quote `PERSON_0001`-style strings; the post-rehydrator would substitute originals before citation extraction sees them. This works today (the M2-B3 + M2-C3 round-trip suite implies it), but introduces an extra translation hop in the citation correctness path. Calibration of the cascade thresholds (M2-E2) might need re-running.
- **Per-request pseudonym stability across mappers.** The per-request mapper already produces stable assignments for the same `(entity_type, original)` pair across user turn + retrieval. Under Option A, the same entity in multiple source documents would consistently pseudonymize to the same value within one request — but pseudonyms drift across requests, which is fine for one-shot Q&A but might surprise users who follow-up with `"What about COMPANY_0001?"` in a subsequent turn. Probably needs a cross-conversation stability mechanism (DE-XXX).
- **Audit-log shape.** `inference_routing_log.anonymization_applied=true` would now be the common case rather than the careful-case; the field becomes less informative. May want a more granular signal (`anonymization_scope = "chat" | "chat+sources"`).
- **Model reasoning quality.** Empirical question: does the model produce worse outputs when it must reason against pseudonymized source content rather than originals? A spot-check on the NDA Review / MSA Review skills before deciding to ship Option A.

**Acceptance criteria:** Spot-check empirical study comparing model output quality on Option A vs M2-1 for at least three skills (NDA Review, MSA Review SaaS, DPA Checklist Review); cross-conversation pseudonym stability decision documented or filed as DE-XXX; audit-log shape extended if needed; `docs/security/anonymization.md` and `docs/citation-engine.md` updated to reflect Option A as the new default; existing M2-B3 / M2-C3 / M2-D2 round-trip tests passing with the new shape.

#### DE-270 — Cryptography review: Fernet vs modern AEAD

**Priority:** P3 · **Effort:** S

**Context:** Provider-key encryption at rest uses Fernet (AES-128-CBC + HMAC-SHA256) per `gateway/app/secrets.py` and ADR 0011. Fernet is robust (RFC-style spec, widely deployed, no known break) but is from the `cryptography` library's 0.6 release (2014) and is not a modern AEAD — it uses encrypt-then-MAC rather than a single-pass authenticated mode. Modern alternatives are AES-GCM, ChaCha20-Poly1305, and libsodium's secretbox. The current choice is defensible (Python ecosystem ubiquity, stable key format, well-understood migration path) but a security reviewer will ask the question.

**Specific scope:** Update `docs/security/cryptography.md` and ADR 0011 to either (a) justify the Fernet choice explicitly with the comparison against modern AEADs and the trade-off articulated, or (b) migrate to a modern AEAD (e.g., AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`) with a documented backward-compatible key-rotation procedure that re-encrypts existing master-key-wrapped provider keys at startup. Either path produces a defensible written record a procurement security team can cite.

**Acceptance criteria:** Either Fernet is justified in writing with the comparison and trade-off articulated, or the migration is implemented with a migration ADR and a re-encryption procedure tested in CI; ADR 0011 reflects the resolved decision; cryptography reference (`docs/security/cryptography.md`) updated accordingly.

#### DE-271 — Dependency-criticality matrix + fallback plan

**Priority:** P2 · **Effort:** M

**Context:** The SBOM (per §7.8) enumerates all dependencies but does not classify them by criticality to the application, nor document a fallback plan if a critical dependency changes terms or is abandoned. The procurement question "if your dependency tree shifts under you, what's your plan?" currently has no anchor — particularly for the dependencies with structural risk: OpenWebUI fork (license/governance shift risk, per ADR 0001's pin-and-monitor posture), Docling (parser correctness; alternatives exist but with different output shapes), PyMuPDF (AGPL-3.0 boundary; if PyMuPDF's licensing changes, the project's distribution posture must adapt), pgvector (vector storage; tied to Postgres major-version compatibility), and Mistral OCR API (paid; not air-gappable).

**Specific scope:** Publish `docs/security/dependency-criticality.md` with: per-dependency criticality tier (T1 critical = swap is months of work, T2 substantial = swap is weeks, T3 routine = swap is hours-to-days); license-change risk per dep (current license + history of license changes if any); abandonment risk per dep (maintainer count, commit cadence, last release); documented fallback per T1 dep ("if OpenWebUI re-licenses, fork pin at current commit + maintain delta; if PyMuPDF re-licenses, evaluate pikepdf as drop-in replacement with reduced byte-precision; if Docling is abandoned, fall back to Apache Tika + custom parser layer"). The matrix is verifiable against the SBOM and updated per release.

**Acceptance criteria:** Document published at `docs/security/dependency-criticality.md`; every dependency in the SBOM classified to a tier; every T1 dependency has a documented fallback plan; document referenced from PRD §1.8, Appendix E, and the security pack README.

#### DE-273 — Audit log API: server-side actor enrichment

**Priority:** P2 · **Effort:** S

**Context:** The audit log API (`GET /api/v1/admin/audit-log`) returns rows with `user_id` (UUID) but no actor enrichment — no email, no display_name. Any UI rendering audit entries must issue a second `/users/{id}` lookup per row to display "who did this" labels, producing an N+1 query pattern. Operators reading the raw JSON cannot tell who an entry refers to without joining manually against the `users` table.

Surfaced in the fresh-install evaluation (2026-05-14) as a usability gap, not a security gap — the data is correct, just unfriendly.

**Specific scope:** Either (a) server-side join — return `user: { id, email, display_name }` instead of (or alongside) bare `user_id`, so the response is self-contained; or (b) add a bulk `/api/v1/users?ids=...` endpoint so the frontend can batch the lookup. Path (a) is preferred for simplicity. Handle the soft-deleted user case explicitly — `user_id` pointing at a deleted row should still render something meaningful, e.g. `{ id, email: "<deleted user>", deleted_at: ... }`, rather than dropping the row or returning `null`.

**Acceptance criteria:** The audit-log response renders actor labels without an additional round-trip; soft-deleted user references resolve to a stable display string; OpenAPI schema reflects the new shape; existing audit-log Cypress E2E updated to assert on the enriched shape.

#### DE-274 — Anonymization pseudonym-collision in source documents

**Priority:** P3 · **Effort:** S

**Context:** The Anonymization Layer (§4.7 / M2-B3) generates pseudonyms in the deterministic format `{ENTITY_TYPE}_{NNNN}` (e.g., `PERSON_0001`, `MATTER_NUMBER_0042`). On the response path, the rehydrator scans the model's output for these patterns and substitutes the originals back from the in-process mapper.

Two distinct collision surfaces this format leaves open:

1. **Source-doc collision.** If a source document happens to contain a literal string matching the pseudonym pattern (e.g., a contract template that literally uses `PERSON_0001` as a placeholder, or a procedural document that references `EMAIL_ADDRESS_0023` from a different system) — and the model's response quotes that string — the rehydrator today does nothing to it (no matching mapper entry, so `str.replace` is a no-op). The literal string is preserved on the way out — the **safe** path. The risk is that future rehydrator changes (e.g., logging unmatched patterns for operator debugging) could turn this into a (minor) leak path.

2. **Cross-mapper collision** (surfaced by the M2-C3 round-trip suite). Because the format is `{ENTITY_TYPE}_{NNNN}` with no per-request salt, two parallel mappers both produce `PERSON_0001` for their respective first PERSON span. Production isolation works because mappers are per-request and dropped on function exit — there is no production path that rehydrates one request's output against another request's mapper. But the data structure offers no cryptographic distinctness; isolation is **scope-enforced**, not collision-prevented. A future architectural change (e.g., caching mappers across requests for any reason) would silently break isolation without surfacing as a test failure.

Both surfaces are pinned by the M2-C3 round-trip test suite so a future change is visible in CI rather than silent. The current pinned behavior is documented in `docs/security/anonymization.md`.

**Specific scope:** Two paths, either acceptable:

- **(a) Per-request random salt on pseudonym generation.** Change `PseudonymMapper.assign` to produce `{ENTITY_TYPE}_{NNNN}_{salt}` where `salt` is a per-request short random suffix (e.g., 4-6 hex chars from `secrets.token_hex`). Source documents that happen to contain the bare `PERSON_0001` form would no longer collide; two parallel mappers would produce structurally distinct pseudonym strings even at the same counter slot, eliminating the cross-mapper collision surface as well. Cost: rehydrate's regex gets one more group; the pseudonym strings the provider sees are 5-7 chars longer.
- **(b) Pre-scan source documents for pseudonym-shaped patterns at retrieval time, and either skip the request or escalate the pseudonym counter to a larger digit width when a collision is detected.** More complex; addresses only the source-doc collision, not the cross-mapper one; harder to compose with the cross-conversation stability invariant.

Path (a) is recommended; the salt is the smaller change with cleaner round-trip semantics and closes both collision surfaces with one move.

**Acceptance criteria:** No source document containing a literal pseudonym pattern can confuse the rehydrator's behavior; two parallel mappers produce structurally distinct pseudonym strings (verified by an updated round-trip test); the mapper's pseudonym format is updated; existing M2-B3 / M2-C3 tests pass with the new format (the cross-mapper test in `test_round_trip.py` flips its assertion when this lands — the test's docstring already calls this out); the change is documented in `docs/security/anonymization.md`.

#### DE-275 — Embed M2 citations in chat-message envelope

**Priority:** P3 · **Effort:** S

**Context:** M2-C2 wires the frontend to `GET /api/v1/chats/{chat_id}/messages/{message_id}/citations` as a lazy fetch immediately after each assistant message renders. The endpoint already exists (M2-A2) and the lazy-fetch path is the smallest change to surface the five-state citation UI without disturbing the chat-streaming pipeline. The cost is one extra round-trip per assistant message; in practice it runs in parallel with the user typing their next message, so end-user-perceived latency is near-zero on a healthy network.

The structural cost is a second request per message — more api/ load, more network traffic, and a small extra failure mode (the citations fetch could fail independently of the chat response). A future refactor could embed the citation rows directly in the assistant-message JSON envelope so they land alongside `content`, removing the second round-trip entirely. M2-D2 (Citation Engine integration with the chat-send path) is the natural moment to revisit this; if measured latency or backend load shows up as a concern in the M2-F2 acceptance corpus, this DE is the path forward.

**Specific scope:** Extend the assistant-message response shape (the chat-send return value and the chat-message read endpoint) to include a `citations` field — same per-row schema as `GET /messages/{id}/citations` returns, including `partial`. Update the frontend renderer to prefer the embedded citations when present and fall back to the lazy GET for older messages (or when the field is absent — e.g., a skill that doesn't emit citations). Keep the GET endpoint operational regardless; it remains the canonical surface for direct citation lookup (audit-log deep-linking, debugging, future operator tooling).

**Acceptance criteria:** New assistant-message responses include a `citations` array reflecting the same data the GET endpoint returns; the frontend renders citations from the embedded data without an additional fetch when present; messages persisted before this lands continue to render correctly via the GET fallback; existing M2-C2 component tests pass with both data paths; `GET /messages/{id}/citations` is unchanged and remains the canonical source-of-truth endpoint.

#### DE-276 — Ingest observability: surface silent embed/parse failures

**Priority:** P2 · **Effort:** S-M

**Status:** **SHIPPED at M3-0.3** (Phase 0, pre-M3 hardening). Implemented as a broader-than-PRD-original scope per the M3 plan: `documents.ingest_status` (enum: `ok | parse_failed | embed_failed | partial`) + `documents.ingest_failure_reason`, the embed worker flips the status on batch failure / clears it on recovery, and `GET /api/v1/admin/ingest-health` aggregates document-level signals plus the existing file-level `files.ingestion_status='failed'` count into a single admin-visible summary. The KB-detail UI surfaces the more-severe of the two signals per row (file-level parse failure ranks above doc-level embed failure ranks above partial-embed). `parse_failed` is reserved on `documents.ingest_status` for forward-compat — today parse failures stop before a `documents` row is created.

The CI-guard portion of the original specific-scope (option c — fresh-install fixture upload that asserts non-NULL embeddings) is deliberately deferred — operators get the in-product alarm immediately via the new endpoint, and the dry-run pattern can be filed as a follow-on DE rather than coupled to this PR.

**Original context (preserved for the historical record):** Surfaced during M2-C2 manual verification on 2026-05-16, a KB-grounded chat returned "I don't have any NDA document in our conversation" despite the KB showing a successfully-attached document. Investigation found the document had been chunked correctly (16 chunks of real NDA text) but every chunk's `embedding` was NULL. Root cause: the ingest worker's `embed_chunks_for_file_job` was failing with `KeyError: 'LQ_AI_GATEWAY_URL'` because the worker container was missing the gateway env vars in `docker-compose.yml`. The worker reported `chunks_embedded: 0` and ARQ logged a one-line truncated error, but no surface in the product (admin UI, document status field, /admin/ingest-health endpoint) escalated this to operator-visible state — the document continued to render as "ready" and KB-attach UI showed it as if it were searchable. The immediate root cause was patched in a follow-on commit; this DE captures the broader observability gap.

The failure mode is structurally bad: a deployment misconfiguration (missing env var, gateway unreachable, embedding-model permissions revoked) silently degrades KB hybrid retrieval to FTS-only across the entire deployment. Operators have no in-product signal until an end-user reports "the AI can't see my documents". The current `documents` table has no embed-state column, and the ingest worker's structured logs are not surfaced anywhere an admin reads.

**Specific scope:** Three paths, ideally landed together:

- **(a) Document-level embed status.** Add `documents.embedding_status` (enum: `pending`, `embedded`, `failed`) populated by `embed_chunks_for_file_job` per its return value. `failed` rows carry a `last_error` text field (the same string the worker already returns). Default `pending` for legacy rows; backfill from a one-time sweep that checks `EXISTS (SELECT 1 FROM document_chunks WHERE document_id = d.id AND embedding IS NULL)`.

- **(b) Admin-visible state.** Surface the new status in the admin KB-detail UI and a new `GET /api/v1/admin/ingest-health` summary endpoint. Failed-embed rows show up with their error text; the admin can decide to re-trigger the embed job per-document or per-KB. Per `[[reference_lq_ai_dev_quirks]]` the operator-facing audit-health pattern (DE-257) is the right precedent.

- **(c) CI guard against the specific regression.** Add a fresh-install validation step (per `[[feedback_dry_run_value]]`) that uploads a small fixture document, waits for `documents.embedding_status='embedded'`, then asserts at least one chunk has a non-NULL `embedding`. This is the canonical guard against the env-var class of failure — it would have caught the present bug at deploy time, not at user-report time.

**Acceptance criteria:** `documents.embedding_status` is populated for every newly-ingested document and updates correctly on retry; the admin UI surfaces failed-embed documents distinctly from ready ones; an end-to-end test against a fresh-install stack uploads a fixture document and asserts the chunks come back embedded (not FTS-only); the gateway-misconfigured-worker class of bug surfaces as a CI failure on PR review rather than a silent production degradation.

#### DE-277 — Citation extractor: fallback to document scan on chunk-boundary miss

**Priority:** P3 · **Effort:** S

**Context:** Surfaced during the M2-D4 edge-case sweep. The Citation Engine's extractor (`app/citation/extraction.py::extract_citations`) locates each quote by calling `_locate_in_chunk(quote, chunk.content)` against the single chunk the model cited via `(Source: [N])`. If the quote spans the boundary between two adjacent retrieved chunks — i.e., the quote is present in `documents.normalized_content` but in neither chunk's individual content — the locator returns `None` and the candidate is dropped silently. No row is persisted; the M2-C2 UI renders the marker as "unverified" (red) even though the underlying document text matches.

In practice the model usually picks the chunk containing the full quote (the retrieval-context block instructs it to). The gap surfaces on adversarial multi-chunk paraphrases or when the model genuinely needs to cite text crossing a chunk seam — both rare but not impossible.

The verifier itself reads against `documents.normalized_content` (un-chunked) and would verify a spanning quote correctly if it ever saw the candidate. The fix is upstream in extraction.

**Specific scope:** Extend `_locate_in_chunk` (or the surrounding loop in `extract_citations`) to fall back to a full-document scan when the chunk-local search misses. Two-stage logic, mirroring the within-chunk pattern:

- **Stage A — chunk-local exact:** current behavior.
- **Stage B — chunk-local fuzzy:** current behavior.
- **Stage C — full-document exact:** if A and B both miss, FK-load the chunk's parent document and `_locate_in_chunk(quote, doc.normalized_content)`. Resolved offsets are document-absolute (no `chunk.char_offset_start` arithmetic needed).
- **Stage D — full-document fuzzy:** if C misses, fuzzy-search the full document. Resolved offsets again document-absolute.

The persisted citation row's `source_offset_start` / `source_offset_end` already index into `documents.normalized_content` (not the chunk), so the downstream Stages 1–4 verifier consumes the document-absolute offsets without any further change.

**Edge case the fix introduces:** a quote that's NOT in the cited chunk but IS elsewhere in the document — possibly the model cited the wrong chunk index. Stage C/D would surface this as verified, masking the mis-cite. Two-option resolution: (a) accept this as a feature (the verification is what matters; chunk-index correctness is decorative); (b) when Stage C/D fires, log a `citation_chunk_mismatch` warning so operators can spot model-side drift. Recommend (b) for observability.

**Acceptance criteria:** the existing `test_chunk_boundary_spanning_citation_does_not_extract_today` test flips its assertion (rows DO persist; `verification_method='exact_match'`); a new test pins the chunk-mismatch warning case; no regression in the existing extraction test suite; `docs/citation-engine.md` "Known limitations" entry on chunk-boundary spanning is updated to either remove the limitation or note the residual chunk-mismatch behavior.

#### DE-278 — Azure OpenAI AD authentication (managed identity / service principal)

**Priority:** P2 · **Effort:** S

**Context:** M2-E1 (DE-267) shipped the Azure OpenAI adapter with API-key authentication only, deferring the Azure AD path to keep the M2-E1 budget at ~4 hr. Many Azure-tenant enterprise deployments disable long-lived API keys entirely and require token-based auth through Azure AD: either a managed identity (when the gateway runs on Azure compute — VM, AKS, Container Apps) or a service principal (when the gateway runs anywhere else but the operator wants AD-mediated access to the Azure OpenAI resource). Operators in this posture currently either provision a long-lived API key (a workaround that contradicts their Azure governance), wait for this DE, or run a custom auth proxy in front of the gateway.

**Specific scope:** Extend `gateway/app/providers/azure_openai.py` to accept an `auth_mode: ad` flag in the provider config (alongside the existing `auth_mode: api_key` default). When `ad` is set, the adapter uses `azure-identity` (the official Azure SDK auth library) to acquire a token via `DefaultAzureCredential` — which transparently tries managed identity, then a service-principal env-var triple (`AZURE_CLIENT_ID`/`AZURE_CLIENT_SECRET`/`AZURE_TENANT_ID`), then other AD sources. Tokens are scoped to `https://cognitiveservices.azure.com/.default` and cached in-memory with the SDK's built-in refresh handling. The `_auth_headers` override emits `Authorization: Bearer <token>` instead of `api-key: <key>`. The `azure-identity` dep adds ~3 MB of transitive packages (msal, msal-extensions, cryptography is already pinned); SBOM impact reviewed at PR time.

**Edge cases to handle:**

- **Token refresh under streaming.** SSE streams can outlast a token's 1-hour lifetime. The `azure-identity` cache returns a fresh token on each `get_token()` call so the streaming iterator must re-fetch the header per HTTP request, not cache it on the adapter instance.
- **Missing AD environment when `auth_mode: ad`.** Construction surfaces a clear startup `ValueError` if the credential chain finds no usable source (e.g., the gateway is configured for AD but running locally with no service-principal vars set).
- **Mixed-mode providers.** Some operators run multiple Azure providers — one AD-authenticated production tenant, one API-key dev tenant. The config takes `auth_mode` per-provider; no global toggle.

**Acceptance criteria:** `auth_mode: ad` provider entries construct cleanly under managed identity (validated in a CI integration test that mocks `DefaultAzureCredential`); the `Authorization: Bearer <token>` header is set on chat/embeddings/health calls (mocked); a regression test pins that `api-key` is NOT set when `auth_mode: ad`; `gateway.yaml.example` documents both auth modes with a comment block; `azure-identity` added to the gateway's `pyproject.toml` with the same pin discipline as other deps; SBOM diff reviewed; one mocked integration test exercises the AD path end-to-end through the FastAPI lifespan.

#### DE-279 — Case citation validation (Bluebook resolution via CourtListener)

**Priority:** P1 · **Effort:** M

**Context:** The M2 Citation Engine validates **type 1** of three distinct citation-checking surfaces ("KB-quote accuracy" — does a model's quote and the meaning it draws accurately represent a document in the operator's KB). The other two surfaces are not built and require architecturally distinct components:

- **Type 2 (this DE) — case citation validation:** given a citation string in Bluebook form (e.g., `Smith v. Jones, 123 U.S. 456 (2020)`), verify that it refers to a real, resolvable judicial opinion. Catches the "the model fabricated a case" failure mode. Distinct from type 1 because the source-of-truth is not an operator-owned document but an external case database.
- **Type 3 — case-content accuracy:** see [DE-280](#de-280--case-content-accuracy-statement-vs-judicial-opinion).

Type 2 is high-priority for any deployment used in litigation work — a fabricated case citation in a brief or memo is the canonical embarrassment-and-sanctions story (e.g., the 2023 *Mata v. Avianca* sanctions). The architectural slot exists in the project's transparency posture (every model-emitted claim is checkable), and Tucuxi-Inc has reference prior art at [`Tucuxi-Inc/Legal-Week-Cite-Checker`](https://github.com/Tucuxi-Inc/Legal-Week-Cite-Checker) — a working implementation of Bluebook-citation detection + CourtListener resolution that can be ported and adapted to the LQ.AI stack.

**Specific scope:**

- New module `api/app/citation/case_resolver.py` with a Bluebook-citation detector (regex + parser; the Legal-Week-Cite-Checker port covers the common Bluebook forms: U.S. Supreme Court reporters, federal reporters F./F.2d/F.3d/F. Supp., state reporters, parallel citations) and a CourtListener client.
- CourtListener resolution uses the public FreeLaw Foundation API (`https://www.courtlistener.com/api/rest/v3/`). Authentication via an operator-supplied API token (env `LQ_AI_COURTLISTENER_TOKEN`); the API is free for reasonable use but the token improves rate limits.
- New `message_case_citations` table mirroring the shape of `message_citations` (id, message_id, citation_string, normalized_form, courtlistener_opinion_id, resolution_status, resolved_at). Migration follows the existing alembic versioning.
- Detector runs on every chat response (parallel with type-1 verification — same pre-render guarantee). Failed resolutions surface in the UI as "unverified case citation — could not resolve" (same chip vocabulary as type 1 for UX consistency).
- Configurable per-deployment: `citation_engine.case_validation.enabled: bool` in `gateway.yaml` so operators with no litigation use case can skip the CourtListener dependency.

**Privacy + transparency implications:** the citation string itself is the only data sent to CourtListener — no claim text, no surrounding context, no user identifier. CourtListener is operated by the Free Law Project (501(c)(3) non-profit) which publishes a clear privacy posture; the request shape is auditable in the routing log.

**Acceptance criteria:** detector recognizes ≥95% of citation strings in a curated test set covering the major Bluebook forms; resolution succeeds for ≥98% of real citations and ≤2% for fabricated citations (false-positive rate); a Cypress E2E exercises the failed-resolution UI state; CourtListener-down failure mode handled gracefully (citation marked "unverified — resolver unavailable", not blocked); documented end-to-end in `docs/citation-engine.md` under a new §2 "Case citation validation"; integration with the existing `message_citations`-style audit row in `api/app/api/chats.py`.

#### DE-280 — Case-content accuracy (statement vs judicial opinion)

**Priority:** P1 · **Effort:** L

**Context:** **Type 3** of the three citation-checking surfaces (see [DE-279](#de-279--case-citation-validation-bluebook-resolution-via-courtlistener) for the taxonomy). Given a statement the model makes *about* a case — what it held, what its reasoning was, what facts it relied on — verify that the statement is an accurate, non-cherry-picked representation of the underlying judicial opinion. Hardest of the three because the source-of-truth (opinion full text) is long, the model's statement is short, and "accurate representation" is a paraphrase-semantics judgment that the existing Stage-3 paraphrase judge (type 1) handles only over short retrieved chunks.

**Scope considerations:**

- **Source-of-truth fetch.** Once a case citation resolves through DE-279, the full opinion text is retrievable from CourtListener (`/api/rest/v3/opinions/<id>/`). Opinions are often 10–50 pages; the judge must reason over the whole opinion, not a single chunk. This is a different verification surface than type 1's chunk-scoped paraphrase judge.
- **Statement extraction.** The chat model emits statements about cases inline — `"the Smith court held that …"`. A detector pairs each statement with the case citation it references (the model is prompted to colocate them; absent colocation we fall back to nearest-citation heuristic).
- **Paraphrase-vs-cherry-pick distinction.** A statement can be technically accurate (the opinion does say *X*) but misleading (the opinion's holding turned on a fact the statement omits). The judge prompt needs to evaluate both fidelity and completeness — a meaningful step beyond type 1's "does this quote support this claim" surface.
- **Calibrated gold set.** Required for confidence thresholds. ~50 statement-vs-opinion pairs reviewed by an attorney for ground truth; calibrate the judge to ≥0.85 precision at recall ≥0.70 before declaring a verdict. This is the one place in the three-type taxonomy where attorney attestation in the contribution path is genuinely load-bearing (the gold set's quality determines what verdicts the system produces in production).

**Specific scope (M4 target):**

- New module `api/app/citation/case_content_judge.py` with a paraphrase-semantics judge over full opinion text. Uses the same gateway-judge surface as type 1's Stage 3 (`paraphrase_judge`), but with a longer-context model and a prompt structured for fidelity + completeness evaluation.
- Token-cost handling: opinion full text + statement + judge prompt = ~10-30k input tokens per judgment. Pre-flight cost budget mirrors the existing M2-D1 ensemble pre-flight; falls back to "unverified — over-budget" when a deployment hits its cap.
- Statement detector + citation pairing — built on top of DE-279's detector.
- New `message_case_statements` table for the verdicts.
- UI state: case-statement chips render alongside type-1 KB chips. Same hover/click affordances; same verbal vocabulary.
- Calibrated gold set committed at `eval/case-content-accuracy/` with attorney-reviewed annotations.

**Acceptance criteria:** judge calibrated against the gold set (≥0.85 precision @ ≥0.70 recall); end-to-end integration with DE-279 (a chat response with a case statement triggers DE-279 resolution + DE-280 content check in parallel); UI renders the case-statement verdict alongside KB-quote verdicts; cost-budget pre-flight handles long-opinion edge cases; documented end-to-end in `docs/citation-engine.md` under a new §3 "Case content accuracy"; depends on DE-279 landing first.

#### DE-281 — Citation Engine operational-telemetry calibration (TOLERANT_MATCH_THRESHOLD + aggregation_rule)

**Priority:** P2 · **Effort:** S

**Context:** M2-E2 calibrated the per-judge-call cost pre-flight against the routing log (replacing the M2-D1 flat `FLAT_PER_JUDGE_USD = 0.005` constant with per-model rolling averages). Two other Citation Engine constants were originally scoped for M2-E2 calibration in the M2 plan but were not addressed because they require empirical workload data the project did not collect (M2-F1 closed via scope reframe rather than building an annotated corpus):

- **`TOLERANT_MATCH_THRESHOLD = 95.0`** at `api/app/citation/verification.py:138` — rapidfuzz threshold for Stage 2 (tolerant-match) acceptance. 95 catches normalization-only differences (smart quotes, whitespace collapse, OCR confusions) while rejecting genuine paraphrases (~70-90 range) that belong to Stage 3. The 95 boundary is plausible but empirically uncalibrated — a real workload might want 92 or 97 to land on the precision/recall sweet spot.
- **`aggregation_rule: strict`** default in `gateway.yaml.example` and `gateway/app/config.py` — Stage 4 ensemble aggregation. Strict requires unanimous agreement across N judges; majority needs N/2+1. The "strict produces too many verified-with-caveats surfaces" vs "majority is too permissive" tradeoff is a UX-and-correctness call that depends on observed disagreement rates the project hasn't measured.

**The M2-E2 substrate enables this:** the per-purpose routing-log column (added in migration 0029) and the rolling-average query infrastructure (`api/app/citation/cost.py`) generalize cleanly to per-stage verdict telemetry. The same machinery that calibrates cost can calibrate accuracy once production deployments accumulate enough chat-send → citation-verdict telemetry to compute disagreement rates and stage-pass distributions.

**Specific scope:**

- Extend `inference_routing_log` (or add a sibling `citation_verdict_log` table) to record per-citation Stage-1-vs-Stage-2-vs-Stage-3 outcomes when Stage 4 ensemble fired, including the per-judge verdict tuples. Lets operators see "of the last 1000 ensemble verifications, how often did the 3 judges agree?" without a synthetic corpus.
- New admin endpoint `GET /admin/v1/citation-calibration` exposing rolling stats: Stage 1 pass rate, Stage 2 pass rate (of Stage 1 misses), Stage 3 pass rate (of Stage 2 misses for single-judge), Stage 4 disagreement rate (per-judge tuple distribution), per-stage average cost.
- Calibration recommendations: when disagreement rate exceeds X%, the admin surface suggests flipping `aggregation_rule` to `majority`. When Stage 2 pass rate is near-zero, suggest lowering `TOLERANT_MATCH_THRESHOLD`. When near-100%, suggest raising it.
- `gateway.yaml` accepts both constants as configurable values (operators can override the defaults per deployment based on the recommendations).

**Why deferred:** the current values are conservative and operator-overridable; no production deployment has accumulated the telemetry needed to calibrate them. The M2-E2 cost calibration shipped because per-model judge cost has obvious order-of-magnitude variation that's measurable from published price sheets; threshold + aggregation calibration both require observing how operators' real workloads behave, which is post-v0.2 work.

**Acceptance criteria:** admin endpoint surfaces per-stage rolling stats with at least 30 days of telemetry; calibration recommendations match the documented decision rules; `gateway.yaml.example` adds documented override knobs for both constants; integration test exercises the recommendation logic against seeded telemetry data; `docs/citation-engine.md` adds a "Calibration" section linking the constants to the telemetry surface.

#### DE-282 — Anonymization Layer empirical validation on legal-document corpus

**Priority:** P1 · **Effort:** M (10–14 hours of focused work; structured for incremental community contribution)

**Status:** **Open — community contribution welcomed.** This DE captures the original [M2-F2 plan scope](M2-IMPLEMENTATION-PLAN.md#task-m2-f2--anonymization-acceptance-test-corpus) which the maintainers chose not to ship in v0.2 in favor of transparent disclosure of the validation gap (see [`docs/security/anonymization.md` §"What's validated vs what's unvalidated"](security/anonymization.md#whats-validated-vs-whats-unvalidated)). The choice keeps v0.2's ship cadence intact while inviting contributions from practitioners whose practice areas have specific recognizer needs.

**Context:** The M2 Anonymization Layer (§4.7) enables 6 Presidio default recognizers (`PERSON`, `ORGANIZATION`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `US_BANK_NUMBER`, `LOCATION`) plus 2 custom legal recognizers (`CaseNumberRecognizer`, `MatterNumberRecognizer`), and disables 7 noisy defaults (`UsSsn`, `UsPassport`, `UsLicense`, `Crypto`, `Iban`, `Ip`, `MedicalLicense`). The enable/disable judgments reflect engineering reasoning about typical legal-document corpus — **not** empirical recall + precision measurements on a curated corpus of contracts, briefs, and correspondence.

For citation verification, a recognizer miss surfaces visibly to the user as an "unverified" chip. For anonymization, **a miss is a silent confidentiality incident** — unredacted client data reaches the model provider before the operator has any signal something went wrong. Operational-telemetry calibration (the path used for cost in [DE-281](#de-281--citation-engine-operational-telemetry-calibration-tolerant_match_threshold--aggregation_rule)) can't address this because by the time a miss is observable, the leak has already happened. Pre-deployment empirical validation against representative legal-document corpus is the right shape of work.

**Specific scope (port of the original M2-F2 plan):**

- **Curate ~50 documents** with ground-truth entity annotations. Sources can mix:
  - Anonymized real practice documents (operator/contributor-supplied; the corpus itself ships under whatever license the contributor specifies, including potentially a separate license tier from the main project).
  - Public-domain legal documents (federal/state statutes via `uscode.house.gov`, court opinions from CourtListener, SEC EDGAR contract exhibits).
  - Synthetic but representative documents authored under the project's license.
- **Annotations format:** per entity type, list of `(text, start_offset, end_offset, type)` tuples. JSONL recommended for diff-friendliness in git.
- **Build runner:** `scripts/run_anonymization_eval.py` that loads the corpus, runs each document through `get_analyzer_engine().analyze(...)`, computes per-entity-type recall / precision / F1 against ground truth, reports the aggregate baseline.
- **Baseline targets** (restated from the original M2-F2 plan; revisit if contributor evidence suggests they need recalibration):
  - `PERSON`, `ORGANIZATION`: recall ≥95%, precision ≥90%.
  - `EMAIL_ADDRESS`, `PHONE_NUMBER`: recall ≥98%, precision ≥98% (regex-based; should be near-perfect).
  - `LOCATION` (ADDRESS): recall ≥85%, precision ≥80%.
  - `CASE_NUMBER`, `MATTER_NUMBER`: recall ≥70%, precision ≥75%.
- **Document the corpus, runner, and baseline metrics** in `docs/security/anonymization.md`, replacing the "What's NOT validated" section's "Unknown" placeholders with measured values.
- **Optional CI nightly** — informational, non-blocking. The corpus is stable enough that meaningful changes only happen when the recognizer set changes, so PR-time CI is sufficient to catch regressions for most contributors.

**Practice-area sub-areas welcomed:**

- **Personal-injury / employment / benefits / immigration practices** — re-evaluate the `UsSsnRecognizer` disable. These practices routinely handle real SSNs; the current disable is correct for general civil litigation but potentially wrong for these areas. Contribution shape: corpus subset that exercises real SSN density in representative documents, plus a measured FP-rate analysis for the case-number collision Presidio's SSN recognizer produces.
- **Healthcare / regulated-industry practices** — re-evaluate `MedicalLicenseRecognizer`, possibly add new recognizers for DEA numbers, NPI numbers, NDC codes. Practice-specific entity types are valuable additions.
- **International practices** — extend beyond Presidio's US-centric defaults. Foreign-language detection is a separate gap tracked in the [Foreign-language entities](security/anonymization.md#foreign-language-entities--out-of-scope-for-v1) section; recognizer-set extensions for non-US jurisdictions belong here.
- **Document Bates numbering, account numbers, social media handles, date-of-birth patterns** — entity types not in the current set that operators have flagged or might flag.

**Acceptance criteria:**

- Corpus of at least 30 documents committed under `eval/anonymization/corpus/` (or a similar path), with documented sourcing and license per document.
- Annotations file at `eval/anonymization/annotations.jsonl` with schema documented in `eval/anonymization/README.md`.
- Eval runner at `scripts/run_anonymization_eval.py` produces per-entity-type metrics.
- Measured baseline numbers replace the "Unknown" placeholders in `docs/security/anonymization.md` §"What's NOT validated".
- If any recognizer-set changes are proposed alongside the corpus (e.g., re-enabling `UsSsn` for a practice-area variant), the corpus includes positive and negative examples justifying the change.
- DCO sign-off + attestation per the project's [skill-contribution model](../skills/CONTRIBUTING.md): the contributor confirms the corpus and annotations were authored under their practice judgment.

**Why this is the right kind of community contribution:**

This DE intentionally combines bounded technical work with practice-specific judgment work. The technical pieces (runner, metrics, CI wiring) are picked up cleanly by any contributor familiar with Python + Presidio. The judgment pieces (which entity types matter, which disable choices to reconsider, which patterns are realistic) require the kind of practice-specific knowledge no single maintainer can supply across the diversity of in-house legal teams' workflows. Splitting the work across contributors who own their respective practice areas is the right shape — and the project's [transparency principle](#13-transparency-as-a-founding-principle) is what makes the invitation honest in the first place.

#### DE-283 — Fresh-install login UX: surface the bootstrap-password path on first 401

**Priority:** P2 · **Effort:** S (~3–4 h as actually shipped)

**Status:** **SHIPPED at M3-0.1** (Phase 0, pre-M3 hardening). Implemented as a new unauthenticated `GET /api/v1/admin/bootstrap-status` endpoint the web login screen consults on the first 401 to decide whether to surface a bootstrap-password hint; the hint hides automatically once the operator rotates (signal: any non-deleted admin still has `must_change_password=true`). Approach is a variant of the DE-283 specific-scope option (b) below — separate-endpoint rather than embedded-in-401-response, so the login endpoint's wire shape stays unchanged. Preserved as a reference example of a small, well-scoped contribution; see the M3-0.1 implementation for the pattern (single backend module + Pydantic schema + integration tests; single Svelte component change + Cypress E2E; one quickstart paragraph).

**Original context (preserved for the historical record):** Surfaced during the M2 pre-tag fresh-install validation (2026-05-17). The maintainer team hit it; an attentive quickstart reader would not, but the failure mode is undocumented at the point it actually happens (the login screen), only at the point a careful reader is meant to have already addressed it (the quickstart Step 4).

**Context:** When an operator deploys a fresh stack (or wipes volumes and restarts), the bootstrap path in `api/app/admin_bootstrap.py` creates a default admin user `admin@lq.ai` with a randomly-generated password printed once to the API container's logs ("First-run admin password: …"). The [quickstart §Step 4](quickstart.md#step-4--sign-in-as-the-first-run-admin) tells operators to grep the logs. Three failure modes routinely reach the login screen instead:

1. **Operators skim past Step 4** — the password is buried in a paragraph, not in a callout box; readers focused on "where do I sign in" miss the prerequisite step.
2. **Operators who upgrade or wipe volumes mid-project** — they had a working admin from a prior install; the new bootstrap fires silently; their cached password no longer works; the error is a generic 401.
3. **Operators who lost the printed password** — the docs document a CLI reset (`docker compose exec api python -m app.cli reset-admin-password`) but that's in a troubleshooting section the operator has to know to look for.

In all three cases the user lands at the LQ.AI shell login form, types their best guess, and gets HTTP 401 with no actionable guidance about *why* the credentials don't match or *where* the right password lives.

**Specific scope (pick whichever combination fits the contributor's interests):**

- **(a) Improve the 401 response shape on the unauthenticated `/api/v1/auth/login` path.** When the request targets an account that was bootstrapped within the last ~24 hours and the operator has not yet completed the `must_change_password=true` flow, include a structured `hint` field in the response body pointing at the docs path — `{"detail": "...", "hint": "first_run_admin_password_in_logs", "docs_url": "https://github.com/LegalQuants/lq-ai/blob/main/docs/quickstart.md#step-4--sign-in-as-the-first-run-admin"}`. Conservative: only fire the hint for the bootstrapped admin email, not every 401 (to avoid leaking enumeration signal about which emails exist).
- **(b) Surface the hint in the LQ.AI shell login UI.** When the login form receives a 401 with `hint=first_run_admin_password_in_logs`, render an explanatory banner: "First-run deployment? Your bootstrap password is in the API container logs — run `docker compose logs api | grep 'First-run admin password'` to retrieve it. See the quickstart for the full bootstrap flow." Single click-through to the docs.
- **(c) Print the bootstrap password more prominently in the API container logs.** Currently the log line is a `WARNING` level emit; consider making it a visually-bracketed multi-line block (e.g., with `==========` separators) so it stands out in `docker compose logs api` output that's full of routine startup messages.
- **(d) Docs-only refinement.** Add a callout box at the top of the quickstart "Sign in" step explicitly framing "if you see a 401 here, your password is probably in the API logs — see §Step 4". And cross-reference from the OpenWebUI shell login surface (since that's the first thing many operators hit) so they're directed to the LQ.AI flow if they bypassed it.

**Why this is a good first contribution:** the issue is reproducible by anyone running through the quickstart; the surfaces touched are small (one endpoint, one Svelte component, or one docs section); the fix scope is bounded; the UX impact is meaningful for every new deployment.

**Acceptance criteria:** an operator who wipes volumes and restarts the stack, then attempts to sign in with stale credentials, sees actionable guidance (in the API response, the UI banner, the docs, or some combination) that lets them retrieve the bootstrap password without searching the troubleshooting section. A regression test pins that the hint surfaces only for accounts within the bootstrap-recency window (defensive against enumeration). `docs/quickstart.md` Step 4 + the troubleshooting section updated for whichever scope landed.

### Workflow intelligence

This subsection captures the bounded items that operationalize the M5+ Forward-Looking Workflow Intelligence direction (§8.5). The items are bounded enough to be picked up by community contributors as the M5+ roadmap matures. The architectural slot for the MCP-client subsystem is already committed for M1–M2 (§8 M1) so this subsection's items can be implemented incrementally without core refactoring.

Privacy and security implications dominate this entire subsection. Most items benefit from Tier 1 / Tier 2 inference (§1.5.2) and from the Anonymization Layer (§4.7); granular consent per signal source and per scope is a hard requirement, not an optional refinement. The §I.6 framing in the source recommendations (preserved here in spirit): "the privacy implications of workflow-aware context are the dominant constraint on the entire capability set; they cannot be appended as an afterthought; they have to be designed in from the start."

#### DE-200 — MCP-client subsystem in the LQ.AI backend

**Priority:** P1 · **Effort:** M

**Context:** The MCP integration substrate is the foundational piece on which all workflow-context capabilities depend. The architectural slot is committed in M1 or M2 (§8 M1) even though no connectors ship until M5; this DE captures the operationalization beyond the slot.

**Specific scope:** A pluggable MCP-client module in the FastAPI backend; configuration via the operator's `mcp.yaml`; per-server credential management; request routing; rate limiting; OpenTelemetry instrumentation matching the rest of the stack.

**Acceptance criteria:** Operator can register an MCP server in configuration; backend lists discovered tools; tools are callable from skills via a documented invocation pattern; community skill demonstrates calling at least one MCP server.

#### DE-201 — Signal Aggregation Service

**Priority:** P1 · **Effort:** L

**Context:** The persistent workspace-state layer that consumes signals from connected sources and exposes a unified query API. Foundation for the Today view, Prioritization Engine, and agent dispatch.

**Specific scope:** New backend service; consumes events via MCP-client subsystem; normalizes to Workspace Event schema (event_type, source, subject, timestamp, payload, metadata); persists in Postgres; exposes query API by user, time range, source, and event type; emits internal events for downstream consumers (Prioritization Engine, agents).

**Acceptance criteria:** Service ingests events from at least three signal sources; query API is documented and tested; event schema is documented and stable.

#### DE-202 — Email connector via MCP

**Priority:** P1 · **Effort:** M

**Context:** First and most important signal source. Ideally implemented as a community-contributed MCP server consumed by LQ.AI rather than baked in.

**Specific scope:** Reference MCP server for Gmail and Microsoft 365 (Exchange Online); read-only by default; granular permission scoping (specific labels/folders only); rate-limit-aware.

**Acceptance criteria:** Operator can configure email access; signals appear in Signal Aggregation Service; consent revocation is instantaneous.

#### DE-203 — Calendar connector via MCP

**Priority:** P1 · **Effort:** M

**Context:** Second signal source. Same pattern as DE-202.

**Specific scope:** Reference MCP server for Google Calendar and Microsoft 365 calendar; read-only by default; per-calendar permission scoping.

**Acceptance criteria:** As above for email.

#### DE-204 — Task system connectors via MCP

**Priority:** P1 · **Effort:** M each

**Context:** Asana, Linear, Jira, GitHub Issues, Monday, ClickUp — each a separate MCP server. Many already exist in the Anthropic MCP ecosystem; the LQ.AI project can leverage rather than duplicate.

**Specific scope:** Documented procedure for connecting community-maintained MCP servers to LQ.AI; reference deployment recipes for the most common task systems.

**Acceptance criteria:** Operator can configure at least three task systems via MCP; signals surface in Signal Aggregation Service.

#### DE-205 — CRM connector via MCP

**Priority:** P2 · **Effort:** M

**Context:** Salesforce above all; HubSpot, Microsoft Dynamics secondarily. CRM signal awareness is meaningful for in-house teams that handle deal-flow legal review.

**Specific scope:** Reference MCP server (or documentation for connecting community-maintained servers); granular access scoping (specific opportunities or accounts only).

**Acceptance criteria:** Operator can configure CRM access; signals (new opportunities matching legal-review criteria) surface in Signal Aggregation Service.

#### DE-206 — Document store connectors via MCP

**Priority:** P2 · **Effort:** M

**Context:** SharePoint, Google Drive, OneDrive, Dropbox, Box. Several have existing MCP servers in the ecosystem.

**Specific scope:** Documentation for connecting common document store MCP servers; pattern for auto-discovery of new documents in legal-team folders; auto-ingestion into Knowledge Bases.

**Acceptance criteria:** Operator can configure at least two document stores via MCP; new-document arrival triggers configurable workflow (auto-ingest, auto-Playbook-run, etc.).

#### DE-207 — Prioritization Engine

**Priority:** P1 · **Effort:** L

**Context:** The Workspace Concierge's core analytical capability. Open source, inspectable, forkable — true to the project's transparency philosophy (§1.3).

**Specific scope:** LangGraph workflow that aggregates signals + Project context + Org Profile + autonomous-layer memory; applies rule + LLM + learned-preference scoring; outputs ranked priority list with rationales. Implementation as a skill (the prioritization skill is open source like all other skills).

**Acceptance criteria:** Engine produces ranked priorities for a representative test workspace; rationales are coherent and traceable to inputs; performance: full re-prioritization completes in <30s for a workspace with 200 pending signals.

#### DE-208 — Today View UI surface

**Priority:** P1 · **Effort:** M

**Context:** The user-facing rendering of the prioritization output.

**Specific scope:** Web app surface (single-page, focused, opinionated); Word add-in equivalent (compact panel); responsive design for mobile browsers; one-click actions on each priority; drill-in to underlying Project or chat.

**Acceptance criteria:** Surface ships with M5; renders in <1s; mobile-responsive; tested on web, Word desktop, Word Online.

#### DE-209 — Email Triage Skill

**Priority:** P1 · **Effort:** S (once email connector exists)

**Context:** First and most-used skill operating on workspace signals.

**Specific scope:** Skill consumes incoming email signals; classifies (legal-relevant / not, contract / question / regulatory / internal / other); proposes routing or task creation; drafts responses for routine items.

**Acceptance criteria:** Skill ships with M5; reviewed by practicing attorney; produces useful classifications on real inbox samples.

#### DE-210 — Calendar Prep Skill

**Priority:** P1 · **Effort:** S (once calendar connector exists)

**Context:** Pre-meeting briefs based on calendar awareness and Project context.

**Specific scope:** Skill runs each evening (or on-demand); identifies meetings in the next 24 hours; for each meeting, finds related Project / matter context; produces a structured brief.

**Acceptance criteria:** Skill ships with M5; produces briefs of consistent quality on a representative calendar test set.

#### DE-211 — Agent Execution Framework

**Priority:** P1 · **Effort:** L

**Context:** Multi-step background agents with approval gates. Builds on M4 autonomous layer; the M4 design explicitly accommodates this extension (§3.10, §8 M4).

**Specific scope:** Agent definition format (extension of skill format); agent runtime in OpenWebUI Pipelines; agent run history; intervention UI; approval workflow for external-side-effecting actions; audit logging integration.

**Acceptance criteria:** Framework ships with M6; reference Email Triage Agent and Calendar Prep Agent demonstrate the pattern; documented contributor guide for agent authors.

#### DE-212 — Voice mode for the Today View

**Priority:** P2 · **Effort:** M

**Context:** Conversational interface to the prioritization output.

**Specific scope:** Voice input via Web Speech API (or browser-side equivalent); audio playback of priorities and rationales; "skip," "drill in," "defer to tomorrow" voice commands.

**Acceptance criteria:** Voice mode functional in Chrome and Safari; tested on common command patterns.

#### DE-213 — Cross-matter pattern recognition

**Priority:** P2 · **Effort:** L

**Context:** When the user has reviewed N similar contracts or matters, the system proactively suggests creating a Playbook, a saved skill, or a reusable position. Mentioned in PRD §3.10 user stories; this elevates it from autonomous-layer note to first-class capability.

**Specific scope:** Background analysis over the user's chat history and Project content; clusters similar matters; surfaces proposals for Playbook creation, skill creation, or Org Profile additions.

**Acceptance criteria:** Reference implementation surfaces meaningful patterns on a test corpus; suggestions are dismissable; user can accept and the system creates the proposed artifact.

#### DE-214 — Counterparty intelligence

**Priority:** P2 · **Effort:** L

**Context:** Aggregate prior interactions with a specific counterparty across emails, contracts, calls (transcribed), and decisions. Surface as context when the counterparty appears in a new matter.

**Specific scope:** Counterparty as a first-class entity (opposed to mentions in scattered places); per-counterparty knowledge graph; context surface in chats where a counterparty is implicated.

**Acceptance criteria:** Counterparty entity reliably resolves across mentions; knowledge surface accessible in chat sidebar; performance: counterparty resolution adds <200ms to chat creation.

#### DE-215 — Negotiation-state tracking

**Priority:** P2 · **Effort:** L

**Context:** A live contract negotiation has state: which side has the redline, what is open, what is converged. The system tracks the state and surfaces it.

**Specific scope:** Negotiation as a first-class entity attached to a Project (§3.11); state machine (drafting → out-for-review → counter-received → in-progress → executed → terminated); per-clause state (open, converged, agreed); visualization.

**Acceptance criteria:** State machine documented and consistent; state surfaces in Project view; supports stalled-negotiation detection (no movement in N days).

#### DE-216 — Personal decision history

**Priority:** P2 · **Effort:** L

**Context:** Captures user decisions with provenance and surfaces them when similar questions arise. "You decided X about counterparty Y in June; this looks like the same question."

**Specific scope:** Decision capture (explicit or inferred from chat content); decision retrieval on similar questions; explicit decision-recording skill.

**Acceptance criteria:** Decision retrieval surfaces relevant prior decisions on a test corpus; user can dismiss surfacing; decisions can be explicitly captured or reformed.

#### DE-217 — Time-blocked work mode

**Priority:** P3 · **Effort:** M

**Context:** "You have 90 minutes open at 2 PM. Tackle these three items?"

**Specific scope:** Calendar-aware availability detection; estimated-time tagging on priorities; bundled "work session" view with the items the user can plausibly complete in the available window.

**Acceptance criteria:** Estimation is calibrated against historical actuals; work session UI ships with M7 or community contribution.

#### DE-218 — Async team handoff briefs

**Priority:** P3 · **Effort:** M

**Context:** When a user goes OOO, hands off to a deputy, or departs the team, the system can prepare a structured handoff brief covering active matters, pending decisions, and key context.

**Specific scope:** Handoff brief generation skill that operates on a Project (or all the user's Projects); produces a structured document optimized for someone unfamiliar with the matters.

**Acceptance criteria:** Brief is useful for an unfamiliar reviewer; reviewed by practicing attorneys for completeness; tested on real OOO scenarios.

### Engineering discipline

This subsection operationalizes the §1.9 engineering-discipline posture and the §5.8 / §5.9 cross-cutting commitments. Each entry is a deferred enhancement whose architectural slot exists (or is documented as a gap in `docs/HONEST-STATE.md` §6) and whose path-to-shipping is bounded. Several entries have a corresponding mini-PRD under `docs/contribute/mini-prds/` — these are the contributor-friendly first PRs that close the M1 gap.

#### DE-222 — OpenSSF Scorecard published in README and automated in CI

**Priority:** P1 · **Effort:** S

**Context:** Per §1.8 addition and §1.9. The OpenSSF Scorecard tool computes 18 objective security-and-practice signals (branch protection, signed releases, dependency-update automation, fuzzing, etc.) and produces a score 0–10. The score is verifiable independently by any reviewer; it makes the engineering-discipline claim concrete and measurable. Closed-source vendors cannot earn this badge because the criteria presuppose source visibility.

**Specific scope:** A `scorecard-action` workflow committed to `.github/workflows/scorecard.yml` running weekly; a `SECURITY-INSIGHTS.yml` at repo root; badges added to README; `docs/security/scorecard-targets.md` documenting the target floor. See the mini-PRD at `docs/contribute/mini-prds/openssf-scorecard-and-badges.md`.

**Acceptance criteria:** Scorecard score published in README and refreshed continuously; initial target ≥7.0; M2 target ≥8.5; M4 target ≥9.0; documented gap-closure plan for any criterion that is not yet met.

#### DE-223 — OpenSSF Best Practices Badge: Passing → Silver → Gold

**Priority:** P1 · **Effort:** M (cumulative across milestones)

**Context:** The OpenSSF Best Practices Badge has Passing, Silver, and Gold tiers, each with explicit criteria (Gold requires multi-factor authentication for committers, signed commits, two-person review of substantive changes, public reproducible build, etc.). Each tier transition is publicly announced and added to the README. The criteria checklist for each tier is itself a useful project-discipline planning artifact.

**Specific scope:** Submit and maintain the badge through the OpenSSF self-attestation site; commit the badge link to README; document the criteria-by-criteria status in `docs/security/best-practices-badge-status.md`.

**Acceptance criteria:** Passing tier achieved by M1 release; Silver tier by M2; Gold tier by M4. Each tier transition produces a public announcement and a documented evidence trail.

#### DE-224 — OWASP LLM Top 10 mitigation mapping

**Priority:** P1 · **Effort:** S

**Context:** The OWASP LLM Top 10 (LLM01 Prompt Injection through LLM10 Model Theft) is the de facto procurement framework for AI-product security review. Closed-source vendors typically do not publish this mapping because they cannot cite their architecture. The mini-PRD is at `docs/contribute/mini-prds/owasp-llm-top10-mapping.md`.

**Specific scope:** A new document `docs/compliance/owasp-llm-top10.md` covering each LLM0X risk in five columns — threat description, applicability to LQ.AI architecture, project mitigations (with citations into `gateway/`, `api/`, `skills/`, or `docs/security/`), residual risk, and operator responsibility. Each row's "project mitigations" column cites at least one specific file path so a reviewer can verify in source. The Citation Engine (§3.3) and Anonymization Layer (§4.7) M1-status notes are reflected accurately.

**Acceptance criteria:** All 10 risks have substantive entries; every cited file path resolves; the doc is referenced from Appendix E (objection on prompt injection); a non-maintainer security architect can read it without producing a "marketing copy" complaint.

#### DE-225 — NIST AI RMF 1.0 Profile commitments

**Priority:** P1 · **Effort:** M

**Context:** The NIST AI Risk Management Framework 1.0 (with the Generative AI Profile NIST AI 600-1) is the U.S. federal-aligned framework for AI risk governance. This is the document a federal procurement team (or a federal-adjacent enterprise) will look for first. The mini-PRD is at `docs/contribute/mini-prds/nist-ai-rmf-profile.md`.

**Specific scope:** A new document `docs/compliance/nist-ai-rmf-alignment.md` structured as the four AI RMF functions (Govern / Map / Measure / Manage) plus the Generative AI Profile additions. Each function maps to a row of "subcategory → LQ.AI design choice or operational practice → code citation or PRD section reference → residual operator responsibility." The Generative AI Profile additions emphasize prompt-injection, data-poisoning, and confabulation rows specifically.

**Acceptance criteria:** Every subcategory is addressed; Govern subcategories that are operator-only are explicitly marked as such; the doc is referenced from the README under compliance and governance; a federal-procurement reviewer can produce a substantive list of gaps rather than a "this is marketing" rejection.

#### DE-226 — MITRE ATLAS threat-model mapping

**Priority:** P2 · **Effort:** M

**Context:** MITRE ATLAS is the adversarial-ML analog of MITRE ATT&CK: a structured matrix of known adversarial-ML tactics, techniques, and case studies. Closed-source vendors typically do not publish an ATLAS mapping because they cannot cite their architecture.

**Specific scope:** A new document `docs/security/atlas-mapping.md` identifying which ATLAS techniques apply to LQ.AI's architecture, what mitigations are in place, what residual risk remains, and what techniques are out of scope (e.g., model-theft techniques largely do not apply to a project that does not train models). Cross-references the STRIDE threat model at `docs/security/threat-model.md`.

**Acceptance criteria:** Every applicable ATLAS technique has a row; mitigations cite into source; out-of-scope techniques are explicitly named as such with rationale.

#### DE-227 — Annual third-party penetration test with public summary

**Priority:** P1 · **Effort:** L (recurring)

**Context:** Per §1.8 addition. A recurring application penetration test by a recognized firm closes the procurement objection "what independent review has this had?" with a verifiable yes rather than the closed-source standard answer of "we have an internal security team." The first engagement is targeted within 90 days of M1 release; the engagement is LegalQuants-funded and not contingent on community contribution.

**Specific scope:** Annual engagement covering the FastAPI surface, the Inference Gateway, the OpenWebUI fork, the Word add-in (once shipped), and the documented reference deployment. Public deliverable: executive summary in `docs/security/releases/pen-test/<year>.md` with finding count by severity, remediation status, and remediation timeline. Detailed findings are coordinated-disclosure-cycled per `SECURITY.md` before publication.

**Acceptance criteria:** First engagement scheduled within 90 days of M1; executive summary published within 30 days of the engagement's conclusion; remediation tracker updated through the disclosure window.

#### DE-228 — Annual adversarial-AI red-team engagement

**Priority:** P1 · **Effort:** L (recurring)

**Context:** Per §1.8 addition. The AI-product-specific analog of the application penetration test. Very few legal-tech competitors commission this; doing so is the structural signal that the project takes AI-specific failure modes seriously.

**Specific scope:** Annual engagement with a recognized AI-security firm or a documented community red team. Scope: prompt injection from malicious documents, jailbreak resistance, citation-hallucination resistance, PII extraction from the Anonymization Layer, skill subversion, autonomous-layer trust-boundary testing (once M4 ships). Public deliverable: methodology document, attack categories tested, detection rates, mitigation effectiveness, residual risk. Published at `docs/security/releases/ai-red-team/<year>.md`.

**Acceptance criteria:** First engagement scheduled within 90 days of M1; methodology and aggregate results published within 30 days of conclusion.

#### DE-229 — Mutation testing in CI with per-release scores published

**Priority:** P2 · **Effort:** M

**Context:** Per §5.8. Mutation testing is the answer to the criticism that coverage percentages can be gamed. The published mutation score per release proves that the test suite catches real defects, not just that the lines are executed.

**Specific scope:** Configure mutmut (Python) and Stryker (TypeScript) to run nightly on the critical-path packages: Inference Gateway, Citation Engine (once wired), Anonymization Layer (once wired), the FastAPI authentication and authorization surface, the audit-log writer. Publish the mutation score per release. Set a target floor (e.g., ≥80% on the Gateway and Citation Engine).

**Acceptance criteria:** Mutation testing runs nightly; per-release mutation score is published in the release notes and rendered as a README badge alongside the OpenSSF Scorecard.

#### DE-230 — Property-based testing for Citation Engine and Anonymization Layer invariants

**Priority:** P1 · **Effort:** M

**Context:** Per §5.8. The Citation Engine, the Anonymization Layer, and the Inference Gateway router are the three components whose invariants are load-bearing for the product's correctness and security story. Properties find the edge cases example-based tests miss.

**Specific scope:** Use Hypothesis (Python property-based testing) to express invariants as properties tested across generated inputs. Citation Engine: every emitted citation resolves to a verbatim quote in the cited chunk; no citation references a chunk not in the retrieval set. Anonymization Layer: every anonymized entity on the request path is rehydrated on the response path; entity identifiers are stable across retries; the anonymization map for one chat is never reused for another. Gateway router: no fallback path can promote a request above its allowed tier.

**Acceptance criteria:** Property tests in `api/tests/property/` and `gateway/tests/property/`; CI runs them with a documented time budget; properties are documented in `docs/security/property-tests.md`. Depends on the underlying pipelines being wired (§3.3 Citation Engine and §4.7 Anonymization Layer at M2).

#### DE-231 — Golden / snapshot testing for built-in skills with model-version regression

**Priority:** P1 · **Effort:** M

**Context:** Per §5.8. The LLM-product analog of regression testing. When a model upgrade causes a skill's structural-output score to drop below threshold, the release-blocking issue is auto-filed. The contributor-friendly path is the skill-acceptance-tests mini-PRD at `docs/contribute/mini-prds/skill-acceptance-tests.md`.

**Specific scope:** Each built-in skill ships with a `skills/<skill>/acceptance/` directory containing 3–5 anonymized real-document inputs and structural-output golden snapshots. The CI runs the skill against the documented multi-model matrix (Anthropic Claude latest two majors; OpenAI GPT latest two majors; one open-weight reference local model) and compares structural output to the snapshots with a documented similarity threshold. A drop below threshold blocks release.

**Acceptance criteria:** All 10 starter skills have populated acceptance directories; CI job runs nightly against the model matrix; structural-similarity threshold is documented; first regression-blocked release demonstrates the gate works as designed.

#### DE-232 — WCAG 2.1 AA accessibility audit and CI gate

**Priority:** P1 · **Effort:** M

**Context:** Per §5.8. Accessibility is increasingly a procurement requirement in legal and regulated industries; shipping with verifiable WCAG 2.1 AA from M1 closes the objection without requiring a separate compliance workstream later.

**Specific scope:** Run axe-core (or pa11y) against the web UI on every PR with WCAG 2.1 AA as the merge gate. Commission a one-time third-party manual accessibility audit at M2 and publish the report at `docs/compliance/accessibility-audit.md`. The Word add-in (M3) follows Microsoft's Office add-in accessibility guidelines and is tested with the Office Accessibility Checker.

**Acceptance criteria:** axe-core CI gate is green on `main`; gate fails PRs with new WCAG 2.1 AA violations; third-party audit at M2 produces a public report with all critical findings remediated or documented.

#### DE-233 — Air-gap install verification CI test

**Priority:** P1 · **Effort:** S

**Context:** Mode 2 (full local inference, Tier 1) is documented in §6.4; nothing currently asserts it. Operators in regulated industries (defense, healthcare on-prem, EU sovereign cloud) gate adoption on this verification. The mini-PRD is at `docs/contribute/mini-prds/air-gap-install-verification.md`.

**Specific scope:** A new CI job (in `ci.yml` or a dedicated `air-gap.yml`) that brings up the stack with `docker compose --profile local up -d`, asserts the compose network has zero outbound NAT, drives a complete chat through the local-Ollama path (login → send → receive), and fails the build if any container makes an outbound DNS query to a non-private address during the test window. The job also asserts the gateway routing-log records `provider: ollama` and `tier: 1` exclusively.

**Acceptance criteria:** CI job is green on PRs that don't touch the egress path; fails when a cloud-provider adapter is accidentally re-enabled in Mode 2; the test is documented in `docs/security/air-gap-verification.md` so operators can re-run it against their own deployment.

#### DE-234 — Reverse-proxy and TLS deployment recipes (Caddy, Traefik, nginx)

**Priority:** P2 · **Effort:** S

**Context:** §6.3 mentions Caddy, Traefik, and nginx as reverse-proxy options; no concrete configurations ship with M1. The mini-PRD is at `docs/contribute/mini-prds/reverse-proxy-tls-deployment-recipes.md`.

**Specific scope:** Three compose overlays and READMEs in `deploy/reverse-proxy/{caddy,traefik,nginx}/`. Each overlays the base `docker-compose.yml`, terminates TLS at the proxy, exposes `web` and `api` on the standard ports, and handles Let's Encrypt automation for Caddy and Traefik (and documents the cert-manager path for nginx). Each recipe is tested end-to-end against a test FQDN.

**Acceptance criteria:** A non-maintainer operator can clone the repo, follow one recipe, and have a TLS-terminated deployment on a real domain in under 30 minutes. CI smoke-tests at least the Caddy recipe.

#### DE-235 — Procurement-Readiness Pack (SIG Lite + CAIQ)

**Priority:** P1 · **Effort:** M

**Context:** The stub at `docs/procurement/README.md` documents the structure and the `[OPERATOR-CONFIGURABLE]` marker pattern. PRD Appendix E (17 pre-empted objections) is the substantive content the questionnaires need; the work is reformatting the existing prose into SIG Lite and CAIQ row shapes. The mini-PRD is at `docs/contribute/mini-prds/procurement-readiness-pack.md`.

**Specific scope:** Three new documents in `docs/procurement/`: `sig-lite.md` (pre-filled SIG Lite responses with `[OPERATOR-CONFIGURABLE]` markers); `caiq.md` (pre-filled CAIQ Lite mapped to CSA Cloud Controls Matrix); `cover-letter.md` (sample procurement-team cover letter explaining why the project is an unusual procurement — self-hosted, no SaaS data residency to verify, source verifiability instead of compliance attestation).

**Acceptance criteria:** A second in-house counsel can take the pack into their procurement team and answer ≥80% of the standard intake questions without writing new prose; `[OPERATOR-CONFIGURABLE]` markers cover only items that genuinely vary across deployments.

#### DE-236 — Acceptance tests for the 10 starter skills

**Priority:** P1 · **Effort:** M (cumulative across skills)

**Context:** Each starter skill has a `test-plan.md`; no harness executes the plans yet. Per `docs/HONEST-STATE.md` §6 and the mini-PRD at `docs/contribute/mini-prds/skill-acceptance-tests.md`. Distinct from DE-231 (which is the regression harness): this is the first contributor-attorney-verified evidence the skills work on real documents.

**Specific scope:** A new directory `skills/<skill>/acceptance/` per skill containing 3–5 anonymized real-document inputs, expected-output golden notes (structural — issue list expected, severity range expected, citation count expected, not exact wording), and a `results.md` summarizing the skill's behavior on each input. Tests run by hand at first (no eval harness yet — see DE-237) but the structured-output format anticipates the harness.

**Acceptance criteria:** Each starter skill has a populated `acceptance/` directory; identified issues from the acceptance pass are filed as GitHub issues; the README links to the acceptance directory as verifiable signal of skill quality.

#### DE-237 — Eval harness with held-out test sets and inter-rater agreement

**Priority:** P1 · **Effort:** L

**Context:** Per §5.8 and `docs/HONEST-STATE.md` §6. The eval harness is itself an open-source artifact reviewers can run and challenge. Supersedes the partial coverage in DE-022 (skill performance and quality measurement) with a structured, multi-judge implementation.

**Specific scope:** Build `tests/eval/` and `docs/quality/eval-methodology.md` such that each built-in skill runs against a held-out corpus with grading rubrics that produce a per-skill quality score. For skills whose evaluation requires legal judgment ("did the redline correctly identify the unusual provision?"), build the grading rubric in a structured form and use multi-judge LLM grading with inter-rater agreement (Cohen's kappa) reported alongside the score.

**Acceptance criteria:** Methodology document published; per-skill quality scores published per release; inter-rater kappa is reported for any subjective rubric; the harness is runnable by any contributor with API access to the documented model matrix.

#### DE-238 — Public skill-quality leaderboard

**Priority:** P2 · **Effort:** M

**Context:** Per §5.8. The leaderboard answers two questions operators care about and competitors cannot: which model should I run this skill with, and is the project's quality improving release over release. Depends on DE-237 (the eval harness).

**Specific scope:** A per-release leaderboard at `docs/quality/leaderboard.md` of built-in skills × inference models × quality score (from DE-237), with historical trend lines. Also a strong recruiting signal for community skill contributors who want their work measured against a clear bar.

**Acceptance criteria:** Leaderboard refreshed per release; historical trend visible; each row links to the underlying eval run and corpus.

#### DE-239 — Prompt-injection detection rates published per skill and per release

**Priority:** P1 · **Effort:** M

**Context:** Per §5.8. Building on DE-110 (Prompt-injection pattern library). Publishing the actual rates is a stronger trust signal than claiming the rates are high.

**Specific scope:** Per-skill detection rates against documented attack corpora (Garak, PyRIT, MITRE ATLAS). The Citation Engine's verification step (§3.3), the structured-output schemas (DE-111), and skill-specific defenses each get a measured detection rate. Published at `docs/quality/prompt-injection-rates.md` and updated per release.

**Acceptance criteria:** Rates measured against the three documented corpora; published per skill and per release; methodology documents which attacks are in scope and which are out of scope.

#### DE-240 — PII leakage testing with measurable rates

**Priority:** P1 · **Effort:** M

**Context:** Per §5.8. The measurable analog of the privacy claim. Depends on the Anonymization Layer being wired (§4.7 at M2).

**Specific scope:** Test the Anonymization Layer against a documented PII corpus: each entity class × each NER backend × each inference tier × each adversarial-extraction technique. Publish a per-release "PII leakage probability" rate per configuration in `docs/quality/pii-leakage-rates.md` with the test methodology.

**Acceptance criteria:** Rates measured for the documented configurations; published per release; the methodology is reproducible by an independent reviewer.

#### DE-241 — Distroless / minimal container base images

**Priority:** P2 · **Effort:** S

**Context:** Distroless images contain only the application runtime and direct dependencies — no shell, no package manager, no commonly-exploited utilities — which materially shrinks the CVE attack surface per image.

**Specific scope:** Migrate the api, gateway, and ingest-worker containers to Google's distroless base images or Chainguard's wolfi-based equivalents. Document the rationale and the rebuild process in `docs/security/container-baseimages.md`.

**Acceptance criteria:** Released images use distroless bases; CVE scan diffs documented before/after; container size reduction recorded.

#### DE-242 — mTLS between internal services

**Priority:** P2 · **Effort:** M

**Context:** For high-assurance deployments where the operator wants to assert "no plaintext traffic anywhere in the deployment," this closes the gap.

**Specific scope:** Configure mTLS for service-to-service traffic in the reference Docker Compose and the Helm chart: api ↔ gateway, api ↔ postgres, api ↔ redis, api ↔ minio. Certificate issuance via cert-manager (Kubernetes) or step-ca (Compose). Documented at `docs/security/internal-mtls.md`.

**Acceptance criteria:** mTLS configurable via a documented flag in `docker-compose.yml` and the Helm chart; reference deployment is tested with mTLS on; the path is documented for operator-side customization.

#### DE-243 — Pod Security Standards (Restricted) profile for the Helm chart

**Priority:** P1 · **Effort:** S

**Context:** The Kubernetes Pod Security Standard Restricted profile is the table-stakes deployment-security posture; shipping it from the first Helm chart release means operators do not have to harden the chart themselves.

**Specific scope:** The Helm chart ships with manifests compliant with the Restricted profile: non-root container users (UID ≥ 10000); read-only root filesystems; dropped capabilities (drop ALL, add only what is required); seccomp profile set to RuntimeDefault; AppArmor profile referenced; resource limits enforced; no host-path mounts; service accounts with minimal RBAC. Depends on DE-030 (Helm chart).

**Acceptance criteria:** Helm chart manifests pass `kubectl --warnings-as-errors` against the Restricted profile; reference deployment runs cleanly under Pod Security admission with `enforce: restricted`.

#### DE-244 — Signed commits enforced on the main branch

**Priority:** P2 · **Effort:** S · **Target milestone:** M2

**Context:** Configure GitHub branch protection on `main` to require GPG- or Sigstore-signed commits, in addition to the existing DCO sign-off requirement (per §7.5). This is an OpenSSF Best Practices Badge Silver-tier requirement and a procurement signal of supply-chain seriousness. **M1 trust model is intentionally weaker on this axis:** DCO sign-off is enforced (any contributor can claim any name; the project does not verify identity), and cryptographic commit signing is not required. The M1 supply-chain signal is the **release-side** cryptographic surface (SLSA-3 provenance, Sigstore-signed container images, SBOM with every release per §7.8); the M2 add is **contributor-identity** cryptographic enforcement. Operators who require commit-signing enforcement before M2 ships can configure their fork's branch protection independently.

**Specific scope:** Enable the branch-protection rule; document the contributor onboarding step for setting up commit signing in `CONTRIBUTING.md` and `docs/contribute/signing-commits.md`; include the Sigstore (gitsign) path alongside GPG.

**Acceptance criteria:** Unsigned commits cannot land on `main`; documented onboarding produces a working signing setup for both GPG and Sigstore paths.

#### DE-245 — Published Service Level Objectives and Indicators

**Priority:** P2 · **Effort:** M

**Context:** Per §5.9. Operators of regulated production systems expect a documented SLO catalog and the corresponding SLI calculations. The reference SLOs are starting points; operators tune to their own risk appetite.

**Specific scope:** A new document `docs/operations/slos.md` covering API availability (target 99.9% monthly), p99 latency by capability (per §3), inference-fallback success rate, audit-log durability. For each SLO, document the SLI calculation and the OpenTelemetry metric (per §5.4) that feeds it.

**Acceptance criteria:** SLO catalog published; SLI calculations are reproducible against the OpenTelemetry instrumentation that ships at M1; reference dashboards in Grafana JSON committed to the repository.

#### DE-246 — Error budget policy

**Priority:** P2 · **Effort:** S

**Context:** Per §5.9. Documents how the project handles SLO breaches in releases. Operative for any future LegalQuants-managed-service offering and illustrative for operators who want to adopt the same discipline. Depends on DE-245 (SLO catalog).

**Specific scope:** A documented error budget policy in `docs/operations/error-budget.md`: budget calculation per SLO; what triggers a release freeze on non-critical changes; what recovery looks like.

**Acceptance criteria:** Policy is documented; the freeze-trigger condition is concrete and testable; the policy is referenced from the release procedure runbook.

#### DE-247 — Public postmortems within 14 days

**Priority:** P2 · **Effort:** M

**Context:** Per §5.9. The discipline mature OSS projects and mature SaaS vendors follow. Publishing postmortems is a credibility multiplier. For self-hosted operator deployments, incident response is the operator's responsibility — this commitment is for incidents in any LegalQuants-operated infrastructure.

**Specific scope:** A documented template at `docs/operations/postmortem-template.md` (timeline, root cause, contributing factors, remediation, action items, lessons learned). Publication committed within 14 days of any incident in LegalQuants-operated infrastructure (the project's hosted demo, GitHub-issued artifacts, the managed-service offering once it exists).

**Acceptance criteria:** Template published; commitment recorded in the release procedure runbook; first postmortem (when an incident occurs) is published within 14 days.

#### DE-248 — Disaster recovery test cadence

**Priority:** P2 · **Effort:** M

**Context:** Per §5.9. The DR procedure is operator-runnable for any self-hosted deployment; the quarterly cadence applies to LegalQuants-managed-service operations.

**Specific scope:** A documented DR procedure (backup restore, secret rotation, key rotation, failover to a secondary region) at `docs/operations/disaster-recovery.md`. Quarterly test cadence with published reports for LegalQuants-managed environments.

**Acceptance criteria:** Procedure is operator-runnable; the test cadence is documented; first quarterly test (when LegalQuants-managed infrastructure exists) is published.

#### DE-249 — Runbooks for operational tasks

**Priority:** P1 · **Effort:** M

**Context:** Per §5.9. The operational-maturity signal that lets a procurement security team check the box on "the vendor has documented operational procedures." For an OSS project, the runbooks are the evidence.

**Specific scope:** A `docs/runbooks/` directory with runbooks for: deploying, upgrading, rotating credentials, responding to a security advisory, recovering from a corrupted vector index, migrating to a different inference provider, ingesting a backlog of documents. Each runbook includes estimated time, prerequisites, the exact commands, success-verification steps, and rollback procedure.

**Acceptance criteria:** Each operational task has a runbook; runbooks are tested against the reference deployment; the first runbook (deploying) is referenced from the README quickstart.

#### DE-250 — Performance regression with historical tracking

**Priority:** P2 · **Effort:** M

**Context:** Per §5.8. Catches the class of defects where a refactor functionally works but materially regresses production behavior.

**Specific scope:** Latency benchmarks (p50, p95, p99) for the conversational core, the Citation Engine (once wired), the Inference Gateway routing decision, and skill execution, run per PR via a CI job. Results committed to a benchmark history in `docs/quality/perf-history.md`. Regressions of more than a documented threshold merge-block.

**Acceptance criteria:** Per-PR benchmark job runs in CI; threshold is documented; first merge-block from a regression demonstrates the gate works as designed.

#### DE-251 — Chaos and fault injection for the gateway and document pipeline

**Priority:** P2 · **Effort:** M

**Context:** Per §5.8. Structured fault testing of the gateway's provider-fault behavior and the document pipeline's malformed-document handling.

**Specific scope:** Provider-fault injection harness for the Inference Gateway (provider returns 500, 429, hangs, returns malformed JSON, returns partial response); document-pipeline harness for malformed inputs (truncated PDFs, malformed DOCX, PDFs with embedded JavaScript, unicode-direction-override attacks). Documented at `docs/quality/chaos-testing.md`.

**Acceptance criteria:** Harness runs in CI nightly; fallback behavior is asserted correct under every documented fault; audit log captures faults accurately; cost accounting remains consistent under fallback.

#### DE-252 — Fuzz testing extended to document parsers and anonymization paths

**Priority:** P2 · **Effort:** M

**Context:** Per §5.8. Extends the Cross-Milestone fuzzing commitment beyond the OpenAI-compatibility surface to the document-pipeline parsers and the Anonymization Layer's regex and NER paths.

**Specific scope:** libFuzzer-style harnesses for Docling input, PyMuPDF input, and OCR API response handling. ReDoS and adversarial-tokenization fuzzing for the Anonymization Layer's regex and NER paths (once §4.7 is wired). Documented at `docs/security/fuzz-testing.md`.

**Acceptance criteria:** Nightly fuzz job runs in CI; first crash report (from any fuzzed surface) is triaged and either fixed or documented as out-of-scope; the fuzzing methodology is referenced from the security policy.

#### DE-253 — Consumer-driven contract testing between services

**Priority:** P2 · **Effort:** M

**Context:** Per §5.8. Especially important given the OpenWebUI fork relationship: contract tests ensure that an upstream OpenWebUI change cannot silently break a backend assumption.

**Specific scope:** Pact (or equivalent) contract tests for the boundaries between `web/`, `api/`, `gateway/`, and the Word add-in (M3). Versioned and committed to source; CI catches breaking changes at PR time.

**Acceptance criteria:** Contract tests in place for the three current boundaries; first breaking change caught at PR time demonstrates the gate works as designed; the test surface is documented for contributor pickup.

#### DE-254 — Cypress shared helpers extracted to `support/`

**Priority:** P2 · **Effort:** S

**Context:** Wave 8 cleanup. The Cypress LQ.AI specs (`wave-d1-power-features`, `wave-d2-skill-creator`, `wave-m1-final-surfaces`) currently duplicate setup helpers (login, KB create, skill fork, etc.) inline. As specs accumulate, the duplication accumulates with them; the next spec should be able to import helpers rather than reproduce them.

**Specific scope:** Move shared helpers to `web/cypress/support/lq-ai/` and refactor the three spec files to import. Each helper has a docstring; the support module is the documented surface for future spec authors.

**Acceptance criteria:** No helper logic duplicated across specs; new spec authors import from the support module; CI run time is unchanged or improved.

#### DE-255 — Add `responseTimeout: 90000` to `cypress.config.ts`

**Priority:** P2 · **Effort:** S

**Context:** Wave 8 cleanup. KB-attach interactions and document ingestion can exceed the Cypress default response timeout under realistic conditions; intermittent flakes have surfaced. The fix is a one-line config change with a documented rationale.

**Specific scope:** Set `responseTimeout: 90000` in `web/cypress.config.ts` with an inline comment naming the failure mode (KB ingest under load).

**Acceptance criteria:** Configuration committed; intermittent timeout-related Cypress flakes are eliminated across three consecutive nightly runs.

#### DE-256 — KB attach interceptor added to `wave-m1-final-surfaces.cy.ts` Test 2

**Priority:** P2 · **Effort:** S

**Context:** Wave 8 cleanup. The current spec asserts post-condition state but not the intermediate KB-attach network call, which makes diagnosis of failures slower than it should be. Adding a `cy.intercept` for the attach endpoint surfaces the failure mode immediately.

**Specific scope:** Add `cy.intercept('POST', '/api/v1/knowledge-bases/*/attach').as('kbAttach')` and `cy.wait('@kbAttach')` with an explicit assertion on the response payload in `web/cypress/e2e/wave-m1-final-surfaces.cy.ts` Test 2.

**Acceptance criteria:** The intercept is in place; a deliberately-broken backend produces a clear assertion failure rather than a timeout in three consecutive runs.

#### DE-257 — `/api/v1/audit-health` endpoint for AmbientFooter signal

**Priority:** P2 · **Effort:** S

**Context:** Per the Wave 8 handoff §3. The AmbientFooter in `web/src/lib/lq-ai/components/AmbientFooter.svelte` polls a backend signal to render the "audit log is healthy" indicator; the endpoint currently does not exist and the component falls back to optimistic rendering.

**Specific scope:** New endpoint `GET /api/v1/audit-health` returning a small payload: `{ ok: true, last_write_at, lag_seconds, ring_buffer_depth }`. Wired to the audit-log writer in `api/app/audit.py`. AmbientFooter consumes the payload directly and renders the corresponding state.

**Acceptance criteria:** Endpoint is in the OpenAPI sketch; backed by a unit test; AmbientFooter renders the correct state in both healthy and degraded conditions; documented in `docs/api/backend-openapi.yaml`.

#### DE-258 — KB embedding-progress percentage aggregation

**Priority:** P2 · **Effort:** S

**Context:** Per the Wave 8 handoff §3. The KB document table currently shows per-document status (`pending` / `ready` / `failed`) but does not aggregate to a KB-level progress percentage, which is the surface users want when an ingest batch is in flight.

**Specific scope:** Extend the `GET /api/v1/knowledge-bases/{id}` response with an `embedding_progress: { ready, total, percent }` block computed at query time from the `documents` table. Render in `web/src/routes/lq-ai/knowledge/[id]/+page.svelte`.

**Acceptance criteria:** Percentage renders correctly during a batch ingest; updates on document-state transitions; covered by a unit test in `api/tests/`.

#### DE-259 — KB attached-matters reverse-lookup

**Priority:** P2 · **Effort:** S

**Context:** Per the Wave 8 handoff §3 and `docs/HONEST-STATE.md` §3. Operators ask "which matters use this KB?" — the forward lookup (matter → KBs) exists; the reverse lookup does not.

**Specific scope:** New endpoint `GET /api/v1/knowledge-bases/{id}/attachments` returning the list of matters/projects that have the KB attached. Render in the KB detail page sidebar.

**Acceptance criteria:** Endpoint returns the correct set in the test fixture; documented in OpenAPI; rendered in the KB detail page; covered by a unit test.

#### DE-260 — Receipts assistant-side skill event deduplication

**Priority:** P2 · **Effort:** S

**Context:** Per the Wave 8 handoff §3. The assistant message carries skill events; the receipts drawer occasionally renders duplicate entries when the same skill is invoked twice on the same turn. The dedupe key is `(kind, skill_id, started_at)`.

**Specific scope:** Fix in `web/src/lib/lq-ai/ReceiptsList.svelte` (or the upstream data source). Cover with a unit test exercising the duplicate-input case.

**Acceptance criteria:** Duplicates do not render; existing single-event behavior is unchanged; unit test passes.

#### DE-261 — `api/client.ts` `errorFor` swallows string-shaped FastAPI detail bodies

**Priority:** P1 · **Effort:** S

**Context:** Prior handoff finding (carried forward as Wave 8 root cause). FastAPI error responses can come as `{ "detail": "string" }`, `{ "detail": { ... } }`, or `{ "detail": [ { ... } ] }`. The current `errorFor` helper handles the second and third forms but silently drops the first, producing the unhelpful "Unknown error" surface to users when the most informative shape is in play. This is the leaf cause behind several user-reported "I don't know what went wrong" reports.

**Specific scope:** Fix in `web/src/lib/lq-ai/api/client.ts`: when `detail` is a string, surface it as the error message. Cover all three shapes with a unit test in `web/src/lib/lq-ai/__tests__/`.

**Acceptance criteria:** All three FastAPI detail shapes surface a meaningful message; existing handling of structured detail is unchanged; unit test passes.

#### DE-262 — OpenWebUI fork TypeScript-check migration

**Priority:** P3 · **Effort:** L (recurring, multi-milestone)

**Context:** The LQ.AI web frontend is a fork of OpenWebUI (ADR 0001). When `svelte-check` runs against the full codebase, approximately 9,359 TypeScript errors surface — all in upstream OpenWebUI files inherited at fork time. None are in LQ.AI-owned code. For M1, CI scopes the typecheck to LQ.AI-owned paths (`src/lib/lq-ai/**`, `src/routes/lq-ai/**`) via `npm run check:lq-ai`, keeping the signal clean for new contributions. The full-scope check (`npm run check`) remains available for auditors. See `docs/HONEST-STATE.md §6.1` for the complete safety analysis.

**Specific scope:** Systematically fix TypeScript strict-mode errors in upstream OpenWebUI files. Prioritize: auth and session code first (security-adjacent), chat shell second (user-facing), settings and utility files third, remaining long-tail last. Each batch should be a clean PR with zero LQ.AI regressions.

**Acceptance criteria:** `npm run check` (full-scope) exits 0; `tsconfig.lq-ai.json` can be retired; Silver OpenSSF Best Practices Badge tier is unblocked from the typecheck signal side.

#### DE-263 — Community skill installer (admin UI)

**Priority:** P2 · **Effort:** M

**Context:** M1 makes the [LegalQuants/lq-skills](https://github.com/LegalQuants/lq-skills) catalog available at deploy time via the `skills/community/` git submodule (commit `216d7ea`). Adding a new community skill after deployment requires updating the submodule on the host, rebuilding the api container, and restarting — friction even for technical operators, impossible for legal-team operators without shell access.

**Specific scope:** Admin-only "Browse community skills" page that lists upstream skills, shows full SKILL.md contents in an install-confirm modal, and persists installed skills as user-scope rows with `forked_from = "lq-skills:<slug>@<commit-sha>"`. Reuses the existing `UserSkillCreate` Pydantic validators for safety. Audit log emits `community_skill.installed` action. See [mini-PRD](contribute/mini-prds/community-skill-installer-ui.md) for the contributor-facing spec.

**Acceptance criteria:** mini-PRD's acceptance checklist is fully satisfied; Cypress e2e covers the install happy path; security review of the new admin endpoint complete.

#### DE-264 — LegalQuants ecosystem integration (PrivacyQuant statutory graph + MCP path)

**Priority:** P2 · **Effort:** L (split into M sub-task + L MCP follow-up)

**Context:** [LegalQuants/privacyquant](https://github.com/LegalQuants/privacyquant) is a sibling MIT-licensed TypeScript project in the same GitHub org, exposing 146 versioned statutory nodes across 20 US state consumer privacy statutes (CCPA/CPRA, VCDPA, CPA, CTDPA, UCPA, TDPSA, OCPA, MCDPA, ICDPA, INCDPA, TIPA, DPDPA, NJDPA, NHDPA, NDPA, KCDPA, MODPA, MCDPA-MN, RIDTPPA, FDBR) via 18 MCP tools — 16 of them deterministic (no LLM, no external API). LQ.AI's M1 starter skill set includes a DPA Checklist Review (skill 4) that operates against general patterns rather than per-statute statutory text; PrivacyQuant's deterministic tools (`pq_check_clause`, `pq_check_applicability`, `pq_resolve_conflict`, `pq_dsar_router`, `pq_score_privacy_risk`) provide citation-grounded statutory checks the same skill can leverage. The integration pattern is the LQ.AI ecosystem play: same org, same transparency posture, complementary surfaces.

**Specific scope:** Two-phase integration. **Phase A (~M2–M3):** port a subset of PrivacyQuant workflows as `skills/community/pq-*` entries (initial candidates: `pq-applicability-check`, `pq-multi-state-conflict-resolution`, `pq-dpa-clause-review`, `pq-dsar-router`). Each skill calls the appropriate PrivacyQuant tool via a documented interface — initially a thin Python shim wrapping the TypeScript MCP server's STDIO transport, eventually replaced by native MCP-client. Skills inherit PrivacyQuant's deterministic citation grounding posture. **Phase B (blocks on MCP-client subsystem from PRD §8.5, M5+):** PrivacyQuant runs as an MCP server in the LQ.AI deployment (Docker Compose service); skills consume it via the standard MCP tool-calling layer; statutory updates flow in via PrivacyQuant's release cadence the same way community skill updates flow in via the `lq-skills` submodule pattern. The pattern generalizes: any future LegalQuants MCP server can plug into the same boundary.

**Acceptance criteria — Phase A:** at least one PrivacyQuant-backed community skill in `skills/community/` with a documented end-to-end path from skill invocation → PrivacyQuant tool call → citation-grounded output rendered in the LQ.AI UI; PrivacyQuant referenced in `README.md` as a LegalQuants ecosystem integration; `docs/skill-authoring-guide.md` updated with the MCP-tool-call skill pattern. **Acceptance criteria — Phase B:** revisit when MCP-client subsystem work begins.

#### DE-287 — Word add-in feature surface (chat, skills, playbooks, tier badge) — deferred to M4 / community contribution

**Priority:** P2 · **Effort:** M (chat + skills) + M (playbook execution) + S (tier badge) = ~26–34 hours of Word-side feature work, on top of the M3 Phase B plumbing

**Context:** The M3 Implementation Plan originally scoped four feature-surface tasks inside the Word add-in: M3-B3 (chat against the open document), M3-B4 (skills in Word with tracked-changes + comments rendering), M3-B5 (playbook execution in Word), and M3-B6 (Inference Tier badge in the task pane). At the M3-A6 PR #57 close (2026-05-21) the M3 critical path was retightened: Phase B retains its plumbing (M3-B1 scaffold + M3-B2 OAuth + M3-B7 signed manifest + code-signing cert procurement + M3-B8 self-hosted JS bundle and version handshake) but defers the four Word-side feature tasks to M4 or to community contribution. The plumbing alone is enough to make the add-in installable and authenticated against an LQ.AI deployment; community contributors with existing Word plugin code can fork against that plumbing without LegalQuants needing to ship every feature surface in M3.

The descope is risk-driven rather than scope-driven. Office.js feature work requires a Word client for live testing, an iterative debug loop against a Microsoft 365 tenant, and a tracked-changes + comments rendering surface that has no analog in the existing SvelteKit codebase. Combining that effort with M3's already-committed Tabular Review (Phase C) + Slack/Teams plumbing (Phase D) + acceptance pass (Phase E) made M3 schedule-risk-bearing. Splitting the feature surface to M4 (where the autonomous layer is the headline) preserves the v0.3.0 release window and matches the open-source-first posture of inviting community contributors into the add-in's user-facing tabs.

**Specific scope (each task carries its own DE-level acceptance):**

- **M3-B3 — Chat against the open document.** Task-pane chat UI mirroring the web app's chat surface (scaled for narrower task pane), open-document and selection-only context modes, streaming responses, 5-state Citation Engine UI with in-doc span highlighting via Office.js range APIs. Calls the existing `/api/v1/chat/completions`; no new backend endpoint. Effort: 8–10 hours.

- **M3-B4 — Skills in Word (apply skill to selection or document).** Task-pane Skills tab pulling from `GET /api/v1/skills`; `Apply skill` flow with whole-document or selection scope; result rendering for redlines (Word tracked changes via `Word.Range.insertText` / `delete` within a tracked-changes session), assessments (Word comments via `Word.Range.insertComment`), and descriptive text (task pane only); Inference Tier badge per-skill execution. Effort: 12–16 hours.

- **M3-B5 — Playbook execution in Word.** Task-pane Playbooks tab; Apply-playbook flow with cost preview confirmation; per-position SSE streaming progress; per-position assessment as Word comment at matching clause location; per-position redline as Word tracked change; position summary card with click-through to the in-doc comment; severity filter/collapse matching the web UI (M3-A4). Effort: 10–12 hours.

- **M3-B6 — Inference Tier badge in task pane.** Task-pane header badge; click-through opens tier-detail panel (reuse web component if practical, else re-implement against `/api/v1/inference-tier-detail`); updates per active chat / skill / playbook execution; matches §3.13 behavior. Effort: 4–6 hours. Parallel with M3-B5 in calendar terms.

**Dependencies (when this work resumes):** the M3 Phase B plumbing (M3-B1 + M3-B2 + M3-B7 + M3-B8) must have shipped; for M3-B5 specifically, M3-A4 (web playbook execution UI) is already shipped (2026-05-19) so the result-rendering surface contract is in place.

**Acceptance criteria:** each task carries its own acceptance criteria from `docs/M3-IMPLEMENTATION-PLAN.md` (Tasks M3-B3 through M3-B6 — see that file for the verification steps). When this DE resolves, the four task entries in the implementation plan transition from "descoped to M4" to "shipped" with cross-references to the PRs that landed them. Community contribution path: a contributor can claim any single task (B3/B4/B5/B6) via a tracking issue and ship it as an independent PR against the M3 Phase B plumbing.

#### DE-288 — Slack/Teams `/lq` slash command + quick-skill flow — deferred to M4 / community contribution

**Priority:** P2 · **Effort:** M (8–10 hours Slack + ~8 hours Teams parity)

**Context:** The M3 Implementation Plan originally scoped four Slack/Teams tasks: M3-D1 (slack-bridge service + OAuth install flow), M3-D2 (`/lq` slash command + `/lq ask` quick-skill flow), M3-D3 (teams-bridge service + Teams OAuth + parity), M3-D4 (bot configuration in LQ.AI admin UI). At the M3-A6 PR #57 close (2026-05-21) the M3 Phase D scope was reduced to plumbing only: M3-D1 (Slack OAuth install + identity binding) + M3-D3 (Teams equivalent) + M3-D4 (admin UI shell). The `/lq` slash command surface (M3-D2) and its Teams mirror inside M3-D3 are deferred to M4 / community contribution.

The Slack/Teams plumbing is enough for an operator to install the bot, complete the OAuth handshake, and surface the identity binding in the admin UI. Without M3-D2, the bot has no user-facing commands — it is installed but inert. That is an acceptable shipping state for v0.3.0 because (a) the bridge service substrate is the load-bearing piece, (b) a community contributor implementing a slash command flow has a clean interface to extend against, and (c) the v0.3.0 release window prioritizes finishing Phases A/B-plumbing/C/D-plumbing/E rather than every user-facing surface inside D.

**Specific scope:**

- **M3-D2 — Slack `/lq` slash command + `/lq ask` quick-skill flow.** Two slash command flows in the `slack-bridge` service: `/lq` (no arg) on a thread forwards thread content as the seed of a new LQ.AI chat, bot replies in-thread with a link to the chat in the web app; `/lq ask "<question>"` runs a configured Org-Profile quick-ask skill (admin-configurable; default `quick-legal-question` skill) against the question and replies in-thread with the answer + a link to open the chat in the web app. Slack user → LQ.AI user identity mapping via email match (unmatched users see a "your Slack account isn't linked" message). Thread contents stored under the linked user's chat history with normal RBAC. Cost-accounting integration tags Slack-sourced inference with `source: slack`. Effort: 8–10 hours.

- **M3-D3 Teams parity for the slash command surface.** The `teams-bridge` service in scope under M3-D3 retains its OAuth install + identity binding surface (the plumbing). The slash-command parity for Teams (the equivalent of M3-D2 in the Microsoft Teams runtime) is deferred to this DE alongside the Slack flow. Effort: ~8 hours assuming the Slack flow is implemented first and the Teams runtime adapter reuses most of the orchestration logic.

**Dependencies:** M3-D1 (slack-bridge service + OAuth install) and M3-D3 plumbing-only scope must have shipped. M3-D4 (bot configuration UI) gives admins the surface to configure the quick-ask skill; without it, the skill is configured via deployment config files.

**Acceptance criteria:** both flows live in `slack-bridge` and `teams-bridge` per the M3-D2 / M3-D3 task acceptance criteria in `docs/M3-IMPLEMENTATION-PLAN.md`. Community contribution path: the Slack flow can ship first as a standalone PR; the Teams parity can ship as a follow-up PR.

#### DE-289 — Lavern as design reference for the Autonomous Layer, full-path ensemble, and MCP catalog

**Priority:** P2 · **Effort:** S (this entry — design study + ADRs) plus downstream impact on M3/M4/M5+ work already scoped

**Context:** [AnttiHero/lavern](https://github.com/AnttiHero/lavern) is an Apache 2.0, TypeScript/React/Fastify/SQLite, open-source "agentic law firm" for document review. It ships 67 specialist agent prompts coordinated through an adversarial debate protocol, a 3-layer verification pipeline (evaluator gates + adversarial debate + 10-pass verification), 21 MCP tools, 9 workflow templates (single-specialist → full adversarial review), 5 bundled legal datasets (CUAD, MAUD, ACORD, UNFAIR-ToS, LEDGAR), a persistent "precedent board," and an autonomous mode ("Clawern") with 30-minute heartbeat monitoring, email/Telegram alerts, precedent accumulation, and cost forecasting. It supports Anthropic, Mistral (EU mode), and local Ollama.

Lavern is the closest public prior art for several LQ.AI roadmap commitments that are currently underdesigned in the PRD, particularly **§3.10 Autonomous Layer (M4)**, the deferred "full chat path" extension of **§3.8 Multi-Model Ensemble Verification**, the MCP tool catalog shape implied by **§8.5 M5+ MCP-client subsystem**, and a possible "complexity dial" on **§3.7 Playbooks (M3)** and **§3.14 Tabular Review (M3)**. It is also the most concrete prior art for Tier 2 of the boundary-register catalog (DE-290 / DE-293): Lavern's `cost-tracker.ts` (R4 economic), `haltCheckHook` (R5 temporal), and dynamic-permissions layer (R6 contextual) are working implementations of the brakes the LQ.AI autonomous layer needs to discharge. Studying Lavern's design choices and writing them up against ours before M3/M4 design freezes is much cheaper than re-deriving the same shape from scratch.

**Stack mismatch makes direct integration uneconomical.** Lavern is TypeScript/React/Fastify/SQLite; LQ.AI is Python/FastAPI/Postgres/SvelteKit (OpenWebUI fork). Apache 2.0 permits code vendoring, but the architecture surface (sync wire formats, single-process SQLite, no vector retrieval, no durable task queue) is strictly weaker than what LQ.AI has already built or specified — re-implementing the ideas natively in the existing services is the right path. Lavern's quality claims also lack independent benchmarks; treat the design as inspiration, not as validated implementation.

**Specific overlap map.**

| Lavern feature | LQ.AI section | Treatment |
|---|---|---|
| 67 specialist agent prompts | §3.4 Skill Library | Already the model. The 67-prompt corpus is potentially seed material for community skills under `skills/community/` (DE-001, DE-219), subject to the skill-contribution path's attorney-attestation gate (§7.5 / `skills/CONTRIBUTING.md`). |
| Adversarial debate protocol with mandatory citations | §3.3 Citation Engine (shipped M2) + §3.8 Ensemble Verification (shipped narrowly on Stage 4 of Citation Engine) | LQ.AI's deterministic substring verification and char-precise offsets are stronger than Lavern's "agents must cite or be discarded." Lavern's contribution is a candidate execution shape for the deferred "full chat path ensemble" framing flagged in §3.8 — N agents debate, an evaluator gates, the user sees the disagreement structure rather than only the reconciled answer. |
| 10-pass verification (context, clarity, accuracy, risk, …) | §3.7 Playbooks (§3.7), §3.14 Tabular Review | Suggests a complexity dial on Playbook execution: single specialist → small panel → full adversarial. Worth scoping as an option on `POST /api/v1/playbooks/{id}/execute` rather than a separate capability. |
| 9 workflow templates | §3.7 Playbooks | The template taxonomy (cost vs. rigor) is a useful framing for how operators choose Playbook execution modes. |
| 21 MCP tools (debate, scoring, verification, knowledge management) | §8.5 M5+ MCP-client subsystem | Concrete prior art for tool categorization and the registration surface. Worth comparing against the MCP-client subsystem skeleton planned for M5 before that work starts. |
| Clawern autonomous mode (30-min heartbeat, alerts, cost forecast, precedent accumulation) | §3.10 Autonomous Layer (M4) | **Highest-value overlap.** §3.10 has committed the architectural slot but explicitly deferred detailed design ("M4 territory; detailed design deferred"). Lavern's Clawern is a working pattern for several of the open questions: how the heartbeat loop interacts with cost budgets, how alerts surface across email and chat, how precedent accumulation contrasts with Project context (§3.11) and user-curated memory. |
| Persistent precedent board | §3.10 vs. §3.11 | A third framing — system-curated cross-matter patterns visible to the user — that sits between Project context (user-curated, per-matter) and autonomous memory (system-curated, system-visible). Worth deciding explicitly whether M4 absorbs this, rejects it, or files it as a separate construct. |
| `cost-tracker.ts` per-session budget (default $5) | DE-293 R4 economic restraint | Most concrete public reference implementation. Suggests $5 as the initial default cap value for the M4 autonomous session. |
| `haltCheckHook` ("the red button") + 5-min idle auto-halt | DE-293 R5 temporal restraint | Direct reference for the liveness primitive and the before-every-tool-call check pattern. |
| Dynamic permissions layer (strips search/read at ethics gate) | DE-293 R6 contextual restraint | Direct reference for per-workflow-phase tool-grant modulation. |
| Bundled legal datasets (CUAD/MAUD/ACORD/UNFAIR-ToS/LEDGAR) | `docs/acceptance-testing-framework.md`; DE-237 eval harness | Useful eval corpora for the Citation Engine and Playbooks, independent of Lavern's runtime. Licensing of each dataset to be verified before any bundling. |
| EU mode (routes through Mistral) | §1.5.2 Inference Tier Spectrum + Provider Compliance Matrix | Already addressed structurally by the Tier model. Lavern's framing as a single switch is worth borrowing as UX language ("EU residency mode") even though the underlying mechanism is the same provider routing. |

**Specific scope (this DE):**

*Phase 1 — design study (before M4 kickoff; ~1 day of reading + writing):*
- Read Lavern's Clawern pipeline source (TypeScript) and write `docs/adr/00XX-autonomous-layer-design-influences.md` comparing it to the §3.10 sketch — naming what LQ.AI adopts, what it adapts, and what it rejects, with the open questions in §3.10 ("Open questions") answered or explicitly punted. The ADR pins the single-agent vs. multi-agent question that gates DE-294 classification.
- Read Lavern's debate protocol and write a short note in §3.8 (or an ADR cross-referenced from it) on whether the "full chat path ensemble" extension should adopt the debate-and-evaluator shape; if yes, file a follow-up DE with concrete scope.
- Read Lavern's MCP tool catalog and capture the categorization in `docs/contribute/mini-prds/mcp-client-subsystem.md` (creating that mini-PRD if it does not yet exist) so the M5 design starts with prior art rather than a blank page.

*Phase 2 — feature increments (folded into existing milestones, not net-new work):*
- **M3 — Playbook execution-mode dial (§3.7).** Add `execution_mode: "single" | "panel" | "adversarial"` to the `POST /api/v1/playbooks/{id}/execute` body, defaulting to `single`. Panel and adversarial route through the same ensemble surface §3.8 already builds on. Cost preview surfaces the mode's expected token spend per §5.5. Estimated +S work on top of M3 §3.7.
- **M4 — Autonomous Layer informed by Clawern (§3.10).** No new line items; the existing M4 scope absorbs the Phase 1 ADR's conclusions. Particular focus areas: heartbeat-loop cost-budget integration; alert surface (email + in-app + optional webhook to align with §3.15 Slack/Teams Bridge once it ships); precedent-board vs. autonomous-memory disambiguation.
- **M5+ — MCP catalog seeded from Lavern (§8.5).** Phase 1 ADR's tool categorization becomes the starting catalog for the MCP-client subsystem's first iteration.

**What is explicitly out of scope:** direct code reuse from Lavern (stack mismatch); bulk import of the 67-agent prompt corpus (skill-contribution path applies per skill); adoption of Lavern's SQLite/Fastify/no-vector-retrieval architecture choices (strictly weaker than LQ.AI's existing substrate); marketing claims about agent counts or verification-pass counts as a quality signal in their own right (§1.9 conservative-posture principle).

**Acceptance criteria — Phase 1:** the autonomous-layer ADR is merged and cross-referenced from §3.10; the §3.8 follow-up note is merged and cross-referenced from §3.8; the MCP-client mini-PRD exists and references Lavern's tool catalog. **Acceptance criteria — Phase 2:** revisit when M3/M4/M5 design freezes for each milestone.

#### DE-290 — Boundary-registers posture document — ✓ Shipped with this PR

**Priority:** P1 · **Effort:** S — ✓ Closed (2026-05-21)

**Context:** §1.8 names the boundary-register catalog (Greenwood, May 2026) as the framework for LQ.AI's boundary-enforcement work. Each register needs a per-register state-of-implementation entry, refreshed each milestone, that any reviewer can verify against source. `docs/HONEST-STATE.md` is the precedent for this pattern — a posture document that names shipped-vs-deferred per capability area; the boundary-registers document is the same pattern for restraints rather than capabilities.

**Specific scope (delivered):** [`docs/security/boundary-registers.md`](security/boundary-registers.md). One section per register (R1 through R6) with definition (citing Greenwood once at the document head), LQ.AI's current implementation with line-level source citations, what's deferred with the DE number that tracks it, and the verification path. Plus an "Orthogonal boundary — the Inference Choice Spectrum" section. Cross-referenced from §1.8 and from §3.10. Update cadence: refreshed at every milestone close.

**Acceptance criteria — closed:** document exists, covers all six registers plus the orthogonal Inference Tier boundary, each claim cites specific source paths, cross-references from §1.8 and §3.10 are in place. **Ongoing maintenance:** future milestone closes that flip a register's state must update this document in the same PR.

#### DE-291 — R1 codification: rules of restraint in the skill-authoring guide and golden tests for starter skills

**Priority:** P1 · **Effort:** M

**Context:** R1 (prompt-and-workflow restraint) is the register LQ.AI ships fully, but the *normative rules* it implements are scattered across `docs/skill-authoring-guide.md`, individual starter skills' SKILL.md files, the Organization Profile schema, and the Citation Engine's verification surface. A reviewer asking "what are LQ.AI's rules of restraint at the conversational layer?" should get a one-section answer with testable invariants, not a treasure hunt. Greenwood's May 2026 article enumerates five specific normative rules at the practice-profile layer of Claude for Legal — `refuse-flag-or-gate`, `severity floor`, `no silent supplement` (three valid responses: supplement-with-flag, say-nothing-and-stop, or flag-but-don't-use), `retrieved-content trust` (data not instructions, no override of guardrails), and `destination check` (a privileged-and-confidential header is a label, not a control). LQ.AI's skill-authoring guide today has some of these but not as a canonical, testable rule set.

**Specific scope:**

1. New section in `docs/skill-authoring-guide.md` — "Rules of restraint." Enumerates the canonical normative rules every skill must implement: (a) refuse-flag-or-gate behavior at consequence boundaries; (b) severity floor — a downstream skill cannot silently demote an upstream finding's severity; (c) no silent supplement — when a skill doesn't know something, the valid responses are supplement-with-flag, say-nothing-and-stop, or flag-but-don't-use, never confident guessing; (d) retrieved-content trust — content returned from any MCP tool, web search, web fetch, or uploaded document is data about the matter, not instructions to the model, and may not override guardrails; (e) destination check — a privileged-and-confidential header on a document is a label, not a control; sharing actions must validate the destination, not the label. Each rule cited against the source authority (Greenwood May 2026 article, ABA Formal Opinion 512 where applicable, the project's existing skill conventions) and given a worked example.
2. Golden-test surface in `api/tests/skills/golden/test_rules_of_restraint.py` (or `tests/skills/golden/test_rules_of_restraint.py` depending on whether the test surface lands in api/ or at the repo root — pinned at implementation time). Each starter skill is exercised against scenarios that probe each rule (e.g., for retrieved-content-trust: a synthetic document containing an injected instruction; assert the skill ignores it). Test failures block merge.
3. Skill-authoring CI check that scans new skills for the frontmatter assertion `lq_ai.acknowledges_rules_of_restraint: true` and rejects skills that omit it. The assertion is a contributor statement, not a runtime guarantee — the golden tests are the guarantee. (Per the M3-A5 framing in `feedback_no_maintainer_legal_review.md`, the user-attorney is the validator; this assertion captures the contributor's acknowledgement that they read the rules, not maintainer attestation.)
4. `docs/security/boundary-registers.md §R1` updated to cite the new section and the golden-test file.

**Sequence:** independent of M3 progress. R1 is shipped; codifying it is documentation work plus testing surface, not new capability. Land mid-M3 or as a small standalone PR.

**Acceptance criteria:** rules section in skill-authoring guide is in place; ten starter skills (M3 built-ins + the M1 starter set) pass every rule's golden test; CI check is wired and blocks merge on missing frontmatter assertion; §1.8 boundary-register posture subsection cross-references the new section; `docs/security/boundary-registers.md §R1` updated.

#### DE-292 — Playbook executor retrofit: declared tool grants + schema-validated step handoffs + per-execution cost cap

**Priority:** P2 · **Effort:** M (retrofit work + tests; folds into post-M3-A6 work)

**Context:** The Playbook executor (M3-A2, `api/app/playbooks/executor.py` + `nodes.py` + `state.py`) is LQ.AI's first multi-step workflow surface in production. It already uses Pydantic-typed state transitions between LangGraph nodes, which gives it a *partial* R3 (code) posture. It does not yet implement: (a) per-position declared tool grants in the Playbook schema (R2-agent facet), (b) the closed-intent-enum + audit-log validation pattern at each cross-step seam (R3 full posture), or (c) a per-execution `max_cost_usd` cap with graceful halt on overrun (R4 partial → fully on the Playbook surface). The prior CC's roadmap-enhancement handoff proposed landing these as in-PR edits to §3.7 before the executor merged; that sequencing is moot because the executor shipped in M3-A2 (`d08bd51`) and M3-A6 PR #57 added more surface on top. This DE retrofits the executor.

**Specific scope:**

1. **Per-position declared tool grants (R2-agent facet).** Add `tools_granted: list[str]` to the `Position` schema in `api/app/schemas/playbooks.py`. The Playbook executor (per-position node in `nodes.py`) validates each step's tool invocations against its declared grants; out-of-grant calls fail with structured error code `tool_not_granted` written to `PlaybookExecution.tool_grant_violations: list[ToolGrantViolation]`. Built-in playbooks (M3-A3 NDA + M3-A5 MSA/DPA) are updated to declare grants explicitly; Easy Playbook wizard output (M3-A6 `app/playbooks/easy/assembly.py`) populates the field with a sensible default (read_document, retrieve_chunks, emit_finding).
2. **Closed intent enum + audit-log validation at step seams (R3 full).** Each transition between executor nodes carries an intent label drawn from a closed enum (`retrieve_clause`, `classify_position`, `draft_redline`, `emit_finding`); the per-intent parameter schema is the existing Pydantic state schema; transitions whose intent or parameters fail validation halt the execution and write a structured failure to `PlaybookExecution.handoff_validation_failures: list[HandoffValidationFailure]`. Accept and reject events are logged via the existing `audit_log` table with `action = playbook_execution.handoff_{accepted,rejected}`.
3. **Per-execution cost cap (R4 partial → fully on the Playbook surface).** Add `max_cost_usd: Decimal | None` to `PlaybookExecutionRequest` (default `None` = no cap; falls back to the per-deployment hard ceiling in `gateway.yaml`'s `inference_tiers` block). The per-step cost-check fires before each model call using the M2-E2 rolling-average estimator (`api/app/citation/cost.py`); an execution that would exceed its cap halts gracefully, surfacing `PlaybookExecution.cost_cap_reached: True` and the partial result. Logged in `PlaybookExecution.cost_total_usd`.
4. **Schema migration.** Three new columns on `playbook_executions` (`tool_grant_violations` JSONB, `handoff_validation_failures` JSONB, `cost_cap_reached` BOOLEAN, `cost_total_usd` NUMERIC). One new column on `playbook_positions` if positions are denormalized, otherwise the `tools_granted` field embeds in the JSONB position payload.
5. **Posture-document update.** `docs/security/boundary-registers.md §R2` and `§R3` and `§R4` updated to reflect the Playbook surface state changes; "deferred" markers updated to "shipped" with line-level citations.

**Sequence:** post-M3-A6, before any further Playbook executor evolution. Folds cleanly as a standalone PR on top of M3-A6.

**Acceptance criteria:** all four code changes shipped; integration tests exercise each (a Position whose tool invocation isn't in `tools_granted` halts with `tool_not_granted`; a Position whose step output fails its schema halts with a `handoff_validation_failures` entry; a Playbook execution whose projected cost exceeds the cap halts gracefully with `cost_cap_reached: True`); posture document refreshed; built-in playbooks updated to declare grants explicitly.

#### DE-293 — Autonomous-layer restraints (R4 economic, R5 temporal, R6 contextual)

**Priority:** P1 · **Effort:** L (folds into M4; tracked as a discrete unit so the implementation specification can mature before M4 design freezes)

**Context:** The autonomous layer (§3.10, M4) is where Tier 2 of the boundary-register catalog (R4 + R5 + R6) first attaches in running code. Lavern (per DE-289) provides the most concrete public prior art: `cost-tracker.ts` enforces a $5-default per-session budget; `haltCheckHook` ("the red button") fires before every tool call and respects an external halt signal, with five-minute idle auto-halt; dynamic permissions strip search/read tools at the ethics gate and delivery phases. LQ.AI's M4 design must discharge each register; the implementation specification below is the concrete bar, derived from the design-influences ADR that DE-289 Phase 1 produces.

**Specific scope:**

1. **R4 — economic.** Per-autonomous-session `max_cost_usd` cap, declared at session creation, defaulting to a per-deployment value in `gateway.yaml` (suggested initial default $5, matching Lavern's posture). Before every tool call the executor checks projected cost against remaining budget; if the call would exceed the cap, the session halts with a `cost_cap_reached` final state. Per-tool cost estimates use the rolling-average mechanism already shipped in M2-E2. Cost is logged per-session in `autonomous_sessions.cost_total_usd`.

2. **R5 — temporal.** Liveness primitive `autonomous_sessions.halt_state` (enum: `running`, `halt_requested`, `halted`, `paused`). Before every tool call, the executor reads `halt_state`; if `halt_requested`, the executor transitions to `halted` and writes the partial state to the session record. Operators halt sessions via `POST /api/v1/autonomous/sessions/{id}/halt` (UI button surfaced in the autonomous-layer dashboard). A session idle for more than `idle_halt_minutes` (suggested default 5, matching Lavern) auto-transitions to `paused` and then `halted`. A halted session's next-attempted tool call fails fast.

3. **R6 — contextual.** Workflows declare phases (`intake`, `analysis`, `drafting`, `ethics_review`, `delivery`) and per-phase tool grants. The executor's current-phase row gates each tool call: a session in `ethics_review` phase with a search-tool grant only at `intake` phase has the search tool stripped at runtime. Phase transitions are explicit (declared in the workflow definition) and audited (`audit_log.action = autonomous_session.phase_transition`).

4. **Posture-document update.** `docs/security/boundary-registers.md §R4` / `§R5` / `§R6` updated to reference the new tables, endpoints, and configuration; "deferred" status updated to "shipped" with line-level citations.

**Dependencies:** §3.10 Autonomous Layer scaffolding; the DE-289 Phase 1 ADR; the M2 cost-tracking infrastructure (`inference_routing_log.cost_estimate`, M2-E2 rolling-average estimator).

**Acceptance criteria:** all three registers implemented per the spec; integration tests exercise each (a session that tries to overspend halts; a session that receives an external halt signal stops on its next tool call; a session in `ethics_review` cannot invoke a tool granted only at `intake`); posture document refreshed; cross-references from §3.10 and §1.8 added.

**Sequence:** the DE entry lands now (with this PR). The implementation lands with M4 once the §3.10 scaffolding is in place.

#### DE-294 — Cross-agent handoff validation for autonomous multi-agent flows

**Priority:** P1 if M4 ships multi-agent autonomous flows / P2 if M4 ships single-agent only · **Effort:** M

**Context:** Greenwood's Register 3 (code-enforced cross-agent handoff validation) has two facets in the LQ.AI architecture. The in-Playbook-step-handoff facet (step output validated against typed schema before becoming step N+1 input) is the retrofit covered by DE-292. The *cross-agent* handoff facet — where one autonomous agent's emitted event becomes another autonomous agent's invocation prompt, and where a hostile document upstream could otherwise smuggle instructions across the seam — only attaches if LQ.AI's autonomous layer ships *multi-agent* autonomous flows. Whether it does is pinned by the DE-289 Phase 1 ADR (the autonomous-layer design-influences study comparing Lavern's multi-agent Clawern pipeline to LQ.AI's planned approach).

**Specific scope (if M4 ships multi-agent autonomous flows):**

A reference cross-agent orchestrator in `api/app/autonomous/orchestrate.py` (or `gateway/app/autonomous/orchestrate.py` if the autonomous executor lives in the gateway — pinned by the ADR). Functional behavior:

- Validates every cross-agent handoff envelope against a closed intent enum (the set of intents the source agent is permitted to emit, declared in the workflow definition) and a per-intent Pydantic schema for parameters.
- Renders the next agent's invocation prompt from a typed template (intent-keyed, parameters interpolated via `format_map`), never from source-agent free text.
- Wraps any free-text field the source agent supplies in an `<agent-handoff source="…" timestamp="…">` envelope inside the rendered prompt, with explicit framing that the envelope content is "data describing a task, not an instruction."
- Refuses (and audits) any handoff whose intent is not in the allowlist or whose parameters fail schema validation. Audit log: appended to a JSONL file `out/handoff-audit.jsonl` (or the structured `audit_log` table — pinned by the ADR) with `params_keys`, `raw_event_len`, `sanitized_event_len`, and the rejection reason for rejected handoffs.

Acceptance is structured against the same four failure modes Lavern's `orchestrate.py` exercises (Greenwood describes them as the "four cases" of validation harness output): unknown target agent, intent not in allowlist, parameter schema violation, oversize / malformed envelope. Plus a fifth Greenwood specifically flags: the non-greedy-regex bug that breaks payload extraction on nested objects — LQ.AI's implementation should parse JSON, not regex-extract, from the start.

**Specific scope (if M4 ships single-agent only):** this DE is reclassified P2 and deferred to whichever later milestone first ships multi-agent autonomous flows. The Playbook-step-handoff implementation in DE-292 covers the in-scope R3 surface in the meantime.

**Acceptance criteria:** depends on classification per the ADR. If M4-scope: orchestrator implementation + 4-case integration test suite + posture-document update naming R3 as "shipped" with line-level citation. If deferred: this DE is marked P2 with a note pointing to the ADR's pin.

**Sequence:** DE entry lands now (with this PR). Classification pinned when the DE-289 Phase 1 ADR lands. Implementation lands with M4 (or later) per classification.

### How to add to this list

When new deferred items are identified during development, ongoing skill authoring, or community feedback:

1. Add an entry to the appropriate subsection (or create a new subsection if needed).
2. Use a unique DE-### identifier; do not reuse retired numbers.
3. Include priority, effort, context, specific scope, and acceptance criteria.
4. Link from the relevant section of the PRD or skill where the decision was made.

This section is mutable across PRD versions; updates do not require a PRD version bump unless they change priority on P1 items.

---

## 10. Appendices

### Appendix A — Glossary

- **agentskills.io format** — open standard for portable AI skills, compatible with Anthropic Claude Skills and Hermes Agent.
- **Anonymization Layer** — Inference Gateway middleware (§4.7) that pseudonymizes sensitive entities before the model call and rehydrates them after; the privacy fallback for Tier 3+ inference.
- **Citation Engine** — LQ.AI's character-fidelity citation pipeline.
- **Citable Chunk** — atomic unit of indexed content with full positional metadata for citation.
- **Compliance Alignment Pack** — `docs/compliance/` documents mapping LQ.AI's design choices to SOC 2, ISO 27001, ISO 42001, GDPR, HIPAA, FedRAMP controls; ships with M1 (§1.8 / §8 M1).
- **Easy Playbook** — auto-generation wizard that drafts a Playbook from prior agreements.
- **Enhance Prompt** — front-running agent that rewrites user input into a structured legal prompt.
- **Inference Choice Spectrum** — five-tier security spectrum (§1.5.2) from local-only (Tier 1) to consumer/free (Tier 5); the central organizing concept of §1.8.
- **Inference Tier** — operator-and-skill-aware classification (1–5) of where customer data goes during inference; surfaced to the user in real time via the Tier badge (§3.13).
- **LQ.AI** — this project.
- **LegalQuants** — the organization stewarding LQ.AI.
- **MCP / MCP server** — Model Context Protocol; an open standard for connecting AI assistants to external systems. The MCP-client subsystem is the integration substrate for the M5+ workflow-intelligence direction (§8.5); the architectural slot is committed in M1–M2.
- **Mode 1 / Mode 2** — self-hosted with cloud LLM keys / self-hosted with local inference.
- **Organization Profile** — singleton skill at the deployment level (§3.12) capturing org-wide voice, jurisdiction, industry, and standard positions; prepended to skill prompts unless declined.
- **Playbook** — codified legal positions for automated contract review.
- **Pre-Empted Procurement Objections** — Appendix E; structured responses to common procurement-team objections, intended to short-cut enterprise procurement review.
- **Project** — user-curated matter-scoped container (§3.11) bundling chats, files, skills, playbooks, and a free-form context document around a single deal, counterparty, or matter.
- **Provider Compliance Matrix** — `docs/compliance/provider-compliance-matrix.md`; per-provider table of compliance facts surfaced to users when they click the Inference Tier badge.
- **Signal Aggregation Service** — proposed M5 backend service consuming workspace signals via MCP, normalizing to a unified Workspace Event schema (§8.5, §9 Workflow Intelligence).
- **Skill** — reusable structured prompt artifact in agentskills.io format.
- **Skill chaining** — composing multiple skills in a single chat.
- **Tabular Review** — M3 capability (§3.14) for structured grid output across N documents; bulk document analysis with citation-grounded cells.
- **Workspace Concierge** — proposed M6 capability (§8.5) layering prioritization and proactive surfacing on top of Signal Aggregation; not a v1 commitment.
- **Work-Product Attribution metadata** — chain-of-custody metadata (§3.3) attached to every model-generated artifact: user, chat/Project, inference tier, provider, model, skills applied, timestamp, content hash.

### Appendix B — License Summary Matrix

| Component | License | Usage |
|---|---|---|
| LQ.AI core (this repo) | Apache 2.0 | Project license |
| OpenWebUI fork (web) | OpenWebUI License | Customized, branding clause respected |
| FastAPI | MIT | Backend framework |
| LangGraph | MIT | Agent runtime |
| pgvector | PostgreSQL License | Vector store |
| Docling | MIT | Document parsing |
| PyMuPDF | AGPL-3.0 | Server-side only, not redistributed |
| Mistral OCR | Paid API | Optional, fallback |
| PaddleOCR-VL | Apache 2.0 | Local-mode OCR alternative |
| Ollama | MIT | Local inference (Mode 2) |
| Langfuse | MIT | Optional LLM observability |
| OpenTelemetry | Apache 2.0 | Standard observability |
| Office.js | Microsoft (free) | Word add-in platform |
| agentskills.io format | Open standard | Skill format |

### Appendix C — Known Risks

1. **OpenWebUI license drift.** OpenWebUI could further restrict their license. Mitigation: pin to a specific version, monitor upstream, maintain a fork-from-BSD-3 plan as fallback.
2. **Foundation model API breaking changes.** Cloud providers occasionally change API behavior. Mitigation: comprehensive provider integration tests in CI, fallback chains in the Gateway.
3. **PyMuPDF AGPL boundary clarification.** Some legal interpretations of AGPL are aggressive. Mitigation: keep PyMuPDF strictly server-side, document the boundary, offer a PyMuPDF-free build configuration as a fallback (using only Docling for offsets, accepting reduced precision).
4. **Office.js platform changes.** Microsoft occasionally deprecates add-in APIs. Mitigation: stick to the documented stable API surface, monitor Microsoft announcements.
5. **Contract law variation across jurisdictions.** Skills and Playbooks default to US-law assumptions; non-US users may need customization. Mitigation: skill metadata supports jurisdiction parameters, community-contributed skills for other jurisdictions.
6. **Hallucinated citations from misuse.** If users disable verification, hallucinated citations could slip through. Mitigation: verification on by default, prominent UI when off, clear disclaimers.
7. **Maintainer bandwidth.** Open-source projects can stall when maintainers get busy. Mitigation: clear governance, multiple committers as community grows, documented release process so others can drive releases.
8. **Weak-tier inference choice by operator.** An operator may configure the deployment to allow Tier 4 or Tier 5 inference for client-confidential work, exposing the deployment to data-retention or training risk. Mitigation: the Inference Tier badge (§3.13) makes the choice transparent to the user; skills can declare `minimum_inference_tier`; deployments can disallow tiers globally; warnings surface when routing at Tier 4 and below; the Compliance Alignment Pack and Pre-Empted Procurement Objections (Appendix E) make the operator-side responsibility explicit.
9. **Workflow-context privacy risk.** If the M5+ Workflow Intelligence direction (§8.5) ships, signals from email, calendar, task systems, and document stores create a much larger sensitive-data surface than v1. Mitigation: granular consent per signal source and per scope; tier defaults that require Tier 1 / Tier 2 inference for these features; opt-in by default for every signal source; skill inspectability extends to workflow skills; relevant only if §I capabilities ship in M5+.
10. **Supply-chain compromise.** A compromised dependency could expose deployments to backdoors, data exfiltration, or remote-code-execution risk. Mitigation: SBOM published per release (§7.8); signed container images with cosign; SLSA-3 build provenance; pinned dependencies enforced in CI; continuous SCA via Trivy / Grype / Dependabot; CodeQL SAST; reproducible builds (deferred to DE-114); coordinated disclosure of supply-chain vulnerabilities per `SECURITY.md`.
11. **Privilege analysis complexity with Anonymization Layer.** When the Anonymization Layer (§4.7) is active and inference routes to Tier 3+, the rehydration step adds a process layer that complicates an attorney-client privilege analysis. Mitigation: privileged Projects (§3.11) disable anonymization by default; Tier 1 inference is the recommended posture for privileged matters; the audit log records the rehydration step explicitly; the privilege banner in the UI warns when anonymization is active in a privileged Project.

### Appendix D — Companion Documents to Produce

The following deliverables are referenced by this PRD and should be produced as separate documents:

1. **LQ.AI Inference Gateway Specification** — full technical spec for the gateway, suitable for an engineer to implement against.
2. **LQ.AI OpenAPI Surface** — complete OpenAPI 3.1 YAML covering every endpoint in §3 and §4.
3. **Skill-Authoring Guide** — how to write a high-quality skill in agentskills.io format.
4. **Playbook-Authoring Guide** — how to write a Playbook.
5. **Deployment Cookbook** — recipes for common production deployments (single-node Docker, K8s with HA Postgres, air-gapped, multi-region).
6. **Skill Drafts (Track 2)** — actual content for the 10 starter skills shipped in M1.
7. **Compliance Alignment Pack** (`docs/compliance/`, M1; per §1.8 and §8 M1 deliverables) — the document set mapping LQ.AI's design choices to SOC 2, ISO 27001, ISO 42001, GDPR, HIPAA, FedRAMP controls. Component documents: `soc2-alignment.md`, `iso-27001-alignment.md`, `iso-42001-alignment.md`, `gdpr-readiness.md`, `hipaa-readiness.md`, `provider-compliance-matrix.md`. FedRAMP and state-privacy alignment documents follow in v1.x or M2.
8. **Code & Supply-Chain Transparency Documentation** (`docs/security/`, M1; per §7.8) — `sbom.md` (SBOM generation and verification), `verifying-releases.md` (cosign signature verification commands), `build-provenance.md` (SLSA-3 attestations), `threat-model.md` (STRIDE-format threat model covering principal data flows), `dependency-security.md` (continuous SCA configuration).
9. **Pre-Empted Procurement Objections** (Appendix E of this PRD; M1) — structured responses to 17 common procurement-team objections, intended to short-cut enterprise procurement review. Updated each release.
10. **Skill-Authoring Guide — Designing Optional Inputs** (companion section of #3 above) — documents the pattern from DE-020: optional inputs that change analytical depth, not just report format.
11. **Procurement-Readiness Pack** (`docs/procurement/`, M1 stretch or v1.x; per DE-086) — SIG Lite responses, CAIQ responses, security architecture summary, data-flow diagram templates.

### Appendix E — Pre-Empted Procurement Objections

This appendix addresses common objections an information-security or legal-operations team will raise during procurement review, paired with LQ.AI's response. Each response either points to an existing artifact (a Compliance Alignment Pack document, an SBOM, the source code), names a roadmap item where parity is being approached, or explains why the objection is misframed for an OSS self-hosted product. The point is to address every plausible objection in writing, in advance, in one place. Operators evaluating LQ.AI internally can adapt these responses to their organization's procurement vocabulary; the underlying answers are stable.

#### Objection: "Is LQ.AI SOC 2 Type II certified?"

**Response.** SOC 2 Type II is an attestation issued to an operating organization, not to a software product. LQ.AI is software you run; the operator (your organization, or a hosting provider you select) is the entity that would receive a SOC 2 attestation for its operating environment. We provide a SOC 2 alignment document (`docs/compliance/soc2-alignment.md`) that maps each Trust Services Criterion to LQ.AI's design choices and configuration options, identifying which controls are project-provided, operator-provided, or joint. An operator following the alignment document's recommendations and operating the deployment in a SOC 2-compliant environment can pursue SOC 2 Type II certification of *that* environment with significantly reduced documentation effort. Closed-source vendors who claim SOC 2 are certifying their own SaaS environment, which is a different question than whether the software is suitable for your environment. The complementary point per §1.8 is that compliance attestation in the absence of source verifiability is a single point of failure: the operator's procurement team is asked to trust an auditor's report it cannot independently verify. LQ.AI ships both layers — the alignment documents that operators use with their procurement teams, and the source that operators (or any third party they hire) use to verify the alignment documents.

#### Objection: "How do we know your compliance alignment documents are not just marketing?"

**Response.** Every claim in every compliance alignment document is verifiable against the source code in this repository. The SOC 2 alignment document cites specific code modules; the OWASP LLM Top 10 mapping (per §9 DE entry) cites specific defenses; the GDPR readiness document cites specific API endpoints; the threat model at `docs/security/threat-model.md` cites trust boundaries that are reified in `api/` and `gateway/`. The operator's security team — or any third party the operator hires — can independently confirm each citation. This is a structurally stronger verification path than the standard closed-source SaaS approach of providing a SOC 2 report and a procurement questionnaire response, because the verification does not terminate in a paid intermediary. We invite verification, first-party (operator security team reads the source) and third-party (operator hires an independent reviewer of their choice). The verification budget is the operator's to set, on a timeline the operator chooses, with a scope the operator defines — none of which is true for closed-source attestation. The `docs/HONEST-STATE.md` document is itself part of this commitment: it names what is shipped, what is deferred, and the verification path for each, so the operator does not have to take any marketing claim on faith.

#### Objection: "Has LQ.AI been pen-tested?"

**Response.** As an open-source project, the LQ.AI codebase is continuously reviewed by anyone who wants to read it, including the project's own maintainers, contributors, and any operator's security team before deployment. The project publishes a threat model (`docs/security/threat-model.md`) identifying trust boundaries and mitigations and runs SAST (CodeQL), dependency scanning (Trivy, Dependabot), and fuzzing (for the Inference Gateway's OpenAI compatibility) on every commit. Specific operating deployments are pen-tested by the operator or their chosen security firm against their specific configuration; the project welcomes and credits responsible disclosure of findings. The project does not commission and publish a single project-wide pen test because the result would not be representative of any specific operator's deployment configuration; instead, we ship the threat model and the tooling for the operator's pen-tester to use.

#### Objection: "Where is LQ.AI's data residency?"

**Response.** LQ.AI does not have a data residency, because LQ.AI does not have data. The operator chooses where to deploy LQ.AI; the data lives in the operator's environment (the Postgres database, MinIO/S3, audit log volumes the operator provisions). The only data that potentially leaves the operator's environment is the inference request to the configured cloud LLM provider, and the operator chooses that provider and the provider's region. The Provider Compliance Matrix (`docs/compliance/provider-compliance-matrix.md`) documents each supported provider's data-residency options. For an EU-only deployment, the operator deploys to EU infrastructure, configures the Inference Gateway to route only to EU-resident provider endpoints (Anthropic EU, AWS Bedrock eu-west-X, Azure OpenAI EU regions, Google Vertex AI EU regions), or runs Tier 1 / Tier 2 inference where no provider call leaves the operator's environment.

#### Objection: "Does the AI provider train on our data?"

**Response.** This is the operator's choice, not the project's. The Inference Tier model (§1.5.2 / §1.8) makes the consequences of the choice explicit. Tier 3 (enterprise managed inference with ZDR / no-training commitments) is the recommended tier for client-confidential work; under Tier 3, no major provider trains on customer data per their commercial terms (Anthropic Commercial Terms, OpenAI Enterprise / API Commercial Terms, AWS Bedrock, Azure OpenAI, Google Vertex AI). The application surfaces the routed tier in the chat UI in real time. Skills can require a minimum tier; deployments can disallow tiers globally. If the operator routes to Tier 5 (consumer endpoints, where some providers train by default), the application warns prominently. Closed-source competitors who offer the same enterprise providers are bound by the same provider terms; the difference is that with LQ.AI, the operator can verify the routing, choose the tier, and even run Tier 1 with no provider involvement.

#### Objection: "What happens to our prompts and outputs?"

**Response.** They are stored in the operator's deployment's Postgres database under the user's chat history, governed by RBAC and the operator's retention configuration. They are sent to the configured inference provider per the routed tier (see prior objection). They are not sent to LegalQuants, the project maintainers, or any third party. The deployment emits no telemetry to LegalQuants by default (§5.7); optional opt-in anonymous usage statistics are clearly flagged and contain no content. The audit log (§5.3) provides a complete record of every prompt, response, and routing decision, which the operator can stream to their SIEM via syslog or webhook.

#### Objection: "Is the AI model audited or certified?"

**Response.** LQ.AI does not train or fine-tune its own foundation model; it uses configured cloud or local models. The model's safety and accuracy properties are inherited from the chosen provider (or, for local models, the model's authors). The project does not endorse a single model; it supports the major providers' models and any OpenAI-compatible local model. We document each major provider's model-evaluation evidence in the Provider Compliance Matrix. Where LQ.AI adds value over the bare model — through skills, playbooks, the Citation Engine, and ensemble verification — those mechanisms are open source and inspectable.

#### Objection: "What is your software supply chain story?"

**Response.** Each release ships with: a Software Bill of Materials (SBOM) in SPDX or CycloneDX format generated by Syft; signed container images (Sigstore/cosign); GPG-signed release tags; SLSA-3-aligned build provenance attestations from GitHub Actions; pinned and audited dependencies (lockfiles enforced in CI); continuous SCA via Trivy / Grype / Dependabot; SAST via CodeQL. Verification commands are documented at `docs/security/verifying-releases.md`. The full build is reproducible from a clean checkout at the release tag (reproducible builds is on the deferred-enhancements list as DE-114; the v1 commitment is the SLSA-3 provenance). We commit to coordinated disclosure of supply-chain vulnerabilities per `SECURITY.md`. Closed-source vendors typically do not provide SBOMs for their internal builds because they cannot — their dependency surface is opaque; an open-source project's supply-chain story is structurally stronger.

#### Objection: "How do you handle privileged communications?"

**Response.** Projects (§3.11) carry an optional `privileged: true` flag that forces a minimum inference tier (default Tier 2; configurable to Tier 1), disables anonymization (which adds processing steps that complicate privilege analysis), and marks every chat and audit-log entry in the Project as privileged. Audit logs include `privilege_marked` and `privilege_basis` fields (§5.3) that support filtering during e-discovery review. Work-product attribution metadata (§3.3) is stored on every model-generated artifact, establishing the chain of custody. The operator can configure the deployment to retain privileged entries on a different schedule than non-privileged entries (see DE-106). For the most sensitive privileged work, run the Project at Tier 1 (local inference) — the prompt never leaves the deployment, eliminating any third-party processor question.

#### Objection: "Does using LQ.AI risk violating Model Rule 5.5 (UPL), 1.1 (competence), or 1.6 (confidentiality)?"

**Response.** LQ.AI is a tool, not a substitute for an attorney's professional judgment — like Westlaw or Word, it produces outputs the attorney reviews under their existing Rule 1.1 competence obligation. ABA Formal Opinion 512 and the growing body of state-bar guidance on generative AI (Florida, California, New York, and DC have all published as of late 2025) consistently hold the attorney responsible for their use of AI in client work; LQ.AI's design supports that responsibility rather than displacing it. **Rule 5.5 (UPL)** is implicated when a non-attorney produces legal advice for third parties — out of scope for LQ.AI (DE-008, business-user contract generation, defers any such workflow to attorney-supervision norms). **Rule 1.6 (confidentiality)** is addressed structurally: self-hosting keeps client data in the operator's environment; the Inference Tier model (§1.5.2) lets the firm choose how much data leaves the deployment, if any (Tier 1 is air-gappable); the privileged-matter flag on Projects (§3.11) forces a minimum tier and tags every audit entry. The skill-contribution model (`skills/CONTRIBUTING.md`) requires practicing-attorney attestation and review for any skill containing legal substance. None of the above is legal advice — operators should consult their own ethics counsel for jurisdiction-specific application.

#### Objection: "Is LQ.AI HIPAA-eligible?"

**Response.** A deployment can be configured to be HIPAA-eligible. The HIPAA readiness document (`docs/compliance/hipaa-readiness.md`) walks through the configuration: limit to Tier 1–3 inference; the operator signs a BAA with the chosen inference provider (Anthropic offers BAA on eligible APIs; OpenAI Enterprise supports BAA; AWS Bedrock under HIPAA-eligible services; Azure OpenAI under Azure's BAA); configure the Citation Engine and audit log per the document's PHI-handling guidance; the operator's organization receives the BAA from the provider directly. The project itself does not enter into BAAs because the project is software, not a service. This is the same structure HIPAA-aware OSS products use.

#### Objection: "How do we handle a GDPR data subject request?"

**Response.** The deployment provides per-user data export and deletion in v1 (`POST /api/v1/users/{id}/export`, `DELETE /api/v1/users/{id}`; per §5.3). Operator-side data-subject-rights tooling — for the harder case where the subject is *referenced* in some other user's chats and files rather than being a user themselves — is on the roadmap (DE-107, P1 priority for EU operators). The GDPR readiness document (`docs/compliance/gdpr-readiness.md`) covers Articles 15–22 (data subject rights), Article 28 (processor relationships), Article 30 (records of processing — exposed via audit log), Article 32 (security of processing), and Article 35 (DPIA, with template). For EU operators, route inference to EU-resident providers per the Provider Compliance Matrix.

#### Objection: "How does LQ.AI handle the EU AI Act, and is it a high-risk AI system?"

**Response.** Under the EU AI Act (in force August 2024; most obligations apply from August 2026), generative-AI-as-a-tool used by lawyers for their own work product is generally a **General Purpose AI (GPAI) model use** — the obligation surface for the underlying foundation model lies with the model provider (Anthropic, OpenAI, Google, etc.), not with LQ.AI. The Annex III "high-risk" classification hinges on deployment context (e.g., automated decision-making in administration of justice, employment, law enforcement); a deployment using LQ.AI for *those* purposes would inherit the high-risk obligations as the operator-deployer. **What LQ.AI provides** is the transparency surface a deployer needs: the Inference Tier model surfaces which provider/region each call routes to; the routing log captures every routing decision; the audit log captures every state-changing action; the open-source skills mean the operator's compliance team can read what each automated step actually does. **ISO 42001** alignment (`docs/compliance/iso42001-alignment.md`, stub at M1; target M2 per `docs/HONEST-STATE.md` §5) is the primary compliance contribution for AI management system requirements that EU AI Act conformity assessment relies on; **NIST AI RMF 1.0 Profile** (mini-PRD at `docs/contribute/mini-prds/nist-ai-rmf-profile.md`) is the contributor-friendly path to deepening this coverage before the August 2026 deadline. For EU operators deploying today, the recommended posture is: route inference to EU-resident provider endpoints per the Provider Compliance Matrix; run privileged matters at Tier 1 (local Ollama) to avoid cross-border data flows; treat the high-risk vs. limited-risk classification as deployment-context-specific rather than a property of the software.

#### Objection: "What if the model hallucinates a citation?"

**Response.** The Citation Engine (§3.3) is structurally defended against this. Every citation must reference a specific chunk of a specific document by ID; the model is constrained at generation time to cite only chunks from the retrieved set; verification compares verbatim quotes against the cited chunks at the byte level; and the LLM-judge verification step catches paraphrased claims unsupported by the source. A failed citation renders as "unverified" in the UI, never as a confident wrong citation. An operator can configure ensemble verification (§3.8) to require multi-model agreement on citations for the highest-stakes operations.

#### Objection: "Can we audit what the AI is actually doing?"

**Response.** Yes. Every state-changing API call writes to the audit log (§5.3); every inference request through the Inference Gateway is traced with provider, model, tier, token counts, and cost; every skill that runs is inspectable in source via the Skill Library UI (§3.4); every prompt and response is stored in the chat history. OpenTelemetry instrumentation feeds traces, metrics, and logs to the operator's chosen sink (Grafana, Honeycomb, Datadog, etc.); Langfuse (optional) provides LLM-specific tracing. The audit log can be streamed to the operator's SIEM. Closed-source competitors typically expose audit logs of *user actions*; LQ.AI exposes the same plus the actual prompts, responses, skills, and routing decisions, because there is no proprietary layer to hide.

#### Objection: "What about prompt injection from a malicious counterparty's document?"

**Response.** This is the genuinely-hard problem in the AI-security space; no commercial competitor has a complete answer either. LQ.AI's defenses are: skill-prompt isolation conventions in the skill-authoring guide (delimited blocks instructing the model not to interpret document content as instructions); structured-output schemas that constrain what the model can produce (DE-111); ensemble verification (§3.8) for high-stakes operations; the prompt-injection pattern library (DE-110) once it ships; and the Citation Engine's verification step which would catch a successful injection that produced an unsupported citation. The honest answer is that a sophisticated injection might still affect outputs in ways the verification does not catch; the operator's defense is the human-in-the-loop review the legal profession already requires. We do not claim to be immune.

#### Objection: "How do we know the open-source code matches what's running?"

**Response.** Container images are signed with Sigstore/cosign and accompanied by SLSA-3 build provenance attestations linking each image to the specific GitHub commit and Actions run that produced it. The operator can verify a deployed image's signature and trace it back to the source commit. Build is reproducible from the release tag (DE-114 strengthens this further). Dependencies are pinned at lockfile level; SBOMs are published per release. This is a stronger story than closed-source SaaS, where the operator has no way to verify what code is running.

#### Objection: "What's your incident response process?"

**Response.** SECURITY.md documents the disclosure email and GPG key, response-time commitments (acknowledge within 72h, fix critical issues within 30d), and public disclosure timing after fix. Past disclosures and fixes are published as security advisories on GitHub. For incidents in a specific operating deployment, the operator owns incident response in their environment; the audit log and OpenTelemetry traces provide the forensics surface, and the project supports the operator's investigation through the same disclosure channel.

#### Objection: "Is this under support?"

**Response.** The open-source project is supported by the LegalQuants-led maintainer team and the broader community. Support cadence: minor releases every 6–8 weeks; LTS designation for one minor version per year with security backports for 12 months; coordinated disclosure with response-time commitments. For organizations that require commercial support, LegalQuants offers managed services (hosted deployments, custom skill authoring, training, support) — the software remains open source and self-hostable; the services are paid (§7.1).

#### Objection: "How do we know your tests are actually testing anything meaningful?"

**Response.** Three structural answers. First, the test surfaces are readable in source: 70 backend pytest files, 27 gateway pytest files, 53 Vitest specs, 10 Cypress E2E specs at M1 (per `docs/HONEST-STATE.md` §6). Any reviewer can read them and assess what they exercise. Second, mutation testing (per §5.8 and §9 DE entry — Mutation testing) will publish a per-release mutation score that proves the tests catch real defects, not just that the lines are executed; the score will render as a README badge alongside the OpenSSF Scorecard. Third, property-based tests for the Citation Engine, the Anonymization Layer, and the Inference Gateway router (per §9 DE entry — Property-based testing) will express load-bearing invariants as properties tested across generated inputs, catching the edge cases example-based tests miss. **M1 status:** the unit and integration suites are in place; mutation and property tests are deferred per §9. The honest answer is that today a reviewer evaluates the engineering-rigor claim from the unit and integration suites plus the OpenSSF Scorecard once it ships; the mutation and property surfaces close the gap on the M2–M4 timeline.

#### Objection: "Has anyone independently reviewed this?"

**Response.** Per §1.8 addition and §9 DE entries 227 and 228: the project commits to an annual third-party penetration test with public executive summary and an annual adversarial-AI red-team engagement with published methodology, attack categories, detection rates, and residual risk. The first engagement of each kind is targeted within 90 days of M1 release, funded by LegalQuants as a project investment. The OpenSSF Best Practices Badge (§9 DE entry — OpenSSF Best Practices Badge: Passing → Silver → Gold) requires public attestation of practices that any reviewer can independently challenge. OWASP ASVS Level 2 third-party verification is committed within 12 months of M1 (per the existing DE-118 commitment). Past disclosures and their remediations are published with credit to reporters (per §7.6). Closed-source vendors typically restrict independent review contractually and gate pen-test reports behind NDAs; the LQ.AI posture is the structural inverse: independent review is invited, scheduled, and published. Reports land in `docs/security/releases/`; readers can verify the commitment becomes evidence as the engagements complete.

#### Objection: "What is your reliability story for a production deployment?"

**Response.** Per §5.9: published Service Level Objectives and the corresponding Service Level Indicators for a reference deployment with documented measurement methodology (API availability target 99.9% monthly; p99 latency by capability; inference-fallback success rate; audit-log durability); a documented error budget policy; public postmortems within 14 days for any incidents in LegalQuants-operated infrastructure; quarterly disaster-recovery test cadence with published reports for LegalQuants-managed environments; runbooks in `docs/runbooks/` for every operational task. Performance regression with historical tracking (per §5.8 and §9 DE entry — Performance regression) proves no PR materially regresses production behavior. **M1 status:** the OpenTelemetry instrumentation (§5.4) and the audit log (§5.3) are in place at M1; the SLO catalog, the error budget policy, the runbook directory, and the postmortem template are deferred per §9. The reliability commitments are structural — they describe how the project handles production maturation rather than asserting it has been reached.

#### Objection: "What if LegalQuants disappears?"

**Response.** The Apache 2.0 license guarantees that the codebase, the documentation, and the rights to use and modify them survive any change in maintainer. The project's governance (§7.4) commits to a path toward a maintainer team and formal governance as the project matures. The skills are agentskills.io-compatible and run in any compatible runtime; the inference gateway is a focused 3,000 LOC piece of code that any competent engineering team can take over. The fork-able-and-deployable structure of the project is the single strongest answer to vendor-continuity risk; closed-source vendors cannot match it.

#### Objection: "If a skill produces wrong output and an attorney relies on it, what is our exposure?"

**Response.** The Apache 2.0 license disclaims warranty in the standard form (LICENSE §7, "AS IS") — the same posture every OSS license takes, and the same effective posture closed-source legal AI EULAs take (their warranty disclaimers are typically more aggressive than Apache 2.0's). The substantive risk allocation is the same as any tool an attorney uses: the attorney exercises professional judgment over the work product they sign or send (Rule 1.1; see prior objection on UPL / competence / confidentiality). What LQ.AI changes versus closed-source alternatives is the **verification surface**: the attorney can read the skill that produced the output before relying on it (`skills/<name>/SKILL.md`, one click away in the application); fork and adjust it to their team's actual practice; read the Citation Engine's verification logic (M2; M1 marks unverified text honestly per `docs/HONEST-STATE.md` §3.1); and read the audit log to reconstruct what the model was asked and what it answered. The same warranty disclaimer applies as any tool, but the attorney's ability to verify before relying — which is what the rules of professional conduct require — is structurally stronger. The project does not warrant any skill produces correct legal output in any specific factual context; no vendor in the legal AI category does, and any vendor who claims to has misrepresented their product.

---

*End of LQ.AI PRD v0.2.*

*Drafted by Kevin Keller for contribution to LegalQuants. Comments, corrections, and contributions welcomed via GitHub once the repository is published.*
