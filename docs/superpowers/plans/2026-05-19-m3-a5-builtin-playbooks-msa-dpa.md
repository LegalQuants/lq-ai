# M3-A5 Built-in Playbooks (MSA-SaaS, DPA-GDPR, MSA-Commercial-Purchase) — Prep Notes

> **Note on plan style:** Unlike M3-A4's mechanical task-by-task plan, M3-A5's work is ~80% legal-content drafting and ~20% engineering. The engineering pattern (seed migration + drift-detection test + integration tests per playbook) is already established and battle-tested by M3-A3. This doc is therefore a short outline — sources, position lists, approach — not a full subagent-driven execution plan.

**Goal:** Add three built-in playbooks to LQ.AI alongside the two NDA playbooks from M3-A3, so v0.3 ships with 5 built-ins covering the most common in-house contract types: NDA (mutual + unilateral), MSA-SaaS, DPA-GDPR, MSA-Commercial-Purchase.

**Branch:** `m3-a5-builtin-playbooks-msa-dpa` off `m3-development` (currently at `884d9a5`).

**Design decisions locked at session start (2026-05-19):**

| Q | Decision |
|---|---|
| Authorship | I draft. **No maintainer-team review gate** — per Kevin's 2026-05-19 reframe, the in-house attorney using LQ.AI is the validator, not the maintainer team. My drafts are explicit starting points / placeholders for that attorney to fork, customize, or replace; Kevin is not reviewing, attesting, or certifying any of the legal content. This is Decision F taken to its logical conclusion. |
| Attestation | Decision F applies. Disclaimer-in-description is the canonical posture; no formal practicing-attorney attestation. Per-playbook description text strengthened from M3-A3's framing to be more explicit about the starting-point posture (e.g., "this is a starting point an attorney should validate before relying on it" — not just "not legal advice"). Test `description_includes_not_legal_advice_disclaimer` from M3-A3 generalizes per playbook. M3-A5 entry in `docs/M3-IMPLEMENTATION-PLAN.md` updated to reflect this. |
| PR strategy | Single PR bundling all three YAMLs + migration 0033 + 3 integration tests. Matches M3-A3 (two playbooks one PR). |
| Sample contracts | Public-domain / permissive templates with attribution. Common Paper CC-BY-4.0 for SaaS/MSA; EU Commission SCCs (Implementing Decision 2021/914) public-domain for DPA. |

---

## Position lists (per M3-IMPLEMENTATION-PLAN.md §M3-A5 scope)

### MSA-SaaS — 11 positions

| # | Position | Severity (default) |
|---|---|---|
| 0 | Service Level Agreement (uptime + remedies) | high |
| 1 | Security Commitments (controls + certifications) | critical |
| 2 | Data Handling & Privacy (subject to companion DPA where applicable) | critical |
| 3 | Intellectual Property (ownership of customer data, derivatives, feedback) | high |
| 4 | Limitation of Liability (cap, exclusions, supercap carveouts) | critical |
| 5 | Indemnification (IP, breach of confidentiality, mutual conduct) | high |
| 6 | Termination (for cause, for convenience, transition assistance) | high |
| 7 | Audit Rights (frequency, scope, cost allocation) | medium |
| 8 | Payment Terms (currency, late fees, dispute, true-up) | medium |
| 9 | Governing Law and Venue | medium |
| 10 | Change Management (price increase, feature deprecation, notice) | medium |

### DPA-GDPR — 8 positions

| # | Position | Severity (default) |
|---|---|---|
| 0 | Processor Obligations (GDPR Art. 28(3)) | critical |
| 1 | Security of Processing (GDPR Art. 32) | critical |
| 2 | Personal Data Breach Notification (GDPR Art. 33) | critical |
| 3 | International Transfers (Chapter V — SCCs, TIA, supplementary measures) | critical |
| 4 | Sub-processor Engagement (Art. 28(2), flow-through obligations) | high |
| 5 | Audit Rights (Art. 28(3)(h), supervisory authority access) | high |
| 6 | Deletion or Return of Personal Data (Art. 28(3)(g)) | high |
| 7 | DSAR Cooperation (Art. 28(3)(e), data subject rights assistance) | medium |

### MSA-Commercial-Purchase — 10 positions

| # | Position | Severity (default) |
|---|---|---|
| 0 | Acceptance (criteria, period, deemed acceptance) | high |
| 1 | Warranties (services, deliverables, non-infringement) | high |
| 2 | Indemnification (IP, third-party claims, mutual conduct) | high |
| 3 | Limitation of Liability (cap, exclusions, mutual structure) | critical |
| 4 | Intellectual Property (work product, background IP, license-back) | high |
| 5 | Change Orders (process, pricing, dispute resolution) | medium |
| 6 | Payment Terms (currency, net days, late fees, withholding) | medium |
| 7 | Termination for Cause | high |
| 8 | Termination for Convenience (notice, transition, refund) | medium |
| 9 | Governing Law and Venue | medium |

**Total: 29 positions across 3 playbooks.** Each position has the M3-A3 structure: `issue`, `description`, `standard_language`, `fallback_tiers[]` (≥2 tiers per position with `rank`, `description`, `language`), `redline_strategy`, `severity_if_missing`, `detection_keywords[]`, `detection_examples[]`, `position_order`.

---

## Source materials (cite in fixtures README + playbook header comments)

**MSA-SaaS baseline:**
- [Common Paper Cloud Service Agreement](https://commonpaper.com/standards/cloud-service-agreement/) — CC-BY-4.0; lawyer-drafted; broadly adopted by mid-market SaaS vendors. Primary baseline for standard_language tone.
- [Bonterms Software License Agreement](https://bonterms.com/forms/software-license-agreement/) — CC-BY-4.0; secondary cross-reference for liability + IP positions.

**DPA-GDPR baseline:**
- [EU Commission Standard Contractual Clauses 2021/914 — Module Two (controller-to-processor)](https://commission.europa.eu/system/files/2021-06/1_en_annexe_acte_autonome_cp_part1_v5_0.pdf) — public-domain; the canonical reference for cross-border processing.
- [EDPB Guidelines 07/2020 on the concepts of controller and processor under the GDPR](https://www.edpb.europa.eu/system/files/2021-07/eppb_guidelines_202007_controllerprocessor_final_en.pdf) — official EU guidance; informs Art. 28 obligation framing.
- [EDPB Recommendations 01/2020 on measures that supplement transfer tools](https://edpb.europa.eu/our-work-tools/our-documents/recommendations/recommendations-012020-measures-supplement-transfer-tools_en) — for the Transfer Impact Assessment (TIA) framing.

**MSA-Commercial-Purchase baseline:**
- [Common Paper Master Subscription Agreement (vendor-side)](https://commonpaper.com/standards/master-subscription-agreement/) — CC-BY-4.0; mirror it from the customer-purchase perspective.
- Standard mid-market commercial-purchase positions from publicly available samples (no single canonical source; synthesize from multiple).

---

## Engineering scaffold (post-content)

Same pattern as M3-A3 (commit `eb59f5c`):

```
api/alembic/versions/0033_seed_builtin_playbooks_msa_dpa.py
api/tests/test_builtin_msa_dpa_playbooks.py   # drift detection per playbook
api/tests/test_playbook_msa_saas_execution.py # integration test
api/tests/test_playbook_dpa_gdpr_execution.py # integration test
api/tests/test_playbook_msa_commercial_execution.py # integration test
api/tests/fixtures/m3-a5/
  README.md                   # source attribution
  sample-msa-saas.md          # public-domain sample contract
  sample-dpa-gdpr.md
  sample-msa-commercial.md
```

Migration 0033 reads the YAML files at upgrade time (mirrors 0032's `pathlib.Path(__file__).parents[4] / "skills" / "playbooks"` walk). Drift-detection tests:
- For each playbook: `test_<slug>_description_includes_not_legal_advice_disclaimer` (Decision F enforcement)
- For each playbook: `test_<slug>_migration_seeded_positions_match_yaml` (single-source-of-truth invariant)

Integration tests follow the (yet-to-be-written) pattern; the executor's actual end-to-end behavior is already covered by `test_executor.py`. These per-playbook integration tests should run the executor against the fixture and assert that ≥1 position resolves to each of the four verdicts (`matches_standard`, `matches_fallback`, `deviates`, `missing`) so the fixture exercises all code paths.

---

## Drafting protocol

Per Kevin's reframe (2026-05-19): no maintainer-team review cycle. I draft each playbook end-to-end and commit it. The disclaimer-in-description carries the "this is a starting point an attorney needs to validate" framing forward to every operator who installs LQ.AI. The integration tests (Task 7) verify the executor runs against a sample contract and produces sensible per-position verdicts — they don't validate the legal substance of the positions themselves.

**Order:** MSA-SaaS first (most standardized → biggest learning yield for the YAML structure). Then DPA-GDPR (regulatory-specific, careful Article alignment). Then MSA-Commercial-Purchase (mirror of MSA-SaaS from the buy side).

Each playbook gets its own commit on the branch. After all three YAMLs land, engineering scaffold (migration + drift tests + fixtures + integration tests) lands in additional commits. Then PR opens.

**Implication for the description boilerplate:** the M3-A3 NDA playbooks' description text was strong but implicit about the "starting point" posture ("operator's responsibility to apply professional judgment"). M3-A5 playbooks make this explicit — e.g., "These positions are starting points that an attorney should review before relying on them. We have not validated them; you must." Worth retro-updating the M3-A3 NDA descriptions to match — filed as a follow-on inside this PR if simple, otherwise a separate small docs PR.

---

## Out of scope (defer for M3-A6 or later)

- Per-playbook fallback ladder tuning based on real-world usage. The M3-A5 ladders are starter positions; M3-A6's Easy Playbook wizard generates user-specific ladders from operator's prior agreements.
- Multi-jurisdiction variants (US + EU + UK governing law). All M3-A5 playbooks default to a US-Delaware or neutral-US framing; international operators fork.
- Industry-specific overlays (healthcare HIPAA, financial services GLBA, government FedRAMP). Filed as candidate community contributions.
- Specific to DPA-GDPR: post-Schrems-II Transfer Impact Assessment (TIA) template embedded in the playbook. The DPA position 3 references TIA but doesn't ship a full template — that's a separate deliverable.

---

*End of prep notes. Drafting begins with MSA-SaaS.*
