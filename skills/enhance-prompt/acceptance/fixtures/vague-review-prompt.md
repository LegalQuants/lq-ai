---
fixture: vague-review-prompt
skill: enhance-prompt
description: >
  Short-and-vague prompt (test-plan.md Scenario 1): the skill should
  expand it with role, scope, output-format, and citation elements and
  emit the structured YAML object with all mandated keys.
synthetic: >
  Fully synthetic test prompt authored for DE-231. Not a real request,
  not legal advice, not attorney work product.
prompt: |
  Enhance the following prompt draft before it is submitted:
skill_inputs:
  raw_input: review this vendor NDA and tell me if we can sign it
---

review this vendor NDA and tell me if we can sign it
