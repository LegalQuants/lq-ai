# LQ.AI — Canonical Database Schema

> **Purpose:** Single source of truth for the LQ.AI PostgreSQL schema. Every table, column, foreign key, and index lands here. When a feature requires a schema change, this document is updated in the same PR as the Alembic migration that implements it. Drift between this document and the migrations indicates a process failure.

The schema runs on PostgreSQL 16 with the `pgvector` extension for vector storage and `pg_trgm` for fuzzy text matching. The full-text search uses Postgres' built-in `tsvector` rather than an external service.

This document is structured by subsystem; tables that span subsystems (audit log, inference routing log) have their own section.

---

## Conventions

- **Primary keys:** all tables use UUID v7 (`uuid_generate_v7()`) as primary keys for time-ordered insertion. Where v7 is unavailable, v4 is acceptable.
- **Timestamps:** `TIMESTAMPTZ` (with timezone). `created_at` and `updated_at` are required on every entity table; `updated_at` is set by trigger on UPDATE.
- **Soft deletes:** entities that should retain history use `deleted_at TIMESTAMPTZ NULL`. Hard deletes are reserved for GDPR Article 17 requests after the grace period.
- **Foreign keys:** named explicitly (`fk_<source_table>_<column>`); ON DELETE behavior specified.
- **Indexes:** named explicitly (`idx_<table>_<columns>`); composite indexes ordered by selectivity.
- **JSONB vs. dedicated tables:** dedicated tables for any field queried by index; JSONB for opaque payloads (audit details, skill examples on disk).
- **Naming:** snake_case for all identifiers; pluralized table names; singular column names.

---

## Core entity tables

### `users`

```sql
CREATE TABLE users (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    email                 CITEXT NOT NULL UNIQUE,
    display_name          TEXT,
    hashed_password       TEXT NOT NULL,
    is_admin              BOOLEAN NOT NULL DEFAULT FALSE,
    role                  TEXT NOT NULL DEFAULT 'member',       -- PRD §5.2 RBAC; CHECK (role IN ('admin','member','viewer'))
    mfa_enabled           BOOLEAN NOT NULL DEFAULT FALSE,
    must_change_password  BOOLEAN NOT NULL DEFAULT FALSE,  -- B2: first-run admin + reset-admin
    totp_secret           TEXT,
    recovery_codes        TEXT[],  -- bcrypt-hashed
    -- PRD §3.2 Wave A — Enhance Prompt reasoning visibility
    reasoning_visibility  TEXT NOT NULL DEFAULT 'disclosure',  -- CHECK (reasoning_visibility IN ('always_show','disclosure','on_request'))
    -- PRD §3.2.1 Wave B v2 — personalization preferences (frontend spec §4.3)
    featured_tools        TEXT NOT NULL DEFAULT 'prominent',   -- CHECK (featured_tools IN ('prominent','inline'))
    workspace_layout      TEXT NOT NULL DEFAULT 'three_pane',  -- CHECK (workspace_layout IN ('three_pane','two_pane','one_pane'))
    trust_pills           TEXT NOT NULL DEFAULT 'labels',      -- CHECK (trust_pills IN ('labels','dots'))
    provenance_pills      TEXT NOT NULL DEFAULT 'always',      -- CHECK (provenance_pills IN ('always','collapsed'))
    -- M4-C2 (migration 0044) — Autonomous Layer per-user opt-in; off by default.
    autonomous_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at         TIMESTAMPTZ,
    deleted_at            TIMESTAMPTZ,
    deletion_scheduled_at TIMESTAMPTZ
);

CREATE INDEX idx_users_email_active ON users(email) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_deletion_scheduled ON users(deletion_scheduled_at) WHERE deletion_scheduled_at IS NOT NULL;
```

**Column notes.**

| Column | Migration | Notes |
|---|---|---|
| `role` | 0017 | Three-role RBAC per PRD §5.2 (`admin`, `member`, `viewer`). Kept in sync with `is_admin` (role=`admin` iff `is_admin=true`). |
| `reasoning_visibility` | 0015 | Enhance Prompt reasoning display mode (§3.2). Default `disclosure` = collapsed behind toggle. |
| `featured_tools` | 0019 | Dashboard tool surfacing: `prominent` (cards) vs. `inline` (toolbar only). |
| `workspace_layout` | 0019 | Matter workspace pane count for Wave C: `three_pane`, `two_pane`, `one_pane`. |
| `trust_pills` | 0019 | Ambient trust label format: `labels` (full text) vs. `dots` (minimal). |
| `provenance_pills` | 0019 | Per-message skill/tier/provider pill row: `always` visible vs. `collapsed`. |
| `autonomous_enabled` | 0044 | M4-C2 Autonomous Layer opt-in. `FALSE` by default; the autonomous executor and trigger surfaces are inert for a user until they flip this on. |

`must_change_password` is set to TRUE for:
- the auto-created first-run admin (Task B2 / migration `0002`),
- any user touched by `python -m app.cli reset-admin-password`.

Authenticated endpoints (other than `GET /users/me`, `POST /auth/logout`, and `POST /auth/change-password`) return HTTP 403 with `error.code = "password_change_required"` while this flag is true. The flag is cleared by a successful `POST /auth/change-password`.

### `user_sessions`

Refresh tokens, hashed; access tokens are stateless JWTs.

```sql
CREATE TABLE user_sessions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_token_hash  TEXT NOT NULL,
    user_agent          TEXT,
    ip_address          INET,
    expires_at          TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at          TIMESTAMPTZ
);

CREATE INDEX idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_token_hash ON user_sessions(refresh_token_hash) WHERE revoked_at IS NULL;
CREATE INDEX idx_user_sessions_expires ON user_sessions(expires_at);
```

### `user_export_jobs`

Per-user GDPR Article 20 export job, tracked from queued → processing →
completed/failed. The actual ZIP bytes live in MinIO under
`storage_key`; the table itself is a job-state ledger that
`POST /users/me/export` writes to and the worker mutates.

```sql
CREATE TABLE user_export_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    storage_key     TEXT,
    error_message   TEXT,
    expires_at      TIMESTAMPTZ
);

CREATE INDEX idx_user_export_jobs_user_created ON user_export_jobs (user_id, created_at DESC);
CREATE INDEX idx_user_export_jobs_expires ON user_export_jobs (expires_at) WHERE storage_key IS NOT NULL;
```

`expires_at` is set to `now() + 7 days` when the worker completes; an
hourly GC cron clears `storage_key` (and deletes the MinIO bytes) once
that timestamp passes. The row itself is retained so status polling
remains deterministic for a recently-deleted bundle.

`status` is TEXT + CHECK rather than a Postgres ENUM so adding a state
later doesn't require a schema migration; the running set is fixed at
4 values.

ON DELETE CASCADE on `user_id` so the D6 hard-delete worker can drop a
user without needing to manually clear export-job rows first.

---

## Projects (matter-scoped containers)

### `projects`

Landed in migration `0004_create_projects.py` (Task C7). The migration
ships what's runnable today; the doc-aspirational `uuid_generate_v7()`
default is replaced with `gen_random_uuid()` (UUIDv4, via the pgcrypto
extension enabled in 0001) until the project takes on the
`pg_uuidv7` extension dependency.

Soft-delete uses `archived_at` (not `deleted_at`) to match the PRD §3.11
language ("archive a Project when the matter closes; it is searchable
but does not clutter the active list"). The semantics are equivalent;
the column-name choice keeps the user-facing concept grounded.

```sql
CREATE TABLE projects (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id                 UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    name                     TEXT NOT NULL,
    slug                     TEXT NOT NULL,  -- URL-friendly identifier; unique-per-owner-active
    description              TEXT,
    context_md               TEXT,  -- free-form markdown
    privileged               BOOLEAN NOT NULL DEFAULT FALSE,
    minimum_inference_tier   SMALLINT,
    is_sandbox               BOOLEAN NOT NULL DEFAULT FALSE,  -- 0022: system-managed try-it sandbox
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at              TIMESTAMPTZ,  -- soft-delete; NULL means active
    CONSTRAINT chk_projects_tier_range CHECK (
        minimum_inference_tier IS NULL OR (minimum_inference_tier BETWEEN 1 AND 5)
    ),
    CONSTRAINT chk_projects_privileged_implies_tier CHECK (
        (privileged = false) OR (minimum_inference_tier IS NOT NULL)
    ),
    CONSTRAINT chk_projects_name_len CHECK (
        char_length(name) > 0 AND char_length(name) <= 200
    ),
    CONSTRAINT chk_projects_slug_len CHECK (
        char_length(slug) > 0 AND char_length(slug) <= 80
    )
);

CREATE INDEX idx_projects_owner_active
    ON projects (owner_id, created_at DESC)
    WHERE archived_at IS NULL;

-- Migration 0022: non-sandbox active projects (the default list query).
CREATE INDEX idx_projects_not_sandbox
    ON projects (owner_id, created_at)
    WHERE is_sandbox = false AND archived_at IS NULL;

-- Slug uniqueness scoped to (owner, active). Archived projects free
-- their slug so a user can reuse it on a new active project.
CREATE UNIQUE INDEX idx_projects_slug_owner_active
    ON projects (owner_id, slug)
    WHERE archived_at IS NULL;

CREATE TRIGGER trg_projects_set_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();
```

**Column notes.**

| Column | Migration | Notes |
|---|---|---|
| `is_sandbox` | 0022 | System-managed flag for the per-user skill try-it sandbox (`slug='__sandbox__'`). `POST /projects/sandbox/ensure` creates or returns the row. Sandbox projects are excluded from the default `GET /projects` list; the `include_sandbox` / `only_sandbox` query params control visibility. |

### `project_files` and `project_skills`

Many-to-many join tables. A project can have multiple skills attached
and multiple files attached. `skill_name` is **text, not a FK** —
skills are filesystem-canonical per ADR 0004; there is no `skills`
SQL table.

```sql
CREATE TABLE project_files (
    project_id   UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_id      UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    attached_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, file_id)
);

CREATE INDEX idx_project_files_file ON project_files (file_id);

CREATE TABLE project_skills (
    project_id   UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    skill_name   TEXT NOT NULL,
    attached_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, skill_name),
    CONSTRAINT chk_project_skills_name_len CHECK (
        char_length(skill_name) > 0 AND char_length(skill_name) <= 200
    )
);

CREATE INDEX idx_project_skills_skill ON project_skills (skill_name);
```

### `files.project_id` FK constraint (closed C4 deferred)

Migration 0003 (Task C4) added `files.project_id` as a nullable
column without an FK constraint because `projects` did not exist yet.
Migration 0004 closes that deferred item:

```sql
ALTER TABLE files
    ADD CONSTRAINT fk_files_project_id
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL;
```

`ON DELETE SET NULL` rather than `CASCADE` because the file is
independently owned by its `owner_id` and may be in other projects via
the `project_files` join (the `files.project_id` column is the file's
*primary* project; the join table is the many-to-many relation).

### `project_knowledge_bases` (migration 0021)

Many-to-many join binding knowledge bases to projects (a project can
surface multiple KBs; a KB can be attached to multiple projects).
Distinct from `knowledge_bases.project_id`, which is the KB's *primary*
project; this table is the many-to-many attach relation.

```sql
CREATE TABLE project_knowledge_bases (
    project_id           UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,            -- fk_project_knowledge_bases_project_id
    knowledge_base_id    UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,     -- fk_project_knowledge_bases_kb_id
    attached_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    attached_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,                       -- fk_project_knowledge_bases_attached_by
    CONSTRAINT pk_project_knowledge_bases PRIMARY KEY (project_id, knowledge_base_id)
);

CREATE INDEX idx_project_knowledge_bases_kb_id
    ON project_knowledge_bases (knowledge_base_id);
```

---

## Chats and messages

> **Implementation notes (Task C3, migration 0006).** The shapes below
> are what migration `0006_create_chats_and_messages.py` actually
> creates. They diverge from the PRD-era sketch in three places that
> were resolved during C3 — recording them here so the doc and the
> migration stay in lockstep:
>
> 1. **Soft-delete column is `archived_at`, not `deleted_at`.** Matches
>    C7's projects soft-delete posture (we don't conflate "user
>    archived this" with "this is scheduled for hard-delete"; D6 owns
>    the latter).
> 2. **`title` is NOT NULL with default `'New chat'`.** The API
>    auto-renames the chat from the first user message's first 80
>    chars on the first `POST /messages`; the default is what stands
>    if the user never sends a message.
> 3. **`messages.cost_estimate_micros` is BIGINT (USD micros)**, not
>    `NUMERIC(10,4)`. Storing as integer micros avoids float
>    round-trip drift in the audit log. Conversion factor is `1 micro
>    = 1e-6 USD`; the API's `usd_to_micros` / `micros_to_usd` helpers
>    in `app/schemas/chats.py` translate.
> 4. **`messages.applied_skills` is `text[]`** (denormalized per ADR
>    0007), not a join table. Skills are filesystem-canonical (no SQL
>    `skills` table to FK to), and audit reads are write-light.
> 5. **`messages.error_code`** is a new column persisted when an
>    assistant message fails mid-stream or the gateway raises. Carries
>    the canonical `app.errors` code (e.g., `provider_unavailable`).
> 6. **`messages.citations`** is `JSONB` with default `'[]'`. M1 stored
>    the empty list; M2-A2 chose the relational
>    `message_citations` table (one row per citation, see below) over
>    JSONB-on-message for queryability. The JSONB column stays at its
>    `'[]'` default and the M2-A2 chat-send path leaves it alone — it
>    is slated for retirement by M2-C2 (failed-citation UI rendering),
>    which will read exclusively from `message_citations`.

### `chats`

```sql
CREATE TABLE chats (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    project_id  UUID REFERENCES projects(id) ON DELETE SET NULL,
    title       TEXT NOT NULL DEFAULT 'New chat'
                  CHECK (char_length(title) > 0 AND char_length(title) <= 200),
    archived_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_chats_owner_active ON chats(owner_id, created_at DESC)
    WHERE archived_at IS NULL;
CREATE INDEX idx_chats_project_active ON chats(project_id)
    WHERE project_id IS NOT NULL AND archived_at IS NULL;

-- updated_at maintenance via the set_updated_at() trigger from migration 0001.
CREATE TRIGGER trg_chats_set_updated_at
    BEFORE UPDATE ON chats FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

### `chat_attached_skills` and `chat_attached_files`

> **Status (M1).** Not implemented yet. The C3 implementation captures
> per-message `applied_skills` directly on the `messages` row — see
> below — which is sufficient for the M1 audit-log requirement. Chat-
> level (rather than per-message) attachment surfaces would land in a
> later task if the UI needs them; the schema below is preserved as a
> forward-looking sketch.

```sql
-- Forward-looking; not in M1.
-- CREATE TABLE chat_attached_skills (
--     chat_id      UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
--     skill_name   TEXT NOT NULL,
--     skill_version TEXT,
--     skill_inputs JSONB,
--     attached_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
--     PRIMARY KEY (chat_id, skill_name)
-- );
-- CREATE TABLE chat_attached_files (
--     chat_id      UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
--     file_id      UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
--     attached_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
--     PRIMARY KEY (chat_id, file_id)
-- );
```

### `messages`

```sql
CREATE TABLE messages (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id                  UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role                     TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
    content                  TEXT NOT NULL,
    -- Per ADR 0007: skills the gateway applied for THIS exchange.
    -- Denormalized text array; skills are filesystem-canonical.
    applied_skills           TEXT[] NOT NULL DEFAULT '{}'::text[],
    -- Routing metadata (assistant messages only; NULL for user/system/tool).
    routed_inference_tier    SMALLINT CHECK (routed_inference_tier IS NULL
                                             OR (routed_inference_tier BETWEEN 1 AND 5)),
    routed_provider          TEXT,
    routed_model             TEXT,
    prompt_tokens            INTEGER CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
    completion_tokens        INTEGER CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
    -- Cost stored as integer USD micros (1 micro = 1e-6 USD) to avoid
    -- float-precision drift in the audit trail. Wire shape converts
    -- back to a USD float for client friendliness.
    cost_estimate_micros     BIGINT,
    -- Populated when the assistant message failed mid-stream or the
    -- gateway raised an LQAIError. Carries the canonical lq_ai.errors
    -- code (e.g., 'provider_unavailable', 'gateway_timeout'). NULL on
    -- success.
    error_code               TEXT,
    -- M2's citation engine populates this. C3 stores [].
    citations                JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_chat_created ON messages(chat_id, created_at);
```

### `inference_routing_log` FK closure (Task C3)

Migration 0006 also closes the A2-deferred FK constraints on the
`inference_routing_log.chat_id` and `inference_routing_log.message_id`
columns. Both `ON DELETE SET NULL` so audit history survives the
deletion of the underlying chat or message.

```sql
ALTER TABLE inference_routing_log
    ADD CONSTRAINT fk_inference_routing_log_chat_id
        FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_inference_routing_log_message_id
        FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL;
```

### `message_citations`

Per M2-A2 (migration `0025_create_message_citations.py`). One row per
model-emitted citation, written by the chat-send path after the
assistant message is persisted and the Citation Engine has run its
verification cascade.

```sql
CREATE TABLE message_citations (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id                UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    source_file_id            UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    source_offset_start       INTEGER NOT NULL,
    source_offset_end         INTEGER NOT NULL,
    source_page               INTEGER,
    source_text               TEXT NOT NULL,
    verified                  BOOLEAN NOT NULL DEFAULT FALSE,
    verification_method       TEXT,  -- enum below
    verification_confidence   NUMERIC(3,2),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_message_citations_offset_start_nonneg
        CHECK (source_offset_start >= 0),
    CONSTRAINT chk_message_citations_offset_end_gt_start
        CHECK (source_offset_end > source_offset_start),
    CONSTRAINT chk_message_citations_method_values
        CHECK (
            verification_method IS NULL
            OR verification_method IN (
                'exact_match', 'tolerant_match', 'llm_judge', 'ensemble', 'failed'
            )
        ),
    CONSTRAINT chk_message_citations_confidence_range
        CHECK (
            verification_confidence IS NULL
            OR (verification_confidence >= 0 AND verification_confidence <= 1)
        ),
    CONSTRAINT chk_message_citations_verified_has_method
        CHECK ((verified = false) OR (verification_method IS NOT NULL))
);

CREATE INDEX idx_message_citations_message ON message_citations(message_id);
CREATE INDEX idx_message_citations_file ON message_citations(source_file_id);
```

The `verification_method` enum carries the stage that produced the
verdict — every stage writes into the same row shape so the
persistence layer (and the UI) don't need to switch on stage:

| Value | Stage | Confidence | Lands in |
|---|---|---|---|
| `'exact_match'` | Stage 1: byte-for-byte against `documents.normalized_content[start:end]` | always `1.0` | **M2-A2 (here)** |
| `'tolerant_match'` | Stage 2: whitespace + OCR-artefact + smart-quote normalization | similarity-based | M2-B1 |
| `'llm_judge'` | Stage 3: LLM paraphrase judge | judge-reported | M2-C1 |
| `'ensemble'` | Stage 4: multi-model agreement for high-stakes ops | quorum-derived | M2-D1 |
| `'failed'` | Every stage rejected; rendered as unverified | NULL | M2-C2 wiring |

The `verified=true ⇒ verification_method IS NOT NULL` CHECK constraint
prevents a row from claiming verification without naming which stage
passed.

M2-A2 ships Stage 1 only: extraction (`app.citation.extraction`) finds
`"..." (Source: [N])` pairs in the assistant response, locates the
quote inside the cited retrieved chunk's content, and derives byte-
precise document offsets. The verifier (`app.citation.verification`)
confirms `normalized_content[start:end] == source_text` byte-for-byte.
Candidates that fail Stage 1 are dropped (not persisted) until later
stages ship; the M2-C2 UI work decides what to render for "model
emitted but we couldn't verify."

### `enhance_prompt_interactions` (migration 0015)

One row per Enhance Prompt (⌘E) invocation. Records the raw input, the
expanded output (or the skip reason if expansion did not apply), the
model's reasoning trace, whether the user used/edited the result, and
the routing metadata for the enhance call.

```sql
CREATE TABLE enhance_prompt_interactions (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,    -- fk_enhance_prompt_interactions_user
    chat_id                UUID REFERENCES chats(id) ON DELETE SET NULL,            -- fk_enhance_prompt_interactions_chat
    raw_input              TEXT NOT NULL,
    expansion_applied      BOOLEAN NOT NULL,
    expanded_output        TEXT,
    reasoning              JSONB NOT NULL DEFAULT '[]'::jsonb,
    skip_reason            TEXT,
    used                   BOOLEAN NOT NULL DEFAULT FALSE,
    edited_before_use      BOOLEAN NOT NULL DEFAULT FALSE,
    routed_inference_tier  INTEGER,
    routed_provider        TEXT,
    routed_model           TEXT,
    prompt_tokens          INTEGER,
    completion_tokens      INTEGER,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_enhance_prompt_tier_range
        CHECK (routed_inference_tier IS NULL OR (routed_inference_tier BETWEEN 1 AND 5)),
    CONSTRAINT chk_enhance_prompt_skip_has_reason
        CHECK (expansion_applied OR skip_reason IS NOT NULL)
);
```

### `work_product_attribution` (migration 0017)

One row per assistant message that constitutes attributable work
product (PRD §5 work-product attribution). Captures the routing/skill/
playbook provenance and a content hash so a given output can be tied
back to the actor, matter, model, and skills that produced it. The
`message_id` FK is `UNIQUE` — at most one attribution row per message.

```sql
CREATE TABLE work_product_attribution (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id             UUID NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,  -- fk_work_product_attribution_message
    user_id                UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,            -- fk_work_product_attribution_user
    chat_id                UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,            -- fk_work_product_attribution_chat
    project_id             UUID REFERENCES projects(id) ON DELETE SET NULL,                 -- fk_work_product_attribution_project
    routed_inference_tier  INTEGER,
    provider               TEXT,
    model                  TEXT,
    model_version          TEXT,
    skill_ids              TEXT[] NOT NULL DEFAULT ARRAY[]::text[],
    playbook_id            UUID,                                          -- plain UUID; no FK (playbooks land in M3)
    content_hash           TEXT NOT NULL,
    timestamp              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_work_product_tier_range
        CHECK (routed_inference_tier IS NULL OR (routed_inference_tier BETWEEN 1 AND 5))
);

CREATE INDEX idx_work_product_user_timestamp
    ON work_product_attribution (user_id, timestamp DESC);
CREATE INDEX idx_work_product_chat
    ON work_product_attribution (chat_id);
```

`playbook_id` is a plain UUID column with no FK constraint — migration
0017 (M1) predates the `playbooks` table (migration 0031, M3), so the
reference is stored unbound.

---

## Skills (sketch — **not built**; superseded by `user_skills`)

> **Status: NOT created by any migration.** The `skills`,
> `skill_reference_files`, and `skill_example_files` tables below are an
> early sketch from before [ADR 0004](adr/0004-skill-loader-locus.md)
> made skills **filesystem-canonical**. There is no `skills` SQL table,
> no `skill_reference_files` table, and no `skill_example_files` table in
> the shipped schema (verified against migrations 0001–0045 and
> `api/app/models/` — no `Skill` ORM model exists). Built-in skills load
> from disk at startup; user/team-scoped skills are stored in the
> **`user_skills`** table (migration 0013, documented below), and the
> singleton Organization Profile is the **`organization_profile`** table
> (migration 0010, documented below). The blocks here are retained only
> as a record of the original sketch.

The original sketch stored skills both on disk (the canonical source for built-in skills loaded at startup) and in the database (for user-scoped and team-scoped skills, plus any forks of built-ins).

### `skills` (sketch — not built)

```sql
CREATE TABLE skills (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    name                     TEXT NOT NULL,
    version                  TEXT NOT NULL,
    scope                    TEXT NOT NULL CHECK (scope IN ('builtin','user','team')),
    owner_id                 UUID REFERENCES users(id) ON DELETE CASCADE,
    is_organization_profile  BOOLEAN NOT NULL DEFAULT FALSE,
    title                    TEXT NOT NULL,
    description              TEXT NOT NULL,
    tags                     TEXT[],
    jurisdiction             TEXT,
    output_format            TEXT NOT NULL CHECK (output_format IN ('report','issues_list','table','redline')),
    minimum_inference_tier   SMALLINT CHECK (minimum_inference_tier BETWEEN 1 AND 5),
    use_organization_profile BOOLEAN NOT NULL DEFAULT TRUE,
    self_improvement         BOOLEAN NOT NULL DEFAULT FALSE,
    content_yaml             TEXT NOT NULL,  -- frontmatter
    content_md               TEXT NOT NULL,  -- body
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at               TIMESTAMPTZ,
    UNIQUE (name, version, scope, owner_id),
    CONSTRAINT chk_org_profile_singleton CHECK (
        NOT is_organization_profile OR (scope = 'team' AND owner_id IS NULL)
    )
);

CREATE UNIQUE INDEX idx_skills_org_profile_singleton 
    ON skills(is_organization_profile) 
    WHERE is_organization_profile = TRUE AND deleted_at IS NULL;
CREATE INDEX idx_skills_name_active ON skills(name) WHERE deleted_at IS NULL;
CREATE INDEX idx_skills_owner_active ON skills(owner_id, scope) WHERE deleted_at IS NULL;
```

The `idx_skills_org_profile_singleton` partial unique index enforces that there is at most one Organization Profile in the deployment.

### `skill_reference_files` and `skill_example_files` (sketch — not built)

Reference and example files associated with a skill. For built-in skills these are loaded from disk at startup; user/team skills store them here. **Like `skills` above, these tables were never created** — reference/example files for built-ins live on disk, and user-skill bodies are stored inline in `user_skills.body` / `user_skills.frontmatter_extra`.

```sql
CREATE TABLE skill_reference_files (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    skill_id     UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    path         TEXT NOT NULL,  -- e.g. 'reference/severity_rubric.md'
    content      TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (skill_id, path)
);

CREATE TABLE skill_example_files (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    skill_id     UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    path         TEXT NOT NULL,  -- e.g. 'examples/example_recipient.md'
    content      TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (skill_id, path)
);
```

### `organization_profile` (Task D4, migration 0010)

The Organization Profile is a "singleton skill" per PRD §3.12 — same
SKILL.md format and inspectability, treated as a singleton by the Skill
Service. Because ADR 0004 keeps built-in skills filesystem-canonical
(there is no `skills` SQL table to add an `is_organization_profile`
column to), D4 backs the GET/PUT API with a focused single-row table.
The gateway-side prompt-assembler fetches the row's content and prepends
it to every attached skill whose frontmatter does not opt out
(`use_organization_profile: false`).

```sql
CREATE TABLE organization_profile (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_md  TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  UUID REFERENCES users(id) ON DELETE SET NULL  -- fk_org_profile_updated_by
);

-- Singleton enforcement — Postgres "at most one row" pattern: the
-- expression index collapses every row to the same literal, so a second
-- insert violates the unique index (23505).
CREATE UNIQUE INDEX idx_organization_profile_singleton
    ON organization_profile ((true));

CREATE TRIGGER trg_organization_profile_updated_at
    BEFORE UPDATE ON organization_profile
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

---

## Files and document pipeline

### `files`

Original uploaded files; the bytes themselves live in object storage (MinIO/S3).

```sql
CREATE TABLE files (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    owner_id        UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    project_id      UUID REFERENCES projects(id) ON DELETE SET NULL,
    filename        TEXT NOT NULL,
    mime_type       TEXT NOT NULL,
    size_bytes      BIGINT NOT NULL,
    hash_sha256     TEXT NOT NULL,
    storage_path    TEXT NOT NULL,  -- object-storage key
    ingestion_status TEXT NOT NULL DEFAULT 'pending' 
        CHECK (ingestion_status IN ('pending','processing','ready','failed')),
    ingestion_error TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_files_owner_active ON files(owner_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX idx_files_project ON files(project_id) WHERE project_id IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX idx_files_status ON files(ingestion_status) WHERE ingestion_status IN ('pending','processing');
CREATE INDEX idx_files_hash ON files(hash_sha256);  -- dedup detection
```

### `documents`

Parsed-document metadata after the document pipeline runs (Task C5,
migration `0004_create_documents_and_chunks.py`).

```sql
CREATE TABLE documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id             UUID NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE,
    parser              TEXT NOT NULL,  -- 'docling+pymupdf', 'pymupdf', 'pymupdf-only'
    parser_version      TEXT,            -- e.g. 'pymupdf=1.24.0; docling=1.16.0'
    page_count          INTEGER,
    character_count     INTEGER,
    structured_content  JSONB,            -- Docling's structured representation; M2 reads
    normalized_content  TEXT NOT NULL DEFAULT '',  -- M2-A1 (migration 0024); see below
    was_ocrd            BOOLEAN NOT NULL DEFAULT FALSE,  -- M2-A1 (migration 0024); see below
    ingest_status       TEXT NOT NULL DEFAULT 'ok'    -- M3-0.3 (migration 0030); see below
        CHECK (ingest_status IN ('ok','parse_failed','embed_failed','partial')),
    ingest_failure_reason TEXT,                       -- M3-0.3 (migration 0030); populated when ingest_status <> 'ok'
    processed_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_documents_file_id ON documents(file_id);
-- Partial index — only the failure-state rows. The 'ok' rows are
-- the steady-state majority; including them would bloat the index
-- and add write cost on the dominant insert path. Powers the
-- /api/v1/admin/ingest-health aggregate without a sequential scan.
CREATE INDEX idx_documents_ingest_status ON documents(ingest_status)
    WHERE ingest_status IN ('parse_failed','embed_failed','partial');
```

Per ADR 0006, the `parser` column carries the cascade outcome:
`docling+pymupdf` (both succeeded), `pymupdf` (Docling fell through),
or `pymupdf-only` (Docling intentionally disabled via
`LQ_AI_DOCLING_ENABLED=false`).

Per M2-A1 (migration 0024), `normalized_content` carries the full,
canonical PyMuPDF text stream — the source the M2 Citation Engine
slices at chunk offsets when verifying that a citation appears in the
source document. The fidelity invariant is
`document_chunks.content == normalized_content[char_offset_start:char_offset_end]`,
held at write time by `app.pipeline.ingest`. Pre-M2 rows landed with
the empty-string default and were reconstructed from their chunks via
the one-time script `scripts/backfill_normalized_content.py` (which
remains idempotent and re-runnable should a future migration require
it).

`was_ocrd` is a forward-looking flag: a later M2 task adds an OCR
fallback for image-only PDFs, and the tolerant-match verification stage
(M2-B1) uses this flag to enable OCR-artifact normalization. Every M1
ingest and every backfilled row sets `was_ocrd = FALSE` because M1's
parsers never OCR (image-only PDFs are rejected with `parse_failed`).

Per M3-0.3 / DE-276 (migration 0030), `ingest_status` records the
**post-parse** outcome that `files.ingestion_status` cannot detect: an
embed batch failure that leaves chunks with NULL embeddings and
silently degrades hybrid retrieval to FTS-only. `embed_failed` is set
when zero chunks were embedded before the batch raised; `partial` is
set when some succeeded but later batches did not — the operator can
re-run ingest to recover from either state. `parse_failed` is a
reserved value (no v0.3 code path writes it; parse failures stop
before a `documents` row is created and are tracked at the file
level instead). The `/api/v1/admin/ingest-health` endpoint aggregates
this column alongside `files.ingestion_status` so operators see a
single ingest-health summary across both pipelines.

### `document_chunks`

Chunked content with embeddings and full-text indexing (Task C5).

```sql
CREATE TABLE document_chunks (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id          UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index          INTEGER NOT NULL,
    content              TEXT NOT NULL,
    page_start           INTEGER,
    page_end             INTEGER,
    char_offset_start    INTEGER NOT NULL,
    char_offset_end      INTEGER NOT NULL,
    tokens               INTEGER,                  -- C6 backfills alongside embeddings
    embedding            VECTOR(1536),             -- nullable for M1 (ADR 0006); C6 backfills
    content_tsv          TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    metadata_json        JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (document_id, chunk_index),
    CHECK (char_offset_start >= 0),
    CHECK (char_offset_end >= char_offset_start),
    CHECK (chunk_index >= 0)
);

CREATE INDEX idx_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_chunks_tsv ON document_chunks USING gin (content_tsv);
CREATE INDEX idx_chunks_document ON document_chunks(document_id, chunk_index);
```

The `ivfflat` index is appropriate for moderate scale; transition to `hnsw` (Postgres 16+) for larger deployments. Per ADR 0008 we keep `ivfflat` for M1 — the differential against HNSW only shows at corpus sizes well above what M1 deployments will see.

Per ADR 0006, the `embedding` column was **nullable for M1** — the C5
pipeline writes chunks with `embedding=NULL` and C6 backfills via the
gateway's `/v1/embeddings`. The pgvector extension is enabled by
migration 0005. The dimension `vector(1536)` matches OpenAI's
`text-embedding-3-small` per ADR 0008 (the embedding-model decision).

C6 closes the embedding deferral via two backfill paths:

* **Eager (worker-driven).** `app.workers.document_pipeline.embed_chunks_for_file_job` walks every `embedding IS NULL` chunk for a file and calls the gateway's `/v1/embeddings` in 64-row batches. Triggered by `POST /api/v1/knowledge-bases/{id}/files` (when the file has unembedded chunks) and by the ingest-completion hook (every successful ingest enqueues an embed job for forward chunks).
* **Lazy (query-driven).** `app.knowledge.embed.ensure_embeddings_for_chunk_ids` covers the gap when a query runs before the worker has caught up.

Token counts (`document_chunks.tokens`) are populated alongside the embedding via `tiktoken`'s `cl100k_base` BPE — closing the C5-deferred per-chunk token-count item. The tokenizer choice tracks the embedding-model choice per ADR 0008.

The `(document_id, chunk_index)` UNIQUE constraint
backs the C5 worker's idempotent-replace strategy: re-running ingest
for a file deletes prior chunks and re-inserts them in the same
transaction.

#### Hybrid retrieval score formula (C6 / ADR 0008)

The KB query handler computes a per-chunk `hybrid_score`:

```
vector_score_raw = 1 - cosine_distance(embedding, query_embedding)
fts_score_raw    = ts_rank_cd(content_tsv, plainto_tsquery('english', query))

vector_score = min_max_normalize(vector_score_raw across candidate union)
fts_score    = min_max_normalize(fts_score_raw across candidate union)

hybrid_score = (1 - alpha) * vector_score + alpha * fts_score
```

* `alpha` is `KBQueryRequest.hybrid_alpha` (per-query override) or
  `knowledge_bases.hybrid_alpha` (KB default; default 0.5).
* `0` means vector-only; `1` means FTS-only; `0.5` means balanced.
* Each side returns `top_k * 4` candidates; the union is normalized
  per-side then linearly combined; top-`k` by combined score returns.
* If embedding generation fails for the query string, the handler
  drops to FTS-only ranking gracefully (`vector_score = 0` everywhere).
* If a chunk's embedding is `NULL` it's invisible to the vector side
  but still visible to the FTS side; the embed-on-write path closes
  this for new chunks.

Min-max (rather than z-score) is used because z-score requires
non-trivial standard deviation — fragile on small candidate sets
common at M1 scale. Min-max also gives values in `[0, 1]` that
operators can read directly.

The `metadata_json` column is named with the `_json` suffix because
the bare `metadata` identifier conflicts with SQLAlchemy's declarative
`Base.metadata` attribute. Functionally it's the JSONB column the
schema doc has historically called `metadata`.

The `char_offset_start` and `char_offset_end` columns are 0-based
half-open offsets (`[start, end)`, Python slice semantics) into the
canonical PyMuPDF character stream of the document. The fidelity
invariant the M2 Citation Engine consumes is:

```
canonical_text[char_offset_start:char_offset_end] == content
```

The C5 chunker tests assert this byte-for-byte against three fixture
PDFs of varying complexity.

---

## Knowledge bases

### `knowledge_bases`

Lands in migration 0007 (Task C6). The schema below reflects what's
shipped; minor naming differences from earlier sketches (`archived_at`
rather than `deleted_at`; `gen_random_uuid()` rather than v7; explicit
`hybrid_alpha`) are documented inline.

```sql
CREATE TABLE knowledge_bases (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id     UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    project_id   UUID REFERENCES projects(id) ON DELETE SET NULL,
    name         TEXT NOT NULL,
    description  TEXT,
    hybrid_alpha REAL NOT NULL DEFAULT 0.5,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at  TIMESTAMPTZ,

    CONSTRAINT chk_knowledge_bases_alpha_range
        CHECK (hybrid_alpha >= 0.0 AND hybrid_alpha <= 1.0),
    CONSTRAINT chk_knowledge_bases_name_len
        CHECK (char_length(name) > 0 AND char_length(name) <= 200)
);

CREATE INDEX idx_kbs_owner_active
    ON knowledge_bases (owner_id, created_at DESC)
    WHERE archived_at IS NULL;
CREATE INDEX idx_kbs_project
    ON knowledge_bases (project_id)
    WHERE project_id IS NOT NULL;

CREATE TRIGGER trg_knowledge_bases_updated_at
    BEFORE UPDATE ON knowledge_bases
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

* `hybrid_alpha` is the per-KB default for the score combine (see the
  document_chunks section above for the formula). `0 ↔ vector-only`,
  `1 ↔ FTS-only`, `0.5 ↔ balanced`. The CHECK constraint is the safety
  net; the API also clamps at the request boundary.
* `archived_at` is the soft-delete column (matching projects/chats).
  Hard-delete is D6 territory.
* `owner_id ON DELETE RESTRICT` — KBs outlive their owner's
  soft-delete; D6's hard-delete cascade will remove them.
* `project_id ON DELETE SET NULL` — KBs outlive their projects (an
  operator may dissolve a project without losing its research
  artifacts).

### `knowledge_base_files`

```sql
CREATE TABLE knowledge_base_files (
    kb_id        UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    file_id      UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    attached_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kb_id, file_id)
);

CREATE INDEX idx_kb_files_file_id ON knowledge_base_files (file_id);
```

The `(file_id)` inverse index supports the embed-on-write trigger's
"which KBs contain this file?" query when ingest completes for a
chunk.

---

## Saved prompts (per [DE-013](PRD.md#de-013--saved-prompts-library) / Issue 04)

```sql
CREATE TABLE saved_prompts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    tags        TEXT[],
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_saved_prompts_user ON saved_prompts(user_id, updated_at DESC);
CREATE INDEX idx_saved_prompts_tags ON saved_prompts USING gin (tags);
```

---

## User skills (per [ADR 0012](adr/0012-db-backed-user-skills.md))

DB-backed user-scope skills that shadow filesystem-canonical built-ins (per ADR 0004) on slug collision when resolved for the owning user's chats. D8 ships the user-scope CRUD; team-scope columns are present from the start but the FK and API surface land in D8.1.

```sql
CREATE TABLE user_skills (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope             TEXT NOT NULL CHECK (scope IN ('user', 'team')),
    owner_user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    owner_team_id     UUID,                                       -- FK target ships in D8.1
    slug              TEXT NOT NULL,
    display_name      TEXT NOT NULL,
    description       TEXT NOT NULL,
    version           TEXT NOT NULL DEFAULT '1.0.0',              -- free-form, user-set semver
    tags              TEXT[] NOT NULL DEFAULT '{}',
    frontmatter_extra JSONB NOT NULL DEFAULT '{}',
    body              TEXT NOT NULL,
    slash_alias       TEXT,                                       -- 0023: chat-composer trigger alias (e.g. '/nda')
    forked_from       TEXT,                                       -- 0023: source skill slug when created via fork
    archived_at       TIMESTAMPTZ,                                -- soft-delete
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_user_skills_scope_owner_consistency CHECK (
        (scope = 'user' AND owner_user_id IS NOT NULL AND owner_team_id IS NULL)
        OR (scope = 'team' AND owner_team_id IS NOT NULL AND owner_user_id IS NULL)
    ),
    CONSTRAINT chk_user_skills_slash_alias_format CHECK (
        slash_alias IS NULL OR slash_alias ~ '^/[a-z0-9-]{1,32}$'
    )
);

-- Slug is unique within an owner for non-archived rows; archived rows free the slug.
CREATE UNIQUE INDEX ux_user_skills_user_slug ON user_skills(owner_user_id, slug)
    WHERE scope = 'user' AND archived_at IS NULL;
CREATE UNIQUE INDEX ux_user_skills_team_slug ON user_skills(owner_team_id, slug)
    WHERE scope = 'team' AND archived_at IS NULL;

CREATE INDEX idx_user_skills_owner_user ON user_skills(owner_user_id, updated_at DESC)
    WHERE scope = 'user' AND archived_at IS NULL;
CREATE INDEX idx_user_skills_owner_team ON user_skills(owner_team_id, updated_at DESC)
    WHERE scope = 'team' AND archived_at IS NULL;

-- Migration 0023: slash_alias uniqueness per owner within active rows.
CREATE UNIQUE INDEX idx_user_skills_slash_alias_owner_active
    ON user_skills (owner_user_id, slash_alias)
    WHERE slash_alias IS NOT NULL AND archived_at IS NULL AND scope = 'user';
CREATE UNIQUE INDEX idx_user_skills_slash_alias_team_active
    ON user_skills (owner_team_id, slash_alias)
    WHERE slash_alias IS NOT NULL AND archived_at IS NULL AND scope = 'team';
```

**Column notes.**

| Column | Migration | Notes |
|---|---|---|
| `slash_alias` | 0023 | Optional chat-composer trigger alias. Must match `^/[a-z0-9-]{1,32}$` (enforced by `chk_user_skills_slash_alias_format`). Unique per active owner (partial unique indexes above). `POST` and `PATCH /user-skills` return 422 with `"slash_alias '...' is already used by another of your skills."` on collision. |
| `forked_from` | 0023 | Slug of the source skill when this row was created via the fork button on the skill detail page. Stored as plain text — the source may be a filesystem-canonical built-in with no DB row (per ADR 0004). Set on create; read-only afterward. |

Resolution path during prompt assembly (`/internal/skills/{slug}?user_id=…`): user-scope row for the requesting user wins on slug match; falls through to the filesystem registry otherwise. D8.1's only addition is the `teams` FK target and a middle resolution slot for team-scope rows.

---

## Teams (D8.1a, per [ADR 0012](adr/0012-db-backed-user-skills.md))

Operator-admin-controlled groupings that scope shared skills. `is_admin=true` users create teams and add members; each `team_members` row carries a `role` (`admin` or `member`) that D8.1b uses to gate mutate rights on team-scope `user_skills` rows. The migration closing the `user_skills.owner_team_id` FK lands here.

```sql
CREATE TABLE teams (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name               TEXT NOT NULL,
    slug               TEXT NOT NULL UNIQUE,                       -- stable lowercase identifier
    description        TEXT,
    created_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE team_members (
    team_id           UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role              TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    added_by_user_id  UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, user_id)
);

CREATE INDEX idx_team_members_user ON team_members(user_id);

-- Closes the user_skills.owner_team_id FK that 0013 left unbound.
ALTER TABLE user_skills
    ADD CONSTRAINT fk_user_skills_team
    FOREIGN KEY (owner_team_id) REFERENCES teams(id) ON DELETE CASCADE;
```

Team deletion CASCADEs to `team_members` and to `user_skills` with `scope='team'`. User deletion CASCADEs into membership rows but is RESTRICTed by the `created_by_user_id` and `added_by_user_id` references — deleting a user requires re-assigning or deleting the teams they created and removing their membership audit trail first.

---

## Audit log (cross-cutting)

The most consequential table in the schema. Every privilege-affecting action lands here. Privileged-marked entries and routed-inference-tier values are first-class fields, not buried in JSONB.

### `audit_log`

```sql
CREATE TABLE audit_log (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    timestamp             TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id               UUID REFERENCES users(id) ON DELETE SET NULL,
    action                TEXT NOT NULL,           -- e.g. 'chat.create', 'message.send', 'skill.fork'
    resource_type         TEXT NOT NULL,           -- e.g. 'chat', 'project', 'skill'
    resource_id           TEXT,                    -- typically a UUID stringified
    privilege_marked      BOOLEAN NOT NULL DEFAULT FALSE,
    privilege_basis       TEXT,                    -- 'project_privileged_flag', 'matter_attorney_directive', etc.
    routed_inference_tier SMALLINT CHECK (routed_inference_tier BETWEEN 1 AND 5),
    routed_provider       TEXT,
    ip_address            INET,
    user_agent            TEXT,
    request_id            TEXT,                    -- correlation across services
    details               JSONB,                   -- opaque payload, queryable but not indexed by default
    CONSTRAINT chk_privileged_with_basis CHECK (
        NOT privilege_marked OR privilege_basis IS NOT NULL
    )
);

CREATE INDEX idx_audit_log_timestamp ON audit_log(timestamp DESC);
CREATE INDEX idx_audit_log_user_timestamp ON audit_log(user_id, timestamp DESC);
CREATE INDEX idx_audit_log_resource ON audit_log(resource_type, resource_id);
CREATE INDEX idx_audit_log_privileged ON audit_log(privilege_marked, timestamp DESC) WHERE privilege_marked = TRUE;
CREATE INDEX idx_audit_log_tier ON audit_log(routed_inference_tier, timestamp DESC) WHERE routed_inference_tier IS NOT NULL;
```

The audit log is **append-only** at the application layer; the database does not enforce this directly (the maintainer-team can add a trigger if desired).

**`details` JSONB conventions.**

The `details` column carries action-specific payloads. Documented keys by action:

| Action | Key | Value |
|---|---|---|
| `chat.message_sent` | `user_message_id` | UUID (as string) of the `messages` row for the user-turn that initiated the exchange (Wave 7.2 — receipts source enrichment). The receipts builder joins `audit_log` to `chat_messages` via `details->>'user_message_id'` to correlate receipt rows with their originating user message. |
| `user_skill.created` | `slug`, `scope`, `version` | Identifies the created row. `team_id` also present for `scope='team'` rows. |
| `user_skill.updated` | `slug`, `scope`, `changed_fields`, `version_before`, `version_after` | `changed_fields` is a sorted array of mutated keys; `version_before`/`version_after` present only when `version` changed. `team_id` present for team-scope rows. |
| `user_skill.deleted` | `slug`, `scope` | Identity of the archived row. |

### `inference_routing_log`

Distinct from the general audit log because it has a different access pattern (every inference request, hot path) and different retention policy (operator-configurable, often shorter than audit log). Not a simple subset of audit_log.

```sql
CREATE TABLE inference_routing_log (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    timestamp                TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id                  UUID REFERENCES users(id) ON DELETE SET NULL,
    chat_id                  UUID REFERENCES chats(id) ON DELETE SET NULL,
    message_id               UUID REFERENCES messages(id) ON DELETE SET NULL,
    requested_model          TEXT,
    routed_provider          TEXT NOT NULL,
    routed_model             TEXT NOT NULL,
    routed_inference_tier    SMALLINT NOT NULL CHECK (routed_inference_tier BETWEEN 1 AND 5),
    tokens_in                INTEGER,
    tokens_out               INTEGER,
    cost_estimate            NUMERIC(10,4),
    latency_ms               INTEGER,
    anonymization_applied    BOOLEAN NOT NULL DEFAULT FALSE,
    refused                  BOOLEAN NOT NULL DEFAULT FALSE,
    refusal_reason           TEXT,                    -- 'tier_below_minimum', 'provider_unavailable', etc.
    request_id               TEXT
);

CREATE INDEX idx_inference_log_timestamp ON inference_routing_log(timestamp DESC);
CREATE INDEX idx_inference_log_user ON inference_routing_log(user_id, timestamp DESC) WHERE user_id IS NOT NULL;
CREATE INDEX idx_inference_log_tier_time ON inference_routing_log(routed_inference_tier, timestamp DESC);
CREATE INDEX idx_inference_log_provider_time ON inference_routing_log(routed_provider, timestamp DESC);
CREATE INDEX idx_inference_log_refused ON inference_routing_log(timestamp DESC) WHERE refused = TRUE;
```

---

## Playbooks (per [PRD §3.7](PRD.md#37-playbooks), M3-A1)

Substrate for the Playbook engine landing in M3. A playbook codifies an
organization's standard positions and fallback positions on common
contract issues; the LangGraph executor (M3-A2) walks each position
against a target contract and produces a per-position assessment with
redline suggestions. Three tables, all introduced by migration
`0031_playbooks.py`:

* `playbooks` — header row per playbook (name, contract type, version,
  author).
* `playbook_positions` — one row per issue inside a playbook. The
  per-position list of acceptable alternatives lives in a JSONB
  `fallback_tiers` column rather than a third normalized table (small
  per-position lists; always fetched together with the position).
* `playbook_executions` — one row per run of a playbook against a
  target document. `results` is JSONB shaped per the M3-A2 executor.

### `playbooks` (M3)

```sql
CREATE TABLE playbooks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    contract_type   TEXT NOT NULL,         -- e.g. 'NDA' | 'MSA-SaaS' | 'DPA' | 'MSA-Commercial'
    description     TEXT NOT NULL DEFAULT '',
    version         TEXT NOT NULL DEFAULT '1.0.0',
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`created_by` is nullable + `ON DELETE SET NULL` so a deleted operator's
playbook stays available to the rest of the team — playbooks outlive
their individual authors (matches the project / skill ownership model).

`contract_type` is free-form per [PRD §3.7](PRD.md#37-playbooks);
the canonical values used by the M3-A3 / M3-A5 built-ins are `'NDA'`,
`'NDA-unilateral'`, `'MSA-SaaS'`, `'MSA-Commercial'`, `'DPA'`, but
operators may define their own without a migration.

### `playbook_positions` (M3)

```sql
CREATE TABLE playbook_positions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    playbook_id         UUID NOT NULL REFERENCES playbooks(id) ON DELETE CASCADE,
    issue               TEXT NOT NULL,                                  -- e.g. 'Limitation of Liability'
    description         TEXT NOT NULL DEFAULT '',
    standard_language   TEXT NOT NULL,                                  -- the org's preferred clause
    fallback_tiers      JSONB NOT NULL DEFAULT '[]'::jsonb,             -- ranked acceptable alternatives
    redline_strategy    TEXT NOT NULL DEFAULT '',
    severity_if_missing TEXT NOT NULL
        CHECK (severity_if_missing IN ('critical','high','medium','low')),
    detection_keywords  TEXT[] NOT NULL DEFAULT '{}'::text[],           -- lexical match
    detection_examples  TEXT[] NOT NULL DEFAULT '{}'::text[],           -- embedding match
    position_order      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_playbook_positions_playbook_order
    ON playbook_positions(playbook_id, position_order);
```

The `fallback_tiers` JSONB array carries objects matching the Pydantic
`FallbackTier` shape (`{rank, description, language}`). Storing as
JSONB rather than a normalized table avoids a join on every executor
read — the per-position list is small (typically 2-3 alternatives) and
always loaded with the position.

`detection_keywords` and `detection_examples` feed the M3-A2 executor's
retrieval step: keywords drive a lexical match against the target
contract; examples drive an embedding-based match.

### `playbook_executions` (M3)

```sql
CREATE TABLE playbook_executions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    playbook_id         UUID NOT NULL REFERENCES playbooks(id) ON DELETE CASCADE,
    target_document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id             UUID REFERENCES users(id) ON DELETE SET NULL,
    project_id          UUID REFERENCES projects(id) ON DELETE SET NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','running','completed','error')),
    results             JSONB,                                          -- M3-A2 executor's payload
    error               TEXT,                                           -- populated when status='error'
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ
);

-- "My recent executions" view for the UI (M3-A4).
CREATE INDEX idx_playbook_executions_user_created
    ON playbook_executions(user_id, created_at DESC);

-- "What playbooks have been run against this document?" — drives the
-- document-detail view's playbook-history surface (M3-A4).
CREATE INDEX idx_playbook_executions_target_document
    ON playbook_executions(target_document_id);
```

Status lifecycle: `pending → running → completed | error`. The CHECK
constraint pins the enum at the storage layer.

`user_id` and `project_id` are both `ON DELETE SET NULL` so historical
executions survive operator or project deletion — audit trails stay
intact even after the actor or matter is removed. The
`target_document_id` FK is `ON DELETE CASCADE` because an execution
against a deleted document has no anchor (the source the executor
ran against is gone).

### `easy_playbook_generations` (M3-A6, migration 0035)

Backs the async Easy Playbook generation pipeline. `POST /api/v1/playbooks/easy`
returns 202 with a generation-row id; the ARQ worker on the `arq:m3a6`
queue runs the extract → cluster → assemble pipeline against the supplied
documents and writes progress back to this row. The Phase-6 wizard's
Step-3 inline editor consumes `draft_playbook` once `status='completed'`.

```sql
CREATE TABLE easy_playbook_generations (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID REFERENCES users(id) ON DELETE SET NULL,        -- fk_easy_playbook_generations_user_id
    contract_type  TEXT NOT NULL,                                       -- free-form per PRD §3.7 ('NDA', 'MSA-SaaS', ...)
    status         TEXT NOT NULL DEFAULT 'pending',
    document_ids   UUID[] NOT NULL DEFAULT '{}'::uuid[],                -- source corpus snapshot; NOT an FK (docs may be soft-deleted)
    draft_playbook JSONB,                                               -- assembled PlaybookCreate shape; populated on status='completed'
    error_message  TEXT,                                                -- populated on status='error'
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,                                         -- set on pending → running
    completed_at   TIMESTAMPTZ,                                         -- set on either terminal state
    CONSTRAINT chk_easy_playbook_generations_status
        CHECK (status IN ('pending','running','completed','error'))
);

-- The wizard's history view sorts the caller's recent generations by recency.
CREATE INDEX idx_easy_playbook_generations_user_recent
    ON easy_playbook_generations (user_id, created_at DESC);
```

`user_id` is `ON DELETE SET NULL` so historical generations survive
operator deletion (matches `playbook_executions`). `document_ids` is a
snapshot array, deliberately not an FK, so the audit row is preserved
even after a source document is soft-deleted.

---

## Tabular review (per [PRD §3.14](PRD.md#314-tabular--multi-document-review-m3), M3-C2)

Substrate for the Tabular / Multi-Document Review surface
([docs/tabular-review.md](tabular-review.md)) landing in M3. Each
execution walks a `documents × columns` grid and produces a
row-per-document by column-per-spec result, run as a LangGraph workflow
on the existing `arq:m3a6` queue (Decision C-3 from the Phase C prep
doc: reuse the queue rather than add a second worker container). One
table, introduced by migration `0036_tabular_executions.py`:

* `tabular_executions` — one row per execution; persists the inputs +
  status + assembled grid so the result view can re-render a week later.

### `tabular_executions` (M3)

```sql
CREATE TABLE tabular_executions (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID REFERENCES users(id) ON DELETE SET NULL,
    parent_execution_id  UUID REFERENCES tabular_executions(id) ON DELETE SET NULL,
    skill_name           TEXT,                                          -- filesystem-canonical skill name; NULL for ad-hoc column lists
    status               TEXT NOT NULL DEFAULT 'pending',
    document_ids         UUID[] NOT NULL DEFAULT '{}'::uuid[],          -- snapshot of source documents; NOT an FK
    columns              JSONB NOT NULL DEFAULT '[]'::jsonb,            -- resolved column spec snapshotted at execution start
    results              JSONB,                                         -- assembled grid; populated when status='completed'
    cost_estimate_usd    NUMERIC(10,4),                                 -- operator-confirmed estimate at start
    cost_actual_usd      NUMERIC(10,4),                                 -- backfilled incrementally as cells complete
    error_text           TEXT,                                          -- populated when status='failed'
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at           TIMESTAMPTZ,
    completed_at         TIMESTAMPTZ,
    deleted_at           TIMESTAMPTZ,                                   -- soft-delete

    CONSTRAINT chk_tabular_executions_status
        CHECK (status IN ('pending','running','completed','failed','cancelled')),
    CONSTRAINT fk_tabular_executions_user_id
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_tabular_executions_parent_execution_id
        FOREIGN KEY (parent_execution_id) REFERENCES tabular_executions(id) ON DELETE SET NULL
);

-- The list endpoint sorts the caller's non-deleted executions by recency.
CREATE INDEX idx_tabular_executions_user_recent
    ON tabular_executions (user_id, created_at DESC)
    WHERE deleted_at IS NULL;

-- Bulk-op siblings query their parent.
CREATE INDEX idx_tabular_executions_parent
    ON tabular_executions (parent_execution_id)
    WHERE parent_execution_id IS NOT NULL;
```

Status lifecycle: `pending → running → completed | failed | cancelled`.
The CHECK constraint pins the enum at the storage layer so an
application bug can't insert an invalid value. `cancelled` is reached
via `POST /tabular/executions/{id}/cancel` before the worker finishes;
all three terminal states set `completed_at`.

`user_id` is `ON DELETE SET NULL` so historical executions survive
operator deletion (matches `playbook_executions` and
`easy_playbook_generations`).

`parent_execution_id` is a nullable self-FK (`ON DELETE SET NULL`),
non-NULL only on bulk-op sibling rows. Per Decision C-9, a bulk
operation (e.g., "Redline column N") spawns a child `tabular_executions`
row pointing at the original rather than mutating the original grid —
preserving the original's auditability. Deleting a parent does not
cascade-delete its siblings.

`document_ids` is the snapshot of source document UUIDs from the
caller's selection. It is deliberately **not** a foreign key: documents
can be soft-deleted after the execution completes, and the audit row is
preserved regardless (matches the `easy_playbook_generations` pattern).
Document display names are carried inside the `results` grid rows, not
in a dedicated column.

`columns` is the resolved column spec snapshotted at execution start —
either the skill's `lq_ai.columns` block at that moment, or the
operator's ad-hoc list typed in the wizard's column step. Snapshotting
is the load-bearing invariant: re-rendering the grid later must be
honest about what was actually run, not what the skill currently says.

`results` is the assembled grid shape
`{rows: [{document_id, document_name, cells: {column_name: CellResult}}]}`,
populated once status is `completed` (may carry partial output on
`failed`).

Soft delete via `deleted_at` matches the `playbooks.deleted_at` posture
from M3-A6's migration 0034.

---

## Intake bridges (per [PRD §3.15](PRD.md#315-intake-bridges-m3), M3-D)

Substrate for the Slack and Microsoft Teams intake bridges
([docs/intake-bridges.md](intake-bridges.md)) landing in M3-D. Each
bridge runs its own OAuth install flow in a dedicated service
(`slack-bridge`, `teams-bridge`) and POSTs the resulting install tuple
to the backend, which persists one row per connected workspace/tenant.
Two tables, introduced by migrations `0037_slack_workspaces.py` and
`0038_teams_tenants.py`. Both use a natural-key unique constraint and
soft-delete; the persistence endpoints **upsert on the natural key**,
reviving a soft-deleted row (setting `deleted_at` back to NULL) on
re-install.

### `slack_workspaces` (M3-D1)

```sql
CREATE TABLE slack_workspaces (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id                  TEXT NOT NULL,                            -- Slack workspace id (T0123456...); natural key
    team_name                TEXT NOT NULL,                           -- snapshotted at install; not auto-refreshed
    bot_token_encrypted      BYTEA NOT NULL,                          -- Fernet-wrapped xoxb-... bot token
    bot_user_id              TEXT NOT NULL,                           -- Slack user id of the install's bot user (U0123456...)
    installer_slack_user_id  TEXT NOT NULL,                           -- operator who clicked install; audit-only
    scope                    TEXT NOT NULL,                           -- comma-separated OAuth scope list, verbatim
    installed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at               TIMESTAMPTZ,                             -- soft-delete; upsert revives to NULL

    CONSTRAINT uq_slack_workspaces_team_id UNIQUE (team_id)
);
```

`bot_token_encrypted` is `BYTEA` holding the Fernet ciphertext of the
bot user OAuth token (`xoxb-...`). It is encrypted at rest under
`LQ_AI_BRIDGE_MASTER_KEY` — deliberately **separate** from the
gateway's provider-key master key (Decision M3-D1-1: Slack bot tokens
enable bot impersonation, provider keys enable inference routing —
different blast radii, different keys). Decrypted in-memory only when
the bridge needs to post a reply.

`team_id` is the natural key from Slack's side and carries the only
unique constraint; the upsert path conflicts on it. Per Decision
M3-D1-2, Slack rotates the bot token on re-install, so the upsert
replaces `bot_token_encrypted` + `installer_slack_user_id` + `scope`
and revives `deleted_at`. No separate index on `team_id` — the unique
constraint's backing index covers it.

`installer_slack_user_id` is audit-only and grants no LQ.AI
permissions; `scope` is stored verbatim so an operator can audit what
the workspace consented to.

### `teams_tenants` (M3-D3)

```sql
CREATE TABLE teams_tenants (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      TEXT NOT NULL,                                    -- Microsoft tenant (M365 directory) GUID; natural key
    tenant_name    TEXT NOT NULL,                                   -- displayName at install; not auto-refreshed
    installer_oid  TEXT NOT NULL,                                   -- M365 oid claim of the admin who consented; audit-only
    installed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at     TIMESTAMPTZ,                                     -- soft-delete; upsert revives to NULL

    CONSTRAINT uq_teams_tenants_tenant_id UNIQUE (tenant_id)
);
```

There is **no encrypted-token column**, and this is deliberate. Unlike
Slack (which issues per-workspace bot tokens), Microsoft Teams uses
**app-level bot credentials** — the bot authenticates to the Bot
Framework with the operator's single `MICROSOFT_APP_ID` +
`MICROSOFT_APP_PASSWORD` regardless of which tenant it runs in. So
there is no per-tenant secret to persist; this table only carries the
identity-binding fields the admin UI (M3-D4) needs to surface "the bot
is installed in tenant X". (Per-user refresh-token storage for an M4
on-behalf-of flow is a future column, not present today.)

`tenant_id` is the natural key from Microsoft's side and carries the
only unique constraint. Per Decision M3-D3-2 the persistence endpoint
upserts on it: a re-install in the same M365 tenant replaces
`tenant_name` + `installer_oid` and revives `deleted_at`. The bridge
runs as a multi-tenant Microsoft identity-platform app (Decision
M3-D3-4), so this table can hold rows for many tenants concurrently.

`installer_oid` is audit-only and grants no LQ.AI permissions.

## Autonomous layer (per [PRD §3.10](PRD.md#310-autonomous-layer-m4), M4)

The per-user Autonomous agent's data substrate (migration
`0039_autonomous_layer.py`, M4-A1; see
[ADR-0013](adr/0013-autonomous-layer-design-influences.md)). Five
tables: the brake-bearing run record (`autonomous_sessions`) plus four
primitive tables for triggers (`autonomous_schedules`,
`autonomous_watches`), curated memory (`autonomous_memory`), and
observed precedent (`precedent_entries`).

**Hard per-user isolation.** Every table carries a non-null `user_id`
FK with `ON DELETE CASCADE`. Unlike the playbook tables (which
`SET NULL` to preserve shared audit history), autonomous state is
private to the operator who ran it and carries no shared work product,
so a user's deletion removes all of their autonomous state.

### `autonomous_sessions` (M4)

The run record carrying the brakes — cost cap, halt state, idle-halt
window, and the phase machine the executor (later M4 tasks) walks.
`halt_state` is orthogonal to `status`: `status` is the terminal-or-
running lifecycle, `halt_state` is the brake the executor checks at
every step.

```sql
CREATE TABLE autonomous_sessions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,        -- fk_autonomous_sessions_user_id
    project_id        UUID REFERENCES projects(id) ON DELETE SET NULL,             -- fk_autonomous_sessions_project_id
    trigger_kind      TEXT NOT NULL CHECK (trigger_kind IN ('watch','schedule','suggestion','manual')),
    trigger_ref       UUID,                                                        -- id of the schedule/watch/suggestion that started it
    current_phase     TEXT NOT NULL DEFAULT 'intake'
                          CHECK (current_phase IN ('intake','analysis','drafting','ethics_review','delivery')),
    halt_state        TEXT NOT NULL DEFAULT 'running'
                          CHECK (halt_state IN ('running','halt_requested','halted','paused')),
    max_cost_usd      NUMERIC(10,4),                                               -- per-session cost cap; NULL = no cap
    cost_total_usd    NUMERIC(10,4) NOT NULL DEFAULT 0,                            -- accumulates as the executor spends
    cost_cap_reached  BOOLEAN NOT NULL DEFAULT FALSE,                              -- latches TRUE when the cap is hit
    idle_halt_minutes INT NOT NULL DEFAULT 5,                                      -- self-halt after this much inactivity
    last_activity_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    status            TEXT NOT NULL DEFAULT 'running'
                          CHECK (status IN ('running','completed','halted','failed')),
    result            JSONB,
    error             TEXT,
    -- M4-B3 (migration 0042): trigger→target seam. Every trigger source
    -- populates the non-null subset of {kb_id, playbook_id, skill_ref,
    -- query}; the executor reads it into initial_state — uniform across
    -- all trigger kinds, decoupled from the schedule/watch tables.
    params            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ
);

-- "My recent sessions" view for the UI.
CREATE INDEX idx_autonomous_sessions_user_created ON autonomous_sessions(user_id, created_at DESC);
-- The scheduler's "which running sessions need a halt/idle check?" scan (partial).
CREATE INDEX idx_autonomous_sessions_active ON autonomous_sessions(halt_state, last_activity_at) WHERE status = 'running';
```

### `autonomous_schedules` (M4)

A cron-triggered run definition. `cron_expr` is a standard five-field
cron string. `playbook_id` / `skill_ref` / `target_kb_id` describe what
the triggered session runs. Soft-deleted via `deleted_at`.

```sql
CREATE TABLE autonomous_schedules (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,           -- fk_autonomous_schedules_user_id
    project_id    UUID REFERENCES projects(id) ON DELETE SET NULL,                -- fk_autonomous_schedules_project_id
    name          TEXT,
    cron_expr     TEXT NOT NULL,
    playbook_id   UUID REFERENCES playbooks(id) ON DELETE SET NULL,               -- fk_autonomous_schedules_playbook_id
    skill_ref     TEXT,
    target_kb_id  UUID REFERENCES knowledge_bases(id) ON DELETE SET NULL,         -- fk_autonomous_schedules_target_kb_id
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at   TIMESTAMPTZ,
    next_run_at   TIMESTAMPTZ,
    -- M4 real-executor work (migration 0045): per-schedule cost cap.
    -- NULL = fall back to settings.autonomous_default_max_cost_usd at spawn.
    max_cost_usd  NUMERIC(10,4),
    deleted_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- M4-B3 (migration 0042): the dispatcher scan
--   WHERE enabled AND deleted_at IS NULL AND next_run_at <= now()
-- The partial predicate matches the always-true filter so the planner
-- reads only live, enabled schedules ordered by next_run_at.
CREATE INDEX idx_autonomous_schedules_due
    ON autonomous_schedules (next_run_at)
    WHERE enabled AND deleted_at IS NULL;
```

### `autonomous_watches` (M4)

A KB-change-triggered run definition. When the watched
`knowledge_base_id` changes (a new file ingested), the agent starts a
session running `playbook_id` / `skill_ref` against the change.
Soft-deleted via `deleted_at`.

```sql
CREATE TABLE autonomous_watches (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,      -- fk_autonomous_watches_user_id
    project_id         UUID REFERENCES projects(id) ON DELETE SET NULL,           -- fk_autonomous_watches_project_id
    knowledge_base_id  UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,  -- fk_autonomous_watches_knowledge_base_id
    playbook_id        UUID REFERENCES playbooks(id) ON DELETE SET NULL,          -- fk_autonomous_watches_playbook_id
    skill_ref          TEXT,
    enabled            BOOLEAN NOT NULL DEFAULT TRUE,
    -- M4 real-executor work (migration 0045): per-watch cost cap.
    -- NULL = fall back to settings.autonomous_default_max_cost_usd at spawn.
    max_cost_usd       NUMERIC(10,4),
    deleted_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The watch dispatcher's "which watches fire for this KB?" lookup; only live, enabled watches matter (partial).
CREATE INDEX idx_autonomous_watches_kb_enabled ON autonomous_watches(knowledge_base_id) WHERE enabled AND deleted_at IS NULL;
```

### `autonomous_memory` (M4)

Memory notes the agent proposes for user curation. `state` walks
`proposed → kept | dismissed`. `category` is a free-form bucket (e.g.
`drafting_preference`). `source_session_id` links back to the proposing
session (`SET NULL` if that session is later deleted). Soft-deleted via
`deleted_at`.

```sql
CREATE TABLE autonomous_memory (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,      -- fk_autonomous_memory_user_id
    state              TEXT NOT NULL CHECK (state IN ('proposed','kept','dismissed')),
    category           TEXT NOT NULL,
    content            TEXT NOT NULL,
    source_session_id  UUID REFERENCES autonomous_sessions(id) ON DELETE SET NULL,  -- fk_autonomous_memory_source_session_id
    kept_at            TIMESTAMPTZ,
    deleted_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The "show me my memory notes in state X" curation view.
CREATE INDEX idx_autonomous_memory_user_state ON autonomous_memory(user_id, state);
```

### `precedent_entries` (M4)

Observed precedent patterns across a user's sessions. `pattern_kind` is
a free-form classifier; `observed_count` increments each time the
pattern recurs. `source_session_id` links to the first observing
session (`SET NULL` on delete). `dismissed_at` is set when the user
dismisses the precedent.

```sql
CREATE TABLE precedent_entries (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,      -- fk_precedent_entries_user_id
    pattern_kind       TEXT NOT NULL,
    summary            TEXT NOT NULL,
    observed_count     INT NOT NULL DEFAULT 1,
    source_session_id  UUID REFERENCES autonomous_sessions(id) ON DELETE SET NULL,  -- fk_precedent_entries_source_session_id
    dismissed_at       TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The "my live precedents for pattern kind X" lookup; dismissed precedents drop out (partial).
CREATE INDEX idx_precedent_entries_user_kind ON precedent_entries(user_id, pattern_kind) WHERE dismissed_at IS NULL;

-- M4-B2 (migration 0041): backs the race-safe propose_precedent upsert
-- (INSERT ... ON CONFLICT). The recurrence key is (user_id, pattern_kind,
-- summary), but `summary` is unbounded TEXT and a btree tuple has a
-- ~2704-byte limit; hashing with md5() yields a fixed 32-char digest. The
-- partial WHERE preserves "a dismissed precedent is not reused": a new
-- observation after dismissal does not conflict and inserts a fresh row.
CREATE UNIQUE INDEX uq_precedent_entries_user_kind_summary_active
    ON precedent_entries (user_id, pattern_kind, md5(summary))
    WHERE dismissed_at IS NULL;
```

> **Note (UUID default):** these tables use `gen_random_uuid()` (UUIDv4)
> rather than the doc-aspirational `uuid_generate_v7()`, matching what
> the migrations actually ship (see the Conventions note and the
> `audit_log` / `inference_routing_log` precedent above).

### `autonomous_notifications` (M4-A3.2)

In-app notification substrate written by the `notify` chokepoint handler
(A3.3). Pulled forward from M4-C1 so A3.3 has a durable write target.
M4-C1 adds email/SMTP transport, the read/dismiss API, the web surface,
and webhook dispatch.

**Hard per-user isolation.** Both `user_id` and `session_id` carry `ON
DELETE CASCADE` — notifications cascade with their parent session and
their owner user.

**Channel enum.** `channel` allows `('in_app','email','webhook')`. The
`webhook` value is **RESERVED** (not dispatched until DE-312, Decision
M4-8); its presence means M4-C1's fold-in is purely additive.

**Body contract.** `body` carries counts/types/IDs + a link to the
receipt — **never raw entity values**. `payload` is optional structured
JSONB the web renders (same constraint).

**Read index (added in migration 0043, M4-C1).** Migration 0040 deferred
the read index until the read-API query shape was concrete; 0043 adds it
now that the shape is known —
`GET /api/v1/autonomous/notifications WHERE user_id = :u [AND read_at IS NULL] ORDER BY created_at DESC`.
The index is a **partial** `(user_id, created_at DESC) WHERE read_at IS NULL`,
serving the hot `?unread=true` query (the predicate matches `read_at IS NULL`
exactly; the `created_at DESC` trailing column matches the newest-first sort).
The all-notifications list is low-volume per user and rides the `user_id`
prefix.

```sql
CREATE TABLE autonomous_notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,               -- fk_autonomous_notifications_user_id
    session_id  UUID NOT NULL REFERENCES autonomous_sessions(id) ON DELETE CASCADE, -- fk_autonomous_notifications_session_id
    channel     TEXT NOT NULL DEFAULT 'in_app'
                    CHECK (channel IN ('in_app','email','webhook')),                 -- chk_autonomous_notifications_channel
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,  -- counts/types/IDs + receipt link; NO raw entity values
    payload     JSONB,          -- optional structured counts/IDs for the web (no raw values)
    read_at     TIMESTAMPTZ,    -- NULL = unread; set by M4-C1 read/dismiss API
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Migration 0043 (M4-C1): partial read index serving
--   GET /autonomous/notifications?unread=true
--   WHERE user_id = :u AND read_at IS NULL ORDER BY created_at DESC
CREATE INDEX idx_autonomous_notifications_user_unread
    ON autonomous_notifications (user_id, created_at DESC)
    WHERE read_at IS NULL;
```

### `project_context_proposals` (M4-B2, migration 0041)

Records the autonomous agent's *proposals* to promote a recurring
precedent into a Project's context document. The agent NEVER writes
`projects.context_md` directly (ADR 0013 D5): it writes a proposal here,
and the user accepting it
(`POST /autonomous/project-context-proposals/{id}/accept`) is the
authorized write that appends `suggested_md` to the Project's context.

**Hard per-user isolation.** All three FKs (`user_id`, `precedent_id`,
`project_id`) are `ON DELETE CASCADE` — a proposal is meaningless without
its precedent or target project, and autonomous state is private to its
owner.

```sql
CREATE TABLE project_context_proposals (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,                 -- fk_project_context_proposals_user_id
    precedent_id  UUID NOT NULL REFERENCES precedent_entries(id) ON DELETE CASCADE,      -- fk_project_context_proposals_precedent_id
    project_id    UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,               -- fk_project_context_proposals_project_id
    suggested_md  TEXT NOT NULL,                                                         -- server-derived from the precedent's summary at promote time
    state         TEXT NOT NULL DEFAULT 'proposed',
    accepted_at   TIMESTAMPTZ,
    rejected_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_project_context_proposals_state
        CHECK (state IN ('proposed','accepted','rejected'))
);

-- (user_id, state) backs the per-user, state-filtered list query that
-- GET /autonomous/project-context-proposals issues.
CREATE INDEX idx_project_context_proposals_user_state
    ON project_context_proposals (user_id, state);
```

## M4+ tables (sketched, land at the indicated milestone)

### `autonomous_tasks` (M4 — **superseded**)

> **Superseded by `autonomous_sessions` + the four primitive tables
> above.** `autonomous_tasks` was a single-table sketch that conflated
> the run record with its triggers. Per [ADR-0013](adr/0013-autonomous-layer-design-influences.md)
> the M4 design (landed in migration `0039`, M4-A1) split it into the
> brake-bearing `autonomous_sessions` run record plus
> `autonomous_schedules` / `autonomous_watches` (triggers),
> `autonomous_memory`, and `precedent_entries`. This block is retained
> only as a record of the original sketch; it is not created by any
> migration.

### `contract_relationships` (M4 — Contract Repository auto-relationship detection; **not built**)

> **Status: NOT created by any migration.** The Contract Repository
> auto-relationship graph is an M4-roadmap capability that was **not**
> built (see [HONEST-STATE.md](HONEST-STATE.md) §M4). The block below is
> the original sketch, retained as a forward-looking record only.

```sql
CREATE TABLE contract_relationships (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    kb_id           UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    source_file_id  UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    target_file_id  UUID NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    relationship    TEXT NOT NULL CHECK (relationship IN ('amends','restates','references','master_of','sub_of')),
    confidence      NUMERIC(3,2) CHECK (confidence BETWEEN 0 AND 1),
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (kb_id, source_file_id, target_file_id, relationship)
);

CREATE INDEX idx_relationships_source ON contract_relationships(source_file_id);
CREATE INDEX idx_relationships_target ON contract_relationships(target_file_id);
```

---

## Schema diagram (logical)

```
                        ┌──────────────┐
                        │    users     │◄────────────────────────┐
                        └──────┬───────┘                         │
                               │                                  │
                ┌──────────────┼──────────────┐                  │
                ▼              ▼              ▼                  │
        ┌──────────────┐ ┌──────────────┐ ┌──────────────┐      │
        │   projects   │ │    chats     │ │    files     │      │
        └──────┬───────┘ └──────┬───────┘ └──────┬───────┘      │
               │                │                 │              │
        ┌──────┴──────┐  ┌──────┴──────┐         ▼              │
        ▼             ▼  ▼             ▼  ┌──────────────┐      │
  attached_skills  files  attached_skills  │   documents  │      │
  attached_files  messages attached_files  └──────┬───────┘      │
                     │                            ▼              │
                     ▼                    ┌──────────────┐      │
              message_citations            │document_chunks│     │
                                           └──────────────┘      │
                                                                  │
    ┌──────────────┐    ┌──────────────┐                         │
    │    skills    │    │  knowledge_  │                         │
    │              │    │    bases     │                         │
    └──────┬───────┘    └──────┬───────┘                         │
           │                    │                                 │
           ▼                    ▼                                 │
  reference_files       knowledge_base_files                     │
  example_files                                                   │
                                                                  │
    ┌──────────────────────────────────┐                         │
    │         audit_log                │─────────────────────────┘
    │  (privilege_marked, tier, etc.)  │
    └──────────────────────────────────┘
    ┌──────────────────────────────────┐
    │     inference_routing_log        │
    └──────────────────────────────────┘
```

---

## Migration approach

- **Alembic** for schema migrations. **Migration head is `0045`.** The
  `0001`–`0045` sequence in `api/alembic/versions/` is the schema truth;
  this document is reconciled to it.
- `0001_initial.py` creates the core M1 tables (`users`, `user_sessions`,
  `audit_log`, `inference_routing_log`, and the M1 foundation). Note:
  there is **no** `skills` SQL table — built-in skills are
  filesystem-canonical per ADR 0004; user/team skills land in
  `user_skills` (`0013`).
- M1 continues: files (`0003`), projects + documents/chunks (`0004`/`0005`),
  chats + messages (`0006`), knowledge bases (`0007`), user_export_jobs
  (`0009`), organization_profile (`0010`), saved_prompts (`0011`),
  user_skills (`0013`), teams + team_members (`0014`),
  enhance_prompt_interactions (`0015`), work_product_attribution (`0017`),
  project_knowledge_bases (`0021`).
- M2 (`0024`–`0029`) adds citation-engine fields and `message_citations`.
- M3 adds playbooks + positions + executions (`0031`),
  easy_playbook_generations (`0035`), tabular_executions (`0036`), and the
  intake-bridge tables slack_workspaces (`0037`) + teams_tenants (`0038`).
- M4 adds the autonomous layer: `0039` (autonomous_sessions,
  autonomous_schedules, autonomous_watches, autonomous_memory,
  precedent_entries — superseding the sketched `autonomous_tasks`),
  `0040` (autonomous_notifications), `0041` (project_context_proposals +
  precedent upsert index), `0042` (autonomous_sessions.params +
  schedule due-index), `0043` (notifications read-index), `0044`
  (users.autonomous_enabled), `0045` (per-trigger max_cost_usd on
  watches + schedules). `contract_relationships` remains a sketch — it is
  **not** created by any migration (see the M4+ sketched section).

Migration conventions:
- Every migration is reversible (`downgrade()` always implemented).
- Every migration runs in a transaction.
- Backfill scripts for data-shape changes are in `scripts/backfill/`.
- Migration testing: spin up clean Postgres, run all migrations, run all-down + all-up cycle, verify schema is identical.

---

## Performance baseline expectations

- **Hot path:** `messages` and `inference_routing_log` see write-heavy traffic. Indexes minimized on these tables to reduce write amplification.
- **Audit log:** writes are queued and batched (every ~100ms or 100 entries) to reduce contention. Async-safe append.
- **Vector search:** ivfflat with `lists = 100` is appropriate for KBs up to ~1M chunks. Beyond that, transition to hnsw (Postgres 16+ supports it natively in pgvector 0.5+).
- **Full-text:** `tsvector` with GIN index handles document-corpus FTS well; for very large corpora (10M+ chunks), consider partitioning by knowledge_base_id.

---

*Schema maintained alongside the PRD. Substantive changes are documented in PRD §9 deferred-enhancements (if forward-looking) or in the changelog of the migration that lands them.*
