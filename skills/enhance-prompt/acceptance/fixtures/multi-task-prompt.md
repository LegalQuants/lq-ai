---
fixture: multi-task-prompt
skill: enhance-prompt
description: >
  Multi-task prompt (test-plan.md Scenario 3): review-then-rewrite must
  be surfaced as a sequence (or a clarification), never silently
  collapsed into one task.
synthetic: >
  Fully synthetic test prompt authored for DE-231. Not a real request,
  not legal advice, not attorney work product.
prompt: |
  Enhance the following prompt draft before it is submitted:
skill_inputs:
  raw_input: >
    review this MSA and also rewrite the indemnification section so it
    protects us better
---

review this MSA and also rewrite the indemnification section so it
protects us better
