# Encrypted-at-Rest Provider Keys — Operator Workflow

> **Status:** Operator-facing workflow for the encrypted-at-rest path landed in [ADR 0011 §"Encrypted-at-rest provider keys"](../adr/0011-transparency-first-model-selection.md#encrypted-at-rest-provider-keys). The CLI helpers ship in [`gateway/app/cli.py`](../../gateway/app/cli.py); the resolver in [`gateway/app/secrets.py`](../../gateway/app/secrets.py).
>
> **Audience:** Operators deploying the LQ.AI gateway. Assumes shell familiarity and basic secrets-vault hygiene; no crypto background required.

---

## Why this exists

Provider API keys (Anthropic, OpenAI, Vertex, etc.) historically lived in `gateway.yaml` as `api_key_env: ANTHROPIC_API_KEY` — the gateway resolved the literal at runtime by reading the host's environment. That works, but the plaintext key is still:

- visible in `ps eww` / `/proc/<pid>/environ` to anyone with shell access on the host,
- present in `.env` files that frequently land in backup snapshots,
- exposed to anything that reads `os.environ` (debuggers, accidental log dumps, errant exception handlers).

The encrypted-at-rest path closes this gap. The plaintext key only exists in two places: in the operator's secrets vault (where it always belonged) and in the gateway process's memory for the duration of an adapter call. `gateway.yaml` itself carries only a Fernet ciphertext, safe to commit to a private deployment repo or stage in build artifacts.

Both paths (`api_key_env` and `api_key_encrypted`) remain supported. Different providers in the same `gateway.yaml` can pick whichever fits the operator's threat model. The deprecated `api_key: ${ANTHROPIC_API_KEY}` direct-interpolation form stays loadable through M1 + M2 per ADR 0011 — operators with new deployments should prefer the encrypted path.

---

## What you're setting up

Two artifacts:

1. A **master key** — one urlsafe-base64 256-bit value. Generated once. Stored in the operator's secrets vault. Bound to the gateway process at startup via the `LQ_AI_GATEWAY_MASTER_KEY` environment variable. Never persisted by the gateway itself.
2. One **encrypted token per provider** — a Fernet ciphertext that wraps a plaintext provider API key under the master key. Pasted into `gateway.yaml` under `providers[].api_key_encrypted`.

The gateway decrypts each token in-memory at adapter build time. The plaintext never touches disk after the operator runs the encryption helper.

---

## One-time bootstrap

Run from the gateway service container (or from `gateway/` in a checkout with the gateway's Python environment active):

```bash
# 1. Generate the master key. Output goes to stdout; usage hint goes to stderr.
python -m app.cli generate-master-key
# → gAAAAAB...your-master-key... (urlsafe-base64; 44 chars)
```

Store this value in the operator's secrets vault — the same place other small high-value secrets live (a password manager, a hardware token, a Vault entry, an SSM parameter, a sealed K8s secret). The gateway never writes it anywhere; if you lose it, see [§"What if I lose the master key?"](#what-if-i-lose-the-master-key) below.

Then export it in the gateway's process environment for every subsequent step in this workflow and for normal gateway runtime:

```bash
export LQ_AI_GATEWAY_MASTER_KEY=gAAAAAB...your-master-key...
```

Deployment-target equivalents:

| Target | How to bind `LQ_AI_GATEWAY_MASTER_KEY` |
|---|---|
| `docker compose` | `environment:` block on the `gateway` service, or a `.env` entry the compose file consumes |
| Kubernetes | `envFrom: secretRef:` referencing a sealed-secret / external-secrets-operator entry |
| systemd | `EnvironmentFile=` pointing at a 0600-permission file |
| direct host | shell profile that the gateway service unit reads at start |

The master key lives in the gateway process; the api/ and web/ services don't need it.

### File-mounted delivery (`*_FILE`)

Every gateway secret `NAME` may instead be delivered as `NAME_FILE=<path>`
(#590, GW-06). This covers `LQ_AI_GATEWAY_MASTER_KEY`, `LQ_AI_GATEWAY_KEY`
(or whatever `gateway_auth.api_key_env` names), and any provider/tool-provider
`api_key_env` target (e.g. `ANTHROPIC_API_KEY_FILE`, `COURTLISTENER_API_TOKEN_FILE`).
The `api/` service honors `LQ_AI_GATEWAY_KEY_FILE` for the same shared secret
so mixed env/file deployments keep authenticating.

```bash
# Docker Compose (Swarm-style secrets block — values are paths, not secrets)
# compose file excerpt (illustrative; replace CHANGEME paths with yours):
# secrets:
#   gateway_master_key:
#     file: ./secrets/gateway_master_key.txt
# services:
#   gateway:
#     secrets:
#       - source: gateway_master_key
#         target: /run/secrets/gateway_master_key
#         mode: 0400
#     environment:
#       LQ_AI_GATEWAY_MASTER_KEY_FILE: /run/secrets/gateway_master_key
```

```yaml
# Kubernetes (external-secrets-operator or sealed-secret mounted as a file)
# env:
#   - name: LQ_AI_GATEWAY_MASTER_KEY_FILE
#     value: /var/run/secrets/lq-ai/gateway_master_key
```

```ini
# systemd (credential passing — no secret in the unit file)
# [Service]
# LoadCredential=gateway_master_key:/etc/lq-ai/secrets/gateway_master_key
# Environment=LQ_AI_GATEWAY_MASTER_KEY_FILE=%d/gateway_master_key
```

Rules:

* Set `NAME` **or** `NAME_FILE`, never both — both set fails at startup with a
  `SecretSourceConflict` naming the variable (never the value).
* Files are UTF-8 text, stripped of surrounding whitespace (a trailing newline
  from Vault/agent templates is fine). Missing, unreadable, directory, or
  empty-after-strip files fail clearly (`SecretFileError` naming var + path).
  Master/gateway-key failures are fatal; a bad provider-key file skips that
  provider with a warning (same as a missing env key) so unrelated providers
  keep serving.
* Permissions: store files `0400`/`0600` owned by the service user. A
  group/world-readable file logs a warning but still loads (warn-only by design
  so sloppy dev mounts do not hard-fail production boot).
* Env-only deployments keep working unchanged — to migrate, mount the file,
  set `*_FILE`, unset the plaintext var, restart.

Remaining exposure (even with files): the plaintext still lives in the gateway
process heap for the duration of adapter calls; `docker inspect` / Compose
`environment:` entries, `/proc/<pid>/environ`, core dumps, and host-root or
`CAP_SYS_PTRACE` container inspection can all recover it. File delivery shrinks
the `.env`-in-backup-snapshot surface — it does not make secrets unreadable to
host root. Keep mount paths `0400`, restrict which UIDs can `docker exec`, and
prefer a secret manager as the file source rather than a checked-in file.

---

## Encrypting each provider key

Once the master key is exported, wrap each provider's plaintext API key:

```bash
# Interactive path — recommended. The plaintext never appears in shell history.
python -m app.cli encrypt-key --provider anthropic-prod
# Provider key (input hidden): ********
# → gAAAAAB...token-for-this-provider... (paste into gateway.yaml)
```

```bash
# Piped path — useful when the plaintext comes from another command (e.g.,
# `vault read -field=value secret/anthropic`). The plaintext still doesn't land
# in history because it's never on a command line.
vault read -field=value secret/anthropic | python -m app.cli encrypt-key --provider anthropic-prod
```

Avoid `--plaintext "<key>"` (inline argument): the plaintext lands in shell history, in `ps` output for the lifetime of the process, and possibly in your terminal scrollback. The flag exists for non-interactive automation that already handles secret hygiene; humans should prefer the interactive prompt or stdin pipe.

Each invocation produces a different ciphertext for the same plaintext — Fernet generates a fresh nonce per call (authenticated encryption requires this for safety). Don't be alarmed when a re-encrypt produces a different token; that's expected, and the gateway decrypts it identically.

The `--provider` argument is purely informational; the encrypted token doesn't bind to a provider name, so technically any token decrypts under any master key. Pass `--provider` anyway so the stderr hint reminds you which `gateway.yaml` entry the token belongs to.

---

## Pasting into `gateway.yaml`

Replace the provider's `api_key_env:` line with `api_key_encrypted:` carrying the token:

```yaml
# Before (env-var path)
providers:
  - name: anthropic-prod
    type: anthropic
    base_url: https://api.anthropic.com
    api_key_env: ANTHROPIC_API_KEY      # ← reads $ANTHROPIC_API_KEY at startup
    tier: 4
    models:
      - claude-opus-4-7

# After (encrypted-at-rest path)
providers:
  - name: anthropic-prod
    type: anthropic
    base_url: https://api.anthropic.com
    api_key_encrypted: gAAAAAB...token-for-this-provider...
    tier: 4
    models:
      - claude-opus-4-7
```

Per ADR 0011 each provider entry uses **either** `api_key_env` **or** `api_key_encrypted`, not both. The config loader rejects mixed entries at startup so a typo doesn't silently fall back to a path the operator didn't intend.

Restart the gateway (or trigger config hot-reload per [ADR 0010](../adr/0010-gateway-config-hot-reload.md)) to pick up the change. The gateway logs decryption failures with the offending provider name and the master-key env var name — wrong key or mangled token both surface the same `DecryptError` because Fernet's authenticated encryption rejects both indistinguishably.

[`gateway.yaml.example`](../../gateway.yaml.example) carries the full canonical commentary on the two paths; that file is the reference any new deployment cargo-cults from.

---

## Master-key rotation

Rotate the master key when:

- a person who had access to the master key leaves the team or changes roles,
- the master key is suspected of compromise (logged accidentally, copy-pasted somewhere it shouldn't have been, found in a snapshot you can't fully redact),
- on whatever cadence the operator's compliance regime dictates (annually is common for SOC 2 / ISO 27001 deployments; the gateway doesn't enforce a cadence).

The procedure is the same in all cases:

1. **Generate a fresh master key.**
   ```bash
   python -m app.cli generate-master-key
   # → gAAAAAB...new-master-key...
   ```

2. **Re-encrypt every provider key under the new master key.** You need the plaintext keys for this — pull them from the secrets vault (the vault is the system of record; `gateway.yaml` was never meant to be that).
   ```bash
   export LQ_AI_GATEWAY_MASTER_KEY=gAAAAAB...new-master-key...
   for provider in anthropic-prod openai-prod vertex-anthropic; do
     vault read -field=value "secret/$provider" \
       | python -m app.cli encrypt-key --provider "$provider"
     # paste each new token into gateway.yaml under its provider entry
   done
   ```

3. **Update `gateway.yaml`** so each `api_key_encrypted:` carries the new token. The yaml diff is large (every encrypted token changes), but the wire-format key has not changed.

4. **Swap `LQ_AI_GATEWAY_MASTER_KEY`** in the gateway's deployment environment to the new value.

5. **Restart the gateway** (or trigger config reload). Verify with `curl http://gateway/admin/v1/providers/health` that each provider's adapter built successfully — a stale master key would surface as `DecryptError` at adapter-build time and the provider would not register.

6. **Revoke the old master key** in your secrets vault (or mark superseded with an audit-log entry — your vault's convention). The gateway never reads it again; nothing in the deployment will accept it.

7. **Optional belt-and-suspenders:** rotate the upstream provider keys themselves (request a new key from Anthropic / OpenAI / etc., revoke the old one). The master key only protects the at-rest form; if you suspect the plaintext provider key itself leaked, rotating the master key alone doesn't help.

There is no online rotation primitive — the gateway doesn't accept two master keys simultaneously. The yaml-swap-and-restart cycle takes seconds and is the supported path; if your deployment's failure budget can't absorb a gateway restart, blue-green a fresh gateway instance with the new master key + tokens, then switch the load balancer over.

---

## What if I lose the master key?

There is no recovery. This is by design — the master key is the cryptographic root of trust for every encrypted token in `gateway.yaml`, and if a stale master key could decrypt them, the encryption wouldn't protect against backup-tape leakage in the first place.

Recovery procedure when the master key is lost:

1. **Re-issue every provider key at the upstream provider.** Log into Anthropic / OpenAI / Vertex / Bedrock / Azure / etc., revoke the old API key, generate a fresh one. (You should treat the old plaintext keys as compromised: anyone who had access to both the old master key and `gateway.yaml` had access to the plaintext, even if you can't prove they did.)
2. **Generate a fresh master key** (`python -m app.cli generate-master-key`); store it in the secrets vault.
3. **Encrypt the new plaintext provider keys** under the new master key; paste the resulting tokens into `gateway.yaml`.
4. **Swap `LQ_AI_GATEWAY_MASTER_KEY`** in the gateway's deployment environment.
5. **Restart the gateway.**

Total effort scales with the number of providers configured. For a deployment with three or four providers, the lost-key recovery is 30–60 minutes of operator time, dominated by waiting for the upstream providers' "issue new API key" UIs.

The lesson is the same as for any cryptographic root of trust: back up the master key in at least two independent vault entries (e.g., the primary password manager + a sealed envelope in a safe) before you turn on encrypted keys in production. The master key is small enough that a printed sheet locked in a drawer is a defensible backup strategy.

---

## Verifying the setup

After bootstrap or rotation, a quick smoke:

```bash
# 1. Encrypted token round-trips on the host (unit-tests this every CI run, but worth a manual check).
python -m app.cli encrypt-key --provider test < <(echo "round-trip-canary")
# → gAAAAAB...token...

# 2. Gateway adapter health — confirms decryption succeeded at startup.
curl -s http://localhost:8001/admin/v1/providers/health | jq '.providers[] | {name, ok}'
# → each provider you've configured should report ok: true

# 3. End-to-end dispatch — confirms the decrypted key reaches the upstream provider.
curl -sX POST http://localhost:8001/v1/chat/completions \
  -H "X-LQ-AI-Gateway-Key: $LQ_AI_GATEWAY_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"smart","messages":[{"role":"user","content":"ping"}]}' \
  | jq '.choices[0].message.content, .routed_provider, .routed_inference_tier'
```

A failure during step 2 with an error message naming `LQ_AI_GATEWAY_MASTER_KEY` means the gateway loaded `gateway.yaml` but couldn't decrypt one of the `api_key_encrypted` entries — most often a mismatched master key or a token that was edited (e.g., line-wrapped) when pasted into yaml.

---

## What this doesn't do

Calibrating the operator's expectations:

- **Encrypted at rest, not encrypted in use.** The plaintext provider key exists in `GatewayConfig.providers[*].api_key` in the gateway's heap for the duration of the process. A memory dump from a compromised gateway host still recovers the plaintext. The threat model is leakage of `gateway.yaml` (committed to a repo, included in a backup, exfiltrated from a snapshot) — not leakage of live process memory.
- **The master key is still a secret you have to keep.** The encryption moves the trust boundary from "anyone with read access to `gateway.yaml` or `.env`" to "anyone with read access to the master key." The latter should be a much smaller set of people and systems.
- **Per-user provider keys are out of scope** (ADR 0011 §"Out of scope"). The Inference Gateway is the security boundary; provider keys belong to the operator, not the end user. A multi-tenant deployment that bills end-users to their own provider accounts is a different architecture.
- **No HSM or KMS integration in M1.** The master key is a raw byte string the operator manages with their existing secrets tooling. Operators who want KMS-rooted master keys (AWS KMS / GCP KMS / HashiCorp Vault Transit) should treat that as a wrapper around the bootstrap step — fetch the master key from KMS at gateway start, bind it to `LQ_AI_GATEWAY_MASTER_KEY`, never write it to disk. A first-class KMS-resolution path is a candidate post-M1 enhancement; track interest as a DE if procurement requires it.

---

## References

- [ADR 0011 §"Encrypted-at-rest provider keys"](../adr/0011-transparency-first-model-selection.md#encrypted-at-rest-provider-keys) — the decision and threat-model framing.
- [`gateway/app/cli.py`](../../gateway/app/cli.py) — `generate-master-key` and `encrypt-key` subcommands.
- [`gateway/app/secrets.py`](../../gateway/app/secrets.py) — `ProviderKeyResolver`, `encrypt_value`, `generate_master_key`, error classes.
- [`gateway/tests/test_secrets.py`](../../gateway/tests/test_secrets.py) — unit-test surface: round-trips, mixed-source rejection, wrong-master-key behavior, corrupted-ciphertext detection.
- [`gateway.yaml.example`](../../gateway.yaml.example) — canonical reference for the two key-resolution paths on a provider entry.
- [ADR 0010 — Gateway config hot-reload](../adr/0010-gateway-config-hot-reload.md) — config-change rollout semantics that apply equally to the encrypted-key path.
- [PRD §1.3 — Transparency as a founding principle](../PRD.md#13-transparency-as-a-founding-principle) — the framing under which "encrypted by default" is the right default for new deployments.
