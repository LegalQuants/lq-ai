# HANDOFF — Runtime tool/authority-provider admin API + "Research sources" card

**Date:** 2026-07-03 · **For:** the next coding session (fresh context) · **Driver so far:** Claude Code
**Branch:** `feat/tool-provider-admin-api` (created off `main @ eb9d9445`; spec committed on it)
**Spec (READ FIRST — it is thorough and current):** `docs/superpowers/specs/2026-07-03-tool-provider-admin-api-design.md`
**Origin:** Donna upstream request `Donna/docs/upstream-requests/lq-ai-runtime-tool-provider-admin-api.md` (also closes a real gap in LQ.AI's OWN web UI).
**⚠️ Security-gated** (gateway config write + secrets + admin authz → CODEOWNERS security review; do NOT self-merge past it).

## Where this stands
- ✅ Brainstormed with Kevin; **two decisions locked:** (1) a **new `/api/v1/admin/tool-providers` route** (NOT a `kind` discriminator on the inference provider-keys endpoint); (2) **build the in-app web "Research sources" card too** (fix our own UI gap, not API-only).
- ✅ Gap **verified against current `main`** (see spec §1/§4).
- ✅ **Spec written + committed** on the branch. It contains the full API contract (§5), the web card (§6), the exact current-state code anchors to read (§4), open-items-resolved-with-recommendation (§7), and testing incl. the collision-guard gotcha (§8).
- ⬜ **NOT YET DONE:** the implementation plan, the build, the PR, and the v0.6.1 release. That's this session's job.

## What to do (resume here)
1. **Read the spec** (`…/2026-07-03-tool-provider-admin-api-design.md`) in full — it is the source of truth.
2. Invoke **`superpowers:writing-plans`** to turn the spec into a task-by-task plan. Suggested task decomposition (each an independently-testable deliverable):
   - **T1 — Gateway config_writer:** `upsert_tool_provider` / `remove_tool_provider` in `gateway/app/config_writer.py`, paralleling `upsert_provider_key` but on the `tool_providers:` block (ADR 0011 encrypt, hot-apply). Gateway owns the per-type defaults (base_url/allowlist) so the api can't inject an arbitrary egress target (SSRF-safe, ADR 0014) — see spec §7. Unit tests.
   - **T2 — Gateway admin HTTP endpoints** for tool-providers (the routes `GatewayClient` will call), returning 400/404/409 per spec §5. Tests.
   - **T3 — `GatewayClient` methods** (`api/app/clients/gateway.py`): `list/set/patch/delete_tool_provider`.
   - **T4 — api admin endpoints** `/api/v1/admin/tool-providers[/{type}]` (thin proxies, `AdminUser`-gated, secrets write-only, audit row on writes) — mirror `set/rotate/revoke_provider_key` in `api/app/api/admin.py`. **DELETE uses the `response_class=Response` 204 recipe** (CLAUDE.md gotcha). Tests (verbs, 400/404/409, non-admin 403, secret-never-returned, hot-apply proof via `research/sources`).
   - **T5 — OpenAPI + collision guards:** 4 new routes → add to `IMPLEMENTED_ROUTES` (`api/tests/test_endpoints.py`) AND bump the path count + `EXPECTED_PATHS` (`api/tests/test_openapi.py`), AND `make openapi` to regenerate `docs/api/backend-openapi.generated.yaml` (DE-373 drift-guard). Do these together or the whole api suite fails at collection.
   - **T6 — web "Research sources" card** (`web/`), mirroring the existing Provider keys card (grep `ProviderKeysCard`) — masked write-only key input, Available/Unavailable badge, enable/disable toggle, hot-applied; svelte-check clean.
3. Build via **`superpowers:subagent-driven-development`** (fresh subagent per task + spec/quality review + final security-aware whole-branch review on the most capable model). Test runner: host venv + throwaway pgvector — `cd api && DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/postgres" .venv/bin/python -m pytest …` (gateway similar; see [[feedback-test-runner-venv-not-docker]]). NOTE: the `lqai-test-pg` container on :55432 may have been stopped — restart it if needed (`docker start lqai-test-pg`).
4. **Security-gated PR** → after merge, mirror `origin`→`tucuxi`, and **reply to Donna's request doc** (`/Users/kevinkeller/Code/Donna/docs/upstream-requests/lq-ai-runtime-tool-provider-admin-api.md`) with the spec §5 contract + the squash SHA (Donna bumps its pin + builds its own "Research sources" card).
5. **Then cut v0.6.1** (Kevin's plan): version bump (`api/app/__init__.py` 0.6.0→0.6.1, `desktop/package.json` 0.6.0→0.6.1) + `make openapi` re-gen + PR/merge → `git tag v0.6.1` (→GHCR) + `git tag desktop-v0.6.1` (→signed .dmg) → Kevin's real-Mac verify. Release ritual: [[project-fiduciary-release-gate]] (v0.6.0 record: `docs/LQVern/HANDOFF-2026-07-03-v0.6.0-release-readiness.md`).

## Session conventions (this project, this workflow)
- Commit `-s` (DCO) + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Push BOTH remotes (`origin` LegalQuants + `tucuxi` Tucuxi-Inc), kept identical on `main`.
- Work through brainstorming→writing-plans→subagent-driven-development→finishing-a-development-branch (the pattern used all session).
- Don't run host `alembic upgrade` on the dev DB; no new migration is expected here (config-file writes, not schema).

## Context / state as of this handoff
Everything before this is SHIPPED: fiduciary-grade milestone → **v0.6.0** (main @ `eb9d9445`; GHCR multi-arch images + real-Mac-verified `.dmg`). DE-365 complete (#260/#262/#269). Auditor role merged (#266). Open DEs from this cycle: **DE-378** (wire MutatingUser for true read-only), **DE-379** (signed attestation export — Donna #2, deferred), **DE-380** (web hardcodes localhost:8000 API base). This tool-provider feature is **Donna request #3** and the immediate next build.
