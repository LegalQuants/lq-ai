"""Short, application-owned governance transactions for ADR 0035.

No provider calls, queue writes or LangGraph types belong here. Public methods
commit before returning. A required current-policy checker must validate pinned
skills, selected resources and current operator grants with database/local policy
reads only. No permissive production checker or dispatch endpoint is supplied.

Lock order: owner -> project -> root -> account -> effect. The owner/project
share locks also serialize revocation with admission. Every worker operation
locks the root; root halt and effect admission therefore have one ordering.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from pydantic import TypeAdapter, ValidationError as SchemaError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import audit_action
from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import (
    ApprovalBinding,
    ExecutionScope,
    Money,
    PreparedPlan,
)
from app.errors import Conflict, Forbidden, NotFound, ValidationError
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

_ACTIVE = frozenset({"queued", "running", "waiting_children"})
_MONEY: TypeAdapter[Decimal] = TypeAdapter(Money)
_EVENTS = frozenset(
    {
        "plan_saved",
        "approved",
        "rejected",
        "children_admitted",
        "claimed",
        "claim_released",
        "claim_renewed",
        "claim_expired",
        "root_expired",
        "deadline_uncertain",
        "halted",
        "effect_admitted",
        "effect_completed",
        "effect_uncertain",
    }
)


class CurrentPolicyCheck(Protocol):
    async def __call__(self, db: AsyncSession, plan: PreparedPlan) -> None:
        """Raise on stale policy/resources/skills; no remote I/O or commits."""
        ...


@dataclass(frozen=True)
class WorkerClaim:
    root_id: UUID
    session_id: UUID
    worker_id: UUID
    generation: int


@dataclass(frozen=True)
class EffectReceipt:
    session_id: UUID
    effect_key: str
    status: str
    reserved_usd: Decimal
    charged_usd: Decimal | None
    result: dict[str, Any] | None


@dataclass(frozen=True)
class ExecutionView:
    plan: PreparedPlan
    scope: ExecutionScope
    lease_seconds: float


def _receipt(effect: Effect) -> EffectReceipt:
    return EffectReceipt(
        effect.session_id,
        effect.effect_key,
        effect.status,
        effect.reserved_usd,
        effect.charged_usd,
        effect.result,
    )


def _money(value: Decimal) -> Decimal:
    try:
        return _MONEY.validate_python(value)
    except SchemaError:
        raise ValidationError(
            message="Amount must be finite, nonnegative and exact to four decimal places"
        ) from None


async def _now(db: AsyncSession) -> datetime:
    return (await db.execute(select(func.clock_timestamp()))).scalar_one()


def _project_scope(project: Project, plan: PreparedPlan) -> None:
    # Gateway tier semantics: lower numbers provide stronger protection.
    # An unset project floor adds no restriction beyond the explicit plan.
    if plan.root.minimum_inference_tier > (project.minimum_inference_tier or 5) or (
        project.privileged and not plan.root.privileged
    ):
        raise Forbidden(message="Project data policy has changed")


async def _audit(db: AsyncSession, root: Root, event: str, **details: Any) -> None:
    assert event in _EVENTS
    await audit_action(
        db,
        user_id=root.owner_id,
        project_id=root.project_id,
        action=f"orchestration.{event}",
        resource_type="autonomous_session",
        resource_id=str(root.session_id),
        details=details,
    )


class OrchestrationStore:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, check_policy: CurrentPolicyCheck
    ) -> None:
        self.sessions = sessions
        self.check_policy = check_policy

    async def _owner_project(
        self, db: AsyncSession, owner_id: UUID, project_id: UUID, *, creating: bool = False
    ) -> Project:
        owner = await db.scalar(
            select(User).where(User.id == owner_id).with_for_update(read=not creating)
        )
        if owner is None or not owner.autonomous_enabled:
            raise Forbidden(message="Autonomous execution is not enabled for this owner")
        project = await db.scalar(
            select(Project).where(Project.id == project_id).with_for_update(read=True)
        )
        if project is None or project.owner_id != owner_id or project.archived_at is not None:
            raise Forbidden(message="Orchestration requires an owned active project")
        return project

    async def _root(self, db: AsyncSession, root_id: UUID) -> tuple[Root, PreparedPlan, datetime]:
        row = await db.get(Root, root_id)
        if row is None:
            raise NotFound(message="Orchestration root not found")
        project = await self._owner_project(db, row.owner_id, row.project_id)
        root = (
            await db.execute(
                select(Root)
                .where(Root.session_id == root_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        plan = await self._stored_plan(db, root)
        _project_scope(project, plan)
        return root, plan, await _now(db)

    async def _stored_plan(self, db: AsyncSession, root: Root) -> PreparedPlan:
        stored = await db.get(PlanRow, (root.session_id, root.current_revision))
        if stored is None:
            raise Conflict(message="Current orchestration plan is missing")
        try:
            plan = PreparedPlan.model_validate_json(json.dumps(stored.snapshot))
        except SchemaError:
            raise Conflict(message="Stored orchestration plan is invalid") from None
        if (
            plan.root_id,
            plan.owner_id,
            plan.project_id,
            plan.plan_id,
            plan.revision,
            plan.approval_hash(),
        ) != (
            root.session_id,
            root.owner_id,
            root.project_id,
            root.plan_id,
            root.current_revision,
            stored.plan_hash,
        ):
            raise Conflict(message="Stored plan identity does not match the root")
        return plan

    async def _live(self, db: AsyncSession, root: Root, plan: PreparedPlan, now: datetime) -> None:
        session = await db.get(AutonomousSession, root.session_id)
        if (
            session is None
            or session.parent_session_id is not None
            or session.trigger_kind != "manual"
            or session.user_id != root.owner_id
            or session.project_id != root.project_id
        ):
            raise Conflict(message="Root session scope is invalid")
        if session.halt_state != "running" or session.status != "running" or now >= plan.deadline:
            raise Conflict(message="Root session is stopped or expired")
        await self.check_policy(db, plan)
        if await _now(db) >= plan.deadline:
            raise Conflict(message="Plan expired during policy validation")

    async def _approved(
        self, db: AsyncSession, root: Root, plan: PreparedPlan, now: datetime
    ) -> None:
        if root.status not in _ACTIVE:
            raise Conflict(message="Root is not approved for execution")
        stored = await db.get(PlanRow, (root.session_id, root.current_revision))
        if stored is None or stored.status != "approved" or stored.approval is None:
            raise Conflict(message="Durable approval is missing")
        try:
            binding = ApprovalBinding.model_validate_json(json.dumps(stored.approval))
        except SchemaError:
            raise Conflict(message="Stored approval is invalid") from None
        binding.require_matches(plan, now=now)
        await self._live(db, root, plan, now)

    async def save_plan(self, plan: PreparedPlan, *, actor_id: UUID) -> None:
        plan = PreparedPlan.model_validate(plan)
        if actor_id != plan.owner_id:
            raise Forbidden(message="Only the owner may prepare this plan")
        try:
            async with self.sessions.begin() as db:
                project = await self._owner_project(
                    db, plan.owner_id, plan.project_id, creating=True
                )
                _project_scope(project, plan)
                root = await db.scalar(
                    select(Root).where(Root.session_id == plan.root_id).with_for_update()
                )
                if root is None:
                    if plan.revision != 1:
                        raise Conflict(message="A new plan starts at revision one")
                    root = Root(
                        session_id=plan.root_id,
                        owner_id=plan.owner_id,
                        project_id=plan.project_id,
                        plan_id=plan.plan_id,
                        current_revision=1,
                        status="awaiting_approval",
                    )
                    await self._live(db, root, plan, await _now(db))
                    session = await db.scalar(
                        select(AutonomousSession)
                        .where(AutonomousSession.id == plan.root_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    assert session is not None
                    prior_spend = _money(session.cost_total_usd)
                    if prior_spend > plan.root_allowance_usd:
                        raise Conflict(
                            message="Prior root spend exceeds the planning/finishing allowance"
                        )
                    db.add(root)
                    await db.flush()
                    db.add(
                        Account(
                            session_id=plan.root_id,
                            root_id=plan.root_id,
                            allocation_usd=plan.root_allowance_usd,
                            spent_usd=prior_spend,
                        )
                    )
                else:
                    if (root.owner_id, root.project_id, root.plan_id) != (
                        plan.owner_id,
                        plan.project_id,
                        plan.plan_id,
                    ):
                        raise Conflict(message="Plan identity cannot change")
                    old = await db.get(PlanRow, (root.session_id, root.current_revision))
                    assert old is not None
                    if (
                        plan.revision == root.current_revision
                        and plan.approval_hash() == old.plan_hash
                    ):
                        return
                    if (
                        root.status not in {"awaiting_approval", "queued"}
                        or plan.revision != root.current_revision + 1
                    ):
                        raise Conflict(message="Plan revision is stale or execution has started")
                    account = await db.get(Account, root.session_id)
                    assert account is not None
                    if (
                        root.admitted_revision is not None
                        or account.generation > 0
                        or account.reserved_usd
                        or account.worker_id is not None
                        or await db.scalar(
                            select(Admission.session_id)
                            .where(Admission.root_id == root.session_id)
                            .limit(1)
                        )
                    ):
                        raise Conflict(message="An admitted batch cannot be revised")
                    if account.spent_usd > plan.root_allowance_usd:
                        raise Conflict(
                            message="Revised root allowance is below already recorded spend"
                        )
                    await self._live(db, root, plan, await _now(db))
                    old.status = "superseded"
                    root.current_revision = plan.revision
                    root.status = "awaiting_approval"
                    root.updated_at = await _now(db)
                    account.allocation_usd = plan.root_allowance_usd
                db.add(
                    PlanRow(
                        root_id=plan.root_id,
                        revision=plan.revision,
                        plan_hash=plan.approval_hash(),
                        snapshot=plan.model_dump(mode="json"),
                        status="proposed",
                    )
                )
                await db.flush()
                await _audit(
                    db, root, "plan_saved", revision=plan.revision, child_count=len(plan.children)
                )
        except IntegrityError:
            raise Conflict(message="Plan conflicts with an existing root or admission") from None

    async def approve(
        self, root_id: UUID, *, actor_id: UUID, revision: int, plan_hash: str
    ) -> ApprovalBinding:
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, root_id)
            if actor_id != root.owner_id:
                raise Forbidden(message="Only the owner may approve this plan")
            if revision != plan.revision or plan_hash != plan.approval_hash():
                raise Conflict(message="Approval refers to a stale plan")
            await self._live(db, root, plan, now)
            stored = await db.get(PlanRow, (root_id, revision))
            assert stored is not None
            if stored.status == "approved" and root.status in _ACTIVE:
                assert stored.approval is not None
                binding = ApprovalBinding.model_validate_json(json.dumps(stored.approval))
                binding.require_matches(plan, now=now)
                return binding
            if root.status != "awaiting_approval" or stored.status != "proposed":
                raise Conflict(message="Plan cannot be approved in its current state")
            binding = ApprovalBinding(
                plan_id=plan.plan_id,
                root_id=root_id,
                project_id=plan.project_id,
                revision=revision,
                plan_hash=plan_hash,
                approving_user_id=actor_id,
                approved_at=now,
                policy_version=plan.policy_version,
                root_skill_digest=plan.root.skill.digest,
            )
            stored.approval = binding.model_dump(mode="json")
            stored.status = "approved"
            root.status = "queued"
            root.updated_at = now
            await _audit(db, root, "approved", revision=revision)
            return binding

    async def reject(self, root_id: UUID, *, actor_id: UUID, revision: int) -> None:
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, root_id)
            if actor_id != root.owner_id:
                raise Forbidden(message="Only the owner may reject this plan")
            if revision != plan.revision:
                raise Conflict(message="Rejection refers to a stale plan")
            if root.status == "rejected":
                return
            if root.status != "awaiting_approval":
                raise Conflict(message="Only an awaiting plan can be rejected")
            stored = await db.get(PlanRow, (root_id, revision))
            assert stored is not None
            stored.status = root.status = "rejected"
            root.updated_at = now
            await _audit(db, root, "rejected", revision=revision)

    async def _account(self, db: AsyncSession, root_id: UUID, session_id: UUID) -> Account:
        account = await db.scalar(
            select(Account)
            .where(Account.session_id == session_id, Account.root_id == root_id)
            .with_for_update()
        )
        if account is None:
            raise Conflict(message="Run has no admitted budget allocation")
        return account

    def _fence(self, account: Account, claim: WorkerClaim, now: datetime) -> None:
        if (
            account.worker_id != claim.worker_id
            or account.generation != claim.generation
            or account.lease_until is None
            or account.lease_until <= now
        ):
            raise Conflict(message="Worker claim is stale or expired")

    async def claim(
        self, root_id: UUID, session_id: UUID, *, worker_id: UUID, seconds: int
    ) -> WorkerClaim:
        if type(seconds) is not int or not 1 <= seconds <= 900:
            raise ValidationError(message="Worker lease must be between 1 and 900 seconds")
        uncertain = False
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, root_id, session_id)
            now = await _now(db)
            if (
                account.worker_id is not None
                and account.lease_until is not None
                and account.lease_until > now
            ):
                raise Conflict(message="Run already has an active worker")
            pending = await db.scalar(
                select(Effect)
                .where(
                    Effect.session_id == session_id, Effect.status.in_(["admitted", "uncertain"])
                )
                .with_for_update()
            )
            if pending is not None:
                pending.status = "uncertain"
                root.status, root.stop_reason = "uncertain", "unresolved_effect"
                account.generation += 1
                account.worker_id = account.lease_until = account.attempt_deadline = None
                await _audit(
                    db,
                    root,
                    "effect_uncertain",
                    session_id=str(session_id),
                    generation=account.generation,
                )
                uncertain = True
            else:
                now = await _now(db)
                if now >= plan.deadline:
                    raise Conflict(message="Plan expired while claiming worker ownership")
                account.generation += 1
                account.worker_id = worker_id
                account.attempt_deadline = min(
                    plan.deadline, now + timedelta(seconds=plan.attempt_timeout_seconds)
                )
                account.lease_until = min(
                    account.attempt_deadline, now + timedelta(seconds=seconds)
                )
                root.status = "running"
                await _audit(
                    db, root, "claimed", session_id=str(session_id), generation=account.generation
                )
            root.updated_at = now
            claim = WorkerClaim(root_id, session_id, worker_id, account.generation)
        if uncertain:
            raise Conflict(
                message="An unresolved effect requires reconciliation before further work"
            )
        return claim

    async def renew_claim(self, claim: WorkerClaim, *, seconds: int) -> datetime:
        """Extend live ownership within its fixed attempt and approved deadline.

        Recheck execution authority even for a no-op renewal. An admitted call
        may remain in flight; renewal changes neither its receipt/reservation nor
        any provider timeout already computed by the adapter. Heartbeats do not
        count as phase progress, change lifecycle or create a new generation.
        """
        if type(seconds) is not int or not 1 <= seconds <= 900:
            raise ValidationError(message="Worker lease must be between 1 and 900 seconds")
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            now = await _now(db)
            self._fence(account, claim, now)
            assert account.attempt_deadline is not None and account.lease_until is not None
            if now >= min(account.attempt_deadline, plan.deadline):
                raise Conflict(message="Worker attempt or plan has expired")
            until = min(account.attempt_deadline, plan.deadline, now + timedelta(seconds=seconds))
            # A delayed shorter heartbeat must not shorten already granted time.
            if until > account.lease_until:
                account.lease_until = until
                await _audit(
                    db,
                    root,
                    "claim_renewed",
                    session_id=str(claim.session_id),
                    generation=claim.generation,
                )
            return account.lease_until

    async def release_claim(self, claim: WorkerClaim) -> None:
        """Relinquish current ownership after the caller has stopped its graph.

        This only narrows authority, so cleanup remains possible after policy
        revocation, opt-out or halt. It does not admit work, change lifecycle
        status, release uncertain reservations or fence framework checkpoints.
        """
        async with self.sessions.begin() as db:
            initial = await db.get(Root, claim.root_id)
            if initial is None:
                raise NotFound(message="Orchestration root not found")
            await db.execute(
                select(User.id).where(User.id == initial.owner_id).with_for_update(read=True)
            )
            await db.execute(
                select(Project.id)
                .where(Project.id == initial.project_id)
                .with_for_update(read=True)
            )
            root = (
                await db.execute(
                    select(Root)
                    .where(Root.session_id == claim.root_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            pending = await db.scalar(
                select(Effect)
                .where(
                    Effect.session_id == claim.session_id,
                    Effect.status.in_(["admitted", "uncertain"]),
                )
                .with_for_update()
            )
            if pending is not None or account.reserved_usd != 0:
                raise Conflict(message="Outstanding effect prevents worker release")
            now = await _now(db)
            self._fence(account, claim, now)
            account.generation += 1
            account.worker_id = account.lease_until = account.attempt_deadline = None
            root.updated_at = now
            await _audit(
                db,
                root,
                "claim_released",
                session_id=str(claim.session_id),
                generation=account.generation,
            )

    async def execution_view(self, claim: WorkerClaim) -> ExecutionView:
        """Resolve immutable worker input, releasing all control locks on return.

        This read is not effect admission. Admission rechecks policy and fencing
        after request preparation, at the guard's R4 boundary.
        """
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            now = await _now(db)
            self._fence(account, claim, now)
            scope = (
                plan.root
                if claim.session_id == claim.root_id
                else next(
                    (c.execution for c in plan.children if c.dispatch_id == claim.session_id), None
                )
            )
            if scope is None or account.lease_until is None:
                raise Forbidden(message="Worker is outside the approved tree")
            return ExecutionView(plan, scope, (account.lease_until - now).total_seconds())

    async def mark_effect_uncertain(self, claim: WorkerClaim, *, effect_key: str) -> bool:
        """Conservatively abandon one admitted effect after rollback/cancellation.

        Reachable after halt, deadline or revocation. Never overwrites a completed
        receipt or another generation. Uncertainty retains the reservation and
        fences this worker; no retry authority is created.
        """
        async with self.sessions.begin() as db:
            initial = await db.get(Root, claim.root_id)
            if initial is None:
                return False
            await db.execute(
                select(User.id).where(User.id == initial.owner_id).with_for_update(read=True)
            )
            await db.execute(
                select(Project.id)
                .where(Project.id == initial.project_id)
                .with_for_update(read=True)
            )
            root = (
                await db.execute(
                    select(Root)
                    .where(Root.session_id == claim.root_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
            account = await self._account(db, claim.root_id, claim.session_id)
            effect = await db.get(Effect, (claim.session_id, effect_key))
            if (
                account.generation != claim.generation
                or account.worker_id != claim.worker_id
                or effect is None
                or effect.generation != claim.generation
                or effect.status != "admitted"
            ):
                return False
            effect.status = "uncertain"
            account.generation += 1
            account.worker_id = account.lease_until = account.attempt_deadline = None
            root.status, root.updated_at = "uncertain", await _now(db)
            root.stop_reason = root.stop_reason or "unresolved_effect"
            await _audit(
                db,
                root,
                "effect_uncertain",
                session_id=str(claim.session_id),
                generation=account.generation,
            )
            return True

    async def admit_children(self, claim: WorkerClaim) -> tuple[UUID, ...]:
        if claim.session_id != claim.root_id:
            raise Conflict(message="Only the root worker can admit children")
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            existing = list(
                (
                    await db.scalars(
                        select(Admission)
                        .where(
                            Admission.root_id == claim.root_id, Admission.revision == plan.revision
                        )
                        .order_by(Admission.child_order)
                    )
                ).all()
            )
            if root.admitted_revision is not None or existing:
                if root.admitted_revision != plan.revision or tuple(
                    a.dispatch_id for a in existing
                ) != tuple(c.dispatch_id for c in plan.children):
                    raise Conflict(
                        message="Existing child admissions do not match the approved batch"
                    )
                return tuple(a.session_id for a in existing)
            for order, child in enumerate(plan.children, 1):
                db.add(
                    AutonomousSession(
                        id=child.dispatch_id,
                        user_id=root.owner_id,
                        project_id=root.project_id,
                        trigger_kind="manual",
                        parent_session_id=claim.root_id,
                        root_session_id=claim.root_id,
                        delegation_depth=1,
                        child_order=order,
                        max_cost_usd=child.budget_usd,
                        params={"orchestration_profile": "research"},
                    )
                )
            await db.flush()
            for order, child in enumerate(plan.children, 1):
                db.add(
                    Admission(
                        session_id=child.dispatch_id,
                        root_id=claim.root_id,
                        revision=plan.revision,
                        dispatch_id=child.dispatch_id,
                        child_order=order,
                    )
                )
                db.add(
                    Account(
                        session_id=child.dispatch_id,
                        root_id=claim.root_id,
                        allocation_usd=child.budget_usd,
                    )
                )
            root.admitted_revision = plan.revision
            root.status, root.updated_at = "waiting_children", now
            await _audit(
                db,
                root,
                "children_admitted",
                revision=plan.revision,
                child_count=len(plan.children),
            )
            return tuple(child.dispatch_id for child in plan.children)

    async def halt(self, root_id: UUID, *, actor_id: UUID) -> None:
        # Halt deliberately remains reachable after opt-out/project archival or
        # policy revocation: it only narrows authority. Take the same lock order.
        async with self.sessions.begin() as db:
            initial = await db.get(Root, root_id)
            if initial is None or initial.owner_id != actor_id:
                raise NotFound(message="Orchestration root not found")
            await db.execute(select(User.id).where(User.id == actor_id).with_for_update(read=True))
            await db.execute(
                select(Project.id)
                .where(Project.id == initial.project_id)
                .with_for_update(read=True)
            )
            root = (
                await db.execute(
                    select(Root)
                    .where(Root.session_id == root_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
            if root.status in {"halted", "completed", "failed", "rejected", "expired"}:
                return
            if root.status != "uncertain":
                root.status = "halted"
            root.stop_reason, root.updated_at = "owner_halt", await _now(db)
            await _audit(db, root, "halted")

    async def expire_root(self, root_id: UUID) -> bool:
        """Recover a due root; return whether it newly became cleanly expired.

        Unresolved effects/reservations retain uncertainty, including unowned
        accounts. Other clean terminal outcomes are preserved. This is a private
        watchdog seam; it neither schedules work nor changes legacy session state.
        """
        async with self.sessions.begin() as db:
            initial = await db.get(Root, root_id)
            if initial is None:
                raise NotFound(message="Orchestration root not found")
            await db.execute(
                select(User.id).where(User.id == initial.owner_id).with_for_update(read=True)
            )
            await db.execute(
                select(Project.id)
                .where(Project.id == initial.project_id)
                .with_for_update(read=True)
            )
            root = (
                await db.execute(
                    select(Root)
                    .where(Root.session_id == root_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
            plan = await self._stored_plan(db, root)
            if await _now(db) < plan.deadline:
                return False
            previous_state = (root.status, root.stop_reason)
            await self._recover_accounts(db, root, effects_only=False)
            # Unowned unresolved accounts must also prevent a clean expiration.
            pending = await db.scalar(
                select(Effect.session_id)
                .join(Account, Account.session_id == Effect.session_id)
                .where(Account.root_id == root_id, Effect.status.in_(["admitted", "uncertain"]))
                .limit(1)
            )
            reserved = await db.scalar(
                select(Account.session_id)
                .where(Account.root_id == root_id, Account.reserved_usd != 0)
                .limit(1)
            )
            if pending is not None or reserved is not None:
                root.status = "uncertain"
                root.stop_reason = root.stop_reason or (
                    "unresolved_effect" if pending is not None else "unresolved_reservation"
                )
            if root.status == "uncertain":
                if previous_state != (root.status, root.stop_reason):
                    root.updated_at = await _now(db)
                    await _audit(db, root, "deadline_uncertain", revision=plan.revision)
                return False
            if root.status not in _ACTIVE | {"awaiting_approval"}:
                return False
            root.status = "expired"
            root.stop_reason = root.stop_reason or "root_deadline"
            root.updated_at = await _now(db)
            await _audit(db, root, "root_expired", revision=plan.revision)
            return True

    async def recover_expired_effects(self, root_id: UUID) -> int:
        """Fence expired owners with admitted effects; retain the legacy count."""
        return await self._recover_expired(root_id, effects_only=True)

    async def recover_expired_claims(self, root_id: UUID) -> int:
        """Drain expired ownership even after halt, deadline or revocation.

        Return the number of claims fenced. Completed receipts and accounting
        survive cleanup. Pending effects or orphaned reservations make the root
        uncertain; clean accounts preserve lifecycle and progress. This does not
        authorize a retry or fence arbitrary framework checkpoint writes.
        """
        return await self._recover_expired(root_id, effects_only=False)

    async def _recover_expired(self, root_id: UUID, *, effects_only: bool) -> int:
        async with self.sessions.begin() as db:
            initial = await db.get(Root, root_id)
            if initial is None:
                raise NotFound(message="Orchestration root not found")
            await db.execute(
                select(User.id).where(User.id == initial.owner_id).with_for_update(read=True)
            )
            await db.execute(
                select(Project.id)
                .where(Project.id == initial.project_id)
                .with_for_update(read=True)
            )
            root = (
                await db.execute(
                    select(Root)
                    .where(Root.session_id == root_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
            return await self._recover_accounts(db, root, effects_only=effects_only)

    async def _recover_accounts(self, db: AsyncSession, root: Root, *, effects_only: bool) -> int:
        root_id = root.session_id
        now = await _now(db)
        accounts = (
            await db.scalars(
                select(Account)
                .where(
                    Account.root_id == root_id,
                    Account.worker_id.is_not(None),
                    Account.lease_until <= now,
                )
                .order_by(Account.session_id)
                .with_for_update()
            )
        ).all()
        count = 0
        for account in accounts:
            pending = await db.scalar(
                select(Effect)
                .where(
                    Effect.session_id == account.session_id,
                    Effect.status.in_(["admitted", "uncertain"]),
                )
                .with_for_update()
            )
            if effects_only and (pending is None or pending.status != "admitted"):
                continue
            was_admitted = pending is not None and pending.status == "admitted"
            if pending is not None:
                pending.status = "uncertain"
            account.generation += 1
            account.worker_id = account.lease_until = account.attempt_deadline = None
            if pending is not None or account.reserved_usd != 0:
                root.status, root.updated_at = "uncertain", await _now(db)
                root.stop_reason = root.stop_reason or (
                    "unresolved_effect" if pending is not None else "unresolved_reservation"
                )
            if was_admitted:
                await _audit(
                    db,
                    root,
                    "effect_uncertain",
                    session_id=str(account.session_id),
                    generation=account.generation,
                )
            if not effects_only:
                await _audit(
                    db,
                    root,
                    "claim_expired",
                    session_id=str(account.session_id),
                    generation=account.generation,
                )
            count += 1
        return count

    async def begin_effect(
        self,
        claim: WorkerClaim,
        *,
        effect_key: str,
        request_hash: str,
        reservation_usd: Decimal,
        phase: Phase,
        intent: ToolIntent,
    ) -> EffectReceipt:
        reservation = _money(reservation_usd)
        if (
            re.fullmatch(r"[a-z][a-z0-9_.:-]{0,127}", effect_key) is None
            or re.fullmatch(r"[0-9a-f]{64}", request_hash) is None
        ):
            raise ValidationError(message="Effect identity is invalid")
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            existing = await db.get(Effect, (claim.session_id, effect_key))
            if existing is not None:
                if (existing.request_hash, existing.phase, existing.intent) != (
                    request_hash,
                    phase.value,
                    intent.value,
                ):
                    raise Conflict(message="Effect identity was reused with different input")
                if existing.status == "admitted":
                    raise Conflict(message="Effect is already in flight")
                return _receipt(existing)
            scope = (
                plan.root
                if claim.session_id == claim.root_id
                else next(
                    (c.execution for c in plan.children if c.dispatch_id == claim.session_id), None
                )
            )
            session = await db.get(AutonomousSession, claim.session_id)
            if (
                scope is None
                or session is None
                or session.halt_state != "running"
                or session.status != "running"
                or session.current_phase != phase.value
                or intent not in scope.grants.for_phase(phase)
            ):
                raise Forbidden(message="Effect is outside the current run's phase or grants")
            if await db.scalar(
                select(Effect.effect_key)
                .where(
                    Effect.session_id == claim.session_id,
                    Effect.status.in_(["admitted", "uncertain"]),
                )
                .limit(1)
            ):
                raise Conflict(message="Run already has an outstanding effect")
            if account.spent_usd + account.reserved_usd + reservation > account.allocation_usd:
                raise Conflict(message="Effect exceeds the run's allocated budget")
            account.reserved_usd += reservation
            effect = Effect(
                session_id=claim.session_id,
                effect_key=effect_key,
                request_hash=request_hash,
                phase=phase.value,
                intent=intent.value,
                generation=claim.generation,
                status="admitted",
                reserved_usd=reservation,
            )
            db.add(effect)
            await db.flush()
            await _audit(
                db,
                root,
                "effect_admitted",
                session_id=str(claim.session_id),
                generation=claim.generation,
                intent=intent.value,
                reserved_usd=str(reservation),
            )
            return _receipt(effect)

    async def complete_effect(
        self, claim: WorkerClaim, *, effect_key: str, charged_usd: Decimal, result: dict[str, Any]
    ) -> EffectReceipt:
        async with self.sessions.begin() as db:
            return await self._settle_effect(
                db, claim, effect_key=effect_key, charged_usd=charged_usd, result=result
            )

    async def _settle_effect(
        self,
        db: AsyncSession,
        claim: WorkerClaim,
        *,
        effect_key: str,
        charged_usd: Decimal,
        result: dict[str, Any],
    ) -> EffectReceipt:
        """Join the guarded outcome transaction; caller commits or rolls back all.

        Internal adapter seam. Must run after provider I/O and before the guard
        flushes session cost/outcome. No new execution is authorized here.
        """
        charge = _money(charged_usd)
        try:
            if not isinstance(result, dict):
                raise ValueError("result must be an object")
            content = json.dumps(result, allow_nan=False)
            if len(content.encode("utf-8")) > 131_072:
                raise ValueError("oversized result")
        except (ValueError, TypeError):
            raise ValidationError(message="Effect result must be bounded JSON") from None
        # Completion may record one admitted call after halt/revocation.
        # It does not resolve policy or authorize another external action.
        root = await db.get(Root, claim.root_id)
        if root is None:
            raise NotFound(message="Orchestration root not found")
        await db.execute(select(User.id).where(User.id == root.owner_id).with_for_update(read=True))
        await db.execute(
            select(Project.id).where(Project.id == root.project_id).with_for_update(read=True)
        )
        root = (
            await db.execute(
                select(Root)
                .where(Root.session_id == claim.root_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        account = await self._account(db, claim.root_id, claim.session_id)
        self._fence(account, claim, await _now(db))
        effect = await db.get(Effect, (claim.session_id, effect_key))
        if effect is None or effect.generation != claim.generation:
            raise Conflict(message="Effect is not owned by this worker generation")
        if effect.status == "completed":
            if effect.charged_usd != charge or effect.result != result:
                raise Conflict(message="Completed effect cannot be rewritten")
            return _receipt(effect)
        if effect.status != "admitted":
            raise Conflict(message="Uncertain effect requires reconciliation")
        account.reserved_usd -= effect.reserved_usd
        account.spent_usd += charge
        effect.status, effect.charged_usd = "completed", charge
        effect.result, effect.completed_at = json.loads(content), await _now(db)
        if account.spent_usd + account.reserved_usd > account.allocation_usd:
            root.status, root.stop_reason = "halted", "observed_budget_overrun"
        root.updated_at = effect.completed_at
        await _audit(
            db,
            root,
            "effect_completed",
            session_id=str(claim.session_id),
            generation=claim.generation,
            charged_usd=str(charge),
        )
        return _receipt(effect)
