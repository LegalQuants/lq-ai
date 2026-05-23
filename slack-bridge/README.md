# LQ.AI Slack Bridge (M3-D1)

The Slack bridge is a small standalone service that mediates between Slack's
OAuth / Events APIs and the LQ.AI backend. It ships with the M3 release as
**plumbing-only**: the `/lq` slash command surface (M3-D2) is descoped to M4 /
community contribution per [PRD §9 DE-288](../docs/PRD.md#de-288--slackteams-lq-slash-command--quick-skill-flow--deferred-to-m4--community-contribution).

## What it does today (v0.3.0)

- Hosts the OAuth install flow at `/slack/oauth/install` → Slack consent →
  `/slack/oauth/callback` → workspace persistence in the LQ.AI api.
- Verifies inbound Slack request signatures (`X-Slack-Signature` /
  `X-Slack-Request-Timestamp`) on every webhook so M3-D2's slash-command
  handler lands on a verified substrate.
- Health surface: `/healthz` (liveness) + `/readyz` (readiness — checks the
  LQ.AI api is reachable on the configured `LQ_AI_BACKEND_URL`).

## What it does NOT do today

- **Slash commands** — `/lq` and `/lq ask`, per DE-288, are deferred.
- **Inbound message handling** — the bot does not read silent channels; it
  only acts on user-invoked commands (when those land in M3-D2 / community).
- **Per-user identity binding** — Slack user ↔ LQ.AI user mapping is in
  M3-D4's admin UI scope. The bridge persists the workspace record; the
  admin UI binds Slack identities to LQ.AI accounts.

## Configuration

| Env var | Required | Purpose |
|---|---|---|
| `SLACK_CLIENT_ID` | yes | OAuth client id (from Slack App admin UI) |
| `SLACK_CLIENT_SECRET` | yes | OAuth client secret |
| `SLACK_SIGNING_SECRET` | yes | Inbound webhook signature verification |
| `LQ_AI_BACKEND_URL` | yes | Base URL of the lq-ai api (e.g. `http://api:8000`) |
| `LQ_AI_BRIDGE_TOKEN` | yes | Shared secret the bridge sends on internal calls to the api |
| `LQ_AI_BRIDGE_PUBLIC_URL` | yes | Public base URL of the bridge — used to build the OAuth `redirect_uri` Slack calls back to (e.g. `https://lqai.example.com/slack`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | OpenTelemetry exporter — opt-in per PRD §5.7 |
| `OTEL_SERVICE_NAME` | no | Defaults to `lq-ai-slack-bridge` |
| `LQ_AI_BRIDGE_LOG_LEVEL` | no | Defaults to `INFO` |

## Running locally

```bash
docker compose --profile slack up -d slack-bridge
```

The slack-bridge service ships behind the `slack` Compose profile so operators
who do not use Slack don't pay the SBOM cost. See `docker-compose.yml` for the
service definition.

## Slack App configuration

`manifest.yml` in this directory is the Slack App manifest. Operators install
their own Slack App (via the [Slack App Manifest UI](https://api.slack.com/reference/manifests))
and supply the resulting OAuth credentials via the env vars above.

The manifest declares only the scopes the bridge needs today:
- `commands` — for the future M3-D2 slash-command surface.
- `chat:write` — so the bot can post replies in channels it is invited to.

No `channels:read`, no `groups:read`, no `im:read` — the bot does **not** read
silent channels. It only acts on explicit user-invoked commands.

## Security posture

- Bot tokens never persist in the bridge. They are POSTed to the LQ.AI api
  on receipt and encrypted there (per the existing secret-management
  conventions for provider keys).
- The OAuth state token is held in-memory in the bridge with a 10-minute
  TTL. A bridge restart between install start and callback invalidates the
  flow; the operator restarts the install.
- The internal call from bridge → api carries `LQ_AI_BRIDGE_TOKEN` as a
  Bearer header. The api verifies it against `LQ_AI_BRIDGE_TOKEN` at every
  bridge-facing endpoint. The token must be different from any user-facing
  token.

## Tests

```bash
cd slack-bridge
.venv/bin/pytest tests/ -q
```
