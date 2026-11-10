Two ways to browse the same skills: by jurisdiction and by practice area,
both read from each first-party skill's own `lq_ai.jurisdiction` and
`lq_ai.tags`. Each jurisdiction or practice-area page lists the skills that
cover it today, plus — where one exists — a scope note explaining what
"covered" actually means for that entry. A tag having skills against it
isn't automatically a clean bill of coverage; read the note before assuming
it is.

Litigation is the clearest example why. The `case-law-research` skill
carries the `litigation` tag, but
[PRD §1.6](../../../docs/PRD.md#16-out-of-scope-v1) excludes "e-discovery or
litigation-specific workflows" outright, and the skill's own "What this
skill does not do" section bounds it further — it won't research non-U.S.
jurisdictions, search statutory or regulatory text, apply retrieved
authority to your facts, or say whether a case is still good law. A page
that showed the tag alone would answer "can it do litigation?" wrongly, by
omission; the scope note exists so it doesn't.

An empty category on this index means no first-party skill was listed
against it — not that nobody has ever written a related skill. Most
jurisdiction- and practice-area-specific work lives in the community
[`lq-skills`](https://github.com/LegalQuants/lq-skills) repository rather
than this one; where this page shows a gap, read
[Where skills live](../../skills/where-skills-live.md) for the contribution
route. Scope notes and their sources are maintained in
`docs/site/_data/coverage-notes.yaml`; where a note is missing, the entry
reflects frontmatter only and should be read as unverified against the
wider canon.

## Next

- [Where skills live](../../skills/where-skills-live.md)
- [Skill catalogue](catalogue.intro.md)
- [Author your first skill](../../skills/author-your-first-skill.md)
