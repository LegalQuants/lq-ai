# Replace a leaked API key

Revoke the exposed key with its provider, add a replacement to LQ.AI, and investigate what happened while the old key was usable.

This page is for a leaked *provider* key (Anthropic, OpenAI, Azure, or another provider) — not the gateway's own master key. If you suspect `LQ_AI_GATEWAY_MASTER_KEY` itself was exposed, that's the bigger job in [If the master key was exposed or lost](#if-the-master-key-was-exposed-or-lost) below.

## Replacing a key in the app

Revoke the leaked key at the provider first, before anything else on this page — log into the provider (Anthropic, OpenAI, Azure, whichever leaked) and revoke it immediately. Nothing in LQ.AI can stop a leaked key from being used elsewhere until the provider itself invalidates it; every other step here is about your own deployment, not the key's validity on the provider's side. [`docs/security/encrypted-keys.md`](../security/encrypted-keys.md#what-if-i-lose-the-master-key) gives the same advice for the master-key-lost case — treat the old plaintext key as compromised and re-issue at the source first.

Setting or rotating a key from the provider-key screen (**Admin → Provider keys**) needs the gateway master key configured — viewing the status list, or revoking an existing runtime key, doesn't. When the master key is set, LQ.AI passes the key you submit through the API to the gateway, which Fernet-encrypts it into `gateway.yaml` and hot-applies the rebuilt adapter immediately, with no gateway restart — the same path the day-to-day [provider-keys (BYOK) flow](../INSTALL-MAC.md#5-provider-keys-byok) uses.

## Reviewing activity

Record the exact replacement time and use that fixed time in log searches. A query starting at `now()` won't find earlier activity — `now()` advances on every run and hides exactly the window you're trying to inspect. Provider-name logs alone cannot identify whether a request used the old or new key. The exact query, what it does and doesn't prove, is in [Investigate a fixed time window](#investigate-a-fixed-time-window) below.

## Finding other copies

Replacing the key through LQ.AI's admin screen doesn't remove any copy of the old key sitting elsewhere — a `.env` file next to your compose file (or, for the macOS desktop app, its own `.env` under the app's per-user application-support directory), a secrets manager, a container's environment, or a backup of the `gateway-config` volume (see [Back up and restore](backup-and-restore.md)). Revoking the old key at the provider is what makes every one of those copies unusable, wherever they are.

## Confirm the replacement path

Generate a fresh key from the provider, then get it into `gateway.yaml`:

- **If `LQ_AI_GATEWAY_MASTER_KEY` is set**, use the runtime admin surface — **Admin → Provider keys**, or its API directly. The runtime provider-key API is `DELETE`-to-revoke, `PATCH`-to-rotate ([`docs/HONEST-STATE.md`](../HONEST-STATE.md) §2): revoke first if you want the compromised key out of the live adapter even before the replacement is ready, or `PATCH` the new key directly to revoke and replace in one move. Either action is Fernet-encrypted into `gateway.yaml` and hot-applied to the live adapter with no restart. This is the fastest path — the one to use at 11pm — from the command line, with an admin bearer token:

  ```bash
  # revoke the compromised key immediately
  curl -X DELETE http://localhost:8000/api/v1/admin/provider-keys/<provider> \
    -H "Authorization: Bearer <admin-jwt>"

  # confirm the gateway's view of the key (also the confirmation step below)
  curl -s http://localhost:8000/api/v1/admin/provider-keys \
    -H "Authorization: Bearer <admin-jwt>" \
    | jq '.provider_keys[] | {provider, configured, last4, source}'
  ```
- **If the provider still uses `api_key_env`** (a plaintext environment variable), update the value in your secrets store and recreate the gateway container so it picks up the new environment.
- **If you manage `api_key_encrypted` by hand**, see [Choose one key source for each provider](#choose-one-key-source-for-each-provider) below.

Either way, confirm the swap took with the provider-key status list — the `curl` above, or **Admin → Provider keys**. Each row is `{provider, type, configured, last4, source}`: the rotated provider should show `configured: true`, a `last4` matching the new key, and `source: runtime` if you used the runtime surface (a runtime set or rotate writes `api_key_encrypted` and clears `api_key_env`, so an env-sourced provider flips to `runtime`). Be clear about what that proves: `configured` means the gateway built an adapter from a key it could resolve — presence, not provider acceptance. The gateway's `GET /admin/v1/providers/health` is a `501` stub as of the checked commit, so there is no health probe that exercises the key upstream — the only check of acceptance is a real request: send a message routed to that provider and confirm it isn't refused with a provider authentication error.

## Investigate a fixed time window

Record when the key could first have been exposed, and the moment the revocation above completed, as fixed timestamps — not `now()`.

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

Once the key is replaced, re-run the same query with `AND l.timestamp >= '<rotation time, UTC>'` in place of the exposure-time filter — a fixed value, not `now()` (`inference_routing_log.timestamp` is `TIMESTAMPTZ`, so use the UTC moment you recorded when the replacement completed). Read the result carefully: rows after the rotation are **not** evidence the old key is still in use. `routed_provider` is the provider's config name, which does not change on rotation, and no routing-log column records which key served a request — so post-rotation rows are simply new traffic through the replacement key, and the log cannot tell the two apart. What the log does bound is your own exposure: the window from first exposure to rotation, in the query above. Whether the *old* key is still being used anywhere is only visible on the provider's side — its own per-key usage or activity view — so watch that for any activity you didn't originate, for as long as your provider's exposure window suggests is prudent.

## If the master key was exposed or lost

That's a different, bigger job than the one above — [Master-key rotation](../security/encrypted-keys.md#master-key-rotation) and [What if I lose the master key?](../security/encrypted-keys.md#what-if-i-lose-the-master-key) in `docs/security/encrypted-keys.md` cover it in full. In short: changing `LQ_AI_GATEWAY_MASTER_KEY` alone leaves every existing encrypted provider key unreadable, so you have to re-encrypt each one under the new master key, replace the encrypted entries in `gateway.yaml`, and recreate the gateway with the matching environment — there is no two-master-key transition in this implementation. If the old master key is lost and no plaintext keys remain in your secrets store, you have to reissue the provider keys at their source instead. If exposure (rather than loss) is what you suspect, revoke the affected provider keys at their source the same way you would for a single leaked key.

Tool-provider (research-source) credentials are encrypted under the same master key, too — each `tool_providers[].api_key_encrypted` entry — so a master-key rotation invalidates their tokens as well. The linked procedure doesn't walk through re-encrypting those explicitly yet, so budget that extra loop yourself.

## Choose one key source for each provider

A provider entry takes `api_key_env` *or* `api_key_encrypted`, never both — the config loader rejects the entry otherwise, so drop `api_key_env` if you're converting a provider to the encrypted form.

- **`api_key_env`** (plaintext, from the process environment) — change the value in your secrets store, then recreate the gateway container. A [config hot-reload](../adr/0010-gateway-config-hot-reload.md) (SIGHUP) re-reads `gateway.yaml`, not the process environment, so it cannot pick up a changed env var; only a fresh container start does.
- **`api_key_encrypted`** (Fernet-encrypted, hand-managed) — re-run `python -m app.cli encrypt-key --provider <name>` under the existing master key (it prompts for the key, or reads it from stdin — don't pass it as a command argument) and paste the new token into `gateway.yaml`. A SIGHUP hot-reload re-reads the file but does **not** rebuild provider adapters — only gateway startup and the runtime provider-key endpoints do — so a hand-pasted token takes effect on the next gateway start, not on reload.
- **Runtime-managed** (the **Admin → Provider keys** screen, or the `provider-keys` API) — the only path that rebuilds the live adapter immediately, with no restart. See [Confirm the replacement path](#confirm-the-replacement-path) above for the exact commands.

Don't assume a hand-edited change and a runtime-managed change behave the same way — only the runtime path is hot-applied.
