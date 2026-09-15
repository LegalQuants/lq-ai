---
title: Threat model
description: STRIDE-by-component threats and mitigations for LQ.AI's five production services, and the registers-of-restraint catalog that extends the picture to autonomous work.
audience: [evaluator, operator]
status: draft
sources:
  - docs/security/threat-model.md
  - docs/security/boundary-registers.md
sidebar:
  order: 3
---

If your security team asked for one document, this is it — the trust boundaries LQ.AI draws
between its own services, between the deployment and the LLM provider, and between the deployment
and your identity provider, with a named threat and a named mitigation for every component and
every STRIDE category that applies. The source below is summary-level by its own admission:
detailed design intent lives in the PRD and the ADR series it cites, but every threat/mitigation
pair here is specific enough to verify against the file paths it names.

<!-- include: docs/security/threat-model.md -->

## Beyond STRIDE — restraining autonomous work

The STRIDE table above covers the five production services as they exist today. It does not cover
a separate question that only applies once a system acts without a human reading every output: what
stops an agent from overspending, running forever, or reaching for a tool outside its current step?
[`docs/security/boundary-registers.md`](../../security/boundary-registers.md) documents this as a
six-register catalog (adopted from a named external framework, not invented here) — three registers
for *how* a restraint is enforced (prompt-and-workflow, capability/tool-grant, code) and three for
*what else* needs restraining once autonomy exists (economic, temporal, contextual). As of the
checked commit the honest count is R1 (prompt-and-workflow) fully, R2 (capability/tool-grant)
fully in an adapted form via the inference-tier floor, R3 (code) partial, and R4, R5 and R6
shipped for the Autonomous Layer — the per-session cost cap, the external halt plus idle
watchdog, and phase-gated tool grants, all enforced at one chokepoint in
`api/app/autonomous/guard.py`. R3's gap is the closed-intent-enum-plus-audit-log retrofit
tracked as DE-292 (Playbook executor) and DE-294 (cross-agent handoff). That document
also names a seventh, orthogonal boundary — the Inference Tier model — which restrains *where* data
goes during inference rather than what the model may decide, spend, run, or touch; it is covered
from a data-flow angle on [What leaves my deployment](what-leaves-my-deployment.md) and in full
in the boundary-registers document itself.

## Next

- [What leaves my deployment](what-leaves-my-deployment.md) — the Inference Tier boundary this page's STRIDE table cross-references.
- [Anonymization](anonymization.md) — the mitigation named against gateway info-disclosure threats.
- [Audit & evidence](audit-and-evidence.md) — the mitigation named against every component's repudiation threat.
