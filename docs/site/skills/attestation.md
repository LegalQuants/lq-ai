---
title: The attestation bar
description: What a legal-substance skill's attestation covers, who can make it, and how it decays.
audience: [author, contributor, evaluator]
status: draft
sources:
  - skills/CONTRIBUTING.md
  - CLAUDE.md
sidebar:
  order: 7
---

Any first-party skill containing legal substance — a review skill's severity
calibration, a checklist's regime coverage, recommended clause language —
carries an attestation before it merges. Here is what that attestation is,
in the contributing guide's own words:

<!-- include: skills/CONTRIBUTING.md from="### 3. Attest" to="### 4. Review" -->

Two things worth being precise about, because "attested" is over-read easily.

**It is not a warranty that the skill is correct for every document you'll
ever run it on.** The guide is explicit that the bar is the same care a
practicing lawyer applies to their own work product — an acknowledgment that
the skill will be used in real practice, not a guarantee of a specific
outcome. Read the skill's "what this skill does not do" section for the
actual boundary of what it's claiming.

:::note[Professional duty]
An attestation is another lawyer's statement of care, not a transfer of your
own. Relying on a skill's output in client work is an exercise of your
competence and, where you supervise others using it, your supervision — the
attesting attorney's name tells you who stood behind the substance at that
version, not that the output is right for your matter. The skill's "What
this skill does not do" section is the boundary the attestation was made
against; read it before the first client use.
:::

**An AI agent cannot make this attestation.** The project's own contribution
rules are direct about it: *"If an agent is generating skill content, this
process still applies — the human contributor is the attesting party. Agents
do not attest."* A skill drafted with an agent's help still needs a named
human — a practicing attorney, or a legal-ops practitioner or engineer paired
with one — standing behind the substantive content before it merges.

**It decays with updates, not with time.** There's no expiry date on an
attestation; what happens instead is that any update to a skill's substance —
a new perspective, a changed severity calibration, a regime added — goes
through the same review-and-attest process again, calibrated to the size of
the change. A skill that hasn't been touched since its `1.0.0` release still
carries its original attestation; a skill on `1.3.0` carries whatever
attestation covered the `1.3.0` change, on top of the ones before it.

**Where you can actually read it.** skills/CONTRIBUTING.md commits the
attesting attorney's name to two places — the skill's own metadata
(`lq_ai.author`; the co-author path states "both names appear in the skill's
`author` field") and the project's contributor credits. As of the checked
commit that commitment is unmet in the shipped corpus: fourteen of the
fifteen first-party `SKILL.md` files record `author: LegalQuants`, and the
fifteenth (`skill-creator`) carries no `lq_ai:` block at all — so none
records an attesting attorney's name, and no `SKILL.md` carries a dedicated
attestation field. The merging pull request is therefore the only
per-skill attestation record today. The
[skill catalogue](catalogue.intro.md)'s "attested-by" column reflects this
honestly — it shows a name only where a skill's own frontmatter carries one,
and says "not recorded in frontmatter" otherwise. If you need the attesting
record for a specific skill, the PR history is currently the only place to
find it.

## Next

- [Skill catalogue](catalogue.intro.md)
- [Where skills live](where-skills-live.md)
- [Test your skill before sharing it](test-your-skill.md)
