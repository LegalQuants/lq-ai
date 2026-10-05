# Keep the app running if circumstances change

Plan who would maintain your installation if a provider or maintainer became unavailable.

## Keep what you need

Record the source version, build instructions, settings and operating responsibilities. Keep backups you have tested restoring. Identify which tasks depend on outside AI services and what alternatives you would use.

### Details

- LQ.AI does not route your data through a LegalQuants-operated service to function. The reference
  deployment (`docker-compose.yml`) persists application data in your own PostgreSQL container
  (volume `pgdata`) and files in your own RustFS container (volume `miniodata` — the volume name
  predates the RustFS migration in [ADR 0036](../adr/0036-bundled-object-store-rustfs.md) / #594 and
  was kept for upgrade compatibility) — both containers you run, on infrastructure you control.
- Per [PRD §5.7](../PRD.md#57-no-telemetry-by-default), "the deployment emits no telemetry to
  LegalQuants or any third party by default," and your provider keys stay in your own gateway
  configuration. If LegalQuants disappeared, nothing about continuity depends on a LegalQuants-held
  credential or endpoint — your running deployment, your data, and your keys are already all in your
  own hands.

## Allow time for maintenance

Having the source gives you options, but someone still needs to understand it, maintain its dependencies and recover the data when needed.

## Plan for dependencies as well as maintainers

Keeping source and data gives you options if maintenance stops, but future provider changes, dependencies and security fixes still need someone to handle them. Keep images, build instructions, model files and recovery keys as well as a Git checkout. Read the separate license texts for the project and its web client.

### Details

- LQ.AI is licensed under [Apache 2.0](../../LICENSE). If every maintainer stopped working on it
  tomorrow, you keep the right to run, modify, and redistribute the code you already have,
  indefinitely, and to fork the repository and continue patching it yourself or hand that work to
  someone else. Nothing in the license requires ongoing participation by the original authors for
  your rights to remain in force.
- The `web/` client (the OpenWebUI fork) ships under a separate
  [Open WebUI License](../../web/LICENSE), not Apache 2.0. It permits redistribution and
  modification, but — except for deployments with 50 or fewer end users in any rolling 30-day
  period, or with the copyright holder's written or enterprise permission — it prohibits removing or
  altering the "Open WebUI" branding (`web/LICENSE`, condition 4). Factor that constraint into any
  continuity plan that involves rebranding a fork of the web client beyond that user count.

## Understand the documented concentration risks

ADR 0025 records concentrated code authorship and a desktop signing identity tied to one developer account. Those are different from committee authority to set direction or maintainers' ability to merge changes. Container signing uses a different workflow. Current staffing and credential custody for these processes are not documented here; treat the record as a reason to ask about continuity, not a guarantee that releases will continue.

### Details

- **Contributor concentration.** [ADR 0025](../adr/0025-release-versioning-and-pipeline-ordering.md)
  records that, of 655 non-merge commits on `main`, roughly 642 (~98%) are authored by one person
  across two identities, with the next-highest human contributor at 6 commits. Five distinct human
  identities have landed commits on `main`. The project is resourced for what one person's
  availability allows, not for committee-wide cadence.
- **A single point of failure on desktop signing.** The macOS launcher's code-signing identity —
  `Developer ID Application: Tucuxi, Inc.` (team `MC8BT9Z8GD`, per
  [`docs/BUILD-AND-RELEASE.md`](../BUILD-AND-RELEASE.md) §1) — is tied to the founder's own Apple
  Developer account, not a LegalQuants-organization account, and the release checklist is marked
  "Kevin only." No one else can currently cut a signed `desktop-vX.Y.Z` release, regardless of
  committee bandwidth. This does **not** apply to the container-image releases most deployments
  actually run: those are signed keyless, with a short-lived certificate bound to the GitHub Actions
  workflow's own OIDC identity, not a personal key — see [Supply chain](../security/releases/README.md).
- **What's already mitigated.** ADR 0025 names, rather than resolves, migrating the desktop signing
  identity to an org-owned LegalQuants Apple Developer account as a tracked but not-yet-completed
  piece of future work — the honest state as of the checked commit is that this risk is open.
  Project decision-making is not solely concentrated, though: [`GOVERNANCE.md`](../../GOVERNANCE.md)
  describes a committee that sets priorities and appoints maintainers, and maintainers beyond the
  founder hold repository write access and can review and merge. Concentration in who has *authored*
  the history to date is a different fact from who is *authorized* to carry the project forward — the
  second is already distributed by the governance structure, even where the first is not.
- **What actually happens if it materializes.** Your running deployment does not stop working if
  LegalQuants stops maintaining the project. What would degrade first is the pace of security patches
  and new releases — and, specifically, the desktop launcher's signed builds, which depend on the one
  credential named above. An operator running the Docker Compose or Helm path is not exposed to that
  particular bottleneck; an operator depending on the signed macOS app is. In either case, your fork
  rights under Apache 2.0 are the backstop: you can always continue patching a checked-out copy of the
  code yourself.

## Next

- [Supply chain](../security/releases/README.md) — how a specific release's images are verified, and the signing identity behind them.
- [Governance](../../GOVERNANCE.md) — who holds decision authority today, separate from who has authored the history.
- [Published gaps](../HONEST-STATE.md) — the honest inventory this page draws its "as of the checked commit" framing from.
