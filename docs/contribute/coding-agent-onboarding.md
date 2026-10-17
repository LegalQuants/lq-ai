# Cold-start guide for a coding agent (Claude Code & friends)

> **Purpose:** Get a fresh AI coding agent — or a new human contributor working alongside one — from zero to shipping a roadmap item correctly, the first time. This is the connective tissue between the docs that already exist; it does not duplicate them, it tells you the order to read them and the loop to run.
>
> **Read this once, in full, before your first contribution.** Then keep [CLAUDE.md](../../CLAUDE.md) open as your decision reference.

---

## 0. The 60-second orientation

LQ.AI is an **open-source, self-hosted AI platform for in-house legal teams**. Three services talk over HTTP via OpenAPI contracts — no shared in-process code:

- **`api/`** — FastAPI backend (sessions, chats, files, KBs, playbooks, tabular review, the autonomous layer). mypy *standard* mode.
- **`gateway/`** — the Inference Gateway: the **security boundary**, the only component holding privileged provider API keys. mypy **`--strict`**. Changes here get security review.
- **`web/`** — a SvelteKit fork of OpenWebUI. (Svelte only — no React in `web/`; the Word add-in is the only React surface.)

The project's reason for existing is **transparency**: every artifact that shapes the user experience (especially skills) is visible, debuggable, forkable work product. That is an architectural commitment, not marketing — it shows up in how you're expected to build (honest docs, no overclaiming, explicit decisions).

---

## 1. Read-order for a cold start

Read these in sequence before touching code. Each answers a different question:

| Order | Doc | The question it answers |
|---|---|---|
| 1 | [CLAUDE.md](../../CLAUDE.md) | How do I make decisions here? (routing, code style, pitfalls, the build loop) |
| 2 | [docs/HONEST-STATE.md](../HONEST-STATE.md) | What is **actually** built right now vs. planned? (the truth map — trust it over older prose) |
| 3 | [README.md](../../README.md) | What does the product claim to do, publicly? |
| 4 | [docs/architecture.md](../architecture.md) | How do the three services fit together? |
| 5 | [docs/ROADMAP.md](../ROADMAP.md) + [docs/PRD.md §9](../PRD.md#9-deferred-enhancements-and-identified-future-work) | What's next, and what's deliberately deferred (the DE-XXX list)? |
| 6 | [docs/contribute/EASIEST-CONTRIBUTIONS.md](EASIEST-CONTRIBUTIONS.md) + [mini-prds/](mini-prds/) | What's a good first item to pick up? |
| 7 | [CONTRIBUTING.md](../../CONTRIBUTING.md) | Code style, DCO, PR mechanics. |

For a specific task, then narrow: the PRD section for the capability, the OpenAPI sketch if it touches an endpoint, the DB schema if it touches a table, and **any existing code in the same area** (don't rebuild what exists). The full decision-routing priority order is in [CLAUDE.md § Decision routing](../../CLAUDE.md#decision-routing).

---

## 2. The build loop (the part that lived only in tribal memory)

This is how work actually gets shipped here. It is battle-tested across the M1–M4 milestones and the post-v0.4.0 integration run. Run it for every non-trivial change.

```
1. VERIFY THE ASK AGAINST THE CODE — FIRST, before writing anything.
   Nearly every incoming request has a wrong premise or a wider blast
   radius than reported. Read the cited files. Confirm the problem is
   real and is where the asker thinks it is. Report what you actually found.

2. SURFACE THE FORKS — don't unilaterally decide.
   If the task hides an architectural / product / authz decision, or a
   scope expansion, or a deferral — STOP and put the options to the human
   (a recommendation + the trade-offs). The maintainer makes those calls.
   The cost of asking is minutes; an undocumented decision costs hours later.

3. PLAN, then BUILD in reviewed increments.
   Break the work into independent tasks. For each: implement (TDD where it
   fits) → independent SPEC-compliance review → independent CODE-QUALITY
   review → fix → re-review. Fresh context per task keeps reviews honest.
   (The `superpowers:subagent-driven-development` skill encodes this; you
   can also run it by hand.)

4. RUN THE GATES YOURSELF — evidence before claims.
   Never report "done" without the command output. See §4.

5. SHIP.
   Commit with DCO (§5) → push the branch to your own fork → open a PR
   → respond to CI and review. A maintainer performs the merge (§6).
```

Two honesty rules that sit on top of the loop:

- **Surface deferrals and scope expansions as choices.** Don't quietly absorb extra work or quietly drop something. Name it.
- **Don't overclaim in code or docs.** "Handles PDF; DOCX is deferred" — not "handles all documents." If tests fail, say so with the output.

---

## 3. Hard rules about the dev environment (learn these before you run anything)

These have each bitten this codebase. Violating them corrupts the running dev stack or crashes CI.

- **NEVER run host-side `alembic upgrade` against the live dev DB** (`127.0.0.1:15432/lq_ai`). That IS the running stack's database; a host-side migration desyncs it and crash-loops the api trio. To **verify** a migration, use a throwaway container:
  ```bash
  docker run -d --name lqai-throwaway-pg \
    -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=lqai_test \
    -p 55432:5432 pgvector/pgvector:pg16
  # then run pytest with DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:55432/lqai_test
  # (conftest auto-migrates to head). Remove the container when done.
  docker rm -f lqai-throwaway-pg
  ```
  To **apply** a migration to the dev stack, rebuild the workers (next bullet) — don't reach for host alembic.
- **When a migration lands, rebuild `api` + `arq-worker` + `ingest-worker` together.** Stale sibling containers crash-loop with "Can't locate revision identified by …" after a daemon bounce — they're all built from the api image and pin the revision.
- **NEVER `docker compose down -v`.** It wipes volumes — including acceptance/review data that's expensive to recreate. Rebuild a single service (`docker compose build web && docker compose up -d web`), don't nuke volumes.
- **The `web` container serves a pre-built static bundle (no HMR).** Source can be many commits ahead of what the browser shows. If a UI change "isn't appearing," rebuild `web` before debugging the code — or, better, don't iterate against the container at all: see [web/docs/frontend-dev.md](../../web/docs/frontend-dev.md) for running `web/` natively with Vite HMR against the dockerized backend.
- **Run BOTH `ruff format` and `ruff check`** locally — CI runs them as separate gates. `ruff check` passing doesn't mean `ruff format` will.

---

## 4. The gates (what "done" means)

Before claiming a change is complete, run and read the output of:

```bash
# From the repository root after `make install`
make lint          # Python ruff/mypy + Web npm run check:lq-ai
make format-check  # Python ruff format --check
make test          # Python local-loop suites + Web Vitest

# Run Web gates independently when iterating on web/
make web-check
make web-test
```

Run API tests that need Postgres against the throwaway pgvector database from
§3; do not claim integration coverage from a run without it.

Current PR CI runs three jobs: **API** (`uv lock --check`, `ruff check api
scripts`, `ruff format --check api scripts`, `mypy app`, and `pytest -n auto -q`
with pgvector Postgres — each xdist worker gets its own session-scoped disposable
database via the conftest fixture, so workers are fully isolated),
**Gateway** (`uv lock --check`, ruff check/format, `mypy app`, and `pytest -q`),
and **Web** (`npm run check:lq-ai` and `npm run test:frontend -- --run`). The
path-triggered Stack smoke workflow also runs on PRs that change the specified
API/Gateway/Web dependency manifests and locks, Dockerfiles, compose, API
migrations, its script, or its workflow. Current PR CI does not enforce coverage
no-decrease or run browser end-to-end tests. A new endpoint needs unit +
integration + OpenAPI-conformance tests; a bug fix needs a regression test.

### Test-suite collision guards (miss these and the **whole** api suite crashes at collection)

These are non-obvious and have each taken down CI at least once:

- **New fully-implemented route** → add it to `IMPLEMENTED_ROUTES` (`api/tests/test_endpoints.py`) **and** bump the exact path count + `EXPECTED_PATHS` set in `api/tests/test_openapi.py`. The count is pinned; an off-by-one fails collection for the entire suite.
- **New `DELETE` endpoint returning `204`** → use the `response_class=Response` recipe (FastAPI's default `JSONResponse` asserts at import time on 204 and collapses the whole suite). The full recipe is in [CLAUDE.md § Common pitfalls](../../CLAUDE.md#common-pitfalls-catch-at-write-time-not-test-time).
- **`docs/api/backend-openapi.yaml` does not parse with plain `yaml.safe_load`** (pre-existing). `api/tests/test_openapi.py` is the authoritative conformance check — run it; don't trust a hand-eyeball.
- **Decimal cost fields serialize as JSON strings** — schemas type them as `string`, not `number`.

---

## 5. Commit & PR mechanics

- **DCO sign-off on every commit:** `git commit -s`. Imperative mood ("Add X", not "Added X"). Reference issues in the body (`Closes #123`, `Refs DE-103`).
- **Stage files explicitly** — never `git add -A`. Inspect `git status` and add
  only the paths intended for the contribution.
- **External contributors:** push the contribution branch only to your own fork,
  open a PR against `LegalQuants/lq-ai`, and respond to CI and maintainer review.
  Do not push maintainer remotes or merge the PR yourself.
- **Maintainers only:** after merging, an authorized maintainer may synchronize
  upstream and configured mirror remotes and apply the project's branch-retention
  policy. These are not contributor steps.

---

## 6. Merge gating (who merges what)

External contributors never auto- or self-merge. CI green is necessary but not
sufficient: a maintainer reviews and merges the PR. External/community PRs also
receive adversarial vetting per
[docs/security/external-contribution-vetting.md](../security/external-contribution-vetting.md).

Changes to `gateway/**`, authentication, authorization, audit, or cryptography
require the applicable security review under
[.github/CODEOWNERS](../../.github/CODEOWNERS) before a maintainer merges them.

When in doubt, treat it as the stricter row and ask.

---

## 7. Picking up a roadmap item, end to end

A worked shape for taking an item from [ROADMAP.md](../ROADMAP.md) / a [mini-PRD](mini-prds/) to a merged PR:

1. **Confirm it's still open and still shaped as described** — read HONEST-STATE and the relevant code; roadmap text can lag reality. If it's already partly built, scope to the gap.
2. **Read the anchors** — PRD section, OpenAPI sketch, DB schema, neighbouring code.
3. **Surface any fork** (§2 step 2) before building.
4. **Branch** off `main` (`feat/...` or `fix/...`).
5. **Build in reviewed increments** (§2 step 3).
6. **Gates** (§4), including the collision guards and a throwaway-DB migration check if you added one.
7. **Docs are part of the change** — update the PRD section, OpenAPI yaml, and DB schema doc that your change touches, in the same PR. Reconcile the narrative docs (README, HONEST-STATE, the feature guide) if behavior changed. File new deferrals as **DE-XXX in PRD §9** rather than expanding scope.
8. **Ship** (§5–§6): push only to your own fork, open the PR, and respond to CI and review; a maintainer merges it.

### Special case: skills with legal substance

Skills that contain legal work product (playbook positions, drafting guidance) go through a claim → draft → **attorney attestation** → review → merge path ([skills/CONTRIBUTING.md](../../skills/CONTRIBUTING.md)). **Agents do not attest** — the human contributor is the attesting party, and the maintainer team does **not** review legal substance (the in-house attorney is the validator). Synthetic test fixtures are functional QA the maintainer team *does* own.

---

## 8. When to stop and ask (non-negotiable)

Stop and put the decision to the human when:

- The task surfaces an **architectural choice** that wasn't anticipated. (Don't decide unilaterally and continue.)
- A decision isn't anchored in any decision-routing doc.
- You'd be **expanding scope** to fold in a good idea (file it DE-XXX instead).
- You'd be **adding a dependency** (it's part of the SBOM / supply-chain surface — needs justification).
- A change touches the **gateway or an authz path** and you're unsure of the security implication.

The friction is the point. An undocumented decision compounds across every task that follows it.

---

*Next stop: [CLAUDE.md](../../CLAUDE.md). Keep it open while you work.*
