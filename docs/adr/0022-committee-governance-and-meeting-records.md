# ADR 0022 — Committee governance document and public meeting records

**Status:** Proposed
**Date:** 2026-07-20
**Owner:** Committee (action item from the 2026-07-19 weekly call)

## Context

The project has moved from founder-led to committee-carried. The
2026-07-19 committee call concluded that the primary bottleneck is
governance and decision-making structure, not technical capability, and
adopted an ADR-first workflow for architectural consensus.

The governance rules themselves, however, live nowhere durable: the
claim process, the review-committee mandate, the weekly-call cadence,
and the async-ratification practice exist only in Slack scrollback and
meeting memory. Two placement questions need deciding:

1. **Where do the governance rules live?** They are read by people
   deciding how to participate, not how to build — a different audience
   from the ADR series.
2. **Where do meeting records live?** The committee wants meetings and
   progress visible to the community, but material committed to this
   repo is pulled by everyone who clones it, and every minutes commit
   would pass through code-review ceremony (PRs, CODEOWNERS routing).

No prior ADR, PRD section, or DE entry decides either question.

## Decision

1. **Governance rules live in `GOVERNANCE.md` at the repo root** — the conventional
   root-level location alongside the community health files.
   It is a living document amended by PR with committee
   approval. The ADR series stays reserved for architectural and
   product decisions, keeping the ADR-first review gate legible.
3. **Meeting minutes are published in a separate `LegalQuants/lq-ai-community`
   repository** (to be created), linked from `GOVERNANCE.md`. One folder
   per meeting: `meetings/YYYY-MM-DD-<topic>/` containing `notes.md`
   (attendees, decisions, action items) and any shareable artifacts.
4. **Raw transcripts and recordings are not published.** They contain
   candid, unpolished discussion not spoken for the public record. The
   published minutes are the record; transcripts remain with the
   participants.
5. **Async ratification is the approval mechanism for minutes and
   governance changes:** committee members absent from a call may
   object on the posted record within 7 days; silence is assent.

## Alternatives considered

- **Record governance rules as ADRs in `docs/adr/`.** The "A" in ADR
  can read as "any decision" (the MADR convention), so this is not
  wrong — but it mixes participation rules into a series contributors
  consult for build decisions, and dilutes the ADR-first gate the
  committee just adopted. A single ADR (this one) recording the
  *adoption* of the governance process preserves the numbered audit
  trail without moving the rules themselves into the series.
- **Keep meeting minutes in this repo under `docs/meetings/`.** The
  byte cost is trivial (minutes are kilobytes of markdown), but every
  clone carries committee plumbing a contributor building the product
  never needs, and every minutes update passes through code-repo PR
  review and CODEOWNERS routing. Rejected on signal-to-noise, not size.
  This is also the pattern large committee-run projects converged away
  from: Kubernetes (`kubernetes/community`), Node.js (`nodejs/TSC`),
  and Rust (`rust-lang/compiler-team`) all keep governance records in
  satellite repos.
- **GitHub Discussions for minutes.** Zero clone weight and reactions
  give a natural async-ratification surface, but content is not
  version-controlled, is harder to cite from PRs and ADRs, and lives
  or dies with platform features. Retained as an optional announcement
  mirror, not the system of record.
- **The repo wiki.** A separate git tree, so no clone weight — but
  edits bypass review, it is poorly discoverable, and wikis rot.
  Rejected.
- **Publish transcripts alongside minutes.** Maximally transparent,
  but transcripts capture candid assessments and half-formed positions
  the speakers did not offer publicly; publishing them would chill the
  candor the calls depend on. Minutes-not-transcripts is the norm in
  the projects above. Rejected.

## Consequences

- `GOVERNANCE.md` lands at the repo root (this PR) and becomes the
  entry point for how the project is run; README gains a pointer in a
  follow-up.
- A `LegalQuants/lq-ai-community` repo needs creating (org-owner action),
  seeded with minutes from the four committee calls held to date
  (2026-06-28, 07-05, 07-12, 07-19) and the meeting-folder convention.
  Until it exists, minutes continue to be posted to the committee
  channel.
- The claims process, review-committee mandate, and async-ratification
  rule stop being oral tradition; new contributors can read how
  decisions are made without joining a call.
- The ADR series keeps a single governance entry (this ADR) rather
  than absorbing process documents, so ADR review remains an
  architecture gate.
- This ADR is Proposed until the committee approves the PR under the
  async-ratification rule it introduces.

---

*Drafted by houfu (Ang Hou Fu) from the 2026-06-28 through 2026-07-19
committee-call records; proposed for committee comment per the
ADR-first workflow adopted 2026-07-19.*
