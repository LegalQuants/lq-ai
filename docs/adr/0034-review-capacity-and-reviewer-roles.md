# ADR 0034 — Review capacity: the trusted-reviewer rung, maintainer promotion, the attorney pool, and an honest review SLA

**Status:** Proposed (2026-09-09; tabled for decision at the LQAI Committee weekly call of
2026-09-13)
**Date:** 2026-09-09
**Owner:** Maintainer team (houfu)
**Related:** [ADR 0022 — committee governance and meeting records](0022-committee-governance-and-meeting-records.md),
[ADR 0030 — pacing 1.0](0030-pacing-1.0-preconditions-and-named-trains.md),
[ADR 0029 D4](0029-definition-of-1.0.md),
[GOVERNANCE.md](../../GOVERNANCE.md), [CONTRIBUTING.md](../../CONTRIBUTING.md),
[skills/CONTRIBUTING.md](../../skills/CONTRIBUTING.md), [.github/CODEOWNERS](../../.github/CODEOWNERS)

---

## Context

The member survey's clearest structural finding was that **review capacity, not authorship, is
the binding constraint**. Five of nine ballots said no 1.0 date should be set until it is
addressed; [ADR 0030](0030-pacing-1.0-preconditions-and-named-trains.md) turned that into three
preconditions. This ADR is the machinery that makes those preconditions reachable. Without it,
ADR 0030's checkpoint has nothing to measure and nothing to measure *against*.

The survey also produced the raw material: **2 definite and 3 possible contributors**, 4
indications toward attorney review or attestation (3 confirmed), 2 toward engineering review, 2
willing to claim work, 4 willing to champion an area, and two confirmed champion openings. The
people exist. What does not exist is a rung for them to stand on.

Three concrete defects block that, all of them cases of the project documenting a practice it does
not have. They are stated plainly because ADR 0029's operating principle — every promise the
documentation makes is enforced or verifiable — applies to the governance documents too.

**Defect 1 — there is no rung below maintainer.** GOVERNANCE.md's roles run Founder → Committee →
Maintainers → Review committee → Contributors. Someone who reviews well has nowhere to be
recognized short of write access, so the project cannot grow reviewers incrementally, and
ADR 0030's precondition P1 has no pipeline feeding it.

**Defect 2 — the review SLA is published but unmet.** CONTRIBUTING.md promises first review within
~5 business days (§ pull request process, and again under reviewer expectations: initial review
within 5 business days, follow-up within 2). Observed reality is a month-old unreviewed queue.
Both places also route an overdue PR to `#contributors` on **Discord — a server that was never
stood up** (issue #490); `skills/CONTRIBUTING.md` points at `#skill-authors` on the same
non-existent server. A contributor following the documented escalation path reaches nothing.

**Defect 3 — CODEOWNERS is inert, in two independent ways.** It routes to
`@legalquants/maintainers`, `@legalquants/security`, `@legalquants/counsel` and
`@legalquants/practicing-attorneys`. **None of those teams exists** — the org has
`lq-ai-maintainers` and `lq-ai-committee`. And the `main` ruleset has
`require_code_owner_review: false` with `required_approving_review_count: 0`, so even correct
entries would not hold anything. CLAUDE.md tells contributors their security-path PR is
"auto-routed to security reviewers and held until they approve." Today it is neither routed nor
held.

Defect 3 is the most serious of the three: it is a **security promise** that does not hold, and
[ADR 0033](0033-document-pipeline-honesty-and-ocr.md) is about to send gateway changes down that
exact path.

---

## Decision

This follows the **adoption-ADR pattern of [ADR 0022](0022-committee-governance-and-meeting-records.md)**:
the rules live in the governance documents, and this ADR records their adoption and the reasoning.
The normative text lands in GOVERNANCE.md, CONTRIBUTING.md, skills/CONTRIBUTING.md and CODEOWNERS
in this ADR's acceptance PR.

### 1. A trusted-reviewer rung on the review committee

GOVERNANCE.md gains **trusted reviewer**: review authority, no merge authority. Appointed by the
committee on a maintainer's nomination, from demonstrated review contributions. The rung is
**advertised openly** rather than filled by invitation — the survey's willing reviewers cannot
volunteer for a role that is not published.

### 2. Published criteria for promotion to maintainer

A trusted reviewer is promoted to maintainer by committee vote on three criteria:

- **Sustained review quality over ≥ 1 quarter** — reviews that catch real defects, not approvals.
- **Security-path familiarity** — demonstrated competence on `gateway/`, auth, audit logging or
  crypto changes, because merge authority without it cannot discharge the CODEOWNERS routing.
- **A committee vote**, recorded in the minutes under the ADR 0022 ratification rule.

Publishing the criteria is the point. ADR 0030's precondition P1 measures a *second maintainer
with merge and security-review authority active for ≥ 1 quarter*; a path that exists only in the
committee's head cannot produce one on a schedule.

### 3. The attorney-reviewer pool, and a lighter acceptance-run role

`skills/CONTRIBUTING.md` today defines the practicing-attorney reviewer's role but names no pool
to assign from, and says reviewers "will be assigned by maintainers" without saying who they are.
It gains:

- **The pool** — how to join, and what joining commits you to.
- **Expected time per engagement**, stated honestly, so an indication of interest can become a
  commitment someone can plan around.
- **A distinction between two different asks**, which the current document conflates:
  - an **attestation review** — substantive sign-off on a skill's legal content, the heavier role;
  - a **D4 acceptance run** — running a starter skill against a real document corpus and recording
    what it did. This is materially lighter, needs no attestation, and is the [ADR 0029](0029-definition-of-1.0.md)
    D4 gate's critical path.

Separating them matters because D4 is the longest-lead gate row and the survey's 4 attorney
indications are far more likely to convert against the lighter ask.

### 4. An honest review SLA, published and measured

CONTRIBUTING.md's SLA is replaced with one the project can meet and does measure:

- A **first-response target** — the maintainer team's stated aim, with the current measured median
  published alongside it, refreshed at the committee's checkpoints.
- The **weekly review-slots practice**: a recurring block in which the open queue is worked in a
  published priority order (ratification docs → gate PRs → volunteer follow-ups and D4 →
  everything else).
- **Escalation that exists**: the Discord references in CONTRIBUTING.md and skills/CONTRIBUTING.md
  are removed in favour of GitHub Discussions and pinging a maintainer on the PR, closing #490.

A published target with a published measurement is honest whether or not the number is good.
A published target alone, as today, is the failure mode ADR 0029 was written against — and it is
the metric ADR 0030's precondition P3 depends on.

### 5. CODEOWNERS routes to teams that exist, and the routing is enforced

- **Every entry points at a real team.** `@LegalQuants/lq-ai-maintainers` is the only team that
  exists today, so it is what the file names. Specialist routing (`security`, `counsel`,
  `practicing-attorneys`) returns **when those teams are created and staffed** — the file records
  the intent in comments rather than routing to a void.
- **The `main` ruleset is changed** to `require_code_owner_review: true` with
  `required_approving_review_count: 1`, so that CODEOWNERS routing actually holds a PR. This is a
  repository-settings change, not a code change; it is an action item on this ADR's acceptance,
  recorded here so it cannot be quietly skipped.
- Until a security team exists, a `gateway/` change is held for **maintainer review with the
  security-path checklist applied** — the honest version of the current claim, rather than the
  stronger claim CLAUDE.md makes today. CLAUDE.md's wording is corrected to match.

### 6. The principles-as-tests / review-bot proposal proceeds as a proposal

The survey's candidate c16 (1 for 1.0 · 5 post-1.0) is the one candidate aimed directly at the
review constraint. It proceeds as a **proposal issue**, not an ADR and not a gate row — the
constraint is real, but automating review before there are reviewers solves the wrong half.

---

## Consequences

- **GOVERNANCE.md**: the trusted-reviewer rung, the promotion criteria, and a note that review
  capacity is a tracked constraint.
- **CONTRIBUTING.md**: the honest SLA, the review-slots practice, and no Discord.
- **skills/CONTRIBUTING.md**: the attorney pool, the time expectation, and the
  attestation-vs-acceptance-run distinction. No Discord.
- **.github/CODEOWNERS**: real team slugs; intent for specialist teams kept in comments.
- **CLAUDE.md**: the security-routing sentence matches what is enforced.
- **A repository-settings action item**: enable code-owner review and require one approval on
  `main`. This ADR is not fully discharged until it is done.
- **ADR 0030 becomes measurable.** P1 gains a pipeline, P2 gains a pool, P3 gains a published
  number. That is the whole point of this ADR: it is the precondition machinery, and it is on the
  critical path for everything the trains promise.

## Alternatives considered

- **Promote a second maintainer directly, without a rung** — rejected: it is what the project has
  tried, and the bus factor is still 1 with merge-plus-security authority. A rung lets someone
  demonstrate the security-path competence the promotion criteria require, before the vote.
- **Keep the 5-business-day SLA and try harder** — rejected: the promise has been in
  CONTRIBUTING.md throughout the period that produced a month-old queue. Restating it changes
  nothing; publishing the measured median creates the pressure the promise was supposed to.
- **Delete the SLA entirely** — rejected: contributors need to know what to expect, and ADR 0030's
  P3 needs something to measure against.
- **Create the four missing GitHub teams now and keep CODEOWNERS as-is** — rejected as the primary
  fix: a team with no members routes as effectively as a team that does not exist, and three of
  the four have no one to put in them. The teams return when they are staffed.
- **Leave the ruleset alone and rely on maintainer discipline** — rejected: it is exactly the
  "asserted, not enforced" pattern ADR 0029 exists to close, and it is asserted about the security
  boundary.

## Explicitly not decided

- **Who the first trusted reviewers are** — nominations follow adoption; the survey's volunteers
  are approached individually, with consent before any public naming.
- **The numeric first-response target** — set with the first published measurement rather than
  guessed now, so the number means something.
- **Whether the committee also wants a separate security-reviewer role** — revisit when there is
  more than one candidate for it.
