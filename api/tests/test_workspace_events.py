"""Workspace-event contracts and real-Postgres foundation/lifecycle proofs.

These tests exercise trusted service calls, not an enabled event producer or a
Today endpoint. Source-adapter authorization remains a gate for the next slice.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.errors import Conflict, Forbidden, NotFound
from app.models import AuditLog, Project, ProjectMember, User, WorkspaceEvent
from app.schemas.workspace_events import (
    EventCursor,
    EventProvenance,
    EventSource,
    WorkspaceEventCreate,
    WorkspaceEventQuery,
    WorkspaceEventRead,
)
from app.workers.user_deletion import hard_delete_user_for_test
from app.workers.user_export import build_export_zip_for_test
from app.workspace_events.service import list_events, record_event, remove_source_events

WHEN = datetime(2026, 10, 15, 12, tzinfo=UTC)


async def _user(db: AsyncSession) -> User:
    user = User(email=f"events-{uuid.uuid4().hex}@example.com", hashed_password="not-used")
    db.add(user)
    await db.flush()
    return user


async def _project(db: AsyncSession, user: User, *, privileged: bool = False) -> Project:
    project = Project(
        owner_id=user.id,
        name="sensitive-project-name-sentinel",
        slug=f"events-{uuid.uuid4().hex}",
        privileged=privileged,
        minimum_inference_tier=1 if privileged else None,
    )
    db.add(project)
    await db.flush()
    return project


async def _count(
    db: AsyncSession, model: type[WorkspaceEvent] | type[AuditLog], user_id: uuid.UUID
) -> int:
    return int(
        await db.scalar(select(func.count()).select_from(model).where(model.user_id == user_id))
        or 0
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "extra",
    [
        {"source_kind": "email"},
        {"event_type": "mail.send"},
        {"sensitivity": "public"},
        {"source_ref": "mail-body-sentinel"},
        {"occurred_at": datetime(2026, 10, 15)},
        {"body": "mail-body-sentinel"},
        {"subject": "mail-body-sentinel"},
        {"status": "dismissed"},
        {"user_id": str(uuid.uuid4())},
        {"observed_at": WHEN},
        {"provenance": {"producer": "arbitrary"}},
        {"provenance": {"producer": "autonomous", "body": "mail-body-sentinel"}},
    ],
)
def test_create_contract_rejects_unsupported_or_payload_fields(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as exc:
        WorkspaceEventCreate.model_validate({"source_ref": uuid.uuid4(), **extra})
    assert "mail-body-sentinel" not in str(exc.value)


@pytest.mark.unit
@pytest.mark.parametrize(
    "query",
    [
        {"limit": 0},
        {"limit": 201},
        {"start_at": datetime(2026, 10, 15)},
        {"start_at": WHEN, "end_at": WHEN},
        {"start_at": WHEN, "end_at": WHEN - timedelta(seconds=1)},
        {"after": {"occurred_at": WHEN, "event_id": "not-a-uuid"}},
        {"offset": 1000000},
    ],
)
def test_query_contract_rejects_unbounded_or_invalid_queries(query: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        WorkspaceEventQuery.model_validate(query)


@pytest.mark.unit
def test_contract_is_closed_and_immutable() -> None:
    event = WorkspaceEventCreate(source_ref=uuid.uuid4())
    assert event.provenance == EventProvenance(producer="autonomous")
    assert event.sensitivity == "confidential"
    with pytest.raises(ValidationError):
        event.source_ref = uuid.uuid4()


@pytest.mark.integration
async def test_record_event_metadata_and_payload_free_audit(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    event = WorkspaceEventCreate(source_ref=uuid.uuid4(), occurred_at=WHEN)
    row = await record_event(db_session, user_id=user.id, event=event)
    metadata = WorkspaceEventRead.model_validate(row).model_dump(mode="json")
    assert metadata["source_ref"] == str(event.source_ref)
    assert row.user_id == user.id
    assert row.occurred_at == WHEN
    assert row.observed_at.tzinfo is not None
    assert row.status == "recorded"
    assert len(row.dedupe_digest) == 64
    assert "body" not in metadata and "title" not in metadata
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.resource_id == str(row.id)))
    assert audit is not None
    assert audit.action == "workspace_event.record"
    assert audit.details == {"source_kind": "internal", "event_type": "finding.created"}


@pytest.mark.integration
async def test_missing_occurrence_uses_first_observation_even_on_retry(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    event = WorkspaceEventCreate(source_ref=uuid.uuid4())
    first = await record_event(db_session, user_id=user.id, event=event)
    assert first.occurred_at == first.observed_at
    initial = first.observed_at
    replay = await record_event(db_session, user_id=user.id, event=event)
    assert replay.id == first.id
    assert replay.observed_at == initial


@pytest.mark.integration
async def test_retry_is_idempotent_without_collapsing_distinct_sources(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    event = WorkspaceEventCreate(source_ref=uuid.uuid4(), occurred_at=WHEN)
    first = await record_event(db_session, user_id=user.id, event=event)
    repeated = await record_event(db_session, user_id=user.id, event=event)
    other = await record_event(
        db_session,
        user_id=user.id,
        event=WorkspaceEventCreate(source_ref=uuid.uuid4(), occurred_at=WHEN),
    )
    assert first.id == repeated.id != other.id
    assert await _count(db_session, WorkspaceEvent, user.id) == 2
    assert await _count(db_session, AuditLog, user.id) == 2


@pytest.mark.integration
async def test_owner_isolation_and_owner_scoped_deduplication(db_session: AsyncSession) -> None:
    first_user, second_user = await _user(db_session), await _user(db_session)
    event = WorkspaceEventCreate(source_ref=uuid.uuid4())
    first = await record_event(db_session, user_id=first_user.id, event=event)
    second = await record_event(db_session, user_id=second_user.id, event=event)
    assert first.id != second.id
    assert first.dedupe_digest != second.dedupe_digest
    for user, expected in [(first_user, first), (second_user, second)]:
        rows = await list_events(db_session, user_id=user.id, query=WorkspaceEventQuery())
        assert [r.id for r in rows] == [expected.id]


@pytest.mark.integration
@pytest.mark.parametrize("deleted", [False, True])
async def test_missing_or_deleted_owner_fails_closed(
    db_session: AsyncSession, deleted: bool
) -> None:
    user_id = uuid.uuid4()
    if deleted:
        user = await _user(db_session)
        user.deleted_at = WHEN
        await db_session.flush()
        user_id = user.id
    with pytest.raises(NotFound):
        await record_event(
            db_session, user_id=user_id, event=WorkspaceEventCreate(source_ref=uuid.uuid4())
        )
    with pytest.raises(NotFound):
        await list_events(db_session, user_id=user_id, query=WorkspaceEventQuery())
    assert await _count(db_session, WorkspaceEvent, user_id) == 0


@pytest.mark.integration
@pytest.mark.parametrize("unavailable", ["foreign", "archived", "missing"])
async def test_project_validation(db_session: AsyncSession, unavailable: str) -> None:
    user = await _user(db_session)
    project_id = uuid.uuid4()
    if unavailable != "missing":
        owner = await _user(db_session) if unavailable == "foreign" else user
        project = await _project(db_session, owner)
        if unavailable == "archived":
            project.archived_at = WHEN
            await db_session.flush()
        project_id = project.id
    with pytest.raises(NotFound):
        await record_event(
            db_session,
            user_id=user.id,
            event=WorkspaceEventCreate(source_ref=uuid.uuid4(), project_id=project_id),
        )
    assert await _count(db_session, WorkspaceEvent, user.id) == 0


@pytest.mark.integration
async def test_privileged_project_cannot_be_downgraded_or_leak_name_into_audit(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    project = await _project(db_session, user, privileged=True)
    row = await record_event(
        db_session,
        user_id=user.id,
        event=WorkspaceEventCreate(source_ref=uuid.uuid4(), project_id=project.id),
    )
    assert row.sensitivity == "privileged"
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.resource_id == str(row.id)))
    assert audit is not None and audit.privilege_marked
    assert audit.privilege_basis == "workspace_event:privileged"
    assert project.name not in json.dumps(audit.details)
    assert project.name not in audit.privilege_basis


@pytest.mark.integration
async def test_replay_cannot_silently_rebind_a_source(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    project = await _project(db_session, user)
    ref = uuid.uuid4()
    first = await record_event(
        db_session, user_id=user.id, event=WorkspaceEventCreate(source_ref=ref)
    )
    with pytest.raises(Conflict):
        await record_event(
            db_session,
            user_id=user.id,
            event=WorkspaceEventCreate(source_ref=ref, project_id=project.id),
        )
    assert first.project_id is None
    assert await _count(db_session, WorkspaceEvent, user.id) == 1
    assert await _count(db_session, AuditLog, user.id) == 1


@pytest.mark.integration
async def test_time_window_and_cursor_pagination(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    ids = []
    for _index in range(5):
        row = await record_event(
            db_session,
            user_id=user.id,
            event=WorkspaceEventCreate(source_ref=uuid.uuid4(), occurred_at=WHEN),
        )
        ids.append(row.id)
    query = WorkspaceEventQuery(start_at=WHEN, end_at=WHEN + timedelta(seconds=1), limit=2)
    seen: list[uuid.UUID] = []
    while True:
        rows = await list_events(db_session, user_id=user.id, query=query)
        if not rows:
            break
        seen.extend(row.id for row in rows)
        last = rows[-1]
        query = query.model_copy(
            update={"after": EventCursor(occurred_at=last.occurred_at, event_id=last.id)}
        )
    assert seen == sorted(ids)
    assert not await list_events(
        db_session, user_id=user.id, query=WorkspaceEventQuery(end_at=WHEN)
    )


@pytest.mark.integration
async def test_cursor_from_another_owner_never_expands_scope(db_session: AsyncSession) -> None:
    user, other = await _user(db_session), await _user(db_session)
    foreign = await record_event(
        db_session,
        user_id=other.id,
        event=WorkspaceEventCreate(source_ref=uuid.uuid4(), occurred_at=WHEN),
    )
    assert not await list_events(
        db_session,
        user_id=user.id,
        query=WorkspaceEventQuery(
            after=EventCursor(occurred_at=foreign.occurred_at, event_id=foreign.id)
        ),
    )


@pytest.mark.integration
async def test_chronology_uses_source_time_not_arrival_and_normalizes_timezone(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    times = [WHEN + timedelta(hours=1), WHEN, WHEN - timedelta(hours=1)]
    for when in times:
        await record_event(
            db_session,
            user_id=user.id,
            event=WorkspaceEventCreate(source_ref=uuid.uuid4(), occurred_at=when),
        )
    rows = await list_events(db_session, user_id=user.id, query=WorkspaceEventQuery())
    assert [row.occurred_at for row in rows] == sorted(times)


@pytest.mark.integration
async def test_filters_and_project_visibility_are_rechecked(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    project = await _project(db_session, user)
    await record_event(
        db_session,
        user_id=user.id,
        event=WorkspaceEventCreate(source_ref=uuid.uuid4(), project_id=project.id),
    )
    query = WorkspaceEventQuery(
        project_id=project.id, source_kind="internal", event_type="finding.created"
    )
    assert len(await list_events(db_session, user_id=user.id, query=query)) == 1
    project.archived_at = WHEN
    await db_session.flush()
    assert not await list_events(db_session, user_id=user.id, query=query)
    project.archived_at = None
    project.owner_id = (await _user(db_session)).id
    await db_session.flush()
    assert not await list_events(db_session, user_id=user.id, query=query)


@pytest.mark.integration
async def test_record_and_audit_roll_back_together(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    with pytest.raises(RuntimeError, match="rollback"):
        async with db_session.begin_nested():
            await record_event(
                db_session, user_id=user.id, event=WorkspaceEventCreate(source_ref=uuid.uuid4())
            )
            raise RuntimeError("rollback")
    assert await _count(db_session, WorkspaceEvent, user.id) == 0
    assert await _count(db_session, AuditLog, user.id) == 0


@pytest.mark.integration
async def test_audit_failure_cannot_leave_an_unaudited_insert(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _user(db_session)
    monkeypatch.setattr(
        "app.workspace_events.service.audit_action",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await record_event(
            db_session, user_id=user.id, event=WorkspaceEventCreate(source_ref=uuid.uuid4())
        )
    assert await _count(db_session, WorkspaceEvent, user.id) == 0


@pytest.mark.integration
async def test_source_removal_is_owned_idempotent_and_audited(db_session: AsyncSession) -> None:
    user, other = await _user(db_session), await _user(db_session)
    ref = uuid.uuid4()
    for owner in (user, other):
        await record_event(db_session, user_id=owner.id, event=WorkspaceEventCreate(source_ref=ref))
    source = EventSource(source_ref=ref)
    assert await remove_source_events(db_session, user_id=user.id, source=source) == 1
    assert await remove_source_events(db_session, user_id=user.id, source=source) == 0
    assert not await list_events(db_session, user_id=user.id, query=WorkspaceEventQuery())
    assert len(await list_events(db_session, user_id=other.id, query=WorkspaceEventQuery())) == 1
    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "workspace_event.remove_source")
    )
    assert audit is not None and audit.details == {"source_kind": "internal", "removed_count": 1}


@pytest.mark.integration
async def test_audit_failure_restores_removed_events(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _user(db_session)
    ref = uuid.uuid4()
    await record_event(db_session, user_id=user.id, event=WorkspaceEventCreate(source_ref=ref))
    monkeypatch.setattr(
        "app.workspace_events.service.audit_action",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await remove_source_events(db_session, user_id=user.id, source=EventSource(source_ref=ref))
    assert await _count(db_session, WorkspaceEvent, user.id) == 1


@pytest.mark.integration
async def test_export_includes_only_the_owners_event_metadata(db_session: AsyncSession) -> None:
    user, other = await _user(db_session), await _user(db_session)
    own = await record_event(
        db_session, user_id=user.id, event=WorkspaceEventCreate(source_ref=uuid.uuid4())
    )
    foreign = await record_event(
        db_session, user_id=other.id, event=WorkspaceEventCreate(source_ref=uuid.uuid4())
    )
    bundle = await build_export_zip_for_test(db_session, user)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        events = json.loads(archive.read("workspace_events.json"))
    assert [event["id"] for event in events] == [str(own.id)]
    assert str(foreign.id) not in json.dumps(events)
    assert "body" not in events[0] and "title" not in events[0]


@pytest.mark.integration
async def test_project_deletion_cascades_event_metadata(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    project = await _project(db_session, user)
    await record_event(
        db_session,
        user_id=user.id,
        event=WorkspaceEventCreate(source_ref=uuid.uuid4(), project_id=project.id),
    )
    await db_session.delete(project)
    await db_session.flush()
    assert await _count(db_session, WorkspaceEvent, user.id) == 0


@pytest.mark.integration
async def test_account_deletion_removes_events_and_preserves_anonymous_audit(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    row = await record_event(
        db_session, user_id=user.id, event=WorkspaceEventCreate(source_ref=uuid.uuid4())
    )
    event_id = row.id
    await hard_delete_user_for_test(db_session, user)
    await db_session.flush()
    assert await _count(db_session, WorkspaceEvent, user.id) == 0
    db_session.expire_all()
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.resource_id == str(event_id)))
    assert audit is not None and audit.user_id is None


@pytest.mark.integration
@pytest.mark.parametrize(
    "bad",
    [
        {"source_kind": "email"},
        {"event_type": "mail.send"},
        {"status": "dismissed"},
        {"sensitivity": "public"},
        {"provenance": {"body": "sentinel"}},
        {"dedupe_digest": "bad"},
    ],
)
async def test_database_constraints_defend_against_bypassing_validation(
    db_session: AsyncSession,
    bad: dict[str, object],
) -> None:
    user = await _user(db_session)
    values = {
        "user_id": user.id,
        "source_kind": "internal",
        "source_ref": uuid.uuid4(),
        "event_type": "finding.created",
        "status": "recorded",
        "occurred_at": WHEN,
        "observed_at": WHEN,
        "sensitivity": "confidential",
        "dedupe_digest": "a" * 64,
        "provenance": {"producer": "autonomous"},
    }
    values.update(bad)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(insert(WorkspaceEvent).values(**values))


@pytest.mark.integration
async def test_migration_created_indexes_and_cascading_foreign_keys(
    db_session: AsyncSession,
) -> None:
    indexes = (
        (
            await db_session.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'workspace_events'")
            )
        )
        .scalars()
        .all()
    )
    assert {
        "uq_workspace_events_source",
        "ix_workspace_events_owner_time",
        "ix_workspace_events_project",
    } <= set(indexes)
    cascades = await db_session.scalar(
        text(
            "SELECT count(*) FROM pg_constraint WHERE conrelid = 'workspace_events'::regclass AND contype = 'f' AND confdeltype = 'c'"
        )
    )
    assert cascades == 2


@pytest.mark.integration
async def test_concurrent_committed_retries_create_one_event_and_one_audit(
    test_engine: AsyncEngine,
) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as setup:
        user = await _user(setup)
        user_id = user.id
        await setup.commit()
    event = WorkspaceEventCreate(source_ref=uuid.uuid4(), occurred_at=WHEN)

    async def write() -> uuid.UUID:
        async with AsyncSession(test_engine, expire_on_commit=False) as db:
            row = await record_event(db, user_id=user_id, event=event)
            result = row.id
            await db.commit()
            return result

    try:
        first, second = await asyncio.wait_for(asyncio.gather(write(), write()), timeout=15)
        assert first == second
        async with AsyncSession(test_engine) as db:
            count = await db.scalar(
                select(func.count()).select_from(AuditLog).where(AuditLog.resource_id == str(first))
            )
            assert count == 1
            assert len(await list_events(db, user_id=user_id, query=WorkspaceEventQuery())) == 1
    finally:
        async with AsyncSession(test_engine) as db:
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


@pytest.mark.integration
async def test_cached_project_cannot_hide_a_committed_privilege_upgrade(
    test_engine: AsyncEngine,
) -> None:
    async with AsyncSession(test_engine, expire_on_commit=False) as setup:
        user = await _user(setup)
        project = await _project(setup, user)
        user_id, project_id = user.id, project.id
        await setup.commit()
    try:
        async with AsyncSession(test_engine, expire_on_commit=False) as reader:
            cached = await reader.get(Project, project_id)
            assert cached is not None and not cached.privileged
            async with AsyncSession(test_engine) as updater:
                await updater.execute(
                    update(Project)
                    .where(Project.id == project_id)
                    .values(privileged=True, minimum_inference_tier=1)
                )
                await updater.commit()
            assert not cached.privileged
            event = await record_event(
                reader,
                user_id=user_id,
                event=WorkspaceEventCreate(source_ref=uuid.uuid4(), project_id=project_id),
            )
            assert event.sensitivity == "privileged"
            audit = await reader.scalar(
                select(AuditLog).where(AuditLog.resource_id == str(event.id))
            )
            assert audit is not None and audit.privilege_marked
    finally:
        async with AsyncSession(test_engine) as cleanup:
            await cleanup.execute(delete(Project).where(Project.id == project_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


@pytest.mark.integration
@pytest.mark.parametrize("is_admin", [False, True])
async def test_ethical_screen_overrides_owner_org_and_admin(
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    user = await _user(db_session)
    user.is_admin = is_admin
    project = await _project(db_session, user)
    project.share_scope = "org"
    await db_session.flush()
    await record_event(
        db_session,
        user_id=user.id,
        event=WorkspaceEventCreate(source_ref=uuid.uuid4(), project_id=project.id),
    )
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="blocked"))
    await db_session.flush()
    assert not await list_events(db_session, user_id=user.id, query=WorkspaceEventQuery())
    with pytest.raises(NotFound):
        await record_event(
            db_session,
            user_id=user.id,
            event=WorkspaceEventCreate(source_ref=uuid.uuid4(), project_id=project.id),
        )
    with pytest.raises(Forbidden, match="reconciliation"):
        await build_export_zip_for_test(db_session, user)


@pytest.mark.integration
@pytest.mark.parametrize("role", ["lead", "contributor", "reader"])
async def test_shared_matter_access_does_not_share_private_events(
    db_session: AsyncSession,
    role: str,
) -> None:
    owner, member = await _user(db_session), await _user(db_session)
    project = await _project(db_session, owner)
    membership = ProjectMember(project_id=project.id, user_id=member.id, role=role)
    db_session.add(membership)
    await db_session.flush()
    await record_event(
        db_session,
        user_id=member.id,
        event=WorkspaceEventCreate(source_ref=uuid.uuid4(), project_id=project.id),
    )
    assert len(await list_events(db_session, user_id=member.id, query=WorkspaceEventQuery())) == 1
    assert not await list_events(db_session, user_id=owner.id, query=WorkspaceEventQuery())
    await db_session.delete(membership)
    await db_session.flush()
    assert not await list_events(db_session, user_id=member.id, query=WorkspaceEventQuery())
    with pytest.raises(NotFound):
        await record_event(
            db_session,
            user_id=member.id,
            event=WorkspaceEventCreate(source_ref=uuid.uuid4(), project_id=project.id),
        )


@pytest.mark.integration
async def test_org_scope_never_shares_another_users_event_rows(db_session: AsyncSession) -> None:
    owner, colleague = await _user(db_session), await _user(db_session)
    project = await _project(db_session, owner)
    project.share_scope = "org"
    await db_session.flush()
    await record_event(
        db_session,
        user_id=owner.id,
        event=WorkspaceEventCreate(source_ref=uuid.uuid4(), project_id=project.id),
    )
    assert not await list_events(db_session, user_id=colleague.id, query=WorkspaceEventQuery())
