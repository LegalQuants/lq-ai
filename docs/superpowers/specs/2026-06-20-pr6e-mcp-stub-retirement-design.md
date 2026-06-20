# PR6e — Retire the OpenWebUI MCP stub (DE-341) Design Spec

> **Milestone:** Legal research + MCP (WS5 / PR6). **Slice:** 6e — the milestone's final code change (internal cleanup), after 6d shipped the case-law skill. The release gate follows 6e.
> **Date:** 2026-06-20. **Branch (to create):** `feat/pr6e-mcp-stub-retirement` off `main` (`658fdbc`).

## Goal

Retire the legacy OpenWebUI MCP client stub (`web/backend/open_webui/utils/mcp/client.py`) and its two usages, plus the frontend affordance that lets a user add an MCP tool server through the web UI. This removes a non-gateway external-egress path from the web backend — a surface that contradicts ADR 0014 (the Inference Gateway is the sole MCP-protocol egress) — and closes DE-341. LQ.AI's real MCP flow (operator-configured `mcp.yaml`, gateway-brokered, per-user OAuth via PR4c) is untouched.

## Decisions locked in brainstorming (2026-06-20)

1. **Remove, don't migrate, the `POST /configs/tool_servers/verify` MCP path.** The OpenWebUI "add a tool server + test connection" flow is fork-legacy. LQ.AI's connector model is operator-configured `mcp.yaml`, gateway-allowlisted (ADR 0014) — users/admins do not add arbitrary MCP servers through the web UI, and the verify endpoint speaks MCP directly from the web backend (bypassing the gateway). Retire the MCP path + its frontend affordance rather than re-routing it through the gateway.
2. **MCP-specific removal only — leave the OpenAPI tool-server paths intact.** Both the verify endpoint and the `middleware.py` tool loop handle MCP *and* OpenAPI tool servers; only the MCP branches touch the stub. 6e removes the MCP branches and the stub; the non-MCP (OpenAPI) tool-server functionality is out of scope (removing it would be a separate, broader decision).
3. **Inline execution.** 6e is a focused deletion (one file deleted + MCP branches removed from ~2 backend + ~3 frontend files + docs), verified by grep + svelte-check + the api/gateway suites. Smaller than 6c/6d; no subagent fan-out.

## Non-goals (explicit scope guard)

- **No migration of the verify capability to the gateway** (decision 1).
- **No removal of OpenAPI tool-server support** — only MCP branches (decision 2).
- **No change to LQ.AI's real MCP flow:** the `api/app/mcp/**` service, the gateway `gateway/app/providers/tool/mcp.py` adapter, the per-user MCP OAuth (PR4c), `mcp.yaml`, and the chat tool-loop (`api/app/chat/tool_loop.py`) are all untouched. The stub is OpenWebUI-fork code that LQ.AI's gateway path already superseded.
- **No new user-facing narrative** — the stub retirement was never a user-facing promise (the 6d honesty pass already dropped the one "coming next" line that mentioned it).
- **No DB/schema/migration change.** No new API endpoints.

## Liveness map (from exploration, `main`=`658fdbc`)

| Surface | File | Liveness | 6e action |
|---|---|---|---|
| The stub | `web/backend/open_webui/utils/mcp/client.py` (whole file, only file in `utils/mcp/`) | — | Delete file + dir |
| Verify endpoint MCP branch | `web/backend/open_webui/routers/configs.py` (import ~L20; `POST /configs/tool_servers/verify`, MCP branch ~L401-443) | **Live** (admin "test connection" UI) | Remove import + MCP branch |
| Chat tool-loop MCP branch | `web/backend/open_webui/utils/middleware.py` (import ~L117; `mcp_clients` ~L2603; `'server:mcp:'` branch ~L2606-2722) | **Dead in LQ.AI** (chat runs through `api/` + gateway, not `web/backend`) | Remove import + MCP branch |
| Add-tool-server modal MCP option | `web/src/lib/components/AddToolServerModal.svelte` (`type` toggles `openapi`/`mcp` ~L40; `registerOAuthClient(...,'mcp')` ~L95; `type==='mcp'` paths) | **Live** (web UI) | Remove MCP type option + MCP-specific code |
| Admin integrations / chat tool connection | `web/src/lib/components/admin/Settings/Integrations.svelte`, `web/src/lib/components/chat/Settings/Tools/Connection.svelte` | **Live** | Remove MCP-specific labels/branches; keep OpenAPI |

Importer set (full blast radius): exactly the two backend importers above + the stub's self-reference. No tests reference `MCPClient`. No `ENABLE_MCP`/`MCP_*` config flags gate it (MCP is type-driven via `TOOL_SERVER_CONNECTIONS[].type == 'mcp'`).

## Component 1 — backend removal

- **Delete** `web/backend/open_webui/utils/mcp/client.py` and the now-empty `web/backend/open_webui/utils/mcp/` directory.
- **`configs.py`:** remove the `from open_webui.utils.mcp.client import MCPClient` import and the `type == 'mcp'` branch of `verify_tool_servers_config` (the `MCPClient()` → `connect` → `list_tool_specs` → `disconnect` block). Keep the OpenAPI + OAuth-discovery branches. If an MCP-typed request still reaches this endpoint, return a clear error — *"MCP tool servers are configured by the operator via the gateway, not added here."* — rather than a silent no-op or a 500.
- **`middleware.py`:** remove the `MCPClient` import, the `mcp_clients` dict initialization, and the `'server:mcp:'` branch of the tool-resolution loop. Keep the OpenAPI/built-in tool branches. (This path is dead in LQ.AI but lives in the fork; removing it is safe and closes the importer.)
- **Grep gate:** `grep -rn "MCPClient\|utils\.mcp\.client\|mcp_clients" web/backend/` returns nothing.

## Component 2 — frontend MCP affordance removal

- **`AddToolServerModal.svelte`:** remove `'mcp'` from the `type` selector (the option element + the `let type = 'openapi'` comment's MCP mention) and the MCP-specific code paths (the `registerOAuthClient(..., 'mcp')` OAuth-2.1-for-MCP block, any `type === 'mcp'` conditionals). The OpenAPI flow (`type === 'openapi'`) stays fully functional.
- **`Integrations.svelte`** and **`chat/Settings/Tools/Connection.svelte`:** remove MCP-specific labels/branches only; keep the OpenAPI tool-server UI.
- The `verifyToolServerConnection` wrapper in `web/src/lib/apis/configs/index.ts` stays (OpenAPI still uses it). `registerOAuthClient` stays only if still used by a non-MCP path; if its sole use was the MCP block, remove it too — grep to decide.
- **Distinct surface, not touched:** LQ.AI's per-user MCP OAuth (PR4c, gateway-brokered) and the operator `mcp.yaml` model. The OpenWebUI tool-server OAuth being removed is a different system.
- **Gate:** `svelte-check` clean (no errors introduced); the web Vitest suite green; grep `grep -rn "'mcp'\|\"mcp\"\|type === 'mcp'" web/src/lib/components/AddToolServerModal.svelte` shows no remaining MCP affordance.

## Component 3 — docs

- **PRD §9:** mark **DE-341 resolved** (shipped in 6e) — append a "Resolved in PR6e (2026-06-20)" note to the DE-341 entry rather than deleting it (preserve the deferral history).
- **Boundary register / security docs:** if `docs/security/boundary-registers.md` (or equivalent) flags the OpenWebUI MCP stub as a known non-gateway-egress gap, mark it removed/closed. (Verify first — fix only genuine references.)
- **Narrative verify (no change expected):** grep the three narrative surfaces (`governed-tool-flow.html`, `learn/how/+page.svelte`, `README.md`) to confirm none promises the stub retirement as "coming" (the 6d honesty pass already removed it). No edit unless a stale reference surfaces.

## Security / gating

- **Not CODEOWNERS security-gated:** the change is in `web/backend/open_webui/**` + `web/src/**` + docs, not `gateway/**` or `docs/security/**` substantively (a boundary-register status note is informational). → **self-merge after CI green.**
- **Security-positive:** 6e *removes* a path by which the web backend could open a direct MCP connection to an external server (bypassing the gateway's audited egress). Note this framing in the PR body — it strengthens the ADR-0014 posture rather than weakening it. If CI's CODEOWNERS routing unexpectedly flags the change, stop and confirm.

## Dev-environment guardrails (CLAUDE.md)

- `web` serves a pre-built static bundle — rebuild `web` to view the modal change (`docker compose up -d --build web`); never `docker compose down -v`.
- Web CI gate = `svelte-check` + Vitest. The backend (`web/backend/`) is Python (OpenWebUI's FastAPI) — confirm its own lint/test gate if one runs in CI; the LQ.AI `api/` + `gateway/` suites are unaffected but must stay green.
- Run `ruff`/lint as the repo configures for `web/backend/` if applicable; otherwise the web CI job is the gate.

## Build shape

Inline (`executing-plans`): a focused, mostly-deletion change.
1. Backend: delete the stub; remove the MCP branch + import from `configs.py` and `middleware.py`; grep gate.
2. Frontend: remove the MCP affordance from `AddToolServerModal.svelte` (+ Integrations/Connection); svelte-check + Vitest.
3. Docs: mark DE-341 resolved; verify no narrative/boundary-register drift.
4. Verify + ship: full grep gate (no `MCPClient` importers), svelte-check + web Vitest + the api/gateway suites green, rebuild `web` and confirm the OpenAPI add-tool-server flow still works and the MCP option is gone; self-merge after CI.

## Acceptance criteria

1. `web/backend/open_webui/utils/mcp/client.py` (and the `utils/mcp/` dir) is gone; `grep -rn "MCPClient\|utils.mcp.client\|mcp_clients" web/backend/` returns nothing.
2. `verify_tool_servers_config` no longer imports/uses `MCPClient`; an MCP-typed verify request returns a clear "configured via the gateway" error; OpenAPI verify still works.
3. `middleware.py`'s `'server:mcp:'` branch and `mcp_clients` are removed; OpenAPI/built-in tool resolution is unchanged.
4. The web UI no longer offers "MCP" as an add-tool-server type; the OpenAPI flow is intact; `svelte-check` clean + web Vitest green.
5. DE-341 is marked resolved in PRD §9; no boundary-register/narrative doc still describes the stub as a live gap or a coming change.
6. LQ.AI's real MCP path (`api/app/mcp/**`, gateway adapter, PR4c OAuth, `mcp.yaml`, chat tool-loop) is untouched and the api/gateway test suites stay green. Not security-gated → self-merge after CI.
