# Turn a saved prompt into a skill

Start with the prompt you already use. Give it a clear name and description, then add the required skill fields.

## Keep the context that matters

Explain the required inputs, expected output and limits. Add reference files when their contents belong in the AI request — the current app includes every file under a skill's `reference/` folder with the instructions: the loader picks up each one, and the gateway's prompt assembler (`gateway/app/skills/assembler.py`) appends it verbatim to the skill's prompt under a `## Reference: <path>` heading, whether or not the body mentions it. Budget prompt size and confidentiality on that basis; reference files are not lazily loaded ([Skill-Authoring Guide](../skill-authoring-guide.md)).

## Try it in the app

Check that the skill file is accepted, then run examples of the task. Getting the file format right is the first step; testing tells you whether the instructions work.

## Map the parts you already have

Put the prompt's steps into `SKILL.md`, then work through the rest field by field below: the short "when I use this" note becomes `description`, ordinary requests become `lq_ai.trigger_examples`, essential facts become `lq_ai.inputs.required`, and genuinely optional context becomes `lq_ai.inputs.optional`. Give it a stable name and a readable title. Specify the jurisdiction, the expected output, and a clear "when not to use this" section.

Field by field, against the format in the [Skill-Authoring Guide](../skill-authoring-guide.md):

| What you already have | What it becomes in `SKILL.md` |
|---|---|
| The prompt text itself | The body of `SKILL.md` — specifically the "Workflow" section: the step-by-step instructions the model follows. |
| A one-line note on when you use this prompt | `description` in frontmatter — one sentence, specific enough that it wouldn't also describe a different prompt you have. |
| The phrases you'd actually type to reach for it | `lq_ai.trigger_examples` — at least three, in your own words. |
| Any "first tell me X" step at the top of the prompt | `lq_ai.inputs.required` — the document or fact the workflow can't run without. |
| Any optional context you sometimes add ("assume the recipient perspective," "use the GDPR checklist") | `lq_ai.inputs.optional` — only where supplying it changes the substance of the output, not only its formatting. |
| Whatever you called it in your own filesystem or notes app | `name` (kebab-case) and `lq_ai.title` (the display name). |
| A stated legal system or regulatory regime the prompt assumes | `lq_ai.jurisdiction` — a free-form field; conventional values are `us`, `eu`, `regime-aware`, `global`/`agnostic`, or `other` (spelled out in the skill body). |
| The shape you expect back — a memo, a checklist, a table | `output_format` — prefer the conventional `report`, `table`, `issues_list` or `redline`; the loader accepts any string and the M1 starter skills use a wider range (NDA Review ships `markdown`), but only `table` changes how the application renders the result. |
| The line where you'd stop and escalate to a colleague instead of trusting the output | "What this skill does not do" — an explicit section, not an implied boundary. |

Most prompt files don't have a stated jurisdiction or an explicit "when this does NOT apply" section yet — they're not hard to add once you've named them, and they're the difference between a prompt that works for you because you know its limits by memory, and a skill someone else can pick up and trust on the same terms.

## Be precise about output formats

Describe the result you want in `output_format`, but do not assume the label creates an export or editor feature. Setting `output_format: table` selects the Tabular Review workflow; labels such as `redline` describe a convention (Word tracked-changes-style output) but do not on their own produce Word tracked changes — the frontmatter parser treats the field as a free-form string, and only `table` is load-bearing (`api/app/skills/schema.py`).

If your prompt has real legal substance in it — review criteria, severity judgments, recommended language — treat it as skill content from the start: the same [conservative-posture conventions](../skill-authoring-guide.md#conservative-posture) and the same [attestation](../../skills/CONTRIBUTING.md#3-attest) expectation apply whether you wrote it from scratch or promoted it from a prompt file you'd been using for months. Add a worked example and the same legal-content review you would require for a newly written skill.

For the full walkthrough of turning that promoted prompt into a merged skill, see [Author your first skill](author-your-first-skill.md).
