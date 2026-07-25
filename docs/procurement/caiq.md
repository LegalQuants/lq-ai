# CAIQ Self-Assessment — LQ.AI

> **Status:** AI-drafted, pending professional review.
>
> Per [`docs/procurement/README.md` §Contributing](README.md#contributing), procurement responses are counsel-review-gated: this document is reviewed for legal accuracy before an operator should hand it to a procurement team as-is.

| | |
|---|---|
| **Assessed artifact** | LQ.AI — self-hosted open-source AI platform for in-house legal teams (this repository) |
| **Codebase state pinned** | Fiduciary-grade agentic legal work milestone close; migration head `0064` (see [`docs/HONEST-STATE.md`](../HONEST-STATE.md)) |
| **Framework referenced** | CSA Cloud Controls Matrix (CCM) v4 control-domain taxonomy, as used by the Consensus Assessments Initiative Questionnaire (CAIQ); the AI-specific supplement is oriented toward CSA's AI-CAIQ v1.0.2 (October 2025) |
| **Author** | LQ.AI project maintainers (self-assessment) |
| **Date** | 2026-07-25 |
| **Review state** | AI-drafted; pending counsel + maintainer review; not yet submitted to the CSA STAR Registry |

## What this document is, and is not

This is a **self-assessment by the project team**. It is not an audit, not an attestation, and not a certification. Certifications and authorizations (SOC 2 reports, ISO 27001/42001 certificates, FedRAMP ATOs, HIPAA obligations and BAAs) attach to **operating organizations**; LQ.AI is software the operator runs, so this document maps LQ.AI's structural controls to the criteria the **operator's** assurance program must satisfy. Every "Yes" from a software project is inherently a shared-responsibility statement: the code supplies a mechanism, and the operator's deployment and program supply the rest.

**Attribution and licensing.** "CAIQ," "Cloud Controls Matrix," "CCM," "AI-CAIQ," and "STAR" are work product of the [Cloud Security Alliance](https://cloudsecurityalliance.org/) (CSA). This document references CSA's **control-domain names** with attribution and paraphrases the **intent** of assessment questions in the project's own words; it does not reproduce official CAIQ question text, and the row numbers below are the project's own, **not** official CAIQ question IDs. Per CSA's licensing terms, a provider may distribute its own completed CAIQ with CSA's trademark and copyright notices intact; when this content is transcribed into the official CAIQ or AI-CAIQ spreadsheet, all CSA notices in that spreadsheet must be preserved.

**Path to STAR Level 1.** This document is structured domain-by-domain against the CCM v4 taxonomy so the maintainer (or an operator) can lift each row into the corresponding section of the official CAIQ / AI-CAIQ spreadsheet downloaded from CSA, and submit the completed spreadsheet to the [CSA STAR Registry](https://cloudsecurityalliance.org/star/) as a Level 1 self-assessment — a free, publicly checkable listing. That submission is a planned follow-up, not a completed fact; do not represent LQ.AI as STAR-listed until the listing exists.

## How to read the tables

Columns:

- **#** — the project's own row number within the domain (not an official CAIQ ID).
- **Question intent** — the assessment topic, paraphrased in the project's own words.
- **Response** — Yes / Partial / No / Out-of-scope, with the substance.
- **Ownership** — **structural-in-code** / **operator-configured** / **shared** / **residual** / **out-of-scope** (the taxonomy used across the pack; see [`docs/procurement/README.md`](README.md)). This maps onto the CAIQ's shared-security-responsibility (SSRM) columns: structural-in-code ≈ provider-owned, operator-configured ≈ customer-owned, shared ≈ shared.
- **Evidence** — a repo path an assessor can open, or `[OPERATOR-CONFIGURABLE]` where the answer depends on the operator's deployment. Deferred work is cited by its DE-number in [PRD §9](../PRD.md#9-deferred-enhancements-and-identified-future-work) — a named gap, never a blank.

Claims are calibrated against [`docs/HONEST-STATE.md`](../HONEST-STATE.md); if a row and the codebase disagree, the codebase is canonical.

---

## A&A — Audit & Assurance

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| A&A-1 | Does the provider hold independent audit reports or certifications (SOC 2, ISO 27001, etc.)? | **No.** The project holds no certifications; certifications attach to operating organizations, and the operator's deployment is what gets certified. The Compliance Alignment Pack maps controls to those frameworks for the operator's program. | out-of-scope (project) / operator-configured (deployment certification) | `docs/compliance/README.md`; `docs/HONEST-STATE.md` §7 |
| A&A-2 | Is recurring independent security testing performed? | **Not yet.** An annual third-party penetration test and an annual adversarial-AI red-team engagement are committed (executive summaries to be published in-repo), but the first engagements have not been performed. Stated as a residual gap, not a shipped control. | residual | `docs/HONEST-STATE.md` §8; PRD §1.8 (`docs/PRD.md`); publication target `docs/security/releases/README.md` |
| A&A-3 | Can the customer independently audit the product? | **Yes.** Full source is public (Apache-2.0); the honest-state catalog gives per-claim verification paths; the audit log gives per-deployment evidence. | structural-in-code | `LICENSE`; `docs/HONEST-STATE.md` §10; `api/app/audit.py` |

## AIS — Application & Interface Security

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| AIS-1 | Is there a secure development lifecycle with enforced gates? | **Yes, with one honest caveat.** CI enforces lint + format (ruff), type checking (mypy; strict on the gateway), and test suites per subsystem. The 80% coverage target is **not** CI-enforced as a failing threshold. | structural-in-code (gates) / residual (coverage gate) | `.github/workflows/ci.yml`; `docs/HONEST-STATE.md` §8 |
| AIS-2 | Are APIs specified under a documented contract? | **Yes.** OpenAPI sketches are the canonical endpoint contracts, with schema-conformance tests. | structural-in-code | `docs/api/backend-openapi.yaml`; `docs/api/gateway-openapi.yaml`; `api/tests/test_openapi.py` |
| AIS-3 | Do security-sensitive changes receive security review? | **Yes.** CODEOWNERS routes `gateway/**`, CI workflows, and security docs to security reviewers; PRs are held until they approve. | structural-in-code | `.github/CODEOWNERS`; `CLAUDE.md` (security-sensitive paths) |
| AIS-4 | Is input validated at the application boundary? | **Yes.** Request/response models are Pydantic-typed throughout the api and gateway. | structural-in-code | `api/app/schemas/`; `gateway/app/` |

## BCR — Business Continuity Management & Operational Resilience

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| BCR-1 | Are business-continuity and disaster-recovery plans, backups, and RTO/RPO targets in place? | **Operator-owned.** The project ships no backup tooling, runbooks, SLOs, or DR cadence yet (an acknowledged gap). `[OPERATOR-CONFIGURABLE]` — the operator's BC/DR program covers the deployment. | operator-configured / residual (project tooling) | `docs/HONEST-STATE.md` §9 |
| BCR-2 | Are the stateful stores documented so the operator can plan backups? | **Yes.** The reference deployment names every state store (Postgres, Redis, MinIO); the DB schema is documented. | structural-in-code | `docker-compose.yml`; `docs/db-schema.md` |

## CCC — Change Control & Configuration Management

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| CCC-1 | Are changes reviewed, tracked, and attributable? | **Yes.** PR review with DCO sign-off; CI gates on every PR; security-path routing per CODEOWNERS. | structural-in-code | `CONTRIBUTING.md`; `.github/workflows/ci.yml`; `.github/CODEOWNERS` |
| CCC-2 | Are schema changes versioned and reproducible? | **Yes.** All schema changes are Alembic migrations, applied in order at boot. | structural-in-code | `api/alembic/versions/` |
| CCC-3 | Is runtime configuration managed and documented? | **Yes.** The gateway's configuration shape is canonical in the example file; config hot-reload is via SIGHUP per ADR. | structural-in-code / operator-configured (values) | `gateway.yaml.example`; `docs/adr/0010-gateway-config-hot-reload.md` |

## CEK — Cryptography, Encryption & Key Management

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| CEK-1 | Is sensitive data encrypted at rest? | **Partial, by data class.** Provider API keys: Fernet under `LQ_AI_GATEWAY_MASTER_KEY`. Slack bridge bot tokens and per-user MCP OAuth tokens: Fernet under distinct master keys (`LQ_AI_BRIDGE_MASTER_KEY`, `LQ_AI_MCP_MASTER_KEY`). Passwords: bcrypt. Whole-database / volume encryption: `[OPERATOR-CONFIGURABLE]` (disk/volume encryption in the operator's environment). | shared | `gateway/app/secrets.py`; `docs/security/encrypted-keys.md`; `api/app/security/encryption.py`; `api/app/security/passwords.py` |
| CEK-2 | Is data encrypted in transit? | **Operator-terminated.** TLS termination sits at the operator's reverse proxy; in-cluster transport security is the operator's deployment choice. `[OPERATOR-CONFIGURABLE]`. | operator-configured | `docs/security/cryptography.md`; `docs/HONEST-STATE.md` §9 (reverse-proxy/TLS recipes not yet shipped) |
| CEK-3 | Who holds the key material? | **The operator, exclusively.** Bring-your-own provider keys; master keys are operator-generated environment secrets; the project holds no keys for any deployment. | structural-in-code (custody model) / operator-configured (key handling) | `gateway/app/secrets.py`; `docs/security/encrypted-keys.md`; `README.md` (BYO-keys) |
| CEK-4 | Is the cryptography inventory documented? | **Yes.** | structural-in-code | `docs/security/cryptography.md` |

## DCS — Datacenter Security

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| DCS-1 | Physical and environmental security of the hosting facility? | **Out-of-scope for the software.** LQ.AI is self-hosted; facility controls belong to the operator's data center or cloud provider. `[OPERATOR-CONFIGURABLE]`. | out-of-scope | `docs/architecture.md` (deployment model) |

## DSP — Data Security & Privacy Lifecycle Management

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| DSP-1 | Is data classified, with controls per classification? | **Yes.** Privileged/non-privileged project classification with per-classification controls (anonymization skip, tier floor, audit columns). Detailed in the response pack. | shared | [`sig-lite.md`](sig-lite.md) Q1–Q2; `gateway/app/tier_floor.py`; `gateway/app/anonymization/middleware.py` |
| DSP-2 | Is data minimized before disclosure to third parties? | **Yes (mechanism), with a measured caveat.** The Anonymization Layer pseudonymizes chat content before provider transmission; recognizer accuracy on legal-document corpora is empirically unmeasured (DE-282, residual). | structural-in-code (mechanism) / residual (empirical validation) | `gateway/app/anonymization/middleware.py`; `docs/security/anonymization.md` |
| DSP-3 | Are retention and disposal schedules enforced? | **No.** Configurable retention policies are **not shipped** (DE-106). The application retains rows indefinitely; operators implement retention via scheduled DB jobs. `[OPERATOR-CONFIGURABLE]`. | residual / operator-configured | `docs/PRD.md` §9 DE-106; [`sig-lite.md`](sig-lite.md) Q3 |
| DSP-4 | Are data-subject rights (export, deletion) supported? | **Partial.** Per-user GDPR-aligned export and account deletion are shipped. Operator-side tooling for subjects *referenced* in other users' data (the harder DSAR case) is **deferred** (DE-107). | shared / residual (DE-107) | `api/app/workers/user_export.py`; `api/app/workers/user_deletion.py`; `api/app/api/users.py`; `docs/PRD.md` §9 DE-107 |
| DSP-5 | Where does data reside? | **Wherever the operator deploys.** Residency is a deployment decision, including which inference tier/provider (if any) content may reach. `[OPERATOR-CONFIGURABLE]`. | operator-configured | `docs/procurement/README.md` (why operator-configurable) |
| DSP-6 | Is customer data used to train models? | **No, structurally.** The project trains no models and operates no service that could ingest customer data. Provider-side training terms are governed by the operator's own contract with their chosen provider; the tier model exists to route sensitive content to local (Tier 1) or ZDR-contracted tiers. | structural-in-code / operator-configured (provider terms) | `gateway/app/tier_floor.py`; PRD §1.5.2 (`docs/PRD.md`) |

## GRC — Governance, Risk & Compliance

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| GRC-1 | Are security and conduct policies published? | **Yes** (project-side). The operator's internal policies (AUP, usage standards) are their own; a template is a planned pack item (`aup-soc-template.md`, future). | structural-in-code (project) / operator-configured (org policies) | `SECURITY.md`; `CODE_OF_CONDUCT.md`; `CONTRIBUTING.md`; `docs/procurement/README.md` |
| GRC-2 | Is a risk assessment / threat model maintained? | **Yes.** STRIDE threat model plus per-boundary registers. | structural-in-code | `docs/security/threat-model.md`; `docs/security/boundary-registers.md` |
| GRC-3 | Is there an honest register of shipped vs. deferred capability? | **Yes** — the project's distinctive governance artifact; every claim in this pack is calibrated against it. | structural-in-code | `docs/HONEST-STATE.md` |

## HRS — Human Resources

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| HRS-1 | Personnel screening, onboarding/offboarding for staff with data access? | **Out-of-scope for the software** — the people with data access are the operator's. `[OPERATOR-CONFIGURABLE]`. | out-of-scope | — |
| HRS-2 | Are external contributors to the codebase vetted? | **Yes.** Contribution-vetting guidance, DCO sign-off, and attorney-attestation requirements for legal-substance skills. | structural-in-code | `docs/security/external-contribution-vetting.md`; `skills/CONTRIBUTING.md` |

## IAM — Identity & Access Management

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| IAM-1 | How are users authenticated? | **Deployment-local accounts:** JWT bearer auth, bcrypt-hashed passwords, a must-change-password gate, and TOTP two-factor. | structural-in-code | `api/app/security/jwt.py`; `api/app/security/passwords.py`; `api/app/security/totp.py`; `api/app/api/auth.py` |
| IAM-2 | Is enterprise SSO (SAML/OIDC federation) supported? | **No.** Not shipped; authentication is against the deployment's own issuer. Operators requiring SSO should treat this as a gap in their evaluation. | residual | `api/app/security/jwt.py` (deployment-local issuer; no federation module in `api/app/security/`) |
| IAM-3 | Is administrative access role-gated? | **Yes.** Admin endpoints require an authenticated JWT plus an admin-role check; non-admins receive 403. | structural-in-code | `api/app/api/dependencies.py`; `api/app/api/admin.py` |
| IAM-4 | Are service identities least-privilege and fail-closed? | **Yes.** Bridge→api auth is a dedicated bearer matched constant-time, never a user JWT, and refuses all traffic if unset; per-user MCP OAuth tokens are scoped per user and encrypted at rest. | structural-in-code | `api/app/api/dependencies.py` (`require_bridge_auth`); `api/app/models/mcp_oauth.py`; `api/app/security/encryption.py` |

## IPY — Interoperability & Portability

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| IPY-1 | Can the customer take their data out in standard formats? | **Yes.** Per-user export; tabular-review export to XLSX/CSV; the full schema is documented, and the operator owns the database outright. | structural-in-code | `api/app/workers/user_export.py`; `api/app/api/tabular.py`; `docs/db-schema.md` |
| IPY-2 | Is there vendor lock-in? | **No, structurally.** Apache-2.0 licensed, self-hosted, provider-agnostic inference (BYO keys across Anthropic / OpenAI / Azure OpenAI / local Ollama). | structural-in-code | `LICENSE`; `docs/HONEST-STATE.md` §2 |

## IVS — Infrastructure & Virtualization Security

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| IVS-1 | Is there a documented reference deployment? | **Yes** — Docker Compose (canonical) and a drafted Helm chart. Network segmentation, firewalling, and host hardening are `[OPERATOR-CONFIGURABLE]`. | shared | `docker-compose.yml`; `deploy/helm/lq-ai/` |
| IVS-2 | Is outbound network egress controlled? | **Yes, structurally.** The Inference Gateway is the sole egress point for both inference and external tool calls (SSRF-guarded, audited); the backend holds exactly one outbound HTTP client, pointed at the gateway. | structural-in-code | `docs/adr/0014-gateway-egress-boundary-for-tool-providers.md`; `gateway/app/providers/tool/`; `api/app/clients/gateway.py` |

## LOG — Logging & Monitoring

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| LOG-1 | Are security-relevant events logged? | **Yes.** Append-only application-layer audit log written atomically with each state change. | structural-in-code | `api/app/audit.py`; `api/app/models/audit.py`; `docs/security/audit-logging.md` |
| LOG-2 | Are inference and external-tool calls logged? | **Yes.** Per-inference routing log at the gateway; per-tool-call egress log (counts/types only). | structural-in-code | `gateway/app/routing_log.py`; `docs/HONEST-STATE.md` §5.5 (`tool_egress_log`) |
| LOG-3 | Are logs protected against tampering? | **Partial.** Append-only at the application layer; **cryptographic tamper-evidence is not implemented** (DE-100, residual). DB-level protections and retention are `[OPERATOR-CONFIGURABLE]` (retention: DE-106). | shared / residual | [`sig-lite.md`](sig-lite.md) Q3; `docs/PRD.md` §9 DE-100, DE-106 |
| LOG-4 | Is operational monitoring available? | **Yes (instrumentation); operator-run (stack).** OpenTelemetry traces, metrics, and domain spans ship; the collection/alerting stack is `[OPERATOR-CONFIGURABLE]`. | shared | `docs/observability.md` |
| LOG-5 | Do logs avoid capturing sensitive content? | **Yes.** Audit and tool logs carry counts/types/IDs/digests, never raw document text or entity values; the anonymization mapper is per-request, in-memory, never persisted or logged. | structural-in-code | `docs/security/audit-logging.md`; `docs/security/anonymization.md`; `docs/HONEST-STATE.md` §3.2, §5 |

## SEF — Security Incident Management, E-Discovery & Cloud Forensics

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| SEF-1 | Is there a vulnerability-report intake and coordinated-disclosure process? | **Yes** (project-side). | structural-in-code | `SECURITY.md` |
| SEF-2 | Who runs incident response for a deployment? | **The operator.** LQ.AI operates no service and has no visibility into any deployment; the operator's IR program owns detection and response. `[OPERATOR-CONFIGURABLE]`. | operator-configured | `docs/security/threat-model.md` |
| SEF-3 | Does the product support forensics and e-discovery? | **Yes.** `request_id` correlation across audit log, routing log, and application logs; first-class `privilege_marked` filtering for privileged-matter review. | structural-in-code | `api/app/models/audit.py`; [`sig-lite.md`](sig-lite.md) Q4 |

## STA — Supply Chain Management, Transparency & Accountability

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| STA-1 | Is an SBOM produced per release? | **Yes.** SPDX-JSON SBOMs are generated per service image at release, verified non-empty, and delivered as signed cosign attestations bound to the image digest. | structural-in-code | `.github/workflows/release.yml` (`sbom` + `sign` jobs); `docs/security/releases/README.md` |
| STA-2 | Are release artifacts signed with verifiable provenance? | **Yes.** Container images are cosign-signed (sigstore keyless) and carry SLSA build provenance attestations pushed to the registry; a step-by-step operator verification guide ships in-repo. | structural-in-code | `.github/workflows/release.yml` (`attest-build-provenance`, `cosign sign`, `cosign attest`); `docs/security/releases/README.md` |
| STA-3 | Are dependencies managed and reviewed? | **Yes.** Dependabot updates; a documented dependency posture; CI actions pinned to full commit SHAs; new dependencies require explicit justification. | structural-in-code | `.github/dependabot.yml`; `docs/security/dependencies.md`; `.github/workflows/release.yml` (pinned SHAs); `CLAUDE.md` |
| STA-4 | Who are the subprocessors? | **There are none.** The project operates no service and processes no customer data. The only third parties that can see content are the inference/tool providers the **operator** contracts with directly under BYO keys — the operator's vendor list, not the project's. | structural-in-code (architecture) / operator-configured (provider contracts) | `README.md`; `gateway/app/secrets.py` (BYO keys); `docs/architecture.md` |

## TVM — Threat & Vulnerability Management

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| TVM-1 | Is there a vulnerability-disclosure policy? | **Yes.** | structural-in-code | `SECURITY.md` |
| TVM-2 | Are dependency vulnerabilities patched on a cadence? | **Yes** (project-side, via Dependabot + release cadence); applying image updates in a deployment is `[OPERATOR-CONFIGURABLE]`. | shared | `.github/dependabot.yml` |
| TVM-3 | Is penetration testing performed? | **Not yet** — committed (annual, with published summaries) but the first engagement has not occurred. See A&A-2. | residual | `docs/HONEST-STATE.md` §8 |
| TVM-4 | Is runtime/image vulnerability scanning in place? | **Operator-run.** Release SBOMs make operator-side scanning straightforward, but the scanner and policy belong to the operator. `[OPERATOR-CONFIGURABLE]`. | operator-configured | `docs/security/releases/README.md` (SBOM retrieval) |

## UEM — Universal Endpoint Management

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| UEM-1 | How are end-user devices managed? | **Out-of-scope for the software** — endpoints are the operator's, under their MDM/endpoint program. `[OPERATOR-CONFIGURABLE]`. Note honestly: browser and Word-add-in sessions hold JWTs in `localStorage` (the same exposure surface for both), so endpoint compromise is in the operator's threat model. | out-of-scope / operator-configured | `docs/word-addin.md`; [`sig-lite.md`](sig-lite.md) Q6 |

---

## AI-specific supplement (AI-CAIQ-oriented)

CSA's AI-CAIQ v1.0.2 (October 2025) extends the CAIQ with AI governance, security, privacy, and AI-lifecycle questions. The rows below cover that ground in the same format so the maintainer can transcribe them into the official AI-CAIQ spreadsheet alongside the domains above.

| # | Question intent | Response | Ownership | Evidence |
|---|---|---|---|---|
| AI-1 | What models are used, and who governs model selection? | **The operator.** LQ.AI ships no model; the operator brings provider keys (Anthropic, OpenAI, Azure OpenAI) or runs local models (Ollama, Tier 1), and can pin minimum inference tiers per project/skill. | operator-configured (selection) / structural-in-code (tier enforcement) | `gateway/app/tier_floor.py`; `gateway.yaml.example`; `docs/HONEST-STATE.md` §2 |
| AI-2 | Are the prompts and instructions shaping AI output inspectable? | **Yes, structurally.** Skills are open-source work product — every prompt is readable, debuggable, and forkable; no hidden instructions. | structural-in-code | `skills/` (`skills/*/SKILL.md`); `docs/skill-authoring-guide.md` |
| AI-3 | What controls address hallucination / confabulation? | **A layered set, with named gaps.** Four-stage character-level citation verification; a per-turn Citation Ledger of every source actually read; a derive-don't-assert PASS/FAIL fiduciary gate per message. Known gaps stated: quotes spanning two retrieved chunks drop at extraction (DE-277); chat/autonomous gate verdict-tier parity is incomplete (DE-370, DE-371). | structural-in-code / residual (named DEs) | `api/app/citation/verification.py`; `api/app/citation/ledger.py`; `api/app/citation/gate.py`; `docs/HONEST-STATE.md` §3.1, §5.6 |
| AI-4 | What controls limit sensitive-data disclosure to model providers? | **Anonymization + tiering, with a measured caveat.** Pre-transmission pseudonymization (Presidio + custom legal recognizers, streaming-aware rehydration) plus tier floors down to local-only. Recognizer accuracy on legal corpora is empirically unmeasured (DE-282, residual); the documented fallback is Tier 1 routing. | shared / residual (DE-282) | `gateway/app/anonymization/middleware.py`; `docs/security/anonymization.md`; [`sig-lite.md`](sig-lite.md) Q1 |
| AI-5 | Are agentic/tool-using behaviors governed? | **Yes.** Every chat tool call routes through a single governed chokepoint with an in-chat human confirmation gate for destructive/connector calls; autonomous sessions run under hard brakes — cost caps (R4), external halt + idle watchdog (R5), phase-gated tool grants (R6) — and are per-user opt-in, off by default. | structural-in-code | `api/app/tools/governance.py`; `api/app/chat/tool_loop.py`; `api/app/autonomous/guard.py`; `docs/autonomous-layer.md` |
| AI-6 | Is external AI-retrieved content provenance-tracked? | **Yes, and kept honest.** External-source retrieval provenance ("Sources consulted") is architecturally distinct from character-verified citations and never conflated with them; case-law treatment signals are labeled "derived, not editorial." | structural-in-code | `docs/HONEST-STATE.md` §5.5–5.6; `api/app/citation/treatment.py`; `api/app/research/registry.py` |
| AI-7 | Is customer data used for AI training or improvement? | **No, structurally** — see DSP-6. The project trains nothing and collects nothing; provider-side terms are the operator's contract. | structural-in-code / operator-configured | `gateway/app/tier_floor.py`; PRD §1.5.2 (`docs/PRD.md`) |
| AI-8 | Is there human oversight over consequential AI actions? | **Yes.** Connector/destructive tool calls pause for explicit in-chat approval; autonomous output is delivered as findings/receipts for human review, never auto-filed externally; skills with legal substance require practicing-attorney attestation at contribution time. | structural-in-code (gates) / operator-configured (review practice) | `api/app/chat/tool_loop.py`; `api/app/autonomous/receipt.py`; `skills/CONTRIBUTING.md` |

---

## Open items

- **STAR Level 1 submission** — transcribe into the official CAIQ / AI-CAIQ spreadsheet (CSA notices intact) and submit; refresh annually per STAR convention.
- **Counsel + maintainer review** — required before any operator relies on this document externally (see banner).
- Named residual rows above track to their DE-numbers in [PRD §9](../PRD.md#9-deferred-enhancements-and-identified-future-work): DE-100 (tamper-evident audit), DE-106 (retention), DE-107 (DSAR tooling), DE-277, DE-282, DE-370/DE-371, plus the unscheduled first pen-test/red-team engagements.
