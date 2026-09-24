See what changed in each release. Every tag below is generated at build time from the
structured release notes in `docs/releases/`, one page per release — a tag with no notes
yet gets a page that says so, instead of one that renders empty. Each release page states
its upgrade class: a **patch** release needs nothing from you — take it blind; a **minor**
release may need something from you before the upgrade works — read its notes first. That
split, and what counts as "needs something," is
[ADR 0025](../../adr/0025-release-versioning-and-pipeline-ordering.md)'s rule, carried in
full on [Release versioning](../../adr/0025-release-versioning-and-pipeline-ordering.md).

**This history is incomplete, and it says so per release.** Detailed notes — the upgrade
class, what to do before upgrading, migration status — exist today for three releases:
[v0.4.0](../../releases/v0.4.0.md), [v0.7.0](../../releases/v0.7.0.md), and
[v0.7.1](../../releases/v0.7.1.md). The project's tags go back further than that, to
`v0.1.0`, with GitHub Releases back to `v0.2.0`; the earlier ones are listed below without
notes yet, not treated as though nothing changed. Only tags reachable from `main` are
counted — a couple of tags in the repository, `v0.9.2` and `v0.11.0`, belong to OpenWebUI,
carried in by the `web/` fork rebase, not to LQ.AI. Filling in the rest of the history is
tracked as the release-notes backfill (the docs-site mini-PRD's spawned item 4, PR #511);
how much of it will eventually be backfilled isn't decided yet.

**App and desktop releases are separate version numbers.** The desktop launcher's
`desktop-vX.Y.Z` is its own version, not a restatement of the image tag it runs, because the
launcher can ship its own fixes with no backend change. A release build of the launcher now
bakes in the exact image set it ships against — `desktop-vX.Y.Z` converts to the matching
`vX.Y.Z` at build time; only a launcher built locally from source still floats to the
`latest` tag. See [Release versioning](../../adr/0025-release-versioning-and-pipeline-ordering.md).

## Next

- [Release versioning](../../adr/0025-release-versioning-and-pipeline-ordering.md) — what patch and minor commit to, in
  the ADR's own words.
- [Upgrade](../../operate/upgrade.md) — the runbook for taking one.
- [Reference](../reference/index.md) — the generated material behind these pages.
