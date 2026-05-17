# Procurement-Readiness Pack

> **Status:** Stub at v1 launch. The Procurement-Readiness Pack — pre-filled SIG Lite and CAIQ questionnaires, plus a cover letter template — is tracked as [DE-086](../PRD.md#de-086--procurement-readiness-pack) and is welcomed as a community contribution.

Procurement reviews are one of the highest-leverage adoption barriers for any tool deployed in enterprise environments — including open-source software the operator runs themselves. In-house counsel evaluating LQ.AI for use in their organization typically need to satisfy their procurement team's standard intake process, which involves SIG Lite (Standardized Information Gathering Lite from Shared Assessments), CAIQ (Consensus Assessments Initiative Questionnaire from Cloud Security Alliance), or a custom enterprise security questionnaire.

The Procurement-Readiness Pack is the project's contribution to that work: pre-filled responses for the most common procurement questionnaires, with operator-overridable fields for items that depend on specific deployment configuration.

## What lands here

| Document | Status | Description |
|---|---|---|
| [`sig-lite.md`](sig-lite.md) | **Starter (M2-D3)** — privileged-matter handling only; full pack [DE-086](../PRD.md#de-086--procurement-readiness-pack) | Pre-filled SIG Lite responses calibrated to the typical LQ.AI deployment. The M2-D3 starter covers the data-protection + audit questions whose answers depend on the privileged-project handling; community contributions fill in the remaining ~15 SIG Lite domains. |
| `caiq.md` | TBD ([DE-086](../PRD.md#de-086--procurement-readiness-pack)) | Pre-filled CAIQ Lite questionnaire mapped to CSA Cloud Controls Matrix. |
| `cover-letter.md` | TBD | Sample cover letter the operator can adapt for their procurement team — explains what LQ.AI is, why it's an unusual procurement (self-hosted open source rather than SaaS), and points at relevant artifacts. |
| `aup-soc-template.md` | Future | Template Acceptable Use Policy and Statement of Operational Controls the operator can adapt for their internal AI-governance program. |

## Format

Each questionnaire response follows this format:

- **Question** as it appears in the source questionnaire.
- **Project response** — the answer that applies to a typical LQ.AI deployment.
- **Operator-configurable items** marked `[OPERATOR-CONFIGURABLE]` where the answer depends on the operator's specific configuration. The marker is followed by a description of what the operator should fill in.
- **References** to relevant PRD sections, Compliance Alignment Pack control mappings, or Pre-Empted Procurement Objections in PRD Appendix E.

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
