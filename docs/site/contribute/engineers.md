---
title: On-ramp for an engineer
description: The build loop, the gates CI runs, DCO sign-off, and where security review is required.
audience: [contributor]
status: draft
sources:
  - .github/workflows/ci.yml
  - docs/test-strategy.md
  - CONTRIBUTING.md
  - CLAUDE.md
  - .github/CODEOWNERS
sidebar:
  order: 5
---

This page gets you from a clone to a pull request that passes review the first time.

## Read before you write

[`CONTRIBUTING.md`](../../../CONTRIBUTING.md) covers quick start, code style, and the PR process in full; read it before your first change rather than skimming for the one command you need. If you are working with a coding agent rather than typing every line yourself, point it at the [coding-agent on-ramp](coding-agents.md) — it is the same information, ordered for a cold-start read.

## The build loop

The project's own build loop, run for every non-trivial change: **verify the ask against the code first** — most requests carry a wrong premise or a wider blast radius than reported, so read the cited files before writing anything. **Surface forks** — if the change hides an architectural, product, or authorization decision, stop and put the options to a maintainer rather than deciding alone. **Build in reviewed increments** rather than one large diff. **Run the gates yourself** — a claim of "done" needs the command output behind it, not a description of what should happen. **Ship** by pushing to your own fork and opening a pull request; external contributors never self-merge.

## The gates

```bash
make lint          # Python ruff/mypy + Web scoped Svelte check
make format-check   # Python ruff format --check
make test           # Python local-loop suites + Web Vitest
```

Current PR CI runs four jobs — API (`uv lock --check`, `ruff check`, `ruff format --check`, `mypy app`, `pytest -n auto -q` against a real pgvector Postgres service, each xdist worker on its own session-scoped disposable database), Gateway (the same Python gates, `mypy` in `--strict` mode, `pytest -q`), Web (`npm run check:lq-ai`, `npm run test:frontend -- --run`), and Release image (`scripts/release-image-check.sh`, the guard in `api/Dockerfile.release` that fails the build unless the `skills/community` submodule's manifests are present). A path-triggered stack-smoke workflow also runs when a change touches dependency manifests, lockfiles, Dockerfiles, compose, or an API migration — it builds every image, boots the full stack, and holds for a soak period to catch boot-time failures the in-process suites miss. Current PR CI does not enforce a coverage threshold or run browser end-to-end tests — the per-surface coverage matrix and the Cypress gap are documented in [`docs/test-strategy.md`](../../test-strategy.md); a new endpoint still needs unit, integration, and OpenAPI-conformance tests, and a bug fix needs a regression test.

## DCO sign-off

Every commit needs a sign-off:

```bash
git commit -s -m "Add tier-config endpoint"
```

This appends a `Signed-off-by:` trailer asserting you have the right to contribute the work under the project's Apache 2.0 license — a lightweight alternative to a CLA. The `git config user.email` you sign off as must match your GitHub account's email or a verified email on it. Pull requests with unsigned commits are not merged; `git commit --amend -s --no-edit` or `git rebase --signoff main` fixes a forgotten sign-off before you push.

## Where security review is required

[CODEOWNERS](../../../.github/CODEOWNERS) routes four paths to the project's security reviewers in addition to the maintainer team: `gateway/**` — the Inference Gateway, the project's only component holding privileged provider API keys — plus `docs/security/**`, `.github/workflows/**`, and `SECURITY.md`. A pull request touching any of those is auto-routed and held until security review approves it. Routing is by path only, so if your change touches authentication, authorization, audit logging, or cryptographic implementations somewhere else in the tree, say so in the PR description and request security review yourself — CLAUDE.md treats those as security-review areas, but no file routes them automatically.

Found a vulnerability rather than making a change? That does not go through a pull request — see [security disclosure](../trust/security-disclosure.md) for the process.

## Next

- [Dev-environment guide](dev-environment.md) — running `api/`, `gateway/`, and `web/` locally
- [Point a coding agent at the repository](coding-agents.md)
- [Code of conduct](code-of-conduct.md)
