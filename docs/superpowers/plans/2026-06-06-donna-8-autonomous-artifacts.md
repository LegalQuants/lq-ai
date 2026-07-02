# Donna ask #8 — document-grade artifacts from autonomous runs

**Date:** 2026-06-06 · **Branch:** `feat/donna-8-autonomous-artifacts` · **Base:** `d95cddf`
**Source ask:** Donna "document-grade artifacts from autonomous runs" (filed 2026-06-06, follow-up to findings ask shipped as #135 / `0097b01`).

## Decisions (locked by Kevin at kickoff, 2026-06-06)

- **D8-1 Storage shape = (a) direct-write.** The artifact lands in the run's
  target KB as a real document: the chokepoint handler synchronously creates a
  `File` row (mime `text/markdown`, `ingestion_status='ready'`), uploads bytes
  via `upload_bytes`, creates the `Document` + chunks directly (markdown is
  already text — the PDF-only ingest pipeline is NOT touched), attaches to the
  KB via direct `KnowledgeBaseFile` insert, and enqueues the existing embed
  job best-effort. A new `autonomous_artifacts` reference table carries
  provenance.
- **D8-2 Opt-in, default off.** New `emit_artifacts` boolean on
  `autonomous_schedules` + `autonomous_watches` (server_default false). The
  artifact instruction is appended to the analysis prompt ONLY when set;
  existing automations see zero behavior/cost change.

## Derived design (conventions, not forks)

- **Deletion semantics:** `autonomous_artifacts.session_id` FK CASCADE (ref
  dies with session); `file_id` FK SET NULL (the KB document OUTLIVES the
  session — it is the user's deliverable). No `user_id` column: authz via the
  owning session, exactly like `autonomous_findings`.
- **Self-ingestion echo prevention:** mode-3 (`since`) retrieval in
  `_handle_retrieve_chunks_since` excludes files referenced by
  `autonomous_artifacts` — otherwise every schedule tick re-analyzes the
  previous tick's memo. Query-mode retrieval and chat RAG deliberately KEEP
  artifacts retrievable (that is the point of shape (a)).
- **No watch loop:** the artifact KB attach is a direct DB insert;
  `fire_watches_for_kb` only fires from the `attach_file` API handler, so an
  artifact arriving in a watched KB does not spawn a new run.
- **No-target-KB runs:** skip persistence, handler returns
  `data={"skipped": "no_target_kb"}`, drafting node emits ONE `info` finding
  saying why (Donna's stated fallback).
- **Artifact content source:** the existing single analysis inference call —
  the structured-output JSON gains an optional `artifacts:
  [{"name", "content_md"}]` key (only instructed when opted in). No second
  inference call; `emit_artifact` is a local zero-cost intent.
- **Defense-in-depth:** drafting node dispatches `emit_artifact` only when
  `session.params["emit_artifacts"]` is truthy, even if the model emits the
  key unasked. R6 additionally grants `emit_artifact` in `drafting` only.
- **Free-text tolerance:** `name`/`mime` are LLM-emitted → no CHECKs (the
  `autonomous_findings.severity` precedent). Content clamped to 1,000,000
  chars (truncated, not rejected) so an over-long emission still persists.
- **Read model:** `GET /api/v1/autonomous/sessions/{id}/artifacts` mirrors the
  findings endpoint exactly — owner-gated via `_load_owned_session`, 404
  id-probing-safe, `created_at` ASC, limit clamped [1,200]. `document_id` is
  resolved at read time via the unique `documents.file_id` (NULL after a file
  hard-delete).
- **Notification:** delivery `notify` payload gains `artifact_count` next to
  `finding_count`; body says "… N finding(s), M document(s)" when M>0.
- **Out of scope** (per the ask): PDF/DOCX rendering, artifact
  editing/versioning, artifacts for interactive chat/playbook paths. The
  md/txt ingest-parser gap surfaced during verification is filed as a DE, not
  absorbed.

## Tasks

### Task 1 — Substrate: model + migration 0047 + schemas

- `AutonomousArtifact` in `api/app/models/autonomous.py`: `id`, `session_id`
  (FK `autonomous_sessions` CASCADE, not null), `file_id` (FK `files`
  SET NULL, nullable), `name` TEXT NOT NULL, `mime` TEXT NOT NULL,
  `size_bytes` BIGINT NOT NULL, `created_at`. Index on `session_id`.
- `emit_artifacts` BOOLEAN NOT NULL server_default `false` on
  `autonomous_schedules` and `autonomous_watches`.
- Migration `0047` (down_revision `0046`), both directions.
- Schemas in `api/app/schemas/autonomous.py`: `AutonomousArtifactRead`
  (id, name, mime, size_bytes, file_id, document_id, created_at),
  `AutonomousArtifactListResponse` (artifacts, total_count, limit, offset) —
  mirror the finding schemas; add `emit_artifacts: bool = False` to schedule
  and watch Create/Update/Read schemas.
- Verify migration via throwaway pgvector container ONLY (never the live dev
  DB at 127.0.0.1:15432).

### Task 2 — `emit_artifact` intent + chokepoint handler + echo exclusion

- `ToolIntent.emit_artifact`; `PHASE_GRANTS[Phase.drafting]` gains it
  (drafting ONLY).
- Handler in `guard.py::_dispatch` — params `{"artifact": {"name", "content",
  "mime"?}}`, zero cost, flush-not-commit like siblings:
  1. `kb_id = session.params.get("kb_id")`; missing → return
     `ToolResult(data={"skipped": "no_target_kb"})`.
  2. Sanitize `name` (strip path separators, default `artifact.md`, ensure an
     extension); clamp content at 1,000,000 chars; `mime` default
     `text/markdown`.
  3. Upload FIRST (no DB state on storage failure): `File` row
     (owner=`session.user_id`, project_id=`session.project_id`,
     storage_path=str(file.id) per ADR 0005, `ingestion_status='ready'`,
     sha256, size); `app.storage.upload_bytes`. Storage failure → return
     `ToolResult(outcome="storage_error", data={"error": …})` with no rows
     (mirrors the gateway_error honesty pattern).
  4. `Document` (parser `"autonomous-artifact"`, `page_count=1`,
     `normalized_content=content`, `character_count`, `was_ocrd=False`) +
     chunks via `chunk_document` over a synthetic single-page
     `ParsedDocument` — preserves the M2-A1 re-read invariant.
  5. Direct `KnowledgeBaseFile(kb_id, file_id)` insert (NOT the attach API —
     no watch fire). Tolerate the duplicate-attach IntegrityError path
     defensively.
  6. `AutonomousArtifact` row; best-effort
     `app.workers.queue.enqueue_embed_job(file_id)` wrapped try/except (the
     notify-email pattern; lazy embed-on-read covers the gap).
  7. `data={"artifact_id", "file_id", "document_id", "name", "size_bytes"}`.
- Mode-3 echo exclusion in `_handle_retrieve_chunks_since`:
  `FileModel.id NOT IN (SELECT file_id FROM autonomous_artifacts WHERE
  file_id IS NOT NULL)`.
- Tests (`api/tests/autonomous/`): happy-path persistence (file + doc +
  chunks + attach + ref row + data shape), no-kb skip, storage failure (no
  orphan rows), oversize truncation, R6 rejects `emit_artifact` outside
  drafting, mode-3 exclusion regression (artifact file not re-retrieved).

### Task 3 — Flag plumbing: spawn paths, prompt, parser, nodes

- Spawn paths copy the flag into `session.params` (non-null-subset
  convention — only set when true): `watch_trigger.fire_watches_for_kb`
  (from `watch.emit_artifacts`), the schedule sweep in
  `api/app/workers/autonomous_worker.py` (from `schedule.emit_artifacts`),
  `_spawn_manual_session` in `api/app/api/autonomous.py` (run-now inherits
  the schedule's flag).
- `prompts.py`: new `ARTIFACT_OUTPUT_INSTRUCTION` documenting the optional
  `"artifacts": [{"name": "...", "content_md": "..."}]` key; appended in
  `assemble_analysis_messages` ONLY when `session.params.get("emit_artifacts")`.
- `structured_output.py`: `StructuredResult.artifacts` parsed via `_as_list`.
- `nodes.py` drafting case 4: when the session flag is set, dispatch each
  parsed artifact via `guarded_tool_call(emit_artifact)`; count successful
  persists as `artifacts_count`; a `skipped: no_target_kb` result emits ONE
  `info` finding ("Artifact not persisted — run has no target knowledge
  base"); `storage_error` emits ONE `warn` finding. Flag off → parsed
  artifacts ignored.
- Delivery node: `notify` body appends ", M document(s)" when M>0; payload
  `{"finding_count": n, "artifact_count": m}`; `completed` audit row gains
  `artifacts_count`.
- Tests: prompt conditional on/off, parser artifacts (+ tolerance), drafting
  dispatch on/off + skip/storage findings, delivery payload + body.

### Task 4 — Read endpoint + contract + docs

- `GET /api/v1/autonomous/sessions/{session_id}/artifacts` — clone of
  `list_session_findings` (owner-gated, 404-safe, clamp [1,200],
  `created_at` ASC); enrich `document_id` via one `IN`-query join on
  `documents.file_id`.
- `create_schedule`/`update_schedule`/`create_watch`/`update_watch` accept +
  persist `emit_artifacts`; reads echo it.
- `docs/api/backend-openapi.yaml`: new path + `AutonomousArtifactRead`/
  `…ListResponse` components + `emit_artifacts` on the 6 schedule/watch
  schemas + notification-payload description note. `api/tests/test_openapi.py`
  path count 117 → 118 + `EXPECTED_PATHS`; new route into
  `IMPLEMENTED_ROUTES` (`tests/test_endpoints.py`).
- Docs: `docs/db-schema.md` (table + 2 columns), `docs/autonomous-layer.md`
  (artifacts section: opt-in flag, direct-write shape, deletion semantics,
  echo/loop prevention), PRD §9 DE-332 (text/markdown ingest-parser support —
  the gap that forced direct-write).
- Tests: endpoint authz (another user's session → 404), pagination + ASC,
  `document_id` enrichment incl. NULL-file case, schedule/watch flag
  round-trip (create → read → patch → read), OpenAPI conformance green.

## Gates (after every task, run by the controller)

`ruff format --check` + `ruff check` + `mypy app` over `api/`; targeted
pytest for the touched suites; full
`pytest tests/autonomous tests/test_openapi.py tests/test_endpoints.py`
before PR. Migration verified on the throwaway pgvector container.

## Loop conventions

DCO `-s` + `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`;
explicit staging (never `git add -A` — `docs/lq-ai-skill-inputs-corpus.md`
stays untracked); push both remotes; PR; CI watch; merge gating decision
(this touches an authz-adjacent KB write path → offer Kevin review) before
merge; report squash SHA for Donna's pin.
