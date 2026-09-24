# LQ.AI — Acceptance Testing Framework

This document establishes the framework for acceptance testing skills before public release. It is the meta-document that the per-skill test plans (in each `skills/<skill-name>/test-plan.md`) follow. The audience is anyone running acceptance testing on the M1 starter skills, anyone authoring new skills who needs to draft a test plan, and reviewers verifying that skill behavior is calibrated correctly before merge.

The framework operationalizes [PRD §9 DE-051](PRD.md#de-051--acceptance-testing-for-the-m1-skill-set-against-real-documents) (acceptance testing for the M1 skill set against real documents) and [DE-061](PRD.md#de-061--contract-qa-acceptance-testing) / [DE-072](PRD.md#de-072--msa-review-acceptance-testing-against-real-document-corpus) (skill-specific acceptance testing entries).

## In short

- Acceptance testing checks two different things: whether a skill's output has the right *shape* — sections, severity tags, and citations a script or a careful reader can check — and whether it's *calibrated* against real documents, which takes a practicing lawyer's judgment.
- A test plan by itself is not a passing result. Passing needs the actual output the skill produced on real test documents, plus a reviewing attorney's evaluation against the plan's stated criteria — not just the plan file existing.
- Test documents come from the operator's own anonymized practice, not the repository — keep confidential material out of anything you commit or share.
- Keep a record of every run: which skill version was tested, which documents were used (described, not reproduced — see Reproduction under Issues filing convention), the actual output, and the reviewing attorney's assessment.

---

## Philosophy

Acceptance testing for legal-AI skills is not regression testing. It is calibration verification. Two questions matter most:

1. **Does the skill produce the *right shape* of output?** The structure, the section headings, the severity tags, the citations, the refusal modes, the conservative-posture markers — does the output match what the skill specification promised?
2. **Is the skill *calibrated* against real documents?** A skill that produces 50 critical findings on every routine NDA is uncalibrated regardless of how clean the output structure is. A skill that produces zero findings on a known-bad contract is uncalibrated in the other direction. Calibration means the skill's severity distribution and finding density match what a practicing lawyer would identify on the same input.

These two questions are answered differently. Output shape is verifiable mechanically — a script can check that the report has the expected sections, that severity tags follow the rubric, that citations point at the source. Calibration requires human judgment — a practicing lawyer reviews the skill's findings against their own analysis and confirms they're in the same ballpark.

Both checks happen for every skill before public release. The per-skill test plans document both: the structural expectations a tester (or CI) can verify, and the calibration expectations a reviewing attorney evaluates.

---

## Test corpus requirements (operator-provided)

The acceptance testing framework provides the test plans, expected behaviors, and pass criteria. **The test documents themselves come from the operator's practice** — anonymized real contracts, real client alerts, real privacy policies. The framework cannot ship synthetic test documents because synthetic documents do not surface the edge cases real practice produces.

Each per-skill test plan specifies what the test corpus should include for that skill (e.g., "5–8 NDAs covering mutual and unilateral variants across at least three counterparty types"). The operator's job is to source documents matching those requirements and anonymize them appropriately.

### Anonymization conventions

For acceptance testing purposes, anonymization should:

- **Replace party names** with neutral placeholders (`Counterparty A`, `Vendor B`, `Customer Org`).
- **Replace specific identifiers** (account numbers, employee IDs, addresses, phone numbers) with structurally similar placeholders (`ACCT-XXXX-1234`, `123 Anytown Way`).
- **Preserve substantive content** — clause language, severity calibrations, and structural patterns are exactly what the skill is being tested against.
- **Preserve dates and amounts** where they're operative, replacing only when the specific value would identify the matter (general dates and amounts are usually fine to preserve; specific large transaction amounts that could identify the deal warrant rounding).
- **Not alter the legal substance** in a way that changes the analysis. Anonymization should be transparent to the skill's findings.

The operator is responsible for confirming anonymization is sufficient before adding documents to the test corpus. Documents that cannot be sufficiently anonymized while preserving substantive content should not be used; source different documents instead.

### Storage of the test corpus

Test documents are not committed to the repository. They live in the operator's local environment in a path documented in each skill's test plan (typically `test-corpus/<skill-name>/`). Test results — the output of running the skill against each test document and the reviewer's evaluation — *are* committed (in anonymized form, so the assessment is auditable without exposing the underlying documents).

For skills shipped with the project (the M1 starter skills), maintainers will run acceptance testing against their own test corpus before each release; community contributors are expected to run the test plan against their own test corpus when contributing skill updates.

---

## Test plan template

Every per-skill test plan follows this structure, intended to live at `skills/_test-plan-template.md` as the starting point for any new skill's test plan. **That file is not present in the repository as of the checked commit** — use an existing plan such as [`skills/nda-review/test-plan.md`](../skills/nda-review/test-plan.md) as the template instead; its structure (summary, corpus requirements, scenarios, pass criteria) is the one every shipped test plan below follows.

```markdown
# Acceptance Test Plan — <skill name> v<version>

## Skill summary

[1–2 sentences describing what this skill does. Pulled from SKILL.md description.]

## Test corpus requirements

[Description of what the test corpus must cover. Specific to each skill.]

- N to M documents covering [variations]
- Including at least one [edge case A]
- Including at least one [edge case B]
- ...

## Test scenarios

[For each scenario the skill should be tested against, a structured entry.
Scenarios cover the skill's variations: perspectives, regimes, edge cases.]

### Scenario 1: <descriptive name>

**Inputs:** [What inputs the scenario provides — document type, optional inputs.]

**Expected output structure:**
- [Section X present]
- [Section Y present]
- [Output format conforms to skill's `output_format`]
- [Citations format correctly]

**Expected calibration:**
- [Severity distribution range, e.g., "1-3 critical, 3-7 material, 5-15 minor"]
- [Findings categories that should appear]
- [Findings categories that should not appear]

**Edge cases to verify:**
- [Specific behavior when X]
- [Specific behavior when Y]

**Pass criteria:**
- Structural pass: [criteria a tester verifies mechanically]
- Calibration pass: [criteria a reviewing attorney evaluates]

### Scenario 2: ...

## Refusal scenarios

[Cases the skill should explicitly refuse or scope-out, with the expected
refusal language and behavior.]

## Cross-cutting verification

[Pass criteria that apply across all scenarios — citation hygiene, conservative
posture conventions, "what this skill does not do" enumeration.]

## Pass/fail decision

[Aggregate pass criteria for the skill as a whole.]
```

### Why this template structure

- **Test corpus requirements** front-load the document-sourcing work. Before running tests, the operator knows what they need to gather.
- **Scenarios** are the unit of testing. Each scenario combines an input pattern with expected outputs and pass criteria. A skill with three perspectives × two regimes generates six scenarios (or fewer if some combinations don't apply).
- **Expected calibration** uses *ranges*, not exact counts. A test that says "must produce exactly 5 critical findings" is brittle; a test that says "1–3 critical findings on this scenario, with at least the [specified categories] surfaced" is robust to the natural variation in LLM output while still flagging miscalibration.
- **Edge cases** are the long tail. Most skill issues surface in edge cases (a document missing an expected section, a clause using non-standard terminology, a regime selection that triggers regime-specific logic). Per-scenario edge cases force the test plan to confront these.
- **Refusal scenarios** are the conservative-posture check. Skills should explicitly refuse out-of-scope inputs, not silently produce wrong output.
- **Cross-cutting verification** captures conventions that apply everywhere: no invented citations, no enforceability opinions, "what this skill does not do" enumeration present.

---

## Expected-behavior format

Within scenarios, expected behavior is documented at three levels:

### Level 1 — Structural (mechanically verifiable)

What a script or tester can verify by inspection:

- Output `output_format` matches frontmatter (markdown report, JSON issues_list, structured table, etc.).
- Required sections are present (e.g., NDA Review report has "Bottom line", "Findings", "What this skill does not do").
- Severity tags follow the rubric (`**[Critical]**`, `**[Material]**`, `**[Minor]**`).
- Citations point at the source document (citation IDs resolve; verbatim quotes match source).
- The skill's frontmatter inputs are correctly applied (e.g., `perspective: recipient` produces recipient-perspective output, not discloser-perspective).

These checks pass or fail definitively. They form the floor of acceptance — if structural checks fail, calibration is moot.

### Level 2 — Calibration (reviewing-attorney judgment)

What a practicing attorney verifies against their own analysis of the same input:

- Severity distribution matches what the attorney would assign (within reasonable range — exact count is unrealistic).
- Findings categories surfaced are the right ones (a missing-IP-indemnity finding should appear when the document is missing IP indemnity).
- Findings calibration (a routine clause is not flagged critical; a genuinely problematic clause is not flagged minor).
- Recommended language is operationally usable (the attorney could plausibly use the recommended language with minor edits, not start from scratch).
- Conservative posture is maintained (no enforceability opinions, no invented citations, no overclaim outside the skill's documented scope).

These checks require human judgment. Reviewers document their assessment in the test results: "Calibration pass" / "Calibration concern: <description>" / "Calibration fail."

### Level 3 — Conservative posture (substantive correctness check)

The bar a skill clears to be ready for production use. The reviewing attorney confirms:

- No findings assert legal substance the skill cannot back up.
- All cited authorities are real and accurately characterized.
- Enforceability opinions are deferred (not "this is unenforceable" but "this is unusual" or "this raises an enforceability question").
- The "what this skill does not do" enumeration is honest and complete — the skill explicitly tells users when to escalate.
- Outputs that would mislead a non-expert user have been caught and corrected.

A skill cannot ship if conservative-posture concerns remain unresolved. This is the final substantive gate.

---

## Pass / fail criteria

A skill passes acceptance testing when:

1. **All scenarios pass structural checks.** Every output produced by the skill against every test scenario has the expected structure, format, citations, and severity tags.
2. **All scenarios pass calibration evaluation.** The reviewing attorney confirms the skill's findings density, severity distribution, and recommended-language quality match what the attorney would produce on the same inputs.
3. **All refusal scenarios trigger the documented refusal behavior.** The skill explicitly declines out-of-scope inputs rather than producing wrong output.
4. **Cross-cutting verification passes.** Conservative-posture conventions are followed; citations are clean; enumerated "does not do" items are present; output is in the correct `output_format`.

A skill *fails* acceptance testing when any of the above fails. Failure modes are categorized:

- **Structural fail** — output shape does not match the specification. Usually a SKILL.md authoring issue (missing section instruction, ambiguous output format directive). Fix is in the SKILL.md and re-run.
- **Calibration fail** — output shape is correct but findings are miscalibrated (too aggressive, too permissive, wrong category). Fix is typically in the severity rubric (`reference/severity_rubric.md`) or the perspective-lens reference (`reference/perspective_lens.md`). Re-run after refining.
- **Conservative-posture fail** — output asserts substance it cannot back up. Highest-priority fix; usually requires both SKILL.md edits and reference-material updates. Re-run after fixing.
- **Refusal fail** — skill produces output on inputs it should refuse. Usually a SKILL.md authoring issue in the "When this skill does not apply" or "Edge cases and refusals" section.

Failures are filed as GitHub Issues with the `acceptance-test-fail` label, linked to the test plan scenario, and tracked through to fix-and-re-run before the skill version ships.

---

## Issues filing convention

Issues found in acceptance testing are filed using a consistent convention so they're easy to triage:

**Title format:** `[<skill-name> v<version>] <scenario name> — <failure category>`

Example: `[nda-review v1.0.1] Scenario 3 (recipient-perspective vendor NDA) — Calibration fail`

**Body format:**

```markdown
## Test scenario

[Reference to the scenario in the test plan, including link.]

## Expected behavior

[Quote or paraphrase the expected behavior from the test plan.]

## Actual behavior

[Description of what the skill actually produced. Include the relevant
output excerpt; do not include the test document itself if it is
sourced from the operator's practice.]

## Failure category

[Structural | Calibration | Conservative-posture | Refusal]

## Reproduction

[How to reproduce: skill version, inputs, document characteristics
that triggered the issue. Document content can be paraphrased rather
than reproduced if confidentiality requires.]

## Suggested fix

[If the tester or reviewer has a hypothesis about where the issue
lives — SKILL.md, reference file, frontmatter — note it.]
```

Issues block the skill version's release until resolved. Resolved-and-re-tested issues are closed with a link to the fix PR.

---

## Cadence

Acceptance testing runs at three points:

1. **Pre-release of a skill version.** Every new or updated skill goes through acceptance testing before the version ships. The skill author runs structural checks; a reviewing attorney runs calibration evaluation; the conservative-posture check is part of the substantive review process documented in [`skills/CONTRIBUTING.md`](../skills/CONTRIBUTING.md).
2. **Pre-release of a project version.** Before each minor release of LQ.AI (every 6–8 weeks), all M1 starter skills are re-run against the test corpus. Regressions surface as failures and block release.
3. **Ad-hoc when issues are reported.** When a community user reports a substantive issue with a skill, the relevant scenario is added to the test corpus and re-run. New scenarios that surface from real-world reports become permanent additions to the test plan.

---

## Test runner conventions

Acceptance testing can be run manually (a tester runs each scenario, captures output, evaluates) or scripted (a test runner iterates over the test corpus, runs the skill, captures output, surfaces results for human review). The framework supports both.

For scripted runs, the convention:

```bash
# From the project root, against a configured LQ.AI deployment
lq-test acceptance \
  --skill nda-review \
  --skill-version 1.0.1 \
  --corpus ./test-corpus/nda-review/ \
  --plan ./skills/nda-review/test-plan.md \
  --output ./test-results/nda-review-v1.0.1/
```

The runner produces:
- `test-results/<skill>-v<version>/structural-results.md` — per-scenario structural-check results.
- `test-results/<skill>-v<version>/outputs/<scenario>.md` — the skill's actual output for each scenario, for the reviewing attorney to evaluate.
- `test-results/<skill>-v<version>/calibration-template.md` — a template for the reviewing attorney to fill in their calibration assessment.

Manual runs follow the same output structure but require the tester to construct the result files by hand.

The `lq-test` CLI is on the deferred-enhancements list (DE-### TBD); for v1, manual runs are the baseline. The framework documents what scripted runs would look like to anchor future work.

---

## Skill-by-skill test plan map

Each M1 starter skill has its test plan in the skill's folder:

| Skill | Test plan location |
|---|---|
| NDA Review | [`skills/nda-review/test-plan.md`](../skills/nda-review/test-plan.md) |
| MSA Review — SaaS | [`skills/msa-review-saas/test-plan.md`](../skills/msa-review-saas/test-plan.md) |
| MSA Review — Commercial Purchase | [`skills/msa-review-commercial-purchase/test-plan.md`](../skills/msa-review-commercial-purchase/test-plan.md) |
| DPA Checklist Review | [`skills/dpa-checklist-review/test-plan.md`](../skills/dpa-checklist-review/test-plan.md) |
| Vendor Privacy Policy First Pass | [`skills/vendor-privacy-policy-first-pass/test-plan.md`](../skills/vendor-privacy-policy-first-pass/test-plan.md) |
| Contract QA | [`skills/contract-qa/test-plan.md`](../skills/contract-qa/test-plan.md) |
| Action Items from Client Alert | [`skills/action-items-from-client-alert/test-plan.md`](../skills/action-items-from-client-alert/test-plan.md) |
| Comms Improver | [`skills/comms-improver/test-plan.md`](../skills/comms-improver/test-plan.md) |
| Enhance Prompt | [`skills/enhance-prompt/test-plan.md`](../skills/enhance-prompt/test-plan.md) |
| Skill Creator | [`skills/skill-creator/test-plan.md`](../skills/skill-creator/test-plan.md) |

For new skills, the contributor drafts a test plan following the template above as part of the skill PR.

---

## What this framework does not do

- **It does not specify exact expected output text.** LLM outputs vary across runs, models, and minor prompt changes. Specifying exact text would produce a test suite that fails on every immaterial wording shift; specifying expected categories, severity ranges, and structural elements is robust to that variation.
- **It does not test correctness of the underlying foundation model.** The model's substantive accuracy (does it correctly identify a force majeure clause? does it accurately describe GDPR Article 28 obligations?) is inherited from the chosen provider. The skill's test plan tests whether the skill *applies the model* in the documented way and whether the skill's *prompts and reference materials* lead the model to produce calibrated output.
- **It does not certify the skill for any particular legal use.** Acceptance testing confirms the skill behaves as specified; it does not warrant the skill's output for any specific legal context. The "What this skill does not do" enumeration in each skill, and the human-in-the-loop expectation in [PRD §1.3](PRD.md#13-transparency-as-a-founding-principle) and [§7.1](PRD.md#71-project-philosophy), remain in effect.
- **It does not replace ongoing skill maintenance.** Skills evolve; regulatory landscapes change; calibrations drift. The test plan is the skill's quality floor at version <X>, not a promise of perpetual correctness.

---

*Framework maintained alongside the skills. Updates land in the skill release cadence; framework changes that affect all skills warrant a PRD amendment.*
