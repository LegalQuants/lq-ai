# Procurement-Readiness Pack

> **Status:** AI-drafted, pending professional review. The pack's core documents (Security Assessment Response Pack, CAIQ self-assessment, cover-letter template) are drafted; counsel review per §Contributing below gates operator-facing use. Tracked as [DE-086](../PRD.md#de-086--procurement-readiness-pack); community contributions remain welcome.

Procurement reviews are one of the highest-leverage adoption barriers for any tool deployed in enterprise environments — including open-source software the operator runs themselves. In-house counsel evaluating LQ.AI for use in their organization typically need to satisfy their procurement team's standard intake process, which involves SIG Lite (Standardized Information Gathering Lite from Shared Assessments), CAIQ (Consensus Assessments Initiative Questionnaire from Cloud Security Alliance), or a custom enterprise security questionnaire.

The Procurement-Readiness Pack is the project's contribution to that work: substantive responses covering the ground the common procurement questionnaires cover, with operator-overridable fields for items that depend on specific deployment configuration.

**A note on questionnaire licensing.** The SIG / SIG Lite question set is proprietary to Shared Assessments (paid license; no public right to reproduce the questions). The pack therefore does **not** ship SIG-keyed responses; it ships a **self-authored Security Assessment Response Pack** covering the same domains under the project's own taxonomy, plus a completed **CAIQ-style** self-assessment (the CAIQ is free to complete and to redistribute as one's own filled copy with CSA's notices intact). Operators whose programs license the SIG can complete it from the response pack — see the cover letter. This licensing position is itself flagged for counsel confirmation.

## What lands here

| Document | Status | Description |
|---|---|---|
| [`sig-lite.md`](sig-lite.md) | **Drafted** — AI-drafted, pending professional review | **Security Assessment Response Pack** (self-authored; filename retained from the M2-D3 SIG-starter era so links keep resolving). Covers privileged-matter handling, audit/logging, and the M3 external trust boundaries (Word add-in, Slack/Teams bridges); points to `caiq.md` for the remaining domains. |
| [`caiq.md`](caiq.md) | **Drafted** — AI-drafted, pending professional review; STAR Level 1 submission is a planned follow-up | Completed CAIQ-style self-assessment across all 17 CSA CCM v4 control domains plus an AI-specific (AI-CAIQ v1.0.2-oriented) supplement. Structured for transcription into the official CSA spreadsheet, with per-row ownership class and repo-path evidence. |
| [`cover-letter.md`](cover-letter.md) | **Drafted** — AI-drafted, pending professional review | Cover-letter template the operator adapts for their procurement team — what LQ.AI is, why it's an unusual procurement (self-hosted open source rather than SaaS), the certification-vs-alignment position, the licensed-questionnaire offer, and artifact-verification (SBOM / cosign / SLSA) instructions. |
| `aup-soc-template.md` | Future | Template Acceptable Use Policy and Statement of Operational Controls the operator can adapt for their internal AI-governance program. |

## Format

Each assessment response follows this format:

- **Question** — the project's own formulation of the assessment topic (self-authored, or a paraphrase of a freely-licensed framework's question intent — never reproduced text from a proprietary questionnaire).
- **Project response** — the answer that applies to a typical LQ.AI deployment.
- **Ownership class** — one of **structural-in-code** (the codebase enforces it), **operator-configured** (the deployment must supply it), **shared** (code provides the mechanism, the operator provides policy/config), **residual** (a known gap, cited by its DE-number rather than left blank), or **out-of-scope** (not a property of the software).
- **Operator-configurable items** marked `[OPERATOR-CONFIGURABLE]` where the answer depends on the operator's specific configuration. The marker is followed by a description of what the operator should fill in.
- **References** — every response cites a resolving repository path (code, doc, workflow) an assessor can open, or is marked `[OPERATOR-CONFIGURABLE]`. Deferred/unshipped capability is answered honestly per [`docs/HONEST-STATE.md`](../HONEST-STATE.md), never overstated.

## Why "operator-configurable"?

LQ.AI is **not a SaaS vendor**. It is software the operator runs in their own environment. Many procurement questionnaire questions assume a SaaS context ("Where is the data stored? In which AWS region?") and the answer for LQ.AI is "wherever the operator chose to deploy" — which the project cannot pre-fill on the operator's behalf.

The `[OPERATOR-CONFIGURABLE]` marker makes this explicit. The operator answers the question for their specific deployment; the project provides the structure and the boilerplate that doesn't change across deployments.

## Related procurement-defense materials

- [PRD §1.8 Security Posture](../PRD.md#18-security-posture) — the underlying security model.
- [PRD Appendix E Pre-Empted Procurement Objections](../PRD.md#appendix-e--pre-empted-procurement-objections) — 17 procurement-team objections with substantive answers, organized by topic.
- [`docs/compliance/`](../compliance/) — Compliance Alignment Pack mapping the project to SOC 2, ISO 27001, ISO 42001, GDPR, HIPAA, FedRAMP.
- [`docs/security/`](../security/) — security artifacts (SBOM, threat model, supply-chain transparency, signed releases).

## Contributing

Procurement-readiness materials are one of the highest-leverage community contribution targets — every operator who has completed a procurement cycle has substantive material that helps the next operator. The contribution path:

1. Open an issue (or pick up [DE-086 / Issue 10](https://github.com/legalquants/lq-ai/issues) when published) describing what you have.
2. Draft the response in your fork following the format above.
3. Mark operator-configurable items consistently.
4. Submit a PR; counsel review applies (procurement responses are reviewed for legal accuracy before merge).

If you completed a procurement cycle for your organization's LQ.AI deployment and want to contribute the responses back without doing extra anonymization work, that's the highest-value first contribution to this folder.

---

*Pack maintained alongside the PRD. Updates land as community contributions are accepted.*
