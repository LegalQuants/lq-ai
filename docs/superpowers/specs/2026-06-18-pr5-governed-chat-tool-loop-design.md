# PR5 / WS4 — Governed chat tool-loop — Design spec

**Date:** 2026-06-18 · **Milestone:** legal-research + MCP (WS4) · **Discharges:** [ADR 0015](../../adr/0015-governed-tool-calling-model.md), proposal [WS4](../../proposals/legal-research-and-mcp.md) · **Gate:** security review (touches the autonomous guard + a gateway capability).

> Built on merged PR1–PR4c: the gateway egress boundary (ADR 0014), CourtListener research tools (WS3), the MCP subsystem + per-user OAuth (WS2). This design adds the **governed tool-calling loop** that lets the chat model — and the autonomous layer — *call* those tools under the existing closed-set governance, without opening a general function-calling surface.

## Goal

Give interactive chat a real, multi-step tool-calling loop over an **operator-enabled allowlist** of research + MCP tools, governed per-call (tier → cost → audit), with a **human confirmation gate** for destructive tools — and expose the same tools to the autonomous layer as two new bounded `ToolIntent`s under the existing R5→R6→R4 brakes. The closed-set posture is preserved: the allowlist *is* the closed set, operator-configured rather than hard-coded; the model picks *among* allowed tools and cannot reach beyond them (ADR 0015, alternative A).

## Locked decisions (brainstormed with the maintainer 2026-06-18)

- **L1 — Decomposition:** ship WS4 as **two security-gated PRs**: **PR5a** (governance substrate + autonomous intents) then **PR5b** (chat loop + confirmation gate, built on 5a). Mirrors the PR4 split.
- **L2 — Scope:** **backend-only.** All UI — case-law panel, MCP provenance pills, the destructive-confirm prompt rendering — is **PR6/WS5**. No `web/` changes in PR5. PR5b delivers the backend confirmation-gate *protocol* (SSE event + approve/deny endpoint) with full backend tests; PR6 renders it.
- **L3 — Confirmation gate = persist-and-resume.** The SSE turn **ends** at the gate (no held connection); state lives in the DB; a separate POST resumes. Multi-worker-safe; survives disconnects. (Detailed in §PR5b.)
- **L4 — Per-turn tool-call cap = 8**, operator-overridable via a settings field. At the cap the loop emits a terminal "tool-call cap reached" signal and lets the model finalize with what it has.
- **L5 — Allowlist source of truth = backend-assembled, gateway-enforced** (ADR 0015 OQ3). The backend assembles the per-turn tool set; the gateway still tier-checks and SSRF/allowlist-guards every call.
- **L6 — Shared governance helper.** Chat and the autonomous layer share ONE substrate: a `governed_tool_invocation` helper (tier → cost → audit → OTel span, flush-not-commit). `guarded_tool_call` is **refactored to delegate** its tier/cost/audit primitives to this helper rather than duplicating them.

## Brake order

The autonomous brakes execute **R5 (temporal/halt) → R6 (contextual/phase-grant) → R4 (economic/cost)** — the real execution order in `guarded_tool_call` (ADR 0015 / proposal C2). All new work follows this order.

---

## PR5a — governance substrate + autonomous intents (api-only)

### `tool_call_log` table (new migration)
One row per proposed/executed tool call, **counts/types only, never raw payloads** (mirrors `tool_egress_log`):

| column | type | notes |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | uuid FK users.id ON DELETE CASCADE, nullable | null for autonomous-session-only calls if no user |
| `chat_id` / `message_id` | uuid, nullable | set for chat calls |
| `session_id` | uuid, nullable | set for autonomous calls |
| `intent` | text | `retrieve_caselaw` / `call_mcp_tool` / a chat-origin marker |
| `provider` | text | tool provider name |
| `tool` | text | tool name |
| `tier` | int | provider egress tier |
| `confirmation_state` | text | `not_required` / `pending_confirmation` / `approved` / `denied` |
| `outcome` | text | `executed` / `refused_tier` / `refused_cap` / `error` / `pending` / `denied` |
| `cost_usd` | numeric (string-serialized) | estimated/charged cost |
| `request_id` | text, nullable | correlation |
| `args_digest` | text, nullable | a hash/summary, NOT the raw args (no payloads) |
| `created_at` / `updated_at` | timestamptz | app-bumped |

### `governed_tool_invocation` helper (the shared substrate — L6)
A single api-side helper both the chat loop and the autonomous dispatch call:
1. **Tier check** — the provider's `egress_tier` vs. the caller's `max_allowed_tier` ceiling; refuse + audit row (`outcome=refused_tier`) if exceeded.
2. **Cost accounting** — `estimate_tool_cost` (extended); record on the row.
3. **Audit** — write the `tool_call_log` row (flush, **not** commit — caller owns the commit, matching `guarded_tool_call`).
4. **OTel span** — `chat.tool_call` / `autonomous.tool_call` (attributes = tool/provider/tier/outcome/cost, counts/types only), mirroring `inference.dispatch` via `app.observability_helpers.get_tracer` (ADR 0015 D5). Discharges the governed-path portion of the standing tool-path-OTel DE.

`guarded_tool_call` (`api/app/autonomous/guard.py`) is refactored so its R-brakes wrap a call to this helper for the tier/cost/audit primitives — one governance path, not two.

### Two new bounded `ToolIntent`s (ADR 0015 D3 / D4)
- Add `retrieve_caselaw` and `call_mcp_tool` to `ToolIntent` (`enums.py`) and `PHASE_GRANTS`:
  - `retrieve_caselaw` → granted in the `analysis` phase (alongside `retrieve_chunks`); conservative elsewhere.
  - `call_mcp_tool` → conservative default (most phases **not** granted), and only for operator-enabled tools.
- `cost.py`: cost estimators for both intents.
- `guard.py` `_dispatch`: handlers that route `retrieve_caselaw` → the research service and `call_mcp_tool` → `GatewayClient.call_tool`, through `governed_tool_invocation`.
- **D4:** a tool whose cached metadata is `destructive` or `requires_confirmation` is **excluded from `PHASE_GRANTS` in all phases** — the autonomous layer cannot fire a human-gated tool without a human, and v1 builds no async-approval channel for autonomous sessions (deferred DE). **Tested** explicitly.

### PR5a tests
Migration/model + cascade; the shared helper (tier-refuse, cost recorded, audit row shape, OTel span emitted, flush-not-commit); the two intents granted in the right phases and refused elsewhere (R6); destructive-exclusion (a `destructive` MCP tool is never in any phase grant); `guarded_tool_call` still passes after the refactor.

---

## PR5b — chat tool-loop + confirmation gate (api + a gateway capability)

### Gateway capability dependency (verify + likely build)
A real function-calling loop needs the gateway's `chat_completion` to accept **`tools`/`tool_choice`** and forward them to the provider, and to surface the provider's **`tool_calls`** in the response. Verified 2026-06-18 against `main`: the **response/message side largely exists** (`ChatMessage.tool_calls`, `FinishReason` includes `tool_calls`, Anthropic/OpenAI/Ollama adapters map tool calls), but the gateway **`ChatCompletionRequest` (`gateway/app/providers/openai_schema.py:144`) has NO `tools`/`tool_choice` request field.** PR5b therefore adds `tools`/`tool_choice` to the gateway request schema + the api `ChatCompletionRequest`, and forwards them in each provider adapter (per-adapter forwarding verified during planning). This is `gateway/**` — part of the security-gated surface.

### Allowlist assembly (L5)
Per turn the backend assembles the model-visible tool set:
- **Research tools** when CourtListener is enabled (via the existing `/research/capabilities` signal): fixed function schemas for `verify_citations`, `search_case_law`, `get_cluster`, `read_opinion`, `find_in_case`.
- **MCP tools** where `mcp_tools.enabled = true` across configured providers: function schema from each cached `parameters` JSON; the cached `read_only`/`destructive`/`requires_confirmation` flags drive the gate.
If the assembled set is empty, the loop is **not** engaged — single-shot completion as today (no behavior change for deployments without research/MCP).

### The loop (`api/app/chat/tool_loop.py`, integrated into `chats.py send_message`)
1. Call the gateway with the function schemas. The model returns a final answer **or** tool-call(s).
2. For each proposed call → `governed_tool_invocation` (tier → cost → audit). Then:
   - `read_only` → **execute inline** (research reads via `app/research/service.*`; MCP read-only via `GatewayClient.call_tool(provider, tool, args, max_allowed_tier=…)`, with the per-user OAuth token from `app/mcp/oauth.get_valid_token` for `oauth` servers). Feed the result back into the conversation.
   - `destructive`/`requires_confirmation` → the **confirmation gate** (below).
3. Repeat until the model emits a final answer or the **per-turn cap (8, L4)** is hit (terminal "cap reached" signal → model finalizes).
4. **Per-turn cluster cache** — a request-scoped dict, discarded at turn end, memoizes CourtListener cluster/opinion fetches so multi-hop within one turn ("read that cluster, now search it for X, now Y") doesn't re-fetch.

### Connect-on-demand (MCP OAuth, added 2026-06-18)
When a proposed call targets an `auth: oauth` MCP server and the calling user has no valid token, `get_valid_token` returns None → the existing PR4c `MCPAuthorizationRequired` (409) contract. In the loop this surfaces as a terminal SSE event **`mcp_authorization_required`** `{server, authorize_url}` (a sibling of `tool_confirmation_required`): the turn ends cleanly and the UI prompts the user to connect that server inline, then the user re-asks (or the loop resumes after connect). `authorize_url` is `/api/v1/mcp/oauth/{server}/authorize` (the PR4d `return_url` carries the browser back to the frontend after the round-trip). This makes the per-user OAuth connect reachable from a chat tool-call without a separate "manage connections" detour. (Depends on PR4d's `return_url`; PR4d ships first.)

### Confirmation gate — persist-and-resume (L3)
1. Persist a `tool_call_log` row in `confirmation_state = pending_confirmation` carrying `{provider, tool, args}`, plus the **assistant-turn resume state** (conversation-so-far incl. inline tool results already gathered, on the partial assistant message).
2. Emit a terminal SSE event **`tool_confirmation_required`** `{pending_call_id, provider, tool, args_summary, tier, destructive}` and **end the turn** (stream closes cleanly).
3. **`POST /api/v1/chats/{chat_id}/tool-calls/{pending_call_id}`** `{decision: "approve"|"deny"}` (ActiveUser-gated, chat-owner-checked):
   - **approve** → `confirmation_state=approved`; execute via `governed_tool_invocation`; feed result back; **resume the loop** (a fresh streaming response continues the assistant turn from persisted state).
   - **deny** → `confirmation_state=denied`; feed "user denied this tool" to the model; resume so it finalizes without the tool.
4. The pending row is **single-use + TTL-bounded** (PR4c `mcp_oauth_state` discipline): an already-resolved or expired `pending_call_id` is rejected (409/410).

### Surface / collision guards
New route `POST /api/v1/chats/{chat_id}/tool-calls/{pending_call_id}` → `EXPECTED_PATHS` +1, `IMPLEMENTED_ROUTES` +1, `backend-openapi.yaml`. (The chat send path is an existing route; its behavior extends.)

### PR5b tests
Loop happy path (model proposes a read_only research call → executes inline → final answer); MCP read-only call with the per-user token threaded; allowlist assembly (research-only, MCP-only, mixed, empty→single-shot); per-turn cap reached; per-turn cluster cache hit; the gateway tools-passthrough round-trip; the confirmation gate full cycle (propose → `tool_confirmation_required` event + turn ends → approve resumes + executes → final; deny resumes + finalizes; expired/replayed pending_call_id rejected; non-owner 403); tier-refusal path; no token/payload in any `tool_call_log` row or log line.

---

## Cross-cutting

- **Tier ceiling source:** the per-call `max_allowed_tier` derives from the chat/skill tier ceiling the inference path already uses; the helper computes it once and threads it to the gateway, which refuses + audits if the provider's `egress_tier` exceeds it.
- **Audit layering:** `tool_call_log` (new, api governance audit) sits alongside the gateway's `tool_egress_log` (egress-boundary audit) — the same two-layer split as `inference_routing_log` (gateway) vs the api audit.
- **No raw payloads** anywhere in `tool_call_log` or logs — args are digested/summarized; tool results are fed into the conversation but never written to the audit row.

## Explicitly deferred (PR6/WS5 or DEs)
- **External-source citation provenance + provenance pills** — net-new citation "source-kind" modeling (proposal C4); PR6/WS5. PR5 feeds raw tool results into the conversation; rich provenance is PR6.
- **All UI** (case-law panel, pills, the confirm-prompt rendering) — PR6/WS5 (L2).
- **Skill-frontmatter tool-usage + `minimum_inference_tier` parser** (proposal C5) — PR6/WS5 (build the parser or scope to docs-only).
- **Per-chat cost cap** — v1 bounds chat by the per-turn cap (8); a cumulative per-chat cost cap is a DE.
- **Autonomous async-approval channel** for destructive tools — ADR 0015 D4 defers; v1 excludes destructive tools from autonomous grants entirely.

## Open items to pin during planning
- Per-adapter `tools`/`tool_choice` forwarding details (Anthropic vs OpenAI vs Ollama) + the gateway response `tool_calls` contract the loop consumes.
- The exact resume-state persistence shape (what slice of conversation-so-far is stored on the partial assistant message vs. reconstructed).
- Migration number (next free after 0051) and `EXPECTED_PATHS` current value at PR5b time.
- Whether the gateway `tools`-passthrough is its own first task of PR5b or folded into PR5a's substrate (recommend: first task of PR5b, since the loop is its only consumer).
