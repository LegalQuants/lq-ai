# ADR 0025 — Release versioning policy and release-pipeline ordering

**Status:** Accepted (2026-08-09) — committee-accepted at the weekly call.
**Date:** 2026-08-02
**Owner:** Maintainer team (houfu)

## Context

The project publishes two independent release artifacts — the container image
set (`v*.*.*` → `release.yml`) and the macOS launcher (`desktop-v*` →
`desktop-release.yml`) — with no enforced ordering between the components of
either, and no operational versioning policy tying their version strings
together.

**The image pipeline is one unordered matrix.** `release.yml` builds `api`,
`gateway`, `web`, and `proxy` as four parallel entries of a single
`build-and-push` job. Its `needs:` edges (`sbom` → `sign`) fan in only *after*
all four have built, so they order the supply-chain steps, not the components.
With `fail-fast: false`, a failed `api` build does not prevent `web` from
publishing — and tagging `:latest` — under the same tag.

**Ordering is documented but unenforced.** `docs/BUILD-AND-RELEASE.md` §3
prescribes cutting images first and the macOS app second, and the BYOK handoff
below follows that order by hand. What no document covers is ordering *within*
the image set — nothing says backend must be verified before `web` builds
against it — and nothing enforces either ordering in CI. The gap is
enforcement and intra-image sequencing, not a total absence of guidance.

**Version drift is live on `main`.** `api/app/__init__.py` is `0.6.1`,
`gateway/app/__init__.py` is `0.5.1`, `desktop/package.json` is `0.6.2`. The
BYOK handoff records api and gateway being bumped *jointly* to `0.5.1`; api
has moved twice since and gateway has not moved at all. No CI check catches
the divergence.

**It has already broken a real install.**
`docs/LQVern/HANDOFF-2026-06-21-byok-recut.md` records `v0.5.0` images and the
`desktop-v0.5.1` `.dmg` shipping without PR #202's BYOK fix, requiring a manual
re-cut of both tags (`v0.5.1` / `desktop-v0.5.2`) so that a fresh install would
work for a stranger.

**No prior decision covers the unit of versioning.** `docs/PRD.md` §7.8
commits to "Semantic versioning (semver)" in a single line with no operational
detail. No prior ADR, PRD section, roadmap item, or DE entry decides what is
versioned as a unit, or what major/minor/patch mean for this project. Nearest
canon: ADR 0023 (a cross-subsystem decision previously undecided anywhere) and
CLAUDE.md's decide-once rule.

## Decision

1. **`api`, `gateway`, `web`, and `proxy` share one release version**, bumped
   together on every `vX.Y.Z` tag — including patch releases where only one
   component substantively changed. They already build from a single tag; this
   makes that fact explicit and enforced rather than incidental.

   The shared version is **the image tag itself**. Only `api` and `gateway`
   carry a project-owned version string (`app/__init__.py`), and those are what
   the consistency check in decision 5 compares. `web/package.json` is
   `0.9.2` — inherited from the OpenWebUI fork and tracking upstream, not this
   project's releases (per ADR 0001's pin-and-monitor posture) — and `proxy`
   has no version string at all. Neither is retitled to match `vX.Y.Z`.

2. **`desktop` versions independently.** The launcher legitimately ships
   launcher-only fixes with no backend change (e.g. `desktop-v0.6.2`'s
   pull-order fix, `05f1cb1e`). Each `desktop-vX.Y.Z` release records which
   `vX.Y.Z` image set it ships against — explicit and discoverable, rather than
   implied by whatever `:latest` resolves to at install time.

   The pinning *mechanism* already exists: `LQ_AI_IMAGE_TAG` is rendered into
   the launcher's runtime `.env` from `cfg.imageTag` (`desktop/src/core/env.ts`).
   What is missing is a truthful default. `docs/BUILD-AND-RELEASE.md` states the
   launcher defaults to "the version we ship the app at", but the shipped code
   defaults to `'latest'` (`desktop/src/main/index.ts:87`) — so today every
   fresh install floats to whatever `:latest` resolves to, which is the exact
   failure mode of the BYOK incident. Correcting that default, and recording the
   pin in a release manifest, is implementation work under this decision.

3. **Pre-1.0, a patch release never requires operator action. Anything that does
   bumps the minor.** Semver §4 says that below `1.0.0` anything may change at
   any time. That gives an evaluating security or procurement team no signal at
   all, so this project promises more than semver requires:

   - **Patch** (`0.6.2` → `0.6.3`) — safe to take without reading anything. No
     new environment variable, no config change, no migration step, no client
     change. Upgrade it blind.
   - **Minor** (`0.6.x` → `0.7.0`) — may require the operator to do something
     before the upgrade works. Read the release notes first. New features land
     here too, so a minor bump means "read", not "brace".
   - **Major** stays unincremented until a `1.0.0` milestone whose criteria this
     ADR does not decide (see *Explicitly not decided*).

   The test is **"does a working install need a human to touch it?"** — not
   "did a function signature change?". The former is something an operator can
   check; the latter is not visible to them.

   **The number is computed from `main`, not chosen in advance.** A release is
   numbered by what has accumulated since the last tag: if any change requiring
   operator action has merged, the next release is a minor bump; otherwise it is
   a patch. A breaking PR therefore does not have to wait for a `0.7.0` to exist
   before it can merge — **merging it is what makes the next release `0.7.0`**.
   Milestones are planning tools and do not decide the number.

   Consequence to plan around: once a change requiring operator action sits on
   `main`, no further *patch* can be cut from `main`. If an urgent fix must ship
   without also shipping that change, it is cherry-picked onto a branch taken
   from the last release tag and cut from there. That path is documented in
   `docs/BUILD-AND-RELEASE.md` and deliberately not automated — with current
   maintainer capacity (see *Cadence*) a standing release-branch discipline
   would cost more than it returns.

4. **The image pipeline gates backend before frontend.** `release.yml`'s matrix
   splits into `build-backend` (api, gateway) and `build-frontend` (web, proxy)
   with `needs: build-backend`, so a backend failure structurally blocks the
   frontend from publishing under the same tag. Each stage gates on a real
   verification step against the published images, not merely a green
   `docker build`. The `desktop-vX.Y.Z` cut remains the final, separate stage,
   unchanged, and is sequenced after both image stages are live and verified.

5. **Both rules are enforced in CI, not left to the runbook.** A `vX.Y.Z` tag
   push fails if `api/app/__init__.py` and `gateway/app/__init__.py` disagree
   with each other or with the tag. It also fails if the tag is a *patch* bump
   while any PR labelled `breaking-change` merged since the previous release tag
   — the gate for decision 3. Each has an explicit override
   (`[allow-version-drift]`, `[allow-breaking-in-patch]` in the tagged commit
   message) whose justification belongs in the release PR.

   The breaking-change gate depends on the label being applied at review time; an
   unlabelled breaking PR is invisible to it. It is a backstop against forgetting
   at release time, not a substitute for judgement at review time.

6. **Cadence commitments are restated as best-effort and capacity-dependent.**
   PRD §7.8's "minor release every 6–8 weeks" and "security backports for 12
   months" predate the committee-governance transition (ADR 0022) and do not
   reflect current maintainer capacity or process latency. See *Cadence* below.

## Worked examples

Taken from the milestones open at the time of writing, to show where the line
falls in practice.

| Change | Does a working install need a human to touch it? | Bump |
|---|---|---|
| **#399** — refuse to boot when `JWT_SECRET` is still the published dev default | **Yes.** An operator who never set `JWT_SECRET` has a running install today that will refuse to start after upgrading, until they set it (or `LQ_AI_DEV_MODE`). | **minor** |
| **#396** — require the gateway key on `/v1` inference endpoints | **Yes.** The api client only sends the header when a key is configured; a deployment without one gets `401` on every inference call after upgrading. | **minor** |
| **#398** — sanitize skill markdown before rendering (XSS) | No. Output-side hardening; nothing to configure. | patch |
| **#442** — list knowledge bases by join table rather than the legacy column | No. Fixes wrong results; no operator step. | patch |
| **#485**, **#481**, **#480** — dependency bumps | No. | patch |
| **#415** — `/lq` slash command for Slack and Teams | No — purely additive. New features are minor because they are new surface, not because they break anything. | **minor** |

**These milestones do not currently follow this rule, and that is the point of
writing it down.** `v0.6.3` is labelled a patch but contains #399 and #396, both
of which require operator action; `v0.7.0` is labelled a minor but contains only
additive work. Under this ADR the two breaking items belong in `v0.7.0`.

**This is already load-bearing, not hypothetical.** #396 and #399 are *both
merged on `main`* — 29 commits past `v0.6.1`, with nothing tagged since. The next
image tag cut from `main` must therefore be **`v0.7.0`**; cutting it as `v0.6.2`
or `v0.6.3` would break this policy on the first release after it is ratified.

## Alternatives considered

- **Fully independent per-component semver** — the status quo. Rejected on the
  evidence: it produced the BYOK re-cut incident and the drift currently live
  on `main`. Unenforced, the components do not stay in sync.
- **One version across all five components, including desktop** — simplest to
  state, and it would make the desktop→image correspondence automatic. Rejected
  because it forces a new image tag, and a full image re-publish, every time the
  launcher needs a zero-backend-change fix.
- **Calendar versioning (CalVer)** — would sidestep the pre-1.0 ambiguity
  entirely and honestly describe a project releasing on availability rather
  than on a compatibility contract. Rejected here because PRD §7.8 already makes
  a public semver commitment; withdrawing it is a larger decision than this ADR
  should carry.
- **Gate the pipeline on build success only, without smoke tests** — cheaper
  and immediately implementable. Rejected because a green `docker build` is
  precisely the signal that was already green during the BYOK incident; the
  images built fine, they just did not contain the fix.

## Cadence

Three factors make the current PRD §7.8 cadence unrealistic to commit to:

- **Contributor concentration.** Of 655 non-merge commits on `main`, roughly
  642 (~98%) are authored by one person across two identities
  (`kevin@tucuxi.ai`, `hikevin@gmail.com`). The next-highest human contributor
  has 6. Five distinct human identities have landed commits on `main`. The
  project is resourced for what one person's availability allows, not for a
  committee-wide cadence.
- **Desktop releases have a hard single point of failure.** The Apple
  code-signing identity — `Developer ID Application: Tucuxi, Inc.`, team
  `MC8BT9Z8GD`, per `docs/BUILD-AND-RELEASE.md` §1 — is tied to the founder's
  own developer account rather than a LegalQuants org account, and
  `docs/BUILD-AND-RELEASE.md` marks the release checklist "Kevin only". No one
  else can cut a signed `desktop-vX.Y.Z` release regardless of committee
  bandwidth.
- **New process latency is not priced in.** ADR-first review (committee call
  plus 7-day async ratification, per ADR 0022) and the staged pipeline gating
  decided above both add real time per release, and both postdate the PRD's
  cadence commitment.

**Proposed replacement text for PRD §7.8** (the first four bullets; the
supply-chain commitments below them are unchanged):

> - Semantic versioning (semver), with the versioning unit and pre-1.0
>   semantics defined in ADR 0025.
> - Releases tagged on GitHub with full changelog.
> - Targeted cadence: minor release **every 8–12 weeks**, patch releases as
>   needed. Cadence is **best-effort and capacity-dependent** while the project
>   operates with its current maintainer and signing-identity concentration;
>   revisit once desktop signing moves to an org-owned Apple Developer account
>   and/or a second maintainer holds release authority.
> - Long-term-support (LTS) designation for one minor version per year, with
>   security backports for **6 months** (reduced from 12), reflecting current
>   capacity to staff backport work; extend once the bottlenecks above are
>   resolved.

## Consequences

- Every `vX.Y.Z` release republishes all four images, and bumps both
  project-owned version strings (`api`, `gateway`), whether or not all four
  components changed. Release notes must therefore distinguish "what changed"
  from "what was rebuilt", or readers will infer substance from a version bump
  that carries none.
- The current drift is resolved as part of the implementing PR: `gateway`
  moves to match `api`, rather than being quietly papered over by the next
  release.
- Splitting the matrix serialises the image build. Backend and frontend no
  longer build concurrently, so wall-clock release time rises by roughly one
  build stage — an accepted cost for the ordering guarantee.
- **The ordering guarantee holds between stages, not within one.** `fail-fast`
  cancels sibling builds inside a stage, but it cannot un-push an image that has
  already pushed, so a `gateway` image can still reach the registry under a tag
  whose `api` build subsequently failed. Closing that gap needs a
  build-then-push-in-a-second-pass design (build all, load, push only once every
  build in the stage has succeeded), which is a larger change than this ADR
  decides and is left as follow-up. Stated here so the guarantee is not read as
  stronger than it is.
- The verification gates in decision 4 do not exist yet and must be built.
  `stack-smoke.yml` is the nearest existing check but is not a drop-in: it
  builds the compose stack from local sources rather than pulling published
  images, and its own header scopes it to "builds, migrates, boots, and holds"
  — explicitly **not** "features work". Cold runs take ~20–30 minutes. Wiring
  the gates therefore means extending stack-smoke to run against published
  image tags, and treating `desktop/VERIFICATION.md` Protocol 1 as the manual
  backstop until an automated equivalent exists.
- A stricter pre-1.0 reading than semver requires means the project will emit
  minor bumps that other tooling may treat as safe. This is documented as a
  deliberate choice, not left for users to discover.
- `docs/BUILD-AND-RELEASE.md` and `docs/PRD.md` §7.8 are updated to carry the
  policy and cross-reference this ADR; the release checklist gains the
  version-consistency and image-pin steps.

## Explicitly not decided

- **What `1.0` means.** This ADR reserves `major` for a `1.0.0` milestone but
  does not define what that milestone requires, and neither does any other
  project doc. "GA" appears three times across the docs — two in PRD §9 (a
  security-doc acceptance criterion and an MCP OAuth timing note) and one in
  `docs/word-addin.md` (the Word add-in's own GA) — and is never operationally
  defined at the product level. The roadmap (PRD §8) is structured as
  milestone-based delivery, each milestone a public release, rather than
  converging on a single 1.0; `docs/HONEST-STATE.md` frames nothing as a 1.0
  gate. Defining 1.0/GA criteria is left to a separate, future committee
  decision — likely its own ADR, once someone is ready to own it. Until then
  this policy governs minor and patch only.
- **Migrating the desktop code-signing identity to an org-owned LegalQuants
  Apple Developer account.** This is the root cause of the desktop
  single-point-of-failure described under *Cadence*, and directly relevant to
  it, but it is an infrastructure and access-provisioning change rather than a
  versioning or pipeline-ordering decision. Tracked separately.

---

*Drafted from the issue decision ledger; every factual claim re-verified against
`legalquants/main` at `b060ae2f`. Filed for committee comment by houfu
(Ang Hou Fu); accepted at the weekly call of 2026-08-09 and merged as PR #487
on 2026-08-10. `v0.7.0` is the first release cut under it.*

*Numbering note: `0024` is taken by the jurisdiction-and-practice-area expansion
ADR, merged as PR #313 on 2026-08-09; this ADR takes `0025`. It cites ADR 0022,
merged as PR #311 on 2026-07-27.*
