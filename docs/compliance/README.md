# Compliance Alignment Pack

> **Status:** Stub at v1 launch. The Compliance Alignment Pack is a documented commitment in [PRD §1.8 Security Posture](../PRD.md#18-security-posture) and lands in M1–M2; this README documents the scope and provides operator-usable orientation in the interim.

The Compliance Alignment Pack is a set of documents mapping LQ.AI's design, architecture, and operational posture to the controls of major compliance frameworks. It is **not a certification** — LQ.AI is open-source software the operator deploys and operates; the operator's deployment is what gets certified, not the project itself. The Pack is the project's contribution to the operator's certification work: pre-mapped control responses with citations to PRD sections, code modules, and documentation, so the operator's compliance team has a substantive starting point rather than a blank questionnaire.

## Frameworks covered

| Framework | Status | Document |
|---|---|---|
| **NIST AI RMF 1.0** (AI 100-1) + **Generative AI Profile** (AI 600-1) | Drafted — self-assessment, pending AI-governance-professional review | [`nist-ai-rmf-profile.md`](nist-ai-rmf-profile.md) |
| **SOC 2 (Type II)** — Trust Services Criteria | Stub | `soc2-alignment.md` (M1) |
| **ISO/IEC 27001:2022** — Information Security Management | Stub | `iso27001-alignment.md` (M1) |
| **ISO/IEC 42001:2023** — AI Management Systems | Stub | `iso42001-alignment.md` (M2) |
| **GDPR** — General Data Protection Regulation | Stub | `gdpr-alignment.md` (M1) |
| **HIPAA** — Security Rule and Privacy Rule | Stub | `hipaa-alignment.md` (M2) |
| **FedRAMP Moderate** | Stub | `fedramp-alignment.md` (M2) |

Each document follows a consistent format: control reference, applicability to LQ.AI deployments, the project's design or operational response, and pointers to the relevant PRD sections, code modules, or operational guidance.

The NIST AI RMF profile is the first shipped document in the pack. It extends the format below with a per-row **ownership class** (structural-in-code / operator-configured / operator-only / shared / residual / out-of-scope) and a per-row **evidence path** into the repository (or an explicit "no evidence yet" state with the deferral reference); subsequent alignment documents adopt the same two columns.

## Format

Each alignment document follows this structure:

```
# [Framework] Alignment

## Scope and limits

What this document is and is not. The Pack is the project's contribution to
the operator's certification; certification of the operator's deployment is
the operator's responsibility.

## Control mappings

For each control in the framework:

- Control ID and short description
- Applicability to LQ.AI deployments
- Project response (design, code, operational practice)
- Operator responsibility (what the operator must do to satisfy this control)
- References (PRD sections, code modules, docs)

## Out of scope / operator-responsibility-only controls

Controls where the project provides no design or operational response because
the control is fully the operator's responsibility (physical security of the
deployment host, personnel screening, etc.).

## Open items

Controls where the project's response is in-development. As M1 and M2 ship,
open items resolve.
```

## Related procurement-readiness materials

- [PRD §1.8 Security Posture](../PRD.md#18-security-posture) — the underlying philosophy.
- [PRD Appendix E Pre-Empted Procurement Objections](../PRD.md#appendix-e--pre-empted-procurement-objections) — 17 common procurement-team questions with substantive answers.
- [`docs/security/`](../security/) — security artifacts (SBOM, threat model, supply-chain transparency).
- [`docs/procurement/`](../procurement/) — procurement-readiness templates (SIG Lite, CAIQ, cover letter).

## Contributing

The Compliance Alignment Pack is one of the highest-leverage community contribution targets. Operators who have completed certification cycles for their own deployments have substantive content that benefits every subsequent operator. See [DE-024 (ISO 42001) and DE-100–115](../PRD.md#9-deferred-enhancements-and-identified-future-work) in the deferred-enhancements list for the specific contribution targets.

If you want to contribute, please open an issue with the `compliance` label first to coordinate with maintainers — substantive compliance content is reviewed by counsel before merging.

---

*Pack maintained alongside the PRD. Substantive updates warrant a PRD version bump.*
