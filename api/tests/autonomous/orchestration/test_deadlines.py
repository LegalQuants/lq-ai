"""Root deadlines end clean waits without erasing uncertainty or prior outcomes."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration import store
from app.errors import Conflict, Forbidden
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationEffect as Effect,
    OrchestrationPlan as PlanRow,
    OrchestrationRoot as Root,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.autonomous import Phase

pytestmark = pytest.mark.integration


def due(env, monkeypatch):
    async def clock(db):
        return env.plan.deadline

    monkeypatch.setattr(store, "_now", clock)


async def audits(env, event):
    async with env.factory() as db:
        return await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.resource_id == str(env.root_id),
                AuditLog.action == f"orchestration.{event}",
            )
        )


async def effect(env, *, amount="1"):
    await env.store.begin_effect(
        env.claim,
        effect_key="analysis:one",
        request_hash="b" * 64,
        reservation_usd=Decimal(amount),
        phase=Phase.analysis,
        intent=ToolIntent.run_skill,
    )


async def prepare(env, state):
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    if state == "awaiting_approval":
        return
    await env.store.approve(
        env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
    )
    if state == "queued":
        return
    env.claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    if state == "waiting_children":
        await env.store.admit_children(env.claim)


@pytest.mark.parametrize("state", ["awaiting_approval", "queued", "running", "waiting_children"])
async def test_clean_deadline_ends_active_and_waiting_roots_once(env, monkeypatch, state):
    await prepare(env, state)
    async with env.factory() as db:
        session = await db.get(AutonomousSession, env.root_id)
        legacy = (
            session.status,
            session.halt_state,
            session.current_phase,
            session.last_activity_at,
        )
        approval = (await db.get(PlanRow, (env.root_id, 1))).approval
    assert not await env.store.expire_root(env.root_id)
    assert await audits(env, "root_expired") == 0
    due(env, monkeypatch)
    results = await asyncio.gather(*(env.store.expire_root(env.root_id) for _ in range(3)))
    assert sorted(results) == [False, False, True]
    async with env.factory() as db:
        root = await db.get(Root, env.root_id)
        assert (root.status, root.stop_reason) == ("expired", "root_deadline")
        accounts = (await db.scalars(select(Account).where(Account.root_id == env.root_id))).all()
        assert all(a.worker_id is a.lease_until is a.attempt_deadline is None for a in accounts)
        assert all(a.spent_usd == a.reserved_usd == 0 for a in accounts)
        assert (await db.get(PlanRow, (env.root_id, 1))).approval == approval
        session = await db.get(AutonomousSession, env.root_id)
        assert (
            session.status,
            session.halt_state,
            session.current_phase,
            session.last_activity_at,
        ) == legacy
    assert await audits(env, "root_expired") == 1
    assert await audits(env, "claim_expired") == int(state in {"running", "waiting_children"})
    with pytest.raises(Conflict):
        await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)


@pytest.mark.parametrize(
    "state", ["halted", "completed", "failed", "rejected", "expired", "uncertain"]
)
async def test_deadline_preserves_prior_clean_outcome_and_receipt(ready, monkeypatch, state):
    env = ready
    await effect(env)
    await env.store.complete_effect(
        env.claim,
        effect_key="analysis:one",
        charged_usd=Decimal("1"),
        result={"fixture": "receipt"},
    )
    async with env.factory.begin() as db:
        root = await db.get(Root, env.root_id)
        root.status, root.stop_reason = state, "existing_reason"
        progress = root.updated_at
    due(env, monkeypatch)
    assert not await env.store.expire_root(env.root_id)
    async with env.factory() as db:
        root = await db.get(Root, env.root_id)
        assert (root.status, root.stop_reason, root.updated_at) == (
            state,
            "existing_reason",
            progress,
        )
        account = await db.get(Account, env.root_id)
        assert account.worker_id is None and account.spent_usd == 1 and account.reserved_usd == 0
        receipt = await db.get(Effect, (env.root_id, "analysis:one"))
        assert receipt.status == "completed" and receipt.result == {"fixture": "receipt"}
    assert await audits(env, "root_expired") == await audits(env, "deadline_uncertain") == 0


@pytest.mark.parametrize(
    "pending,owned,amount",
    [
        ("admitted", True, "1"),
        ("admitted", True, "0"),
        ("uncertain", False, "0"),
        (None, False, "1"),
    ],
)
@pytest.mark.parametrize("child_run", [False, True])
async def test_deadline_never_hides_unresolved_accounting(
    ready, monkeypatch, pending, owned, amount, child_run
):
    env = ready
    if child_run:
        children = await env.store.admit_children(env.claim)
        env.claim = await env.store.claim(env.root_id, children[0], worker_id=uuid4(), seconds=60)
        async with env.factory.begin() as db:
            (await db.get(AutonomousSession, children[0])).current_phase = "analysis"
    session_id = env.claim.session_id
    if pending is not None:
        await effect(env, amount=amount)
    async with env.factory.begin() as db:
        account = await db.get(Account, session_id)
        if not owned:
            account.worker_id = account.lease_until = account.attempt_deadline = None
        if pending == "uncertain":
            (await db.get(Effect, (session_id, "analysis:one"))).status = "uncertain"
        elif pending is None:
            account.reserved_usd = Decimal(amount)
    due(env, monkeypatch)
    assert not await env.store.expire_root(env.root_id)
    assert not await env.store.expire_root(env.root_id)
    async with env.factory() as db:
        root = await db.get(Root, env.root_id)
        assert root.status == "uncertain"
        assert root.stop_reason == ("unresolved_effect" if pending else "unresolved_reservation")
        account = await db.get(Account, session_id)
        assert account.worker_id is None and account.reserved_usd == Decimal(amount)
        if pending:
            assert (await db.get(Effect, (session_id, "analysis:one"))).status == "uncertain"
    assert await audits(env, "root_expired") == 0
    assert await audits(env, "deadline_uncertain") == 1


@pytest.mark.parametrize("revocation", ["policy", "optout", "archive", "project_policy"])
async def test_deadline_cleanup_does_not_require_execution_permission(
    ready, monkeypatch, revocation
):
    env = ready
    if revocation == "policy":
        env.policy.valid = False
    else:
        async with env.factory.begin() as db:
            if revocation == "optout":
                await db.execute(
                    update(User).where(User.id == env.owner_id).values(autonomous_enabled=False)
                )
            elif revocation == "archive":
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
    due(env, monkeypatch)
    assert await env.store.expire_root(env.root_id)
    with pytest.raises((Conflict, Forbidden)):
        await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)


@pytest.mark.parametrize("corruption", ["snapshot", "hash", "identity"])
async def test_deadline_rejects_invalid_stored_plan_without_guessing(
    ready, monkeypatch, corruption
):
    env = ready
    async with env.factory.begin() as db:
        plan = await db.get(PlanRow, (env.root_id, 1))
        if corruption == "snapshot":
            plan.snapshot = {}
        elif corruption == "hash":
            plan.plan_hash = "0" * 64
        else:
            plan.snapshot = {**plan.snapshot, "owner_id": str(uuid4())}
    due(env, monkeypatch)
    with pytest.raises(Conflict, match="Stored"):
        await env.store.expire_root(env.root_id)
    async with env.factory() as db:
        assert (await db.get(Root, env.root_id)).status == "running"
        assert (await db.get(Account, env.root_id)).worker_id == env.claim.worker_id
    # Expired ownership can still be narrowed independently of plan validity.
    assert await env.store.recover_expired_claims(env.root_id) == 1


@pytest.mark.parametrize("pending", [False, True])
async def test_deadline_audit_failure_rolls_back_cleanup_and_lifecycle(ready, monkeypatch, pending):
    env = ready
    if pending:
        await effect(env)
    original = store._audit

    async def fail(db, root, event, **details):
        await original(db, root, event, **details)
        if event in {"root_expired", "deadline_uncertain"}:
            raise RuntimeError("deadline audit failed")

    monkeypatch.setattr(store, "_audit", fail)
    due(env, monkeypatch)
    with pytest.raises(RuntimeError, match="deadline audit"):
        await env.store.expire_root(env.root_id)
    async with env.factory() as db:
        root = await db.get(Root, env.root_id)
        account = await db.get(Account, env.root_id)
        assert root.status == "running" and root.stop_reason is None
        assert (
            account.worker_id == env.claim.worker_id and account.generation == env.claim.generation
        )
        if pending:
            assert (await db.get(Effect, (env.root_id, "analysis:one"))).status == "admitted"
            assert account.reserved_usd == 1
    for event in ("claim_expired", "effect_uncertain", "root_expired", "deadline_uncertain"):
        assert await audits(env, event) == 0


async def test_plan_revision_and_expiry_race_uses_the_locked_current_plan(env, monkeypatch):
    await prepare(env, "awaiting_approval")
    revised = env.plan.model_copy(
        update={"revision": 2, "deadline": env.plan.deadline + timedelta(hours=1)}
    )
    due(env, monkeypatch)
    result, saved = await asyncio.gather(
        env.store.expire_root(env.root_id),
        env.store.save_plan(revised, actor_id=env.owner_id),
        return_exceptions=True,
    )
    async with env.factory() as db:
        root = await db.get(Root, env.root_id)
        if result is True:
            assert (
                isinstance(saved, Conflict)
                and root.status == "expired"
                and root.current_revision == 1
            )
        else:
            assert result is False and not isinstance(saved, BaseException)
            assert root.status == "awaiting_approval" and root.current_revision == 2


async def test_clean_expiration_preserves_charge_and_frees_owner_root_slot(ready, monkeypatch):
    env = ready
    await effect(env)
    await env.store.complete_effect(
        env.claim, effect_key="analysis:one", charged_usd=Decimal("1"), result={"fixture": "done"}
    )
    async with env.factory.begin() as db:
        session = AutonomousSession(
            user_id=env.owner_id,
            project_id=env.project_id,
            trigger_kind="manual",
            max_cost_usd=Decimal("10"),
        )
        db.add(session)
        await db.flush()
        new_id = session.id
    next_plan = env.plan.model_copy(
        update={
            "plan_id": uuid4(),
            "root_id": new_id,
            "deadline": env.plan.deadline + timedelta(hours=1),
        }
    )
    with pytest.raises(Conflict):
        await env.store.save_plan(next_plan, actor_id=env.owner_id)
    due(env, monkeypatch)
    assert await env.store.expire_root(env.root_id)
    await env.store.save_plan(next_plan, actor_id=env.owner_id)
    async with env.factory() as db:
        assert (await db.get(Root, new_id)).status == "awaiting_approval"
        assert (await db.get(Account, env.root_id)).spent_usd == 1
        receipt = await db.get(Effect, (env.root_id, "analysis:one"))
        assert receipt.status == "completed" and receipt.result == {"fixture": "done"}


async def test_deadline_audits_new_reason_on_already_uncertain_root(ready, monkeypatch):
    env = ready
    async with env.factory.begin() as db:
        root = await db.get(Root, env.root_id)
        root.status = "uncertain"
        assert root.stop_reason is None
        account = await db.get(Account, env.root_id)
        account.worker_id = account.lease_until = account.attempt_deadline = None
        account.reserved_usd = Decimal("1")
    due(env, monkeypatch)
    assert not await env.store.expire_root(env.root_id)
    assert not await env.store.expire_root(env.root_id)
    assert await audits(env, "deadline_uncertain") == 1
    async with env.factory() as db:
        assert (await db.get(Root, env.root_id)).stop_reason == "unresolved_reservation"
