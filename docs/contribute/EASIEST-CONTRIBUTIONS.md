# Find something to work on

Use the current issue board to find a task and see whether someone is already working on it.

LQ.AI keeps a small, curated set of **mini-PRDs**: contributions where the underlying capability already ships, the missing piece is written down, and the path to merge is short. Each one names the scope, the acceptance criteria, and the contributor profile in advance, so you can judge whether it fits your weekend with the same information the maintainer team has. Every mini-PRD points to specific files, endpoints, and an acceptance checklist, so you can verify what's being asked before you start — and the reviewer checks "done" against that same checklist.

## Make it easy to review

Explain the problem, what you changed, and how you checked it. For a documentation correction, include the original wording and the code or behavior it should describe.

When you submit, follow [CONTRIBUTING.md](../../CONTRIBUTING.md) for the engineering process — DCO sign-off (`git commit -s`), imperative-mood commit messages, and the PR template. For skill content specifically, also follow [skills/CONTRIBUTING.md](../../skills/CONTRIBUTING.md); the attestation step applies there.

## Check the current status

Priorities and assignments change, so confirm a row is still open before you start:

1. Open a GitHub issue with the mini-PRD's slug as the title (for example, "owasp-llm-top10-mapping").
2. Comment "I'd like to take this." A maintainer responds within ~7 days.

## Read the task brief first

Each row in the list below links to a mini-PRD under `docs/contribute/mini-prds/`. Read it before you start — its "Where to start" section, not this page's summary, is the working brief once you claim a row.

The mini-PRD's "Definition of merged" section is the contract. If the acceptance criteria are checked off and the substance review passes, the PR merges. If a question surfaces that the mini-PRD doesn't answer, raise it on the issue thread before doing the work; the maintainer team will resolve the ambiguity in writing rather than letting the PR review absorb it.

### The list

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

**Foundation readiness** reflects how much of the supporting code, documentation, or convention is already shipped. **High** means you read existing source, fill the gap, and submit the PR. **Medium-High** means one or two ancillary decisions are still open and the maintainer resolves them during review.

## What we are not asking for here

These mini-PRDs are scoped for short-cycle work where the foundation makes the path tractable. The full deferred-enhancement list is in [PRD §9](../PRD.md#9-deferred-enhancements-and-identified-future-work); items there that aren't in the mini-PRD list either need deeper maintainer context, depend on architectural decisions not yet made, or are larger than a single contributor can ship in a reasonable timeframe.

Examples of items intentionally **off** this list:

- New starter skills that touch novel practice areas — these need a maintainer collaboration upfront on scope and rubric design.
- The eval harness for the skill corpus — this depends on multi-judge grading infrastructure that has not been designed yet.
- Third-party penetration testing and adversarial-AI red-team engagements — the work is the vendor engagement, not the code.

If you want to pick up something not on this list, open a discussion first. The maintainer team will either expand the list (and write the mini-PRD with you) or explain what additional foundation needs to land first.

## Maintenance note

This list is curated. Items leave when they ship; items join when the foundation makes them tractable. Open an issue if you think something else belongs.

---

*Pack maintained alongside the PRD. Updates land as items ship or as the foundation closes new gaps.*
