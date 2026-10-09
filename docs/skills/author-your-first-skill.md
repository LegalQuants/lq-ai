# Author your first skill

There are two ways to get a first skill written, and neither requires
reading the whole [Skill-Authoring Guide](../skill-authoring-guide.md)
before you start.

## Build it in conversation

The fastest path is the **Skill Creator**, itself a skill
([`skills/skill-creator/SKILL.md`](../../skills/skill-creator/SKILL.md)),
attached to a chat like any other. It asks one question at a time rather
than running a fixed form — what triggers the skill, what document or
input it needs, what the workflow actually checks, what it should refuse
— and drafts the `SKILL.md` for you once it has enough to work with. Its
stated posture: "You hold the format. The user holds the legal
expertise." It will not invent a jurisdiction-specific rule or a severity
calibration you haven't given it; if it needs a substantive position you
haven't stated, it asks rather than guesses. That's deliberate — the same
conservative posture every shipped skill follows.

## Write it by hand

The other path is drafting `SKILL.md` directly against the format
documented in the [Skill-Authoring Guide](../skill-authoring-guide.md).
The frontmatter carries the fields the application and the model both
read to decide when the skill applies and how it runs. Real frontmatter,
from the shipped NDA Review skill, shows the shape:

```yaml
---
name: nda-review
description: Use when the user uploads or pastes a non-disclosure agreement and asks for review, redline, risk assessment, or a recommendation on whether to sign. Identifies missing standard protections, one-sided or unusual provisions, and operational issues; produces a structured report with severity ratings and citations to specific clauses, calibrated to the user's perspective (discloser, recipient, or mutual).
lq_ai:
  title: NDA Review
  version: 1.0.1
  author: LegalQuants
  tags: [contracts, nda, confidentiality, review]
  jurisdiction: US-default
  trigger_examples:
    - "review this NDA"
    - "redline this confidentiality agreement"
    - "what should I watch for in this NDA"
    - "is this NDA okay to sign"
    - "summarize the risks in this NDA"
  inputs:
    required:
      - name: document
        type: document
        description: The NDA to review (PDF, DOCX, or pasted text).
      - name: perspective
        type: text
        description: Which side the user represents. One of "discloser" (we are sharing information; we want strong protections on the recipient), "recipient" (we are receiving information; we want narrow obligations on us), or "mutual" (both parties are exchanging information; we want symmetric, balanced terms). If not provided, ask before proceeding.
    optional:
      - name: jurisdiction
        type: text
        description: Governing-law jurisdiction if known (e.g., "Delaware", "California", "New York", "EU", "UK"). Defaults to general US commercial assumptions.
      - name: deal_type
        type: text
        description: The transaction context this NDA supports. Common values - "vendor_evaluation" (we're evaluating a vendor product/service), "customer_engagement" (we're engaging with a prospective customer), "ma_diligence" (acquisition or investment due diligence), "partnership" (commercial partnership exploration), "employment_recruitment" (recruiting senior talent), "litigation_settlement" (settlement-adjacent confidentiality), "general_commercial" (exploratory business conversation, default). Affects severity calibration — e.g., non-solicits warrant more scrutiny in vendor evaluations than in M&A diligence.
      - name: prior_agreements
        type: text
        description: Any existing agreements between the parties that may interact with this NDA (e.g., "we already have an MSA dated 2024-03"; "we signed a prior unilateral NDA in 2023"). Surfaces conflict-with-prior-agreement issues during review.
      - name: standard_positions
        type: text
        description: User's organization's standard fallback positions on common NDA issues (term length, definition scope, etc.), if applicable.
  output_format: markdown
  self_improvement: false
---
```

`name` matches the folder name exactly; `description` is what both the UI
and the model use to decide when the skill applies, so it earns being
specific rather than generic. `lq_ai.trigger_examples` wants at least
three real phrasings — NDA Review ships five. Required inputs stay
minimal — NDA Review requires only the document and the reviewer's
perspective; everything else is optional and, per the guide's own test,
changes the *substance* of the analysis rather than only the report's
formatting (`deal_type` recalibrates which provisions get scrutiny;
`jurisdiction` shifts the governing-law assumptions).

The body of `SKILL.md` follows a consistent structure across the M1
starter skills, documented as ten sections in the
[Skill-Authoring Guide's "SKILL.md body structure"](../skill-authoring-guide.md#skillmd-body-structure)
— eight expected, plus optional "Reference materials" and "Examples".
Read [`skills/nda-review/SKILL.md`](../../skills/nda-review/SKILL.md) end
to end once to see the shape in a shipped skill; note that it folds its
negative scoping into "When this skill applies" rather than carrying a
separate "When this skill does NOT apply" section. Its
[`examples/example_mutual.md`](../../skills/nda-review/examples/example_mutual.md)
shows what a worked example looks like.

## Before you call it done

Run the guide's own
[authoring checklist](../skill-authoring-guide.md#authoring-checklist)
before you submit. A skill with legal substance in it does not stop at
"it runs." Read the
[acceptance testing framework](../acceptance-testing-framework.md)
for how the project verifies structure and calibration before a skill
goes out, and [The attestation bar](../../skills/CONTRIBUTING.md#3-attest)
for what signing off on one actually means.
