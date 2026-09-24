# Contributing Skills to LQ.AI

## In short

- A skill's `author` field alone doesn't prove it was reviewed — a real review names who checked it, what they tested, and what they found.
- Any skill with legal substance needs a named human attestation before it merges: a practicing attorney certifies in the PR description that they reviewed the content and it reflects reasonable practice in the stated jurisdiction(s) — either as the skill's co-author, or as the reviewing attorney when the author is a legal-ops practitioner or engineer. An AI agent cannot make this attestation.
- Merge also needs review from a practicing attorney and an engineer, and any later change to a skill's substance goes through the same process again.
- No shipped skill records the attesting attorney's name in its own metadata: 14 of the 15 first-party `SKILL.md` files list `author: LegalQuants`, and the 15th (`skill-creator`) carries no `lq_ai:` block at all — the merging pull request is the only place to find a skill's attestation record.

Skills are the canonical artifact of value in this project. **When the project produces a wrong answer, the answer to "why" is almost always in a `SKILL.md` somewhere. Improving LQ.AI is mostly improving skills.**

This document covers contributions of **skills containing legal substance** — the everyday work-product skills like NDA Review, MSA Review, DPA Checklist Review, and the dozens of related skills the deferred-enhancements list catalogs. The contribution path for skills is meaningfully different from the engineering contribution path because skills carry legal substance: the patterns they encode, the severity calibrations they apply, and the recommended language they suggest will affect real legal work in real organizations. The bar is correspondingly higher.

For **engineering contributions** (code, infrastructure, deployment recipes, general project documentation), see the project-root [`CONTRIBUTING.md`](../CONTRIBUTING.md) instead. For **skills that don't carry legal substance** (developer tooling, infrastructure helpers — the rare skill that is a pure technical utility), the engineering path applies.

---

## Why skill contribution has a higher bar

LQ.AI is open source for the same reason a black-box statute would be unsuited to law: **the tools that shape a lawyer's judgment should be accountable to clients, courts, regulators, and ethics boards**. A skill that produces a wrong answer should be readable, debuggable, and forkable by the lawyer who relies on it. A skill that codifies a position should be reviewable by the team that signs off on it.

That accountability has a flip side. Because skills are open source and used in real practice, contributing a skill means contributing legal substance to a community of practitioners who may rely on it. The contribution norms below — attestation, practicing-attorney review, conservative posture — exist to keep the bar high enough that the project is fitness-for-purpose for the work it claims to do.

---

## What skills look like

A skill is a folder containing `SKILL.md` (with YAML frontmatter) and optional supporting files in the [agentskills.io / Anthropic Claude Skills format](https://github.com/anthropics/skills). The structure:

```
my-skill/
├── SKILL.md              # Required. Main instruction file with frontmatter.
├── reference/            # Optional. Reference material the skill cites.
│   └── ...
├── examples/             # Optional but strongly encouraged. Worked examples.
│   └── ...
└── scripts/              # Optional. Executable helpers (Python).
    └── ...
```

`SKILL.md` frontmatter follows the format documented in the [Skill-Authoring Guide](../docs/skill-authoring-guide.md):

```yaml
---
name: my-skill-name
description: One sentence describing when this skill should be applied.
lq_ai:
  title: My Skill Title
  version: 1.0.0
  author: <Your name or LegalQuants>
  tags: [...]
  jurisdiction: <regime-aware | us | eu | global | other>
  trigger_examples:
    - "..."
  inputs:
    required:
      - ...
    optional:
      - ...
  output_format: report     # report | table | issues_list | redline
  minimum_inference_tier: 2 # optional
  use_organization_profile: true  # optional; default true
  is_organization_profile: false  # singleton; only set true on the org profile
  self_improvement: false   # default false for v1.0.0 skills
---
```

The body of `SKILL.md` is the operational content of the skill: when to apply it, when not to, the workflow, the output format, edge cases, refusals, and what the skill does not do.

For the full conventions — perspective branching, severity rubrics, optional-input design, output-format conventions, calibration check expectations — read the [Skill-Authoring Guide](../docs/skill-authoring-guide.md). The M1 starter skills demonstrate the patterns the guide documents; they are good examples to read before authoring.

---

## What kinds of skills the project welcomes

The deferred-enhancements list ([PRD §9](../docs/PRD.md#9-deferred-enhancements-and-identified-future-work)) catalogs specific skills the project welcomes. The most consequential candidates:

**New domain skills (DE-001):**
- Settlement Agreement Review.
- Employment Offer Letter Review.
- SOC 2 / Audit Response Drafter.
- Regulatory Filing Drafter (state-by-state corporate filings).
- Patent License Review.
- Trademark License Review.
- Open Source License Compatibility Checker.
- HIPAA BAA Review (as a separate skill from DPA Checklist Review's HIPAA mode).
- Multi-state US Privacy DPA Review (harmonized).

**Additional regimes for DPA Checklist Review (DE-002):**
- Brazil LGPD.
- China PIPL.
- Singapore PDPA.
- Australia Privacy Act.
- India DPDP Act.
- South Korea PIPA.
- Canada PIPEDA / provincial laws (Quebec Bill 64 / Law 25, BC PIPA, Alberta PIPA).

**Skill-pattern skills (DE-005, DE-006, DE-007, DE-008):**
- Defined-Terms Consistency Check.
- Cross-Document Comparison.
- Issue List Generator (structured-output mode for any review skill).
- Self-serve business-user contract generation (NDA generator, sales-side order form generator).

**Capability-extension skills (DE-082):**
- Regulatory monitoring (Federal Register / SEC EDGAR / EUR-Lex / state AG watch skills).

**Workflow-intelligence skills (M5+; DE-209, DE-210):**
- Email Triage Skill (consumes incoming email signals; classifies; proposes routing).
- Calendar Prep Skill (pre-meeting briefs from calendar awareness and Project context).

The full backlog is in [PRD §9](../docs/PRD.md#9-deferred-enhancements-and-identified-future-work). Pick a candidate that matches your practice area and propose a skill.

Skills outside this catalog are also welcome — file an issue describing the use case and the proposed skill before investing time in authoring.

**Where a new skill lands** is decided by [ADR 0024](../docs/adr/0024-jurisdiction-and-practice-area-expansion.md): a new domain skill or a new jurisdiction/regime for an existing skill is a community work-product contribution and routes to [`legalquants/lq-skills`](https://github.com/LegalQuants/lq-skills), not this repository. This repository's own `skills/` directory holds the curated first-party set; a change to an existing first-party skill (a new regime for DPA Checklist Review, for example) still follows the process below, in this repository.

---

## The contribution process

Skill contribution has five steps: claim, draft, attest, review, merge.

### 1. Claim

**File or comment on a tracking issue first.** This avoids two contributors duplicating work on the same skill, surfaces any architectural or scope concerns early, and gives a maintainer the chance to flag related work.

If a deferred-enhancement entry exists for the skill (e.g., DE-001 candidates, DE-002 regimes), comment on the existing issue or file a new one referencing the DE-### entry. If no entry exists, file an issue describing the skill: what it does, when it triggers, what inputs it takes, what output it produces, what perspective branching applies if any.

A maintainer will respond within ~5 business days confirming the slot, suggesting refinements, or (rarely) flagging a scope concern.

### 2. Draft

**Read the [Skill-Authoring Guide](../docs/skill-authoring-guide.md) before drafting.** The guide documents the conventions established by the M1 starter skills — perspective branching, severity rubrics, optional-input design, output-format patterns, calibration check expectations. New skills should follow these conventions unless there's a specific reason to diverge.

**Read at least two M1 starter skills** in the area closest to your skill before drafting. Suggested pairings:

| If you're drafting | Read these first |
|---|---|
| A new contract review skill | NDA Review, MSA Review — SaaS |
| A new privacy / regulatory review skill | DPA Checklist Review, Vendor Privacy Policy First Pass |
| A new Q&A skill | Contract QA |
| A new extraction skill | Action Items from Client Alert |
| A new transformation skill | Comms Improver |
| A new meta-skill | Skill Creator, Enhance Prompt |

Draft the skill in your fork:

```bash
mkdir -p skills/my-skill/reference skills/my-skill/examples
# Draft skills/my-skill/SKILL.md following the format
# Draft any reference files in skills/my-skill/reference/
# Draft at least one worked example in skills/my-skill/examples/
```

**Required elements:**

- `SKILL.md` with complete frontmatter (every `lq_ai:` field that applies; do not omit fields with the assumption that they'll default).
- The body of `SKILL.md` covering: when this skill applies, when not to apply, inputs, workflow, output format, edge cases and refusals, what this skill does not do.
- **At least one worked example** in `examples/` showing the skill applied end-to-end on a representative input, with the resulting output. For skills with perspective branching or regime selection, multiple examples are strongly preferred (one per perspective / regime).
- **Reference files** in `reference/` for any operational checklists, severity rubrics, or substantive content the skill draws on. The pattern from the contract-review skills — separate `reference/severity_rubric.md`, `reference/report_structure.md`, etc. — is a good model for review skills, less applicable to extraction or transformation skills.

**Conservative posture conventions** (from the M1 skills, applied across the board):

- Skills do not invent legal substance. They surface patterns, apply rubrics, and flag concerns; they do not assert legal opinions outside the scope of the skill.
- Skills defer enforceability opinions. "This clause is unusual" not "this clause is unenforceable."
- Skills do not invent statutory citations. If a citation is not verified in the source document or reference material, the skill does not include it.
- Skills explicitly enumerate what they do NOT do. The "What this skill does not do" section is a feature, not a defensiveness — it tells users when to escalate to expert legal counsel.
- `self_improvement: false` is the default for v1.0.0 skills. Self-improvement is a deferred enhancement; v1.0.0 skills are stable artifacts under semver, not learning systems.

### 3. Attest

**Skills containing legal substance require an attestation** that the substantive content is accurate to the contributor's knowledge. Add the attestation to your PR description:

> **Attestation.** I have reviewed the substantive legal content of this skill and certify that, to the best of my knowledge as a [practicing attorney / legal professional / specific role], the patterns, severity calibrations, recommended language, and reference material reflect accurate and reasonable legal practice in [jurisdiction(s)]. I understand that this skill will be used in real practice and that errors could affect real legal work; I have authored this skill with the same care I would apply to my own client work.
>
> *Signed: [your name and any relevant qualifications]*

The attestation is **not a personal warranty of legal correctness for every conceivable use case** — that bar is impossible. It is an attestation of the same care a practicing lawyer applies to their own work product, an acknowledgment that the contribution will be used in real practice, and an acknowledgment that the contributor has reviewed the skill substantively (not just submitted it).

Contributors who are not themselves practicing attorneys can still author skills, with one of two paths:

- **Pair with a practicing-attorney co-author.** The co-author makes the attestation; both names appear in the skill's `author` field.
- **Author and have the skill reviewed by a practicing attorney before submission.** Add the reviewing attorney's name and acknowledgment to the PR description; the reviewer makes the attestation. This is the right path for legal-ops practitioners and engineers who want to contribute substantive skills.

In both cases, the attesting attorney's name appears in the skill's metadata and the project's contributor credits.

> [!NOTE]
> **Professional duty** — An attestation is another lawyer's statement of care, not a transfer of your own. Relying on a skill's output in client work is an exercise of your competence and, where you supervise others using it, your supervision — the attesting attorney's name tells you who stood behind the substance at that version, not that the output is right for your matter. Each skill's "What this skill does not do" section is the boundary the attestation was made against; read it before the first client use.

The attestation does not expire with time; it decays only with updates. There is no expiry date on an attestation — what happens instead is that any update to a skill's substance (a new perspective, a changed severity calibration, a regime added) goes through this same review-and-attest process again, calibrated to the size of the change. A skill that hasn't been touched since its `1.0.0` release still carries its original attestation; a skill on `1.3.0` carries whatever attestation covered the `1.3.0` change, on top of the ones before it.

As of the checked commit, the commitment above (the attesting attorney's name in the skill's `author` field) is unmet in the shipped corpus: fourteen of the fifteen first-party `SKILL.md` files record `author: LegalQuants`, and the fifteenth (`skill-creator`) carries no `lq_ai:` block at all — so no shipped skill records an individual attesting attorney's name in frontmatter, and no `SKILL.md` carries a dedicated attestation field. The merging pull request is therefore the only per-skill attestation record today; if you need the attesting record for a specific skill, the PR history is currently the only place to find it.

### 4. Review

**All skills containing legal substance require review by at least one practicing attorney plus one engineer** before merge. The reviewer roles:

- **Practicing attorney reviewer** focuses on substantive accuracy: are the patterns correct? Are the severity calibrations reasonable? Is the recommended language clean? Are there scenarios where the skill would produce wrong output? Is the conservative-posture norm being followed?
- **Engineer reviewer** focuses on the operational shape: is the frontmatter complete? Does the workflow run cleanly? Are the worked examples actually worked? Does the skill follow the format conventions? Are there integration concerns with the application or other skills?

Reviewers will be assigned by maintainers when the PR is opened. If you have a specific reviewer in mind (e.g., a maintainer with relevant practice-area expertise), tag them in the PR description.

Review feedback typically falls into three categories:

1. **Substantive concerns** — the practicing-attorney reviewer disagrees with a pattern, severity calibration, or recommended language. Address by discussing in the PR thread; the goal is to reach the most defensible position, which sometimes means deferring to the reviewer's reasoning, sometimes means deferring to the contributor's, and sometimes means revising in a third direction.
2. **Format / convention concerns** — the engineer reviewer flags missing frontmatter fields, incomplete examples, conventions the skill diverges from. Usually quick to address.
3. **Scope concerns** — the skill does too much, too little, or the wrong thing. May require restructuring; in extreme cases, splitting into multiple skills or merging with an existing skill.

Maintainer approval is required to merge; for skills with significant substantive content, a second maintainer review is preferred.

### 5. Merge

After approval, the skill is merged. The merge commit:

- Adds the skill folder under `skills/<skill-name>/` in the canonical location.
- Updates the skill registry in `skills/index.json` (or equivalent).
- Triggers a release-prep step that includes the skill in the next minor release.
- Adds the contributor's name to the project's `CONTRIBUTORS.md` if not already present.

---

## Versioning skills

Skills carry semver version numbers in `lq_ai.version`. The conventions:

- **`1.0.0`** — first stable release of a skill. Reviewed, attested, ready for production use.
- **`1.0.x`** — patch updates that don't change skill behavior materially: typo fixes, reference material updates, additional examples, expanded edge-case handling.
- **`1.x.0`** — minor updates that add capabilities without breaking existing behavior: a new optional input, a new perspective, a new output mode.
- **`2.0.0`** — major updates that change skill behavior in ways that existing users would notice: removed inputs, changed defaults, materially different output structure.

Pre-1.0 versions (`0.x.y`) signal that the skill is not yet ready for production use; these should be marked clearly in the skill's frontmatter and not surfaced to end users.

When updating a skill, bump the version per the conventions above and update the `version` field in frontmatter. The skill-update path follows the same review and attestation process as new-skill creation, calibrated to the scope of the change: a typo fix needs less review than a new perspective added.

---

## Forking and divergent positions

Skills are **forkable**. If your team's practice diverges from a starter skill — different severity calibration, different jurisdiction-specific conventions, different recommended language — you can fork the skill, modify it for your team, and use the fork in your deployment.

Forks can be:

- **Private to your deployment** — most common case; your fork stays in your repo.
- **Contributed back as a variant** — if your fork would be useful to others (e.g., MSA Review for a different industry vertical), file an issue proposing the variant. Variants typically take a different `name` (`msa-review-saas`, `msa-review-financial-services`) and live alongside the original rather than replacing it.
- **Contributed back as an improvement** — if your fork addresses a substantive issue with the original, file a PR against the original. Substantive improvements go through the same review and attestation process.

The project welcomes variants and improvements; what we do not do is replace a starter skill with a fork that has a meaningfully different posture without preserving both. The original maintains its name; the variant gets a new name; users choose which to attach.

---

## What about skills that don't contain legal substance?

A small number of skills are pure technical utilities — developer tooling, deployment helpers, or infrastructure skills (e.g., a skill that runs a security scan against an attached document). These do not require the practicing-attorney attestation and review path. Submit them under the [engineering CONTRIBUTING.md](../CONTRIBUTING.md) instead.

The line between "contains legal substance" and "pure technical utility" is occasionally fuzzy. When in doubt, treat the skill as substantive — the higher bar is the safer default. A maintainer will redirect to the engineering path if the higher bar isn't warranted.

---

## Maintenance and ownership

Once merged, a skill enters the project's maintenance flow:

- **Issues filed against the skill** are routed to the original contributor as the first reviewer. If the contributor is unavailable or no longer active, maintainers triage.
- **Updates from upstream regulatory changes** (e.g., a new EU regulation that affects DPA Checklist Review) are typically handled by maintainers or the original contributor. Community contributions to bring a skill current with regulatory changes are very welcome.
- **Deprecation** of a skill happens only with maintainer approval and a clear migration path for users. Deprecated skills remain in the repository (for users on older versions) but are removed from the default installation.

The original contributor's name remains in the skill's `author` field even when subsequent contributors update or maintain the skill; updaters add their names rather than replacing.

---

## Code of Conduct

The project [Code of Conduct](../CODE_OF_CONDUCT.md) applies to skill contribution as much as to engineering contribution. Skill review can produce substantive disagreement — that's part of the value. The expectation is that disagreements stay focused on the work and on what would best serve in-house counsel using the skill, not on personal characteristics or contributor identity.

---

## License

By contributing a skill, you agree that your contribution will be licensed under the project's [Apache License 2.0](../LICENSE). Skills are work product the community can read, fork, modify, and redistribute under the same license. The DCO sign-off (per [`CONTRIBUTING.md`](../CONTRIBUTING.md)) is your assertion that you have the right to contribute the work under that license.

---

## Questions?

- **General skill-authoring questions** → GitHub Discussions or `#skill-authors` on Discord.
- **Specific skill proposals** → file a GitHub Issue with the `skill-proposal` label, referencing the relevant DE-### entry if one exists.
- **Substantive legal questions on a skill in review** → discuss in the PR thread; tag the practicing-attorney reviewer for substantive review.
- **Cross-cutting skill conventions** → propose changes to the [Skill-Authoring Guide](../docs/skill-authoring-guide.md) via a PR; conventions changes go through maintainer review.

Thanks for contributing a skill. The project's value is in its curation and authoring of skills — your contribution makes the project more useful to in-house lawyers everywhere.
