# Explicit Slack account linking

This increment links a verified `(team_id, Slack user_id)` to the active LQ.AI
user who explicitly confirms it. PR #415 stays parked. Quick-ask inference,
thread forwarding (#342), profile lookup and Teams parity are separate work.

## Configure and try

1. Apply migration `0080` through the normal deployment process.
2. Set a fresh random `LQ_AI_SLACK_COMMAND_TOKEN` on both `api` and
   `slack-bridge`. Use a different value from the installation credential
   `LQ_AI_BRIDGE_TOKEN`. The new credential can issue association links only.
3. Set `LQ_AI_WEB_PUBLIC_URL` on the API to the public HTTPS web origin.
   Local testing accepts `http://localhost:3000` or `http://127.0.0.1:3000`.
   Keep the existing OAuth credentials, signing secret and installation token.
4. Replace the bridge URL placeholder in `slack-bridge/manifest.yml`, then
   configure `/lq` with the HTTPS request URL ending `/slack/commands`.
   This product route uses signed HTTP requests. Disable Socket Mode for this
   app before testing HTTP delivery. The earlier Socket Mode smoke responder
   does not serve this flow. No additional scopes are needed for linking.
5. Complete the existing workspace OAuth installation into this deployment.
   Type `/lq help` in Slack. Only the invoker sees the returned link.
6. Open the link, sign in normally, check the workspace, Slack user ID and
   LQ.AI account shown, then click **Confirm account link**. Opening or previewing
   the page alone never links an account.
7. Under **Settings → Account → Linked Slack accounts**, click **Unlink** to
   revoke the mapping and any outstanding links for that Slack identity.

The confirmation URL expires in ten minutes. A new `/lq help` link replaces the
previous pending link. A Slack identity already linked to another account cannot
be transferred by possession of a fresh URL. Its owner must unlink it first.
Workspace disconnection revokes all its links and pending challenges atomically.
Reinstalling a disconnected workspace requires fresh user linking.

## Security contract

- The bridge verifies HMAC over the exact raw body and checks the five-minute
  timestamp window before parsing the bounded slash-command form. It forwards
  only platform IDs. Duplicate form fields are refused.
- The API accepts issuance only through the scoped service credential. All
  preview, confirmation, listing and unlinking handlers require an active user
  session, including normal password-rotation and mandatory-MFA gates.
- The user never supplies an LQ.AI actor ID. Email matching, `users.info`, profile
  scopes, arbitrary response-URL posting and inference are absent.
- The 256-bit capability is stored as SHA-256, expires after ten minutes, and is
  deleted on confirmation. A database uniqueness constraint prevents rebinding.
- URLs carry the capability in a fragment. The browser removes the fragment,
  retains it only in tab-scoped session storage through login, and clears it on
  success, cancellation or invalid preview. Login resumes a fixed internal route.
  Request bodies contain the token only for authenticated preview/confirmation.
  Link responses use `Cache-Control: no-store`. Validation errors do not echo input.
  Operators must keep request/response body capture disabled in proxies and tracing.
- Issuance, confirmation, unlink and disconnect serialize on the workspace row.
  Mutation and audit commit together. Audits contain IDs and action metadata,
  never association tokens, bot secrets, prompts or response URLs.
- Personal-data exports include only the owner’s linked Slack account metadata.
  Hard account deletion removes mappings through the user foreign key. Challenge
  tokens and encrypted bot credentials are excluded from exports.
- Future `/lq ask` admission must resolve the live mapping and current install,
  apply backend permissions, and audit admission atomically. This increment
  provides no delegated inference endpoint or authorization shortcut.

The command transport follows Slack's [signature verification contract](https://docs.slack.dev/authentication/verifying-requests-from-slack/)
and [slash-command response contract](https://docs.slack.dev/interactivity/implementing-slash-commands/).
The backend call has a two-second timeout so the bridge can return a private
failure within Slack's three-second response window under normal network conditions.

## Acceptance checks

Run API tests against a disposable pgvector PostgreSQL instance only.

```sh
cd api
uv sync --frozen --extra dev
DATABASE_URL=postgresql+asyncpg://... uv run pytest tests/test_slack_account_linking.py tests/test_integrations_slack.py tests/test_admin_intake_bridges.py tests/test_openapi.py tests/test_openapi_export.py
```

These verify hash-only storage, non-mutating preview, explicit confirmation,
single-use and expiry, pending-link replacement, ownership and workspace
isolation, credential scope, password/MFA gates, input redaction, disconnect
revocation, audit rollback and concurrent redemption using separate connections.

```sh
cd slack-bridge
python -m pip install '.[dev]'
ruff check app tests
ruff format --check app tests
mypy app --strict
pytest -q
```

Bridge tests cover valid/unsigned/stale/tampered/ambiguous requests, private
responses, only platform IDs reaching the API, and safe failures with no profile,
response-URL or inference call.

```sh
cd web
npm ci
npm run check:lq-ai
# Start the normal web dev server separately.
npx cypress run --spec cypress/e2e/lq-ai-slack-account-linking.cy.ts
```

Browser tests use intercepted API contracts. They cover preview without linking,
explicit confirmation, sign-in resumption, cancellation, expiry, conflict and
unlinking. They join the deterministic CI inventory. A real OAuth install plus
signed HTTP `/lq help` against a live Slack workspace remains a separate manual
acceptance check. The Socket Mode smoke test does not establish that result.
