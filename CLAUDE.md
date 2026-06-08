# Orientation for Claude Code (and other coding assistants)

> **Purpose:** Ground orientation for any agentic coding assistant working on the LQ.AI codebase. Read this first; it points at the right reference for any decision and lays out the project's standards in one place.
>
> **Audience:** Claude Code, Cursor, Aider, or any human or agent making implementation decisions. Read in full before the first contribution; refer back as needed.
>
> **New here?** Start with the [cold-start guide for coding agents](docs/contribute/coding-agent-onboarding.md) — it gives you the read-order, the build loop, the dev-environment hard rules, and how to take a roadmap item to a merged PR. Then keep this file open as your decision reference.

---

## What this project is

LQ.AI is an open-source AI platform for in-house legal teams. Self-hosted; bring-your-own-keys; runs in the operator's environment. Skills are open-source work product, not closed prompts. The Inference Gateway is the security boundary — the only component holding privileged provider API keys.

The project's reason for existing — and its central design constraint — is **transparency**. Every artifact that shapes the user experience is visible work product. A skill that produces a wrong answer should be readable, debuggable, and forkable by the user who relies on it. This is not a marketing principle; it is an architectural commitment that affects every implementation decision.

Read [README.md](README.md) for the public-facing description. Read [docs/PRD.md §1.3 Transparency as a Founding Principle](docs/PRD.md#13-transparency-as-a-founding-principle) for the full philosophical grounding.

---

## Decision routing

When you face a decision while implementing, the canonical reference is — in priority order:

1. **The PRD** ([docs/PRD.md](docs/PRD.md)) — for product, capability, and architectural decisions.
2. **The OpenAPI sketches** ([docs/api/backend-openapi.yaml](docs/api/backend-openapi.yaml), [docs/api/gateway-openapi.yaml](docs/api/gateway-openapi.yaml)) — for endpoint shapes, request/response schemas, status codes.
3. **The database schema** ([docs/db-schema.md](docs/db-schema.md)) — for tables, columns, indexes, constraints.
4. **The gateway configuration example** ([gateway.yaml.example](gateway.yaml.example)) — for the gateway's configuration shape.
5. **The implementation order** ([docs/M1-IMPLEMENTATION-ORDER.md](docs/M1-IMPLEMENTATION-ORDER.md)) — for which task is next and what its acceptance criteria are.
6. **The skill-authoring guide** ([docs/skill-authoring-guide.md](docs/skill-authoring-guide.md)) — for skill conventions.
7. **CONTRIBUTING.md** ([CONTRIBUTING.md](CONTRIBUTING.md)) — for code style, testing, PR process.

If a decision is not anchored in any of these, **stop and ask** rather than guess. The right move is usually:

1. Document the decision in the appropriate place (PRD §9 if it's forward-looking; an ADR in `docs/adr/` if it's structural; CLAUDE.md if it's a workflow convention).
2. Resume implementation.

This is more friction than letting an agent decide independently, and that friction is worth it. The cost of an undocumented decision compounds across every subsequent task that relates to it.

---

## What the codebase looks like

```
lq-ai/
│
├── api/                # FastAPI backend service (Python)
├── gateway/            # Inference Gateway service (Python)
├── web/                # OpenWebUI fork (TypeScript/JavaScript)
├── word-addin/         # Office.js Word add-in (M3)
├── tests/              # Cross-cutting integration tests
├── scripts/            # Operational scripts (backfills, one-time tools)
│
├── skills/             # The 10 starter skills (filesystem-canonical)
│   ├── nda-review/
│   ├── msa-review-saas/
│   └── ...
│
├── docs/               # PRD, architecture, contribution guides, schemas
├── deploy/             # Helm chart, deployment recipes
└── docker-compose.yml
```

Each subsystem (`api/`, `gateway/`, `web/`) is a self-contained service. They talk over HTTP using OpenAPI-defined contracts. There is no shared in-process code — adapters cross the boundary explicitly.

---

## Code style

### Python (`api/`, `gateway/`, `scripts/`)

- **Formatter:** `ruff format` (Black-compatible).
- **Linter:** `ruff check` with the project's `ruff.toml`.
- **Type checker:** `mypy` strict mode for `gateway/`; standard mode for `api/`.
- **Type annotations:** required on all public functions and class methods.
- **Async:** prefer `async def` for I/O-bound code; use `httpx.AsyncClient`, not `requests`.
- **Exceptions:** use the `lq_ai.errors` exception hierarchy; do not raise bare `Exception`.

### JavaScript / TypeScript (`web/`)

- **Formatter:** Prettier per `.prettierrc`.
- **Linter:** ESLint per `.eslintrc`.
- **TypeScript:** required for new files; legacy `.js` files migrate gradually.
- **Framework:** SvelteKit. The `web/` subdirectory is a fork of OpenWebUI, which is a SvelteKit app — extensions and customizations stay in Svelte. We do **not** mix React into `web/`. The Word add-in (`word-addin/`, M3) uses Office.js with React; the `web/` codebase does not.
- **Component conventions:** match the OpenWebUI conventions for shared components; use the project's design system primitives rather than ad-hoc Tailwind.

### Both

- **Imperative-mood commit messages** ("Add X" not "Added X").
- **DCO sign-off** required on every commit (`git commit -s`).
- **Reference issues** in commit body: `Closes #123`, `Refs DE-103`.

Full conventions in [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Testing

Coverage target is 80% across `api/` and `gateway/`. CI enforces no-decrease.

- **Unit tests** — fast, no external deps. `pytest` in each subsystem's `tests/` folder.
- **Integration tests** — run against real Postgres in Docker. Provider integration gated behind `pytest -m provider`.
- **End-to-end tests** — Playwright against a deployed stack. Runs on every PR.

Bug fixes include a regression test. New API endpoints include unit tests for handler logic, integration tests for the endpoint, and OpenAPI schema-conformance tests.

Detailed test strategy in [docs/test-strategy.md](docs/test-strategy.md) (M1 deliverable).

---

## Working with skills (special case)

Skills containing legal substance are **not** ordinary code contributions. They go through:

1. **Claim** — file or comment on a tracking issue.
2. **Draft** — author the SKILL.md, reference files, and at least one worked example.
3. **Attest** — practicing-attorney attestation paragraph in PR description.
4. **Review** — practicing attorney + engineer review.
5. **Merge** — only after both reviews pass.

If an agent is generating skill content, this process still applies — the human contributor is the attesting party. Agents do not attest.

Detailed skill contribution path in [skills/CONTRIBUTING.md](skills/CONTRIBUTING.md). Authoring conventions in [docs/skill-authoring-guide.md](docs/skill-authoring-guide.md).

---

## Security-sensitive paths

These paths require security review per [.github/CODEOWNERS](.github/CODEOWNERS):

- `gateway/**` — the security boundary.
- `docs/security/**` — security artifacts.
- `.github/workflows/**` — CI; supply-chain attack surface.
- Any change touching authentication, authorization, audit logging, or cryptographic implementations.

If you are working in any of these areas, your PR is auto-routed to security reviewers and held until they approve.

**Vulnerabilities** are not contributed via PR. They go through the disclosure process in [SECURITY.md](SECURITY.md).

---

## What good output looks like

A few principles that compound across this codebase:

### 1. Decisions are explicit, not implicit

If you find yourself making an unstated assumption ("I'll just use Pydantic v2"), stop. Either:

- The PRD says Pydantic v2 → use it without comment.
- The PRD doesn't say → make the decision once, document it (probably an ADR), use it everywhere consistently.

The failure mode is not "wrong decision"; the failure mode is "different decisions in different files."

### 2. Tests are part of the change

A new endpoint without a unit test is half a change. A bug fix without a regression test invites the same bug to come back. Tests are not optional; they are coupled to every change.

### 3. Documentation is part of the change

If you add a feature, the PRD section that describes the feature must be updated. If you change an endpoint, the OpenAPI sketch must be updated. If you add a column, the DB schema doc must be updated. The PR is incomplete without these.

### 4. The conservative posture extends to engineering

Don't overclaim what was built. If the citation engine works for PDFs but not yet for DOCX, don't write "the citation engine handles all document types" — write "the citation engine handles PDF; DOCX is M2." Documentation should be honest about state.

### 5. The skills are work product

Skills are the canonical artifact of value (per PRD §7.1). When implementing skill-related capabilities, the bar is "this works correctly when an in-house lawyer uses it on real documents in their actual practice." Not "this passes the tests" — that's necessary but not sufficient.

---

## What good agent behavior looks like

A few specific patterns that work well for agentic implementation on this project:

### The build loop

Run this for every non-trivial change — it is battle-tested across M1–M4 and the post-v0.4.0 integration run:

1. **Verify the ask against the code first** — before writing anything. Most requests carry a wrong premise or a wider blast radius than reported; read the cited files and confirm the problem is real and where the asker thinks it is.
2. **Surface the forks** — if the task hides an architectural / product / authz decision, a scope expansion, or a deferral, stop and put the options (with a recommendation) to the maintainer. Don't decide unilaterally.
3. **Build in reviewed increments** — independent tasks, each: implement → spec-compliance review → code-quality review → fix → re-review. (The `superpowers:subagent-driven-development` skill encodes this.)
4. **Run the gates yourself** — evidence before claims (see Testing + the collision guards below).
5. **Ship** — `git commit -s` + the co-author trailer, push **both** remotes (`origin` + `tucuxi`, kept identical on `main`), open the PR, watch CI, merge per the gating rule, report the squash SHA.

The full step-by-step, including merge-gating and dev-environment rules, is in the [cold-start guide](docs/contribute/coding-agent-onboarding.md).

### Read before writing

Before implementing a task, read:

1. The relevant PRD section.
2. The relevant OpenAPI section if the task touches an API endpoint.
3. The relevant DB schema section if the task touches the database.
4. Any existing implementation in the same area (don't rebuild what exists).

### Common pitfalls (catch at write-time, not test-time)

A few traps that have bitten this codebase more than once. Each has a fix recipe; follow it the first time and the bug never surfaces in your branch.

**`DELETE` endpoints returning `204 No Content`** — FastAPI's default `JSONResponse` is body-emitting and asserts at import time when `status_code=204`. The assertion (`Status code 204 must not have a response body`) fires during test collection, collapsing the whole test suite — not just the new endpoint's tests. Recurred between M3-C2 (fix in commit `c613c43`) and M3-D4 because the recipe lived only in code comments.

Recipe:

```python
from fastapi import Response, status

@router.delete(
    "/things/{thing_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,                       # critical — overrides default JSONResponse
)
async def soft_delete_thing(...) -> Response:
    ...
    return Response(status_code=status.HTTP_204_NO_CONTENT)  # explicit empty return
```

Both `response_class=Response` AND the explicit `return Response(...)` are required. Omitting either resurfaces the assertion.

**Test-suite collision guards** — these crash the *whole* api suite at collection, not just the offending test:

- A new fully-implemented route must be added to `IMPLEMENTED_ROUTES` (`api/tests/test_endpoints.py`) **and** bump the exact path count + `EXPECTED_PATHS` set in `api/tests/test_openapi.py`. The count is pinned; an off-by-one fails collection.
- `docs/api/backend-openapi.yaml` does **not** parse with plain `yaml.safe_load` (pre-existing) — `test_openapi.py` is the authoritative conformance check; run it rather than eyeballing.
- Decimal cost fields serialize as JSON **strings** — type them `string`, not `number`.

### Dev-environment hard rules

These corrupt the running dev stack or crash CI if violated:

- **NEVER run host-side `alembic upgrade` against the live dev DB** (`127.0.0.1:15432/lq_ai`) — it desyncs the running stack and crash-loops the api trio. Verify migrations on a throwaway `pgvector/pgvector:pg16` container (conftest auto-migrates); apply to the dev stack by rebuilding the workers, not host alembic.
- **When a migration lands, rebuild `api` + `arq-worker` + `ingest-worker` together** — stale siblings crash-loop on a revision mismatch.
- **NEVER `docker compose down -v`** — it wipes volumes including expensive-to-recreate acceptance data. Rebuild a single service instead.
- **The `web` container serves a pre-built static bundle (no HMR)** — rebuild `web` before debugging a UI change that "isn't appearing."
- **Run BOTH `ruff format` and `ruff check`** locally — CI runs them as separate gates.

### Surface ideas as DE-XXX

When a useful idea surfaces that is out of scope for the current task, file it as a deferred enhancement (DE-XXX) in PRD §9. Do not expand the task to incorporate the idea; preserve the focus, defer the idea.

### Stop on architectural questions

If a task surfaces an architectural decision that wasn't anticipated, stop. Don't make the decision unilaterally and continue. The cost of stopping is minutes; the cost of an undocumented architectural choice is hours-to-days of subsequent rework.

### Verify against the documented verification step

Each task in [M1-IMPLEMENTATION-ORDER.md](docs/M1-IMPLEMENTATION-ORDER.md) has a verification step. Do not consider a task complete until verification passes. Self-verification of "I think this works" is not sufficient; the documented verification is the contract.

### Don't add libraries without justification

The project's dependency tree is part of the SBOM and the supply-chain attack surface. New dependencies need to be justified — what does this give us that we couldn't reasonably build, and is the trade-off worth the SBOM entry? "It would be slightly more elegant" is not justification.

---

## File-discovery shortcuts

When you need to find something quickly:

| Looking for | Look at |
|---|---|
| Project description | [README.md](README.md) |
| Capability specifications | [docs/PRD.md §3](docs/PRD.md#3-capability-specifications) |
| Inference Gateway internals | [docs/PRD.md §4](docs/PRD.md#4-the-lq-ai-inference-gateway) |
| Architecture overview | [docs/architecture.md](docs/architecture.md) |
| API endpoints | [docs/api/backend-openapi.yaml](docs/api/backend-openapi.yaml) |
| Database tables | [docs/db-schema.md](docs/db-schema.md) |
| Gateway configuration | [gateway.yaml.example](gateway.yaml.example) |
| Implementation tasks | [docs/M1-IMPLEMENTATION-ORDER.md](docs/M1-IMPLEMENTATION-ORDER.md) |
| Code style | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Skill conventions | [docs/skill-authoring-guide.md](docs/skill-authoring-guide.md) |
| What's already implemented | Existing code in `api/`, `gateway/`, `web/` |
| What's deferred | [docs/PRD.md §9](docs/PRD.md#9-deferred-enhancements-and-identified-future-work) |
| Contributor-pickup mini-PRDs | [docs/proposals/](docs/proposals/) |
| Security policy | [SECURITY.md](SECURITY.md) |
| Conduct policy | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) |

---

*Maintained by the maintainer team. Updates land alongside structural project changes.*
