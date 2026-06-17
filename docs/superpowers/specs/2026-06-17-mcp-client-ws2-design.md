# Design — MCP Client subsystem (WS2 / PR4), gateway-brokered + governed + per-user OAuth

**Date:** 2026-06-17 · **Milestone:** legal-research + MCP · **Workstream:** WS2 (DE-200, PRD §8.5)
**Spec source:** [`docs/proposals/legal-research-and-mcp.md`](../../proposals/legal-research-and-mcp.md) · **ADRs:** [0014](../../adr/0014-gateway-egress-boundary-for-tool-providers.md) (egress boundary), [0015](../../adr/0015-governed-tool-calling-model.md) (governed tool-calling)

> Brings an **MCP client** to LQ.AI with MikeOSS parity (`streamable_http` only, no stdio), re-seated on LQ.AI's boundaries: the **gateway is the sole egress** and the only MCP-protocol speaker; the **api owns the user**, the discovery cache, per-tool policy, and per-user OAuth. PR4 is WS2; PR5 (the governed chat tool-loop + `ToolIntent`s) and PR6 (transparency UI) consume what this builds.

---

## 1. Decisions (locked 2026-06-17)

| # | Decision | Rationale |
|---|---|---|
| **D1** | **The gateway owns the MCP `streamable_http` client.** New `MCPToolProviderAdapter` in `gateway/`; the `mcp` SDK is a gateway dependency. | MCP `streamable_http` is a *stateful session* (connect → `initialize` → JSON-RPC over SSE). Whoever holds the outbound connection must speak MCP. ADR 0014 makes the gateway the sole egress → the protocol client lives there. This reinterprets the proposal's "port the stub into `api/`" as "port into the gateway adapter." |
| **D2** | **Separate `mcp.yaml`, loaded by the gateway** alongside `gateway.yaml`; each entry is synthesized into a `type: mcp` `ToolProviderConfig` internally. | Keeps the (potentially long) MCP server + tool-policy list out of `gateway.yaml`; matches the proposal/handoff. `ToolProviderType` already includes `mcp`. |
| **D3** | **Ship per-user OAuth** (not a stub): `none` / `bearer` / `oauth` auth modes. | Operator's MCP servers often require user identity. |
| **D4** | **The api drives + stores OAuth; the gateway takes a per-call token.** The api runs the authz-code+PKCE flow, stores per-user tokens Fernet-encrypted in the api DB, refreshes them, and passes the user's access token to the gateway per tool-call. The gateway stays user-unaware. | The gateway has no user DB ("the gateway has no user" — ADR 0007); user secrets live where user data lives (the api). Egress stays in the gateway. Reuses the audited `api/app/security/encryption.py` (Fernet) — **no new crypto**. |
| **D5** | **Backend OAuth in PR4; polished consent UI in PR6.** PR4 ships the api `authorize`/`callback` endpoints (testable headless); the `web/` connect button + provenance pills land in PR6/WS5 where all MCP UI lives. | Keeps PR4 backend-focused; keeps the `web/` surface in one place. |
| **D6** | **3-PR decomposition** (PR4a gateway / PR4b api-registry / PR4c api-OAuth), mirroring WS3's gateway→transport→api split. | Isolates the security-review surfaces; each is independently shippable behind a flag. |

---

## 2. Architecture & data flow

```
          mcp.yaml (operator) ──loaded by──►  GATEWAY  (sole egress, MCP-protocol speaker)
                                              │  MCPToolProviderAdapter (mcp SDK, streamable_http)
 MCP server ◄── streamable_http (initialize → JSON-RPC) ──┤  every call: validate_egress_target (SSRF/allowlist)
                                              │  GET  /v1/tools/{provider}            → list_tools (discovery)   [NEW]
                                              │  POST /v1/tools/{provider}/{tool}     {args, user_token?}        [EXTENDED]
                                              ▲
   api/app/mcp/ :  registry • discovery-cache (DB) • per-tool enable/disable • OAuth flow • token store (DB, Fernet)
                                              ▲
   user ── consent ──► api OAuth (authz-code + PKCE) ─► encrypted per-user token ─► supplied per-call to the gateway
                                              ▲
                                 chat / autonomous governed tool-loop  (PR5, out of scope here)
```

**Auth resolution per server (`mcp.yaml` `auth:`):**
- `none` — no credential; operator vouches for the server.
- `bearer` — operator-static token (gateway-side, sourced like other provider keys: `api_key_env` / `api_key_encrypted`).
- `oauth` — the gateway uses the **per-call `user_token`** the api supplies for that session; if absent for an `oauth` server, the call is refused with a typed "mcp_authorization_required" error so the UI can prompt consent.

**Tool metadata mapping.** MCP tool annotations (`readOnlyHint`, `destructiveHint`) map onto the existing `ToolSpec` flags `read_only` / `destructive` / `requires_confirmation`. **Safe default for un-annotated tools** (a server that omits hints): `read_only=False`, `destructive=False`, `requires_confirmation=True` — treat unknown tools as confirmation-required rather than auto-runnable; PR5 enforces the gate. A tool that explicitly declares `readOnlyHint=true` maps to `read_only=True, requires_confirmation=False`; `destructiveHint=true` maps to `destructive=True, requires_confirmation=True`. These flags are cached api-side and carried to PR5.

---

## 3. Components & boundaries

### 3.1 Gateway (PR4a) — `gateway/app/providers/tool/mcp.py`
- **`MCPToolProviderAdapter(ToolProviderAdapter)`** — implements the existing 4-method contract:
  - `list_tools()` → opens a streamable_http session, calls MCP `list_tools`, maps each to a `ToolSpec` (with the annotation→flags mapping above). Live discovery; not static.
  - `invoke_tool(tool, args, *, request_id)` → opens a session, calls MCP `call_tool`, returns a `ToolResult` (payload = MCP result content; byte counts; `skip_anonymization` left at the ADR-0014 default for tool egress, i.e. **False** unless a future policy says otherwise).
  - `health_check()` → cheap `initialize`-only probe.
  - `aclose()` → release any pooled client.
  - Ported from `web/backend/open_webui/utils/mcp/client.py` (the disconnect/cancel-scope discipline in that stub is load-bearing — preserve it). All outbound HTTP through the egress guard.
- **`mcp.yaml` schema + loader** — a Pydantic `MCPServerConfig` (name, `server_url`, `auth: none|bearer|oauth`, `egress_tier`, `allowlist.hosts`, optional `tool_policy`, `rate_limit`). The gateway config loader reads `MCP_CONFIG_PATH` (default sibling of `gateway.yaml`) and synthesizes each into a `type: mcp` `ToolProviderConfig` merged into `tool_providers`. `mcp.yaml.example` documents the shape.
- **Discovery endpoint** — `GET /v1/tools/{provider}` → `adapter.list_tools()` as JSON; gateway-key gated like the invoke transport; `GatewayError`-enveloped.
- **Per-call token** — extend `ToolCallRequest` (and the discovery path) with an optional `user_token`; `route_tool_call` threads it to the adapter for `oauth` servers. **Never logged**; never written to `tool_egress_log` (counts only).
- **New dep:** `mcp` SDK — one SBOM entry, gateway only. Justified: it *is* the client.

### 3.2 api registry/cache/admin (PR4b) — `api/app/mcp/`
- **registry** — enumerates configured MCP servers via the existing `GatewayClient.list_tool_providers()` filtered to `type == "mcp"` (no second config read api-side).
- **discovery cache** — calls the gateway discovery endpoint, upserts `mcp_tools` rows; refresh on demand. Per-tool `enabled` toggle is persisted api-side and is authoritative for what PR5 exposes to the model.
- **admin surface** — `/api/v1/admin/mcp`: list servers (+ cached tools + enabled state), `POST .../refresh` (re-discover), `PATCH .../tools/{...}` (enable/disable). `AdminUser`-gated.
- Works **end-to-end for `none`/`bearer` servers** without PR4c.

### 3.3 api OAuth (PR4c) — `api/app/mcp/oauth.py` + token store
- **Flow** — `GET /api/v1/mcp/oauth/{server}/authorize` (active user) → builds the authz-code+PKCE redirect to the MCP server's authorization endpoint, stashes the PKCE verifier + state server-side; `GET /api/v1/mcp/oauth/{server}/callback` → validates state, exchanges code → access/refresh tokens.
- **Token store** — `mcp_oauth_tokens`, tokens Fernet-encrypted via `app.security.encryption` (same pattern as Slack/Teams tenant secrets). Refresh on expiry before a tool call; revoke on disconnect.
- **Per-call plumbing** — the research/tool path supplies the decrypted access token to the gateway as `user_token`. Retire the `web/` stub here (its role is fully replaced).
- **Security review** — auth + secret-storage path → CODEOWNERS routes to security reviewers.

---

## 4. Data model (api, migration 0050; head is 0049)

```
mcp_tools                                   -- discovery cache (operator/global, not per-user)
  provider_name   text     ┐ PK
  tool_name       text     ┘
  description     text
  parameters      jsonb              -- JSON-schema for the tool's args
  read_only       boolean
  destructive     boolean
  requires_confirmation boolean
  enabled         boolean  default true   -- operator toggle; authoritative for PR5 exposure
  discovered_at   timestamptz

mcp_oauth_tokens                            -- per-user (PR4c)
  user_id         uuid     ┐ PK  (FK users)
  provider_name   text     ┘
  access_token    bytea              -- Fernet ciphertext
  refresh_token   bytea              -- Fernet ciphertext (nullable)
  expires_at      timestamptz
  scopes          text[]
```

OpenAPI: `docs/api/backend-openapi.yaml` gains `/api/v1/admin/mcp*` (PR4b) and `/api/v1/mcp/oauth/*` (PR4c). Gateway OpenAPI gains `GET /v1/tools/{provider}` (PR4a). Collision guards: `IMPLEMENTED_ROUTES` + `EXPECTED_PATHS` + pinned count (currently **124**) bumped per route, in the same commit.

## 5. Feature flags / shippability
- MCP is **off** until `mcp.yaml` declares a server (no servers → `list_tool_providers` returns none → admin surface lists nothing, no egress).
- OAuth engages **only** for `auth: oauth` servers; `none`/`bearer` servers are fully functional after PR4b.
- PR4a ships behind the config gate; PR4b is usable with token-/no-auth servers; PR4c layers OAuth on top. Each is independently revertible.

## 6. Testing
- **Gateway (PR4a):** an in-memory / fake MCP server (the `mcp` SDK ships an in-memory transport usable in tests) exercising `list_tools`/`invoke_tool` mapping, annotation→flags defaults, egress-tier refusal, SSRF allowlist refusal, the three auth modes (incl. missing-token refusal for `oauth`), and `user_token` never appearing in `tool_egress_log`. Optional live `-m provider` test against a reference MCP server.
- **api (PR4b):** discovery-cache upsert/refresh, enable/disable, `/admin/mcp` surface, registry filtering to `type==mcp`.
- **api (PR4c):** authz-code+PKCE happy path + state/verifier validation (mock gateway + mock MCP authz server), token encrypt/decrypt round-trip, refresh-on-expiry, per-call token plumbing to the gateway, decrypted tokens never logged.

## 7. Out of scope (explicit)
- stdio transport (parity is `streamable_http` only).
- The governed chat tool-loop + `retrieve_caselaw`/`call_mcp_tool` `ToolIntent`s + per-turn cap + confirmation-gate SSE pause/resume → **PR5**.
- MCP provenance pills, the consent UI, destructive-confirm prompts → **PR6/WS5**.
- Tool-path OpenTelemetry spans → deferred enhancement (filed; ADR 0014 D3 / 0015 D5).

## 8. Confirm-in-planning (grounded, not forks)
- Exact `mcp` SDK package name + pinned version for the gateway SBOM; its in-memory test transport API.
- The MCP authorization spec flow specifics (dynamic client registration vs pre-registered client; PKCE S256) and how `mcp.yaml` declares the client id/secret or DCR.
- The gateway config-loader extension for `MCP_CONFIG_PATH` (merge vs sibling holder; reload semantics via `MutableConfigHolder`).
- Whether the discovery endpoint should be `GET /v1/tools/{provider}` or `/v1/tools/{provider}/specs` (avoid collision with a future per-provider resource).
</content>
</invoke>
