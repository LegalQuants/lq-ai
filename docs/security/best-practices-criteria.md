# OpenSSF Scorecard targets & Best Practices (Passing) criteria walkthrough

> **Serves:** DE-222 (OpenSSF Scorecard in README + CI) and DE-223 (OpenSSF Best Practices badge, Passing tier) — roadmap item 3.4.
>
> **Filename reconciliation:** DE-222 (PRD §9) names a `docs/security/scorecard-targets.md`; DE-223 names a `docs/security/best-practices-badge-status.md`; the mini-PRD ([openssf-scorecard-and-badges.md](../contribute/mini-prds/openssf-scorecard-and-badges.md)) names `docs/security/best-practices-criteria.md` (and, in one passage, `BEST_PRACTICES_CRITERIA.md`). Those are four names for two closely-coupled artifacts — the Scorecard target floor and the badge criteria walkthrough share most of their evidence, so they live together in **this single document**, at the path the mini-PRD specifies. The PRD entries should be read as pointing here.

This document has three parts:

1. [Scorecard: targets, expected check-by-check state, and the score rationale](#part-1--openssf-scorecard)
2. [Best Practices badge: every Passing-tier criterion with status + evidence](#part-2--best-practices-badge-passing-tier-walkthrough)
3. [The maintainer checklist — everything that cannot be done from a PR](#part-3--maintainer-checklist)

**Status legend** used throughout:

- **Met** — satisfied by an artifact in this repository; the evidence citation is the thing a reviewer verifies.
- **Maintainer action** — requires a repo-settings toggle, a bestpractices.dev attestation, or an ongoing-practice declaration that only a maintainer can make. A PR cannot close these.
- **N/A** — not applicable (or vacuously satisfied), with justification.

---

## Part 1 — OpenSSF Scorecard

### What ships in this repo

- [`.github/workflows/scorecard.yml`](../../.github/workflows/scorecard.yml) — weekly cron + push-to-main + `branch_protection_rule` + manual dispatch; `publish_results: true` (powers the badge and the [scorecard.dev viewer](https://scorecard.dev/viewer/?uri=github.com/LegalQuants/lq-ai)); SARIF uploaded to code scanning.
- [`.github/workflows/codeql.yml`](../../.github/workflows/codeql.yml) — CodeQL SAST for `python` + `javascript-typescript` on PRs, pushes to main, and weekly. This is what the Scorecard **SAST** check credits.
- [`SECURITY-INSIGHTS.yml`](../../SECURITY-INSIGHTS.yml) — OSSF security-insights (spec v2) structured security metadata at the repo root.
- README Scorecard badge (live once the first publishing run completes) and a clearly-marked Best Practices badge placeholder (see [Part 3](#part-3--maintainer-checklist)).

### Score targets (per DE-222)

| Milestone | Target floor |
|---|---|
| Initial (this PR merged + maintainer checklist done) | **≥ 7.0** |
| M2 | ≥ 8.5 |
| M4 | ≥ 9.0 |

The targets are commitments to *maintain a floor*, not one-time measurements: the weekly run keeps the badge honest, and any check that regresses below its expected state below is a bug against this document.

### Expected check-by-check state

The score below is an **expectation with evidence, not a measured fact** — the first authoritative number comes from the first `publish_results` run on `main` after merge. Ground-checked against this repo's CI as of 2026-07-25:

| Scorecard check | Expected state | Evidence / gap |
|---|---|---|
| Dangerous-Workflow | Pass | No `pull_request_target`, no PR-checkout of untrusted refs, no untrusted `${{ }}` interpolation into `run:` scripts (audited across all six workflows). |
| Token-Permissions | Pass | Every workflow declares top-level `permissions: contents: read`; write scopes are job-scoped (`release.yml` sign/attest jobs, `desktop-release.yml` build job, `scorecard.yml`/`codeql.yml` analysis jobs). |
| Pinned-Dependencies | Pass (high) | All `uses:` pinned to 40-char SHAs with `# vX.Y.Z` comments; CI's Postgres service image pinned by digest ([ci.yml](../../.github/workflows/ci.yml)). Known residual: service `Dockerfile`s pin base images by tag, not digest — tracked as a gap-closure item for the M2 target. |
| Dependency-Update-Tool | Pass | [`.github/dependabot.yml`](../../.github/dependabot.yml): pip (api, gateway), npm (web), github-actions ecosystems. |
| CI-Tests | Pass | [`ci.yml`](../../.github/workflows/ci.yml) runs web + api + gateway suites on every PR; [`stack-smoke.yml`](../../.github/workflows/stack-smoke.yml) boots the full stack on manifest changes. |
| SAST | Pass | [`codeql.yml`](../../.github/workflows/codeql.yml) (added by this PR) — the check specifically credits `github/codeql-action`. ruff + mypy also run in CI but score lower with Scorecard. |
| Security-Policy | Pass | [`SECURITY.md`](../../SECURITY.md): private contact, response commitments, disclosure language. |
| Signed-Releases | Pass (improving) | [`release.yml`](../../.github/workflows/release.yml): cosign keyless signatures + SPDX SBOM attestations + SLSA provenance per image. The check inspects the last 5 releases, so the score converges as post-pipeline releases accumulate. |
| License | Pass | Apache-2.0 at [`LICENSE`](../../LICENSE). |
| Maintained | Pass | Active weekly commit/release cadence (informational; no action). |
| Vulnerabilities | Pass expected | No known unpatched OSV vulnerabilities; Dependabot keeps manifests current. |
| Binary-Artifacts | Pass expected | No checked-in generated binaries. |
| Branch-Protection | **Maintainer action** | Settings toggle, tiered 3→10 pts (see Part 3). Without an admin-scoped token Scorecard sees only the public subset, capping this check. |
| Code-Review | Partial → improving | PR-based flow with review is the working practice; the check scores the recent ~30-commit window, so any direct pushes decay it and recovery is gradual. Practice commitment in Part 3. |
| CII-Best-Practices | 0 until enrolled | Becomes 5 pts at Passing tier once the maintainer completes the bestpractices.dev registration (Part 3; Part 2 is the prepared evidence). |
| Fuzzing | 0 — **deliberate** | Rejected for this stage per the supply-chain survey: OSS-Fuzz integration is the highest-effort/lowest-relevance check for a FastAPI + SvelteKit application. Revisit if/when a parsing-heavy native component lands. |
| Packaging | N/A | No language-registry packages published (container images are covered by Signed-Releases). Scorecard scores this `-1` (excluded from the aggregate). |
| Webhooks / SBOM (experimental) | Informational | SBOM per release already ships as a cosign attestation. |

### Why ≥ 7.0 is the documented expectation

The weighted checks that dominate the aggregate — Dangerous-Workflow (critical), Token-Permissions (high), Branch-Protection partial, Maintained (high), Signed-Releases (high), Vulnerabilities (high), Code-Review (high, partial), plus medium-weight Pinned-Dependencies, Dependency-Update-Tool, CI-Tests, SAST, Security-Policy, License — are pass-or-near-pass on the evidence above; the only structural zeros are Fuzzing (deliberate) and CII-Best-Practices (until enrollment). That mix lands comfortably above 7.0 in Scorecard's weighting **provided the maintainer completes the branch-protection tier in Part 3**; if the first published run comes in lower, the failing checks get a gap-closure entry in this table (per the mini-PRD acceptance criteria) rather than a target adjustment.

---

## Part 2 — Best Practices badge: Passing-tier walkthrough

Criteria list per [bestpractices.dev/en/criteria/0](https://www.bestpractices.dev/en/criteria/0) (Passing level; 67 criteria). Levels: MUST / SHOULD / SUGGESTED as defined by the badge program. The maintainer transcribes this table into the bestpractices.dev questionnaire — each *Met* row's evidence is the citation to paste; each *Maintainer action* row is an attestation only the maintainer can make.

### Basics (13)

| Criterion | Level | Status | Evidence / action |
|---|---|---|---|
| `description_good` | MUST | Met | [`README.md`](../../README.md) opening section + GitHub repo description. |
| `interact` | MUST | Met | README (issues link), [`CONTRIBUTING.md`](../../CONTRIBUTING.md), GitHub Issues/Discussions. |
| `contribution` | MUST | Met | [`CONTRIBUTING.md`](../../CONTRIBUTING.md) (PR process §"Pull request process"); [`skills/CONTRIBUTING.md`](../../skills/CONTRIBUTING.md) for legal-substance skills. |
| `contribution_requirements` | SHOULD | Met | CONTRIBUTING.md: code style, DCO sign-off, testing requirements. |
| `floss_license` | MUST | Met | Apache-2.0 ([`LICENSE`](../../LICENSE)). |
| `floss_license_osi` | SUGGESTED | Met | Apache-2.0 is OSI-approved. |
| `license_location` | MUST | Met | `LICENSE` at repo root. |
| `documentation_basics` | MUST | Met | README, [`docs/PRD.md`](../PRD.md), [`docs/architecture.md`](../architecture.md). |
| `documentation_interface` | MUST | Met | OpenAPI specs: [`docs/api/backend-openapi.yaml`](../api/backend-openapi.yaml), [`docs/api/gateway-openapi.yaml`](../api/gateway-openapi.yaml); [`gateway.yaml.example`](../../gateway.yaml.example). |
| `sites_https` | MUST | Met | Project site is the GitHub repo (HTTPS/TLS). |
| `discussion` | MUST | Met | GitHub Issues + Discussions (searchable, URL-addressable). |
| `english` | SHOULD | Met | All documentation in English. |
| `maintained` | MUST | Met | Active commit and release cadence (tags through v0.6.1); maintainer confirms on the form. |

### Change Control (9)

| Criterion | Level | Status | Evidence / action |
|---|---|---|---|
| `repo_public` | MUST | Met | https://github.com/LegalQuants/lq-ai |
| `repo_track` | MUST | Met | git history (authors, timestamps, diffs). |
| `repo_interim` | MUST | Met | `main` carries interim commits between releases. |
| `repo_distributed` | SUGGESTED | Met | git. |
| `version_unique` | MUST | Met | `v*.*.*` tags drive [`release.yml`](../../.github/workflows/release.yml). |
| `version_semver` | SUGGESTED | Met | SemVer tags (…v0.5.1, v0.6.0, v0.6.1). |
| `version_tags` | SUGGESTED | Met | git tags per release. |
| `release_notes` | MUST | Met | GitHub Releases carry human-readable notes per release. |
| `release_notes_vulns` | MUST | N/A | No publicly known vulnerabilities (CVEs) fixed to date, so none to list. [`SECURITY.md`](../../SECURITY.md) commits to advisories + CVE coordination when the first one lands. |

### Reporting (8)

| Criterion | Level | Status | Evidence / action |
|---|---|---|---|
| `report_process` | MUST | Met | CONTRIBUTING.md + GitHub Issues; README invites issues for doc/code divergence. |
| `report_tracker` | SHOULD | Met | GitHub issue tracker. |
| `report_responses` | MUST | **Maintainer action** | Attestation of practice: majority of bug reports acknowledged (2–12-month window). Evidence accrues in the tracker; only the maintainer can attest the ratio. |
| `enhancement_responses` | SHOULD | **Maintainer action** | Same shape: attestation that enhancement requests get responses. |
| `report_archive` | MUST | Met | GitHub Issues archive (public, searchable). |
| `vulnerability_report_process` | MUST | Met | [`SECURITY.md`](../../SECURITY.md) §"Reporting a vulnerability". |
| `vulnerability_report_private` | MUST | Met | security@legalquants.com + GitHub Security Advisories (private). |
| `vulnerability_report_response` | MUST | Met | SECURITY.md commits to acknowledgment within **72 hours** (criterion: ≤ 14 days). |

### Quality (13)

| Criterion | Level | Status | Evidence / action |
|---|---|---|---|
| `build` | MUST | Met | `docker compose build` ([`docker-compose.yml`](../../docker-compose.yml)); per-service Dockerfiles; web Vite build. |
| `build_common_tools` | SUGGESTED | Met | Docker, pip, npm. |
| `build_floss_tools` | SHOULD | Met | Entire toolchain is FLOSS. |
| `test` | MUST | Met | pytest suites (`api/tests/`, `gateway/tests/`), Vitest + svelte-check (`web/`), all FLOSS, run in [`ci.yml`](../../.github/workflows/ci.yml). |
| `test_invocation` | SHOULD | Met | Standard invocations: `pytest`, `npm run test:frontend`. |
| `test_most` | SUGGESTED | Met | Substantial suites across all three subsystems; 80% coverage target documented in CONTRIBUTING.md. (Honest caveat: the CI coverage *gate* is a deferred wave — see ci.yml header.) |
| `test_continuous_integration` | SUGGESTED | Met | ci.yml on every PR + push to main; stack-smoke.yml boot validation. |
| `test_policy` | MUST | Met | CONTRIBUTING.md §"Testing requirements" + CLAUDE.md ("tests are part of the change"; bug fixes require regression tests). |
| `tests_are_added` | MUST | Met | Recent merged PRs demonstrably ship with tests (see merge history); maintainer confirms on the form. |
| `tests_documented_added` | SUGGESTED | Met | CONTRIBUTING.md documents the add-tests requirement in the contribution instructions. |
| `warnings` | MUST | Met | ruff (lint + format), mypy (strict for `gateway/`), ESLint + svelte-check for `web/` — all CI-enforced. |
| `warnings_fixed` | MUST | Met | CI gates are hard-fail; warnings are addressed before merge. |
| `warnings_strict` | SUGGESTED | Met | `mypy --strict` on the security boundary (`gateway/`). |

### Security (16)

| Criterion | Level | Status | Evidence / action |
|---|---|---|---|
| `know_secure_design` | MUST | **Maintainer action** | Attestation that ≥ 1 primary developer knows secure-design principles. Supporting evidence: [`docs/security/threat-model.md`](threat-model.md) (STRIDE), gateway-as-security-boundary architecture. |
| `know_common_errors` | MUST | **Maintainer action** | Attestation of common-vuln-class knowledge. Supporting evidence: [`docs/security/`](README.md) set, CodeQL adoption. |
| `crypto_published` | MUST | Met | Only published primitives: JWT HS256, bcrypt, Fernet (AES-128-CBC + HMAC-SHA256), TLS — inventory in [`docs/security/cryptography.md`](cryptography.md). |
| `crypto_call` | SHOULD | Met | Delegates to `PyJWT`, `bcrypt`, `cryptography` — no re-implemented primitives (cryptography.md). |
| `crypto_floss` | MUST | Met | All crypto via FLOSS libraries. |
| `crypto_keylength` | MUST | Met | JWT secret recommended 256-bit (`openssl rand -hex 32`); refresh tokens 256-bit random; Fernet 128-bit AES + 256-bit HMAC (≥ NIST 112-bit 2030 floor). See cryptography.md §key lifecycle. |
| `crypto_working` | MUST | Met | No broken algorithms (no MD5/SHA-1/DES in security contexts) — cryptography.md inventory. |
| `crypto_weaknesses` | SHOULD | Met | No known-weak defaults; documented trade-offs (HS256 vs RS256, Fernet vs AEAD-GCM) in cryptography.md §limitations. |
| `crypto_pfs` | SHOULD | Met | Key agreement is delegated to TLS at the Caddy proxy (TLS 1.3 suites are ECDHE/PFS-only); the app implements no bespoke key-agreement protocol. |
| `crypto_password_storage` | MUST | Met | bcrypt, cost factor 12 (configurable), per-user salt inherent to bcrypt — `api/app/security/passwords.py`, documented in cryptography.md. |
| `crypto_random` | MUST | Met | CSPRNG-sourced secrets (256-bit opaque refresh tokens, Fernet keys via `cryptography`) — cryptography.md inventory. |
| `delivery_mitm` | MUST | Met | Delivery over HTTPS (GitHub, GHCR); images cosign-signed with SLSA provenance ([`release.yml`](../../.github/workflows/release.yml), verify steps in [`docs/security/README.md`](README.md)). |
| `delivery_unsigned` | MUST | Met | No unsigned hashes over HTTP anywhere in the delivery path. |
| `vulnerabilities_fixed_60_days` | MUST | **Maintainer action** | The badge commitment: no *publicly known* medium+ vulnerability unpatched > 60 days. Note for the maintainer: [`SECURITY.md`](../../SECURITY.md) currently commits to 90 days for medium severity *from confirmation of a privately reported issue* — a different clock than this criterion's public-disclosure clock, but the maintainer should consciously stand behind the 60-day public-vuln commitment (and optionally tighten SECURITY.md) before attesting. |
| `vulnerabilities_critical_fixed` | SHOULD | Met | SECURITY.md commits to critical fixes within 30 days, with acceleration for actively exploited issues. |
| `no_leaked_credentials` | MUST | Met | No credentials in-repo by design (bring-your-own-keys; provider keys Fernet-encrypted per [`encrypted-keys.md`](encrypted-keys.md); the only obvious default, `dev-jwt-secret-change-me`, is an intentionally invalid placeholder documented in cryptography.md). Maintainer runs a secret-scan pass before attesting. |

### Analysis (8)

| Criterion | Level | Status | Evidence / action |
|---|---|---|---|
| `static_analysis` | MUST | Met | CodeQL ([`codeql.yml`](../../.github/workflows/codeql.yml), added by this PR) + ruff + mypy in CI, applied to every proposed release by construction (CI on every PR/push). |
| `static_analysis_common_vulnerabilities` | SUGGESTED | Met | CodeQL default query suites target common vulnerability classes for Python and JS/TS. |
| `static_analysis_fixed` | MUST | **Maintainer action** | Ongoing-practice attestation: medium+ findings from analysis are fixed promptly. (Code-scanning alerts dashboard is the evidence trail.) |
| `static_analysis_often` | SUGGESTED | Met | CodeQL + linters run on every PR and push to main, plus weekly cron. |
| `dynamic_analysis` | SUGGESTED | N/A (deliberate deferral) | Fuzzing/OSS-Fuzz rejected for this stage per the supply-chain survey (poor effort/relevance fit for a FastAPI + SvelteKit stack). SUGGESTED criteria do not block Passing. |
| `dynamic_analysis_unsafe` | SUGGESTED | N/A | No memory-unsafe languages in the codebase (Python, TypeScript/JavaScript). |
| `dynamic_analysis_enable_assertions` | SUGGESTED | N/A | No dynamic-analysis configuration exists to enable assertions in. |
| `dynamic_analysis_fixed` | MUST | N/A | Conditional on dynamic-analysis findings existing; vacuously satisfied (none are run — see `dynamic_analysis`). |

### Tally

| Status | Count |
|---|---|
| Met (in-repo evidence) | **56** |
| Maintainer action (settings/attestation) | **6** |
| N/A (justified) | **5** |
| **Total (Passing tier)** | **67** |

All 6 maintainer-action items are attestations or settings — none require new code. Silver and Gold tiers are explicitly out of scope for this pass (per the mini-PRD scope cuts); DE-223 tracks the M2 (Silver) and M4 (Gold) transitions.

---

## Part 3 — Maintainer checklist

Everything below is *not PR-able* — it needs repo-admin or bestpractices.dev account authority.

### M1. Branch protection on `main` (Scorecard Branch-Protection, tiered)

Settings → Branches → protect `main`:

1. Disallow force pushes + deletions (tier 1, 3 pts).
2. Require a pull request before merging, ≥ 1 approving review (tier 2, 6 pts).
3. Require status checks to pass (`CI` jobs + `CodeQL`) (tier 3, 8 pts).
4. Optional, for the M2 ≥ 8.5 target: 2+ reviewers (9 pts) and dismiss stale approvals (10 pts) — weigh against solo-maintainer throughput.

Also maintain the Code-Review practice: no direct pushes to `main`; the check scores the recent ~30-commit window and recovers slowly after direct pushes.

### M2. Register the project on bestpractices.dev

1. Sign in at https://www.bestpractices.dev with the GitHub account that has authority over `LegalQuants/lq-ai`; add the project.
2. Transcribe Part 2 above into the questionnaire (Met rows → citation URLs; Maintainer-action rows → your attestations, including the **60-day public-vulnerability commitment** — read the `vulnerabilities_fixed_60_days` note first).
3. On award of Passing, note the numeric project ID from the project page URL (`https://www.bestpractices.dev/projects/<ID>`).
4. **Replace the README placeholder:** [`README.md`](../../README.md) contains an HTML-comment placeholder badge with `<BP_PROJECT_ID>` tokens — the ID does not exist until this registration, so it was deliberately not fabricated. Uncomment and substitute the real ID:
   `[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/<BP_PROJECT_ID>/badge)](https://www.bestpractices.dev/projects/<BP_PROJECT_ID>)`
5. Announce the tier per DE-223's acceptance criteria.

### M3. First Scorecard publish

The Scorecard badge in the README resolves once the first `scorecard.yml` run with `publish_results: true` completes on `main` (requires the repo to be public — it is). Compare the published per-check results against the Part 1 table; file gap-closure items for any divergence.

### M4. Standing commitments the badges encode

- Keep the weekly Scorecard and CodeQL runs green; treat regressions as bugs.
- Acknowledge vulnerability reports within 72 hours (SECURITY.md); hold the 60-day line for publicly known medium+ vulnerabilities (badge commitment).
- Keep the annual `last-reviewed` date in [`SECURITY-INSIGHTS.yml`](../../SECURITY-INSIGHTS.yml) fresh when reviewing this document.

---

*Maintained alongside `SECURITY-INSIGHTS.yml` and the Scorecard/CodeQL workflows; re-verify the criteria table against bestpractices.dev when the badge program revises its criteria set.*
