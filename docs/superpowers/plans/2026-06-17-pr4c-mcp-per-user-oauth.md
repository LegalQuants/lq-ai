# PR4c — per-user OAuth for MCP servers (WS2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let a user authorize against an `auth: oauth` MCP server so the api can obtain, store, refresh, and supply a per-user access token to the gateway for that user's MCP tool calls — completing WS2. Built on merged PR4a (gateway adapter + `X-LQ-AI-User-Token` per-call header) and PR4b (registry/cache/admin).

**Architecture:** MCP authorization is full OAuth 2.1 (PKCE mandatory) + MCP-specific discovery (RFC 9728 protected-resource-metadata → RFC 8414 auth-server-metadata), the `resource` parameter (RFC 8707), and `iss` validation (RFC 9207). The consent step is **interactive + asynchronous**, and the gateway's `streamable_http` connect is **non-interactive + per-call** — so the OAuth flow is driven **out-of-band by the api** (it has the user + a web redirect), and the gateway just uses the resulting access token as a static `Authorization: Bearer` on its session (the `X-LQ-AI-User-Token` path already wired in PR4a). The api uses **authlib** for the OAuth 2.1 core (PKCE / token exchange / refresh) plus thin hand-written MCP glue (PRM + AS discovery, `resource` param, `iss` check). Tokens are **Fernet-encrypted** at rest under a dedicated MCP master key.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, **authlib** (new api dep), httpx, Fernet (`cryptography`, already a dep), Pydantic v2, pytest + respx.

**Decisions (locked 2026-06-17):**
- **D-c1** OAuth impl: **authlib** for OAuth-2.1 core + thin MCP glue (not hand-rolled; not the transport-coupled mcp SDK).
- **D-c2** Client registration: **pre-registered `client_id`** per server in `mcp.yaml` (no DCR in v1).
- **D-c3** **Public clients only in v1** (PKCE, no client secret). Confidential clients (with a secret) need a gateway→api secret-handoff → **DE-340** (deferred). OAuth 2.1+PKCE makes public clients first-class, and this sidesteps exposing the gateway-held secret to the api.
- **D-c4** The api reads the non-secret OAuth config (`oauth_client_id`, server canonical URI) from the gateway's **existing** sanitized `GET /admin/v1/config`.
- **D-c6 (LOCKED 2026-06-17 — ADR-0014-pure):** the OAuth **discovery + token-exchange/refresh** HTTP calls go **through the gateway**, not direct from the api. Add gateway passthrough endpoints (egress-guarded) so 100% of third-party egress stays at the one audited boundary. The browser **authorize redirect** is the user-agent → AS directly (not server egress), so it stays api-driven. **Implication:** the auth-server (AS) host is discovered at runtime (from PRM) and may differ from the MCP server host — so the operator MUST allowlist the AS host in that server's `mcp.yaml` `allowlist.hosts` alongside the MCP server host; the gateway `validate_egress_target` checks the discovered AS/token URLs against that allowlist. Document this in `mcp.yaml.example`.
- **D-c5** Per-user tokens are Fernet-encrypted under a **dedicated** `LQ_AI_MCP_MASTER_KEY` (separate blast radius from bridge secrets), reusing `app/security/encryption.py`'s Fernet helper.

**Gate:** touches a gateway config field (`gateway/**`) AND api auth/crypto/token-storage → **security review (Kevin merges).**

**Pre-flight facts (verified against merged `main` @ `786801a`):**
- PR4a per-call token: `GET /v1/tools/{provider}` and `POST /v1/tools/{provider}/{tool}` accept `X-LQ-AI-User-Token`; `GatewayClient.discover_tools(provider, *, user_token=None, ...)` and `call_tool(...)` forward it. PR4c just needs to SUPPLY it.
- `MCPServerConfig` (`gateway/app/config.py`, added in PR4a): `name, server_url, auth (none|bearer|oauth), api_key_env, api_key_encrypted, egress_tier, allowlist, rate_limit, enabled`, `extra="forbid"`, `to_tool_provider_config()`. `ToolProviderConfig` is `extra="allow"`, and `/admin/v1/config` returns `config.model_dump(mode="json")` (full, secrets are env-var names only) — so a new non-secret `oauth_client_id` flows to the api.
- api `GatewayClient.get_admin_config(*, request_id=None)` returns the sanitized config dict; `list_tool_providers` strips to `{name,type}` — PR4c reads `get_admin_config()` directly to get `oauth_client_id` + `base_url` for mcp providers.
- Encryption: `app/security/encryption.py` — `BridgeTokenEncryptor` (Fernet) with module helper `_fernet_from(master_key)`, `generate_master_key()`. Mirror it for MCP with `LQ_AI_MCP_MASTER_KEY`.
- Migration head is **0050** (`0050_mcp_tools.py`); PR4c migration is **0051**. Model registry: `api/app/models/__init__.py`.
- Collision guards: `IMPLEMENTED_ROUTES` (test_endpoints.py) + `EXPECTED_PATHS` + count (currently **127** after PR4b) in test_openapi.py.
- `web/backend/open_webui/utils/mcp/client.py` is retired in this PR (its role — the MCP client + OAuth — is fully replaced by the gateway adapter (PR4a) + this api OAuth flow).

**Run/gate reminders:** api tests via host venv + throwaway pgvector :15433 (conftest auto-migrates); gateway tests via gateway venv. ruff is pinned **0.15.17** (PR #168) — run `ruff format` to apply. Commit `-s` + the Opus-4.8 trailer; stage explicitly.

---

## The MCP OAuth flow (what the api implements, out-of-band)

```
1. DISCOVERY (per server, cached):
   GET {server_url}/.well-known/oauth-protected-resource   (RFC 9728)
        -> { authorization_servers: [AS_URL], resource: CANONICAL_URI, scopes_supported? }
   GET {AS_URL}/.well-known/oauth-authorization-server      (RFC 8414; fall back to OIDC)
        -> { authorization_endpoint, token_endpoint, issuer, authorization_response_iss_parameter_supported? }

2. AUTHORIZE (user clicks "connect"):
   api builds authorize URL via authlib (client_id from mcp.yaml, PKCE S256, scope, resource=CANONICAL_URI,
        redirect_uri = api callback), stashes {state, code_verifier, issuer, server} server-side, 302s the user.

3. CALLBACK (AS redirects back):
   GET /api/v1/mcp/oauth/{server}/callback?code=&state=&iss=
   -> validate state; validate iss against recorded issuer (RFC 9207); authlib fetch_token(token_endpoint,
      code, code_verifier, resource=CANONICAL_URI) -> {access_token, refresh_token?, expires_in, scope}
   -> Fernet-encrypt + persist in mcp_oauth_tokens(user_id, provider).

4. USE (per tool call):
   api get_valid_token(user, server): load row; if expired & refresh_token present -> authlib refresh_token(...)
      -> re-encrypt+persist; return access_token. Supply as user_token to discover_tools/call_tool
      (gateway sets Authorization: Bearer on the streamable_http session).
```

---

## File structure

| File | Responsibility |
|---|---|
| `api/pyproject.toml` (modify) | add `authlib` dep |
| `api/app/security/encryption.py` (modify) | add `MCPTokenEncryptor` (LQ_AI_MCP_MASTER_KEY) reusing the Fernet helper |
| `gateway/app/config.py` (modify) | add `oauth_client_id: str | None` to `MCPServerConfig` + pass through in `to_tool_provider_config` |
| `mcp.yaml.example` (modify) | document `oauth_client_id` on an oauth server |
| `api/app/models/mcp_oauth.py` (create) | `MCPOAuthToken` model |
| `api/app/models/__init__.py` (modify) | register it |
| `api/alembic/versions/0051_mcp_oauth_tokens.py` (create) | table |
| `api/app/mcp/oauth.py` (create) | discovery glue + authlib authorize/exchange/refresh + token store + `get_valid_token` |
| `api/app/clients/gateway.py` (modify) | `list_mcp_oauth_config()` helper reading `get_admin_config()` for `{name, server_url/base_url, oauth_client_id}` of oauth mcp servers |
| `api/app/schemas/mcp_oauth.py` (create) | status/response schemas |
| `api/app/api/mcp_oauth.py` (create) | `/api/v1/mcp/oauth/{server}/{authorize,callback}` + status/disconnect |
| `api/app/api/__init__.py` (modify) | register router |
| `api/app/mcp/service.py` (modify) | `refresh_server` supplies `user_token` for oauth servers (via `get_valid_token`) |
| `web/backend/open_webui/utils/mcp/client.py` (delete) | retire the stub |
| collision guards + `docs/api/backend-openapi.yaml` | new routes |
| `api/tests/test_mcp_oauth*.py` (create) | discovery, flow, token store, refresh, endpoints |

---

## Task 1: deps + MCP token encryptor

**Files:** `api/pyproject.toml`, `api/app/security/encryption.py`, `api/tests/test_mcp_encryption.py`

- [ ] **Step 1 (controller/main-loop — needs network): add authlib.** Add `"authlib>=1.3,<2",` to `api/pyproject.toml` runtime deps with a justifying comment (vetted OAuth 2.1 client; avoids hand-owning PKCE/discovery/refresh security code — CLAUDE.md dependency bar). Install: `cd api && .venv/bin/pip install 'authlib>=1.3,<2'`. Confirm `pip check` clean. (The implementer subagent has no network, so the controller does this step before dispatching.)
- [ ] **Step 2: failing test** for an `MCPTokenEncryptor` that round-trips under `LQ_AI_MCP_MASTER_KEY` and raises on wrong key — mirror existing `BridgeTokenEncryptor` tests.
- [ ] **Step 3: implement** `MCPTokenEncryptor` in `app/security/encryption.py` reusing the module's `_fernet_from`, with `MCP_MASTER_KEY_ENV = "LQ_AI_MCP_MASTER_KEY"`, `from_environ()`, `encrypt(str)->bytes`, `decrypt(bytes)->str`, and an `MCPEncryptionError`. Add to `__all__`.
- [ ] **Step 4: gates** (`pytest tests/test_mcp_encryption.py`, ruff, mypy). **Commit.**

## Task 2: gateway `oauth_client_id` on `MCPServerConfig`

**Files:** `gateway/app/config.py`, `mcp.yaml.example`, `gateway/tests/test_mcp_config.py`

- [ ] **Step 1: failing test** — `MCPServerConfig(..., auth="oauth", oauth_client_id="lqai-acme")` is accepted and `to_tool_provider_config().oauth_client_id == "lqai-acme"`; for non-oauth auth, `oauth_client_id` may be None.
- [ ] **Step 2: implement** — add `oauth_client_id: str | None = None` to `MCPServerConfig`; in `_bearer_needs_key` (or a new validator) optionally require `oauth_client_id` when `auth=="oauth"` (recommend: require it, with a clear error — an oauth server with no client_id can't be authorized). Pass `oauth_client_id` through in `to_tool_provider_config()`'s dict. Update `mcp.yaml.example`'s commented oauth example to show `oauth_client_id`.
- [ ] **Step 3: gates** (gateway pytest + ruff + mypy --strict). **Commit.** (gateway/** — part of the security-review surface.)

## Task 3: `mcp_oauth_tokens` model + migration 0051

**Files:** `api/app/models/mcp_oauth.py`, `api/app/models/__init__.py`, `api/alembic/versions/0051_mcp_oauth_tokens.py`, `api/tests/test_mcp_oauth_models.py`

Mirror the PR4b model/migration pattern (Task 1 of PR4b). Table `mcp_oauth_tokens`:
```
user_id        uuid        ┐ PK   (FK users.id, ON DELETE CASCADE)
provider_name  text        ┘
access_token   bytea  NOT NULL     -- Fernet ciphertext
refresh_token  bytea                -- Fernet ciphertext, nullable
expires_at     timestamptz          -- nullable (some AS omit expiry)
scopes         text[]               -- granted scopes
issuer         text                 -- recorded AS issuer (RFC 9207)
created_at     timestamptz NOT NULL default now()
updated_at     timestamptz NOT NULL default now()
```
- [ ] model (composite PK, `Mapped[...]`), register in `__init__.py`, migration `revision="0051"`/`down_revision="0050"` with `op.create_table` + FK to `users` (ON DELETE CASCADE) — check how other per-user tables declare the users FK and match. Column test. **Commit.**

## Task 4: api OAuth service (`api/app/mcp/oauth.py`) — the security-critical heart

**Files:** `api/app/mcp/oauth.py`, `api/app/clients/gateway.py` (config helper), `api/tests/test_mcp_oauth_service.py`

### 4a — gateway config helper
- [ ] Add `GatewayClient.list_mcp_oauth_config(*, request_id=None) -> list[dict]` reading `get_admin_config()` → for each `tool_providers` entry with `type=="mcp"` and `auth=="oauth"`, return `{"name", "server_url": base_url, "oauth_client_id"}`. (Non-secret; mirrors `list_tool_providers`.) Test with respx on `/admin/v1/config`.

### 4b — discovery glue (hand-written; MCP-specific)
- [ ] `async def discover_endpoints(server)` — resolves `authorization_endpoint`, `token_endpoint`, `issuer`, `resource` (canonical URI), `scopes_supported`, `authorization_response_iss_parameter_supported` via the **gateway passthrough** (D-c6): the gateway performs `GET {server_url}/.well-known/oauth-protected-resource` (RFC 9728) → `authorization_servers[0]` → `GET {as}/.well-known/oauth-authorization-server` (RFC 8414, fall back to `/.well-known/openid-configuration`), each `validate_egress_target`-guarded against the server's allowlist (which must include the AS host — D-c6). The api calls the new gateway endpoint and parses the returned metadata. Cache per-process with a TTL.

> **DECIDED (b) — ADR-0014-pure (D-c6):** route OAuth discovery + token-exchange/refresh through the gateway. **New gateway task (do FIRST, it's the gateway-side of PR4c):** add an egress-guarded OAuth passthrough — e.g. `POST /v1/oauth/{provider}/discover` (returns the merged PRM+AS metadata) and `POST /v1/oauth/{provider}/token` (proxies the form-POST to the AS `token_endpoint` for both authorization_code and refresh grants, returning the token response). Both gateway-key-gated like `/v1/tools/...`; both `validate_egress_target` the target URL against the provider's allowlist; **the user's auth code / refresh token / client creds pass through but are NEVER logged or written to `tool_egress_log`** (counts-only, same discipline as the tool path). The browser authorize redirect stays api-driven (user-agent → AS directly). authlib still builds the authorize URL + PKCE and parses the token response api-side; only the two HTTP egress calls move behind the gateway.

### 4c — authorize / callback / refresh (authlib)
- [ ] `build_authorize_url(server, user, redirect_uri) -> (url, state)`: resolve client_id via `list_mcp_oauth_config`; discover endpoints; `AsyncOAuth2Client(client_id=cid, redirect_uri=redirect_uri, scope=..., code_challenge_method="S256")`; generate `code_verifier` (`authlib.common.security.generate_token(48)`); `client.create_authorization_url(authorization_endpoint, code_verifier=code_verifier, resource=resource, state=state)`; stash `{state -> (user_id, server, code_verifier, issuer, resource, token_endpoint)}` server-side (a short-TTL store: a dedicated `mcp_oauth_state` table OR signed state — recommend a small table or the existing cache; FLAG choice). Return the URL.
- [ ] `exchange_code(state, code, iss) -> MCPOAuthToken`: look up the stashed state; **validate `iss`** against the recorded issuer per RFC 9207 (reject on mismatch/absence-when-required); `await client.fetch_token(token_endpoint, code=code, code_verifier=code_verifier, resource=resource)`; Fernet-encrypt access+refresh; upsert `mcp_oauth_tokens`. Delete the consumed state.
- [ ] `get_valid_token(db, *, user_id, server) -> str | None`: load row; if absent → None; if `expires_at` in the past and `refresh_token` present → `await client.refresh_token(token_endpoint, refresh_token=...)`, re-encrypt+persist; return the (decrypted) access token. If expired with no refresh → None (caller treats as "needs re-auth").
- [ ] `disconnect(db, *, user_id, server)`: delete the row (optionally call the AS revocation endpoint if advertised — optional).
- [ ] Tests (respx the discovery + token endpoints; fake clock for expiry): discovery parse, authorize-url has PKCE challenge + resource, iss-mismatch rejected, exchange stores encrypted token, refresh-on-expiry, get_valid_token returns None when no token / expired-no-refresh. **Commit.**

## Task 5: api OAuth endpoints + guards + OpenAPI

**Files:** `api/app/schemas/mcp_oauth.py`, `api/app/api/mcp_oauth.py`, `api/app/api/__init__.py`, collision guards, `docs/api/backend-openapi.yaml`, `api/tests/test_mcp_oauth_endpoints.py`

Endpoints (`ActiveUser`-gated — these are per-user, NOT admin):
- `GET /api/v1/mcp/oauth/{server}/authorize` → 302 to the AS authorize URL (sets state).
- `GET /api/v1/mcp/oauth/{server}/callback?code&state&iss` → exchange + store; redirect to a web "connected" page (or 200 JSON in v1; the polished UI is PR6) — FLAG the redirect target.
- `GET /api/v1/mcp/oauth/{server}/status` → `{connected: bool, scopes, expires_at}` for the current user.
- `DELETE /api/v1/mcp/oauth/{server}` → disconnect (204).

- [ ] schemas, router (mind the `204` recipe: `response_class=Response`), register under `_active`, audit `mcp.oauth_connected` / `mcp.oauth_disconnected`. Collision guards: add the 4 routes (paths dedupe to `/api/v1/mcp/oauth/{server}/authorize`, `/callback`, `/status`, `/api/v1/mcp/oauth/{server}`) → **127 → 131**; IMPLEMENTED_ROUTES tuples; OpenAPI entries. Tests: authorize 302 + state set; callback happy/iss-mismatch/bad-state; status connected/not; disconnect; non-authed 401. **Commit.**

## Task 6: supply the token on the tool path + retire the web stub

**Files:** `api/app/mcp/service.py`, delete `web/backend/open_webui/utils/mcp/client.py`, `api/tests/test_mcp_service.py`

- [ ] `refresh_server(db, *, provider, user_id=None, request_id=None)` — when the provider is `auth: oauth`, call `oauth.get_valid_token(db, user_id=user_id, server=provider)` and pass it as `user_token` to `discover_tools`. If no valid token → raise a typed `MCPAuthorizationRequired` (→ a 409/401 the UI maps to "connect this server"). For none/bearer, unchanged. (The admin refresh in PR4b had no user context; oauth discovery now needs a user — so admin refresh of an oauth server should surface "per-user; use the user-scoped path" rather than silently failing. FLAG: decide whether admin refresh of oauth servers is disallowed or uses the admin's own token.) Add tests.
- [ ] Delete `web/backend/open_webui/utils/mcp/client.py` and grep for any remaining import of it (`grep -rn "utils.mcp.client\|utils/mcp/client" web/`); remove dead references. Confirm `web/` still builds (the stub was unwired per the proposal, so this should be a clean delete). **Commit.**

## Task 7: full gates + ship (security review)

- [ ] api full suite (`pytest`), ruff format --check + ruff check, mypy; gateway suite + ruff + mypy --strict (for the Task 2 change). Final holistic review focused on: token never logged/echoed; `iss` validation present; state single-use + TTL; PKCE S256; tokens encrypted at rest (separate key); the ADR-0014 discovery-egress exception documented + accepted; refresh path. Push both remotes; PR; CI; **Kevin reviews/merges** (gateway/** + auth/crypto). Report SHA.

---

## Definition of done (PR4c)
- A user can `connect` an `auth: oauth` MCP server (authorize→callback), the token is Fernet-encrypted at rest under `LQ_AI_MCP_MASTER_KEY`, refreshed on expiry, and supplied to the gateway per-call so that user's MCP tools work.
- `iss` (RFC 9207) + PKCE (S256) + `resource` (RFC 8707) all enforced; state single-use + TTL.
- Public clients (PKCE, no secret); confidential clients = DE-340.
- `web/` MCP stub deleted. Full api + gateway gates green. **Gate:** security review.

## Confirm-in-planning / FLAGS for the implementer + reviewer
- authlib's exact `AsyncOAuth2Client` API for PKCE (`create_authorization_url(code_verifier=...)`, `fetch_token`, `refresh_token`) against the installed `authlib>=1.3` — verify and adapt the snippets.
- ~~ADR-0014 discovery-egress~~ **RESOLVED → (b) gateway passthrough (D-c6).** Add the gateway OAuth passthrough endpoints (new gateway-side task, build before the api OAuth service); operator allowlists the AS host in `mcp.yaml`. This makes PR4c's gateway surface bigger than "just the `oauth_client_id` field" — Tasks 2 + the passthrough are both `gateway/**`.
- **State store** (Task 4c) — dedicated `mcp_oauth_state` table vs signed-state cookie vs in-process cache. Recommend a small table (survives restarts, multi-worker safe).
- **callback redirect target** (Task 5) — JSON 200 (v1) vs redirect to a web page (needs PR6 UI).
- **admin refresh of oauth servers** (Task 6) — disallow vs admin-token. Recommend: admin refresh covers none/bearer; oauth discovery/refresh is user-scoped.

## Follow-on
- **DE-340** — confidential MCP OAuth clients (client_secret): needs a gateway→api secret-handoff (the api drives token exchange but the secret is gateway-held). Public-client/PKCE covers v1.
- **PR5** — governed chat tool-loop + `retrieve_caselaw`/`call_mcp_tool` ToolIntents (consumes the enabled MCP tools + per-user tokens this PR makes available).
</content>
