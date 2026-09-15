---
title: Test your skill before sharing it
description: The structural-vs-calibration test-plan pattern every first-party skill follows, and what's tested today versus documented but open.
audience: [author, contributor]
status: draft
sources:
  - docs/acceptance-testing-framework.md
  - docs/contribute/mini-prds/skill-acceptance-tests.md
  - docs/PRD.md
  - skills/nda-review/test-plan.md
sidebar:
  order: 5
---

Before you attach a new skill to real client work — or ship one for others to
use — you want more than "it ran without an error." The project's acceptance
framework asks two separate questions, and it's worth keeping them separate:

1. **Is the output the right shape?** Sections present, severity tags
   formatted per the rubric, citations that resolve, the correct
   `output_format`. This is mechanically checkable.
2. **Is it calibrated?** A skill that flags every routine NDA as carrying
   critical findings is uncalibrated regardless of how clean its structure is.
   Calibration needs a practicing lawyer's judgment against real documents —
   there is no way to script it.

## Writing a test plan

Each of the ten M1 starter skills carries a `test-plan.md` alongside its
`SKILL.md` (the index is in
[`docs/acceptance-testing-framework.md`](../../../docs/acceptance-testing-framework.md)).
The five later built-ins — `case-law-research`, `contract-snapshot`,
`msa-snapshot`, `nda-snapshot`, `playbook-easy-extract` — do not.
[`skills/nda-review/test-plan.md`](../../../skills/nda-review/test-plan.md) is a
representative one: it opens with the skill summary and the test-corpus
requirements (how many documents, which variants — mutual, unilateral from
each perspective, at least one unusual-structure outlier, one clean baseline),
then walks through numbered scenarios, each with the inputs, the expected
output structure, the expected calibration (a finding-count and severity range
a reviewing attorney would recognize as sane), and edge cases the scenario is
meant to surface.

The framework document
([`docs/acceptance-testing-framework.md`](../../../docs/acceptance-testing-framework.md))
describes a `skills/_test-plan-template.md` as the starting point for a new
plan. **That file is not present in the repository as of the checked
commit** — use an existing plan such as
[`skills/nda-review/test-plan.md`](../../../skills/nda-review/test-plan.md) as the
template instead; its structure (summary, corpus requirements, scenarios, pass
criteria) is the one every shipped test plan follows.

Test documents themselves are never committed to the repository — you source
and anonymize your own corpus from real (anonymized) practice, per the
anonymization conventions the framework lays out: neutral party names,
structurally similar placeholders for identifiers, substantive clause
language and severity-relevant content left intact.

## What "acceptance-tested" means today

The framework also specifies a fuller **acceptance pack** — an `acceptance/`
directory per skill with anonymized inputs, structural expectations, captured
outputs across at least two models, and a `results.md` naming the reviewing
attorney and their substantive notes, per the
[skill-acceptance-tests mini-PRD](../../../docs/contribute/mini-prds/skill-acceptance-tests.md).
That mini-PRD is tracked as ten separable, attorney-authored contributions —
one per starter skill. The PRD labels this area **partial**: the test plans
ship, the harness that executes them is **deferred**, and the acceptance pass
is open for contribution as ten separable PRs. As of the checked commit, none
of the fifteen built-in skills has a populated `acceptance/` directory in this
repository. The test plans exist; the acceptance pass that runs them against
real documents and records the result does not yet, for any shipped skill. If you're evaluating a skill's real-world reliability rather
than authoring one, read its `test-plan.md` to see what it's designed to
handle, but do not read an absent `acceptance/` directory as a claim either
way about how it performs.

If you're picking up one of the ten as a contribution, the mini-PRD's
"Where to start" section and the skill's own `test-plan.md` are the two files
to read next.

## Next

- [The attestation bar](attestation.md)
- [Author your first skill](author-your-first-skill.md)
