# Dependencies & Vulnerability Monitoring

> **Scope:** how LQ.AI manages its dependency tree, monitors for vulnerabilities, and ships updates. Pairs with the SBOM shipped with every release (see [docs/security/releases/README.md](releases/README.md)).

## Dependency review

Per [CLAUDE.md's "Don't add libraries without justification" principle](../../CLAUDE.md), every new dependency added to `api/`, `gateway/`, or `web/` requires an explicit justification in the PR description. The bar is: "what does this give us that we couldn't reasonably build, and is the trade-off worth the SBOM entry?"

For dependencies touching:
- **Authentication / authorization / cryptography** — security-reviewer approval required per [.github/CODEOWNERS](../../.github/CODEOWNERS).
- **LLM-provider SDKs** — Inference Gateway boundary (PRD §4); same auto-routing.
- **Web frontend** — must not introduce React or other framework runtimes alongside SvelteKit; the boundary lives in [ADR 0009](../adr/0009-web-lq-ai-shell-coexistence.md).

## Lockfiles (gateway/, api/)

Per [ADR 0023](../adr/0023-uv-lockfiles-gateway-api.md), `gateway/` and `api/` are locked with [uv](https://docs.astral.sh/uv/). Two layers, deliberately separated:

- **Policy** — `pyproject.toml` keeps the tight range windows with rationale comments (intent: which versions we accept, and why).
- **Fact** — the committed `uv.lock` pins the exact resolved tree, transitives included (what actually ships).

This makes the shipped dependency tree a **reviewed artifact**: container images install with `uv sync --frozen`, so the tree in the image is exactly the tree in the lockfile diff a reviewer approved — the build fails rather than silently re-resolving. CI gates lock freshness with `uv lock --check`, which is the "lockfiles enforced in CI" commitment in the PRD's supply-chain posture (Appendix C risk 10, Appendix E). Dependency PRs therefore carry concrete name+version pairs that mechanical vetting (OSV advisory lookup, release-age cooldown, new-package detection in lockfile churn) can check.

The `web/` subsystem is out of scope here: its Python side still installs from the fork's `requirements.txt`, and consuming the fork's upstream-maintained `web/uv.lock` is a tracked follow-up (see ADR 0023's consequences).

## Automated scanning

Two layers of automated dependency-vulnerability scanning:

1. **GitHub Advisory Database / Dependabot.** [`.github/dependabot.yml`](../../.github/dependabot.yml) configures weekly scans for `api/` (uv), `gateway/` (uv), `web/` (npm), and `.github/workflows/` (actions). High and critical advisories open PRs automatically. For the uv ecosystems, updates arrive as lock-pinned bumps against `uv.lock` with a 7-day release-age cooldown, not range widenings. `web/` is **security-updates only** (`open-pull-requests-limit: 0`): it is a vendored OpenWebUI fork pinned by [ADR 0001](../adr/0001-openwebui-fork-pin.md), so routine version currency arrives with the quarterly rebase rather than between refreshes. Advisories against `web/` packages still open PRs — that limit constrains version updates only.
2. **SBOM scanning.** The SBOM produced by the release workflow (per [docs/security/releases/README.md](releases/README.md)) is in SPDX JSON format and is parseable by any SCA tool. Operators evaluating a specific release can run `grype sbom:./api.spdx.json` (or equivalent) to check the dependency snapshot.

## Update cadence

| Severity | Response time |
|---|---|
| Critical | Patch released within 30 days |
| High | Patch released within 60 days |
| Medium | Folded into the next minor release |
| Low | Folded as convenient |

These mirror the vulnerability-fix commitments in [SECURITY.md](../../SECURITY.md). The cadence applies to both first-party fixes (LQ.AI code) and dependency advisories (upstream library fixes).

## Operator workflows

### Verifying a release's dependency tree

```bash
# Download the SBOM attestation from the registry
cosign download attestation \
  --predicate-type=https://spdx.dev/Document \
  ghcr.io/legalquants/lq-ai-api:vX.Y.Z \
  | jq -r '.payload' | base64 -d | jq '.predicate' > api.spdx.json

# Scan with grype (or any SCA tool)
grype sbom:./api.spdx.json
```

### Pinning to a specific patch version

The Helm chart pins `image.tag` via `values.yaml`. Operators with strict change-management can pin to a specific tag and upgrade explicitly:

```bash
helm upgrade lq-ai ./deploy/helm/lq-ai \
  --set image.tag=v0.2.3 \
  -n lq-ai
```

## Known transitive risks

- **OpenWebUI fork.** `web/` is forked from OpenWebUI at the version pinned in [ADR 0001](../adr/0001-openwebui-fork-pin.md). Upstream advisories affect us; we track them and pull fixes per the cadence above. The fork pin means we don't auto-update with upstream master.
- **pgvector / Postgres.** Vector-index queries are powered by pgvector. Advisories against pgvector are uncommon (it's a thin C extension), but the Postgres major version (16 at M1) follows community LTS.

## Reporting a vulnerability in a dependency

If you find a vulnerability in a dependency that we ship, report it to the upstream project first; advise us via the channel in [SECURITY.md](../../SECURITY.md) so we can fast-track the bump if the advisory is severe enough.
