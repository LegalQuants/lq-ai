---
title: The contribution board
description: The maintainer team's own curated list of short-cycle, mergeable contributions, read live from the repository.
audience: [contributor]
status: draft
sources:
  - docs/contribute/EASIEST-CONTRIBUTIONS.md
sidebar:
  order: 2
---

This is the maintainer team's own list of contributions where the foundation is already in the repository, the gap is named in writing, and the path to merge is short. Each row below is a **mini-PRD** — a scope, a verification checklist, and a contributor profile, decided in advance so you can judge whether it fits your weekend before you start. These are not "issues to be claimed" in the loose sense; they are decisions the maintainer team has already made and written down.

The board is included on this page, not copied onto it, so it is always the same list the maintainer team is working from. If the row you want has moved or closed since you last looked, this page is stale and [`docs/contribute/EASIEST-CONTRIBUTIONS.md`](../../contribute/EASIEST-CONTRIBUTIONS.md), the file the table below is included from, is not — the "checked against" stamp at the bottom of this page tells you which commit it was read at. Treat the linked mini-PRD itself, not this page's summary, as the working brief once you claim a row.

<!-- include: docs/contribute/EASIEST-CONTRIBUTIONS.md -->

## Which row fits you

One row — acceptance tests for the built-in skills — is written for a practicing attorney and read against real, anonymized documents rather than code. Two more read closer to a compliance, procurement, or AI-governance background than an engineering one: the Procurement-Readiness Pack (in-house counsel or a procurement analyst) and the NIST AI RMF mapping (an AI-governance or compliance professional). [The compliance and procurement on-ramp](compliance-professionals.md) covers what each of those two produces and where it lands in the repository. The remaining rows — the OWASP LLM Top 10 mapping, the OpenSSF Scorecard badges, the air-gap install verification test, the reverse-proxy and TLS recipes, and the community skill installer UI — assume an engineering background at S to M effort; [the engineering on-ramp](engineers.md) covers the build loop and the gates CI runs against any pull request you open from one of them.

Effort is marked S (under a day), M (a few days), or L (more than a week) — this list only carries S and M items by design; anything larger goes through a discussion first rather than sitting on a public board.

## Next

- [On-ramp for lawyers](lawyers.md)
- [On-ramp for compliance and procurement professionals](compliance-professionals.md)
- [On-ramp for engineers](engineers.md)
