# Mini-PRD: OWASP LLM Top 10 Mitigation Mapping

> **Status:** Drafted for the v0.8.1 milestone; pending maintainer and professional security review. This does not assert a released version or completed acceptance.
> **Effort:** S
> **Contributor profile:** Security-aware engineer or AppSec consultant. Reads source comfortably; familiar with OWASP risk-mapping format. ~6-8 hours focused work.
> **Mentor:** Maintainer (Kevin Keller, via PR review)

## What this is

A new document at `docs/compliance/owasp-llm-top10.md` that maps each of the ten risks in the **2025 edition** of the [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llm-top-10/) to LQ.AI's architecture, mitigations, residual risk, and operator responsibility. Each structural claim cites specific files and inclusive line ranges at a pinned source revision so a reviewer can verify the mitigation in source. The mapping records its source snapshot separately from the v0.8.1 milestone.

Where a mitigation is partial, the document names its configuration, failure and coverage limits directly. The M2 Citation Engine and Anonymization Layer have shipped; their residual risks remain relevant, including unquoted reasoning and unmeasured recognizer performance on legal corpora. Distinguish shipped code, operator configuration, release-artifact evidence and deferred controls.

## Why it matters

The OWASP LLM Top 10 is the de facto procurement framework for AI-product security review. When an operator's security team is asked to bless an LLM-touching tool, the OWASP LLM mapping is the first artifact they look for; absence of one is treated as a signal the vendor hasn't thought through AI-specific risks. The frameworks the project already maps against (SOC 2, ISO 27001, GDPR) cover the application-security and privacy surface; the LLM Top 10 covers the AI-specific surface the operator's security team will not find in those mappings.

Source citations let the operator verify the implementation. LLM01:2025 (Prompt Injection) cites the assembler in [`gateway/app/skills/assembler.py`](../../../gateway/app/skills/assembler.py) and the threat model in [`docs/security/threat-model.md`](../../security/threat-model.md). LLM02:2025 (Sensitive Information Disclosure) cites the audit writer, the master-key workflow in [`docs/security/encrypted-keys.md`](../../security/encrypted-keys.md), and the shipped anonymization middleware with its skips and disabled default. The operator's security reviewer reads the cited files and forms their own judgment.

The post-attestation procurement posture treats source verifiability as a first-class trust signal alongside paid attestation. The LLM Top 10 mapping is one of the cleanest examples of why: every claim points to source, none of the claims terminate in a paid intermediary.

## What we'd ship

The mapping plus a standard-library citation checker, regression tests and a CI job:

```
docs/compliance/
└── owasp-llm-top10.md       # NEW — 10 risk sections + cover + scope notes
scripts/check-compliance-citations.py
scripts/tests/test_compliance_citations.py
.github/workflows/ci.yml    # compliance-citations job
```

Document structure:

```
# OWASP Top 10 for LLM Applications — LQ.AI Alignment

## Scope and limits
What this document is. What it is not (it is not a certification; it is a
mapping of mitigations to specific implementation, with residual risk
named honestly).

## How to read this document
Each risk has five fields:
  - Threat as it applies to LQ.AI's architecture
  - Structural mitigations (design choices baked into the codebase)
  - Operator-configured mitigations (defaults that can be tuned)
  - Residual risk (what is not mitigated, with the deferral path if known)
  - Operator responsibility (what the operator must do to close residual risk)

## LLM01:2025 — Prompt Injection
[Threat / Structural mitigations / Operator-configured / Residual / Operator responsibility]

## LLM02:2025 — Sensitive Information Disclosure
[...]

[... LLM03 through LLM10 ...]

## Out of scope
Risk slices not applicable to LQ.AI's architecture (e.g., training-time
poisoning under LLM04:2025 is delegated to the operator's chosen model
provider because LQ.AI does not train or fine-tune models). Retrieval-time
poisoning remains in scope. LLM10:2025 is Unbounded Consumption.
```

Per-risk content lives in five paragraphs:

1. **Threat as it applies to LQ.AI's architecture.** Specific. Names the trust boundaries from [`docs/security/threat-model.md`](../../security/threat-model.md).
2. **Structural mitigations.** Cites specific file paths and inclusive line ranges. For LLM01: the untrusted-content envelope in `gateway/app/skills/assembler.py` (ADR 0007, amendment of 2026-09-02) — JSON-encoded, source-labelled unconsumed inputs under a data-not-instructions policy, plus escaping of input-created assembler headings in placeholder-consumed inputs — **described as envelope integrity, not isolation**: untrusted content still sits in the system message, and the relocation is open as DE-388. Cite the gap as a residual risk, never as a mitigation. Distinguish tool-role messages from that system-message path. For LLM02, describe anonymization and key handling with their limits; for LLM05, describe output parsing and sanitization without claiming strict schemas or safe semantic content. For LLM04, distinguish provider-owned training risks from retrieval-time poisoning.
3. **Operator-configured mitigations.** Tier policy, model-checksum verification (deferred — name it honestly), audit-log retention, RBAC scope. Each item cites the config knob.
4. **Residual risk.** What is not mitigated. The Citation Engine and Anonymization Layer are shipped M2 capabilities; document their residual risks under LLM09 and LLM02 respectively, with citations into PRD §3.3 / §4.7. Do not confuse a shipped implementation with comprehensive mitigation or measured efficacy.
5. **Operator responsibility.** Human-in-the-loop review (the legal-profession default), operator's incident response, tier-policy choices the operator owns.

Every cited file path and inclusive line range must resolve. Evidence links pin the reviewed source commit; corresponding `<!-- code-cite: path:start-end -->` markers are checked in the candidate checkout by `scripts/check-compliance-citations.py`. Every structural bullet needs a marker. The CI job runs checker regression tests and validates the mapping's markers and local links. Location checks cannot establish that a claim is true or that a control works; source changes still require human review.

## How we'd know it's done

- [ ] `docs/compliance/owasp-llm-top10.md` exists and covers all ten risks in the current OWASP LLM Top 10 published version (LLM01 through LLM10).
- [ ] Every risk row has the five fields populated (threat / structural / operator-configured / residual / operator responsibility).
- [ ] Every "structural mitigation" claim cites at least one specific file path + line range, and every cited path resolves at the commit the PR targets.
- [ ] The Citation Engine and Anonymization Layer's shipped implementations, configuration limits and residual risks are stated accurately under LLM09 and LLM02, with citations to [PRD §3.3](../../PRD.md#33-citation-engine-exact-quote) and [PRD §4.7](../../PRD.md#47-anonymization-layer-m2).
- [ ] A "How to read this document" section distinguishes structural mitigations (in source, verifiable) from operator-configured mitigations (defaults the operator tunes).
- [ ] A CI job verifies all cited file paths and inclusive line ranges resolve and each structural bullet has evidence. The checker and its regression tests run from `.github/workflows/ci.yml` and are part of this PR. The job does not certify substantive claims.
- [ ] The document is referenced from [`docs/compliance/README.md`](../../compliance/README.md) (status table updated) and from [PRD Appendix E](../../PRD.md#appendix-e--pre-empted-procurement-objections) (the prompt-injection objection links to LLM01).
- [ ] A non-maintainer security architect can read the document and produce concrete follow-up questions rather than "this is marketing copy."

## Where to start

1. Read the 2025 OWASP LLM Top 10 at https://genai.owasp.org/llm-top-10/ — use its risk IDs and titles consistently.
2. Read [`docs/security/threat-model.md`](../../security/threat-model.md) — the STRIDE coverage is the substrate for several risk rows.
3. Read [`docs/security/cryptography.md`](../../security/cryptography.md) and [`docs/security/encrypted-keys.md`](../../security/encrypted-keys.md) for the key-management surface (relevant to LLM02).
4. Read the gateway's skill-assembler at [`gateway/app/skills/assembler.py`](../../../gateway/app/skills/assembler.py) and ADR 0007 ([`docs/adr/0007-skill-prompt-assembly.md`](../../adr/0007-skill-prompt-assembly.md)) — the assembler's untrusted-content envelope (and its limits) is the foundation of the LLM01 story. There are **no** skill-prompt isolation conventions in the authoring guide; an earlier draft of this document said there were, and PRD Appendix E repeated it. Do not reintroduce that claim.
5. Read [`gateway/app/anonymization/middleware.py`](../../../gateway/app/anonymization/middleware.py), its wiring in [`gateway/app/api/inference.py`](../../../gateway/app/api/inference.py) and [`gateway.yaml.example`](../../../gateway.yaml.example). Identify the disabled default and each skip condition before describing LLM02 coverage.
6. Read [`api/app/citation/verification.py`](../../../api/app/citation/verification.py), [`api/app/citation/extraction.py`](../../../api/app/citation/extraction.py) and the citation endpoint in [`api/app/api/chats.py`](../../../api/app/api/chats.py). Distinguish exact/tolerant matching from semantic judging; ensemble judging replaces the single judge when configured and budget permits, rather than following it as another sequential stage.
7. Read [PRD §3.3 Citation Engine](../../PRD.md#33-citation-engine-exact-quote), [PRD §4.7 Anonymization Layer](../../PRD.md#47-anonymization-layer-m2), and [PRD Appendix E](../../PRD.md#appendix-e--pre-empted-procurement-objections) for the substantive content that backs several risk rows.
8. Read [`docs/security/audit-logging.md`](../../security/audit-logging.md) and the audit writer at [`api/app/audit.py`](../../../api/app/audit.py) — relevant to observability under LLM10 (Unbounded Consumption) and LLM06 (Excessive Agency).
9. Confirm the tier-floor refusal path in [`gateway/app/tier_floor.py`](../../../gateway/app/tier_floor.py) — relevant to LLM02 (Sensitive Information Disclosure); inspect [`api/app/autonomous/guard.py`](../../../api/app/autonomous/guard.py) and [`api/app/autonomous/cost.py`](../../../api/app/autonomous/cost.py) for LLM06/LLM10 limits and fail-open cost estimation.
10. Draft section-by-section, citing into source as you go. The first three sections (LLM01, LLM02, LLM06) will surface most of the conventions you reuse for the remaining seven.

## Scope cuts (what's out of scope for this PR)

- Mitigations not yet shipped get documented as gaps with a PRD/DE reference. Document limitations of shipped controls separately; historical milestone deferrals must not override current source evidence.
- The OWASP API Security Top 10 (a different mapping, also relevant) is its own document and is not in scope here.
- The OWASP ASVS L2 verification matrix is a separate, larger deliverable; it is not in scope.
- Per-skill prompt-injection detection rates (measured numbers) are deferred to the eval-harness work; this PR documents the architectural defenses, not the measured detection rates.
- Cross-references to MITRE ATLAS are valuable but not required for this PR; if the contributor wants to add an "Also see ATLAS technique X" sidebar per row, that is welcome but not part of acceptance.

## How this strengthens the project

The OWASP LLM Top 10 mapping is the artifact an operator's AI-security reviewer asks for first; it is also the artifact that distinguishes a serious AI-product security posture from marketing copy. Every claim in the document cites into source. The operator's reviewer reads the cited file and forms their own judgment. A closed-source vendor's equivalent document, if it exists, asserts the mitigation without showing the implementation; here, the implementation is the citation. That structural difference is the project's central trust commitment, expressed in the format the AI-security community has standardized on.

Beyond the procurement surface, the document is a forcing function for the engineering team: every gap honestly named in the document is a backlog item the team agrees to either close or document the residual-risk story for. Honest disclosure is internally aligning, not just externally trustworthy.

## References

- OWASP Top 10 for LLM Applications: https://owasp.org/www-project-top-10-for-large-language-model-applications/
- [PRD §1.8 Security Posture](../../PRD.md#18-security-posture)
- [PRD §3.3 Citation Engine](../../PRD.md#33-citation-engine-exact-quote)
- [PRD §4.7 Anonymization Layer (M2)](../../PRD.md#47-anonymization-layer-m2)
- [PRD Appendix E — Pre-Empted Procurement Objections](../../PRD.md#appendix-e--pre-empted-procurement-objections)
- [`docs/security/threat-model.md`](../../security/threat-model.md)
- [`docs/security/audit-logging.md`](../../security/audit-logging.md)
- [`docs/security/encrypted-keys.md`](../../security/encrypted-keys.md)
- [`docs/adr/0007-skill-prompt-assembly.md`](../../adr/0007-skill-prompt-assembly.md)
- [`gateway/app/skills/assembler.py`](../../../gateway/app/skills/assembler.py)
- [`gateway/app/tier_floor.py`](../../../gateway/app/tier_floor.py)
- Related: [Mini-PRD: NIST AI RMF 1.0 Profile](nist-ai-rmf-profile.md), [Mini-PRD: Procurement-Readiness Pack](procurement-readiness-pack.md)

## Definition of "merged"

The PR is merged when (a) the acceptance criteria checklist is fully checked off, (b) the maintainer has reviewed the substance against the cited code paths, and (c) the CI link-check job is green on the PR branch. Practicing-attorney attestation is not required for this engineering-discipline contribution — the standard PR review process applies.
