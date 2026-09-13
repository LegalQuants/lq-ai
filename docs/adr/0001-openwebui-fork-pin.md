# ADR 0001 — OpenWebUI fork pin and refresh strategy

**Status:** Accepted (2026-05-07)
**Decision-makers:** Kevin Keller (initial maintainer)
**Affected components:** `web/`

---

## Context

LQ.AI's web client (`web/`) is a fork of [OpenWebUI](https://github.com/open-webui/open-webui), per [PRD §2.2](../PRD.md#22-technology-decisions-and-rationale). OpenWebUI is a SvelteKit application with an active release cadence (multiple minor releases per quarter, frequent patches). At the time M1 implementation begins, we need to pick a specific upstream version to fork from, document the refresh procedure, and set expectations for keeping our fork current.

Considerations:

- **Reproducibility.** Anyone building from a tagged LQ.AI release should land on the same `web/` substrate. Tracking a moving branch (`main`) defeats this.
- **SBOM stability.** The supply-chain transparency commitments in [PRD §7.8](../PRD.md#78-release-cadence-and-supply-chain-transparency) require knowing exactly which upstream code is in our build. A pinned tag is the cleanest answer.
- **Rebase cost.** Each upstream rebase introduces some merge cost as our customizations (branding, tier-badge UI, skill inspector, etc.) move forward against upstream changes.
- **Security currency.** Falling more than 6 months behind upstream creates security and compatibility risk.
- **License.** OpenWebUI's license is BSD-3-Clause-modified with a branding clause; we comply with their branding requirements and document the relationship per [PRD §2.2 and §7.2](../PRD.md#72-license).

## Decision

**Pin `web/` to OpenWebUI `v0.9.2`** (released 2026-04-24).

**Why this version:**

- Latest non-prerelease tag at the time of forking.
- Patches the dependency-install issues (`aiosqlite`, `asyncpg`) from v0.9.0.
- v0.9.x brings features (desktop app, scheduled automations, calendar workspace, task management) that don't conflict with LQ.AI's roadmap — their generic task management is orthogonal to legal-matter Projects (PRD §3.11), and their workspace calendar is not the M5+ Today View (PRD §8.5).

**Refresh cadence:**

- Quarterly rebase against the latest upstream stable tag, or earlier if an upstream security fix lands that affects us.
- Rebase work happens in a `vendor/openwebui-upstream` branch; the rebase result lands in `main` as a single PR titled `chore(web): rebase OpenWebUI fork to vX.Y.Z` with a body listing every upstream commit included and any of our patches that needed rework.
- Rebase PRs require two maintainer approvals because the merge cost is real and the integration surface is large.
- `web/`'s npm dependencies are upstream's, not ours, so their currency arrives with the rebase. `.github/dependabot.yml` runs the `/web` npm ecosystem at `open-pull-requests-limit: 0` — **security updates only**. Routine version bumps raised between refreshes are superseded by the next rebase before they can be reviewed; advisories are not, and still open PRs.

**How customizations are organized:**

- All LQ.AI customizations to `web/` live as patches on top of the pinned tag.
- Branding changes (logo, color palette, footer) are isolated in dedicated files where possible.
- Functional additions (tier badge, skill inspector, project sidebar, etc.) follow the OpenWebUI component patterns and live in clearly-named directories: `web/src/lib/lq-ai/`.
- Patches that should ideally land upstream (bug fixes, generic UX improvements) are flagged in a top-of-file comment as "candidate for upstream PR."

**License posture:**

- We comply with OpenWebUI's branding requirements. The README and the deployment docs explicitly credit OpenWebUI as the upstream.
- OpenWebUI's license is preserved in `web/LICENSE` alongside our Apache 2.0 `LICENSE` at the repo root, with a clear note explaining the dual-license structure.
- **Branding clause (significant, surfaced during A1.d import).** OpenWebUI's license clause 4 prohibits altering, removing, obscuring, or replacing "Open WebUI" branding (name, logo, visual / textual / symbolic identifiers) in any deployment or distribution, with three carve-outs: (i) deployments with ≤50 end users in any rolling 30-day period, (ii) specific prior written permission from the copyright holder, or (iii) a duly executed enterprise license. **What this means for us:** Task A5 ("Apply LQ.AI branding") cannot strip OpenWebUI's branding out of the UI for deployments above the 50-user threshold. The right pattern is **dual-branding**: an LQ.AI banner / footer / chrome added alongside (not replacing) OpenWebUI's identifiers. For larger-deployment operators who want full re-branding, the README must direct them to OpenWebUI for an enterprise license. This is operator-side compliance, not a maintainer-side blocker — but A5 needs to be explicit about it, and our deployment docs need a "Branding obligations" subsection.

## Consequences

**Positive:**

- Reproducible builds; SBOM is stable per release.
- Customizations are auditable — anyone can diff `web/` against the upstream `v0.9.2` tag and see exactly what we changed.
- Quarterly rebase rhythm keeps us close enough to upstream that security fixes apply cleanly.

**Negative:**

- Upstream features released between rebases are unavailable to LQ.AI users until the next rebase lands.
- A rebase that conflicts with our customizations costs real merge work; the maintainer doing the rebase needs context on every active customization.

**Mitigations:**

- Customizations are isolated where possible (separate files / directories) to minimize rebase conflicts.
- The rebase PR template requires testing against the M1 quickstart end-to-end before merge.

---

## Operational notes

**At fork time (Task A1):** clone OpenWebUI at `v0.9.2`, copy into `web/`, remove `.git`, re-init under our repo. Do **not** add OpenWebUI as a git submodule — submodules complicate the patch-on-top model and are a known friction point for contributors.

**Tracking upstream changes:** maintainers subscribe to the OpenWebUI release feed and the security advisories feed. New CVEs in our pinned version trigger an out-of-cadence rebase if the fix is non-trivial to backport.

---

*Superseding this ADR requires an explicit follow-on ADR. Updating the pinned version (e.g., v0.9.2 → v0.10.0 at the next quarterly rebase) is an in-place edit to this document — record the new version, the date, and a one-line rationale in a "Revisions" section at the bottom.*

---

## Revisions

- **2026-08-25 — v0.9.2 → v0.11.0.** First quarterly refresh under this ADR. Latest upstream stable at the time (released 2026-07-27); 1402 upstream commits, 880 changed paths, 12 files changed on both sides of which 6 conflicted. The [ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md) deletion of `utils/mcp/client.py` was re-asserted, and Cypress was carried forward after upstream removed it entirely. Procedure and findings: [`docs/openwebui-rebase-runbook.md`](../openwebui-rebase-runbook.md); tracked in [#498](https://github.com/LegalQuants/lq-ai/issues/498).

> **Note on the text above.** The Decision, Consequences and Mitigations sections record the position *at the time this ADR was accepted* and are deliberately left unedited — including their references to `v0.9.2`. This Revisions section is the authoritative record of the current pin. Likewise, `v0.9.2` references in ADR 0009, `M1-PROGRESS.md` and `M1-IMPLEMENTATION-ORDER.md` are historical statements about what happened during M1 and are correct as written; they are not stale pins and should not be rewritten at each refresh.
