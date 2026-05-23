# Slack / Teams Light Intake Bridges

> The intake bridges let an operator connect a Slack workspace or a
> Microsoft 365 tenant to one LQ.AI deployment via OAuth. Per PRD §3.15:
> in-house teams report that most incoming work arrives over Slack,
> Teams, or email — a web-only product structurally underweights the
> channels users live in. The bridges close that gap with bounded scope:
> *light* intake (install + identity binding), explicitly **not** matter
> management, triage, or SLA tracking (the boundary with Streamline AI's
> category per §1.6).

This doc describes what shipped in M3 Phase D — the install / OAuth /
identity-binding plumbing for both bridges, the api-side persistence and
encryption surfaces, and the admin management page. It is the
implementation companion to PRD §3.15.

**Honest state up front.** What M3 shipped is **plumbing only**. The
service scaffolds, the OAuth handlers, the bridge→api persistence path,
at-rest token encryption, and the admin surface all exist and were
verified *in isolation* during M3-E1. The end-to-end install flow — a
real OAuth round-trip against a public-URL tunnel back into a live Slack
workspace / M365 tenant — has **never** been exercised. The bridges'
status is "plumbing shipped, real-OAuth integration **unverified**,"
tracked as [DE-312](#references) (P1). The `/lq` slash-command surface
(the user-facing reason to install a bridge) is descoped to M4 /
community contribution, tracked as [DE-288](#references). Do not read
this document as a claim that the bridges work end-to-end.

---

## Scope

"Connect Slack / Teams to LQ.AI" can mean three things. M3 ships the
first as plumbing; the second is descoped to M4; the third is out of
scope entirely.

1. **Install + OAuth + identity binding** *(this plumbing, shipped in M3
   Phase D)* — an operator can stand up the `slack-bridge` /
   `teams-bridge` service, complete the OAuth handshake, and have the
   workspace / tenant row surface in the admin UI. This is install
   substrate, not a user-facing feature.

2. **The `/lq` slash-command surface** *(descoped to M4 / community;
   tracked at [DE-288](#references))* — `/lq` on a thread forwards the
   thread as the seed of an LQ.AI chat; `/lq ask "<question>"` runs a
   configured quick-ask skill and replies in-thread. This is the reason
   an operator would install a bridge. It does **not** exist at v0.3.0:
   no slash-command handler, no per-user identity mapping, no
   in-thread reply. The admin UI carries visible-but-disabled
   quick-ask-skill pickers and an empty `/lq` audit-log shell as
   forward hooks for this work.

3. **Full intake / triage / matter management** *(out of scope
   entirely; PRD §1.6)* — the explicit boundary with Streamline AI's
   category. The bridges are *light* by design.

The two shipped bridges are architecturally parallel but not identical
— Slack issues per-workspace bot tokens that must be encrypted at rest;
Teams uses app-level bot credentials with nothing per-tenant to encrypt.
That asymmetry runs through the persistence and security sections below.

**What M3-E1 actually verified (in isolation).** Service health
(`/healthz` + `/readyz`); bridge-bearer auth (POST→201 with the right
token, →401 with a wrong one); the Slack bot token landing **encrypted**
at rest (confirmed Fernet ciphertext, not plaintext); the admin
`intake-bridges` endpoint surfacing the persisted rows; and soft-delete
(→204). What M3-E1 did **not** verify: any real OAuth callback. No
ngrok / cloudflared tunnel was ever stood up during M3-D1 / M3-D3
development (no `LQ_AI_BRIDGE_PUBLIC_URL` in any `.env`, no tunnel
reference in any commit or handoff). The install + real OAuth callback +
identity-binding flow is unverified — see [DE-312](#references) and
[Known limitations](#known-limitations).

---

## Architecture

Each bridge is a small standalone FastAPI service that sits between an
external identity provider (Slack / Microsoft) and the LQ.AI api. The
bridges hold no LQ.AI state of their own; every OAuth callback ends with
a POST to a bridge-facing persistence endpoint on the api.

```
   Operator                 Bridge service               LQ.AI api
   (browser)                (slack-/teams-bridge)         (FastAPI)
      │                            │                          │
      │  click "install"           │                          │
      ├───────────────────────────►│  GET /…/oauth/install    │
      │                            │  (mint state, redirect)   │
      │ ◄──── 302 to provider ─────┤                          │
      │                            │                          │
   [consent at Slack / Microsoft]  │                          │
      │                            │                          │
      │  GET /…/oauth/callback?code=…&state=…                 │
      ├───────────────────────────►│                          │
      │                            │  exchange code → token   │
      │                            │  (provider token endpoint)│
      │                            │                          │
      │                            │  POST /api/v1/integrations/…
      │                            ├─────────────────────────►│  upsert
      │                            │  Authorization: Bearer    │  + encrypt
      │                            │  LQ_AI_BRIDGE_TOKEN       │  (Slack only)
      │                            │ ◄──────── 201 ───────────┤
      │ ◄──── HTML success page ───┤                          │
```

Three architectural facts were locked across M3 Phase D and govern both
bridges:

1. **One shared bridge bearer token.** A single `LQ_AI_BRIDGE_TOKEN`
   authenticates *every* bridge→api POST (Slack workspaces, Teams
   tenants, any future bridge). The api matches it constant-time via the
   shared `require_bridge_auth` dependency. This is service-to-service
   auth with no user context — not a user JWT (M3-D1 decision #3 /
   M3-D3 decision #2).

2. **One shared bridge encryption key, distinct from the gateway's.**
   At-rest bridge secrets are encrypted under `LQ_AI_BRIDGE_MASTER_KEY`,
   deliberately separate from the gateway's `LQ_AI_GATEWAY_MASTER_KEY`.
   Slack bot tokens (bot-impersonation blast radius) and provider API
   keys (inference-routing blast radius) live in different threat
   models, so they get different keys (M3-D1 decision #1). At v0.3.0
   the *only* at-rest secret this key protects is
   `slack_workspaces.bot_token_encrypted`; `teams_tenants` has none.

3. **Bridges are profile-gated.** The services ship behind the `slack`
   and `teams` Compose profiles so operators who don't use them don't
   pay the SBOM cost. An air-gapped or chat-free deployment never runs
   the services. (See the [DE-305 gotcha](#known-limitations) — the
   profile gating is undermined today by required-error env
   interpolation in `docker-compose.yml`.)

Both bridge services share the same shape: a `create_app()` factory, a
`config.py` `Settings` (pydantic-settings, same pattern as `api/` and
`gateway/`), an `oauth.py` router, opt-in OTel (`observability.py`,
no telemetry by default per PRD §5.7), and a `/healthz` + `/readyz`
health surface where `/readyz` returns 503 unless the configured
`LQ_AI_BACKEND_URL` is reachable.

---

## Slack bridge

The Slack bridge ([`slack-bridge/`](../slack-bridge/), port 8002)
implements the Slack `oauth.v2.access` install flow.

### OAuth install flow

[`slack-bridge/app/oauth.py`](../slack-bridge/app/oauth.py):

1. **`GET /slack/oauth/install`** — mints a random `state` token
   (`secrets.token_urlsafe(32)`, CSRF protection), stores it in an
   in-memory store with a 10-minute TTL, and 302-redirects to Slack's
   consent screen (`https://slack.com/oauth/v2/authorize`) with the
   App's `client_id`, the requested scopes, the `redirect_uri` built
   from `LQ_AI_BRIDGE_PUBLIC_URL`, and the `state`.
2. **`GET /slack/oauth/callback`** — verifies the round-tripped `state`
   against the store (single-use: popped on read, replay-protected),
   exchanges the `code` for a bot token via `oauth.v2.access` (using
   the `slack_sdk` `AsyncWebClient`, lazily imported off the hot path),
   assembles the workspace record, and POSTs it to the api.
3. **Success / failure** — returns a plain HTML success page (the
   operator is in a browser, not curl). Every failure path — user
   denial, token-exchange error, malformed Slack response, api
   persistence rejection — renders an HTML error page rather than
   raising, with a short correlation id on the success page for support
   reference.

The workspace record sent to the api is:
`{team_id, team_name, bot_token, bot_user_id, installer_slack_user_id,
scope}`. The bridge then POSTs it to
`POST /api/v1/integrations/slack/workspaces` with
`Authorization: Bearer LQ_AI_BRIDGE_TOKEN`.

### State-token caveat

State tokens live **in-memory** in the bridge (`_STATE_STORE`), garbage-
collected best-effort inside the handlers. The bridge is single-instance
per deployment, so an in-memory store suffices — but a bridge restart
between install initiation and callback invalidates the flow and the
operator must restart the install. (The OAuth comments flag a DE
candidate to persist state tokens api-side so installs survive restarts;
not filed formally yet.)

### Scopes — narrow on purpose

The bridge requests exactly two bot scopes:
[`SCOPES = ["commands", "chat:write"]`](../slack-bridge/app/oauth.py) —
matching the `oauth_config.scopes.bot` block in
[`slack-bridge/manifest.yml`](../slack-bridge/manifest.yml):

- `commands` — for the future `/lq` slash-command surface (DE-288).
- `chat:write` — so the bot can post replies in channels it is invited
  to.

There is no `channels:read` / `groups:read` / `im:read`. **The bot does
not read silent channels** — it only acts on explicit user invocations
(PRD §3.15 permission model). The manifest declares no `slash_commands`
block at v0.3.0 because the slash-command surface is deferred; a
community contributor adding `/lq` extends the manifest via PR.

### Inbound webhook + signature verification

`POST /slack/events`
([`slack-bridge/app/main.py`](../slack-bridge/app/main.py)) is a
verified-but-inert stub. It verifies the Slack request signature
(HMAC-SHA256 over `v0:{timestamp}:{body}` with a 5-minute replay window,
[`slack-bridge/app/signing.py`](../slack-bridge/app/signing.py)) on
every request, handles Slack's one-off `url_verification` challenge, and
otherwise returns 200. The signature check is shipped now so M3-D2's
slash-command handler (DE-288) lands on a verified substrate; no event
type does anything observable at v0.3.0.

### Manifest

[`slack-bridge/manifest.yml`](../slack-bridge/manifest.yml) is the Slack
App manifest the operator pastes into the Slack App admin UI
("From a manifest"). It carries a `${LQ_AI_BRIDGE_PUBLIC_URL}`
placeholder in the `redirect_urls` that the operator substitutes
manually — Slack's manifest UI does not perform env substitution, and
the value must match the `redirect_uri` the bridge builds at runtime or
Slack rejects the callback. `socket_mode`, `org_deploy`, and
`token_rotation` are all disabled.

---

## Teams bridge

The Teams bridge ([`teams-bridge/`](../teams-bridge/), port 8003)
implements the Microsoft identity platform multi-tenant admin-consent
flow.

### OAuth admin-consent flow

[`teams-bridge/app/oauth.py`](../teams-bridge/app/oauth.py):

1. **`GET /teams/oauth/install`** — mints a `state` token (same
   posture as Slack), and 302-redirects to the **multi-tenant**
   authorize endpoint
   (`https://login.microsoftonline.com/common/oauth2/v2.0/authorize`)
   with `response_type=code`, the declared scopes, the `redirect_uri`
   built from `LQ_AI_TEAMS_BRIDGE_PUBLIC_URL`, and
   **`prompt=admin_consent`** so a tenant admin grants consent for the
   whole tenant in one flow.
2. **`GET /teams/oauth/callback`** — verifies `state`, then POSTs to
   the multi-tenant token endpoint
   (`/common/oauth2/v2.0/token`, `grant_type=authorization_code`) to
   exchange the `code` for an `id_token` + `access_token` +
   `refresh_token`.
3. **Identity extraction** — base64url-decodes the `id_token` payload
   **without signature verification** (`_decode_id_token_unverified`),
   reading the `tid` (tenant id) and `oid` (admin object id) claims. The
   decode is intentionally unverified: the token arrived over TLS from
   Microsoft's token endpoint via the bridge's `client_secret`-
   authenticated POST, and the claims grant no LQ.AI-side permissions —
   they only identify which tenant + admin completed the install.
4. **Best-effort display name** — calls Microsoft Graph
   `GET /v1.0/organization` with the access token to fetch the org's
   `displayName` (`_fetch_tenant_display_name`). On **any** failure
   (Graph error, non-200, malformed body) it falls back to the raw
   `tid` rather than failing the whole install.
5. **Persist** — POSTs `{tenant_id, tenant_name, installer_oid}` to
   `POST /api/v1/integrations/teams/tenants` with the shared
   `LQ_AI_BRIDGE_TOKEN` bearer, then returns an HTML success page.

### Architectural decisions (M3-D3)

- **Decision #3 — raw httpx, no botbuilder SDK.** Both the token
  exchange and the Graph lookup are plain HTTP calls. The official
  `botbuilder-core` SDK adds ~15 transitive deps the plumbing doesn't
  need.
- **Decision #4 — multi-tenant.** The authorize/token endpoints use the
  `/common/` tenant placeholder, so one Azure AD multi-tenant app
  registration can host installs from any M365 tenant. The
  `teams_tenants` table can carry many tenant rows concurrently.

### Scopes

[`SCOPES`](../teams-bridge/app/oauth.py) =
`openid`, `profile`, `email`, `offline_access`,
`https://graph.microsoft.com/User.Read`. `User.Read` is the narrowest
scope that returns a Graph-usable access token (for the best-effort
display-name lookup); `offline_access` keeps refresh-token plumbing
alive for future M4 on-behalf-of flows.

### Manifest

[`teams-bridge/manifest.json`](../teams-bridge/manifest.json) is a Teams
app manifest v1.16. It carries `${MICROSOFT_APP_ID}` and
`${LQ_AI_TEAMS_BRIDGE_PUBLIC_HOST}` (bare host, no scheme/path)
placeholders the operator substitutes before uploading to the Teams
Admin Center. The `bots[].commandLists` array is intentionally **empty**
until DE-288 ships; the bot is registered so the install flow +
identity binding work, but it exposes no commands. `webApplicationInfo`
is present for future Azure AD SSO (task-pane / message-extension
surfaces) but is M4 scope.

### No per-tenant token

Teams uses **app-level** bot credentials — one `MICROSOFT_APP_ID` +
`MICROSOFT_APP_PASSWORD` per deployment — regardless of which tenant the
bot runs in. There is therefore nothing per-tenant to encrypt, and the
`teams_tenants` table stores no token. Contrast `slack_workspaces`,
which holds a Fernet-wrapped `bot_token_encrypted`. Per-user refresh
tokens (when M4 lands the on-behalf-of flow) will likely add a separate
`teams_user_tokens` table.

---

## Persisted row shape

Two tables back the bridges. Both use a UUID PK, a unique natural key
(the provider's id), an `installed_at` timestamp defaulting to `now()`,
and a nullable `deleted_at` for soft-delete. Both upsert on the natural
key; re-install revives a soft-deleted row in place (`deleted_at` → NULL)
and `installed_at` stays at the original install time, so an operator
can infer re-install activity from the ciphertext changing without the
install timestamp moving.

### `slack_workspaces` (migration 0037)

[`api/app/models/slack_workspace.py`](../api/app/models/slack_workspace.py),
[`api/alembic/versions/0037_slack_workspaces.py`](../api/alembic/versions/0037_slack_workspaces.py):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | `gen_random_uuid()` |
| `team_id` | text, **unique** | Slack workspace id (`T0…`); the upsert conflict key |
| `team_name` | text | Display name snapshotted at install; not auto-refreshed |
| `bot_token_encrypted` | bytea | **Fernet-wrapped** `xoxb-…` bot token; decrypted in-memory only when needed |
| `bot_user_id` | text | Slack user id of the bot user |
| `installer_slack_user_id` | text | Operator who installed — **audit only**, grants no LQ.AI permissions |
| `scope` | text | Comma-separated consented scopes, stored verbatim for audit |
| `installed_at` | timestamptz | `now()` |
| `deleted_at` | timestamptz, null | Soft-delete; revived on re-install |

The persistence endpoint
([`api/app/api/integrations_slack.py`](../api/app/api/integrations_slack.py))
encrypts `body.bot_token` with `BridgeTokenEncryptor` *before* the row
ever lands. The plaintext token travels the trusted in-cluster network
under the bridge bearer; it is never stored in plaintext and is omitted
from the `SlackWorkspaceResponse` echoed back to the bridge.

### `teams_tenants` (migration 0038)

[`api/app/models/teams_tenant.py`](../api/app/models/teams_tenant.py),
[`api/alembic/versions/0038_teams_tenants.py`](../api/alembic/versions/0038_teams_tenants.py):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | `gen_random_uuid()` |
| `tenant_id` | text, **unique** | M365 directory GUID (`tid` claim); the upsert conflict key |
| `tenant_name` | text | Best-effort Graph `displayName`, falls back to `tid` |
| `installer_oid` | text | M365 `oid` of the consenting admin — **audit only** |
| `installed_at` | timestamptz | `now()` |
| `deleted_at` | timestamptz, null | Soft-delete; revived on re-install |

No encrypted-token column — see [Teams bridge: No per-tenant token](#no-per-tenant-token).
The endpoint
([`api/app/api/integrations_teams.py`](../api/app/api/integrations_teams.py))
just upserts the identity tuple.

### Request validation

Both `…Create` schemas
([`api/app/schemas/slack_workspace.py`](../api/app/schemas/slack_workspace.py),
[`api/app/schemas/teams_tenant.py`](../api/app/schemas/teams_tenant.py))
set `extra="forbid"` and `min_length=1` on every field, so a malformed
bridge POST is rejected at the schema boundary. The field names match
exactly what the bridges produce from the provider responses — a rename
on either side breaks the bridge→api contract.

---

## Admin surface

The admin page
([`web/src/routes/lq-ai/admin/intake-bridges/+page.svelte`](../web/src/routes/lq-ai/admin/intake-bridges/+page.svelte))
is backed by
[`api/app/api/admin_intake_bridges.py`](../api/app/api/admin_intake_bridges.py)
(M3-D4). It is a management *shell*, not a feature surface.

### API

- **`GET /api/v1/admin/intake-bridges`** — returns a section-split
  response (`{slack_workspaces: [...], teams_tenants: [...]}`,
  [`api/app/schemas/intake_bridges.py`](../api/app/schemas/intake_bridges.py)).
  Live rows only (`deleted_at IS NULL`), sorted `installed_at DESC`
  within each section. The summary shapes deliberately **omit** the bot
  token / any secret — they carry only the id, natural key, display
  name, installer id, and install timestamp.
- **`DELETE /api/v1/admin/intake-bridges/slack/{workspace_id}`** and
  **`/teams/{tenant_id}`** — **soft-delete** (set `deleted_at = now()`),
  →204. A 404 (`NotFound`) is returned if the row is missing or already
  soft-deleted. The row stays in the DB so a re-install via the bridge
  OAuth flow revives it in place — install history is preserved rather
  than lost.

### Auth posture

The list/delete handlers stack on `ActiveUser` (bearer + must-change-
password gate, mounted at the router level) **plus** the `AdminUser`
dependency at handler level. A non-admin authenticated user gets 403
with `code="forbidden"`. This is distinct from the
`require_bridge_auth` service-to-service posture on the
*persistence* endpoints — the admin surface is operated by a human admin
with a JWT; the persistence surface is called by a bridge with the
shared bearer.

### What's visible-but-disabled (DE-288 hooks)

The page surfaces the install + uninstall surface and a "Linked users"
column, but several elements are deliberately inert at v0.3.0:

- **Quick-ask skill picker** — a disabled `<select>` per row with a
  tooltip pointing at DE-288. No API backs it; there's nothing to
  configure until the slash-command surface exists.
- **Linked users** — renders `— (DE-288)`; per-user Slack/Teams ↔ LQ.AI
  identity mapping is DE-288 work.
- **Recent `/lq` invocations** — an empty audit-log shell with copy
  pointing at DE-288.
- **Install buttons** — open the bridge's `/…/oauth/install` URL in a
  new tab. The page takes the bridge public URL as a free-text hint
  (the real value is whatever the operator configured as
  `LQ_AI_BRIDGE_PUBLIC_URL` / `LQ_AI_TEAMS_BRIDGE_PUBLIC_URL`); it does
  not read deployment config.

These are surfaced now so the admin UI doesn't churn when DE-288 lands.

---

## Security / threat model

The Inference Gateway is LQ.AI's security boundary — the one component
holding privileged provider keys. The intake bridges are a different
kind of boundary: **external trust boundaries** that accept inbound
traffic from Slack / Microsoft and hold (for Slack) a bot credential
that can impersonate the bot in the operator's workspace. The design
treats them accordingly.

### Bridge → api authentication

Every bridge→api POST carries `LQ_AI_BRIDGE_TOKEN` as a bearer. The api
matches it **constant-time** (`secrets.compare_digest`) via the shared
`require_bridge_auth` dependency
([`api/app/api/dependencies.py`](../api/app/api/dependencies.py)). Two
fail-safes:

- If `LQ_AI_BRIDGE_TOKEN` is **unset** on the api, the dependency raises
  500 and refuses all bridge traffic — accepting bridge POSTs with no
  enforced secret would silently break the trust contract (it never
  "runs open"). M3-E1 confirmed wrong-token → 401.
- The token must differ from any user-facing token; it is
  service-to-service only, never a user JWT.

### At-rest secret encryption

Slack bot tokens are encrypted at rest with Fernet (authenticated
encryption) under `LQ_AI_BRIDGE_MASTER_KEY`
([`api/app/security/encryption.py`](../api/app/security/encryption.py),
`BridgeTokenEncryptor`). The key is:

- **Distinct from the gateway's master key.** Bot tokens
  (bot-impersonation blast radius) and provider keys (inference-routing
  blast radius) are different threat models; sharing a key would couple
  the two blast radii. This mirrors the gateway's ADR-0011 Fernet
  pattern without sharing key material.
- **Never persisted by the encryptor.** Read from the environment at
  construction, held in memory only.
- A wrong key and a tampered ciphertext are indistinguishable by Fernet
  design (AEAD rejects both identically) — surfaced as
  `BridgeEncryptionError`.

M3-E1 confirmed the persisted `bot_token_encrypted` is Fernet ciphertext,
not plaintext. Teams has no at-rest secret to protect.

### Identity claims grant no authority

The Teams `id_token` is decoded **without** signature verification — but
no LQ.AI permission is granted on the basis of those claims. The `tid` /
`oid` are identity/audit fields only; `installer_slack_user_id` and
`installer_oid` are explicitly audit-only and grant nothing. The decode
is safe because the token arrived over TLS via the bridge's
`client_secret`-authenticated POST to Microsoft's token endpoint.

### Inbound webhook signatures

The Slack `/slack/events` endpoint verifies the HMAC signature on every
request before any handling, with a 5-minute replay window. This
prevents an attacker from POSTing fake events and getting an observable
response — even though the handler is otherwise a no-op at v0.3.0.

### Permission narrowness

The bot requests only the scopes it needs (`commands`, `chat:write` for
Slack; `User.Read` + identity scopes for Teams). It cannot read silent
channels. Confidentiality of forwarded thread content is a DE-288
concern (PRD §3.15 requires thread contents to be stored under the
user's chat history with normal RBAC) — but since no thread is forwarded
at v0.3.0, that path does not yet exist.

### The unverified-OAuth caveat is a security caveat too

Because the real OAuth round-trip has never run against a public tunnel
([DE-312](#references)), the bridge's behavior under a genuine
provider callback — `state` round-trip, redirect-URI matching,
token-exchange error handling against the live endpoints — is verified
only by unit tests and isolated POST simulation, not by an end-to-end
install. Treat the OAuth surface as "implemented and unit-tested" rather
than "proven against the live providers" until DE-312 closes.

---

## Configuration

Both bridge services load config from env via `pydantic-settings`. All
fields are required **except** the OTel exporter URL (opt-in per PRD
§5.7) and the log level.

### Slack bridge env

| Env var | Required | Purpose |
|---|---|---|
| `SLACK_CLIENT_ID` | yes | OAuth client id (Slack App admin UI) |
| `SLACK_CLIENT_SECRET` | yes | OAuth client secret |
| `SLACK_SIGNING_SECRET` | yes | Inbound webhook signature verification |
| `LQ_AI_BACKEND_URL` | yes | api base URL inside the network (e.g. `http://api:8000`) |
| `LQ_AI_BRIDGE_TOKEN` | yes | Shared bearer the bridge presents to the api |
| `LQ_AI_BRIDGE_PUBLIC_URL` | yes | Public base URL of the bridge — builds the OAuth `redirect_uri` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | OTel exporter (opt-in) |
| `OTEL_SERVICE_NAME` | no | Defaults to `lq-ai-slack-bridge` |
| `LQ_AI_BRIDGE_LOG_LEVEL` | no | Defaults to `INFO` |

### Teams bridge env

| Env var | Required | Purpose |
|---|---|---|
| `MICROSOFT_APP_ID` | yes | Azure AD multi-tenant app client_id |
| `MICROSOFT_APP_PASSWORD` | yes | Azure AD app client secret |
| `LQ_AI_BACKEND_URL` | yes | api base URL inside the network |
| `LQ_AI_BRIDGE_TOKEN` | yes | **Reused** from slack-bridge (same shared bearer, M3-D3 decision #2) |
| `LQ_AI_TEAMS_BRIDGE_PUBLIC_URL` | yes | Public base URL of the teams-bridge |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | OTel exporter (opt-in) |
| `OTEL_SERVICE_NAME` | no | Defaults to `lq-ai-teams-bridge` |
| `LQ_AI_TEAMS_BRIDGE_LOG_LEVEL` | no | Defaults to `INFO` |

### api-side env

The api reads `LQ_AI_BRIDGE_TOKEN` (to match bridge POSTs) and
`LQ_AI_BRIDGE_MASTER_KEY` (to encrypt Slack bot tokens). Both are
declared with the soft-default `${VAR:-}` form on the `api` service in
`docker-compose.yml`, so an operator who never uses the bridges leaves
them unset and the api refuses bridge traffic with 500.

### Compose profiles

The services are gated by the `slack` and `teams` profiles:

```bash
docker compose --profile slack up -d slack-bridge
docker compose --profile teams up -d teams-bridge
```

The slack-bridge binds `127.0.0.1:8002`, the teams-bridge
`127.0.0.1:8003` by default (overridable via `*_BRIDGE_BIND_ADDR` /
`*_BRIDGE_HOST_PORT`); operators typically front both with a reverse
proxy. Neither service runs migrations or holds external storage — they
are stateless HTTP services. See `.env.example` (~L295–361) and
`docker-compose.yml` (the `slack-bridge` / `teams-bridge` blocks) for
the full surface.

---

## Known limitations

### Real OAuth end-to-end has never been exercised (DE-312, P1)

This is the headline limitation. The install + real OAuth callback +
identity-binding flow has **never** run against a real public-URL
tunnel. No ngrok / cloudflared tunnel was stood up during M3-D1 / M3-D3
development; no `LQ_AI_BRIDGE_PUBLIC_URL` appears in any `.env`, and no
commit or handoff references a tunnel. M3-E1 verified the full plumbing
path *in isolation* (service health, bridge-bearer auth, at-rest
encryption, admin surfacing, soft-delete) but not a genuine OAuth
round-trip. The bridges' status is **"plumbing shipped, real-OAuth
integration unverified."** [DE-312](#references) (P1) tracks standing up
a tunnel, configuring the Slack App + Azure AD redirect URIs to match,
and completing a real round-trip per bridge — including confirming the
rows surface in the admin UI from a *genuine* install and the Teams
Graph display-name lookup resolves (or falls back). This must close
before any milestone delivering the slash-command surface (DE-288) and
before any claim that the bridges are end-to-end functional.

### No `/lq` slash-command surface (DE-288)

The bridges are installable and OAuth-bound but otherwise **inert**.
There is no `/lq` slash command, no `/lq ask` quick-skill flow, no
per-user Slack/Teams ↔ LQ.AI identity mapping, no in-thread reply, and
no thread-forwarding into chat history. The admin UI carries
visible-but-disabled hooks (quick-ask skill picker, linked-users column,
`/lq` audit-log shell). [DE-288](#references) (P2) tracks the
slash-command surface for M4 / community contribution — the Slack flow
can ship as a standalone PR with Teams parity as a follow-up.

### Compose env interpolation breaks all Compose commands when unset (DE-305)

The `slack-bridge` and `teams-bridge` service definitions in
`docker-compose.yml` use the **required-error** `${VAR:?msg}`
interpolation form for the bridge env vars. Docker Compose interpolates
**every** service definition at parse time regardless of the active
`--profile`, so *any* `docker compose` command (`up`, `down`, `config`,
`ps`) fails with `"required variable … is missing a value"` for an
operator who hasn't set the bridge vars — **even one who never enables
the `slack` / `teams` profiles**. This directly contradicts the
`.env.example` promise (~L298) that "operators who don't use Slack can
leave all of the variables below unset," and it undermines the
profile-gating design intent. (Note the api service's own bridge env
uses the soft `${VAR:-}` form, so the contradiction is specifically in
the bridge service blocks.) [DE-305](#references) (P2) tracks moving the
"required when the profile is active" enforcement into the bridge
container entrypoints and switching the compose interpolation to the
soft-default form.

### In-memory OAuth state tokens don't survive a bridge restart

Both bridges hold OAuth `state` tokens in an in-memory store with a
10-minute TTL. A bridge restart between install initiation and callback
invalidates the in-flight install; the operator restarts it. Acceptable
for a single-instance bridge; the OAuth module flags persisting state
api-side as a DE candidate (not yet filed formally).

### Display name / workspace name can go stale

`team_name` / `tenant_name` are snapshotted at install time and **not**
auto-refreshed if the operator renames the workspace / tenant on the
provider side. A re-install refreshes them. The Teams display name is
best-effort (falls back to the raw `tid` on any Graph failure), so a
tenant row may surface with a GUID as its display name.

---

## References

- PRD §3.15 (Slack / Teams Light Intake Bridge) — the capability spec
  this doc implements: [docs/PRD.md](PRD.md)
- PRD §9 [DE-288](PRD.md#de-288--slackteams-lq-slash-command--quick-skill-flow--deferred-to-m4--community-contribution)
  — `/lq` slash-command + quick-skill flow, deferred to M4 / community
- PRD §9 [DE-305](PRD.md#de-305--bridge-env-vars-use-var-and-break-all-compose-commands-when-unset-m3-e1-finding-f1)
  — bridge env `${VAR:?}` breaks all Compose commands when unset
- PRD §9 [DE-312](PRD.md#de-312--slack--teams-bridge-oauth-end-to-end-tunnel-verification-m3-e1-finding)
  — Slack + Teams bridge OAuth end-to-end tunnel verification (P1)
- Slack bridge service: [slack-bridge/app/main.py](../slack-bridge/app/main.py),
  [slack-bridge/app/oauth.py](../slack-bridge/app/oauth.py),
  [slack-bridge/app/signing.py](../slack-bridge/app/signing.py),
  [slack-bridge/app/config.py](../slack-bridge/app/config.py),
  [slack-bridge/manifest.yml](../slack-bridge/manifest.yml),
  [slack-bridge/Dockerfile](../slack-bridge/Dockerfile),
  [slack-bridge/README.md](../slack-bridge/README.md)
- Teams bridge service: [teams-bridge/app/main.py](../teams-bridge/app/main.py),
  [teams-bridge/app/oauth.py](../teams-bridge/app/oauth.py),
  [teams-bridge/app/config.py](../teams-bridge/app/config.py),
  [teams-bridge/manifest.json](../teams-bridge/manifest.json),
  [teams-bridge/Dockerfile](../teams-bridge/Dockerfile),
  [teams-bridge/README.md](../teams-bridge/README.md)
- api persistence + admin surface:
  [api/app/api/integrations_slack.py](../api/app/api/integrations_slack.py),
  [api/app/api/integrations_teams.py](../api/app/api/integrations_teams.py),
  [api/app/api/admin_intake_bridges.py](../api/app/api/admin_intake_bridges.py),
  [api/app/api/dependencies.py](../api/app/api/dependencies.py) (`require_bridge_auth`)
- at-rest encryption:
  [api/app/security/encryption.py](../api/app/security/encryption.py) (`BridgeTokenEncryptor`)
- models / schemas / migrations:
  [api/app/models/slack_workspace.py](../api/app/models/slack_workspace.py),
  [api/app/models/teams_tenant.py](../api/app/models/teams_tenant.py),
  [api/app/schemas/slack_workspace.py](../api/app/schemas/slack_workspace.py),
  [api/app/schemas/teams_tenant.py](../api/app/schemas/teams_tenant.py),
  [api/app/schemas/intake_bridges.py](../api/app/schemas/intake_bridges.py),
  [api/alembic/versions/0037_slack_workspaces.py](../api/alembic/versions/0037_slack_workspaces.py),
  [api/alembic/versions/0038_teams_tenants.py](../api/alembic/versions/0038_teams_tenants.py)
- admin UI:
  [web/src/routes/lq-ai/admin/intake-bridges/+page.svelte](../web/src/routes/lq-ai/admin/intake-bridges/+page.svelte)
- operator config: [.env.example](../.env.example) (~L295–361),
  [docker-compose.yml](../docker-compose.yml) (`slack-bridge` / `teams-bridge` blocks)
