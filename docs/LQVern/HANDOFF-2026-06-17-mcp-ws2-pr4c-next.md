# Handoff — 2026-06-17 (eve) · Legal-research + MCP: WS2 backend mostly shipped · next = PR4c (per-user OAuth)

**Repo:** `~/Code/lq-ai` (canonical; NEVER `~/Desktop`; Bash cwd resets — prefix every command `cd ~/Code/lq-ai && …`).
**main HEAD = `103cfbd`** (origin == tucuxi — both remotes byte-identical on `main`). **Migration head 0050.** **`EXPECTED_PATHS` = 127** (`api/tests/test_openapi.py`).
**ruff is pinned `==0.15.17`** (PR #168) — keep both dev venvs on it: `cd api && .venv/bin/pip install 'ruff==0.15.17'` and same for `gateway/`. (Unpinned `ruff>=0.6` drift cost a CI round-trip on PR4b.)

> Read `[[project-legal-research-mcp-milestone]]`, `[[project-pr6-transparency-posture-narrative]]`, `[[feedback-test-runner-venv-not-docker]]`, `[[feedback-commit-trailer-model]]` first — they carry the durable state. This file is the session-specific pointer.

---

## What shipped this session (all merged to `main`)

| PR | SHA | What | Gate |
|---|---|---|---|
| #163 | `38dbbb0` | Donna research-surface refinements: typed `VerifiedCitation`, `OpinionTextField` Literal, `GET /research/capabilities` + retired hardcoded provider | api-only (self-merged) |
| #164 | `e2cc311` | Carry #163's typed shapes into hand-maintained `backend-openapi.yaml` (it had drifted) | docs (self-merged) |
| #165 | `5b73e75` | **PR4a** — gateway MCP tool-provider adapter: `mcp` SDK (starlette pinned <0.49), `mcp.yaml` schema+loader, `MCPToolProviderAdapter` (streamable_http, annotation→ToolSpec flags, egress-guarded), `build_tool_adapter` mcp branch, per-call `X-LQ-AI-User-Token` header (never logged), `GET /v1/tools/{provider}` discovery | gateway/** (Kevin merged) |
| #166 | `8142d58` | **PR4b** — api MCP registry/cache/admin: `mcp_tools` (migration 0050), `GatewayClient.discover_tools`, `app/mcp/service.py` (list/refresh-reconcile/enable-toggle, provider-scoped), `/api/v1/admin/mcp` (audited) | api-only (self-merged) |
| #167 | `786801a` | Donna cursor ask: `/research/search` accepts `cursor` (CL adapter `?cursor=`) | gateway/** (Kevin merged) |
| #168 | `103cfbd` | Pin `ruff==0.15.17` (api+gateway) — stop CI/local formatter drift | gateway/** (Kevin merged) |

**WS2 (MCP) backend now works end-to-end for `none`/`bearer` servers:** operator declares servers in `mcp.yaml` → gateway discovers/invokes over streamable_http (sole egress, ADR 0014) → api caches tools + per-tool enable/disable via `/admin/mcp`. WS3 (CourtListener) was already done. **Only PR4c (per-user OAuth) remains in WS2**, then PR5 (chat tool-loop) + PR6 (transparency UI).

---

## NEXT SESSION STARTS HERE — PR4c (per-user OAuth for MCP)

**Plan is written + committed:** `docs/superpowers/plans/2026-06-17-pr4c-mcp-per-user-oauth.md` on branch **`feat/mcp-oauth-pr4c`** (pushed to both remotes, HEAD `830a653`). Spec: `docs/superpowers/specs/2026-06-17-mcp-client-ws2-design.md`. Build with `superpowers:subagent-driven-development`, same loop used all session (implement → spec review → quality review → fix → final holistic review → ship).

**Locked decisions (do NOT re-litigate):**
- Out-of-band OAuth 2.1 authz-code **+PKCE** driven by the **api** (the gateway connect is non-interactive, so it just gets the resulting bearer per-call via PR4a's `X-LQ-AI-User-Token`).
- **authlib** (new api dep, `>=1.3,<2`) for the OAuth core + thin hand-written MCP glue (RFC 9728 PRM discovery, RFC 8414 AS discovery, RFC 8707 `resource`, RFC 9207 `iss` validation).
- **Pre-registered PUBLIC clients** (PKCE, no secret) in v1. `oauth_client_id` is a new field on `MCPServerConfig` (gateway); the api reads it from the existing sanitized `GET /admin/v1/config`. Confidential clients (secret) = **DE-340** (deferred — needs a gateway→api secret handoff).
- Tokens **Fernet-encrypted** at rest (migration **0051**, `mcp_oauth_tokens`) under a **dedicated** `LQ_AI_MCP_MASTER_KEY` (mirror `app/security/encryption.py`'s `BridgeTokenEncryptor`).
- **Kevin LOCKED egress decision (b) — ADR-0014-pure:** OAuth **discovery + token-exchange/refresh** go **THROUGH the gateway** via NEW egress-guarded passthrough endpoints (`POST /v1/oauth/{provider}/discover` + `POST /v1/oauth/{provider}/token`); creds pass through but are **never logged / never in `tool_egress_log`**. **Build the gateway passthrough FIRST.** Operator must allowlist the **AS host** in that server's `mcp.yaml` `allowlist.hosts` (the AS host is discovered at runtime and may differ from the MCP server host). The browser authorize **redirect** stays api-driven (user-agent → AS directly; not server egress).

**Still-open FLAGS for whoever builds it** (recommendations in the plan; lower-stakes): state-store (recommend a small `mcp_oauth_state` table, multi-worker safe), callback redirect target (JSON 200 in v1; polished page is PR6), admin-refresh-of-oauth-servers (recommend: admin refresh covers none/bearer; oauth discovery/refresh is user-scoped).

**Gate:** PR4c touches gateway/** (passthrough + `oauth_client_id` field) AND api auth/crypto/token-storage → **security review (Kevin merges).** EXPECTED_PATHS 127→131. Retire `web/backend/open_webui/utils/mcp/client.py` in this PR (its role is fully replaced).

---

## Hard-won facts (don't relearn)
1. **Tests via host venv, NOT docker** ([[feedback-test-runner-venv-not-docker]]): `cd gateway && .venv/bin/pytest …`; `cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest …` (throwaway pgvector on :15433, conftest auto-migrates). NEVER host `alembic upgrade` against the dev DB.
2. **ruff pinned 0.15.17** — keep dev venvs aligned or `ruff format --check` will fail in CI on code that's "clean" locally.
3. **mcp SDK + starlette pin:** gateway has `mcp>=1.28,<2` + `starlette>=0.40,<0.49` (mcp's sse-starlette would otherwise pull starlette 1.x and break fastapi 0.116). Don't "fix" the starlette pin.
4. **Collision guards** crash the whole api suite at collection: a new route → add to `IMPLEMENTED_ROUTES` (`api/tests/test_endpoints.py`) AND `EXPECTED_PATHS` + bump the pinned count (`api/tests/test_openapi.py`). `backend-openapi.yaml` is hand-maintained (DE-337 to fix) and doesn't plain-`safe_load` — `test_openapi.py` is authoritative.
5. **Per-call token is a HEADER** (`X-LQ-AI-User-Token`), never a query param (PR4a fix — query params hit uvicorn access logs). Keep that discipline in PR4c.
6. **Subagents have no network** — `pip install` (mcp, authlib) and WebFetch/WebSearch are main-loop only; do dep installs in the controller before dispatching implementers.

## The loop (used all session — keep it)
verify ask vs code → surface forks via AskUserQuestion w/ recommendation → subagent-driven (fresh implementer per task, sonnet; spec review then quality review; opus for final holistic on security-critical) → run gates yourself (evidence before claims) → ship (`git commit -s` + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`; stage explicitly, never `git add -A` — untracked `docs/lq-ai-*.md` + `docs/proposals/*` stay untracked; push origin + tucuxi). **Merge gating:** gateway/** OR auth/authz/audit/crypto OR `.github/workflows/**` → Kevin reviews+merges; api-only/docs → self-merge after CI green.

## DEs filed this session (PRD §9)
DE-336 (503s on /research OpenAPI), DE-337 (generate backend-openapi.yaml from app.openapi()), DE-338 (bound MCP session teardown), DE-340 (confidential MCP OAuth clients).

## After PR4c
**PR5** — governed chat tool-loop + `retrieve_caselaw`/`call_mcp_tool` ToolIntents (R5→R6→R4), per-turn cluster cache, destructive-confirm gate (touches autonomous guard → security review). **PR6/WS5** — transparency surfaces: external-source citations (net-new source-kind modeling), audit actions, and the **playground "how it works" viz + Learn + README that NARRATE the security posture** ([[project-pr6-transparency-posture-narrative]] — Kevin's explicit ask). **Tool-path OpenTelemetry** is still a deferred DE.
</content>
