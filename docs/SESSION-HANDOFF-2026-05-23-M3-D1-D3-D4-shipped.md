# Session handoff — 2026-05-22 night → 2026-05-23 — M3 Phase D fully shipped (D1 + D3 + D4)

> **Why this file:** This session opened with M3-D1 backend half pending and closed with all of M3 Phase D shipped to main across three PRs (#76, #77, #78). M3-E1 (fresh-install verification) is the next session's natural starting point. This handoff captures what shipped, what surfaced operationally during the session (a 101-file Finder-dup wave + a recurrence of the M3-C2 DELETE-204 bug), and where the next session picks up.

## What's on main

Latest commits, newest first:

* **`54eff60`** — feat(m3-d4): admin intake-bridges shell — list + soft-delete for Slack + Teams (#78)
* **`5b7a7ac`** — feat(m3-d3): teams-bridge service + Microsoft OAuth + backend persistence (#77)
* **`2e14ac2`** — M3-D1 (DRAFT, ~half) — slack-bridge service scaffold + OAuth handlers (#76)
* **`9616d45`** — M3-C4a — Tabular Review XLSX/CSV export (#75)
* **`a29999a`** — M3 Phase F (planning) — OpenTelemetry deepening (#74)

(Note: #76's squash title preserves the "DRAFT, ~half" framing from the original PR title; the commit content includes both the scaffold AND the backend persistence half. Future commits could rename the squash if it bothers a reviewer, but it's accurate to the PR history.)

## Three phases shipped this session

### PR #76 — M3-D1 slack-bridge (backend half)

The slack-bridge service scaffold + OAuth handlers were ALREADY built at session start (6 of ~11 hr complete on the `m3-d1-slack-bridge` branch). This session closed the backend persistence half.

**Three architectural decisions locked at start (handoff recommendations all ratified):**
1. **Encryption key:** separate `LQ_AI_BRIDGE_MASTER_KEY` (NOT shared with gateway). Different threat models — bot impersonation vs inference routing.
2. **Re-install semantics:** upsert on `team_id` (Slack rotates bot tokens on re-install).
3. **Bridge-token storage:** in api's `Settings` only (NOT gateway). Keeps gateway secret surface minimal.

**Shipped:**
* Migration 0037 `slack_workspaces` (uuid PK, team_id unique, team_name, bot_token_encrypted bytea, bot_user_id, installer_slack_user_id, scope, installed_at, deleted_at)
* `api/app/security/encryption.py` — Fernet wrapper (`BridgeTokenEncryptor`) mirroring `gateway/app/secrets.py` ADR-0011 pattern. New env var `LQ_AI_BRIDGE_MASTER_KEY`.
* `SlackWorkspace` ORM + `SlackWorkspaceCreate` / `SlackWorkspaceResponse` Pydantic
* `POST /api/v1/integrations/slack/workspaces` with shared-bearer auth + upsert-on-team_id
* Slack App `manifest.yml` (narrow scopes: commands + chat:write only)
* docker-compose `slack-bridge` service under `profiles: [slack]`
* OAuth callback integration tests (`slack-bridge/tests/test_oauth.py` — 7 cases)
* Backend endpoint tests (`api/tests/test_integrations_slack.py` — 8 cases)
* Encryption unit tests (`api/tests/test_encryption.py` — 8 cases)
* OpenAPI sketch + .env.example updates

### PR #77 — M3-D3 teams-bridge (full)

Microsoft Teams equivalent of M3-D1. Multi-tenant Azure AD app posture.

**Four architectural decisions locked at start (all "Recommended" options taken):**
1. **Encryption key:** reuse `LQ_AI_BRIDGE_MASTER_KEY` (same bridge threat model; in practice nothing per-tenant encrypted in M3-D3).
2. **Bridge bearer:** reuse `LQ_AI_BRIDGE_TOKEN` (one rotation point).
3. **MS Bot Framework auth library:** raw httpx, no `botbuilder-core` SDK (~15 transitive deps saved).
4. **Tenancy:** multi-tenant Azure AD app (one registration serves any tenant).

**Shipped:**
* `require_bridge_auth` lifted from `integrations_slack.py` into `app/api/dependencies.py` so both bridges share the matcher
* Migration 0038 `teams_tenants` (uuid PK, tenant_id unique, tenant_name, installer_oid, installed_at, deleted_at — **no** bot_token_encrypted because Teams uses app-level credentials, not per-tenant tokens)
* `TeamsTenant` ORM + Pydantic schemas
* `POST /api/v1/integrations/teams/tenants` with shared `require_bridge_auth` + upsert-on-tenant_id
* `teams-bridge/` standalone FastAPI service (port 8003): pyproject + Dockerfile + README + app/main + config + observability
* `teams-bridge/app/oauth.py` — Microsoft identity platform `/common/oauth2/v2.0/{authorize,token}` flow (multi-tenant) with `prompt=admin_consent`, scopes `openid profile email offline_access https://graph.microsoft.com/User.Read`, id_token base64 decode for `tid`/`oid`, best-effort Graph `/organization` lookup for tenant displayName (falls back to tid on Graph hiccup), POST tenant record to api with shared bridge bearer
* `teams-bridge/manifest.json` (Teams app manifest v1.16 schema; `${MICROSOFT_APP_ID}` + `${LQ_AI_TEAMS_BRIDGE_PUBLIC_HOST}` placeholders the operator substitutes)
* docker-compose `teams-bridge` service under `profiles: [teams]`
* OAuth integration tests (`teams-bridge/tests/test_oauth.py` — 9 cases including Graph-failure-fallback)
* Backend endpoint tests (`api/tests/test_integrations_teams.py` — 6 cases)
* OpenAPI sketch + .env.example updates

### PR #78 — M3-D4 admin intake-bridges shell

SvelteKit admin UI page + backing admin endpoints.

**Shipped:**
* `app/api/admin_intake_bridges.py` — admin-gated router with `GET /admin/intake-bridges` (section-split: slack_workspaces + teams_tenants, live rows only, sorted by `installed_at DESC`) + `DELETE /admin/intake-bridges/{slack,teams}/{id}` (soft-delete; revivable per M3-D1/M3-D3 upsert)
* `app/schemas/intake_bridges.py` — Pydantic summary shapes (bot tokens / ciphertext deliberately omitted)
* `web/src/lib/lq-ai/api/intakeBridgesApi` client
* `web/src/routes/lq-ai/admin/intake-bridges/+page.svelte` — two-section admin UI with install/disconnect buttons + visible-but-disabled quick-ask-skill picker + empty `/lq` audit-log shell (both DE-288 hooks)
* `web/src/routes/lq-ai/admin/intake-bridges/page-helpers.ts` — pure helpers extracted for vitest
* `web/src/routes/lq-ai/admin/+layout.svelte` — new "Intake bridges" nav link
* Backend integration tests (10) + frontend vitest helpers (20)
* OpenAPI sketch updates (3 new paths + 3 new schemas)

## Operational hiccups worth carrying forward

### 1. Finder duplicate file wave (recurred massively)

The `* [0-9].*` macOS Finder dup pattern hit twice in this session:
- After PR #75 fetch: 11 dups
- After PR #76 merge fetch: **101 dups** spread across api/, slack-bridge/, web/, docs/quickstart/sample-msas/, skills/

All were untracked (`.gitignore` patterns `* [0-9].*` and `* [0-9][0-9].*` already exclude them from commits) but each wave broke alembic locally because two files defined `revision = "0037"`. Cleanup is one-liner:

```bash
find /Users/kevinkeller/Desktop/lq-ai -name "* [0-9].*" -type f \
  -not -path "*/node_modules/*" -not -path "*/.venv/*" -not -path "*/.git/*" -delete
```

**Open question for next session:** the dups regenerate via iCloud sync after every git fetch/pull that touches files. The `.gitignore` keeps them out of commits but the local hassle is real. Options to explore:
- Move the repo OUT of the iCloud-synced Desktop tree (e.g., `~/Code/lq-ai`)
- Add a Finder/iCloud exclusion for the repo path
- A `make clean-dups` target that wraps the find -delete (palliative not curative)

### 2. M3-C2 DELETE-204 import-time bug recurred in M3-D4

When writing `admin_intake_bridges.py`'s DELETE endpoints, I hit the same FastAPI import-time assertion that bit M3-C2:

```
AssertionError: Status code 204 must not have a response body
```

Caused by declaring `status_code=204` without `response_class=Response`. FastAPI's default `JSONResponse` is body-emitting, and its router asserts at import time. This collapses the whole test suite at collection (every test file imports `app.main → app.api → app.api.admin_intake_bridges`).

Fix recipe (now documented in code comments in the new file):

```python
from fastapi import Response, status

@router.delete(
    "/slack/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,                       # critical
)
async def soft_delete_slack_workspace(...) -> Response:
    ...
    return Response(status_code=status.HTTP_204_NO_CONTENT)  # explicit return
```

Worth folding into a project-wide convention doc (perhaps in `docs/test-strategy.md` or `CLAUDE.md`'s "Read before writing" section) so future contributors catch it at write-time instead of test-time.

## Pre-existing OWUI svelte-check noise

`npm run check` reports 9360 errors across 382 files — virtually all are pre-existing in the OpenWebUI fork (`src/routes/s/[id]/+page.svelte`, `src/routes/watch/`, etc.). My new files (`intake-bridges/+page.svelte` + page-helpers + intakeBridges.ts) compile clean. CI doesn't seem to fail on these (PRs land green) but the noise drowns out any new errors.

## Next session pickup

### Sequenced next steps

1. **M3-E1** — Pre-tag fresh-install verification (~8-12 hr). Destroy all volumes + images, fresh clone, `docker compose --profile slack --profile teams up --build`, walk through every M3 surface:
   - Playbook engine (NDA + Easy Playbook against 5 sample NDAs)
   - Word Add-In plumbing (manifest generate + sideload via unsigned-manifest path)
   - Tabular Review (5 NDAs × 4 columns + XLSX export)
   - Slack bridge plumbing (install + OAuth + admin UI surfaces install)
   - Teams bridge plumbing (install + OAuth + admin UI surfaces install)
   - File any blockers as DE-XXX entries before tagging
   - Reviewing-attorney walk-through of Playbook + Tabular surfaces against real contracts

2. **M3-E2** — Documentation finalization (~10-14 hr):
   - New docs: `docs/playbooks.md`, `docs/word-addin.md`, `docs/tabular-review.md`, `docs/intake-bridges.md`
   - 3 Learn-tab playgrounds (Playbook cascade, Tabular interactive grid, Word Add-In install walkthrough)
   - Updated docs: PRD §3.7 / §3.14 / §3.9 / §3.15 statuses; architecture.md Mermaid diagram; quickstart.md
   - Explicit "I just cloned the repo" developer onboarding pass in quickstart

3. **M3-F1/F2/F3** — OpenTelemetry deepening (~36-48 hr). Three PRs per `docs/proposals/opentelemetry-deepening.md`:
   - F1: trace correlation across api ↔ gateway ↔ ingest-worker ↔ arq-worker ↔ slack-bridge ↔ teams-bridge
   - F2: domain spans (NDA-review extraction, Citation Engine cascade, Tabular cell extraction, ingest pipeline, Slack/Teams OAuth handlers, **plus the new `slack_workspaces` + `teams_tenants` upserts**)
   - F3: deployment recipes + OTel-evaluation Learn-tab playground

4. **v0.3.0 tag** — at M3-close.

### Remaining M3 effort

~60-80 hr (E1 + E2 + F1/F2/F3).

### Branch state at session end

* `main` → post-#78 squash (latest)
* `m3-d4-admin-intake-bridges` → preserved on origin per branch-preservation policy (#78 source)
* `m3-d3-teams-bridge` → preserved on origin (#77 source)
* `m3-d1-slack-bridge` → preserved on origin (#76 source)
* `session-handoff-2026-05-22-night` → still preserved as historical record (handoff doc only, never merged)

## Memory updates from this session

* `project_lq_ai_status` — refreshed at session start, will be refreshed again at session end to reflect M3-D1+D3+D4 all shipped.

## Architectural decisions for future sessions (locked this session)

These are not memory entries (which are operational guidance for me); they're architectural facts that bind future work:

* **One shared bridge bearer token:** `LQ_AI_BRIDGE_TOKEN` authenticates every bridge → api persistence POST. New bridges (e.g., future Teams-OBO refresh-token storage, future Discord) should reuse this dep + env var.
* **One shared bridge encryption key:** `LQ_AI_BRIDGE_MASTER_KEY` encrypts at-rest secrets owned by the api side of any bridge (currently only `slack_workspaces.bot_token_encrypted`; teams_tenants has no at-rest secret). New bridges reuse.
* **Bridges are profile-gated:** every new bridge ships under `profiles: [<name>]` so operators who don't use that surface don't pay the SBOM cost.
* **DELETE 204 endpoints need `response_class=Response` + explicit `Response(status_code=204)` return.** Documented now in 3+ places (M3-C2 fix commit `c613c43`, M3-D4 code comments, this handoff).

---

*Generated 2026-05-23 by Claude Code (session b67ff912-24a1-422d-a92b-38f488ab6485 → continuation).*
