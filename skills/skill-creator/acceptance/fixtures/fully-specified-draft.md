---
fixture: fully-specified-draft
skill: skill-creator
description: >
  Fully front-loaded skill specification with a worked example and an
  explicit workflow confirmation (test-plan.md Scenario 1 completion
  state): the skill has everything it needs to draft the SKILL.md
  artifact in this turn.
synthetic: >
  Fully synthetic test request authored for DE-231. Not a real request,
  not legal advice, not attorney work product.
prompt: |
  I have already worked through the design of the skill I want, below,
  including a worked example. I confirm this workflow is what I want —
  please draft the SKILL.md now rather than asking further questions;
  apply sensible defaults for anything minor I left out.
skill_inputs: {}
---

Skill name: force-majeure-clause-check.

Purpose: review a single force majeure clause that the user pastes in,
and tell them (a) which standard elements are present or missing —
covered events list, causation requirement, notice obligation,
mitigation duty, termination trigger for extended events, payment
carve-out — and (b) whether any wording is unusually broad or narrow.

Trigger phrasings users would type: "check this force majeure clause",
"is this force majeure clause standard", "review our FM clause".

Required input: the clause text (pasted). Optional inputs: perspective
("customer" or "supplier"; default neutral with a note) and
governing_law (free text; if absent, general US commercial assumptions
noted).

Output format: markdown. Structure: a one-paragraph bottom line; a
present/missing element table; a short unusual-wording section with
severity tags Critical/Material/Minor; recommended next steps; and an
items-requiring-human-judgment section that defers enforceability
questions. Conservative posture: no enforceability opinions, no
invented authorities, include a "what this skill does not do" note.

Edge cases: if the paste is a whole contract rather than one clause,
ask the user to point at the clause; if the clause is not in English,
flag and ask before proceeding.

Worked example — input clause: "Neither party shall be liable for any
failure or delay resulting from events beyond its reasonable control,
including acts of God, war, terrorism, epidemics, labor disputes, or
governmental action, provided the affected party gives notice within
ten (10) days and uses commercially reasonable efforts to resume
performance. If such event continues for more than ninety (90) days,
either party may terminate the affected order upon written notice.
Nothing herein excuses any obligation to pay amounts due." Expected
output for that example: bottom line says the clause is broadly
market-standard; element table marks all six elements present; unusual
wording section notes "labor disputes" is broader than many
supplier-side templates (Minor from a neutral read); next steps say
sign-off is reasonable; human-judgment section defers any
jurisdiction-specific reading of "governmental action".

Self-improvement: false.
