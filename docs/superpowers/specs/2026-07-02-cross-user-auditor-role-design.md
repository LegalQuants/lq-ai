# Design — Cross-user auditor / compliance role

**Date:** 2026-07-02
**Owner:** Claude Code (driven), maintainer + **security** review (authz change)
**Origin:** Donna upstream request `Donna/docs/upstream-requests/lq-ai-cross-user-auditor-role.md`
**Branch:** `feat/cross-user-auditor-role`
**Status:** Approved design — ready for implementation plan
**⚠️ Security-gated:** touches authorization → auto-routed to security reviewers per `.github/CODEOWNERS`.

---

## 1. Problem

The citation ledger, fiduciary gate, and autonomous-session ledger are strictly **owner-scoped** — a cross-user read returns **404** (existence-safe), and there is **no admin bypass** on the ledger endpoints (unlike the receipts endpoints, which do bypass for `is_admin`). So a **reviewer-facing** audit — a supervising partner reviewing an associate's matter, or a compliance officer auditing a session — is impossible for any API consumer (Donna) to build: the backend returns no data for work the caller didn't author. This is a genuine backend authorization gap, not a UI gap.

This design adds a **read-only, deployment-wide `auditor` role** that (together with `admin`) may read another user's ledger/gate/session-ledger/receipts, with every such cross-user read audit-logged. Ordinary owner-scoping for `member`/`viewer` users is unchanged.

## 2. Goals / non-goals

**Goals**
- A new `auditor` value in the existing RBAC role enum, granted through the existing admin role API, read-only by construction.
- A unified **privileged-reader** set `{admin, auditor}` that may read any user's: chat ledger, message sources, autonomous-session ledger (+ the embedded fiduciary gate), and the chat-receipts read + export endpoints.
- Existence-safety preserved: a **non-privileged** non-owner still gets an indistinguishable 404 on the ledger endpoints.
- **Audit-the-auditor:** every privileged *cross-user* read writes an `audit_log` row.
- Fixes the asymmetry Donna flagged — `admin` gains ledger read parity with its existing receipts bypass.

**Non-goals (YAGNI / explicit honest boundaries)**
- **No cross-user listing/discovery.** An auditor reads a ledger/session **by known id** (Donna holds the id from its own UI). The list endpoints (`GET /chats`, `GET /autonomous/sessions`) stay owner-scoped. Cross-user discovery is deferred (would likely need the scoped model below).
- **No per-matter / per-org scoping.** There is no org/membership primitive today (`OrganizationProfile` is a singleton; `Team` is skill-sharing only; `Project`/`Chat`/`AutonomousSession` are single-owner with no membership table). A scoped auditor would require a new table — deferred as a future enhancement (file a DE) if/when multi-tenancy arrives.
- **No JWT/token change** — `role` is re-read from the DB row on every request (`get_current_user` at `dependencies.py:67`), so authorization is enforced purely server-side.
- **The signed-attestation export** (Donna's other request) is a separate sub-project; the reviewer variant there will compose on this role.
- **Not reconciling the 404-vs-403 convention.** The ledger endpoints 404 non-owners (existence-safe); receipts 403s them. This design does **not** change the non-privileged failure code on either — it only adds the privileged bypass. The inconsistency is noted as a future cleanup DE.

## 3. Current state (verified against code, 2026-07-02)

- **Role model:** `User.role` (`api/app/models/user.py:40`, default `member`), CHECK constraint `chk_users_role_enum` (`api/alembic/versions/0017_...py:56-58`, currently `role IN ('admin','member','viewer')`). `User.is_admin` (`user.py:35`) kept in sync by `admin.py` when role changes.
- **Enum + mutation gate:** `_ROLE_ENUM = {"admin","member","viewer"}` (`api/app/api/admin.py:655`); `_MUTATING_ROLES = {"admin","member"}` (`api/app/api/dependencies.py:191`) — `MutatingUser` 403s any role outside it (so `viewer` and, once added, `auditor` are read-only for free).
- **Granting:** `PATCH /api/v1/admin/users/{user_id}/role` (`admin.py:766-849`) validates against `_ROLE_ENUM`, sets `target.is_admin = body.role == "admin"`, refuses last-admin demotion, writes a `user.role_updated` audit row.
- **Owner-scoped read endpoints (the ones to change):**
  - `GET /chats/{id}/ledger` — `chats.py:1795` (handler `get_chat_ledger`), via `_load_visible_chat(db, cid, user.id, ...)` (`chats.py:328-352`, filters `Chat.owner_id == owner_id`, 404 on miss/cross-user).
  - `GET /chats/{id}/messages/{mid}/sources` — `chats.py:1741` (handler `get_message_sources`), same `_load_visible_chat`.
  - `GET /autonomous/sessions/{id}/ledger` — `autonomous.py:659` (handler `get_session_ledger`), via `_load_owned_session(db, session_id, user_id)` (`autonomous.py:241-273`, filters `AutonomousSession.user_id`, 404).
  - Fiduciary gate: no standalone route — embedded in the two ledger responses via `resolve_gates(...)` (`chats.py:1830`, `autonomous.py:704`); inherits the ledger endpoint's check.
- **Existing bypass (the asymmetry):** `chat_receipts.py:103` — `if chat.owner_id != user.id and not user.is_admin: raise Forbidden(...)` on `get_chat_receipts` and its `export` variant.
- **Audit infra:** `AuditLog` model (`api/app/models/audit.py:21-77`); `audit_action(...)` helper (`api/app/audit.py:112`, flushes but does **not** commit — rides caller's txn); closed-enum wrapper precedent `autonomous_audit()` (`api/app/autonomous/audit.py`). Note: `audit_action` is only ever called from **state-changing** paths today — logging reads is a new call pattern.

## 4. Design

### 4.1 Role addition
- Add `"auditor"` to `_ROLE_ENUM` (`admin.py:655`). `PATCH .../role` then accepts it with no further change; `is_admin` stays `False` for an auditor (`body.role == "admin"` is false).
- Migration **0065** (down_revision `0064`): drop and recreate `chk_users_role_enum` as `role IN ('admin','member','viewer','auditor')`. No data migration (existing rows satisfy the wider set). Downgrade recreates the 3-value constraint (safe only if no `auditor` rows exist — downgrade note in the migration).
- `_MUTATING_ROLES` is **unchanged** — `auditor ∉ {admin, member}` → `MutatingUser` 403s auditors on every mutating endpoint automatically. (Add a test asserting this; no code change.)

### 4.2 Privileged-reader predicate + reader helpers
- Add a single predicate, e.g. in `api/app/api/dependencies.py` (or a small `authz` helper module):
  ```python
  def is_privileged_reader(user: User) -> bool:
      return user.is_admin or user.role == "auditor"
  ```
- **Chat reads** — new helper `_load_chat_for_reader(db, chat_id, user) -> tuple[Chat, bool]`:
  - load `Chat` by id; if `None` → `NotFound` (404);
  - if `chat.owner_id == user.id` → `(chat, False)`  (owner, not privileged-cross-user);
  - elif `is_privileged_reader(user)` → `(chat, True)`  (privileged cross-user read);
  - else → `NotFound` (404).  ← preserves existence-safety for non-privileged non-owners.
  Use it in `get_chat_ledger` and `get_message_sources` in place of `_load_visible_chat`. The returned `bool` (`was_privileged`) drives the audit write.
- **Session reads** — mirror helper `_load_session_for_reader(db, session_id, user) -> tuple[AutonomousSession, bool]` with the same owner/privileged/404 branching; use in `get_session_ledger`.
- **Receipts** — extend the existing `chat_receipts.py:103` gate: the bypass condition becomes `is_privileged_reader(user)` instead of `user.is_admin` (so `auditor` joins `admin`). Keep its existing **403** for non-privileged non-owners (do not regress the receipts convention). Apply to both the read and the `export` variant. Compute `was_privileged = chat.owner_id != user.id and is_privileged_reader(user)` for the audit write.

### 4.3 Audit-the-auditor
- A closed-enum wrapper `auditor_audit(db, *, user, action, resource_type, resource_id, viewed_user_id)` (mirroring `autonomous_audit`) restricting `action` to a fixed set: `auditor.ledger_viewed`, `auditor.sources_viewed`, `auditor.session_ledger_viewed`, `auditor.receipts_viewed`, `auditor.receipts_exported`. It forwards to `audit_action` with `details={"viewed_user_id": <owner id>}` and the resource id.
- Called **only when `was_privileged` is true** (owner-reading-own is not logged).
- **Read-path commit:** these are GET handlers where the request session is not otherwise committed. After the `auditor_audit` write, the handler must **explicitly `await db.commit()`** (a small, dedicated commit for the audit row) so the audit record persists. This is the one deliberate departure from the "state-changing calls only" convention and from the "rides the caller's txn" default — called out here so the implementer commits intentionally. (The successful read response is unaffected by the audit commit.)

### 4.4 Failure-mode matrix (the contract)
| Caller vs resource | Ledger / sources / session-ledger | Receipts (read + export) |
|---|---|---|
| Owner | 200 (no audit row) | 200 (no audit row) |
| `admin` or `auditor`, not owner | **200 + audit row** | **200 + audit row** |
| `member`/`viewer`, not owner | **404** (existence-safe, unchanged) | **403** (unchanged) |
| Nonexistent id | 404 | 404 (read) / existing behavior |
| Any non-`{admin,member}` role on a mutating endpoint | 403 (MutatingUser, unchanged) | 403 |

## 5. Testing

- **Ledger/sources/session-ledger:** extend the existing cross-user tests (`api/tests/integration/test_ledger_endpoint.py:113`, `api/tests/autonomous/test_session_ledger_endpoint.py:162`) to a triad: non-privileged non-owner → 404; `auditor` → 200; `admin` → 200. Assert an `audit_log` row is written with the right action + `viewed_user_id` for the privileged reads, and **not** written for owner reads.
- **Add the missing test:** `GET /chats/{id}/messages/{mid}/sources` has **no** cross-user ownership test today (`test_message_tool_sources.py` only covers unknown-id 404) — add the triad there.
- **Receipts:** extend `api/tests/test_chat_receipts.py` — `auditor` joins `admin` in the bypass (200 + audit row); non-privileged still 403; export variant likewise.
- **Role plumbing:** extend `api/tests/test_wave_c.py` — `PATCH .../role` accepts `auditor` (200, `is_admin` stays False, audit row); an `auditor` is 403'd on a representative mutating endpoint (MutatingUser).
- **Migration:** verified on a throwaway `pgvector/pgvector:pg16` container (conftest auto-migrates); the constraint accepts `auditor` and still rejects a bogus role.
- Coverage: no decrease (CI-enforced). Run `ruff format` + `ruff check` + `mypy` (api standard).

## 6. Dev-environment & delivery rules

- **NEVER host-side `alembic upgrade` against the live dev DB** — verify 0065 on a throwaway pgvector container; apply to the dev stack by rebuilding `api` + `arq-worker` + `ingest-worker` **together** (revision-mismatch crash-loops otherwise). Never `docker compose down -v`.
- No new routes → the `IMPLEMENTED_ROUTES` / `EXPECTED_PATHS` path-count guards are unaffected and must not be touched. The **admin role-enum** in the OpenAPI sketch (`docs/api/backend-openapi.yaml`) and any enumerated role schema must add `auditor`; run `test_openapi.py` as the authoritative check.
- **Security-gated** — the PR auto-routes to security reviewers; do not self-merge past that gate.
- On merge: reply to Donna's request doc with the **contract** (role name `auditor`; granted via `PATCH /api/v1/admin/users/{id}/role`; endpoint behavior per the §4.4 matrix; access audit-logged) + the **squash SHA**, and add a note to the lq-ai integration doc.

## 7. Risks / open items

- **Read-path audit commit** (§4.3) is the main novelty — an un-committed audit write would silently lose the "who viewed whose trail" record. The plan makes the explicit commit a required, tested step (assert the row persists after the read).
- **Downgrade of migration 0065** fails if `auditor` rows exist — documented in the migration; acceptable (forward-only in practice).
- **`viewer` vs `auditor` semantics:** `viewer` = read-own-only; `auditor` = read-any (cross-user). Both are non-mutating. The spec keeps them distinct roles (an auditor is not merely a viewer) — no attempt to merge them.
- **Existence-safety at the seam:** the privileged branch returns 200 for a cross-user read, but the non-privileged branch must remain a bare 404 (no timing/side-channel that distinguishes "exists, not yours" from "doesn't exist"). The reader helpers load-then-branch, so a non-privileged caller's path is identical for both cases.
