# Handoff — 2026-06-19 · Legal-research + MCP: WS2 complete, PR5a (WS4 substrate) merged · next = PR5b (chat tool-loop + confirmation gate)

**Repo:** `~/Code/lq-ai` (canonical; NEVER `~/Desktop`; Bash cwd resets — prefix every command `cd ~/Code/lq-ai && …`).
**main HEAD = `36223de`** (origin == tucuxi — both remotes byte-identical on `main`). **Migration head 0053.** **`EXPECTED_PATHS` = 132** (`api/tests/test_openapi.py`).
**`origin/main` is a PROTECTED branch — direct pushes are REJECTED.** Everything (incl. docs) lands via a PR + GitHub merge; then sync tucuxi: `git push tucuxi <origin-main-sha>:main`. NEVER `git push origin main`.
**ruff pinned `==0.15.17`** in both venvs (keep them aligned or `ruff format --check` fails in CI on locally-"clean" code).

> Read these memories FIRST (durable state): `[[project-legal-research-mcp-milestone]]`, `[[project-pr6-transparency-posture-narrative]]`, `[[feedback-test-runner-venv-not-docker]]`, `[[feedback-commit-trailer-model]]`. This file is the session-specific pointer.

---

## What's merged (the whole milestone so far)

| PR | SHA | What | Gate |
|---|---|---|---|
| #158–#163 | … | WS1 gateway tool-egress boundary, WS3 CourtListener provider + api research subsystem, Donna research refinements | mixed |
| #165 PR4a | `5b73e75` | gateway MCP tool-provider adapter (streamable_http, `X-LQ-AI-User-Token`) | gateway/** |
| #166 PR4b | `8142d58` | api MCP registry/cache/admin (`mcp_tools`, `/admin/mcp`) | api-only |
| #170 PR4c | `d4a026e` | per-user MCP OAuth — gateway OAuth passthrough (ADR-0014-pure) + api OAuth flow (PKCE+iss+resource, Fernet at rest, migration 0051) | security |
| #171 | `4c8ea24` | **PR5/WS4 design spec** (the doc PR5b implements) | docs |
| #172 PR4d | `6a6e83e` | OAuth UX surface — `GET /api/v1/mcp/oauth` list, allowlisted `return_url`, `MCPServerView.auth` (migration 0052) | security |
| #181 PR5a | `36223de` | **WS4 substrate** — `tool_call_log` (migration 0053) + `governed_tool_invocation` helper + `retrieve_caselaw`/`call_mcp_tool` intents under R5→R6→R4, D4 destructive/disabled exclusion | security |

**WS2 (MCP) is complete end-to-end** (none/bearer/oauth + per-user OAuth UX + connect-on-demand contract). **WS4 is half-built: PR5a (the governance substrate) merged; PR5b (the chat tool-loop) is next.**

---

## NEXT SESSION STARTS HERE — PR5b (chat tool-loop + confirmation gate)

**The design is approved + merged.** Spec: `docs/superpowers/specs/2026-06-18-pr5-governed-chat-tool-loop-design.md` (read §PR5b in full). PR5a's plan (`docs/superpowers/plans/2026-06-19-pr5a-tool-governance-substrate.md`) shows the substrate PR5b reuses. **Write a PR5b implementation plan first** (`superpowers:writing-plans`) against the spec + current `main`, then build with `superpowers:subagent-driven-development` (the loop used all milestone: implement → spec review → quality review → fix → opus whole-branch review → ship).

**Backend-only** (UI = case-law panel, provenance pills, confirm-prompt rendering = PR6/WS5). **Security-gated** (touches the chat send path + a gateway capability) → Kevin reviews/merges.

### What PR5b builds (from the spec §PR5b)
1. **Gateway `tools`/`tool_choice` passthrough (the one gateway/** piece — likely build FIRST):** the gateway `ChatCompletionRequest` (`gateway/app/providers/openai_schema.py:144`) has **NO `tools`/`tool_choice` request field** today; the response-side `tool_calls` plumbing **largely exists** (`ChatMessage.tool_calls`, `FinishReason` includes `tool_calls`, Anthropic/OpenAI/Ollama adapters map tool calls). Add `tools`/`tool_choice` to the request schema + the api `ChatCompletionRequest`, and forward them per-adapter (verify Anthropic vs OpenAI vs Ollama forwarding during planning).
2. **Allowlist assembly (backend-assembled, gateway-enforced):** per turn, build the model-visible tool set — research tools when CourtListener is enabled (fixed schemas for `verify_citations`/`search_case_law`/`get_cluster`/`read_opinion`/`find_in_case`) + MCP tools where `mcp_tools.enabled = true`. Empty set ⇒ single-shot completion as today (no behavior change).
3. **The loop** (`api/app/chat/tool_loop.py`, integrated into `send_message` at `api/app/api/chats.py:1118`): call gateway with tool schemas → model returns final answer OR tool-call(s) → each call goes through **`governed_tool_invocation`** (PR5a's shared helper — reuse unmodified: pass `origin="chat"`, chat/message ids, a `chat.tool_call` span, `denied_on`, `confirmation_state`) → `read_only` tools execute inline (research via `app/research/service.*`; MCP via `GatewayClient.call_tool` with the per-user OAuth token from `app/mcp/oauth.get_valid_token` for oauth servers) → feed result back → repeat until final answer or the **per-turn cap = 8** (operator-overridable). A **per-turn cluster cache** (request-scoped dict) memoizes CourtListener fetches within one turn.
4. **Confirmation gate — persist-and-resume (LOCKED):** on a `destructive`/`requires_confirmation` tool, persist a `tool_call_log` row in `confirmation_state="pending_confirmation"` + the assistant-turn resume state, emit a terminal SSE event **`tool_confirmation_required` {pending_call_id, provider, tool, args_summary, tier, destructive}**, and **end the turn** (no held connection — multi-worker-safe). New route **`POST /api/v1/chats/{chat_id}/tool-calls/{pending_call_id}` {decision: approve|deny}** (ActiveUser, owner-checked) resumes the loop (a fresh streaming response). Pending row single-use + TTL (PR4c `mcp_oauth_state` discipline). EXPECTED_PATHS 132→133.
5. **Connect-on-demand:** when a chat tool-call hits an `auth: oauth` MCP server with no valid token (`get_valid_token`→None → `MCPAuthorizationRequired`), emit a terminal SSE **`mcp_authorization_required` {server, authorize_url}** so the UI prompts inline connect. `authorize_url` = `/api/v1/mcp/oauth/{server}/authorize`; PR4d's `return_url` lands the browser back.

### Locked decisions (do NOT re-litigate)
- 2-PR split (PR5a done, PR5b now); **backend-only**, UI → PR6.
- **Persist-and-resume** confirmation gate (turn ends at the gate; POST resumes). Multi-worker-safe.
- Per-turn cap **8**, operator-overridable.
- Allowlist **backend-assembled, gateway-enforced**.
- Reuse PR5a's `governed_tool_invocation` **unmodified** — its interface (`origin`, chat ids, `confirmation_state`, `denied_on`, optional span) was deliberately built general; the whole-branch review confirmed PR5b can reuse it without touching the helper.

### Open items to pin during PR5b planning
- Per-adapter `tools`/`tool_choice` forwarding details + the response `tool_calls` contract the loop consumes.
- The exact assistant-turn resume-state persistence shape (what slice of conversation-so-far is stored on the partial assistant message vs reconstructed).
- The chat-side tier ceiling source for `max_allowed_tier` (the spec says "the chat/skill tier ceiling the inference path already uses" — ground it in the actual inference-path tier logic during planning).
- SSE event wire shapes (`tool_confirmation_required`, `mcp_authorization_required`) vs the existing chat-stream contract.
- The migration (if any) for persisted pending/confirmation state vs reusing `tool_call_log`'s `confirmation_state`.

---

## Hard-won facts (don't relearn)
1. **Tests via host venv, NOT docker** (`[[feedback-test-runner-venv-not-docker]]`): gateway `cd gateway && .venv/bin/pytest …`; api `cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest …` (throwaway pgvector on :15433, conftest auto-migrates). NEVER host `alembic upgrade` against the dev DB (:15432). The dev compose stack bakes code (no source mount) — it's the running app, not the test harness; never `docker compose down -v`.
2. **`origin/main` is PROTECTED** — PR + merge only; sync tucuxi after. ruff pinned 0.15.17 both venvs.
3. **Collision guards** crash the whole api suite at collection: a new route → `IMPLEMENTED_ROUTES` (`test_endpoints.py`) AND `EXPECTED_PATHS` + the pinned count (`test_openapi.py`, currently **132**); `backend-openapi.yaml` is hand-maintained (DE-337). 204 DELETE needs `response_class=Response` + explicit `return Response(...)`. Decimal cost fields serialize as JSON **strings**.
4. **Subagents have no network** — `pip install` + WebFetch/WebSearch are main-loop only; do dep installs in the controller before dispatching.
5. **PR5a substrate to reuse:** `app/tools/governance.py` — `governed_tool_invocation(db, *, origin, provider, tool, intent, provider_tier, max_allowed_tier, estimated_cost, dispatch, span=None, confirmation_state="not_required", denied_on=(), user_id/chat_id/message_id/session_id, args_digest, ...)`, `resolve_provider_tier(provider)` (fail-safe), `ToolTierRefused`. `tool_call_log` outcomes: `pending|executed|refused_tier|error|denied`; `confirmation_state`: `not_required|pending_confirmation|approved|denied`. Flush-not-commit (caller commits). Single-estimate (caller passes `estimated_cost`; never re-estimate in the helper).

## The loop (used all milestone — keep it)
verify ask vs code → surface forks via AskUserQuestion w/ recommendation → subagent-driven (fresh implementer per task; spec review then quality review; opus for the helper/guard/whole-branch on security-critical) → run gates yourself (full api suite via :15433; ruff format --check + check; mypy; evidence before claims) → ship (`git commit -s` + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`; stage explicitly, never `git add -A`; push origin + tucuxi; PR vs main; watch CI; **Kevin merges security-gated**, then sync tucuxi main). Track tasks in the `.git/sdd/progress.md` ledger.

## DEs filed across the milestone (PRD §9)
DE-336 (research OpenAPI 503s), DE-337 (generate backend-openapi.yaml), DE-338 (MCP session teardown), DE-340 (confidential OAuth clients), DE-341 (retire web `utils/mcp/client.py` stub in PR5/chat-path migration — STILL OPEN; the OpenWebUI chat path still imports `MCPClient` at `web/backend/open_webui/routers/configs.py:403` + `utils/middleware.py:2671`; PR5b/PR6 should migrate those to the gateway path then delete the stub), DE-342 (egress_refused → clearer error), DE-343 (resource on OAuth refresh), DE-344 (per-provider external-tool cost model so R4 throttles `retrieve_caselaw`/`call_mcp_tool`).

## After PR5b
**PR6 / WS5 — transparency surfaces:** external-source citations (net-new "source-kind" citation modeling, proposal C4), new `audit_log` actions, the **`playground`-skill "how it works" visualization + Learn + README that NARRATE the security posture** (Kevin's explicit ask — `[[project-pr6-transparency-posture-narrative]]`), MCP provenance pills, the case-law panel, the destructive-confirm prompt UI, the skill-frontmatter tool-usage parser (proposal C5). Also: retire the web MCP stub (DE-341), tool-path OpenTelemetry DE.
