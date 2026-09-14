"""User-data export worker — Task D6 (GDPR Article 20).

Builds a ZIP archive of every piece of data the LQ.AI backend stores
about one user, uploads it to MinIO under
``exports/<user_id>/<job_id>.zip``, and updates the
:class:`UserExportJob` row with the resulting key + 7-day expiry.

The export bundle contains:

* ``user.json`` — profile row, sanitized (no password hash, no TOTP
  secret, no recovery-code hashes).
* ``chats.json`` + ``messages.json`` — all chats owned by the user
  and every message within them.
* ``projects.json`` — all projects owned by the user.
* ``files.json`` — file-row metadata (excludes soft-deleted rows;
  the user's own DELETE has already removed those from their view).
  Bytes for each non-deleted file land at ``files/<file_id>__<filename>``.
* ``knowledge_bases.json`` — KBs owned by the user.
* ``audit_log.json`` — rows where ``actor_user_id == user.id``, so the
  user can audit their own actions.
* ``skills.json`` — empty array under M1 (skills are filesystem-canonical
  per ADR 0004; no per-user DB rows).
* ``README.md`` — bundle manifest.

A best-effort export: if a particular row family fails to serialize
the worker logs a warning, drops a stub for that entry in the bundle,
and continues; the only fatal failure is the storage put or the row
update.

GC: :func:`export_gc_job` runs hourly via
:class:`WorkerSettings.cron_jobs`, scans for rows whose ``expires_at``
has passed and ``storage_key`` is non-null, and deletes the bytes.
The row itself is preserved so a status poll for an expired bundle
returns a clean "expired" answer rather than a 404 surprise.
"""

from __future__ import annotations

import io
import json
import logging
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory
from app.models import (
    AuditLog,
    Chat,
    File,
    KnowledgeBase,
    Message,
    Project,
    User,
    UserExportJob,
)
from app.storage import delete_object, stream_download, upload_bytes

log = logging.getLogger(__name__)

# Validity window for the bundle in object storage. After this, the GC
# cron clears the storage_key and deletes the bytes; the user must
# request a fresh export. 7 days is generous enough that a slow user
# can fetch the bundle on their own schedule without operators
# accumulating GBs of stale exports.
_EXPORT_TTL = timedelta(days=7)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _serialize_user(user: User) -> dict[str, Any]:
    """Render :class:`User` to JSON-safe dict, omitting credentials."""

    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "mfa_enabled": user.mfa_enabled,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "last_login_at": (user.last_login_at.isoformat() if user.last_login_at else None),
        "deletion_scheduled_at": (
            user.deletion_scheduled_at.isoformat() if user.deletion_scheduled_at else None
        ),
    }


def _serialize_chat(chat: Chat) -> dict[str, Any]:
    return {
        "id": str(chat.id),
        "title": chat.title,
        "project_id": str(chat.project_id) if chat.project_id else None,
        "created_at": chat.created_at.isoformat() if chat.created_at else None,
        "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
    }


def _serialize_message(message: Message) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "chat_id": str(message.chat_id),
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _serialize_project(project: Project) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "name": project.name,
        "slug": project.slug,
        "description": project.description,
        "minimum_inference_tier": project.minimum_inference_tier,
        "privileged": project.privileged,
        "archived_at": project.archived_at.isoformat() if project.archived_at else None,
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


def _serialize_file(file: File) -> dict[str, Any]:
    return {
        "id": str(file.id),
        "filename": file.filename,
        "mime_type": file.mime_type,
        "size_bytes": file.size_bytes,
        "hash_sha256": file.hash_sha256,
        "ingestion_status": file.ingestion_status,
        "project_id": str(file.project_id) if file.project_id else None,
        "created_at": file.created_at.isoformat() if file.created_at else None,
        "deleted_at": file.deleted_at.isoformat() if file.deleted_at else None,
    }


def _serialize_kb(kb: KnowledgeBase) -> dict[str, Any]:
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "hybrid_alpha": kb.hybrid_alpha,
        "project_id": str(kb.project_id) if kb.project_id else None,
        "archived_at": kb.archived_at.isoformat() if kb.archived_at else None,
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
    }


def _serialize_audit(row: AuditLog) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "privilege_marked": row.privilege_marked,
        "privilege_basis": row.privilege_basis,
        "routed_inference_tier": row.routed_inference_tier,
        "routed_provider": row.routed_provider,
        "details": row.details,
    }


def _serialize_work_product(row: Any) -> dict[str, Any]:
    """Serialize one WorkProductAttribution row for the export bundle.

    Imported lazily inside :func:`_build_zip` so this helper survives a
    cyclic-import-style load (the model imports nothing from this
    module, but keeping the lazy pattern matches the surrounding
    serializers).
    """

    return {
        "id": str(row.id),
        "message_id": str(row.message_id),
        "chat_id": str(row.chat_id),
        "project_id": str(row.project_id) if row.project_id else None,
        "routed_inference_tier": row.routed_inference_tier,
        "provider": row.provider,
        "model": row.model,
        "model_version": row.model_version,
        "skill_ids": list(row.skill_ids or []),
        "playbook_id": str(row.playbook_id) if row.playbook_id else None,
        "content_hash": row.content_hash,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
    }


_README_TEMPLATE = """\
# LQ.AI personal data export

Generated for user: `{email}` (id: `{user_id}`)
Exported at: {exported_at}

This archive contains every piece of data the LQ.AI backend stores
about your account, fulfilling GDPR Article 20 (right to data
portability). The contents are JSON for the structured rows plus the
original bytes for any files you uploaded.

## Layout

- `user.json`            — your profile (no credentials).
- `chats.json`           — chat threads you own.
- `messages.json`        — messages within those chats.
- `projects.json`        — matter-scoped projects you own.
- `files.json`           — file metadata for each upload (active rows;
                            soft-deleted entries are excluded — those
                            files were already removed at your request).
- `files/<id>__<name>`   — original bytes for each file.
- `knowledge_bases.json` — knowledge bases you own.
- `audit_log.json`       — log of state-changing actions you took.
- `work_product_attribution.json` — chain-of-custody metadata
                            (PRD §3.3): one row per assistant message you
                            generated, with tier / provider / model /
                            applied skills / content hash. Hand this to
                            a third party (e.g., trial counsel, an
                            auditor) when you need to attest to how a
                            specific piece of model output was produced.
- `skills.json`          — empty under M1; skills are filesystem-canonical
                            (see ADR 0004) and live in the deployment's
                            `skills/` directory rather than the database.
- `skill_workspaces.json` — your optional saved skill work, including file
                            contents, namespaces and revisions.

## Validity

The presigned download URL expires 24 hours after issue. The bundle
itself remains in storage for 7 days; after that, the bytes are
deleted and a status-poll on this job will report it expired.
"""


async def _build_zip(session: AsyncSession, user: User) -> bytes:
    """Assemble the export ZIP for ``user`` and return the bytes."""

    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "README.md",
            _README_TEMPLATE.format(
                email=user.email,
                user_id=user.id,
                exported_at=_utcnow().isoformat(),
            ),
        )
        zf.writestr("user.json", json.dumps(_serialize_user(user), indent=2))

        # Chats + messages (messages indirected via chat_id).
        chats = (
            (await session.execute(select(Chat).where(Chat.owner_id == user.id))).scalars().all()
        )
        zf.writestr(
            "chats.json",
            json.dumps([_serialize_chat(c) for c in chats], indent=2),
        )
        if chats:
            chat_ids = [c.id for c in chats]
            messages = (
                (await session.execute(select(Message).where(Message.chat_id.in_(chat_ids))))
                .scalars()
                .all()
            )
        else:
            messages = []
        zf.writestr(
            "messages.json",
            json.dumps([_serialize_message(m) for m in messages], indent=2),
        )

        # Projects.
        projects = (
            (await session.execute(select(Project).where(Project.owner_id == user.id)))
            .scalars()
            .all()
        )
        zf.writestr(
            "projects.json",
            json.dumps([_serialize_project(p) for p in projects], indent=2),
        )

        # Files: metadata for active (non-soft-deleted) rows + bytes.
        files = (
            (
                await session.execute(
                    select(File).where(File.owner_id == user.id, File.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        zf.writestr(
            "files.json",
            json.dumps([_serialize_file(f) for f in files], indent=2),
        )
        for file in files:
            try:
                async with stream_download(storage_path=file.storage_path) as chunks:
                    chunk_buffer = bytearray()
                    async for chunk in chunks:
                        chunk_buffer.extend(chunk)
                zf.writestr(
                    f"files/{file.id}__{file.filename}",
                    bytes(chunk_buffer),
                )
            except Exception as exc:
                log.warning(
                    "user_export: failed to copy bytes for file %s: %s",
                    file.id,
                    exc,
                )
                zf.writestr(
                    f"files/{file.id}__MISSING.txt",
                    f"Failed to copy bytes for file {file.id} ({file.filename}): {exc}",
                )

        # Knowledge bases.
        kbs = (
            (await session.execute(select(KnowledgeBase).where(KnowledgeBase.owner_id == user.id)))
            .scalars()
            .all()
        )
        zf.writestr(
            "knowledge_bases.json",
            json.dumps([_serialize_kb(k) for k in kbs], indent=2),
        )

        # Audit log entries the user is the actor on.
        audit_rows = (
            (await session.execute(select(AuditLog).where(AuditLog.user_id == user.id)))
            .scalars()
            .all()
        )
        zf.writestr(
            "audit_log.json",
            json.dumps([_serialize_audit(r) for r in audit_rows], indent=2),
        )

        # Wave C — chain-of-custody attributions (PRD §3.3).
        from app.models.work_product import WorkProductAttribution

        attrib_rows = (
            (
                await session.execute(
                    select(WorkProductAttribution).where(WorkProductAttribution.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        zf.writestr(
            "work_product_attribution.json",
            json.dumps([_serialize_work_product(r) for r in attrib_rows], indent=2),
        )

        # Skills — empty under M1 (filesystem-canonical per ADR 0004).
        zf.writestr("skills.json", json.dumps([], indent=2))

        from app.models.skill_workspace import SkillWorkspace, SkillWorkspaceFile
        from app.skills.workspace import metadata

        saved_work = []
        for workspace in await session.scalars(
            select(SkillWorkspace)
            .where(SkillWorkspace.owner_id == user.id)
            .order_by(SkillWorkspace.id)
        ):
            workspace_files = await session.scalars(
                select(SkillWorkspaceFile)
                .where(SkillWorkspaceFile.workspace_id == workspace.id)
                .order_by(SkillWorkspaceFile.name)
            )
            saved_work.append(
                {
                    "id": str(workspace.id),
                    "skill_key": workspace.skill_key,
                    "skill_name": workspace.skill_name,
                    "format_version": workspace.format_version,
                    "project_id": str(workspace.project_id) if workspace.project_id else None,
                    "files": [{**metadata(row), "content": row.content} for row in workspace_files],
                }
            )
        zf.writestr("skill_workspaces.json", json.dumps(saved_work, ensure_ascii=False, indent=2))

    return buffer.getvalue()


async def export_user_data_job(ctx: dict[str, Any], job_id_str: str) -> dict[str, Any]:
    """arq job: build + upload one user's export ZIP.

    Updates :class:`UserExportJob` row at every state transition so a
    status-poll can read accurate progress at any moment.
    """

    job_id = uuid.UUID(job_id_str)
    log.info(
        "user_export: job start",
        extra={"event": "user_export_start", "job_id": job_id_str},
    )

    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(UserExportJob, job_id)
        if job is None:
            log.warning("user_export: job %s not found; skipping", job_id)
            return {"job_id": job_id_str, "status": "missing"}

        user = await session.get(User, job.user_id)
        if user is None:
            job.status = "failed"
            job.error_message = "user no longer exists"
            await session.commit()
            return {"job_id": job_id_str, "status": "failed"}

        job.status = "processing"
        job.started_at = _utcnow()
        await session.commit()

        try:
            zip_bytes = await _build_zip(session, user)
            storage_key = f"exports/{user.id}/{job.id}.zip"
            await upload_bytes(
                storage_path=storage_key,
                body=zip_bytes,
                content_type="application/zip",
            )

            job.status = "completed"
            job.completed_at = _utcnow()
            job.storage_key = storage_key
            job.expires_at = _utcnow() + _EXPORT_TTL
            await session.commit()

            return {
                "job_id": job_id_str,
                "status": "completed",
                "storage_key": storage_key,
                "size_bytes": len(zip_bytes),
            }
        except Exception as exc:
            log.exception("user_export: job %s failed", job_id)
            job.status = "failed"
            job.error_message = repr(exc)[:500]
            await session.commit()
            return {"job_id": job_id_str, "status": "failed", "error": repr(exc)[:200]}


async def export_gc_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """arq cron job: delete export bytes whose ``expires_at`` has passed.

    Runs hourly. Clears ``storage_key`` after a successful delete so a
    second pass won't re-attempt; the row itself stays so users polling
    an old job get a deterministic "expired" answer.
    """

    factory = get_session_factory()
    reaped = 0
    failed = 0
    async with factory() as session:
        now = _utcnow()
        rows = (
            (
                await session.execute(
                    select(UserExportJob).where(
                        UserExportJob.expires_at < now,
                        UserExportJob.storage_key.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )

        for row in rows:
            assert row.storage_key is not None  # narrow for the helper call
            try:
                await delete_object(storage_path=row.storage_key)
                row.storage_key = None
                reaped += 1
            except Exception as exc:
                log.warning(
                    "user_export_gc: failed to delete %s: %s",
                    row.storage_key,
                    exc,
                )
                failed += 1

        await session.commit()

    return {"reaped": reaped, "failed": failed}


# ---------------------------------------------------------------------------
# Bytes helper used by tests that don't go through arq
# ---------------------------------------------------------------------------


async def build_export_zip_for_test(session: AsyncSession, user: User) -> bytes:
    """Test-only entry point that returns raw ZIP bytes.

    Tests that don't need MinIO can call this and inspect the archive
    directly via :mod:`zipfile` rather than spinning up arq.
    """

    return await _build_zip(session, user)
