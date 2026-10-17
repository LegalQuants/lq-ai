Two ways into the same data: by jurisdiction and by practice area, built from
every first-party skill's `lq_ai.jurisdiction` and `lq_ai.tags`. Each
jurisdiction or practice-area page lists the skills that cover it today, and —
where the canon has one — a scope note explaining what "covered" actually
means for that entry. A tag with skills against it is not automatically a
clean bill of coverage; read the note.

The clearest example is litigation. The `case-law-research` skill carries the
`litigation` tag, but [PRD §1.6](../../../docs/PRD.md#16-out-of-scope-v1) excludes
"e-discovery or litigation-specific workflows" outright. `docs/skill-authoring-guide.md`'s
tag conventions list `litigation` as "(rarely; out of scope for v1)", and the
`case-law-research` skill's own "What this skill does not do" section bounds
it — it will not research non-U.S. jurisdictions, search statutory or
regulatory text, apply retrieved authority to the user's facts, or assert
that a case is still good law. A page that showed the tag without the note
would answer "can it do litigation?" wrongly by omission; this index carries
the note precisely so that doesn't happen.

Where a jurisdiction or practice area has no skill against it yet, the page
says so plainly rather than leaving a silent gap, and points at
[Where skills live](../../skills/where-skills-live.md) for the contribution route — most
jurisdiction- and practice-area-specific work goes to the community
[`lq-skills`](https://github.com/LegalQuants/lq-skills) repository, not this
one. Scope notes and their sources are maintained in
`docs/site/_data/coverage-notes.yaml`; where a note is missing, the entry
reflects frontmatter only and should be read as unverified against the wider
canon.

## Next

- [Where skills live](../../skills/where-skills-live.md)
- [Skill catalogue](catalogue.intro.md)
- [Author your first skill](../../skills/author-your-first-skill.md)
