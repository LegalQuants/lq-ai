# Internal workspace-event foundation

Implements the first backend slice of the proposal in
[ADR PR #677](https://github.com/LegalQuants/lq-ai/pull/677), tracking
[issue #256](https://github.com/LegalQuants/lq-ai/issues/256) and PRD DE-201.
The foundation is **inactive**: no producer, ingestion job, public endpoint or Today page calls it.
This is not completion of DE-201, DE-208 or the wider M5 roadmap.

## Deployment and database ownership

Events use the API's existing SQLAlchemy session and operator-configured `DATABASE_URL`.
They stay in that installation's existing Postgres database; this change provisions no hosted
service, shared cross-firm database, account, new connection pool or provider SDK. The existing
Postgres/pgvector deployment requirements still apply. There are no new dependencies.

Firms can operate separate LQAI deployments under the current deployment model. Support for other
database engines, per-firm database routing or other enterprise platforms is a separate future
architecture decision, not a compatibility promise made by this change.

## Small, closed contract

Migration `0079` adds `workspace_events`; the ORM model is `app.models.WorkspaceEvent`.
`app.schemas.workspace_events` defines internal service contracts, not client-writable API schemas.

- Server-owned identity, owner, observation time, status and creation/update timestamps.
- Optional project association, verified through the central matter-access resolver.
- `source_kind="internal"`, an opaque UUID `source_ref`, and `event_type="finding.created"`.
- Source occurrence time, falling back to the initial observation time if unavailable.
- Fixed provenance `{"producer": "autonomous"}`; arbitrary metadata is rejected.
- Sensitivity `confidential` or `privileged`; privileged projects cannot be downgraded by input.
- Stable SHA-256 identity digest and database uniqueness on
  `(user_id, source_kind, source_ref, event_type)`.

Only `recorded` status exists. There is no dismissal, approval or execution operation.
There are no bodies, titles, subjects, addresses, URLs, attachments or raw tool payload columns.
Pydantic contracts reject additional fields; database constraints enforce the bounded vocabulary
and provenance. Adding a source/type requires an explicitly reviewed contract/migration change.

Source identity, not content, is deduplicated. Distinct source UUIDs remain distinct events even
if their source text is identical. A replay returns the original event and does not update its
timestamps or create another audit row. A replay cannot silently rebind a project or sensitivity.

## Service and transaction boundary

`app.workspace_events.service` provides:

- `record_event(db, user_id=..., event=...)`: persist validated metadata plus its payload-free
  `workspace_event.record` audit. `ON CONFLICT DO NOTHING` handles concurrent retries.
- `list_events(db, user_id=..., query=...)`: owner-scoped metadata queries with live matter access.
  Source/type/project filters are optional. Time windows are half-open `[start_at, end_at)`;
  all supplied times must be timezone-aware. Stored occurrence/observation times are UTC.
- `remove_source_events(db, user_id=..., source=...)`: idempotent owner-scoped removal plus one
  payload-free `workspace_event.remove_source` audit when rows are actually removed.

Mutations use savepoints and the existing audit writer, but **never commit the caller's
transaction**. A failed audit rolls back the associated event mutation. A caller integrating
source writes/removal must propagate failures and commit source, event and audit together.

Queries use ascending `(occurred_at, id)` order and a matching owner/time index. The cursor carries
both values, and remains inside the requested owner's scope. Limits are 1–200, default 50; no
unbounded OFFSET interface is exposed. This is stable keyset ordering, not a snapshot: a later
arrival with an earlier occurrence time requires refetching the relevant time window.

## Authorization and lifecycle gates before enabling a producer

The owner must be server-derived, not copied from model/client input. The service checks that the
owner exists and is not soft-deleted. Project writes call the existing `require_matter` resolver,
which refreshes current policy; list queries use its `matter_scope_filter` counterpart. Explicit
ethical screens override ownership, membership, organization sharing and administrator status.
Shared-matter access never grants access to another user's private event rows. Missing, inaccessible
or archived projects fail closed; no parallel matter-authorization rules are introduced.

An opaque `source_ref` is deliberately not a polymorphic foreign key. This generic foundation does
**not** validate that a finding exists or that the caller can access it. Before introducing the
first real producer, the next PR must:

1. Resolve the actual source through its existing authorization rules; derive owner/project and
   source identity from that record, not model-supplied claims.
2. Map source creation/removal and events/audits into one local transaction, including source
   deletion hooks using `remove_source_events` (or an equally tested database lifecycle link).
3. Recheck source visibility before any Today projection exposes a reference, link or source text.
4. Prove that deletion, revocation, replay and source/project changes do not expose stale content.

Until that slice is reviewed, do not enable producers or expose this metadata service as an HTTP
API. The stored sensitivity is an observation-time label, not an authorization or inference grant.

Account hard-deletion cascades to events. Project hard-deletion also cascades; archived or
no-longer-accessible projects hide events from ordinary queries. Existing audits retain their normal
payload-free, anonymized-user lifecycle. `workspace_events.json` is included in the owner's
existing personal-data export, including their retained metadata for archived projects. The existing
export-level ethical-screen reconciliation gate remains in effect; it is not bypassed by events.

No new time-based retention policy or automatic source cleanup job is introduced. Metadata is
retained until explicit source cleanup, project deletion or account deletion. Producer-specific
retention and lifecycle rules must be reviewed before that source is enabled; email fields and
email retention are still out of scope.

## Verification and safe rollout

Tests live in `api/tests/test_workspace_events.py` and
`api/tests/test_workspace_events_migration.py`. They cover closed contracts, real Postgres
constraints, owner/project isolation, chronological queries, duplicate/concurrent retries,
transaction/audit failure, source removal, export, account/project deletion and migration cycling.
These are foundation tests, not proof of a Today page or a running producer.

Run database checks only on disposable Postgres/pgvector. Never run host Alembic against the live
development database or delete existing Compose volumes. The new table is additive and has no
existing readers/writers. Follow the repository's migration process and rebuild the API,
arq-worker and ingest-worker together when applying it to a running stack.

Normal rollback retains the new table/data and disables new callers. `downgrade()` drops only
this table and indexes: it is suitable for disposable verification, but destroys event metadata
and requires explicit data-handling approval on a real installation.

Later PRs separately add one internal producer, `/api/v1/today`, then `/lq-ai/today`. No email,
connector, ranking, background triage or mailbox mutation is implemented here.
