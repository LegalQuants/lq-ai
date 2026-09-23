# Rotate a leaked provider key

A provider API key leaked — committed to a public repo, pasted somewhere it shouldn't have been, or only suspected of exposure. This page assumes the key itself, not the gateway's master key, is what's compromised; if you suspect the `LQ_AI_GATEWAY_MASTER_KEY` itself was exposed, that's the [master-key rotation](../security/encrypted-keys.md#master-key-rotation) procedure instead — a bigger job, covered in full there. Tool-provider (research-source) credentials are encrypted under the same master key, so a master-key rotation invalidates their tokens too — re-encrypt each `tool_providers[].api_key_encrypted` entry the same way; the linked procedure doesn't yet walk through that step explicitly, so budget the extra loop yourself.

## 1. Revoke at the upstream provider — first, before anything else here

Log into the provider (Anthropic, OpenAI, Azure, whichever leaked) and revoke that key immediately. Nothing in LQ.AI can stop a leaked key from being used elsewhere until the provider itself invalidates it — every step below is about your own deployment, not the key's validity on the provider's side. [`docs/security/encrypted-keys.md`](../security/encrypted-keys.md#what-if-i-lose-the-master-key) states the same instinct for the master-key-lost case: "treat the old plaintext keys as compromised" and re-issue at the source first.

## 2. Revoke it in the gateway, then replace it

Generate a fresh key from the provider, then get it into `gateway.yaml`:

- **If `LQ_AI_GATEWAY_MASTER_KEY` is set** — use the runtime admin surface: **Admin → Provider keys**. The runtime provider-key API is `DELETE`-to-revoke, `PATCH`-to-rotate ([`docs/HONEST-STATE.md`](../HONEST-STATE.md) §2) — revoking first takes the compromised key out of the live adapter immediately if you want that gap even before the replacement is ready, or set the new key directly (`PATCH`) to do both in one move. Either action is Fernet-encrypted into `gateway.yaml` and **hot-applied to the live adapter with no restart** — the same path the day-to-day BYOK flow uses (see [`docs/INSTALL-MAC.md`](../INSTALL-MAC.md#5-provider-keys-byok)). This is the fastest path and the one to use at 11pm — from the command line, with an admin bearer token:

  ```bash
  # revoke the compromised key immediately
  curl -X DELETE http://localhost:8000/api/v1/admin/provider-keys/<provider> \
    -H "Authorization: Bearer <admin-jwt>"

  # confirm the gateway's view of the key (also step 2's own confirmation, below)
  curl -s http://localhost:8000/api/v1/admin/provider-keys \
    -H "Authorization: Bearer <admin-jwt>" \
    | jq '.provider_keys[] | {provider, configured, last4, source}'
  ```
- **If the provider still uses `api_key_env`** (plaintext env-var form), update the value in your secrets store and recreate the gateway container so it picks up the new environment.
- **If you manage `api_key_encrypted` by hand**, re-run `python -m app.cli encrypt-key --provider <name>` under the existing master key (it prompts for the key, or reads it from stdin — don't pass it as a command argument) and paste the new token into `gateway.yaml`. A provider entry takes `api_key_env` *or* `api_key_encrypted`, never both — the config loader rejects the entry otherwise — so drop `api_key_env` if you are converting one. Then recreate the gateway container: a [config hot-reload](../adr/0010-gateway-config-hot-reload.md) (SIGHUP) re-reads `gateway.yaml` but does not rebuild provider adapters — only gateway startup and the runtime provider-key endpoints do — so a hand-pasted token takes effect on the next gateway start, not on reload.

Either way, confirm the swap took with the provider-key status list — `GET /api/v1/admin/provider-keys` with an admin token (the `curl` above), or **Admin → Provider keys**. Each row is `{provider, type, configured, last4, source}`: the rotated provider should show `configured: true`, a `last4` matching the new key, and `source: runtime` if you used the runtime surface (a runtime set or rotate writes `api_key_encrypted` and clears `api_key_env`, so an env-sourced provider flips to `runtime`). Be clear about what that proves: `configured` means the gateway built an adapter from a key it could resolve — presence, not provider acceptance. The gateway's `GET /admin/v1/providers/health` is a `501` stub as of the checked commit, so there is no health probe that exercises the key upstream; the only check of acceptance is a real request — send one message routed to that provider and confirm it isn't refused with a provider authentication error.

## 3. Find the blast radius — one query

Every routed request is a row in `inference_routing_log`, keyed by `routed_provider`. Cross-referencing `audit_log` on `request_id` tells you whether any of that traffic touched a privileged matter:

```sql
SELECT l.timestamp, l.user_id, l.chat_id, l.routed_model,
       l.tokens_in, l.tokens_out, l.anonymization_applied,
       a.privilege_marked, a.privilege_basis
FROM inference_routing_log l
LEFT JOIN audit_log a ON a.request_id = l.request_id
WHERE l.routed_provider = '<compromised-provider-name>'
  AND l.timestamp >= '<when the key was first exposed>'
ORDER BY l.timestamp DESC;
```

This is a read against your own deployment's audit trail — it tells you what *your* gateway sent through the compromised key, not what happened to it afterward on the provider's side (a leaked key used by someone else, on their own account, leaves no trace here). `anonymization_applied` on each row tells you whether pseudonymization was active for that request; `privilege_marked` flags rows tied to a project you marked privileged. Both columns are documented in full at [Audit and evidence](../security/audit-logging.md).

> [!NOTE]
> **Professional duty** — If the query above shows privileged-matter traffic routed through the compromised key before you revoked it, whether that triggers a client-notification obligation is a question this page cannot answer for you — it depends on your jurisdiction's rules on confidentiality and security-incident notification, and on what "compromised" actually means here (a leaked key is not the same exposure as a confirmed third-party read of the traffic). Treat the query's output as the fact pattern you bring to that judgment, not as the judgment itself.

## 4. Confirm

Record the moment step 2 completed as a UTC timestamp (`inference_routing_log.timestamp` is `TIMESTAMPTZ`), and re-run the blast-radius query with `AND l.timestamp >= '<rotation time, UTC>'` in place of the exposure-time filter — a fixed value, not `now()`, which advances on every run and hides exactly the window you are trying to inspect. Read the result carefully: rows after the rotation are *not* evidence the old key is still in use. `routed_provider` is the provider's config name, which does not change on rotation, and no routing-log column records which key served a request — so post-rotation rows are simply new traffic through the replacement key, and the log cannot tell the two apart. What the log does bound is your own exposure: the window from first exposure to rotation in the step 3 query. Whether the *old* key is still being used anywhere is only visible on the provider's side — its per-key usage or activity view — so watch that for any activity you didn't originate, for as long as your provider's exposure window suggests is prudent.
