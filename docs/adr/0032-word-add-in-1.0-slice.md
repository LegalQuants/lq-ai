# ADR 0032 — The Word add-in 1.0 slice: scope, the DE-287 collision, and document-representation sequencing

**Status:** Proposed (2026-09-09; opened for comment, not for decision at the 2026-09-13 call)
**Date:** 2026-09-09
**Owner:** Maintainer team (houfu)
**Related:** [ADR 0029 F3](0029-definition-of-1.0.md),
[ADR 0017 — DOCX ingest via Pandoc](0017-docx-ingest-via-pandoc.md),
[docs/word-addin.md](../word-addin.md),
[PRD §9 DE-287](../PRD.md#9-deferred-enhancements-and-identified-future-work),
[HONEST-STATE §4.3](../HONEST-STATE.md)

---

## Context

[ADR 0029](0029-definition-of-1.0.md) F3 puts a Word add-in slice in the 1.0 gate: run a skill on
the selection or the document, get tracked-changes redlines back. The survey kept the row **5–2**
but produced **no consensus on its scope** — 2 thinner · 1 as-proposed · 2 wider · 4 blank — and
the most useful comment on it was "make the slice concrete before committing."

It is also the only gate row with **no PR and no owner**, at an estimated 16–22 build + 6–9 review
person-days. And it is contested territory: three different things currently claim the Word
surface.

1. **PR #314** — document-grounded in-Word chat, +41k lines, from a community contributor.
2. **The downstream fork's `word-add-in-surfaces` branch** — a different take on the same tabs.
3. **The F3 slice itself** — skills-on-selection with redlines, which is neither of the above.

Every review cycle spent on any one of these before the lane is chosen is a cycle spent against a
constraint the project does not have to spare. This ADR opens for comment rather than decision:
the collision needs the contributor's and the fork's voices in the thread, not a committee vote
taken without them.

---

## Decision

### 1. The slice stays as proposed

Run a skill on the selection or the whole document; get **tracked-changes redlines** written back.
In-Word chat, playbook execution and the tier badge remain **post-1.0**. The add-in's remaining
tabs keep their deep-link cards, labeled as pointers rather than features — which is what
HONEST-STATE §4.3 already says about them.

The scope vote produced no consensus, so the proposal is the default rather than the winner. The
reasoning for holding it: redlines are the one thing a lawyer cannot get from the web app by
pasting text, and in-Word chat is the one thing they can.

### 2. The collision is decided before more review is spent

The canonical lane for the Word surface is chosen — #314, the fork's branch, or the slice — and
the choice is recorded on this ADR **before** further review cycles go into any of them. The
decision is made with the #314 contributor and the fork in the thread. Whichever lane wins, the
other two get an explicit disposition (adopt-with-conditions, close with a pointer, or park), not
silence.

This is a process commitment, and it is the reason this ADR exists separately from ADR 0029.

### 3. The backend contract is designed for a future document layer

The slice's backend is a **skill-execute endpoint returning structured redlines** — roughly a
third of the slice's cost, and the part that outlives whichever front-end lane wins. It is
designed so that a future document-representation / intermediate-representation layer can sit
underneath it without a breaking change, per the survey comment asking to "prepare the Word path
for a future representation layer even if chat ships first."

The tracked-changes **write-back dependency** is evaluated against the project's SBOM bar
(CLAUDE.md: a new dependency needs to justify its supply-chain entry) as part of this work, not
after it.

### 4. The ADR 0029 fallback applies

If the slice is unowned when the *Candidate* train opens, the add-in is labeled **experimental**
and 1.0 tags without it. This is permitted by ADR 0029's operating principle — a surface may be
incomplete if it is labeled — and it is the worse outcome, not the plan.

---

## Consequences

- ADR 0029's F3 wording is read subject to this ADR for scope.
- DE-287 is updated to record the slice boundary and the three-lane collision.
- `docs/word-addin.md` gains the slice's scope and the redline contract once decision 2 lands.
- An Office.js champion opening is advertised; this is the gate row most likely to be carried by
  someone outside the maintainer team, and the one where that help is worth the most.
- **Nothing in the Word lane is reviewed at depth until decision 2 is made.** Said plainly so the
  #314 contributor is not left reading silence as neglect.

## Alternatives considered

- **A thinner slice** (skills on selection, plain-text output, no redlines) — rejected: it is the
  web app with extra steps, and it would not justify the add-in's own security posture
  (unsigned-manifest install path, OAuth handling) for what it delivers.
- **A wider slice** (chat + playbooks + redlines) — rejected: 2 ballots wanted it, but it is
  multiples of the estimate on the one gate row with no owner, and it would make F3 the item that
  sets the 1.0 date.
- **Adopt PR #314 as the F3 answer** — not rejected, but not assumed: it is a different product
  (chat, not redlines) at +41k lines. If decision 2 picks it, F3's definition changes with it and
  ADR 0029 is amended accordingly.
- **Drop F3 from the gate entirely** — rejected: the survey kept the row 5–2, and the add-in is
  the project's most-visible placeholder surface. The experimental-label fallback already covers
  the failure case without removing the intent.

## Explicitly not decided

- **Which lane is canonical** — decision 2 is the process; the outcome comes from the thread.
- **The redline data shape** — designed with the endpoint, once the lane is chosen.
- **Whether the document-representation layer is ever built** — the contract is designed not to
  preclude it; nothing here commits to it.
