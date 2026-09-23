# Audit Logging

> **Scope:** what LQ.AI records to the audit log, retention, and integrity protection. Operators evaluating procurement responses often need this in writing; this is the operational reference for the `audit_log` table.

## What is logged

Each audit event is a row in the `audit_log` table (see [docs/db-schema.md §audit_log](../db-schema.md) for the schema). Columns:

- `id` — UUID primary key, defaulted by `gen_random_uuid()` (random UUIDv4; **not** time-ordered). Do not infer chronology from the primary key: order by `timestamp`, adding `id` as a stable tie-breaker for repeatable display — a tie-breaker gives a deterministic order but does not reconstruct true event order when timestamps tie.
- `timestamp` — `TIMESTAMPTZ`, server-clock; default `now()` at insert.
- `user_id` — actor; FK to `users.id` with `ON DELETE SET NULL` so user deletion preserves the row but anonymises the actor.
- `action` — verb-form event string (e.g. `chat.message_sent`, `kb.created`); the canonical event-type field.
- `resource_type` — noun the action was performed on (e.g. `chat`, `project`, `skill`).
- `resource_id` — stringified identifier of the affected resource, typically a UUID; nullable for actions with no concrete subject.
- `privilege_marked` — `BOOLEAN`, true when the action affects a project flagged privileged; first-class column (not buried in `details`) so operator queries do not require JSONB scans.
- `privilege_basis` — short human-readable handle for why the row is privileged (e.g. `project:<name>`); the DB enforces `privilege_marked → privilege_basis IS NOT NULL` via `chk_audit_log_privileged_with_basis`.
- `routed_inference_tier` — `SMALLINT 1..5` when the action touched inference routing; null otherwise.
- `routed_provider` — the provider the gateway selected for the routed call (e.g. `anthropic`, `openai`); null when the action did not route inference.
- `ip_address` — `INET`; the client address attached to the originating request.
- `user_agent` — request `User-Agent` header.
- `request_id` — correlation id from `X-Request-ID`; cross-references gateway logs and structured app logs.
- `details` — JSONB payload for action-specific fields (e.g. `{"name": "...", "privileged": true}`); queryable but not indexed by default.

Logged events (verified against `action=` literals emitted by `api/app/`; the list below is the M1 baseline plus the later additions called out inline and is not exhaustive — later milestones add further families such as the M4 `autonomous_session.*` events, so run `grep -rn 'action="' api/app` for the current full set):

- **Authentication & session:** `user.login`, `user.login_failed`, `user.login_mfa_challenged`, `user.logout`, `user.session_refreshed`, `user.session_refresh_failed`.
- **MFA lifecycle:** `user.mfa_setup_initiated`, `user.mfa_enabled`, `user.mfa_enable_failed`, `user.mfa_disabled`, `user.mfa_disable_failed`, `user.mfa_verify_failed`.
- **Password & credentials:** `user.password_changed`, `user.password_change_failed`.
- **Account lifecycle:** `user.role_updated`, `user.preferences_updated`, `user.deletion_scheduled`, `user.deletion_cancelled`, `user.export_requested`.
- **Project:** `project.knowledge_base_attached`, `project.knowledge_base_detached`. Project creation itself is **not** audited: the create handler commits the row and writes a structured service log line (`event=project_created`) but does not call `audit_action()`; `project.create` appears only as the docstring example in `api/app/audit.py`.
- **Chat:** `chat.message_sent`.
- **Skills (user-scoped):** `user_skill.created`, `user_skill.updated`, `user_skill.deleted`.
- **Files:** `file.uploaded`, `file.deleted`.
- **Knowledge base:** `kb.created`, `kb.updated`, `kb.deleted`, `kb.file_attached`, `kb.file_detached`.
- **Saved prompts:** `saved_prompt.create`, `saved_prompt.update`, `saved_prompt.delete`.
- **Teams:** `team.created`, `team.updated`, `team.deleted`, `team.member_added`, `team.member_removed`, `team.member_role_changed`.
- **Admin / organization:** `organization_profile.updated`, `tier_policy.updated`.
- **Privileged cross-user reads ("audit the auditor"):** `auditor.ledger_viewed`, `auditor.sources_viewed`, `auditor.citations_viewed`, `auditor.session_ledger_viewed`, `auditor.receipts_viewed`, `auditor.receipts_exported` — written when an admin/auditor reads another user's data; `details.viewed_user_id` records whose data was read.

All writes go through one helper — `app.audit.audit_action()` in [api/app/audit.py](../../api/app/audit.py) — so every row populates `privilege_marked` / `privilege_basis` consistently and captures `ip_address` / `user_agent` / `request_id` uniformly when a `Request` is available. The `auditor.*` rows go through the closed-enum wrapper `app.auditor_audit.auditor_audit()`, which calls the same helper.

## What is NOT logged

- **Plaintext message content.** `chat.message_sent` records the chat and message ids in `details`, not the message body. Inference-routing has its own table (`inference_routing_log`) with provider, model, token counts and latency — also without message content, per PRD §4.
- **Provider API responses.** Same reasoning; the gateway records routing metadata only.
- **Cryptographic material.** `JWT_SECRET`, master keys, the field-level encryption keys, and provider API keys are never logged — see [encrypted-keys.md](encrypted-keys.md) for the key-handling contract.
- **Ordinary read traffic.** M1 audits state-changing actions (PRD §5.3); a user reading their own data is not audited. The exception is privileged cross-user reads: when an admin/auditor reads another user's ledger, sources, citations, session ledger or receipts, the handler writes an `auditor.*` row (listed above) and commits it explicitly. Inference routing decisions land in `inference_routing_log` regardless.

## Retention

- **Default retention:** audit rows are never automatically deleted at M1. Operators with regulatory retention requirements (e.g. SOC 2 expects ≥1 year; some jurisdictions require longer) can rely on the default-retain posture.
- **User deletion behaviour:** when a user is deleted, the FK `audit_log.user_id` is `ON DELETE SET NULL`, so the audit row persists but the actor reference is anonymised. The state-change history remains queryable by `resource_type` / `resource_id` / `details`. The user-data export worker (`api/app/workers/user_export.py`) includes the rows where the user is the actor in their export under `audit_log.json`, but export and deletion are separate jobs: `POST /users/me/export` queues an export, `POST /users/me/delete` schedules deletion after the grace period, and the deletion worker (`api/app/workers/user_deletion.py`) neither triggers nor waits for an export — it also deletes any stored export bundles for that user. There is no guarantee that a deletion is preceded by a completed export; a user who wants their audit rows must request and download the export before the scheduled deletion runs.
- **Operator-controlled archival:** operators can `pg_dump --table=audit_log` to long-term storage on a schedule of their choosing. No first-class export workflow in M1; we may add one if operator demand surfaces.
- **Manual purge:** operators with privacy-driven purge requirements (e.g. GDPR right-to-erasure) can DELETE specific rows by `user_id` directly. A future enhancement may add a `redact_user(user_id)` CLI command that NULLs the actor and PII-bearing `details` fields per user (tracked as a deferred enhancement; file via operator request — see PRD §9).

## Integrity protection

- **Application-layer:** the api process is the sole writer. `audit_action()` flushes the audit row inside the caller's transaction but does **not** commit; the handler commits both the state change and the audit row in one boundary. An audited event is therefore either both present in the audit log and reflected in the underlying tables, or neither — there is no audit-row-without-state-change failure mode. The converse holds only for handlers that call `audit_action()`: a state change made by a handler that does not call it leaves no audit row at all, so coverage is per handler, not a property of the helper. The known case is the provider-key proxy — `POST`/`PATCH`/`DELETE /api/v1/admin/provider-keys` in `api/app/api/admin.py` — which forwards the change to the gateway; the gateway persists it to `gateway.yaml` outside any api database transaction, and the handler never calls `audit_action()`, unlike the tool-provider proxy beside it (`/api/v1/admin/tool-providers`), which does. Before relying on the log for complete coverage of a given kind of change, check that its handler calls `audit_action()`.
- **Append-only at the application layer:** no application code path issues `UPDATE` or `DELETE` against `audit_log`. The database does not enforce append-only directly; operators with stricter requirements can add a trigger that rejects updates and deletes (the schema comment in `docs/db-schema.md` flags this).
- **Database-layer:** Postgres WAL provides crash-consistency. Operators with stricter durability requirements run Postgres with `synchronous_commit=on` (the default in our chart).
- **Tamper detection (not in M1):** chained hashes (each row commits a hash over `(prev_hash, current_row)`) would let operators detect after-the-fact tampering. Not in M1; tracked as a deferred enhancement (file via operator request — see PRD §9). Operators needing this today can use Postgres logical replication to a write-once destination.

> [!CAUTION]
> **Silent failure** — Append-only is enforced by the application, not by the database: no api code path issues `UPDATE` or `DELETE` against `audit_log`, but Postgres does not reject one issued outside the application (a direct database session, a misconfigured migration, an operator with superuser access). Absent the optional trigger above or the tamper-detection mitigations planned for a later milestone, a row altered directly in the database leaves no signal — the WAL and crash-consistency guarantees above protect against crashes, not against a privileged actor editing the table directly.

This is the structural answer to a question a closed-source SaaS product cannot give you: you can evidence, to your client or your regulator, every occasion on which their material was sent to a model provider — not as an assertion, but as a query you run yourself against your own database.

## Matter-scoped evidence for a specific model call or citation

The workflows above answer "what happened to a given user or privileged resource." A narrower
question — "what did the assistant read and verify for this specific matter" — is answered by two
tables that are not part of `audit_log` itself: `citation_ledger_entry`, indexed on `project_id`
(one row per turn per source the assistant actually read, referencing exactly one of a KB-document
citation, a case-law citation, or a tool-retrieved source, and holding no content of its own — a
metadata index only, see [docs/db-schema.md](../db-schema.md)); and `inference_routing_log`, which
records the provider, model, and routed tier for every inference call and carries a `chat_id`.

```sql
-- Every source the assistant read and verified for one matter
SELECT chat_id, message_id, source_kind, verification_status, confidence, provider, retrieved_at
FROM citation_ledger_entry
WHERE project_id = '<matter-uuid>'
ORDER BY created_at;

-- Every model call made inside that matter's chats
SELECT r.timestamp, r.routed_provider, r.routed_model, r.routed_inference_tier, r.anonymization_applied
FROM inference_routing_log r
JOIN chats c ON c.id = r.chat_id
WHERE c.project_id = '<matter-uuid>'
ORDER BY r.timestamp;
```

Neither query returns the content of what was read or said — `citation_ledger_entry` is metadata
only, and `inference_routing_log` never carries message bodies — but together they produce a
matter-scoped record of every model call and every citation verification an insurer's inquiry, a
malpractice review, or an internal audit would ask for, without reconstructing it by hand.

## Operator workflows

### Investigating an incident

Pattern: pull all events for a given actor in a time window.

```sql
SELECT timestamp, action, resource_type, resource_id, privilege_marked, details
FROM audit_log
WHERE user_id = '<uuid>'
  AND timestamp BETWEEN '<from>' AND '<to>'
ORDER BY timestamp DESC;
```

To narrow to privileged-resource activity:

```sql
SELECT timestamp, user_id, action, resource_type, resource_id, privilege_basis
FROM audit_log
WHERE privilege_marked = TRUE
  AND timestamp BETWEEN '<from>' AND '<to>'
ORDER BY timestamp DESC;
```

Both queries are supported by indexes (`idx_audit_log_user_timestamp`, `idx_audit_log_privileged`).

### Long-term archival

```bash
# Weekly archive
pg_dump -d lq_ai --table=audit_log --data-only --column-inserts \
  > audit-log-$(date +%Y-%m-%d).sql
```

### Compliance attestation

Operators answering "do you maintain an audit log of administrative actions" can reference this doc plus the `audit_log` table schema in `docs/db-schema.md`. The Compliance Alignment Pack at `docs/compliance/` (separate cycle) maps specific audit events to specific SOC 2 / ISO 27001 controls.

## Cross-references

- [docs/db-schema.md](../db-schema.md) §audit_log — schema definition.
- [docs/PRD.md](../PRD.md) §5.3 — design intent (cross-cutting audit requirement).
- [docs/security/threat-model.md](threat-model.md) — Repudiation coverage.
- [api/app/audit.py](../../api/app/audit.py) — the single audit-write helper.
