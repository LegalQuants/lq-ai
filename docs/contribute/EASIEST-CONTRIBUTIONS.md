# Easiest Contributions

> A curated list of contributions where the foundation is already in source, the gaps are named in source, and the path to merge is short.

## What this is

LQ.AI maintains a small, deliberately-curated set of **mini-PRDs** for contributions where the underlying capability is already shipped, the missing piece is well-defined, and the path to merge is short. They are not "issues to be claimed" in the usual sense — they are decisions already made by the maintainer team, written down in advance: the scope, the verification criteria, the contributor profile, and the rough effort.

A practicing attorney can pick up a skill acceptance-test PR. A security engineer can pick up the OWASP LLM Top 10 mapping. An in-house counsel can pick up the Procurement-Readiness Pack. The mini-PRDs make the contract explicit before any work begins, so the contributor decides whether to spend a weekend on this with the same information the maintainer team has.

## Why we publish these explicitly

When the foundation is in source and the gaps are named in source, a contributor can verify what is being asked of them before they start. Every mini-PRD on this list points to specific files, specific endpoints, and a specific acceptance checklist. The reviewer can confirm "done" against the same checklist the contributor worked from.

That is also the structural posture of the project. The work product an operator's security or procurement team needs — an OWASP mapping, a SIG Lite response, an air-gap verification, an OpenSSF score — is only useful if the operator can independently verify each claim. We publish the gap, the rationale, and the verification criteria together because the verification criteria are part of the deliverable, not separate from it.

## The list

| # | Mini-PRD | Contributor profile | Effort | Foundation readiness |
|---|---|---|---|---|
| 1 | [Procurement-Readiness Pack](mini-prds/procurement-readiness-pack.md) | In-house counsel / procurement analyst | M | High |
| 2 | [OWASP LLM Top 10 mapping](mini-prds/owasp-llm-top10-mapping.md) | Security-aware engineer | S | High |
| 3 | [Acceptance tests for built-in skills](mini-prds/skill-acceptance-tests.md) | Practicing attorney | M (per skill) | High |
| 4 | [OpenSSF Scorecard + Best Practices badges](mini-prds/openssf-scorecard-and-badges.md) | Junior-to-mid engineer | S | High |
| 5 | [Air-gap install verification CI test](mini-prds/air-gap-install-verification.md) | Mid engineer w/ Docker networking | S-M | Medium-High |
| 6 | [NIST AI RMF 1.0 Profile mapping](mini-prds/nist-ai-rmf-profile.md) | AI-governance / compliance professional | M | High |
| 7 | [Reverse-proxy + TLS deployment recipes](mini-prds/reverse-proxy-tls-deployment-recipes.md) | Junior-to-mid DevOps | S | High |
| 8 | [Community skill installer (admin UI)](mini-prds/community-skill-installer-ui.md) | Mid-level engineer (Svelte + FastAPI) | M | High |

**Effort key:** S = under a day; M = a few days; L = more than a week.

**Which row fits you:** row 3 (acceptance tests for the built-in skills) is written for a
practicing attorney and read against real, anonymized documents rather than code. Rows 1
and 6 (Procurement-Readiness Pack, NIST AI RMF mapping) read closer to a compliance,
procurement, or AI-governance background than an engineering one. Rows 2, 4, 5, and 7
assume an engineering background at S-to-M effort — the OWASP LLM Top 10 mapping, the
OpenSSF Scorecard badges, the air-gap install verification test, and the reverse-proxy and
TLS recipes. Row 8, the community skill installer UI, is a mid-level Svelte + FastAPI
engineering item. This list only carries S and M items by design; anything larger goes
through a discussion first rather than sitting on a public board.

**Foundation readiness** reflects how much of the supporting code, documentation, or convention is already shipped. **High** means the contributor reads existing source, fills the gap, and submits the PR. **Medium-High** means one or two ancillary decisions are still open and the maintainer will resolve them during review.

## How to claim one

1. Open a GitHub issue with the mini-PRD's slug as the title (e.g., "owasp-llm-top10-mapping").
2. Comment "I'd like to take this." A maintainer responds within ~7 days.
3. Follow the "Where to start" section in the mini-PRD.
4. Submit a PR following [CONTRIBUTING.md](../../CONTRIBUTING.md) for the engineering process — DCO sign-off, imperative-mood commit messages, the PR template.
5. For skill content specifically, also follow [skills/CONTRIBUTING.md](../../skills/CONTRIBUTING.md) — the attestation step applies.

The mini-PRD's "Definition of merged" section is the contract. If the acceptance criteria are checked off and the substance review passes, the PR merges. If a question surfaces that the mini-PRD does not answer, raise it on the issue thread before doing the work; the maintainer team will resolve the ambiguity in writing rather than letting the PR review absorb it.

## What we are not asking for here

These mini-PRDs are scoped for short-cycle contributions where the foundation makes the path tractable. The full deferred-enhancement list is in [PRD §9](../PRD.md#9-deferred-enhancements-and-identified-future-work). Items there that are not in the mini-PRD list either require deeper maintainer context, depend on architectural decisions not yet made, or are larger than a single contributor can ship in a reasonable timeframe.

Examples of items intentionally **off** this list:

- New starter skills that touch novel practice areas — these need a maintainer collaboration upfront on scope and rubric design.
- The eval harness for the skill corpus — this depends on multi-judge grading infrastructure that has not been designed yet.
- Third-party penetration testing and adversarial-AI red-team engagements — the work is the vendor engagement, not the code.

If you want to pick up something not on this list, open a discussion first. The maintainer team will either expand the list (and write the mini-PRD with you) or explain what additional foundation needs to land first.

## Maintenance note

This list is curated. Items leave the list when they ship; items join the list when the foundation makes them tractable. Open an issue if you think something else belongs.

---

*Pack maintained alongside the PRD. Updates land as items ship or as the foundation closes new gaps.*
