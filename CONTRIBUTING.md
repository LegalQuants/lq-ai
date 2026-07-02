# Contributing to LQ.AI

Thanks for your interest in contributing. This document covers contributions to **code, infrastructure, deployment recipes, and general project documentation**. Skills containing legal substance follow a different process documented in [`skills/CONTRIBUTING.md`](skills/CONTRIBUTING.md) — that path includes attestation requirements and practicing-attorney review that don't apply to engineering work.

---

## Quick start

```bash
git clone https://github.com/legalquants/lq-ai.git
cd lq-ai
cp .env.example .env
# Edit .env with at least one LLM provider API key (or use local profile)
docker compose up -d              # Mode 1
# OR
docker compose --profile local up -d   # Mode 2
```

**Running backend tests in Docker** (recommended when you don't want a local Python venv):

```bash
# api/Dockerfile.dev installs [dev] extras (pytest, respx, pytest-cov, …)
# on top of the production image so the test suite runs in-container.
docker build -f api/Dockerfile.dev -t lq-ai-api-dev api/
docker run --rm lq-ai-api-dev python -m pytest tests/ -x
```

The production image (`api/Dockerfile`) does **not** install dev extras to keep
the runtime surface area minimal. Use `Dockerfile.dev` for any work that requires
running the test suite inside a container.

For backend development without Docker:

```bash
# Backend
cd api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Inference Gateway (separate service)
cd gateway
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8001

# Web (OpenWebUI fork)
cd web
npm install
npm run dev
```

Run the test suite before submitting:

```bash
# Python (api/, gateway/)
pytest                    # unit + integration
pytest -m "not provider"  # skip provider-integration tests (require API keys)
ruff check .
ruff format --check .
mypy .

# JavaScript (web/)
npm test
npm run lint
npm run typecheck
```

---

## What to work on

> **Working with an AI coding agent (Claude Code, Cursor, …)?** Start it on the [cold-start guide for coding agents](docs/contribute/coding-agent-onboarding.md) — read-order, the build loop, dev-environment hard rules, and how to take a roadmap item to a merged PR.

The project's [Deferred Enhancements list (PRD §9)](docs/PRD.md#9-deferred-enhancements-and-identified-future-work) catalogs ~50+ bounded enhancements where the architectural slot exists and the implementation is well-defined. Items tagged **P1** are particularly welcome for v1.5+. A few that are well-shaped for first-time contributors:

- **DE-013 Saved Prompts Library** (S effort) — per-user saved prompts in a sidebar; CRUD plus promote-to-skill.
- **DE-015 Voice / Dictation Input** (S) — Web Speech API toggle on the chat input.
- **DE-031 Reverse proxy / TLS recipes** (S) — document Caddy / Traefik / nginx integration patterns.
- **DE-103 IP allowlisting and geo-restriction** (S) — configurable IP allowlist for the web app and Word add-in.
- **DE-105 Outbound proxy support** (S) — `HTTPS_PROXY` / `NO_PROXY` configuration in the Inference Gateway.

For larger items (M and L effort), please **file an issue first** to discuss approach before opening a PR. We do not want anyone to invest weeks of work that turns out to conflict with an architectural choice or another in-flight contribution.

For features not on the deferred-enhancements list, please file an issue describing the use case and the proposed approach. Pull requests for unfiled features are welcome but at higher risk of bouncing if they conflict with the project's direction.

---

## Pull request process

1. **Fork the repository** and create a branch from `main`. Branch names should describe the work: `feat/saved-prompts`, `fix/citation-engine-empty-result`, `docs/clarify-tier-config`.
2. **Make your changes** following the code style and testing requirements below.
3. **Add or update tests** covering the change. Pytest coverage target is 80%; PRs that drop coverage materially will be flagged.
4. **Update documentation** — the PRD, README, skill-authoring guide, or capability docs as relevant. If your change affects user-facing behavior, the docs need to reflect it.
5. **Sign your commits** per the DCO requirement (see [Sign-off](#sign-off-developer-certificate-of-origin) below). PRs without DCO sign-off cannot be merged.
6. **Open the PR** with a description that explains what changed, why, and how to verify. Link to any relevant issue or DE-### entry in the PRD.
7. **Respond to review** — maintainers will review within ~5 business days for most PRs, faster for security or bug fixes. Substantive review feedback usually requires changes; small style nits can be deferred to follow-ups.
8. **CI must pass** — tests, linting, type checks, container builds, security scans (Trivy, CodeQL). PRs with failing CI are not merged.
9. **At least one maintainer approval** is required to merge. For changes affecting multiple subsystems, two approvals are preferred.

Squash-and-merge is the default; merge commits are reserved for cases where the per-commit history meaningfully aids future debugging.

---

## Sign-off (Developer Certificate of Origin)

LQ.AI uses the [Developer Certificate of Origin (DCO)](https://developercertificate.org/) — not a CLA. The DCO is a lightweight assertion that you have the right to contribute the work under the project's Apache 2.0 license. Industry standard, sufficient legal cover, no separate paperwork.

Every commit must be signed off:

```bash
git commit -s -m "Your commit message"
```

This adds a trailer to your commit message:

```
Signed-off-by: Your Name <your.email@example.com>
```

The `git config user.email` you sign off as must match the email associated with your GitHub account or be in your verified emails list. CI validates DCO sign-off on every commit; PRs with unsigned commits cannot be merged.

If you forget to sign off, amend your commits before pushing:

```bash
git commit --amend -s --no-edit          # most recent commit
git rebase --signoff main                 # all commits since main diverged
```

---

## Code style

### Python (`api/`, `gateway/`, scripts)

- **Formatter:** `ruff format` (Black-compatible). CI rejects unformatted code.
- **Linter:** `ruff check` with the project's `ruff.toml` config. Most pyflakes / pycodestyle / pyupgrade / bugbear rules enforced.
- **Type checker:** `mypy` in strict mode for the gateway; standard mode for the backend (strict-mode migration is a tracked enhancement, DE-### TBD).
- **Type annotations:** required on all new public functions and class methods. Internal helpers can omit return types where obvious; public API contracts require full annotations.
- **Imports:** sorted by `ruff` (isort-compatible). Standard library first, then third-party, then local.
- **Docstrings:** required on public modules, classes, and functions in the gateway and backend. Format: triple-quoted, summary line, blank line, detail. Descriptive variable names reduce the need for inline comments.
- **Async:** prefer `async def` for I/O-bound functions; use `httpx.AsyncClient` rather than `requests`. Sync helpers are fine for CPU-bound or test code.
- **Exceptions:** raise typed errors from each subsystem's `app.errors` module ([api/app/errors.py](api/app/errors.py), [gateway/app/errors.py](gateway/app/errors.py)) — `LQAIError` and its subclasses. Do not raise bare `Exception`. Per [ADR 0003](docs/adr/0003-error-handling.md), the two subsystems each ship parallel hierarchies; the cross-subsystem contract is the error-code enum in the OpenAPI sketches plus the conformance test in [`tests/test_error_code_contract.py`](tests/test_error_code_contract.py).

### JavaScript / TypeScript (`web/`)

- **Formatter:** Prettier with the project's `.prettierrc`. CI rejects unformatted code.
- **Linter:** ESLint with the project's `.eslintrc`. TypeScript-specific rules enforced for `.ts` files; Svelte rules for `.svelte` files.
- **TypeScript:** required for new files; gradual migration of legacy `.js` files welcome but not required for unrelated changes.
- **Framework:** SvelteKit. The `web/` codebase is a fork of OpenWebUI, which is a SvelteKit app — extensions and customizations stay in Svelte. Do **not** introduce React into `web/`. The Word add-in (`word-addin/`, M3) uses Office.js with React; the `web/` codebase does not.
- **Component conventions:** match the OpenWebUI conventions for shared components; use the project's design system primitives rather than ad-hoc Tailwind.

### Configuration files

- **YAML:** 2-space indent. Use anchors and aliases sparingly; prefer explicit duplication over clever YAML.
- **TOML:** for Python project configuration (`pyproject.toml`, `ruff.toml`).
- **Markdown:** GitHub-flavored. Headings use `#`, not `===`. Wrap at ~100 chars in prose; do not wrap inside code blocks.

### Commit messages

- **Imperative mood.** "Add tier-config endpoints" not "Added tier-config endpoints".
- **Subject under ~70 chars**; body wrapped at ~72 chars.
- **Reference issues** in the body: `Closes #123`, `Refs DE-103`.
- **No marketing language** in commit messages. Describe what changed and why; the changelog is for marketing.

---

## Testing requirements

The project takes testing seriously because the substantive correctness of the legal-AI work product depends on it.

### Coverage target

Pytest coverage target is **80%** across `api/` and `gateway/`. The CI configuration enforces no-decrease coverage on PRs — your PR cannot drop overall coverage. New code should be covered by tests; bug fixes should include a regression test that fails before the fix and passes after.

### Test categories

- **Unit tests** — fast, no external dependencies. Run on every commit. Mock the Inference Gateway, the database, and any provider APIs.
- **Integration tests** — run against a real Postgres instance (Docker-launched in CI) and the actual Inference Gateway against a mocked provider. These exercise multi-component flows.
- **Provider-integration tests** — gated behind `pytest -m provider` and require provider API keys configured. CI runs these nightly against a small subset; contributors are not expected to run them locally unless their changes specifically affect provider integration.
- **End-to-end tests** — Playwright tests covering happy paths in the web UI. Run on every PR.
- **Fuzzing** — the Inference Gateway's OpenAI compatibility surface is fuzzed continuously in CI against the OpenAI API spec.

### Test stack conventions (Python)

Locked-in choices so new tests don't drift across `api/` and `gateway/`. Changes to these defaults need a PR with rationale.

- **Test runner:** `pytest`. No alternative.
- **Async tests:** `pytest-asyncio` with `asyncio_mode = "auto"` configured in `pyproject.toml`. Async test functions are written as `async def test_*(...)` without a per-test decorator. We picked `pytest-asyncio` over `anyio`'s test plugin because the project's runtime is asyncio-only — we never need trio compatibility, and `pytest-asyncio` has the larger ecosystem.
- **HTTP client in tests:** `httpx.AsyncClient` with `ASGITransport` for in-process FastAPI tests; no `TestClient`. Real-network calls in tests are forbidden outside the `provider`-marked tests.
- **Test database:** session-scoped fixture runs Alembic migrations once against a per-CI-run Postgres database; per-test fixture wraps each test in a transaction that rolls back on teardown. No truncation between tests; no test-specific migrations. Both subsystems share `tests/conftest.py` patterns.
- **Test data:** factory pattern using `polyfactory` for Pydantic models; no hand-written fixture dictionaries except for canonical examples that stay readable inline.
- **Provider mocking:** `respx` for httpx-level mocks; record-replay fixtures for end-to-end provider flows under `tests/fixtures/providers/`.
- **Time and randomness:** `freezegun` for time, `random.seed(0)` at the top of any test that uses randomness. Flaky tests are not tolerated; if you find one, fix it or skip it with a tracked issue.

### Test markers

Standard markers — declared in each subsystem's `pyproject.toml` so `pytest --strict-markers` will reject typos:

| Marker | Purpose | Default behavior |
|---|---|---|
| `unit` | Pure unit, no I/O | Always run |
| `integration` | Hits Postgres, Redis, MinIO, or the Gateway | Run on every PR |
| `provider` | Hits a real LLM provider; requires API key | Skipped unless `-m provider` |
| `slow` | Takes > 5s; usually integration with realistic data | Run nightly, optional locally |
| `e2e` | Playwright end-to-end | Run on every PR via the Playwright job |

`pytest -m "not provider and not slow"` is the local-loop default; `make test` runs this.

### JavaScript/TypeScript tests (`web/`)

The OpenWebUI fork is SvelteKit. New tests use **Vitest** (Svelte's standard) for unit and component tests; Playwright for end-to-end. Don't introduce Jest unless there's a concrete reason — Vitest is closer to SvelteKit's tooling and has fewer ESM-vs-CJS pitfalls.

- **Component tests:** `@testing-library/svelte` with Vitest.
- **Type checking in tests:** test files are `.ts` / `.svelte` and pass `npm run typecheck`.
- **Snapshot testing:** discouraged for component output; preferred for stable structured data (e.g., backend-returned shapes).

### When to write what kind of test

| Change type | Required tests |
|---|---|
| Bug fix | Regression test (unit if possible; integration if the bug is multi-component) |
| New API endpoint | Unit tests for the handler logic + integration test exercising the endpoint end-to-end + OpenAPI schema-conformance test |
| New provider adapter | Provider-integration tests (gated behind `-m provider`); unit tests with mocked provider responses for the request/response shape |
| New skill (engineering side; the skill content itself goes through the skills/CONTRIBUTING.md path) | A worked-example test verifying the skill renders and produces structured output of the expected shape |
| New deployment recipe | Documented steps + a CI verification job that runs the recipe in a clean environment |
| Documentation only | No new tests; CI lints markdown |

---

## Security

If you discover a security vulnerability, **please do not file a public GitHub issue**. Follow the disclosure process in [`SECURITY.md`](SECURITY.md):

1. Email security@legalquants.com (or the address documented in `SECURITY.md` at the time you read this) with a description of the vulnerability and reproduction steps. GPG key available at the URL in `SECURITY.md`.
2. We will acknowledge receipt within 72 hours.
3. We will fix critical issues within 30 days and coordinate disclosure timing with you.
4. After fix and disclosure, the advisory is published on GitHub Security Advisories with credit to the reporter (unless you prefer to remain anonymous).

The project includes safe-harbor language committing not to pursue legal action against good-faith security researchers who follow the coordinated-disclosure process.

For security-affecting *changes* (not vulnerabilities — changes you want to propose to the project that have security implications), file a normal PR but flag the security implications in the description and tag a maintainer for direct review. Examples: changes to authentication flows, audit logging, the Inference Gateway's tier-derivation logic, the Anonymization Layer, encryption configuration, supply-chain artifacts.

---

## Documentation expectations

If your change affects user-facing behavior, the documentation must be updated in the same PR. The relevant docs:

- **`docs/PRD.md`** — the canonical specification. Capability changes go here. PRD edits should follow the existing structure (see PRD's own changelog convention).
- **`README.md`** — the front-door doc. Update if your change affects how users get started, what the project does, or the high-level capability list.
- **`docs/skill-authoring-guide.md`** — if your change affects how skills work or what's expected of skill authors.
- **`docs/playbook-authoring-guide.md`** — if your change affects Playbooks.
- **`docs/deployment-cookbook.md`** — if your change affects deployment.
- **`docs/compliance/`** — if your change affects compliance posture (e.g., new audit-log field, new tier-handling logic, new data-flow path that affects a control mapping).
- **`docs/security/`** — if your change affects security posture (e.g., new dependency that affects the SBOM story, new endpoint that affects the threat model).
- **API changes** — the OpenAPI schema is generated from the FastAPI handlers; update handlers, run `make openapi` to regenerate the schema, and commit the regenerated schema.

PRs that change behavior without updating docs will be asked to add the doc changes before merge.

---

## Porting skills from external sources

Skills may be ported from external corpora (law firm knowledge bases, open-source legal-AI repositories, academic datasets, etc.) if the licence and provenance allow. Porting is a special case of the skill-contribution workflow documented in [`skills/CONTRIBUTING.md`](skills/CONTRIBUTING.md); the additional requirements below apply **in addition** to the standard skill-authoring steps.

### Attestation

Every ported skill PR description must include an attestation paragraph signed by a practicing attorney (the PR author, a co-author, or a named legal reviewer). Template:

> I, [Name], a licensed attorney in [jurisdiction(s)], attest that:
>
> 1. I have reviewed the ported skill against the original source material and confirm the substance is accurately represented.
> 2. The upstream licence ([SPDX identifier]) permits this use under the terms stated in NOTICES.md.
> 3. Any jurisdictional limitations of the source material are reflected in the skill's `jurisdiction:` frontmatter field.
> 4. This skill does not constitute legal advice and is labelled accordingly in the skill frontmatter.

Pull requests without a complete attestation paragraph will not be merged. Agents do not attest — the human contributor is the attesting party.

### Provenance preservation

The upstream source must be recorded in three places:

1. **Skill frontmatter** — add a `source:` key under the `lq_ai:` extension block:

   ```yaml
   lq_ai:
     source:
       uri: "https://example.com/original-skill-repo"
       license: "Apache-2.0"
       retrieved_at: "2026-05-14"
   ```

2. **NOTICES.md** — add a row to the per-skill provenance table at the repo root. See [`NOTICES.md`](NOTICES.md) for the column format.

3. **Commit message** — include the upstream URI in the commit body:
   `Ported from https://example.com/original-skill-repo (Apache-2.0).`

### Attribution requirements

If the upstream source requires attribution (e.g., a CC-BY licence), the attribution text must appear in:
- The skill's `SKILL.md` under an "Attribution" heading.
- The NOTICES.md row for that skill.

Questions about licence compatibility should be directed to the maintainer team before opening the PR. When in doubt, do not port — create a new skill inspired by the source instead.

---

## Reviewer expectations

Reviewers will look for:

1. **Correctness** — does the change do what it claims to do?
2. **Tests** — does the change have adequate test coverage?
3. **Style** — does the change follow the project's conventions?
4. **Clarity** — is the change readable and maintainable?
5. **Compatibility** — does the change preserve backward compatibility, or if not, is the breaking change documented and justified?
6. **Security implications** — does the change introduce new attack surface, weaken existing protections, or change the data-flow path? If so, has it been thought through?
7. **Performance implications** — does the change add latency or memory overhead in the request path? If so, is the trade-off documented?
8. **Documentation** — has the relevant doc been updated?

Reviewers are also expected to be:

- **Constructive** — feedback is about the work, not the contributor. Suggest specific changes rather than abstract complaints.
- **Timely** — initial review within 5 business days for most PRs; follow-up review within 2 days. Communicate if you cannot meet that timeline.
- **Decisive** — approve, request changes, or comment with a specific question. Do not leave PRs in limbo.

If a PR has been waiting for review longer than the timeline above, please ping a maintainer in the PR or in `#contributors` on Discord.

---

## Code of Conduct

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/). The full text is in [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Briefly: be kind, assume good faith, focus on the work, and engage with disagreements substantively rather than personally.

Reports of unacceptable behavior go to conduct@legalquants.com. Reports are confidential and will be reviewed by maintainers; meaningful violations result in escalating consequences from a private warning through to a permanent ban.

---

## License

By contributing to LQ.AI, you agree that your contributions will be licensed under the project's [Apache License 2.0](LICENSE). The DCO sign-off (above) is your assertion that you have the right to contribute the work under that license.

---

## Questions?

- **General questions** → GitHub Discussions or `#contributors` on Discord.
- **Bug reports** → GitHub Issues with the `bug` label and a reproduction case.
- **Feature requests** → GitHub Issues with the `enhancement` label; reference the [PRD §9 Deferred Enhancements](docs/PRD.md#9-deferred-enhancements-and-identified-future-work) entry if one exists.
- **Security** → security@legalquants.com (see [`SECURITY.md`](SECURITY.md)).
- **Skill contributions** → see [`skills/CONTRIBUTING.md`](skills/CONTRIBUTING.md) — the skill-specific contribution path.

Thanks for contributing.
