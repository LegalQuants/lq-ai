"""Recovery pages use real independent transactions and reveal only safe outcomes."""

import asyncio
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.autonomous.orchestration import store as store_module
from app.autonomous.orchestration.watchdog import sweep_recovery
from app.errors import ValidationError
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationPlan as PlanRow,
    OrchestrationRoot as Root,
)
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def batch(env):
    entries = [env]
    owners = []
    try:
        for _ in range(3):
            async with env.factory.begin() as db:
                owner = User(
                    email=f"sweep-{uuid4()}@example.com",
                    hashed_password="unused",
                    autonomous_enabled=True,
                )
                db.add(owner)
                await db.flush()
                project = Project(owner_id=owner.id, name="Sweep fixture", slug=f"sweep-{uuid4()}")
                db.add(project)
                await db.flush()
                session = AutonomousSession(
                    user_id=owner.id,
                    project_id=project.id,
                    trigger_kind="manual",
                    current_phase="analysis",
                    max_cost_usd=env.plan.budget_usd,
                )
                db.add(session)
                await db.flush()
                owner_id, project_id, root_id = owner.id, project.id, session.id
            owners.append(owner_id)
            plan = env.plan.model_copy(
                update={
                    "plan_id": uuid4(),
                    "owner_id": owner_id,
                    "project_id": project_id,
                    "root_id": root_id,
                    "children": tuple(
                        c.model_copy(update={"dispatch_id": uuid4()}) for c in env.plan.children
                    ),
                }
            )
            entries.append(
                SimpleNamespace(
                    **{
                        **vars(env),
                        "plan": plan,
                        "owner_id": owner_id,
                        "project_id": project_id,
                        "root_id": root_id,
                    }
                )
            )
        for item in entries:
            await item.store.save_plan(item.plan, actor_id=item.owner_id)
            await item.store.approve(
                item.root_id,
                actor_id=item.owner_id,
                revision=1,
                plan_hash=item.plan.approval_hash(),
            )
            item.claim = await item.store.claim(
                item.root_id, item.root_id, worker_id=uuid4(), seconds=60
            )
        yield sorted(entries, key=lambda item: item.root_id)
    finally:
        async with env.factory.begin() as db:
            await db.execute(delete(AuditLog).where(AuditLog.user_id.in_(owners)))
            await db.execute(delete(AutonomousSession).where(AutonomousSession.user_id.in_(owners)))
            await db.execute(delete(Project).where(Project.owner_id.in_(owners)))
            await db.execute(delete(User).where(User.id.in_(owners)))


def due(env, monkeypatch):
    async def clock(db):
        return env.plan.deadline

    monkeypatch.setattr(store_module, "_now", clock)


async def audit_count(env, event):
    async with env.factory() as db:
        return await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.resource_id == str(env.root_id),
                AuditLog.action == f"orchestration.{event}",
            )
        )


async def test_pages_advance_past_persistent_invalid_root_and_clean_up_its_claim(
    batch, monkeypatch
):
    first = batch[0]
    async with first.factory.begin() as db:
        (await db.get(PlanRow, (first.root_id, 1))).snapshot = {"private": "must not appear"}
    due(first, monkeypatch)
    report = await sweep_recovery(first.store, limit=1)
    assert report.inspected == report.claims_recovered == 1 and report.roots_expired == 0
    assert report.next_after == first.root_id
    assert [(e.root_id, e.stage, e.code) for e in report.failures] == [
        (first.root_id, "deadline", "conflict")
    ]
    assert "must not appear" not in repr(asdict(report))
    second = await sweep_recovery(first.store, limit=2, after=report.next_after)
    assert second.inspected == second.claims_recovered == second.roots_expired == 2
    assert not second.failures and second.next_after == batch[2].root_id
    last = await sweep_recovery(first.store, limit=2, after=second.next_after)
    assert last.inspected == last.claims_recovered == last.roots_expired == 1
    assert last.next_after is None and not last.failures
    # Restarting the maintenance scan revisits the invalid root without re-fencing.
    repeated = await sweep_recovery(first.store)
    assert repeated.inspected == 1 and repeated.claims_recovered == 0
    assert len(repeated.failures) == 1
    assert await audit_count(first, "claim_expired") == 1


async def test_clean_terminal_roots_are_skipped_unless_they_still_own_workers(batch, monkeypatch):
    for item in batch:
        await item.store.halt(item.root_id, actor_id=item.owner_id)
    await batch[0].store.release_claim(batch[0].claim)
    due(batch[0], monkeypatch)
    report = await sweep_recovery(batch[0].store)
    assert report.inspected == report.claims_recovered == 3
    assert report.roots_expired == 0 and not report.failures
    repeated = await sweep_recovery(batch[0].store)
    assert repeated.inspected == 0 and repeated.next_after is None
    async with batch[0].factory() as db:
        for item in batch:
            assert (await db.get(Root, item.root_id)).status == "halted"


async def test_before_deadline_sweep_preserves_live_claims(batch):
    report = await sweep_recovery(batch[0].store, limit=2)
    assert report.inspected == 2 and report.claims_recovered == report.roots_expired == 0
    assert not report.failures and report.next_after == batch[1].root_id
    async with batch[0].factory() as db:
        for item in batch:
            assert (await db.get(Account, item.root_id)).worker_id == item.claim.worker_id


async def test_competing_sweeps_do_not_duplicate_recovery_or_expiration(batch, monkeypatch):
    due(batch[0], monkeypatch)
    reports = await asyncio.gather(*(sweep_recovery(batch[0].store) for _ in range(3)))
    assert sum(r.claims_recovered for r in reports) == 4
    assert sum(r.roots_expired for r in reports) == 4
    assert not any(r.failures for r in reports)
    for item in batch:
        assert (
            await audit_count(item, "claim_expired") == await audit_count(item, "root_expired") == 1
        )


async def test_blocked_root_times_out_without_blocking_later_roots(batch, monkeypatch):
    first = batch[0]
    due(first, monkeypatch)
    async with first.factory.begin() as blocker:
        await blocker.execute(
            select(Root).where(Root.session_id == first.root_id).with_for_update()
        )
        report = await asyncio.wait_for(
            sweep_recovery(first.store, operation_timeout_seconds=1), timeout=6
        )
        assert [(e.root_id, e.stage, e.code) for e in report.failures] == [
            (first.root_id, "claims", "timeout"),
            (first.root_id, "deadline", "timeout"),
        ]
        assert report.claims_recovered == report.roots_expired == 3
    async with first.factory() as db:
        account = await db.get(Account, first.root_id)
        assert (
            account.worker_id == first.claim.worker_id
            and account.generation == first.claim.generation
        )
    retry = await sweep_recovery(first.store)
    assert retry.claims_recovered == retry.roots_expired == 1 and not retry.failures


async def test_failed_deadline_audit_keeps_prior_claim_cleanup_and_continues(batch, monkeypatch):
    first = batch[0]
    due(first, monkeypatch)
    original = store_module._audit

    async def fail(db, root, event, **details):
        await original(db, root, event, **details)
        if root.session_id == first.root_id and event == "root_expired":
            raise RuntimeError("private provider payload must not leak")

    monkeypatch.setattr(store_module, "_audit", fail)
    report = await sweep_recovery(first.store)
    assert report.claims_recovered == 4 and report.roots_expired == 3
    assert [(e.stage, e.code) for e in report.failures] == [("deadline", "internal_error")]
    assert "provider payload" not in repr(asdict(report))
    async with first.factory() as db:
        assert (await db.get(Account, first.root_id)).worker_id is None
        assert (await db.get(Root, first.root_id)).status == "running"
    assert await audit_count(first, "claim_expired") == 1
    assert await audit_count(first, "root_expired") == 0


async def test_candidate_deleted_after_discovery_is_reported_without_stopping_page(
    batch, monkeypatch
):
    first = batch[0]
    due(first, monkeypatch)
    original = first.store.recover_expired_claims

    async def deleted(root_id):
        if root_id == first.root_id:
            async with first.factory.begin() as db:
                await db.execute(delete(AutonomousSession).where(AutonomousSession.id == root_id))
        return await original(root_id)

    monkeypatch.setattr(first.store, "recover_expired_claims", deleted)
    report = await sweep_recovery(first.store)
    assert report.claims_recovered == report.roots_expired == 3
    assert [(e.stage, e.code) for e in report.failures] == [
        ("claims", "not_found"),
        ("deadline", "not_found"),
    ]


async def test_cancelled_sweep_does_not_swallow_cancellation_or_visit_later_roots(
    batch, monkeypatch
):
    first = batch[0]
    entered = asyncio.Event()
    forever = asyncio.Event()
    due(first, monkeypatch)
    original = store_module._audit

    async def blocked(db, root, event, **details):
        await original(db, root, event, **details)
        if event == "claim_expired":
            entered.set()
            await forever.wait()

    monkeypatch.setattr(store_module, "_audit", blocked)
    task = asyncio.create_task(sweep_recovery(first.store))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    for item in batch:
        assert await audit_count(item, "claim_expired") == 0
    monkeypatch.setattr(store_module, "_audit", original)
    retry = await sweep_recovery(first.store)
    assert retry.claims_recovered == retry.roots_expired == 4 and not retry.failures


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 51},
        {"limit": True},
        {"limit": 1.5},
        {"after": "not-a-uuid"},
        {"operation_timeout_seconds": 0},
        {"operation_timeout_seconds": 6},
        {"operation_timeout_seconds": True},
    ],
)
async def test_sweep_rejects_unbounded_or_ill_typed_inputs(env, kwargs):
    with pytest.raises(ValidationError):
        await sweep_recovery(env.store, **kwargs)


async def test_old_approval_wait_is_not_subject_to_legacy_idle_rules(env):
    from datetime import UTC, datetime

    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    async with env.factory.begin() as db:
        (await db.get(AutonomousSession, env.root_id)).last_activity_at = datetime(
            2000, 1, 1, tzinfo=UTC
        )
    report = await sweep_recovery(env.store)
    assert report.inspected == 1 and report.claims_recovered == report.roots_expired == 0
    assert not report.failures
    async with env.factory() as db:
        assert (await db.get(Root, env.root_id)).status == "awaiting_approval"
        session = await db.get(AutonomousSession, env.root_id)
        assert (session.status, session.halt_state) == ("running", "running")


async def test_sweep_keeps_uncertain_reservation_while_expiring_other_roots(batch, monkeypatch):
    from decimal import Decimal

    from app.autonomous.enums import ToolIntent
    from app.models.orchestration import OrchestrationEffect as Effect
    from app.schemas.autonomous import Phase

    first = batch[0]
    await first.store.begin_effect(
        first.claim,
        effect_key="analysis:one",
        request_hash="b" * 64,
        reservation_usd=Decimal("1"),
        phase=Phase.analysis,
        intent=ToolIntent.run_skill,
    )
    due(first, monkeypatch)
    report = await sweep_recovery(first.store)
    assert report.claims_recovered == 4 and report.roots_expired == 3 and not report.failures
    async with first.factory() as db:
        assert (await db.get(Root, first.root_id)).status == "uncertain"
        assert (await db.get(Account, first.root_id)).reserved_usd == 1
        assert (await db.get(Effect, (first.root_id, "analysis:one"))).status == "uncertain"
    again = await sweep_recovery(first.store)
    assert again.inspected == 1 and again.claims_recovered == again.roots_expired == 0
    assert await audit_count(first, "effect_uncertain") == 1


async def test_discovery_releases_its_only_connection_before_recovery(
    batch, test_db_url, monkeypatch
):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.autonomous.orchestration.store import OrchestrationStore

    first = batch[0]
    due(first, monkeypatch)
    engine = create_async_engine(test_db_url, pool_size=1, max_overflow=0)
    try:
        isolated = OrchestrationStore(
            async_sessionmaker(engine, expire_on_commit=False), check_policy=first.policy
        )
        report = await sweep_recovery(isolated, operation_timeout_seconds=1)
        assert report.claims_recovered == report.roots_expired == 4 and not report.failures
    finally:
        await engine.dispose()


async def test_cancellation_after_claim_commit_can_restart_page_without_double_fencing(
    batch, monkeypatch
):
    first = batch[0]
    due(first, monkeypatch)
    entered, forever = asyncio.Event(), asyncio.Event()
    original = first.store.expire_root

    async def blocked(root_id):
        entered.set()
        await forever.wait()
        return await original(root_id)

    monkeypatch.setattr(first.store, "expire_root", blocked)
    task = asyncio.create_task(sweep_recovery(first.store))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert await audit_count(first, "claim_expired") == 1
    monkeypatch.setattr(first.store, "expire_root", original)
    retry = await sweep_recovery(first.store)
    assert retry.claims_recovered == 3 and retry.roots_expired == 4 and not retry.failures
    assert await audit_count(first, "claim_expired") == 1


async def test_discovery_timeout_propagates_without_processing_a_page(
    batch, test_db_url, monkeypatch
):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.autonomous.orchestration.store import OrchestrationStore

    first = batch[0]
    due(first, monkeypatch)
    engine = create_async_engine(test_db_url, pool_size=1, max_overflow=0)
    try:
        isolated = OrchestrationStore(
            async_sessionmaker(engine, expire_on_commit=False), check_policy=first.policy
        )
        async with engine.connect():
            with pytest.raises(TimeoutError):
                await sweep_recovery(isolated, operation_timeout_seconds=1)
        for item in batch:
            assert await audit_count(item, "claim_expired") == 0
    finally:
        await engine.dispose()
