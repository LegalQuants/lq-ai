"""Durable governance invariants under separate Postgres transactions."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import PreparedPlan
from app.errors import Conflict, Forbidden
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationAdmission as Admission,
    OrchestrationEffect as Effect,
    OrchestrationPlan as PlanRow,
    OrchestrationRoot as Root,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.autonomous import Phase

pytestmark = pytest.mark.integration


async def begin(env, key="analysis:one", *, amount="1", digest="b" * 64):
    return await env.store.begin_effect(
        env.claim,
        effect_key=key,
        request_hash=digest,
        reservation_usd=Decimal(amount),
        phase=Phase.analysis,
        intent=ToolIntent.run_skill,
    )


async def expire(env):
    async with env.factory.begin() as db:
        await db.execute(
            update(Account)
            .where(Account.session_id == env.claim.session_id)
            .values(lease_until=func.clock_timestamp() - text("interval '1 second'"))
        )


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


async def test_approval_is_a_barrier_and_concurrent_duplicates_are_idempotent(env):
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    with pytest.raises(Conflict):
        await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    bindings = await asyncio.gather(
        *(
            env.store.approve(
                env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
            )
            for _ in range(3)
        )
    )
    assert bindings[0] == bindings[1] == bindings[2]
    assert await audit_count(env, "approved") == 1
    async with env.factory() as db:
        assert (
            await db.scalar(
                select(func.count()).select_from(Admission).where(Admission.root_id == env.root_id)
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AutonomousSession)
                .where(AutonomousSession.parent_session_id == env.root_id)
            )
            == 0
        )


async def test_wrong_owner_stale_hash_and_rejected_plan_cannot_approve(env):
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    with pytest.raises(Forbidden):
        await env.store.approve(
            env.root_id, actor_id=uuid4(), revision=1, plan_hash=env.plan.approval_hash()
        )
    with pytest.raises(Conflict):
        await env.store.approve(env.root_id, actor_id=env.owner_id, revision=1, plan_hash="0" * 64)
    await env.store.reject(env.root_id, actor_id=env.owner_id, revision=1)
    await env.store.reject(env.root_id, actor_id=env.owner_id, revision=1)
    with pytest.raises(Conflict):
        await env.store.approve(
            env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
        )
    assert await audit_count(env, "rejected") == 1


async def test_revised_plan_preserves_old_consent_but_requires_approval_again(env):
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    await env.store.approve(
        env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
    )
    revised = PreparedPlan.model_validate(
        {**env.plan.model_dump(), "revision": 2, "goal": "Revised fixture"}
    )
    await env.store.save_plan(revised, actor_id=env.owner_id)
    with pytest.raises(Conflict):
        await env.store.approve(
            env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
        )
    with pytest.raises(Conflict):
        await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    async with env.factory() as db:
        old = await db.get(PlanRow, (env.root_id, 1))
        assert old.status == "superseded" and old.approval is not None
    await env.store.approve(
        env.root_id, actor_id=env.owner_id, revision=2, plan_hash=revised.approval_hash()
    )


async def test_concurrent_child_admission_is_one_batch_with_fixed_allocations(ready):
    env = ready
    results = await asyncio.gather(*(env.store.admit_children(env.claim) for _ in range(3)))
    assert results[0] == results[1] == results[2] == tuple(c.dispatch_id for c in env.plan.children)
    assert await audit_count(env, "children_admitted") == 1
    async with env.factory() as db:
        allocations = list(
            (
                await db.scalars(
                    select(Account.allocation_usd).where(Account.root_id == env.root_id)
                )
            ).all()
        )
        assert allocations == [Decimal("2")] * 3
        children = list(
            (
                await db.scalars(
                    select(AutonomousSession).where(
                        AutonomousSession.parent_session_id == env.root_id
                    )
                )
            ).all()
        )
        assert len(children) == 2
        assert all(
            c.root_session_id == env.root_id
            and c.delegation_depth == 1
            and c.user_id == env.owner_id
            and c.project_id == env.project_id
            for c in children
        )
    revised = PreparedPlan.model_validate({**env.plan.model_dump(), "revision": 2})
    with pytest.raises(Conflict):
        await env.store.save_plan(revised, actor_id=env.owner_id)


async def test_one_active_root_per_owner_is_database_enforced(env):
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    async with env.factory.begin() as db:
        other = AutonomousSession(
            user_id=env.owner_id, project_id=env.project_id, trigger_kind="manual"
        )
        db.add(other)
        await db.flush()
        other_id = other.id
    another = PreparedPlan.model_validate(
        {**env.plan.model_dump(), "root_id": other_id, "plan_id": uuid4()}
    )
    with pytest.raises(Conflict):
        await env.store.save_plan(another, actor_id=env.owner_id)


async def test_expired_or_halted_plan_cannot_start(env):
    expired = PreparedPlan.model_validate(
        {**env.plan.model_dump(), "deadline": datetime(2000, 1, 1, tzinfo=UTC)}
    )
    with pytest.raises(Conflict):
        await env.store.save_plan(expired, actor_id=env.owner_id)
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    await env.store.halt(env.root_id, actor_id=env.owner_id)
    with pytest.raises(Conflict):
        await env.store.approve(
            env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
        )


async def test_only_one_worker_claim_wins_and_stale_generation_cannot_admit(ready):
    env = ready
    await expire(env)
    claims = await asyncio.gather(
        *(
            env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
            for _ in range(2)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(x, Conflict) for x in claims) == 1
    fresh = next(x for x in claims if not isinstance(x, Exception))
    with pytest.raises(Conflict):
        await begin(env)
    env.claim = fresh
    assert (await begin(env)).status == "admitted"


async def test_duplicate_effect_and_double_settlement_cannot_spend_twice(ready):
    env = ready
    attempts = await asyncio.gather(begin(env), begin(env), return_exceptions=True)
    assert sum(isinstance(x, Conflict) for x in attempts) == 1
    first = await env.store.complete_effect(
        env.claim, effect_key="analysis:one", charged_usd=Decimal("0.5"), result={"content": ""}
    )
    repeated = await env.store.complete_effect(
        env.claim, effect_key="analysis:one", charged_usd=Decimal("0.5"), result={"content": ""}
    )
    assert first == repeated
    replay = await begin(env)
    assert replay.status == "completed" and replay.result == {"content": ""}
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert account.spent_usd == Decimal("0.5") and account.reserved_usd == 0
    assert await audit_count(env, "effect_admitted") == 1
    assert await audit_count(env, "effect_completed") == 1
    with pytest.raises(Conflict):
        await begin(env, digest="c" * 64)
    with pytest.raises(Conflict):
        await env.store.complete_effect(
            env.claim,
            effect_key="analysis:one",
            charged_usd=Decimal("1"),
            result={"content": "changed"},
        )


async def test_unresolved_effect_becomes_uncertain_and_keeps_reservation(ready):
    env = ready
    await begin(env)
    await expire(env)
    with pytest.raises(Conflict, match="reconciliation"):
        await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    async with env.factory() as db:
        effect = await db.get(Effect, (env.root_id, "analysis:one"))
        account = await db.get(Account, env.root_id)
        root = await db.get(Root, env.root_id)
        assert effect.status == "uncertain" and account.reserved_usd == 1 and account.spent_usd == 0
        assert root.status == "uncertain"
    with pytest.raises(Conflict):
        await env.store.complete_effect(
            env.claim, effect_key="analysis:one", charged_usd=Decimal("0.5"), result={}
        )
    with pytest.raises(Conflict):
        await begin(env, "analysis:two")


async def test_completed_receipt_survives_new_worker_generation(ready):
    env = ready
    await begin(env)
    await env.store.complete_effect(
        env.claim,
        effect_key="analysis:one",
        charged_usd=Decimal("0.5"),
        result={"outcome": "empty"},
    )
    await expire(env)
    env.claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    assert (await begin(env)).result == {"outcome": "empty"}
    assert await audit_count(env, "effect_admitted") == 1


async def test_halt_blocks_new_calls_but_allows_one_admitted_completion(ready):
    env = ready
    await begin(env)
    await env.store.halt(env.root_id, actor_id=env.owner_id)
    await env.store.complete_effect(
        env.claim, effect_key="analysis:one", charged_usd=Decimal("0.5"), result={}
    )
    with pytest.raises(Conflict):
        await begin(env, "analysis:two")


@pytest.mark.parametrize("revocation", ["policy", "optout", "archive"])
async def test_current_revocation_stops_admission_but_halt_stays_reachable(ready, revocation):
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
                    .values(archived_at=func.now())
                )
    with pytest.raises(Forbidden):
        await begin(env)
    await env.store.halt(env.root_id, actor_id=env.owner_id)
    assert await audit_count(env, "halted") == 1


async def test_stronger_project_floor_revokes_weaker_plan(env):
    scope = env.plan.root.model_copy(update={"minimum_inference_tier": 3})
    env.plan = env.plan.model_copy(
        update={
            "root": scope,
            "children": tuple(c.model_copy(update={"execution": scope}) for c in env.plan.children),
        }
    )
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    await env.store.approve(
        env.root_id, actor_id=env.owner_id, revision=1, plan_hash=env.plan.approval_hash()
    )
    env.claim = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    async with env.factory.begin() as db:
        await db.execute(
            update(Project).where(Project.id == env.project_id).values(minimum_inference_tier=2)
        )
    with pytest.raises(Forbidden, match="Project data policy"):
        await begin(env)
    await env.store.halt(env.root_id, actor_id=env.owner_id)


@pytest.mark.parametrize(
    "project_floor,plan_floor,allowed", [(None, 4, True), (3, 2, True), (2, 3, False)]
)
async def test_plan_preparation_uses_gateway_tier_direction(
    env, project_floor, plan_floor, allowed
):
    async with env.factory.begin() as db:
        await db.execute(
            update(Project)
            .where(Project.id == env.project_id)
            .values(minimum_inference_tier=project_floor)
        )
    scope = env.plan.root.model_copy(update={"minimum_inference_tier": plan_floor})
    env.plan = env.plan.model_copy(
        update={
            "root": scope,
            "children": tuple(c.model_copy(update={"execution": scope}) for c in env.plan.children),
        }
    )
    if allowed:
        await env.store.save_plan(env.plan, actor_id=env.owner_id)
    else:
        with pytest.raises(Forbidden, match="Project data policy"):
            await env.store.save_plan(env.plan, actor_id=env.owner_id)


async def test_budget_reservation_and_observed_overrun_are_honest(ready):
    env = ready
    with pytest.raises(Conflict):
        await begin(env, amount="2.0001")
    await begin(env)
    with pytest.raises(Conflict):
        await begin(env, "analysis:two", amount="0")
    await env.store.complete_effect(
        env.claim,
        effect_key="analysis:one",
        charged_usd=Decimal("3"),
        result={"provider_actual": "3"},
    )
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        root = await db.get(Root, env.root_id)
        assert account.spent_usd == 3 and account.reserved_usd == 0
        assert root.status == "halted" and root.stop_reason == "observed_budget_overrun"


async def test_audit_failure_rolls_back_effect_and_reservation(ready, monkeypatch):
    env = ready

    async def fail(*args, **kwargs):
        raise RuntimeError("fixture audit failure")

    monkeypatch.setattr("app.autonomous.orchestration.store._audit", fail)
    with pytest.raises(RuntimeError, match="fixture audit"):
        await begin(env)
    async with env.factory() as db:
        assert await db.get(Effect, (env.root_id, "analysis:one")) is None
        assert (await db.get(Account, env.root_id)).reserved_usd == 0


async def test_hierarchy_rejects_cross_project_depth_and_mutation(ready):
    env = ready
    children = await env.store.admit_children(env.claim)
    async with env.factory() as db:
        legacy = await db.get(AutonomousSession, env.root_id)
        assert legacy.root_session_id == legacy.id and legacy.delegation_depth == 0
    with pytest.raises(IntegrityError):
        async with env.factory.begin() as db:
            db.add(
                AutonomousSession(
                    user_id=env.owner_id,
                    project_id=None,
                    trigger_kind="manual",
                    parent_session_id=env.root_id,
                    root_session_id=env.root_id,
                    delegation_depth=1,
                    child_order=1,
                )
            )
    with pytest.raises(IntegrityError):
        async with env.factory.begin() as db:
            db.add(
                AutonomousSession(
                    user_id=env.owner_id,
                    project_id=env.project_id,
                    trigger_kind="manual",
                    parent_session_id=children[0],
                    root_session_id=children[0],
                    delegation_depth=1,
                    child_order=1,
                )
            )
    with pytest.raises(IntegrityError):
        async with env.factory.begin() as db:
            await db.execute(
                update(AutonomousSession)
                .where(AutonomousSession.id == children[0])
                .values(
                    parent_session_id=None,
                    root_session_id=children[0],
                    delegation_depth=0,
                    child_order=None,
                )
            )


async def test_audit_contains_no_plan_or_result_text(ready):
    env = ready
    await begin(env)
    await env.store.complete_effect(
        env.claim,
        effect_key="analysis:one",
        charged_usd=Decimal("0"),
        result={"private": "sensitive result marker"},
    )
    async with env.factory() as db:
        details = list(
            (
                await db.scalars(
                    select(AuditLog.details).where(
                        AuditLog.resource_id == str(env.root_id),
                        AuditLog.action.like("orchestration.%"),
                    )
                )
            ).all()
        )
    assert "sensitive result marker" not in str(details)
    assert "Fixture" not in str(details)


async def test_deleted_children_are_not_silently_readmitted(ready):
    env = ready
    children = await env.store.admit_children(env.claim)
    async with env.factory.begin() as db:
        await db.execute(delete(AutonomousSession).where(AutonomousSession.id.in_(children)))
    with pytest.raises(Conflict, match="do not match"):
        await env.store.admit_children(env.claim)


async def test_effect_identity_includes_phase_and_intent(ready):
    env = ready
    await begin(env)
    await env.store.complete_effect(
        env.claim, effect_key="analysis:one", charged_usd=Decimal("0"), result={}
    )
    with pytest.raises(Conflict, match="different input"):
        await env.store.begin_effect(
            env.claim,
            effect_key="analysis:one",
            request_hash="b" * 64,
            reservation_usd=Decimal("1"),
            phase=Phase.analysis,
            intent=ToolIntent.run_playbook,
        )


async def test_recovery_after_halt_and_optout_keeps_uncertainty_visible(ready):
    env = ready
    await begin(env)
    await env.store.halt(env.root_id, actor_id=env.owner_id)
    await expire(env)
    async with env.factory.begin() as db:
        await db.execute(
            update(User).where(User.id == env.owner_id).values(autonomous_enabled=False)
        )
    assert await env.store.recover_expired_effects(env.root_id) == 1
    assert await env.store.recover_expired_effects(env.root_id) == 0
    assert await audit_count(env, "effect_uncertain") == 1
    async with env.factory() as db:
        assert (await db.get(Effect, (env.root_id, "analysis:one"))).status == "uncertain"
        assert (await db.get(Account, env.root_id)).reserved_usd == 1


async def test_child_admission_audit_failure_rolls_back_whole_batch(ready, monkeypatch):
    env = ready

    async def fail(*args, **kwargs):
        raise RuntimeError("fixture admission audit failure")

    monkeypatch.setattr("app.autonomous.orchestration.store._audit", fail)
    with pytest.raises(RuntimeError):
        await env.store.admit_children(env.claim)
    async with env.factory() as db:
        assert (await db.get(Root, env.root_id)).admitted_revision is None
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AutonomousSession)
                .where(AutonomousSession.parent_session_id == env.root_id)
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count()).select_from(Account).where(Account.root_id == env.root_id)
            )
            == 1
        )


async def test_tampered_durable_consent_refuses_child_admission(ready):
    env = ready
    async with env.factory.begin() as db:
        stored = await db.get(PlanRow, (env.root_id, 1))
        stored.approval = {**stored.approval, "plan_hash": "0" * 64}
    with pytest.raises(Conflict):
        await env.store.admit_children(env.claim)
    assert await audit_count(env, "children_admitted") == 0


async def test_prior_planning_cost_is_not_reset_by_plan_storage_or_revision(env):
    async with env.factory.begin() as db:
        await db.execute(
            update(AutonomousSession)
            .where(AutonomousSession.id == env.root_id)
            .values(cost_total_usd=Decimal("0.75"))
        )
    await env.store.save_plan(env.plan, actor_id=env.owner_id)
    revised = PreparedPlan.model_validate(
        {**env.plan.model_dump(), "revision": 2, "root_allowance_usd": Decimal("1")}
    )
    await env.store.save_plan(revised, actor_id=env.owner_id)
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert account.spent_usd == Decimal("0.75") and account.allocation_usd == 1
    too_small = PreparedPlan.model_validate(
        {**revised.model_dump(), "revision": 3, "root_allowance_usd": Decimal("0.5")}
    )
    with pytest.raises(Conflict):
        await env.store.save_plan(too_small, actor_id=env.owner_id)


async def test_initial_allowance_cannot_discard_prior_spend(env):
    async with env.factory.begin() as db:
        await db.execute(
            update(AutonomousSession)
            .where(AutonomousSession.id == env.root_id)
            .values(cost_total_usd=Decimal("3"))
        )
    with pytest.raises(Conflict, match="Prior root spend"):
        await env.store.save_plan(env.plan, actor_id=env.owner_id)
    async with env.factory() as db:
        assert await db.get(Root, env.root_id) is None


async def test_child_phase_transaction_does_not_lock_its_parent(ready):
    env = ready
    children = await env.store.admit_children(env.claim)
    async with env.factory.begin() as child_db:
        await child_db.execute(
            update(AutonomousSession)
            .where(AutonomousSession.id == children[0])
            .values(current_phase="analysis")
        )

        async def halt_parent():
            async with env.factory.begin() as root_db:
                await root_db.execute(
                    update(AutonomousSession)
                    .where(AutonomousSession.id == env.root_id)
                    .values(halt_state="halt_requested")
                )

        # The child transaction remains open, as it can during a guarded call.
        # Ordinary child updates must not make an independent root halt wait.
        await asyncio.wait_for(halt_parent(), timeout=2)


async def test_release_preserves_completed_receipt_and_fences_old_worker(ready):
    env = ready
    await begin(env)
    receipt = await env.store.complete_effect(
        env.claim, effect_key="analysis:one", charged_usd=Decimal("0.5"), result={"content": "done"}
    )
    async with env.factory() as db:
        approved = (await db.get(PlanRow, (env.root_id, 1))).approval
    await env.store.release_claim(env.claim)
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert account.worker_id is account.lease_until is None
        assert account.generation == env.claim.generation + 1
        assert account.spent_usd == Decimal("0.5") and account.reserved_usd == 0
        assert (await db.get(Root, env.root_id)).status == "running"
        assert (await db.get(PlanRow, (env.root_id, 1))).approval == approved
        effect = await db.get(Effect, (env.root_id, "analysis:one"))
        assert effect.status == receipt.status == "completed"
        assert effect.result == receipt.result and effect.charged_usd == receipt.charged_usd
    assert await audit_count(env, "claim_released") == 1
    with pytest.raises(Conflict, match="stale"):
        await env.store.release_claim(env.claim)
    fresh = await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)
    assert fresh.generation == env.claim.generation + 2
    with pytest.raises(Conflict, match="stale"):
        await env.store.release_claim(env.claim)
    with pytest.raises(Conflict, match="stale"):
        await begin(env, key="analysis:stale")
    with pytest.raises(Conflict, match="stale"):
        await env.store.complete_effect(
            env.claim, effect_key="analysis:one", charged_usd=Decimal("0"), result={}
        )
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert account.worker_id == fresh.worker_id and account.generation == fresh.generation
        assert account.spent_usd == Decimal("0.5")


@pytest.mark.parametrize(
    "pending_status,amount",
    [
        ("admitted", "1"),
        ("admitted", "0"),
        ("uncertain", "1"),
        ("uncertain", "0"),
        ("orphan_reservation", "1"),
    ],
)
async def test_release_refuses_outstanding_effect_or_reservation(ready, pending_status, amount):
    env = ready
    if pending_status == "orphan_reservation":
        async with env.factory.begin() as db:
            await db.execute(
                update(Account).where(Account.session_id == env.root_id).values(reserved_usd=1)
            )
    else:
        await begin(env, amount=amount)
        if pending_status == "uncertain":
            # Isolate the unresolved-receipt check from recovery's usual fence.
            async with env.factory.begin() as db:
                await db.execute(
                    update(Effect)
                    .where(Effect.session_id == env.root_id)
                    .values(status="uncertain")
                )
    with pytest.raises(Conflict, match="Outstanding effect"):
        await env.store.release_claim(env.claim)
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert (
            account.worker_id == env.claim.worker_id and account.generation == env.claim.generation
        )
        assert account.lease_until is not None and account.reserved_usd == Decimal(amount)
        if pending_status != "orphan_reservation":
            assert (await db.get(Effect, (env.root_id, "analysis:one"))).status == pending_status
    assert await audit_count(env, "claim_released") == 0


@pytest.mark.parametrize("revocation", ["policy", "halt", "optout", "archive", "project_policy"])
async def test_release_allows_revoked_cleanup_but_not_execution(ready, revocation):
    env = ready
    if revocation == "policy":
        env.policy.valid = False
    elif revocation == "halt":
        await env.store.halt(env.root_id, actor_id=env.owner_id)
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
                    .values(archived_at=func.now())
                )
            else:
                await db.execute(
                    update(Project)
                    .where(Project.id == env.project_id)
                    .values(privileged=True, minimum_inference_tier=1)
                )
    async with env.factory() as db:
        root = await db.get(Root, env.root_id)
        state = root.status, root.stop_reason
    await env.store.release_claim(env.claim)
    async with env.factory() as db:
        root = await db.get(Root, env.root_id)
        assert (root.status, root.stop_reason) == state
        assert (await db.get(Account, env.root_id)).worker_id is None
    with pytest.raises((Conflict, Forbidden)):
        await env.store.claim(env.root_id, env.root_id, worker_id=uuid4(), seconds=60)


async def test_release_audit_failure_rolls_back_ownership_and_audit(ready, monkeypatch):
    from app.autonomous.orchestration import store

    env = ready
    original = store._audit

    async def fail(db, root, event, **details):
        await original(db, root, event, **details)
        if event == "claim_released":
            raise RuntimeError("release audit fixture failure")

    monkeypatch.setattr(store, "_audit", fail)
    with pytest.raises(RuntimeError, match="release audit"):
        await env.store.release_claim(env.claim)
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert (
            account.worker_id == env.claim.worker_id and account.generation == env.claim.generation
        )
        assert account.lease_until is not None
    assert await audit_count(env, "claim_released") == 0
    await begin(env)


async def test_release_expired_or_wrong_claim_cannot_clear_ownership(ready):
    from dataclasses import replace

    env = ready
    for wrong in (
        replace(env.claim, worker_id=uuid4()),
        replace(env.claim, generation=env.claim.generation + 1),
        replace(env.claim, session_id=uuid4()),
    ):
        with pytest.raises(Conflict):
            await env.store.release_claim(wrong)
    await expire(env)
    with pytest.raises(Conflict, match="expired"):
        await env.store.release_claim(env.claim)
    assert await audit_count(env, "claim_released") == 0
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert (
            account.worker_id == env.claim.worker_id and account.generation == env.claim.generation
        )


async def test_release_waiting_parent_and_child_ownership_are_independent(ready):
    env = ready
    children = await env.store.admit_children(env.claim)
    await env.store.release_claim(env.claim)
    async with env.factory() as db:
        assert (await db.get(Root, env.root_id)).status == "waiting_children"
    claims = [
        await env.store.claim(env.root_id, child, worker_id=uuid4(), seconds=60)
        for child in children
    ]
    await env.store.release_claim(claims[0])
    async with env.factory() as db:
        assert (await db.get(Account, children[0])).worker_id is None
        sibling = await db.get(Account, children[1])
        assert (
            sibling.worker_id == claims[1].worker_id and sibling.generation == claims[1].generation
        )
        assert (await db.get(Account, env.root_id)).generation == env.claim.generation + 1
        assert (await db.get(Root, env.root_id)).admitted_revision == 1


async def test_release_racing_effect_admission_has_one_safe_winner(ready):
    env = ready
    released, admitted = await asyncio.gather(
        env.store.release_claim(env.claim), begin(env), return_exceptions=True
    )
    assert sum(isinstance(result, Conflict) for result in (released, admitted)) == 1
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        effect = await db.get(Effect, (env.root_id, "analysis:one"))
        if released is None:
            assert isinstance(admitted, Conflict)
            assert effect is None and account.reserved_usd == 0
            assert account.worker_id is None and account.generation == env.claim.generation + 1
        else:
            assert isinstance(released, Conflict) and not isinstance(admitted, BaseException)
            assert effect.status == "admitted" and account.reserved_usd == 1
            assert (
                account.worker_id == env.claim.worker_id
                and account.generation == env.claim.generation
            )


async def test_release_rechecks_expiry_after_waiting_for_account_lock(ready, monkeypatch):
    env = ready
    waiting = asyncio.Event()
    original = env.store._account

    async def observe_lock(db, root_id, session_id):
        waiting.set()
        return await original(db, root_id, session_id)

    monkeypatch.setattr(env.store, "_account", observe_lock)
    async with asyncio.TaskGroup() as group:
        async with env.factory.begin() as blocker:
            account = await blocker.scalar(
                select(Account).where(Account.session_id == env.root_id).with_for_update()
            )

            async def release():
                with pytest.raises(Conflict, match="expired"):
                    await env.store.release_claim(env.claim)

            attempt = group.create_task(release())
            await asyncio.wait_for(waiting.wait(), timeout=2)
            # Expire while release is blocked, using the database clock rather
            # than sleeping. Its post-lock check must see this committed value.
            account.lease_until = await blocker.scalar(select(func.clock_timestamp()))
        await asyncio.wait_for(attempt, timeout=2)
    assert await audit_count(env, "claim_released") == 0
    async with env.factory() as db:
        account = await db.get(Account, env.root_id)
        assert (
            account.generation == env.claim.generation and account.worker_id == env.claim.worker_id
        )
