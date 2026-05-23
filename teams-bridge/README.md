# LQ.AI Teams Bridge (M3-D3)

The Teams bridge is a small standalone service that mediates between
Microsoft identity platform / Bot Framework and the LQ.AI backend. It
ships with the M3 release as **plumbing-only**: the `/lq` slash-command
surface (M3-D2's Teams parity) is descoped to M4 / community
contribution per [PRD §9 DE-288](../docs/PRD.md#de-288--slackteams-lq-slash-command--quick-skill-flow--deferred-to-m4--community-contribution).

## What it does today (v0.3.0)

- Hosts the OAuth admin-consent flow at `/teams/oauth/install` →
  Microsoft identity platform → `/teams/oauth/callback` → tenant
  persistence in the LQ.AI api.
- Multi-tenant Azure AD app posture per [M3-D3 decision #4](../docs/M3-IMPLEMENTATION-PLAN.md#task-m3-d3--teams-bridge-service--teams-oauth--lq-flows)
  — one Azure AD app registration can host installs from any
  Microsoft 365 tenant.
- Health surface: `/healthz` (liveness) + `/readyz` (readiness —
  checks the LQ.AI api is reachable on the configured
  `LQ_AI_BACKEND_URL`).

## What it does NOT do today

- **Slash commands** — `/lq` and `/lq ask` Teams parity, per DE-288,
  are deferred.
- **Bot framework message handling** — the bot does not respond to
  channel messages; it only completes the OAuth install flow.
- **Per-user Microsoft Graph access** — the on-behalf-of flow for
  per-user Graph queries is M4 scope (when the slash-command surface
  lands and `/lq` needs to read mail/files on the invoker's behalf).
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
