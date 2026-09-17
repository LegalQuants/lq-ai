Every release below is generated at build time from the structured release notes in
`docs/releases/`, one page per release, with a page for each tag that has no notes saying
so. Each release page states its upgrade class: **patch** releases need nothing from you —
take them blind; **minor** releases may need something from you before the upgrade works —
read the notes first. That split, and what qualifies as "needs something," is
[ADR 0025](../../adr/0025-release-versioning-and-pipeline-ordering.md)'s rule, carried in
full on [Release versioning](../reference/versioning.md).

**This list is incomplete, and it says so per release.** Structured release notes —
the upgrade class, the operator-action list, migration status — exist today for three
releases, [v0.4.0](../../releases/v0.4.0.md), [v0.7.0](../../releases/v0.7.0.md) and
[v0.7.1](../../releases/v0.7.1.md); the repository's own tags go back to `v0.1.0`, and its
GitHub Releases back to `v0.2.0`. Tags such as `v0.9.2` and `v0.11.0` also exist in the
repository, but they are OpenWebUI's, carried in by the `web/` fork rebase, not LQ.AI
releases; the list below leaves them out the way `docs/BUILD-AND-RELEASE.md` and the release
workflow do — only tags reachable from `main` count. A release page for any tag without a matching structured note says so
plainly instead of rendering empty. Closing that gap is tracked as the release-notes
backfill (the docs-site mini-PRD's spawned item 4, PR #511), which records that source
material exists for the releases it scopes. How much of the full tag history will be
backfilled is not stated in the repository as of the checked commit.

The desktop launcher versions independently — `desktop-vX.Y.Z` is its own version, not a
restatement of an image tag, because the launcher ships launcher-only fixes with no backend
change. ADR 0025 decides that each desktop release should also record which image set it
ships against; that is not yet implemented, and the launcher still defaults to the floating
`latest` tag. See [Release versioning](../reference/versioning.md).

## Next

- [Release versioning](../reference/versioning.md) — what patch and minor commit to, in
  the ADR's own words.
- [Upgrade](../operate/upgrade.md) — the runbook for taking one.
- [Reference](../reference/index.md) — the generated material behind these pages.
