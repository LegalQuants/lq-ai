# Remote branch audit — 2026-07-08

**Question:** can we delete the stale branches on `origin` (`LegalQuants/lq-ai`)?

**Answer:** yes — 131 of the 155 non-`main` remote branches are fully contained
in `main` and safe to delete. 24 must be kept or need a maintainer decision.
`scripts/delete-stale-branches.sh` deletes the 131 vetted branches (dry-run by
default; `--execute` to act; each branch is deleted only if its tip still
matches the SHA recorded at audit time).

## Method

The repository uses squash merges, so `git branch --merged` finds nothing
(0 of 155 branches are merged by ancestry). Containment was therefore
established two independent ways:

1. **Patch-id check** — for each branch, its full diff against the merge-base
   with `main` was recreated as a single squashed commit and compared against
   `main` by patch-id (`git cherry`). 113 branches matched: their entire
   content is textually present in `main`.
2. **Merged-PR check** — the remaining branches were cross-referenced against
   all 241 closed PRs. 18 more branches (the m2/m3 stacked task branches,
   PRs #29–#57 and #150) have tips that exactly match the head SHA of a merged
   PR. Their bases were the `m2-development`/`m3-development` integration
   branches, whose content was verified file-by-file to be in `main` (which is
   why the patch-id check alone missed them).
   - `docs/install-mac-screenshots` has one commit past its merged PR #150,
     but every file that commit adds is present in `main` (delivered via
     `docs/install-mac-flow-screenshots`).

Every open PR whose head lives in this repository was excluded: all 18 are
Dependabot branches, and none of the 131 deletable branches has an open PR.
(The other open PRs come from contributor forks; their branches are not in
this repository and are unaffected.)

## Result

| Category | Count | Action |
|---|---|---|
| Content fully in `main` (squash-verified or merged-PR-verified) | 131 | Delete — `scripts/delete-stale-branches.sh --execute` |
| Dependabot branches with **open** PRs | 18 | Keep — deleting closes the PR; Dependabot deletes them itself when the PR is merged/closed |
| `roadmap-enhancements-parked` | 1 | Keep — deliberately parked work product (5 files, incl. a draft .docx) that exists nowhere else |
| `session-handoff-2026-05-22-night`, `session-handoff-2026-05-23-m3-d-shipped`, `session-handoff-2026-05-23-m3-e-complete`, `session-handoff-2026-05-24-m3-f-complete`, `m3-development` | 5 | Maintainer call — see below |

## The 5 maintainer-call branches

`main` preserves the session-handoff record in `docs/` through
`SESSION-HANDOFF-2026-05-21-night-…`. Five later handoff docs exist **only**
on these branches:

- `docs/SESSION-HANDOFF-2026-05-21-m3-a6-shipped-roadmap-enhancements-kickoff.md` (only unique commit on `m3-development`; all its M3 code is in `main`)
- `docs/SESSION-HANDOFF-2026-05-22-night-m3-c3-c4a-shipped-m3-d1-half.md`
- `docs/SESSION-HANDOFF-2026-05-23-M3-D1-D3-D4-shipped.md`
- `docs/SESSION-HANDOFF-2026-05-23-m3-e-complete.md`
- `docs/SESSION-HANDOFF-2026-05-24-m3-f-complete.md`

Options: (a) cherry-pick the five docs onto `main` to close the gap in the
handoff record, then delete all five branches; or (b) accept the loss and
delete. Deleting without either choice silently loses the only copies.

## Permissions

A `git push --dry-run origin --delete <branch>` from the working environment
was accepted, so the credential in use can delete remote branches. `main` is
the only branch that should be protected; none of the 131 listed branches is
`main`.
