---
title: Your prompt files are already skills
description: What has to change in an existing prompt file to make it a SKILL.md — mapped field by field.
audience: [author]
status: draft
sources:
  - docs/skill-authoring-guide.md
  - skills/nda-review/SKILL.md
sidebar:
  order: 4
---

If you already keep a text file of prompts you reuse — a standard NDA-review
instruction you paste into a chat, a checklist you retype every time a DPA
lands on your desk — you're closer to a skill than a blank page. The work is
mostly restructuring what you already have, not inventing new content.

| What you already have | What it becomes in `SKILL.md` |
|---|---|
| The prompt text itself | The body of `SKILL.md` — specifically the "Workflow" section: the step-by-step instructions the model follows. |
| A one-line note on when you use this prompt | `description` in frontmatter — one sentence, specific enough that it wouldn't also describe a different prompt you have. |
| The phrases you'd actually type to reach for it | `lq_ai.trigger_examples` — at least three, in your own words. |
| Any "first tell me X" step at the top of the prompt | `lq_ai.inputs.required` — the document or fact the workflow can't run without. |
| Any optional context you sometimes add ("assume the recipient perspective," "use the GDPR checklist") | `lq_ai.inputs.optional` — only where supplying it changes the substance of the output, not only its formatting. |
| Whatever you called it in your own filesystem or notes app | `name` (kebab-case) and `lq_ai.title` (the display name). |
| The shape you expect back — a memo, a checklist, a table | `output_format` — prefer the conventional `report`, `table`, `issues_list` or `redline`; the loader accepts any string and the M1 starter skills use a wider range (NDA Review ships `markdown`), but only `table` changes how the application renders the result. |
| The line where you'd stop and escalate to a colleague instead of trusting the output | "What this skill does not do" — an explicit section, not an implied boundary. |

What a prompt file usually lacks that a skill needs: a stated jurisdiction
(`lq_ai.jurisdiction`), an explicit "when this does NOT apply" section, and at
least one worked example showing the prompt run on a real input with the
output it produced. None of those are hard to add once you've named them —
they're the difference between a prompt that works for you because you know
its limits by memory, and a skill someone else can pick up and trust on the
same terms.

If your prompt has real legal substance in it — review criteria, severity
judgments, recommended language — treat it as skill content from the start:
the same conservative-posture conventions and the same attestation expectation
apply whether you wrote it from scratch or promoted it from a prompt file you'd
been using for months.

## Next

- [Author your first skill](author-your-first-skill.md)
- [What a skill is](what-a-skill-is.md)
- [The attestation bar](attestation.md)
