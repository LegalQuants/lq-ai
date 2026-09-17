---
title: Contribute to LQ.AI
description: Two contribution tracks for this repository's own code and first-party skills — engineering and legal substance — that share a repository but not a review path.
audience: [contributor]
status: draft
sources:
  - CONTRIBUTING.md
  - skills/CONTRIBUTING.md
sidebar:
  order: 1
---

LQ.AI takes contributions from two different kinds of work, and the two run through different review paths in the same repository.

**Engineering** — code, infrastructure, deployment recipes, and general project documentation — is reviewed by maintainers under the ordinary pull-request process. **Legal substance** — the skills that do the actual review, drafting, and analysis work — carries an attestation and a practicing-attorney review, because a skill that produces a wrong answer affects real legal work. Neither track is a lesser front door: a lawyer with no engineering background and an engineer with no legal background are both first-class contributors, on their own track, and a single pull request rarely needs both hats at once.

The split exists because the two kinds of review answer different questions. Maintainer review on the engineering track asks whether the change does what it claims, is tested, and follows the project's conventions. Attorney review on the legal-substance track asks whether the skill's patterns, severity calibrations, and recommended language reflect reasonable practice — a question an engineer reviewer, however careful, is not positioned to answer alone. Both tracks still land in the same pull-request process and both are gated on the same Code of Conduct.

Start with whichever describes what you want to work on. If neither is obvious yet, [the contribution board](board.md) lists specific, scoped items with an effort estimate and a contributor profile attached to each — several fit a first-time contributor with no prior context on the codebase.

## The engineering track

The section below is included live from [`CONTRIBUTING.md`](../../../CONTRIBUTING.md):

<!-- include: CONTRIBUTING.md from="## What to work on" to="## Pull request process" -->

## The legal-substance track

Skills carry a higher bar than code, and the project is explicit about why, in [`skills/CONTRIBUTING.md`](../../../skills/CONTRIBUTING.md):

<!-- include: skills/CONTRIBUTING.md from="## Why skill contribution has a higher bar" to="## What skills look like" -->

The five steps — claim, draft, attest, review, merge — are unchanged whether a human or a coding agent drafts the skill. Agents do not attest; the human contributor is always the attesting party.

## Next

- [On-ramp for lawyers](lawyers.md)
- [On-ramp for engineers](engineers.md)
- [On-ramp for compliance and procurement professionals](compliance-professionals.md)
- [Point a coding agent at the repository](coding-agents.md)
