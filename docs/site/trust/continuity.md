---
title: Continuity
description: What survives if the maintainers stop — the license, where your data actually lives, and the two named risks this project's own release-process ADR is honest about.
audience: [evaluator, partner]
status: draft
sources:
  - LICENSE
  - docs/PRD.md
  - docs/adr/0025-release-versioning-and-pipeline-ordering.md
  - GOVERNANCE.md
  - docker-compose.yml
  - docs/releases/v0.7.0.md
  - docs/security/releases/README.md
sidebar:
  order: 9
---

An evaluator asking "what if LegalQuants disappears" is asking a structural question a closed-source
SaaS vendor cannot answer honestly, because the product stops existing along with the vendor. Here
the answer is bounded by what the license and the repository actually give you, not by a promise —
this page states only what those two things support.

## What the license gives you

LQ.AI is licensed under [Apache 2.0](../../../LICENSE). If every maintainer stopped working on it
tomorrow, you keep the right to run, modify, and redistribute the code you already have,
indefinitely, and to fork the repository and continue patching it yourself or hand that work to
someone else. Nothing in the license requires ongoing participation by the original authors for
your rights to remain in force.

## Where your data actually is

LQ.AI does not route your data through a LegalQuants-operated service to function. The reference
deployment (`docker-compose.yml`) persists application data in your own PostgreSQL container
(volume `pgdata`) and files in your own MinIO container (volume `miniodata`) — both containers you
run, on infrastructure you control. Per [PRD §5.7](../../PRD.md#57-no-telemetry-by-default), "the
deployment emits no telemetry to LegalQuants or any third party by default." If LegalQuants
disappeared, your running deployment keeps running, your data stays where it already was, and your
provider keys stay in your own gateway configuration — nothing about continuity depends on a
LegalQuants-held credential or endpoint.

## Named risks

This project's own release-process ADR is unusually direct about where continuity actually
concentrates, and this page repeats only what it states:

- **Contributor concentration.** [ADR 0025](../../adr/0025-release-versioning-and-pipeline-ordering.md)
  records that the large majority of commits on `main` are authored by one person across two
  identities, with the next-highest human contributor a small fraction of that. A later release's
  own notes ([`docs/releases/v0.7.0.md`](../../releases/v0.7.0.md)) recount the same figure at a
  different commit and land on a similar order of magnitude. The project is resourced for what one
  person's availability allows, not for committee-wide cadence.
- **A single point of failure on desktop signing.** The macOS launcher's code-signing identity —
  a `Developer ID Application` certificate tied to the founder's own Apple Developer account, not a
  LegalQuants-organization account — means no one else can currently cut a signed `desktop-vX.Y.Z`
  release, regardless of committee bandwidth. This does **not** apply to the container-image
  releases most deployments actually run: those are signed keyless, with a short-lived certificate
  bound to the GitHub Actions workflow's own OIDC identity, not a personal key — see
  [Supply chain](supply-chain.md).

## Named mitigations

ADR 0025 names, rather than resolves, migrating the desktop signing identity to an
org-owned LegalQuants Apple Developer account as a tracked but not-yet-completed piece of future
work — the honest state as of the checked commit is that this risk is open. Separately, project
decision-making is not solely concentrated: [`GOVERNANCE.md`](../../../GOVERNANCE.md) describes a
committee that sets priorities and appoints maintainers, and maintainers beyond the founder hold
repository write access and can review and merge. Concentration in who has *authored* the history
to date is a different fact from who is *authorized* to carry the project forward — the second is
already distributed by the governance structure described on the [Governance](governance.md) page,
even where the first is not.

## What this means for you

Your running deployment does not stop working if LegalQuants stops maintaining the project. What
would degrade first is the pace of security patches and new releases — and, specifically, the
desktop launcher's signed builds, which depend on the one credential named above. An operator
running the Docker Compose or Helm path is not exposed to that particular bottleneck; an operator
depending on the signed macOS app is. In either case, your fork rights under Apache 2.0 are the
backstop: you can always continue patching a checked-out copy of the code yourself.

## Next

- [Supply chain](supply-chain.md) — how a specific release's images are verified, and the signing identity behind them.
- [Governance](governance.md) — who holds decision authority today, separate from who has authored the history.
- [Published gaps](published-gaps.md) — the honest inventory this page draws its "as of the checked commit" framing from.
