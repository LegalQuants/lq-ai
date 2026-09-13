"""Renewal preserves a fixed attempt boundary under real database races."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.store import WorkerClaim
from app.errors import Conflict, Forbidden, ValidationError
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationEffect as Effect,
    OrchestrationRoot as Root,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.autonomous import Phase

pytestmark = pytest.mark.integration


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


async def begin(env):
    return await env.store.begin_effect(
        env.claim,
        effect_key="analysis:one",
        request_hash="b" * 64,
        reservation_usd=Decimal("1"),
        phase=Phase.analysis,
        intent=ToolIntent.run_skill,
    )


async def expire(env):
    async with env.factory.begin() as db:
        await db.execute(
            update(Account)
            .where(Account.session_id == env.claim.session_id)
            .values(lease_until=func.clock_timestamp())
        )


@pytest_asyncio.fixture
async def leased(env):
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    await env.store.approve(
        env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
    )
    env.claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=30)
    return env


@pytest.mark.parametrize("child_run", [False, True])
async def test_renewal_caps_at_fixed_attempt_without_changing_progress(leased, child_run):
    env = leased
    if child_run:
        children = await env.store.admit_children(env.claim)
        env.claim = await env.store.claim(env.root_id, children[0], worker_id=uuid4(), seconds=30)
    async with env.factory() as db:
        before = await db.get(Account, env.claim.session_id)
        root = await db.get(Root, env.root_id)
        session = await db.get(AutonomousSession, env.claim.session_id)
        progress = (root.updated_at, root.status, session.last_activity_at, session.current_phase)
        assert before.attempt_deadline - before.lease_until == timedelta(seconds=30)
    until = await env.store.renew_claim(env.claim, seconds=900)
    assert until == before.attempt_deadline
    assert await env.store.renew_claim(env.claim, seconds=1) == until
    assert await env.store.renew_claim(env.claim, seconds=900) == until
    assert await audit_count(env, "claim_renewed") == 1
    async with env.factory() as db:
        account = await db.get(Account, env.claim.session_id)
        root = await db.get(Root, env.root_id)
        session = await db.get(AutonomousSession, env.claim.session_id)
        assert (
            root.updated_at,
            root.status,
            session.last_activity_at,
            session.current_phase,
        ) == progress
        assert (account.generation, account.worker_id) == (before.generation, before.worker_id)
        assert account.spent_usd == account.reserved_usd == 0
        assert account.attempt_deadline == until
        if child_run:
            assert (await db.get(Account, env.root_id)).lease_until < until
            assert (await db.get(Account, children[1])).attempt_deadline is None


async def test_root_deadline_bounds_claim_and_renewal(env):
    async with env.factory() as db:
        now = await db.scalar(select(func.clock_timestamp()))
    env.plan = env.plan.model_copy(update={"deadline": now + timedelta(seconds=45)})
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    await env.store.approve(
        env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
    )
    claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=30)
    assert await env.store.renew_claim(claim, seconds=900) == env.plan.deadline
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert account.attempt_deadline == account.lease_until == env.plan.deadline


@pytest.mark.parametrize("seconds", [True, False, 0, -1, 901, 1.5, "60", None])
async def test_renewal_rejects_invalid_durations(leased, seconds):
    with pytest.raises(ValidationError):
        await leased.store.renew_claim(leased.claim, seconds=seconds)
    assert await audit_count(leased, "claim_renewed") == 0


@pytest.mark.parametrize("reason", ["policy", "optout", "archive", "project_policy", "halt"])
async def test_revocation_refuses_renewal_but_allows_release(leased, reason):
    env = leased
    async with env.factory() as db:
        until = (await db.get(Account, env.root_id)).lease_until
    if reason == "policy":
        env.policy.valid = False
    elif reason == "halt":
        await env.store.halt(env.root_id, actor_id=env.owner_id)
    else:
        async with env.factory.begin() as db:
            if reason == "optout":
                await db.execute(
                    update(User).where(User.id == env.owner_id).values(autonomous_enabled=False)
                )
            elif reason == "archive":
                await db.execute(
                    update(Project)
                    .where(Project.id == env.project_id)
                    .values(archived_at=func.clock_timestamp())
                )
            else:
                await db.execute(
                    update(Project)
                    .where(Project.id == env.project_id)
                    .values(privileged=True, minimum_inference_tier=1)
                )
    with pytest.raises((Conflict, Forbidden)):
        await env.store.renew_claim(env.claim, seconds=900)
    async with env.factory() as db:
        assert (await db.get(Account, env.root_id)).lease_until == until
    assert await audit_count(env, "claim_renewed") == 0
    await env.store.release_claim(env.claim)
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert account.worker_id is account.lease_until is account.attempt_deadline is None


async def test_expired_and_replaced_claims_cannot_be_renewed(leased):
    env = leased
    for stale in (
        replace(env.claim, worker_id=uuid4()),
        replace(env.claim, generation=env.claim.generation + 1),
        replace(env.claim, session_id=uuid4()),
    ):
        with pytest.raises(Conflict):
            await env.store.renew_claim(stale, seconds=60)
    await expire(env)
    with pytest.raises(Conflict, match="stale or expired"):
        await env.store.renew_claim(env.claim, seconds=60)
    replacement = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=30)
    with pytest.raises(Conflict, match="stale or expired"):
        await env.store.renew_claim(env.claim, seconds=60)
    async with env.factory() as db:
        assert (await db.get(Account, env.root_id)).worker_id == replacement.worker_id
    assert await audit_count(env, "claim_renewed") == 0


async def test_renewal_audit_failure_rolls_back_extension(leased, monkeypatch):
    from app.autonomous.orchestration import store

    env = leased
    async with env.factory() as db:
        before = await db.get(Account, env.root_id)
    original = store._audit

    async def fail(db, root, event, **details):
        await original(db, root, event, **details)
        if event == "claim_renewed":
            raise RuntimeError("audit rollback fixture")

    monkeypatch.setattr(store, "_audit", fail)
    with pytest.raises(RuntimeError, match="audit rollback"):
        await env.store.renew_claim(env.claim, seconds=900)
    async with env.factory() as db:
        after = await db.get(Account, env.root_id)
        assert after.lease_until == before.lease_until
        assert after.attempt_deadline == before.attempt_deadline
        assert after.generation == before.generation
    assert await audit_count(env, "claim_renewed") == 0


async def test_concurrent_renewals_serialize_without_shortening(leased):
    env = leased
    async with env.factory() as db:
        limit = (await db.get(Account, env.root_id)).attempt_deadline
    results = await asyncio.gather(
        *(env.store.renew_claim(env.claim, seconds=s) for s in (900, 1, 45))
    )
    assert max(results) == limit
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert account.lease_until == account.attempt_deadline == limit
        assert account.generation == env.claim.generation


async def test_renewal_cannot_resurrect_claim_after_waiting_for_account_lock(leased, monkeypatch):
    env = leased
    entering = asyncio.Event()
    original = env.store._account

    async def lock(db, root_id, session_id):
        entering.set()
        return await original(db, root_id, session_id)

    monkeypatch.setattr(env.store, "_account", lock)
    async with asyncio.TaskGroup() as group:
        async with env.factory.begin() as blocker:
            account = await blocker.scalar(
                select(Account).where(Account.session_id == env.root_id).with_for_update()
            )

            async def renew():
                with pytest.raises(Conflict, match="stale or expired"):
                    await env.store.renew_claim(env.claim, seconds=900)

            task = group.create_task(renew())
            await asyncio.wait_for(entering.wait(), timeout=5)
            account.lease_until = await blocker.scalar(select(func.clock_timestamp()))
        await asyncio.wait_for(task, timeout=5)
    assert await audit_count(env, "claim_renewed") == 0


async def test_renewal_and_release_race_cannot_restore_released_ownership(leased):
    env = leased
    results = await asyncio.gather(
        env.store.renew_claim(env.claim, seconds=900),
        env.store.release_claim(env.claim),
        return_exceptions=True,
    )
    assert results[1] is None
    assert not isinstance(results[0], BaseException) or isinstance(results[0], Conflict)
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert account.worker_id is account.lease_until is account.attempt_deadline is None
        assert account.generation == env.claim.generation + 1
    with pytest.raises(Conflict):
        await env.store.renew_claim(env.claim, seconds=900)


async def test_expired_pending_effect_cannot_be_renewed_or_reclaimed(leased):
    env = leased
    await begin(env)
    async with env.factory.begin() as db:
        end = await db.scalar(select(func.clock_timestamp()))
        await db.execute(
            update(Account)
            .where(Account.session_id == env.root_id)
            .values(lease_until=end, attempt_deadline=end)
        )
    results = await asyncio.gather(
        env.store.renew_claim(env.claim, seconds=900),
        env.store.recover_expired_effects(env.root_id),
        env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60),
        return_exceptions=True,
    )
    assert isinstance(results[0], Conflict) and isinstance(results[2], Conflict)
    assert results[1] in (0, 1)
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        effect = await db.get(Effect, (env.root_id, "analysis:one"))
        assert account.worker_id is account.lease_until is account.attempt_deadline is None
        assert account.reserved_usd == effect.reserved_usd == Decimal("1")
        assert account.spent_usd == 0 and effect.status == "uncertain"
        assert account.generation == env.claim.generation + 1
    assert await audit_count(env, "effect_uncertain") == 1


async def test_live_renewal_keeps_recovery_and_competing_claim_out(leased):
    env = leased
    await begin(env)
    results = await asyncio.gather(
        env.store.renew_claim(env.claim, seconds=900),
        env.store.recover_expired_effects(env.root_id),
        env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60),
        return_exceptions=True,
    )
    assert not isinstance(results[0], BaseException)
    assert results[1] == 0 and isinstance(results[2], Conflict)
    await env.store.complete_effect(
        env.claim, effect_key="analysis:one", charged_usd=Decimal("1"), result={}
    )
    await env.store.release_claim(env.claim)


async def test_fresh_attempt_gets_new_limit_after_safe_release(leased):
    env = leased
    await env.store.renew_claim(env.claim, seconds=900)
    async with env.factory() as db:
        old_limit = (await db.get(Account, env.root_id)).attempt_deadline
    await env.store.release_claim(env.claim)
    fresh = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=30)
    assert isinstance(fresh, WorkerClaim) and fresh.generation == env.claim.generation + 2
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert old_limit < account.attempt_deadline <= env.plan.deadline
        assert account.attempt_deadline - account.lease_until == timedelta(seconds=30)


async def test_noop_renewal_still_checks_current_policy(leased):
    await leased.store.renew_claim(leased.claim, seconds=900)
    leased.policy.valid = False
    with pytest.raises(Forbidden):
        await leased.store.renew_claim(leased.claim, seconds=1)
    assert await audit_count(leased, "claim_renewed") == 1


@pytest.mark.parametrize("operation", ["claim", "renew"])
async def test_plan_deadline_rechecked_after_account_lock(leased, monkeypatch, operation):
    from app.autonomous.orchestration import store

    env = leased
    if operation == "claim":
        await env.store.release_claim(env.claim)
    original_now, original_account = store._now, env.store._account
    locked = False

    async def account(db, root_id, session_id):
        nonlocal locked
        row = await original_account(db, root_id, session_id)
        locked = True
        return row

    async def clock(db):
        # Advance only after the account lock; approval used the real DB clock.
        return env.plan.deadline if locked else await original_now(db)

    monkeypatch.setattr(env.store, "_account", account)
    monkeypatch.setattr(store, "_now", clock)
    with pytest.raises(Conflict, match="expired"):
        if operation == "claim":
            await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=30)
        else:
            await env.store.renew_claim(env.claim, seconds=900)
    assert await audit_count(env, "claim_renewed") == 0
    async with env.factory() as db:
        row = await db.get(Account, env.root_id)
        assert row.worker_id == (None if operation == "claim" else env.claim.worker_id)
