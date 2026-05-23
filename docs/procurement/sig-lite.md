# SIG Lite — Privileged-Matter Handling (M2-D3 starter) + M3 External Trust Boundaries

> **Scope of this file**: a **focused starter** covering (1) the SIG Lite questions whose answers depend on the privileged-project handling implemented in M2-B3 / verified in M2-D3, and (2) the questions raised by the **M3 external trust boundaries** — the Word add-in OAuth flow and the Slack / Teams light intake bridges. The **full Procurement-Readiness Pack** (every SIG Lite domain, plus CAIQ, plus cover letter) is **out of scope here** and tracked as [DE-086](../PRD.md#de-086--procurement-readiness-pack); this file is the starter for that work.
>
> Operators reviewing this file for their own procurement cycle should treat it as a complement to (not a substitute for) the full SIG Lite questionnaire. Items not covered here either don't bear on these surfaces or belong to a SIG Lite domain DE-086 will fill in.

---

## How to read this file

Each question below follows the format established in [`docs/procurement/README.md`](README.md):

- **Question** — text from the SIG Lite questionnaire (paraphrased where the source uses domain-specific shorthand).
- **Project response** — the answer applicable to a standard LQ.AI deployment with privileged matters configured per the recommended posture.
- **`[OPERATOR-CONFIGURABLE]`** — where the answer depends on operator-specific deployment choices.
- **References** — relevant PRD sections, security artifacts, and code-side enforcement points.

---

## Data Protection & Privacy Domain (D — selected questions)

### D.1.3 — How is sensitive data classified, and what controls apply to each classification?

**Project response.** LQ.AI provides a two-tier classification mechanism at the application layer:

1. **Non-privileged matters** — the default. Anonymization Layer (PRD §4.7) pseudonymizes user/assistant chat content before transmission to the configured inference provider; retrieved source documents remain un-pseudonymized so the model can reason against intact source text (per [Decision M2-1](../security/anonymization.md#what-gets-pseudonymized)). The pre-anonymization step covers the standard Presidio entity set (PERSON, ORGANIZATION, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION) plus two custom legal recognizers (CaseNumberRecognizer, MatterNumberRecognizer per M2-B2). The post-anonymization step rehydrates pseudonyms back to originals in the model's response before it reaches the user.

2. **Privileged matters** — explicit operator/user designation via the `Project.privileged` flag (`docs/db-schema.md` → `projects` table). Anonymization is **disabled** for chats inside privileged projects (per [Decision A — privileged-skip](../security/anonymization.md#privileged-chats--why-we-skip-m2-b3--m2-d3)): the content reaches the provider verbatim because rewriting privileged work product risks corrupting it and may complicate later assertion of privilege over the artifact. Privileged projects pair with `minimum_inference_tier` (DB CHECK constraint enforces non-NULL when `privileged=true`) so the operator can require local-only (Tier 1) routing for the most sensitive matters.

The control set differs by classification:

| Control | Non-privileged | Privileged (Tier 1 local) | Privileged (Tier 2+ ZDR) |
|---|---|---|---|
| Pre-transmission pseudonymization | Yes | N/A (no transmission) | No |
| Tier-floor enforcement (gateway) | Optional per project | Tier 1 required | Tier 2+ allowed per project setting |
| Audit `privilege_marked` | `false` | `true` | `true` |
| Audit `privilege_basis` | NULL | `project:<name>` | `project:<name>` |
| Provider sees raw entity names | No (pseudonymized) | N/A (local) | Yes |

**References:** [`docs/security/anonymization.md` §What gets pseudonymized](../security/anonymization.md#what-gets-pseudonymized); [`docs/security/anonymization.md` §Privileged chats](../security/anonymization.md#privileged-chats--why-we-skip-m2-b3--m2-d3); PRD §1.5.2 (Inference Tiers), PRD §4.7 (Anonymization Layer).

**Honest validation posture for non-privileged classification.** The pseudonymization control described above runs on every non-privileged chat. Its **mechanism** (pre-substitute, transmit, post-rehydrate; per-request mapper, never persisted) is exercised end-to-end by integration tests including the round-trip correctness suite. Its **recognizer accuracy on legal-document corpus** is empirically unmeasured — Presidio's published metrics target general English (news, social media), not legal prose. Procurement reviewers evaluating residual-risk should read [`docs/security/anonymization.md` §"What's validated vs what's unvalidated"](../security/anonymization.md#whats-validated-vs-whats-unvalidated) for the explicit "where to trust and where to be careful" framing, including the explicit "route to Tier 1 (local Ollama) if the unvalidated risk is unacceptable" guidance. Empirical validation on a curated legal-document corpus is welcomed as a community contribution per [PRD §9 / DE-282](../PRD.md#de-282--anonymization-layer-empirical-validation-on-legal-document-corpus).

---

### D.2.7 — Are any controls applied to data classified as attorney work-product or covered by attorney-client privilege?

**Project response.** Yes. The application provides a first-class **privileged-project** designation that:

1. **Bypasses pseudonymization end-to-end.** The pre-anonymization middleware short-circuits when the incoming request carries `lq_ai_privileged=true` (`gateway/app/anonymization/middleware.py`); the response-path rehydrator is a no-op because nothing was substituted on the request path. The content reaches the inference provider exactly as the user composed it.

2. **Audit-logs the privilege designation as a first-class column.** Every state-changing action on a privileged-project resource writes an `audit_log` row with `privilege_marked=true` and `privilege_basis="project:<project name>"`. The column is indexed and queryable; operators querying for "every action against privileged-matter content over date range X" use `SELECT * FROM audit_log WHERE privilege_marked = true AND timestamp BETWEEN ...`. The CHECK constraint `chk_audit_log_privileged_with_basis` enforces that `privilege_marked=true` rows always have a non-NULL `privilege_basis`.

3. **Honors a per-project tier-floor.** Privileged projects must declare a `minimum_inference_tier` (DB CHECK constraint `chk_projects_privileged_implies_tier`). The gateway's tier-floor logic (PRD §4.4) refuses any routing weaker than the declared tier with HTTP 403 `tier_below_minimum`. The recommended configuration for privileged matters is `minimum_inference_tier=1` (local Ollama only) so the content never leaves the operator's deployment.

4. **Preserves Citation Engine functionality.** Citation verification operates on the chat content directly; no special-casing for privileged projects. A privileged-matter chat with attached source documents produces verified citations exactly as a non-privileged chat does.

**`[OPERATOR-CONFIGURABLE]`** — The operator decides which projects are privileged and which tier floor applies per project. The default posture for new projects is non-privileged + no tier floor; operators set the privileged flag and tier floor when creating or updating the project (`POST /api/v1/projects`, `PATCH /api/v1/projects/{id}`).

**`[OPERATOR-CONFIGURABLE]`** — For privileged matters routed at Tier 2 (enterprise ZDR upstream) rather than Tier 1 (local), the operator's procurement agreement / DPA / BAA with that provider is the binding contractual control covering the unsubstituted content. The application surfaces what tier was used per request via `inference_routing_log.routed_inference_tier`; the contractual control is the operator's responsibility to negotiate and maintain with the upstream.

**References:** [`docs/security/anonymization.md` §Privileged chats](../security/anonymization.md#privileged-chats--why-we-skip-m2-b3--m2-d3); PRD §3.11 (Projects), PRD §4.4 (Tier-Floor Enforcement), PRD §5.3 (Audit Log); `api/app/audit.py::_resolve_project_privilege`; `gateway/app/anonymization/middleware.py` skip conditions.

---

## Audit & Logging Domain (L — selected questions)

### L.2.5 — Are administrative actions on customer data logged in a tamper-evident manner?

**Project response.** Yes, with the following posture:

- **Append-only at the application layer.** The `audit_log` table has no UPDATE or DELETE paths exposed through the API; every state-changing action writes one row at the time of the action. The audit-log writer (`api/app/audit.py::audit_action`) is the only authorized writer; the row is added to the request's outer transaction so the audit row commits atomically with the underlying state change (no audit row without a state change; no state change without an audit row).

- **First-class privilege + tier columns.** The privilege fields (`privilege_marked`, `privilege_basis`) and the routing fields (`routed_inference_tier`, `routed_provider`) are first-class columns rather than JSONB so audit queries can filter on them efficiently. The CHECK constraint `chk_audit_log_privileged_with_basis` prevents writing `privilege_marked=true` without a `privilege_basis`.

- **Request correlation.** Each row carries a `request_id` (the X-Request-ID header value) so audit-log entries cross-reference to gateway `inference_routing_log` rows and application logs.

**`[OPERATOR-CONFIGURABLE]`** — Tamper-evidence at the **DB level** (e.g., row-level signatures, append-only Postgres extensions, periodic snapshot hashes) is the operator's responsibility per their deployment posture. The application does not implement cryptographic tamper-evidence on `audit_log` rows in v0.2; operators with that requirement typically address it via Postgres-level controls (immutable schemas, role-restricted writes, WAL archiving with integrity checking).

**`[OPERATOR-CONFIGURABLE]`** — Retention policy for `audit_log` is operator-controlled. The application writes rows indefinitely; operators with retention-period requirements run a periodic `DELETE FROM audit_log WHERE timestamp < ...` job sized to their policy.

**References:** [`docs/db-schema.md` `audit_log` table](../db-schema.md#audit_log); PRD §5.3 (Audit Log).

---

### L.3.2 — Can administrators surface every action taken on a customer's data within a defined time window?

**Project response.** Yes, via the `GET /admin/audit-log` endpoint (admin-gated). Query parameters include `user_id`, `resource_type`, `resource_id`, `action`, `privilege_marked`, `routed_inference_tier`, `from_timestamp`, `to_timestamp`. The response is paginated (default 100 rows; max 500) so large windows can be walked with cursor-style pagination.

For privileged-matter compliance evidence specifically: `GET /admin/audit-log?privilege_marked=true&from_timestamp=...&to_timestamp=...` returns every audited action against privileged-project resources in the window. Cross-reference to the gateway's `inference_routing_log` table (joined on `request_id`) yields the full pipeline view including which provider/model handled each request and whether anonymization fired.

**References:** [`api/app/api/admin.py` audit-log endpoint]; PRD §5.3 (Audit Log).

---

## Third-Party / Supplier Management Domain (G — selected questions, M3 external trust boundaries)

> The questions in this domain and the next cover the **M3 external trust boundaries**: the Word add-in (Office.js task pane authenticating against the deployment) and the Slack / Teams light intake bridges (OAuth install + identity binding). These surfaces accept inbound traffic from, or run inside, third-party platforms (Microsoft Word, Slack, Microsoft 365). They are **opt-in and operator-controlled**: the operator holds every credential, and LQ.AI remains a self-hosted product — **not** a SaaS intermediary that brokers data between the operator and the third-party platform. See [`docs/word-addin.md`](../word-addin.md) and [`docs/intake-bridges.md`](../intake-bridges.md) for the authoritative implementation state.

### G.1.4 — Does the product integrate with third-party platforms, and if so, who holds the credentials for those integrations?

**Project response.** Three optional third-party integrations exist as of M3; all are operator-controlled, and in every case the operator holds the credentials — LQ.AI does not mediate access through any project-held account.

1. **Word add-in (Microsoft Word / Office.js)** — an Office.js task pane installed into the operator's Word clients via an XML manifest the operator generates from their own admin UI and sideloads through their Microsoft 365 Admin Center. The add-in authenticates against the **deployment's own JWT issuer** (the same one the web app uses), not a third-party IdP, MSAL, or WAM (Word Add-In Decision B-3). There is no LQ.AI-held credential and no third-party OAuth app registration required for the add-in's authentication path.

2. **Slack intake bridge** — an OAuth install to a Slack workspace the operator administers. The operator registers their **own** Slack App (supplying `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` / `SLACK_SIGNING_SECRET`), and the resulting per-workspace bot token is stored **encrypted at rest** inside the operator's own deployment (see G.2.2 and the Access-Control domain below). LQ.AI holds no Slack credential centrally; each operator's deployment holds only its own.

3. **Teams intake bridge** — an OAuth admin-consent install against a Microsoft 365 tenant, backed by an Azure AD **multi-tenant** app the operator registers (`MICROSOFT_APP_ID` / `MICROSOFT_APP_PASSWORD`). The credentials are **app-level**, held by the operator's deployment; **no per-tenant token is stored** (see G.2.2).

**`[OPERATOR-CONFIGURABLE]`** — All three integrations are off by default. The bridges ship behind Docker Compose `slack` / `teams` profiles; an operator who does not enable a profile runs none of that service's code and carries none of its SBOM cost. The Word add-in is distributed only when the operator generates and sideloads the manifest. The operator decides which (if any) to enable and registers the corresponding third-party app(s) under accounts they own.

**Honest integration-maturity posture.** What shipped in M3 for the bridges is **plumbing only** — the service scaffolds, OAuth handlers, bridge→api persistence path, at-rest token encryption, and the admin surface. The install / OAuth / identity-binding path was verified **in isolation** (service health, bridge-bearer auth, at-rest encryption confirmed as Fernet ciphertext, admin surfacing, soft-delete). A **real OAuth round-trip against a public-URL tunnel into a live Slack workspace / M365 tenant has never been exercised** — tracked as [DE-312](../intake-bridges.md#references) (P1). The user-facing `/lq` slash-command surface is deferred to M4 ([DE-288](../intake-bridges.md#references)). The Word add-in's in-document feature surface is likewise deferred to M4 ([DE-287](../word-addin.md#references)); v0.3.0 is install-authenticate-version-check plumbing only. Procurement reviewers should not read these integrations as fully-exercised end-to-end functionality.

**References:** [`docs/intake-bridges.md` §Scope](../intake-bridges.md#scope), §Known limitations; [`docs/word-addin.md` §Scope](../word-addin.md#scope); PRD §3.9 (Word Add-In), PRD §3.15 (Slack / Teams Light Intake Bridge); `slack-bridge/app/oauth.py`, `teams-bridge/app/oauth.py`, `api/app/api/word_addin.py`.

---

### G.2.2 — Are third-party integration secrets (OAuth tokens, API keys) encrypted at rest?

**Project response.** The posture differs by integration because the integrations have different credential models:

- **Slack bridge** — the per-workspace bot token (`xoxb-…`) is encrypted at rest with **Fernet authenticated encryption** under a dedicated master key, `LQ_AI_BRIDGE_MASTER_KEY` (`api/app/security/encryption.py`, `BridgeTokenEncryptor`). The api encrypts the token **before** the row lands; the plaintext travels only the trusted in-cluster network under the bridge bearer, is never persisted in plaintext, and is omitted from any response echoed back to the bridge. The bridge master key is **deliberately distinct** from the gateway's provider-key master key (`LQ_AI_GATEWAY_MASTER_KEY`): a bot token's blast radius (bot impersonation in one workspace) and a provider key's blast radius (inference routing) are different threat models, so they do not share key material.

- **Teams bridge** — there is **no per-tenant secret to encrypt**. Teams uses **app-level** bot credentials (one `MICROSOFT_APP_ID` / `MICROSOFT_APP_PASSWORD` per deployment, supplied as operator-held environment config), so the `teams_tenants` table stores only an identity tuple (tenant id, tenant display name, installing-admin object id) and no token at rest.

- **Word add-in** — no integration secret is stored on the deployment side for the add-in. It authenticates with the deployment's standard user-facing JWTs, which live in the client's `localStorage` (the same exposure surface as the web app, not weakened by the add-in).

**`[OPERATOR-CONFIGURABLE]`** — The operator generates `LQ_AI_BRIDGE_MASTER_KEY` once and stores it as they store other high-value secrets (password manager, secrets vault, hardware token). The encryptor reads it from the environment at construction and holds it in memory only; nothing in the module persists it. An operator who never enables the Slack bridge never needs this key.

**References:** [`api/app/security/encryption.py`](../../api/app/security/encryption.py) (`BridgeTokenEncryptor`); [`docs/intake-bridges.md` §At-rest secret encryption](../intake-bridges.md#at-rest-secret-encryption), §No per-tenant token; `api/app/api/integrations_slack.py`, `api/app/api/integrations_teams.py`; ADR-0011 (gateway Fernet pattern, mirrored without shared key material).

---

## Access Control & Application Security Domain (I — selected questions, M3 external trust boundaries)

### I.3.1 — How are service-to-service and external-platform callbacks authenticated and authorized?

**Project response.** Each M3 external surface uses an authentication model scoped to its trust relationship:

- **Bridge → api (service-to-service).** Every bridge→api persistence POST carries a single shared bearer, `LQ_AI_BRIDGE_TOKEN`, matched **constant-time** (`secrets.compare_digest`) by the api's `require_bridge_auth` dependency (`api/app/api/dependencies.py`). This is service-to-service auth with **no user context** — it is never a user JWT. Fail-safe: if `LQ_AI_BRIDGE_TOKEN` is unset on the api, the dependency raises 500 and refuses all bridge traffic rather than running open. M3-E1 confirmed wrong-token → 401, correct-token → 201.

- **Admin management surface (human admin).** The admin intake-bridges list/delete endpoints (`api/app/api/admin_intake_bridges.py`) require an authenticated user JWT (bearer + must-change-password gate) **plus** an admin-role check; a non-admin authenticated user receives 403 `forbidden`. This is distinct from the service-to-service posture on the persistence endpoints.

- **OAuth CSRF protection.** Both bridges mint a single-use, TTL-bounded `state` token on install initiation and verify it on callback (popped on read, replay-protected). State tokens are held in-memory in the single-instance bridge; a bridge restart mid-install invalidates the in-flight install and the operator restarts it.

- **Inbound Slack webhook signatures.** The Slack `/slack/events` endpoint verifies the Slack HMAC-SHA256 request signature (5-minute replay window) on **every** request before any handling — shipped now so the deferred slash-command handler lands on a verified substrate, even though the handler is otherwise inert at v0.3.0.

- **Word add-in OAuth.** The task pane authenticates over the Office.js Dialog API against the deployment's own JWT issuer; the dialog navigates only to `{deployment_origin}/lq-ai/word-addin/oauth-start` (same origin as the pane). `messageParent` payloads from the dialog are parsed defensively — malformed JSON, unexpected types, and dialog-API failures resolve to a typed error/cancelled outcome rather than throwing.

**Honest caveat (OAuth surface).** Because the real OAuth round-trip against a public tunnel has never run for the bridges ([DE-312](../intake-bridges.md#references), P1), the bridges' behavior under a genuine provider callback — live `state` round-trip, redirect-URI matching, token-exchange error handling against the real provider endpoints — is verified only by unit tests and isolated POST simulation, not by an end-to-end install. Treat the bridge OAuth surface as "implemented and unit-tested" rather than "proven against the live providers" until DE-312 closes.

**References:** [`docs/intake-bridges.md` §Security / threat model](../intake-bridges.md#security--threat-model); [`docs/word-addin.md` §OAuth flow](../word-addin.md#oauth-flow-m3-b2), §Threat model; `api/app/api/dependencies.py` (`require_bridge_auth`), `api/app/api/admin_intake_bridges.py`; `slack-bridge/app/signing.py`.

---

### I.4.2 — What identity and permission scope do the third-party integrations carry, and do their stored identity claims grant any application authority?

**Project response.** The integrations request narrow scopes and store identity claims for audit only — no stored identity claim grants any LQ.AI permission.

- **Scope narrowness.** The Slack bridge requests exactly two bot scopes (`commands`, `chat:write`) — no `channels:read` / `groups:read` / `im:read`, so **the bot does not read silent channels**; it acts only on explicit user invocations (a surface that itself is deferred to M4). The Teams bridge requests `openid` / `profile` / `email` / `offline_access` / `User.Read` — `User.Read` is the narrowest scope returning a Graph-usable token for the best-effort tenant display-name lookup. The Word add-in declares `ReadWriteDocument` in its manifest, but **no shipped code exercises it** at v0.3.0 — the permission is declared ahead of the deferred feature surface (DE-287), so the granted permission currently exceeds what the shipped code uses; reviewers should note this gap.

- **Identity claims are audit-only.** The Slack installer's user id, the Teams installing-admin object id, and the Teams tenant id are stored as **audit/identity fields only** and grant no LQ.AI-side permission. The Teams `id_token` is decoded **without signature verification** to read the tenant / admin claims — this is safe because the token arrived over TLS via the bridge's `client_secret`-authenticated POST to Microsoft's token endpoint, and the claims confer no authority.

- **No add-in-scoped audience.** The Word add-in uses the same bearer-token shape as the web app — no `aud: word-addin` claim. The add-in is the **same trust principal** as the web app today, not a separately revocable one; this is documented honestly rather than overstated.

**References:** [`docs/intake-bridges.md` §Scopes — narrow on purpose](../intake-bridges.md#scopes--narrow-on-purpose), §Identity claims grant no authority; [`docs/word-addin.md` §No add-in-scoped token](../word-addin.md#no-add-in-scoped-token), §Document permissions; `slack-bridge/manifest.yml`, `teams-bridge/manifest.json`, `word-addin/manifest.xml`.

---

### I.5.3 — How is software from this product distributed and verified at install time (supply-chain integrity at the install boundary)?

**Project response.** Relevant to the Word add-in specifically. At v0.3.0 the add-in ships **only the unsigned-manifest sideload path**: the operator generates an XML manifest from their own admin UI and uploads it through their Microsoft 365 Admin Center. **M365 will warn the admin that the add-in is unsigned during upload** — this warning is expected and correct at v0.3.0, because the project does not yet hold a code-signing certificate. Two properties bound the residual risk:

1. The trust decision rests with the operator's **own admin**, who is uploading a manifest they generated from their own deployment's admin UI. The manifest points only at the operator's own `DEPLOYMENT_ORIGIN` (a single `<AppDomain>`), so the install does not widen the navigation surface beyond the deployment the admin already trusts.

2. The add-in's installed version is **baked into the bundle** (`__ADDIN_VERSION__`), not read from the API, so a tampered version-handshake response cannot misrepresent the add-in's own version to bypass the compatibility gate. The handshake's optional bundle-hash field ships `null` (don't-enforce) at v0.3.0, so the add-in cannot yet detect a stale-cached bundle.

**`[OPERATOR-CONFIGURABLE]` / honest gap.** A **signed** manifest + signed distribution package would let the admin verify provenance cryptographically rather than trust the generation flow. That work is [DE-295](../word-addin.md#references) (community-led, gated on code-signing certificate procurement). Until it lands, the unsigned path must **not** be represented as equivalent to a signed enterprise distribution.

**References:** [`docs/word-addin.md` §Unsigned-manifest posture](../word-addin.md#unsigned-manifest-posture), §Version handshake integrity; PRD §3.9; `word-addin/manifest.xml`, `api/app/api/word_addin.py`.

---

## Out of scope for this file

The full SIG Lite questionnaire covers 18 domains spanning data protection, access controls, network security, vulnerability management, incident response, business continuity, supplier management, and more. This starter file covers only the questions whose responses materially differ depending on the privileged-project handling (D, L) or the M3 external trust boundaries — the Word add-in and the Slack / Teams intake bridges (G, I).

For the full procurement-readiness pack — pre-filled responses across every SIG Lite domain plus CAIQ Lite plus a cover letter template — see [DE-086](../PRD.md#de-086--procurement-readiness-pack). Community contributions to that work are explicitly welcomed; see [`docs/procurement/README.md` §Contributing](README.md#contributing) for the contribution path.
