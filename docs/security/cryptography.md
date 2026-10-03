# Cryptography

> **Scope:** Cryptographic primitives used by LQ.AI, key lifecycle, and known limitations. Intended for operators evaluating the system for procurement, and for security reviewers tracing a specific control. Anchored to the M1 implementation — not generic AppSec text.

## Primitives in use

| Purpose | Algorithm | Library | Reference |
|---|---|---|---|
| Session access tokens | JWT HS256 | `PyJWT` (`pyjwt[crypto]`) | [`api/app/security/jwt.py:43`](../../api/app/security/jwt.py) (`_JWT_ALGORITHM = "HS256"`); minted at `:99`, verified at `:117` |
| MFA challenge tokens | JWT HS256 | `PyJWT` | [`api/app/security/jwt.py:161`](../../api/app/security/jwt.py) (minted), `:168` (verified) |
| Refresh tokens (plaintext) | CSPRNG, 32 bytes urlsafe-base64 | Python `secrets` | [`api/app/security/jwt.py:219`](../../api/app/security/jwt.py) (`secrets.token_urlsafe(32)`) |
| Refresh tokens (at rest) | bcrypt | `bcrypt` (direct, not via `passlib`) | [`api/app/security/jwt.py:223-228`](../../api/app/security/jwt.py) |
| User passwords (at rest) | bcrypt, cost factor 12 (configurable) | `bcrypt` | [`api/app/security/passwords.py:25-40`](../../api/app/security/passwords.py); cost factor at [`api/app/config.py:207`](../../api/app/config.py) |
| MFA recovery codes (at rest) | bcrypt | `bcrypt` (via `app.security.passwords`) | [`api/app/security/totp.py:117-122`](../../api/app/security/totp.py) |
| TOTP shared secret | RFC 6238 (base32, 30 s step, 6 digits) | `pyotp` | [`api/app/security/totp.py:64-71`](../../api/app/security/totp.py) |
| First-run admin password | CSPRNG, 24 chars from `[A-Za-z0-9]` (~143 bits) | Python `secrets` | [`api/app/admin_bootstrap.py:52-58`](../../api/app/admin_bootstrap.py) (`secrets.choice`) |
| MFA recovery-code generation | CSPRNG, 48-bit hex tokens | Python `secrets` | [`api/app/security/totp.py:117-120`](../../api/app/security/totp.py) (`secrets.token_hex`) |
| Provider API keys (at rest) | Fernet (AES-128-CBC + HMAC-SHA256, RFC-compliant authenticated encryption) | `cryptography` | [`gateway/app/secrets.py:33`](../../gateway/app/secrets.py), [encrypted-keys.md](encrypted-keys.md), [ADR 0011 §Encrypted-at-rest provider keys](../adr/0011-transparency-first-model-selection.md#encrypted-at-rest-provider-keys) |
| In-transit between services | TLS 1.2+ | Operator-deployed via ingress | [Helm chart Ingress](../../deploy/helm/lq-ai/templates/ingress.yaml) (`.Values.ingress.tls`) |

No application-layer database-column encryption. The PostgreSQL `pgcrypto` extension is used only for `gen_random_uuid()` server defaults (primary keys), not for encrypted columns; all at-rest encryption decisions are made in application code.

## Key lifecycle

### Session signing secret (`JWT_SECRET`)

- **Generation:** operator-supplied at deployment time. Recommended: `openssl rand -hex 32` (256 bits). The Pydantic default (`"dev-jwt-secret-change-me"` at [`api/app/config.py:149`](../../api/app/config.py)) is intentionally obvious so it trips review.
- **Storage:** Kubernetes Secret `lq-ai-auth` key `jwt-secret` ([`deploy/helm/lq-ai/values.yaml:63-64`](../../deploy/helm/lq-ai/values.yaml); referenced from [`deploy/helm/lq-ai/templates/deployment-api.yaml:57`](../../deploy/helm/lq-ai/templates/deployment-api.yaml)). For Docker Compose deployments: `.env` entry `JWT_SECRET`.
- **Rotation:** restart api with a new `JWT_SECRET`. Existing access and MFA tokens fail signature verification; refresh tokens (opaque random + bcrypt hash, not JWT) survive rotation but the user will need to re-authenticate when their access token expires. No graceful overlap window in M1.
- **Disclosure impact:** an attacker with `JWT_SECRET` can forge any user's access token (including `is_admin=true`). Treat as "rotate immediately + accept that all sessions invalidate."

### Master key for Fernet-wrapped provider keys (`LQ_AI_GATEWAY_MASTER_KEY`)

- **Generation:** operator-controlled via `python -m gateway.cli generate-master-key`. See [encrypted-keys.md §One-time bootstrap](encrypted-keys.md#one-time-bootstrap).
- **Storage:** operator's secrets vault. Gateway reads the plaintext master key from `LQ_AI_GATEWAY_MASTER_KEY` (or `LQ_AI_GATEWAY_MASTER_KEY_FILE`, #590) at process start ([`gateway/app/secrets.py`](../../gateway/app/secrets.py)); never on disk after the encryption helper exits.
- **Rotation:** re-encrypt every provider key under the new master before restarting the gateway with the new value. Fernet has no in-band rotation primitive; the operator runs the encryption CLI once per provider with the new master, swaps the `api_key_encrypted` tokens in `gateway.yaml`, then restarts.
- **Disclosure impact:** an attacker with the master key can decrypt every `api_key_encrypted` in `gateway.yaml`. Treat as "rotate master + re-encrypt all provider keys."

### Gateway shared secret (`LQ_AI_GATEWAY_KEY`)

- **Generation:** operator-supplied at deployment time. Recommended: `openssl rand -hex 32` ([`deploy/helm/lq-ai/values-example.yaml:10`](../../deploy/helm/lq-ai/values-example.yaml)).
- **Storage:** Kubernetes Secret `lq-ai-auth` key `gateway-key` ([`deploy/helm/lq-ai/values.yaml:65`](../../deploy/helm/lq-ai/values.yaml); referenced from [`deploy/helm/lq-ai/templates/deployment-gateway.yaml:29-31`](../../deploy/helm/lq-ai/templates/deployment-gateway.yaml) and [`deploy/helm/lq-ai/templates/deployment-api.yaml:52`](../../deploy/helm/lq-ai/templates/deployment-api.yaml)). For Docker Compose: `.env` `LQ_AI_GATEWAY_KEY` or `LQ_AI_GATEWAY_KEY_FILE` pointing at a `0400`/`0600` mount (#590).
- **Rotation:** the gateway picks up new admin-managed configuration via the hot-reload path ([ADR 0010](../adr/0010-gateway-config-hot-reload.md)); the shared-secret env var itself requires a coordinated restart of both api and gateway with the new value.
- **Disclosure impact:** an attacker with this key can call the gateway directly, bypassing api-level audit logging.

### Provider API keys

Two paths, per [ADR 0011 §Encrypted-at-rest provider keys](../adr/0011-transparency-first-model-selection.md#encrypted-at-rest-provider-keys):

- `api_key_env` — operator passes the plaintext key as an env var. Plaintext exists in the gateway process environment for the lifetime of the process and is visible to anything reading `/proc/<pid>/environ`.
- `api_key_encrypted` — operator runs `python -m gateway.cli encrypt-key` to produce a Fernet ciphertext ([`gateway/app/cli.py`](../../gateway/app/cli.py)); gateway decrypts in memory at adapter-build time. Plaintext never on disk after the encryption helper exits. See [encrypted-keys.md](encrypted-keys.md) for the full operator workflow including rotation and recovery.

### TOTP shared secrets

- **Generation:** [`pyotp.random_base32()`](../../api/app/security/totp.py) at MFA enrollment.
- **Storage:** plaintext on `users.totp_secret`. The operator-of-self model gives the user no recovery path from a lost secret other than disabling MFA; storing the secret plaintext is a deliberate trade against re-enrollment churn. Database-leak exposure is mitigated by the same DB-access controls protecting password hashes.
- **Rotation:** user-initiated via re-enrolling MFA (issues a fresh secret and a fresh recovery-code set).

## Known limitations

- **HS256 (symmetric) instead of RS256/ES256.** M1 uses HS256 because a single backend service signs tokens for itself — there is no third party that needs to verify without holding the secret. Asymmetric signing would add operational complexity (key-pair management, public-key distribution) without changing the threat model in our deployment topology. If a future milestone introduces a second verifier (e.g., a separate audit-log signer), switching to RS256/ES256 is a localized change in [`api/app/security/jwt.py`](../../api/app/security/jwt.py) (the `_JWT_ALGORITHM` constant plus the secret-loading path).
- **No session-overlap during `JWT_SECRET` rotation.** Rotation invalidates every outstanding access and MFA token. Acceptable for M1's deployment scale; a graceful overlap window (dual-key verification during a rollover) is a future enhancement if operator deployments grow large enough that simultaneous re-authentication becomes operationally painful.
- **Fernet uses AES-128-CBC + HMAC-SHA256, not AEAD-GCM.** Fernet is a documented profile that does provide authenticated encryption via HMAC, but it is not NIST-AEAD. Operators preferring NIST-standardized AEAD-GCM can swap in libsodium-based encryption by replacing [`gateway/app/secrets.py`](../../gateway/app/secrets.py); the chart, CLI, and `gateway.yaml` schema continue to work as long as the wire format is documented in the replacement.
- **TLS termination is operator-managed.** LQ.AI does not terminate TLS in any container; ingress or an operator-supplied reverse proxy handles certs. This is by design (cert management is operator policy, not application policy) but means the application has no telemetry on TLS-handshake-level threats. The Helm chart's `.Values.ingress.tls` block ([`deploy/helm/lq-ai/templates/ingress.yaml:17-19`](../../deploy/helm/lq-ai/templates/ingress.yaml)) is the operator's hook.
- **No HSM / KMS integration in M1.** The master key for Fernet-wrapped provider keys is an env-var-held secret. Operators with HSM/KMS requirements can fork [`gateway/app/secrets.py`](../../gateway/app/secrets.py) to source the master key from cloud KMS at process start; a built-in adapter (AWS KMS, GCP KMS, Vault Transit) is a candidate for a future milestone.
- **bcrypt is not memory-hard.** bcrypt at cost factor 12 is the OWASP-recommended floor as of 2024, and the dominant offline-cracking constraint here is the entropy of refresh tokens (32 bytes / 256 bits) and the generated admin password (~143 bits) rather than the hash function. Operators handling high-value user-chosen passwords against a determined offline attacker can raise `BCRYPT_ROUNDS` ([`api/app/config.py:207`](../../api/app/config.py)) or, as a future enhancement, the project may migrate to argon2id — both are localized changes in [`api/app/security/passwords.py`](../../api/app/security/passwords.py).
