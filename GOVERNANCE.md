# LQ.AI Governance

> **Status:** Adopted. This document codifies how the LQ.AI project is governed
> during its current phase. It was drafted by houfu (Ang Hou Fu) following the
> committee call of 2026-07-19 and was adopted alongside
> [ADR 0022](docs/adr/0022-committee-governance-and-meeting-records.md), which the
> committee accepted at the 2026-07-26 weekly call (merged as PR #311).

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
- **Trusted reviewers.** Contributors granted **review authority without merge authority**,
  appointed by the committee on a maintainer's nomination from demonstrated review
  contributions. The rung exists so that review capacity can grow before write access is
  granted, and it is **advertised openly** rather than filled by invitation. Adopted by
  [ADR 0034](docs/adr/0034-review-capacity-and-reviewer-roles.md).
- **Contributors.** Anyone who opens an issue or PR. The contribution path is in
  [CONTRIBUTING.md](CONTRIBUTING.md); the skill-specific path (including
  practicing-attorney attestation) is in [skills/CONTRIBUTING.md](skills/CONTRIBUTING.md).

## Becoming a maintainer

Review capacity — not authorship — is the project's binding constraint, and the path to
merge authority is published so that it can be walked deliberately. The committee promotes a
trusted reviewer to maintainer on three criteria:

1. **Sustained review quality over at least one quarter** — reviews that catch real defects,
   not approvals.
2. **Security-path familiarity** — demonstrated competence on `gateway/`, authentication,
   authorization, audit logging or cryptographic changes, because merge authority without it
   cannot discharge the routing in [.github/CODEOWNERS](.github/CODEOWNERS).
3. **A committee vote**, recorded in the minutes under the async-ratification rule above.

Openings at both rungs are advertised; interest is welcome from anyone already reviewing.
See [ADR 0034](docs/adr/0034-review-capacity-and-reviewer-roles.md) for the reasoning, and
[ADR 0030](docs/adr/0030-pacing-1.0-preconditions-and-named-trains.md) for why the second
maintainer is a precondition for dating 1.0.

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
- **Internal review and async ratification:** internal notes and the proposed public
  version circulate internally after the meeting with an explicit deadline seven days
  from circulation. All committee members, including those who missed the call, may
  raise corrections or objections. If no objections are raised by the deadline, record
  approval through the no-objection process (silence is assent). Resolve outstanding
  objections before publication; the passage of the deadline alone is not evidence
  that no objections were raised.
- **Publication after approval:** Joel Kaufmann publishes the approved public version
  to [lq-ai-community](https://github.com/LegalQuants/lq-ai-community) as time permits.
  Public notes separately record internal circulation, the objection deadline, approval
  date and basis, and GitHub publication. Publication does not restart the seven-day
  window. Internal notes, discussion, and private review exchanges remain private.
- **Corrections:** material changes to recorded decisions, attendee identification, or
  publishable content require recirculation and a fresh seven-day window. Typographical
  corrections do not restart it. Later corrections use issues or follow-up PRs and dated
  entries, preserving the historical record.
- **Publication safeguards:** public discussion and action ownership are anonymized;
  attendee lists are confirmed by another attendee or the committee, with the reviewer
  or approving body recorded. Exclude meeting access details, credentials, transcripts,
  recordings, and confidential, privileged, or client-identifying material. Review
  statements about identifiable individuals for accuracy and neutral phrasing.

### Transition clarification (2026-10-13)

The team approved the proposal in
[lq-ai-community issue #3](https://github.com/LegalQuants/lq-ai-community/issues/3).
**Proposed effective-date rule for review:** no calendar effective date was specified.
Apply the clarified process to records first circulated internally on or after both
coordinated PRs (this governance amendment and the community documentation update) merge.
Until then, and for records already in review at that point, retain the previous
seven-day window beginning at public posting. Record the actual effective date in a dated
follow-up once both merges occur.

Previously published records retain their posting dates and public objection deadlines,
including September 27, 2026 for the August 30, September 6, and September 13 notes, and
October 15, 2026 for the September 20 notes. Do not infer historical circulation or review
dates, reopen or shorten existing windows, or infer ratification solely from an elapsed
deadline. Add confirmed information as dated clarifications without silently rewriting
prior entries. See the
[community transition record](https://github.com/LegalQuants/lq-ai-community/blob/main/meetings/README.md#transition-clarification-2026-10-13).

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
