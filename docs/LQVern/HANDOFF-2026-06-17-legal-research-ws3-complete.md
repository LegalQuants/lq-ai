# Handoff — 2026-06-17 · Legal-research WS3 (CourtListener) SHIPPED · follow-on = MCP + chat-loop + transparency

**Repo:** `~/Code/lq-ai` (canonical; NEVER `~/Desktop`; the Bash cwd resets between calls — prefix every command `cd ~/Code/lq-ai &&`).
**main HEAD = `dac1f3f`** (origin == tucuxi — both remotes kept byte-identical on `main`). **Migration head 0049.** `EXPECTED_PATHS` = **123** (`api/tests/test_openapi.py`).

> **STATUS: WS3 (CourtListener case-law research) is COMPLETE and merged.** The remaining workstreams (MCP, governed chat tool-loop, transparency UI) are a **follow-on project** (maintainer's call). Next session starts at **PR4 (MCP client)**.

---

## What this milestone is

Bring **case-law research (CourtListener)** + an **MCP client** to LQ.AI with MikeOSS capability parity, but re-seated on LQ.AI's boundaries (gateway-as-sole-egress, closed bounded tool intents, operator-controlled credentials) rather than MikeOSS's backend-direct style. Spec: [`docs/proposals/legal-research-and-mcp.md`](../proposals/legal-research-and-mcp.md). Architecture pinned in two ADRs:
- **[ADR 0014](../adr/0014-gateway-egress-boundary-for-tool-providers.md)** — gateway egress boundary for tool/data-source providers (one audited boundary; `tool_egress_log`; SSRF primitive; egress-tier refusal; outbound-anonymization default; inbound public text `skip_anonymization`).
- **[ADR 0015](../adr/0015-governed-tool-calling-model.md)** — governed tool-calling model (operator allowlist; per-call tier/audit/cost/confirmation; new `retrieve_caselaw`/`call_mcp_tool` ToolIntents under R5→R6→R4; destructive tools never auto-granted to the autonomous layer in v1).

6-PR sequence; **WS3 = PRs 1–3b** (the CourtListener slice) is done.

---

## What shipped this session (all merged to `main`)

| PR | Branch | What | Gate |
|---|---|---|---|
| **#158** | feat/legal-research-mcp-plan | WS1 gateway tool-provider egress boundary + ADRs 0014/0015 + decomposed mini-PRD. `tool_providers` config, `ToolProviderAdapter` base, SSRF `validate_egress_target`, per-provider rate limiter, egress-tier refusal, gateway-written `tool_egress_log` (raw SQL, mirrors `inference_routing_log`), `Router.route_tool_call`, `echo` proof-provider. | gateway/** (Kevin merged) |
| **#159** | feat/courtlistener-tool-provider | WS3a `courtlistener` tool-provider: `verify_citations`/`search_case_law`/`get_cases`, `Authorization: Token`, respx tests + a **passing live `-m provider` test** (Brown v. Board). Added `ToolProviderInvalidRequestError`. | gateway/** (Kevin merged) |
| **#160** | feat/research-subsystem | WS3 transport: gateway `POST /v1/tools/{provider}/{tool}` exposing `route_tool_call`; key-gated like admin; `GatewayError`-enveloped errors. | gateway/** (Kevin merged) |
| **#161** | feat/research-api | WS3b api research subsystem: `GatewayClient.call_tool`; 5 distinct REST endpoints `/api/v1/research/{verify-citations,search,clusters/{id},opinions/{id},find-in-case}`; read-through opinion caching (plaintext→object storage, metadata→DB migration 0049); stdlib `html.parser` HTML→text (no new dep); `find_in_case`/`read_case` on fetched opinions (404 otherwise). | api-only (self-merged after CI green) |

**End-to-end capability now live:** an authed user can POST a citation → gateway brokers a CourtListener lookup → audited in `tool_egress_log`; fetch a cluster → opinions cached (object storage + DB); read an opinion / keyword-search within it. The backend never calls CourtListener directly — every call traverses the gateway boundary (ADR 0014).

---

## ⚠️ Hard-won facts (don't relearn these)

1. **Tests run via the host venv, NOT docker compose.** The compose `api`/`gateway` services **bake** code into the image (no source bind-mount), so `docker compose run pytest` tests stale code. Use: `cd gateway && .venv/bin/pytest tests/X.py`; `cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/X.py`. The Makefile (`make api-test`/`gateway-test`/`api-lint`) is canonical. The docker stack is the *running app* — leave it alone (never `docker compose down -v`).
2. **api tests need a Postgres.** The conftest does NOT spin one up — it needs `DATABASE_URL` and creates isolated `lq_ai_test_*` DBs on it. Use a **throwaway pgvector on :15433** (isolated from the dev stack on :15432): `docker run -d --name lq-test-pg -p 15433:5432 -e POSTGRES_USER=lq_ai -e POSTGRES_PASSWORD=test -e POSTGRES_DB=lq_ai pgvector/pgvector:pg16`. (`lq-test-pg` may still be running.)
3. **CI gate that bites: `ruff format --check api scripts`.** Run BOTH `ruff format` AND `ruff check` (PR1's only CI failure was a missed `ruff format`). Gateway is mypy `--strict`; api standard.
4. **CourtListener token** is in gitignored `.env` as `COURTLISTENER_API_TOKEN` (auth header `Authorization: Token <v>`). Live test: `cd gateway && COURTLISTENER_API_TOKEN=$(grep '^COURTLISTENER_API_TOKEN=' ../.env|cut -d= -f2) .venv/bin/pytest -m provider tests/test_courtlistener_live.py`.
5. **Collision guards** (crash the whole api suite at collection): a new route → add to `IMPLEMENTED_ROUTES` (`api/tests/test_endpoints.py`) AND bump the pinned count + path set in `api/tests/test_openapi.py` (now **123**). `backend-openapi.yaml`/`gateway-openapi.yaml` don't plain-`safe_load` — `test_openapi.py` is the authoritative conformance check.
6. **Egress-tier semantic:** `route_tool_call` refuses when `provider.egress_tier > max_allowed_tier`. `tool_egress_log.tier` CHECK is `0..5` (0 = pre-resolution refusal — fixed during PR1 review when unknown-provider refusals wrote tier=0 against a 1..5 CHECK and were silently dropped).
7. **respx, not VCR** for provider HTTP tests (matches the codebase; no new SBOM dep). Gateway upstream-4xx → `invalid_request` (`ToolProviderInvalidRequestError`), aligning Jaime's #155.

---

## The proven loop (used all session — keep using it)

1. **Verify the ask against the code FIRST** (subagents read local code fine; they have **no network** — WebFetch/WebSearch only work from the main loop; CourtListener API facts were fetched main-loop and captured in the PR2 plan).
2. **Surface genuine forks via AskUserQuestion** with a recommendation before building (e.g. the PR2/PR3 caching-location split, the /research API shape).
3. **subagent-driven-development** — fresh implementer per task (sonnet for well-specified TDD), independent verification, final holistic review on the security-critical pieces.
4. **Run gates yourself** (evidence before claims): full suite + ruff format/check + mypy.
5. **Ship**: commit `-s` + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` (Opus 4.8 — honest about the running model; Kevin corrected the old "4.7" note). Stage files **explicitly** (never `git add -A` — untracked `docs/lq-ai-*-corpus.md`/`-playbook.md` stay untracked). Push **both** remotes (origin=LegalQuants, tucuxi=Tucuxi-Inc; identical on `main`). PR → CI → merge per gating → report SHA.

**Merge gating:** `gateway/**` OR authz/auth/audit/crypto OR `.github/workflows/**` → **Kevin reviews + merges** (offer review-vs-self). api-only/docs → **self-merge after CI green**.

---

## Follow-on project (the rest of the milestone)

Plans for these are NOT yet written — plan each against merged `main` (the gateway tool transport contract + `GatewayClient.call_tool` are the integration points).

- **PR4 — MCP client (DE-200).** New `api/app/mcp/` (client, discovery, registry). Transport `streamable_http` only. **Port the production-grade existing stub** `web/backend/open_webui/utils/mcp/client.py` (it's complete: connect/list_tool_specs/call_tool/list_resources/read_resource, async ctx-mgr). Operator `mcp.yaml` (allowlisted servers; loaded like `gateway.yaml`). Each MCP server is a gateway **tool provider** (`type: mcp`) — brokered through the same egress boundary + `POST /v1/tools/...` transport built in WS3. Tool discovery + DB cache, per-tool enable/disable, `read_only`/`destructive`/`requires_confirmation` flags. `none`/`bearer` auth; per-user OAuth only where needed. `/api/v1/admin/mcp`. Retire the `web/` stub. (Gateway adapter side = `gateway/**` security review; `mcp` is already a valid `ToolProviderType` literal.)
- **PR5 — governed chat tool-loop + `ToolIntent` extension (ADR 0015).** The chat send path drives the model over the operator allowlist; per-call tier/audit/cost + confirmation gate for destructive tools; per-turn cluster cache (deferred from PR3b). Add `retrieve_caselaw` + `call_mcp_tool` to `ToolIntent` (`api/app/autonomous/enums.py`) + `PHASE_GRANTS`, enforced by `guarded_tool_call` R5→R6→R4. Destructive tools never auto-granted to the autonomous layer. (Touches autonomous guard → security review.)
- **PR6 / WS5 — transparency surfaces.** External-source citations: the citation engine has **no "source-kind" abstraction** — this is net-new modeling (court/cluster/opinion id/`retrieved_at`) so case-law quotes run the exact/tolerant verification cascade. New `audit_log` actions (`research.search`, `research.read_opinion`, `mcp.tool_call`). The **Learn "how it works" page visualization** for the CourtListener/MCP flow — **use the `playground` skill** to build the self-contained interactive explorer (Kevin specifically wants this). MCP provenance pills + destructive-confirm prompt in `web/`. Skills frontmatter `minimum_inference_tier` is declared but **not parsed in code** — build the parser or ship docs-only.

### Deferred enhancements to file in PRD §9
- **DE (tool-path OpenTelemetry):** the inference path emits OTel (`inference.dispatch` via `app.observability_helpers.get_tracer`), but the **tool/research path has NO OTel spans** — only the durable `tool_egress_log` audit. ADR 0014 D3 / 0015 D5 specify `tool_egress`/`chat.tool_call` domain spans (counts-only, anonymization-safe). Wire them in the follow-on, mirroring `inference.dispatch`, across `gateway/app/api/tools.py` + `route_tool_call` and `api/app/research/`. (Kevin raised this 2026-06-17.)
- Outbound-anonymization transform for tool payloads (ADR 0014 D5 — parsed `anonymize_outbound` flag exists; transform deferred; PR3b writes `anonymization_applied=False` honestly).
- CourtListener bulk-data import (O3); per-turn cluster cache (now PR5); pin the launcher image tag (DE-334, pre-existing); webui.db WAL hardening (DE-335, pre-existing).

---

## Next session
Start at **PR4 (MCP client)**. Read `[[project-legal-research-mcp-milestone]]` + `[[feedback-test-runner-venv-not-docker]]`, then this handoff. Verify the `web/` MCP stub + the gateway tool-provider contract against `main` before planning. Same loop: verify → surface forks → subagent-driven → gates → ship.
