# ADR 0005 — File-storage soft-delete and MinIO key scheme

**Status:** Accepted
**Date:** 2026-05-08
**Owners:** Kevin Keller (LegalQuants)
**Context:** Task C4 — File upload + storage

---

## Context

Task C4 wires `POST /api/v1/files`, `GET /api/v1/files/{id}` (metadata),
`GET /api/v1/files/{id}/content` (download), and `DELETE /api/v1/files/{id}`
into the running stack: a streaming upload to MinIO, metadata persisted in
the new `files` table, content-addressable identity via SHA-256, and an
`ingestion_status: pending` marker for the document pipeline (C5) to pick
up.

Two architectural questions had to be resolved before C4 could land:

1. **Delete semantics.** Should the user-facing DELETE be a hard-delete
   (drop the row, drop the MinIO object) or a soft-delete (set
   `deleted_at`, leave the bytes alone for now)?
2. **MinIO key scheme.** Three plausible shapes: `<file_id>`,
   `<owner_id>/<file_id>`, or `<file_id>/<filename>`. Each makes
   different trade-offs around access scoping, debuggability, and
   multitenancy.

The PRD §3.5 doesn't pre-empt either question; `docs/db-schema.md`
implicitly answers (1) by listing `files.deleted_at`. CLAUDE.md's hard
rule says: when an architectural choice surfaces and isn't anchored in
existing docs, document the call rather than make it implicitly.

## Decision

### 1. Soft-delete by default; hard-delete is a separate admin action.

`DELETE /api/v1/files/{id}` flips `files.deleted_at` from NULL to `now()`
and **leaves the MinIO object in place**. A subsequent `GET /api/v1/files/{id}`
returns 404 (not 410) because the file is no longer accessible to the user.
The MinIO object is reaped later by:

- D6's per-user export+delete (the GDPR Article 17 path), which walks the
  user's still-soft-deleted files and hard-deletes them along with the
  rest of the user's data, OR
- A future operator-facing admin tool / cron job that hard-deletes rows
  past a configurable retention window (out of scope for M1; tracked as a
  deferred enhancement in PRD §9 — DE-XXX).

#### Why soft-delete

- **Audit log integrity.** `audit_log` rows reference `resource_id`
  (file UUIDs) as text. Hard-deleting the file row breaks the audit
  trail's ability to answer "what file did user X delete on 2026-05-08
  at 14:32?" with anything more than a UUID. Soft-delete keeps the
  filename and metadata queryable for that lookup.
- **Document-pipeline race.** C5 is going to pick up files in
  `ingestion_status='pending'` and process them asynchronously. A
  hard-delete during ingestion would surface as a confusing
  ObjectNotFound mid-pipeline; soft-delete lets the pipeline finish or
  cleanly abandon the work via a `deleted_at IS NOT NULL` check.
- **`document_chunks` FK cascade.** `documents.file_id` has
  `ON DELETE CASCADE`; hard-deleting a file would cascade-delete every
  chunk and every embedding for that document. If the user
  accidentally deletes a file (the kind of accident M1 should make
  recoverable), undoing the cascade requires re-uploading and
  re-running the entire pipeline. Soft-delete makes recovery a
  single-row UPDATE.
- **Consistent with `users.deleted_at` and `users.deletion_scheduled_at`.**
  The user model already follows this pattern (PRD §5.3); applying it
  to files keeps the deletion semantics uniform.

#### Why not soft-delete the MinIO object too

The MinIO object is the *source of truth* for the bytes. Soft-deletion
on the row is sufficient for "user can't see this file anymore"; the
bytes are already protected by the row-level access check (every
content read goes through the `files` table first). Garbage collection
runs less often than visibility flips; collapsing both into one
operation is over-coupling.

### 2. MinIO key scheme: `<file_id>` (the bare UUID).

The MinIO `storage_path` for an uploaded file is the file's UUID with no
prefix or suffix:

```
<bucket>/<file_id>
e.g. lq-ai-files/0193e8a4-3f10-7891-b234-1234567890ab
```

#### Why bare UUID

- **No information leakage.** A path like `<owner_id>/<file_id>`
  embeds an internal user identifier into the storage layer. Any
  operator who reaches a MinIO console with read access can enumerate
  filenames per-user — not a security boundary, but adjacent enough
  to PII that flat is preferable.
- **No filename in the key.** A path like `<file_id>/<filename>` adds
  a filename that we don't read back from MinIO at all (the filename
  is in the `files.filename` column). Putting it in the key adds noise
  and gives operators a misleading sense that the key is meaningful.
- **Multitenancy is application-level, not key-level.** The
  `files.owner_id` column plus the per-handler `WHERE owner_id =
  current_user.id` filter is the access boundary. The MinIO key
  scheme should not be a parallel access boundary — operators who
  need cross-user access (D6 export, abuse handling) must go through
  the application layer that re-applies the access check.
- **UUID v4 collision space is sufficient.** The chance of a collision
  on a flat namespace is the same as on a hierarchical one
  (collisions are governed by the UUID, not the prefix). UUID v4
  collision probability is computationally negligible at our scale.

The `storage_path` column on `files` is still typed as TEXT (not UUID)
so a future migration can layer prefixes (e.g., `tenants/<tenant_id>/<file_id>`)
without an ALTER on the file_id column type. Today we write the file_id
unmodified; tomorrow we can layer scoping in front of it.

## Consequences

### Positive

- DELETE is reversible. The audit log retains useful resource_id/filename
  lookups for at least the soft-delete window.
- The document pipeline (C5) does not have to handle "file row vanished
  mid-ingestion" — only "file marked deleted; abandon work."
- The MinIO key scheme is simple and operator-readable: `<UUID>` is
  immediately recognizable as a file identifier.

### Negative

- Soft-deleted files continue to consume MinIO bytes until D6 or a
  future GC sweep reaps them. Operators who care about storage cost
  before D6 ships need a manual cleanup tool (deferred to PRD §9 as
  DE-XXX).
- A user who soft-deletes a file expecting "the bytes are gone now"
  is wrong until D6 hard-deletes them. **The PRD's §1.8 Security
  Posture commits to "user-controlled deletion"**; we keep the
  contract by making D6 (per-user export+delete) the load-bearing
  hard-delete path. C4 is the *visibility* delete; D6 is the
  *bytes* delete. Both are user-controlled.

### Neutral

- We could add a `forceful=true` query parameter to `DELETE` later that
  performs both row-soft-delete AND immediate object-delete. The
  current shape doesn't preclude it; it's just not in C4.

## Alternatives considered

### Hard-delete

Drop the row; delete the MinIO object. Rejected for the audit-trail
and document-pipeline reasons above. The simplicity isn't worth the
loss of recovery and lookup affordances.

### Soft-delete with grace-period auto-hard-delete

A scheduled job hard-deletes rows where `deleted_at < now() - interval`.
Considered but deferred: M1 doesn't have a scheduled-job framework, and
adding one to land C4 is gold-plating. The right place to introduce a
scheduler is when D6 lands or when a clear second use-case shows up.

### `<owner_id>/<file_id>` key scheme

Considered for "operators can ls per-user." Rejected because:
- The application layer is the canonical owner-scoping mechanism.
- Operators who need cross-user inventory have psql + the `files`
  table with proper joins, which is more useful than ls-ing MinIO.

### `<file_id>/<original_filename>` key scheme

Considered for "operators see filenames in MinIO." Rejected because:
- Filenames can collide; UUIDs don't.
- The filename is already in the `files.filename` column.
- MinIO operators rarely need to inspect storage by filename; they
  need it by file_id (which they already have from the audit log).

## Companion artifacts

- `api/alembic/versions/0003_create_files_table.py` — migration.
- `api/app/models/file.py` — ORM model.
- `api/app/storage.py` — streaming upload/download/delete helpers.
- `api/app/api/files.py` — handlers.
- `docs/db-schema.md` — already documents `files.deleted_at`; this
  ADR is the rationale for using it the way C4 does.

## Revisions

- **2026-09-21 — ADR 0036 operationalisation.** The bundled implementation is
  now RustFS rather than MinIO. This ADR's key scheme, soft-delete semantics,
  and S3 contract are unchanged; occurrences of “MinIO” above describe the
  original implementation and should be read as “the S3-compatible object
  store.” The historical `miniodata` volume key remains through 0.x so an
  upgrade cannot silently attach an empty volume.
