# ADR 0023 — uv-managed lockfiles for gateway/ and api/

**Status:** Accepted (2026-07-27)
**Date:** 2026-07-19
**Owner:** Issue #310 (dependency locking); arising from the PR #308 security review

## Context

The PRD commits to "pinned and audited dependencies (lockfiles enforced
in CI)" (Appendix E, supply-chain procurement response) and lists
"pinned dependencies enforced in CI" as a supply-chain-compromise
mitigation (Appendix C, risk 10). DE-114 (reproducible builds) requires
deterministic dependency installation.

Today neither `gateway/` nor `api/` has a lockfile. Both images run
`pip install .` from range-style manifests, so:

- the transitive dependency tree re-resolves on every image build —
  two builds of the same commit can ship different trees;
- CI's stack smoke test validates only the single version resolved at
  build time, a moving target;
- dependabot's pip ecosystem responds to range-style requirements by
  widening ranges (open #308, #306, #177, #175, #131), eroding the
  manifests' tight-window convention; and
- dependency PRs at the security boundary carry no concrete versions in
  the diff, so mechanical vetting (OSV advisory lookup, release-age
  cooldown, new-package detection in lockfile churn) has nothing to
  check.

No prior ADR, PRD section, roadmap item, or DE entry decides the Python
dependency toolchain. Nearest canon: ADR 0001 (fork-pinning precedent)
and CLAUDE.md's decide-once and dependency-justification rules. The
repo's current uv exposure is minimal, and this is a deliberate
migration: `web/uv.lock` is inherited from the OpenWebUI fork and
unconsumed by any build; `web/Dockerfile` uses uv only as a faster pip.

## Decision

uv is the Python dependency toolchain for `gateway/` and `api/`:

1. Dependencies are locked in committed `uv.lock` files generated from
   the existing `pyproject.toml` range declarations, which remain the
   policy layer (tight windows with rationale comments).
2. CI and container images install from the lock (`uv sync --frozen`),
   and CI gates lock freshness with `uv lock --check` — fulfilling the
   PRD's "lockfiles enforced in CI" claim.
3. `.github/dependabot.yml` runs the `uv` package-ecosystem for both
   directories, so updates arrive as lock-pinned version bumps rather
   than range widenings.

## Alternatives considered

- **Keep the status quo (range windows, no lock).** Rejected: the PRD's
  "lockfiles enforced in CI" claim remains unmet (or must be amended);
  transitives stay unpinned; every dependency PR at the security
  boundary remains a manual review of an unverifiable range.
- **pip-tools (`requirements.in` → compiled `requirements.txt`).**
  Least new tooling, but lockfiles are per-platform (uv's are
  universal), and dependabot's native lockfile ecosystem support is
  uv-only.
- **Exact-pin everything in `pyproject.toml` (`==`).** Pins direct
  dependencies only; transitives still float; loses the policy/fact
  separation between declared ranges and locked resolution.

## Consequences

- The shipped dependency tree becomes a reviewed artifact: the
  `uv.lock` diff is what ships, and the per-release SBOM becomes
  predictable rather than discovered post-build.
- Dependabot PRs for gateway/api become concrete pinned bumps that
  mechanical checks can vet; the open range-widening PR family
  (#308, #306, #177, #175, #131) is superseded and closed by
  maintainers after the migration lands.
- One-time costs in the implementation PR: two large generated
  `uv.lock` diffs; Dockerfile and CI changes; contributor-doc updates
  (`CONTRIBUTING.md`, `gateway/README.md`, `api/README.md` move from
  `pip install -e ".[dev]"` to `uv sync`);
  `docs/security/dependencies.md` gains the lockfile story.
- The implementation PR spans gateway + api + CI; this ADR is the
  single anchor spanning those subsystems and is cited from that PR.
- Follow-up (tracked separately, not decided here): the web image
  consuming the fork's upstream-maintained `uv.lock` instead of
  `requirements.txt`.

---

*Drafted by lq-maintainer-agent v0.2.0 from the issue #310 decision
ledger; reviewed and proposed for committee comment by houfu
(Ang Hou Fu) (proposal, issue #310).*
