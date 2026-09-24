---
title: "Reusable instructions: skills"
description: A skill is a saved set of instructions for a task, sometimes with supporting files — where to read, write, test, place, and trust one.
audience: [author, contributor, evaluator]
status: draft
sources:
  - README.md
sidebar:
  order: 1
---

A skill is a saved set of instructions for a particular task, sometimes with supporting files — it
gives the AI a starting point you can inspect and adapt. LQ.AI's skills are its canonical artifact
of value (PRD §7.1): reusable, structured prompt artifacts that shape what the assistant does for a
recurring task — reviewing an NDA, checking a DPA against a regime's checklist, drafting action
items from a client alert. Every skill is a folder in the open, built on the
[agentskills.io / Anthropic Claude Skills](https://github.com/anthropics/skills)
format. When a skill produces output you disagree with, you read the `SKILL.md`
driving it, fork it, and change it — that is the point of shipping skills as
files instead of a hidden system prompt.

## Find, adapt, or share

Use the catalogue and coverage pages to find a starting point. Read [What is a skill?](../../skill-authoring-guide.md)
for its structure, then the authoring and saved-prompt guides to adapt it. Testing, the attestation
bar, and where skills live cover different parts of sharing one responsibly. Playbooks has its own
page because contract positions are different from a skill's workflow.

- [What is a skill?](../../skill-authoring-guide.md) — the anatomy of a `SKILL.md`: what goes
  in frontmatter, what goes in the body, and what becomes part of the model's
  prompt.
- [Write your first skill](../../skills/author-your-first-skill.md) — write one by hand
  following the authoring guide, or build it in conversation with the Skill
  Creator, using NDA Review as the worked example.
- [Turn a saved prompt into a skill](../../skills/your-prompt-files-are-skills.md) — the
  fastest way in if you already have prompts you reuse by hand.
- [Test a skill before sharing it](../../acceptance-testing-framework.md) — the structural-vs-
  calibration test-plan pattern every first-party skill follows, and what
  "acceptance-tested" does and does not mean today.
- [Find the skill files](../../skills/where-skills-live.md) — personal, team-shared, or
  upstream, and which upstream, for jurisdiction- or practice-area-specific
  work.
- [What counts as a reviewed skill?](../../../skills/CONTRIBUTING.md) — what a legal-substance skill's
  attestation covers, who can make it, and how it decays.
- [Use a review playbook](../../playbooks.md) — the related artifact that codifies an
  organization's standard and fallback positions, rather than a workflow.
- [Skill catalogue](catalogue.intro.md) — every first-party skill in one table:
  practice area, jurisdiction, version, author, attestation.
- [Coverage by jurisdiction and practice area](coverage.intro.md) — what's
  covered today, what's a documented gap, and where a gap goes to get filled.

## Next

- [What is a skill?](../../skill-authoring-guide.md)
- [Skill catalogue](catalogue.intro.md)
