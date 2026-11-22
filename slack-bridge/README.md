# LQ.AI Slack Bridge (M3-D1)

Account linking is documented in [the linking guide](../docs/slack-account-linking.md).
`/lq help` now returns a private association link. `/lq ask` remains unavailable.

The Slack bridge mediates OAuth installation and signed commands between Slack
and the LQ.AI backend. The current command surface is `/lq help`, which returns
a private account-link URL. The API owns the identity mapping and auditing.

## What it does today

- Hosts `/slack/oauth/install` and `/slack/oauth/callback` and persists the
  encrypted workspace installation in the API.
- Verifies Slack signatures and timestamp freshness over raw request bodies.
- Handles `/slack/commands` for `/lq help`, forwarding only the verified
  workspace and user IDs through a scoped backend credential.
- Supports explicit signed-in confirmation and unlinking in the web app.
- Provides `/healthz` and `/readyz`.

Quick-ask inference, thread forwarding, profile lookup and Teams account-linking
parity remain separate work. The bridge does not read silent channels. Real
OAuth and signed HTTP linking against a live Slack workspace remain unverified.

## Configuration

| Env var | Required | Purpose |
|---|---|---|
| `SLACK_CLIENT_ID` | yes | OAuth client id (from Slack App admin UI) |
| `SLACK_CLIENT_SECRET` | yes | OAuth client secret |
| `SLACK_SIGNING_SECRET` | yes | Inbound webhook signature verification |
| `LQ_AI_BACKEND_URL` | yes | Base URL of the lq-ai api (e.g. `http://api:8000`) |
| `LQ_AI_BRIDGE_TOKEN` | yes | Shared secret the bridge sends on internal calls to the api |
| `LQ_AI_SLACK_COMMAND_TOKEN` | for linking | Scoped API account-link issuance credential, separate from the installation token |
| `LQ_AI_WEB_PUBLIC_URL` | API only | Public HTTPS web origin used to generate confirmation URLs |
| `LQ_AI_BRIDGE_PUBLIC_URL` | yes | Public base URL at which the bridge's routes are reachable, **without** the `/slack` router prefix — the bridge appends `/slack/oauth/callback` itself (e.g. `https://slack-bridge.example.com`; give the bridge its own origin). `https://lqai.example.com/slack` would yield `…/slack/slack/oauth/callback`. |
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
- `commands` — for `/lq help` account linking.
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
