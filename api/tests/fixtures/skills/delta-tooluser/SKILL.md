---
name: delta-tooluser
description: A synthetic skill used to test C5 tool_usage surfacing; not for production use.
lq_ai:
  title: Delta Tool-User Skill
  version: 1.0.0
  author: LQ.AI tests
  tags: [test, fixture, delta]
  jurisdiction: agnostic
  output_format: markdown
  minimum_inference_tier: 2
  trigger_examples:
    - "use the delta tool-user skill"
    - "run delta"
  inputs:
    required:
      - name: query
        type: text
        description: A synthetic required input.
  tool_usage: [courtlistener]
  use_organization_profile: false
  self_improvement: false
---

# Delta Tool-User Skill

This is a synthetic skill used to exercise the C5 tool_usage surfacing path. It declares
a dependency on the `courtlistener` connector. It contains no legal substance and must
not be used in production.

## Workflow

1. Read `query`.
2. Return a synthetic result.
