Every first-party skill in `skills/`, one row per skill, read straight from
each `SKILL.md`'s own frontmatter. The table is generated, not
hand-maintained, so it can't fall behind what's actually shipped.

Each row shows the skill's practice area (from `lq_ai.tags`), jurisdiction,
version, author, attested-by, and tier floor. **Attested-by** reads "not
recorded in frontmatter" on every row today — no shipped first-party skill's
frontmatter carries a dedicated attestation field yet, so the column says so
plainly rather than leaving a blank a reader could misread as "unattested".
Where a skill does carry a named attestation, it isn't a warranty that the
skill is right for every use: it's a named practicing attorney certifying
the same care they'd apply to their own work product, at the version
attested, remade whenever the skill's substance changes. Read
[The attestation bar](../../../skills/CONTRIBUTING.md) before relying on any
row here. **Tier floor** shows a skill's declared `minimum_inference_tier`
and is blank where the skill sets none — `skill-creator` carries no
`lq_ai:` block at all, so most of its row is blank too.

**First-party only.** This table covers the skills that ship in this
repository's own `skills/` directory. More live in the community
[`LegalQuants/lq-skills`](https://github.com/LegalQuants/lq-skills)
repository — 30+ of them at last count — and aren't indexed on this site
yet; browse that repository directly, or read
[Where skills live](../../skills/where-skills-live.md) for how the two relate.

## Next

- [The attestation bar](../../../skills/CONTRIBUTING.md)
- [Where skills live](../../skills/where-skills-live.md)
- [Coverage by jurisdiction and practice area](coverage.intro.md)
