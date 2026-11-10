# Contribution coverage map

This is the shared claim ledger required by [ADR 0024 D5](../adr/0024-jurisdiction-and-practice-area-expansion.md).
Check it before routing a jurisdiction or practice-area contribution, then record or update the claim
in the same routing sweep. It covers both `LegalQuants/lq-ai` and `LegalQuants/lq-skills`.

## Reading and maintaining the map

- **Merged** means the linked PR merged. **Present on main (baseline/import)** means the artifact
  exists in the inspected default-branch snapshot, but no tracking issue was identified for this
  back-fill. The linked artifact supports its presence; do not invent a claim issue.
- **Open proposal** and **Open PR** reserve visibility for proposed work; they do not mean the
  contribution is accepted, merged, attested, or available to operators.
- Jurisdiction cells use free text from the skill manifest or repository README, with explicit
  scope detail where the manifest supplies it. They record declared scope, not verified legal
  completeness or the author's bar admission. For document utilities, a declared jurisdiction
  does not by itself establish jurisdiction-specific legal functionality.
- Each existing top-level skill has its own row. A skill present in both repos appears twice so
  routing can find both homes. Identical folder names do not establish identical content:
  the two `nda-review` skills, for example, have different declared scopes.
  CoQuill's internal sub-skills are included through its orchestrator, not separate claims.
  The five [built-in playbooks](https://github.com/LegalQuants/lq-ai/tree/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/playbooks) cover NDA, MSA and GDPR-DPA work already represented
  below; they are not counted as extra skills.
- Before routing, compare both jurisdiction and work product with existing and open rows. Link
  related work and ask the maintainer to resolve overlaps; a shared coverage cell is not an
  automatic duplicate or rejection.
- In the same sweep, add the proposal's issue/PR link and observed status, or update an existing
  row. Keep redirects and superseded claims linked to their successor rather than silently
  erasing the history. Update statuses after merge or closure.
- This ledger implements claim recording only. It does not introduce a jurisdiction vocabulary,
  substantive trust tier, attestation rule, new routing decision, or automated enforcement.

## Existing coverage

Back-filled on 2026-10-05 using the
[lq-ai snapshot](https://github.com/LegalQuants/lq-ai/tree/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6) and
[lq-skills snapshot](https://github.com/LegalQuants/lq-skills/tree/884cf402949981ca2a4afb8ff88f19337005eecf),
their manifests and README, and GitHub PR merge records. Repository presence is a historical
coverage record, not a claim that every listed skill loads or performs correctly.

### lq-ai — authority sources

| Jurisdiction | Practice area | Claim issue link | Status |
|---|---|---|---|
| US | Legal research/litigation — CourtListener authority source | [lq-ai#159](https://github.com/LegalQuants/lq-ai/pull/159) | Merged |
| US federal | Legal research — GovInfo federal authority source | [lq-ai#245](https://github.com/LegalQuants/lq-ai/pull/245) | Merged |
| US | Corporate/securities — SEC EDGAR filings authority source | [lq-ai#254](https://github.com/LegalQuants/lq-ai/pull/254) | Merged |
| EU | Legal research — EUR-Lex authority source (get-by-CELEX) | [lq-ai#257](https://github.com/LegalQuants/lq-ai/pull/257) | Merged |

### lq-ai — first-party skills

| Jurisdiction | Practice area | Claim issue link | Status |
|---|---|---|---|
| agnostic | Regulatory/compliance — client-alert action extraction — [`lq-ai/action-items-from-client-alert`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/action-items-from-client-alert/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| us | Legal research/litigation — CourtListener case-law research — [`lq-ai/case-law-research`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/case-law-research/SKILL.md) | [lq-ai#192](https://github.com/LegalQuants/lq-ai/pull/192) | Merged |
| agnostic | Cross-practice — plain-language legal communications — [`lq-ai/comms-improver`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/comms-improver/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| agnostic | Commercial contracts — contract Q&A — [`lq-ai/contract-qa`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/contract-qa/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| agnostic | Commercial contracts — comparative contract tables — [`lq-ai/contract-snapshot`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/contract-snapshot/SKILL.md) | [lq-ai#62](https://github.com/LegalQuants/lq-ai/pull/62) | Merged |
| Regime-dependent (EU/UK GDPR; US state privacy; US HIPAA; general commercial) | Privacy — DPA/BAA checklist review — [`lq-ai/dpa-checklist-review`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/dpa-checklist-review/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| agnostic | Cross-practice — prompt preparation — [`lq-ai/enhance-prompt`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/enhance-prompt/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| US-default | Commercial contracts — purchase/supply MSA review — [`lq-ai/msa-review-commercial-purchase`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/msa-review-commercial-purchase/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| US-default | Commercial contracts — SaaS MSA review — [`lq-ai/msa-review-saas`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/msa-review-saas/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| agnostic | Commercial contracts — comparative MSA tables — [`lq-ai/msa-snapshot`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/msa-snapshot/SKILL.md) | [lq-ai#62](https://github.com/LegalQuants/lq-ai/pull/62) | Merged |
| US-default | Commercial contracts — NDA review — [`lq-ai/nda-review`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/nda-review/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| agnostic | Commercial contracts — comparative NDA tables — [`lq-ai/nda-snapshot`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/nda-snapshot/SKILL.md) | [lq-ai#62](https://github.com/LegalQuants/lq-ai/pull/62) | Merged |
| global | Cross-practice — experimental contract-question orchestration — [`lq-ai/orchestration-chat-demo`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/orchestration-chat-demo/SKILL.md) | [lq-ai#631](https://github.com/LegalQuants/lq-ai/pull/631) | Merged |
| regime-aware | Commercial contracts — playbook-position extraction — [`lq-ai/playbook-easy-extract`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/playbook-easy-extract/SKILL.md) | [lq-ai#57](https://github.com/LegalQuants/lq-ai/pull/57) | Merged |
| Not declared (technical demonstration) | Cross-practice — saved-notes capability demonstration — [`lq-ai/saved-notes-demo`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/saved-notes-demo/SKILL.md) | [lq-ai#596](https://github.com/LegalQuants/lq-ai/pull/596) | Merged |
| Not declared (meta utility) | Cross-practice — skill authoring — [`lq-ai/skill-creator`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/skill-creator/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| Regime-aware (user-specified) | Privacy — vendor-policy triage — [`lq-ai/vendor-privacy-policy-first-pass`](https://github.com/LegalQuants/lq-ai/blob/b8c5597990c21f0c32473ba6f8f04c15d8e5cac6/skills/vendor-privacy-policy-first-pass/SKILL.md) | No tracking issue located | Present on main (baseline/import) |

### lq-skills — community skills

| Jurisdiction | Practice area | Claim issue link | Status |
|---|---|---|---|
| agnostic | Regulatory/compliance — client-alert action extraction — [`lq-skills/action-items-from-client-alert`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/action-items-from-client-alert/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| Agnostic | Cross-practice — quality control of AI deliverables — [`lq-skills/adversarial-qc`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/adversarial-qc/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| eu | AI governance — EU AI Act triage — [`lq-skills/ai-act-quick`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/ai-act-quick/SKILL.md) | [lq-skills#8](https://github.com/LegalQuants/lq-skills/pull/8) | Merged |
| SG | Legal research — statutory citation checking — [`lq-skills/bart-statutory-reference-checker`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/bart-statutory-reference-checker/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| Agnostic | Litigation — sourced chronologies — [`lq-skills/building-chronologies`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/building-chronologies/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| US-CA | Property tax — California BOE research — [`lq-skills/california-property-tax`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/california-property-tax/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| Agnostic | Litigation — adversarial case-file analysis (proof of concept) — [`lq-skills/case-file-analyzer`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/case-file-analyzer/SKILL.md) | [lq-skills#2](https://github.com/LegalQuants/lq-skills/pull/2) | Merged |
| Agnostic | Competition law — compliance-programme classification — [`lq-skills/classify-ccp`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/classify-ccp/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| Agnostic | Cross-practice — document-review feedback — [`lq-skills/collating-reviewer-feedback`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/collating-reviewer-feedback/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| agnostic | Cross-practice — plain-language legal communications — [`lq-skills/comms-improver`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/comms-improver/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| agnostic | Commercial contracts — contract Q&A — [`lq-skills/contract-qa`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/contract-qa/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| Agnostic | Cross-practice — document assembly — [`lq-skills/coquill`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/coquill/SKILL.md) | [lq-skills#4](https://github.com/LegalQuants/lq-skills/pull/4) | Merged |
| UK | Corporate — Companies House investigation — [`lq-skills/corporate-registry-investigation`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/corporate-registry-investigation/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| US | Customs/trade — HTS and ruling research — [`lq-skills/customs-trade-law`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/customs-trade-law/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| eu | Privacy — GDPR Art. 28 DPA review, drafting and redlining — [`lq-skills/dpa-art28`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/dpa-art28/SKILL.md) | [lq-skills#6](https://github.com/LegalQuants/lq-skills/pull/6) | Merged |
| Regime-dependent (EU/UK GDPR; US state privacy; US HIPAA; general commercial) | Privacy — DPA/BAA checklist review — [`lq-skills/dpa-checklist-review`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/dpa-checklist-review/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| agnostic | Cross-practice — prompt preparation — [`lq-skills/enhance-prompt`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/enhance-prompt/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| Multi-jurisdiction | Legal research — foreign/comparative law — [`lq-skills/foreign-law-research`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/foreign-law-research/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| Agnostic | Litigation — claim economics and funding — [`lq-skills/legal-claim-economics`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/legal-claim-economics/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| Agnostic | Cross-practice — legal translation — [`lq-skills/legal-translation`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/legal-translation/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| US | IP/software — open-source licensing — [`lq-skills/license-comply`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/license-comply/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| AG | Legal operations — workspace privacy boundaries — [`lq-skills/local-first-legal-workspace`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/local-first-legal-workspace/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| MULTI | Corporate governance — board-document review — [`lq-skills/lq-board-document-review`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/lq-board-document-review/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| MULTI | Corporate governance — playbook benchmarking — [`lq-skills/lq-governance-playbook-benchmark`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/lq-governance-playbook-benchmark/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| US-default | Commercial contracts — purchase/supply MSA review — [`lq-skills/msa-review-commercial-purchase`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/msa-review-commercial-purchase/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| US-default | Commercial contracts — SaaS MSA review — [`lq-skills/msa-review-saas`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/msa-review-saas/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| AG (jurisdiction-agnostic) | Commercial contracts — NDA review — [`lq-skills/nda-review`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/nda-review/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| eu | Cybersecurity — NIS2 scope, gaps and roadmap — [`lq-skills/nis2-navigator`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/nis2-navigator/SKILL.md) | [lq-skills#5](https://github.com/LegalQuants/lq-skills/pull/5) | Merged |
| US | AI governance — NIST AI RMF — [`lq-skills/nist-ai-rmf`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/nist-ai-rmf/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| SG | Cross-practice — Word tracked-changes utility — [`lq-skills/office-word-diff`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/office-word-diff/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| eu | Privacy — GDPR notices — [`lq-skills/privacy-notice-eu`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/privacy-notice-eu/SKILL.md) | [lq-skills#7](https://github.com/LegalQuants/lq-skills/pull/7) | Merged |
| Agnostic | Legal research/litigation — proposition-to-source support — [`lq-skills/proposition-checking`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/proposition-checking/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| MULTI | International arbitration — document production — [`lq-skills/redfern-schedule`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/redfern-schedule/SKILL.md) | [lq-skills#10](https://github.com/LegalQuants/lq-skills/pull/10) | Merged |
| SG | Cross-practice — DOCX redlining utility — [`lq-skills/redlines`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/redlines/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| SG | Legal research/litigation — Singapore court citations — [`lq-skills/sgcite`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/sgcite/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| Meta | Cross-practice — skill authoring — [`lq-skills/skill-creator`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/skill-creator/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| US (federal, state, local) | Legal research — statutory interpretation — [`lq-skills/statutory-analysis`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/statutory-analysis/SKILL.md) | [lq-skills#3](https://github.com/LegalQuants/lq-skills/pull/3) | Merged |
| SG | Cross-practice — DOCX multi-agent redlining utility — [`lq-skills/superdoc-redlines`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/superdoc-redlines/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| SG | Cross-practice — text-source attribution — [`lq-skills/text-provenance`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/text-provenance/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| UK | Legal research/litigation — UK citation verification — [`lq-skills/uk-citation-verification`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/uk-citation-verification/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| England and Wales | Litigation — Court of Appeal drafting signals — [`lq-skills/uk-court-of-appeal-judicial-preference-check`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/uk-court-of-appeal-judicial-preference-check/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| England and Wales | Litigation — disclosure-list review — [`lq-skills/uk-disclosure-list-review`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/uk-disclosure-list-review/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| England and Wales | Litigation — Particulars of Claim review — [`lq-skills/uk-particulars-of-claim-review`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/uk-particulars-of-claim-review/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| England and Wales | Litigation — witness-statement review — [`lq-skills/uk-witness-statement-review`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/uk-witness-statement-review/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| US | Privacy — US state consumer-privacy analysis — [`lq-skills/us-state-privacy-navigator`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/us-state-privacy-navigator/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| Regime-aware (user-specified) | Privacy — vendor-policy triage — [`lq-skills/vendor-privacy-policy-first-pass`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/vendor-privacy-policy-first-pass/SKILL.md) | No tracking issue located | Present on main (baseline/import) |
| UK | Commercial contracts — batch playbook redlining — [`lq-skills/vibe-legal-batch-redliner`](https://github.com/LegalQuants/lq-skills/blob/884cf402949981ca2a4afb8ff88f19337005eecf/skills/vibe-legal-batch-redliner/SKILL.md) | No tracking issue located | Present on main (baseline/import) |

## Open proposals and amendments

The [direction paper's live docket](../proposals/jurisdiction-and-practice-area-expansion.md#the-live-docket-evidence-collected-2026-07-20)
is the starting point. Statuses below were refreshed on 2026-10-05, with the additional open
community PRs included to make overlapping work visible.

For #174, the later maintainer response recommends a contributor-owned repository, while
ADR 0024 describes the general S3 home as an org-level repository. The row records that
proposal-specific recommendation; it does not amend the ADR. Obtain a maintainer placement
decision for new corpus proposals, using the ADR's second-maintainer review if routing is disputed.

| Jurisdiction | Practice area | Claim issue link | Status |
|---|---|---|---|
| EU / Spain | Privacy — GDPR statutory graph, LOPDGDD and AEPD corpus | [lq-ai#174](https://github.com/LegalQuants/lq-ai/issues/174) | Open proposal; [maintainer recommends a contributor-owned corpus repo](https://github.com/LegalQuants/lq-ai/issues/174#issuecomment-5235556612), with gateway-brokered MCP integration; proposer ownership commitment pending |
| EU | IP/trademarks — EUIPO register authority source | [lq-ai#271](https://github.com/LegalQuants/lq-ai/issues/271) | [Routed S1 by maintainer](https://github.com/LegalQuants/lq-ai/issues/271#issuecomment-5238729646); awaiting OAuth2 design (DE-386) and register-record quotation decision |
| US (proposer identifies NV/CA) | Litigation — research and drafting carve-in | [lq-ai#287](https://github.com/LegalQuants/lq-ai/issues/287) | [Routed S4](https://github.com/LegalQuants/lq-ai/issues/287#issuecomment-5235242060); mini-PRD and committee amendment required; Phase-1 skill home remains open |
| Jurisdiction-agnostic | Legal research — scoped Knowledge Sources catalog | [lq-ai#309](https://github.com/LegalQuants/lq-ai/issues/309) | Open proposal; [engineering-only framing and placement questioned](https://github.com/LegalQuants/lq-ai/issues/309#issuecomment-5015788564); [proposer agrees catalog needs jurisdiction-expert review](https://github.com/LegalQuants/lq-ai/issues/309#issuecomment-5034411558) |
| EU | IP/trademarks — EUIPO clearance | [lq-skills#9](https://github.com/LegalQuants/lq-skills/pull/9) | Open PR; not merged |
| EU | IP/trademarks — EUIPO goods/services classification | [lq-skills#16](https://github.com/LegalQuants/lq-skills/pull/16) | Open PR; not merged |
| EU | IP/trademarks — EUIPO homoglyph screening | [lq-skills#17](https://github.com/LegalQuants/lq-skills/pull/17) | Open PR; not merged |
| EU-ES (proposer-declared) | Privacy — GDPR Art. 28 specialist DPA review | [lq-skills#18](https://github.com/LegalQuants/lq-skills/pull/18) | Open PR; overlaps merged [lq-skills#6](https://github.com/LegalQuants/lq-skills/pull/6); relationship needs maintainer review |
| EU | AI governance — AI Act Article 50 transparency | [lq-skills#19](https://github.com/LegalQuants/lq-skills/pull/19) | Open PR; not merged; related to merged [lq-skills#8](https://github.com/LegalQuants/lq-skills/pull/8) |
| US | Regulatory/enforcement — enforcement-action analysis | [lq-skills#20](https://github.com/LegalQuants/lq-skills/pull/20) | Open PR; not merged |
| Jurisdiction not established in PR summary (contract-specific) | Commercial contracts — AWS SLA service-credit checks | [lq-skills#21](https://github.com/LegalQuants/lq-skills/pull/21) | Open PR; not merged |
| US | Export controls — EAR crypto scan | [lq-skills#22](https://github.com/LegalQuants/lq-skills/pull/22) | Open PR; not merged |
| Jurisdiction-agnostic (README) | Competition law — classify-ccp metadata fix | [lq-skills#23](https://github.com/LegalQuants/lq-skills/pull/23) | Open amendment of existing coverage; not a new domain |
| MULTI | International arbitration — Redfern benchmark documentation | [lq-skills#24](https://github.com/LegalQuants/lq-skills/pull/24) | Open documentation amendment; supersedes closed unmerged #13 |
| MULTI | International arbitration — Redfern local-model operation | [lq-skills#25](https://github.com/LegalQuants/lq-skills/pull/25) | Open amendment of merged [lq-skills#10](https://github.com/LegalQuants/lq-skills/pull/10) |

## Redirected and superseded claims

| Jurisdiction | Practice area | Claim issue link | Status |
|---|---|---|---|
| MULTI | International arbitration — Redfern benchmark documentation | [lq-skills#13](https://github.com/LegalQuants/lq-skills/pull/13) | Closed unmerged; superseded by [lq-skills#24](https://github.com/LegalQuants/lq-skills/pull/24) |
| MULTI | International arbitration — Redfern original product-repo submission | [lq-ai#190](https://github.com/LegalQuants/lq-ai/pull/190) | Closed unmerged / redirected; merged as [lq-skills#10](https://github.com/LegalQuants/lq-skills/pull/10) |
