---
fixture: already-structured
skill: enhance-prompt
description: >
  Already-well-structured prompt (test-plan.md Scenario 2 / SKILL.md
  skip condition: over ~80 words with explicit format, audience, and
  scope instructions): expansion should be skipped or minimal.
synthetic: >
  Fully synthetic test prompt authored for DE-231. Not a real request,
  not legal advice, not attorney work product.
prompt: |
  Enhance the following prompt draft before it is submitted:
skill_inputs:
  raw_input: >
    Acting as in-house commercial counsel for the customer, review the
    attached SaaS master subscription agreement from the customer's
    perspective under Delaware law. Produce a structured markdown
    report with sections for critical, material, and minor issues, a
    missing-protections list, and recommended next steps. Cite the
    specific section number for every finding, quote the operative
    language for critical findings, and propose redline language for
    each critical and material issue. Exclude pricing commentary and
    do not opine on enforceability; flag enforceability questions for
    escalation to outside counsel. The audience is our general counsel,
    who wants a two-page maximum read.
---

Acting as in-house commercial counsel for the customer, review the
attached SaaS master subscription agreement from the customer's
perspective under Delaware law. Produce a structured markdown report
with sections for critical, material, and minor issues, a
missing-protections list, and recommended next steps. Cite the specific
section number for every finding, quote the operative language for
critical findings, and propose redline language for each critical and
material issue. Exclude pricing commentary and do not opine on
enforceability; flag enforceability questions for escalation to outside
counsel. The audience is our general counsel, who wants a two-page
maximum read.
