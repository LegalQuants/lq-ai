---
title: Release versioning
description: What a version bump means before you take it — patch, minor, and the pre-1.0 promise behind them.
audience: [operator, author]
status: draft
sources:
  - docs/adr/0025-release-versioning-and-pipeline-ordering.md
  - desktop/src/main/index.ts
sidebar:
  order: 2
---

Before you take an upgrade, you want to know one thing: does this release need you to do
anything, or can you take it blind? [ADR 0025](../../adr/0025-release-versioning-and-pipeline-ordering.md)
answers that with a rule stricter than semver requires while the project is pre-1.0, and
this page carries that rule verbatim rather than paraphrasing it — paraphrase is exactly
how a policy like this drifts from what the ADR actually commits to.

`api`, `gateway`, `web` and `proxy` share one version, bumped together on every `vX.Y.Z`
tag. The desktop launcher (`desktop-vX.Y.Z`) versions independently of the image tags.
ADR 0025 decides that each desktop release should record which `vX.Y.Z` image set it ships
against; that recording is not implemented as of the checked commit — the launcher still
defaults to the floating `latest` tag (`desktop/src/main/index.ts`), which the ADR names as
implementation work still outstanding. See [Upgrade](../operate/upgrade.md) for the runbook
that applies this policy to an actual running deployment.

<!-- include: docs/adr/0025-release-versioning-and-pipeline-ordering.md from="## Decision" to="## Alternatives considered" -->

The worked examples above are taken from milestones open when the ADR was written, not
invented for illustration — and the ADR goes on to name two of its own releases, `v0.6.3`
and `v0.7.0`, as mis-numbered under the rule it was writing. Publishing that table is the
point, not an embarrassment.

## What "1.0" means

Nothing, yet. ADR 0025 reserves the major version for a `1.0.0` milestone and explicitly
declines to define what that milestone requires — no other project document does either.
Until a future decision sets that bar, every release stays inside `0.x`, and the rule above
governs minor and patch only. Do not read a `0.x` release as pre-alpha because of the
leading zero; do not read a future `1.0.0` as a bigger change than the release notes say it
is, either — treat the number the same way this page treats every other release: read the
notes, not the version string, for what actually changed.

## What this page does not cover

Cadence — how often a minor release should land, and the reasons the project cannot commit
to PRD §7.8's original 6–8 week target today — is a capacity question, not a versioning
rule, and is covered in the ADR's own "Cadence" section rather than repeated here. The
[changelog](../changelog/index.intro.md) applies this page's classes to every actual
release; [Upgrade](../operate/upgrade.md) is the step-by-step procedure.

## Next

- [Changelog](../changelog/index.intro.md) — see which class each shipped release fell
  into.
- [Upgrade](../operate/upgrade.md) — the runbook.
- [ADR 0025](../../adr/0025-release-versioning-and-pipeline-ordering.md) — the full
  decision, including cadence and what it explicitly leaves undecided.
