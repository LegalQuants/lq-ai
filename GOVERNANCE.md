# LQ.AI Governance

> **Status:** Proposed. This document codifies how the LQ.AI project is governed
> during its current phase. It was drafted by houfu (Ang Hou Fu) following the
> committee call of 2026-07-19 and is adopted when the PR introducing it is approved
> by the committee. The decision record behind it is
> [ADR 0022](docs/adr/0022-committee-governance-and-meeting-records.md).

## Background

LQ.AI began as a founder-led project. It has grown into a community effort carried
by a committee of practicing lawyers and legal engineers. This document records how
that committee makes decisions, so that contributors can see not just *what* was
decided (the ADRs, the PRD) but *how* decisions get made and by whom.

Transparency is the project's founding principle, and it applies to governance the
same way it applies to skills: the process that shapes the project is visible work
product.

## Roles

- **Founder.** Kevin Keller authored the project's guiding principles, initial
  architecture, and roadmap. The founder's documents remain canonical unless amended
  through the process below. The founder is welcome at any committee call.
- **Committee.** The group that steers the project between releases: sets priorities,
  decides scope questions, and appoints maintainers and review-committee members.
  Membership is currently by invitation of the existing committee.
- **Maintainers.** Hold write access to the repository; ack claims, triage issues,
  review and merge PRs, and keep CI healthy.
- **Review committee.** Maintainers and appointed members responsible for PR merge
  decisions, established at the committee call of 2026-06-28.
  [CONTRIBUTING.md](CONTRIBUTING.md) sets the merge threshold
  (one maintainer approval; two preferred for multi-subsystem changes).
  Volunteers apply through an existing member.
- **Contributors.** Anyone who opens an issue or PR. The contribution path is in
  [CONTRIBUTING.md](CONTRIBUTING.md); the skill-specific path (including
  practicing-attorney attestation) is in [skills/CONTRIBUTING.md](skills/CONTRIBUTING.md).

## How decisions are made

1. **Architectural and product decisions are ADR-first.** Before a significant issue
   or PR is accepted, the underlying architectural question is settled in a proposed
   ADR in [docs/adr/](docs/adr/), opened as a PR for community comment. PRs that
   implement an undecided architectural choice wait for their anchor ADR. (Agreed at
   the committee call of 2026-07-19.)
2. **Routine maintenance uses lazy consensus.** Dependency bumps, bug fixes with
   regression tests, and small self-explanatory hardening PRs need a maintainer
   review, not a committee decision.
3. **Scope, governance, and roadmap decisions belong to the committee**, discussed
   at the weekly call or asynchronously in a tracking issue, and recorded in the
   meeting minutes and — when structural — an ADR or PRD amendment.
4. **Security-sensitive paths** follow the stricter routing in
   [CLAUDE.md](CLAUDE.md#security-sensitive-paths) and
   [.github/CODEOWNERS](.github/CODEOWNERS); vulnerabilities follow
   [SECURITY.md](SECURITY.md), never public PRs.

## Meetings

- The committee holds a **weekly call on Sundays** (currently 2pm GMT, on Zoom).
- **Minutes are public.** Decisions, action items, and attendee lists are published
  as meeting records (see ADR 0022 for where they live). Raw transcripts and
  recordings are not published; the minutes are the record.
- **Async ratification:** committee members who miss a call may register agreement
  or objection on the posted minutes within 7 days. Silence after 7 days is assent
  to the recorded decisions.

## Claiming work

Roadmap items and deferred enhancements are claimed by opening a GitHub issue titled
with the item ID (e.g. "DE-202") and commenting "I'd like to take this". A maintainer
acts within about 7 days. Claims live as GitHub issues — not chat messages or
screenshots — so they are visible to anyone reading the repo. For anything XL or
architectural, open a discussion first so the boundary is agreed before anyone spends
a weekend.

## Amending this document

Governance changes are proposed as a PR to this file, announced at the weekly call,
and merged after committee approval under the async-ratification rule above.
