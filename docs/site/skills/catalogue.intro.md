Every first-party skill in `skills/`, one row per skill, built from each
`SKILL.md`'s own frontmatter — this table is generated, not hand-maintained,
so it cannot drift from what's actually shipped.

Columns: skill, practice area (from `lq_ai.tags`), jurisdiction, version,
author, attested-by, and tier floor. **Attested-by** shows a name only where a
skill's frontmatter records one; no shipped first-party skill carries a
dedicated attestation field, so the column reads "not recorded in
frontmatter" across the board rather than leaving a blank that could be
misread as "unattested". An attestation is
not a warranty of legal correctness for every use — it is a named practicing
attorney certifying the same care they apply to their own work product, at
the version attested, and it is re-made when the skill's substance changes.
Read [The attestation bar](../../../skills/CONTRIBUTING.md) before relying on any row here.
**Tier floor** shows a skill's `minimum_inference_tier` where one is
declared, and is blank where a skill sets no minimum. A blank cell means the
skill's frontmatter does not record that field — `skill-creator` carries no
`lq_ai:` block at all, so most of its columns are empty.

**First-party only.** This table covers the skills in this repository's own
`skills/` directory — 30+ additional skills in the
[`LegalQuants/lq-skills`](https://github.com/LegalQuants/lq-skills) community
repository are not indexed on this site yet; browse it directly, or read
[Where skills live](../../skills/where-skills-live.md) for how the two repositories relate.

## Next

- [The attestation bar](../../../skills/CONTRIBUTING.md)
- [Where skills live](../../skills/where-skills-live.md)
- [Coverage by jurisdiction and practice area](coverage.intro.md)
