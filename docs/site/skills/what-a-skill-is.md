---
title: What a skill is
description: The anatomy of a SKILL.md — what's frontmatter, what's prompt, and why the format matters.
audience: [author, evaluator]
status: draft
sources:
  - docs/skill-authoring-guide.md
  - README.md
sidebar:
  order: 2
---

You're about to write, read, or evaluate a skill and want to know what you're
actually looking at before the frontmatter tables and worked examples. A skill
is a folder, not a black box: `SKILL.md` plus a few optional subfolders, and
everything in `SKILL.md` becomes part of the prompt the model runs on when you
attach the skill to a chat.

<!-- include: docs/skill-authoring-guide.md from="## Skill anatomy" to="## SKILL.md frontmatter" -->

Two things follow from that anatomy that a first read tends to miss.

First, **`reference/` is not automatically in the prompt.** It's material the
skill's own workflow instructions point at — "see `reference/severity_rubric.md`
for the calibration tiers" — so the model loads it when the skill's instructions
say to, not unconditionally. A skill with a heavy `reference/` tree is not
necessarily a heavier prompt; it depends what the workflow actually cites.

Second, **`examples/` is documentation, not instruction.** It exists for three
audiences at once — a user deciding whether the skill fits their document, a
reviewer checking the skill's calibration, and a maintainer checking for drift
after a model upgrade — and none of that depends on the model reading it at
run time.

Where a skill physically lives changes what "editing" a skill means. Built-in
skills (the ones this repository ships in `skills/`) are files in this
repository — editing one is a pull request through
[`skills/CONTRIBUTING.md`](../../../skills/CONTRIBUTING.md). Community skills
come from a separate repository mounted as a submodule and are not indexed by
this site yet. Skills a user builds and saves inside the running application —
through the Skill Creator or the skill wizard — are rows in a database table,
not files in this repository at all; see [Where skills live](where-skills-live.md)
for how those two worlds relate. Whichever kind you're looking at, the promise
is the same: click through to the actual `SKILL.md`, in full, before you trust
what it produces.

## Next

- [Author your first skill](author-your-first-skill.md)
- [Your prompt files are already skills](your-prompt-files-are-skills.md)
- [Where skills live](where-skills-live.md)
