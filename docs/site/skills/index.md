---
title: Skills
description: What a skill is in LQ.AI, and where to read, write, test, place, and trust one.
audience: [author, contributor, evaluator]
status: draft
sources:
  - README.md
sidebar:
  order: 1
---

LQ.AI's skills are its canonical artifact of value: reusable, structured prompt
artifacts that shape what the assistant does for a recurring task — reviewing an
NDA, checking a DPA against a regime's checklist, drafting action items from a
client alert. Every skill is a folder in the open, built on the
[agentskills.io / Anthropic Claude Skills](https://github.com/anthropics/skills)
format. When a skill produces output you disagree with, you read the `SKILL.md`
driving it, fork it, and change it — that is the point of shipping skills as
files instead of a hidden system prompt.

This section covers what a skill is, how to write one, how to test it before you
rely on it, where a new skill should live, and what the attestation on a
legal-substance skill actually promises.

- [What a skill is](../../skill-authoring-guide.md) — the anatomy of a `SKILL.md`: what goes
  in frontmatter, what goes in the body, and what becomes part of the model's
  prompt.
- [Author your first skill](../../skills/author-your-first-skill.md) — write one by hand
  following the authoring guide, or build it in conversation with the Skill
  Creator, using NDA Review as the worked example.
- [Your prompt files are already skills](../../skills/your-prompt-files-are-skills.md) — the
  fastest way in if you already have prompts you reuse by hand.
- [Test your skill before sharing it](../../acceptance-testing-framework.md) — the structural-vs-
  calibration test-plan pattern every first-party skill follows, and what
  "acceptance-tested" does and does not mean today.
- [Where skills live](../../skills/where-skills-live.md) — personal, team-shared, or
  upstream, and which upstream, for jurisdiction- or practice-area-specific
  work.
- [The attestation bar](../../../skills/CONTRIBUTING.md) — what a legal-substance skill's
  attestation covers, who can make it, and how it decays.
- [Playbooks](../../playbooks.md) — the related artifact that codifies an
  organization's standard and fallback positions, rather than a workflow.
- [Skill catalogue](catalogue.intro.md) — every first-party skill in one table:
  practice area, jurisdiction, version, author, attestation.
- [Coverage by jurisdiction and practice area](coverage.intro.md) — what's
  covered today, what's a documented gap, and where a gap goes to get filled.

## Next

- [What a skill is](../../skill-authoring-guide.md)
- [Skill catalogue](catalogue.intro.md)
