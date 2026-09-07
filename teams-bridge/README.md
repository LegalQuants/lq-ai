# LQ.AI Teams Bridge (M3-D3)

The Teams bridge is a small standalone service that mediates between
Microsoft identity platform / Bot Framework and the LQ.AI backend. It
ships with the M3 release as **plumbing-only**: the `/lq` slash-command
surface (M3-D2's Teams parity) is descoped to M4 / community
contribution per [PRD §9 DE-288](../docs/PRD.md#de-288--slackteams-lq-slash-command--quick-skill-flow--deferred-to-m4--community-contribution).

## What it does today

- Hosts the OAuth admin-consent flow at `/teams/oauth/install` →
  Microsoft identity platform → `/teams/oauth/callback` → tenant
  persistence in the LQ.AI api.
- Multi-tenant Azure AD app posture per [M3-D3 decision #4](../docs/M3-IMPLEMENTATION-PLAN.md#task-m3-d3--teams-bridge-service--teams-oauth--lq-flows)
  — one Azure AD app registration can host installs from any
  Microsoft 365 tenant.
- **`/lq` command surface** (DE-288) at `POST /teams/messages` — the
  Bot Framework messaging endpoint (point the Azure Bot resource at
  `{LQ_AI_TEAMS_BRIDGE_PUBLIC_URL}/teams/messages`). ActivityHandler-
  shaped dispatch: `message` activities containing `/lq …` (mention
  stripped) parse into `help` / `ask "<question>"`; `conversationUpdate`
  posts a welcome/usage message. `/lq ask` resolves the invoker's email
  from the authenticated Connector conversation-member record, calls the
  api's bridge-bearer quick-ask endpoint (which maps email → LQ.AI
  account, fail-closed), and delivers ONE reply activity with the answer
  + chat link. Unlinked users get a refusal, never an answer.
- Health surface: `/healthz` (liveness) + `/readyz` (readiness —
  checks the LQ.AI api is reachable on the configured
  `LQ_AI_BACKEND_URL`).

## What it does NOT do today

- **Inbound Connector JWT validation** — the seven-point Bot Connector
  JWT validation requires a JWT library; the PyJWT-vs-`botbuilder-core`
  dependency choice is an open maintainer fork (DE-288 research memo
  §4) and this bridge does not add a dependency unilaterally. Interim
  posture (documented in `app/commands.py`): bearer-presence check +
  strict `serviceUrl` host allowlist (`*.botframework.com` /
  `*.trafficmanager.net`) + identity always derived from our own
  authenticated Connector member-info call and re-checked by the api's
  fail-closed email → account mapping. **Restrict network ingress to
  this bridge**; full JWT validation is the highest-priority follow-up
  and lands via the security-review path.
- **Per-user Microsoft Graph access** — the on-behalf-of flow for
  per-user Graph queries is M4 scope (`/lq` reading mail/files on the
  invoker's behalf).
- **Per-tenant bot token encryption** — Teams uses operator-supplied
  APP-LEVEL bot credentials (one `MICROSOFT_APP_ID` +
  `MICROSOFT_APP_PASSWORD` per deployment) not per-tenant tokens, so
  there's nothing per-tenant to encrypt. Contrast `slack-bridge`
  which stores `bot_token_encrypted` per workspace.

## Configuration

| Env var | Required | Purpose |
|---|---|---|
| `MICROSOFT_APP_ID` | yes | Azure AD multi-tenant app client_id (from Azure AD admin) |
| `MICROSOFT_APP_PASSWORD` | yes | Azure AD app client secret |
| `LQ_AI_BACKEND_URL` | yes | Base URL of the lq-ai api (e.g. `http://api:8000`) |
| `LQ_AI_BRIDGE_TOKEN` | yes | **Reused** from slack-bridge per M3-D3 decision #2 — same shared secret authenticates both bridges to the api |
| `LQ_AI_TEAMS_BRIDGE_PUBLIC_URL` | yes | Public base URL of the teams-bridge — used to build the OAuth `redirect_uri` Microsoft calls back to (e.g. `https://lqai.example.com/teams`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | OpenTelemetry exporter — opt-in per PRD §5.7 |
| `OTEL_SERVICE_NAME` | no | Defaults to `lq-ai-teams-bridge` |
| `LQ_AI_TEAMS_BRIDGE_LOG_LEVEL` | no | Defaults to `INFO` |

## Running locally

```bash
docker compose --profile teams up -d teams-bridge
```

The teams-bridge service ships behind the `teams` Compose profile so
operators who do not use Teams don't pay the SBOM cost. See
`docker-compose.yml` for the service definition.

## Setting up the Azure AD multi-tenant app

1. In Azure Portal → Azure Active Directory → App registrations → New
   registration:
   - Name: LQ.AI
   - Supported account types: "Accounts in any organizational
     directory (Any Azure AD directory — Multitenant)"
   - Redirect URI (Web): `${LQ_AI_TEAMS_BRIDGE_PUBLIC_URL}/teams/oauth/callback`
2. Copy the Application (client) ID → `MICROSOFT_APP_ID`.
3. Certificates & secrets → New client secret → copy value →
   `MICROSOFT_APP_PASSWORD`.
4. API permissions → Microsoft Graph → Delegated → `User.Read` +
   `offline_access` (already on by default). Grant admin consent for
   your own tenant.
5. Expose an API (optional, only if the bot needs SSO into the task
   pane — M4 scope).

## Teams app manifest

The Teams app manifest at `teams-bridge/manifest.json` declares the
Teams app metadata, valid domains, and bot id. Operators upload the
manifest to their tenant's Teams Admin Center → Manage apps → Upload.

The bot id in the manifest must match `MICROSOFT_APP_ID`. The
manifest is templated with `${MICROSOFT_APP_ID}` placeholders the
operator substitutes before uploading.
