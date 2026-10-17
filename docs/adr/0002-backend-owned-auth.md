# ADR 0002 — Backend (FastAPI) owns authentication

**Status:** Accepted (2026-05-07)
**Decision-makers:** Kevin Keller (initial maintainer)
**Affected components:** `api/`, `web/`, `word-addin/` (M3)

---

## Context

PRD v0.1 stated that "v1 uses OpenWebUI's built-in auth: local accounts, OAuth, SAML, LDAP/AD, SCIM 2.0, trusted-header SSO." The OpenAPI sketches drafted alongside v0.2, however, specified a complete auth surface owned by the FastAPI backend (`/api/auth/login`, `/api/auth/mfa/*`, `/api/auth/refresh`, etc.). The Word add-in (M3) was always going to authenticate against a backend endpoint, not against the OpenWebUI fork.

Two architectures had been on the table:

**Option A — OpenWebUI owns auth.** The Web client uses OpenWebUI's built-in auth; the backend trusts session cookies or trusted-header SSO from OpenWebUI; the Word add-in either re-implements OpenWebUI's auth or uses a separate backend auth path. Identity store is OpenWebUI's database (or whatever IdP OpenWebUI is configured against).

**Option B — Backend owns auth.** The FastAPI backend implements all auth flows. The OpenWebUI fork is configured to delegate to the backend's auth endpoints; the Word add-in (and any future client) uses the same endpoints. There is one identity store, one session model, one audit-log trail.

During M1 planning, several factors made Option B the simpler architecture in practice:

- **Single source of truth.** The audit-log requirements in [PRD §5.3](../PRD.md#53-audit-logging) — particularly `privilege_marked`, `privilege_basis`, and `routed_inference_tier` correlation across login, chat, file, and inference events — work cleanly when one service owns the identity-and-session model.
- **Word add-in (M3) parity.** The Word add-in was always going to use the backend, not OpenWebUI. Two auth paths in v1 to consolidate later was strictly worse than one auth path from the start.
- **MFA, recovery codes, and per-user export/delete.** The M1 deliverable surface (MFA-mandatory option, GDPR Article 17 deletion, GDPR Article 20 export) is cleaner to implement once, in one service, against one schema.
- **OpenAPI surface is already drafted.** The backend OpenAPI sketch already specified the auth endpoints in detail. Reversing course to OpenWebUI-owned auth would have meant rewriting the sketch and de-scoping the Word add-in's auth work.

## Decision

**The LQ.AI FastAPI backend owns authentication.** All clients (the OpenWebUI fork, the Word add-in, and any future surface) authenticate via the backend's auth endpoints.

**Identity store.** The `users`, `user_sessions`, and related tables in the LQ.AI Postgres database (per [`docs/db-schema.md`](../db-schema.md)) are the canonical identity store. There is no parallel OpenWebUI auth database.

**Session model.** Short-lived JWT access tokens (~15 min) plus refresh tokens (default 7 days, hashed at rest in `user_sessions`). Refresh tokens rotate on use. Programmatic clients use scoped API tokens.

**IdP integrations.** OAuth (Google, Microsoft, GitHub), SAML 2.0, LDAP/AD, SCIM 2.0, and trusted-header SSO are first-class — implemented in the backend as pluggable auth providers, not as an OpenWebUI configuration.

**OpenWebUI fork integration.** The fork is configured to disable its built-in auth and delegate to the backend. The login UI in `web/` calls `/api/auth/login`; the chat session uses the JWT access token; logout calls `/api/auth/logout`. The fork does not maintain a parallel session.

**MFA.** TOTP via `pyotp` in M1; WebAuthn is a tracked enhancement (DE-### TBD). Recovery codes are single-use, hashed at rest, rotated on re-enrollment.

### October 2026 addendum — local account administration

For a small operator-managed deployment, trusted admins may create accounts and
reset any live user's password, including their own or another admin's (PRD §5.1).
The API returns the generated initial password in the creation/reset response with
`Cache-Control: no-store`, stores only a bcrypt hash, forces a password change, and
audits the mutation in the same transaction. Existing MFA enrollment is preserved.

Access and MFA challenge tokens include a required `credential_version` claim.
Each password change/reset (including CLI reset) increments the user version and
revokes refresh sessions atomically. The existing per-request identity lookup
checks that version, so no token denylist or extra database query is required.
Password mutation and session issuance serialize on the user row; refresh must
recheck session revocation after acquiring that lock. Existing unversioned JWTs
need refresh or login after deployment. Access-token expiry remains 15 minutes by
default. Requests already authorized before reset can finish.

This extends the token validity check beyond signature/expiry while retaining
backend-owned authentication and the existing session store. It adds no public
signup, invitation service, MFA recovery, or finer-grained administrator roles.

## Consequences

**Positive:**

- One identity store, one session model, one audit log. Cross-event correlation (login → chat → inference call → privilege flag) works without joining across services.
- Word add-in (M3), Slack/Teams bridge (M3), and any future surface all use the same auth endpoints — no parallel work.
- The OpenAPI surface that procurement-evaluators read matches what the backend actually does.

**Negative:**

- The OpenWebUI fork loses the rich built-in IdP integrations OpenWebUI ships out of the box. We re-implement OAuth, SAML, LDAP, SCIM in the backend.
- Rebasing the OpenWebUI fork (per [ADR 0001](0001-openwebui-fork-pin.md)) needs to re-confirm that auth-delegation glue still works after each rebase. This is part of the rebase PR test plan.
- The MFA implementation in M1 is TOTP-only. WebAuthn is deferred. Operators with WebAuthn-mandatory policies will need to wait or front the deployment with Authentik/Keycloak.

**Mitigations:**

- The OAuth/SAML/LDAP/SCIM surface in the backend is documented in the OpenAPI sketch (PRD decision-routing #2) so the implementation is anchored, not improvised.
- The OpenWebUI fork's auth-delegation glue is a small isolated module under `web/src/lib/lq-ai/auth/` (per ADR 0001's customization-organization principle), making it easy to verify after rebases.
- Operators with complex IdP needs can front the deployment with Authentik or Keycloak via reverse proxy — the backend trusts the proxy's authenticated headers (per the PRD §5.1 reverse-proxy recipe).

---

*Updates to PRD §5.1 reflect this decision; PRD v0.2 (May 2026) carries the updated text. The earlier "v1 uses OpenWebUI's built-in auth" language is preserved here in the Context section as the historical position so future maintainers can recover the reasoning.*
