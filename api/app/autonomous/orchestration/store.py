"""Short, application-owned governance transactions for ADR 0035.

No provider calls, queue writes or LangGraph types belong here. Public methods
commit before returning. A required current-policy checker must validate pinned
skills, selected resources and current operator grants with database/local policy
reads only. No permissive production checker or dispatch endpoint is supplied.

Lock order: owner -> project -> chat -> root -> account -> effect -> message.
A run outside any matter has no project; its lock on the project row selects
nothing, and the order is otherwise the same (ADR 0038 D1).
The owner/project share locks also serialize revocation with admission. Every
worker operation locks the root; root halt and effect admission therefore have
one ordering. The chat is locked only at intake, before its run's root exists,
and the bound message only at delivery, after everything else (ADR 0038 D1).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from pydantic import TypeAdapter, ValidationError as SchemaError
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import audit_action
from app.autonomous.audit import recorded_privilege, run_privilege
from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import (
    ApprovalBinding,
    ExecutionScope,
    Money,
    PreparedPlan,
)
from app.autonomous.orchestration.outcomes import (
    CollectedTopic,
    DemonstrationResult,
    DirectAnswer,
    TopicOutcome,
    direct_answer,
    topic_coverage,
)
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.profiles import require_profile
from app.autonomous.orchestration.reading import MatterTerms, borrowed_terms, selection_terms
from app.errors import Conflict, Forbidden, NotFound, ValidationError
from app.models.autonomous import AutonomousSession
from app.models.chat import Chat, Message
from app.models.file import File
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationAdmission as Admission,
    OrchestrationEffect as Effect,
    OrchestrationPlan as PlanRow,
    OrchestrationRoot as Root,
)
from app.models.project import Project, ProjectFile
from app.models.user import MUTATING_ROLES, User
from app.models.work_product import WorkProductAttribution
from app.schemas.autonomous import Phase
from app.schemas.chats import derive_chat_title
from app.skills.capabilities import MAX_FILE_BYTES, ReferenceRead

log = logging.getLogger(__name__)

_ACTIVE = frozenset({"queued", "running", "waiting_children"})
_TERMINAL = frozenset({"halted", "completed", "failed", "rejected", "expired", "closed"})
_MONEY: TypeAdapter[Decimal] = TypeAdapter(Money)
_EVENTS = frozenset(
    {
        "plan_saved",
        "planning_started",
        "planning_failed",
        "synthesis_failed",
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
        "phase_changed",
        "topic_delivered",
        "root_delivered",
        "answered_directly",
        "tool_refused",
        "run_closed",
    }
)


class BudgetExhausted(Conflict):
    """An effect the run's allocation cannot fund. No call was admitted."""


class DeliveryHook(Protocol):
    async def __call__(
        self, db: AsyncSession, root: Root, plan: PreparedPlan | PlanningSnapshot, message: Message
    ) -> dict[str, Any]:
        """Local checks on a delivered answer, inside the delivery transaction.

        ``plan`` is the approved plan, or the intake when the orchestrator
        answered by itself and no plan exists. No remote I/O and no commit.
        Returns counts and labels for the audit row; never text. Raising rolls
        delivery back.
        """
        ...


class CurrentPolicyCheck(Protocol):
    async def __call__(self, db: AsyncSession, plan: PreparedPlan | PlanningSnapshot) -> None:
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
    plan: PreparedPlan | PlanningSnapshot
    scope: ExecutionScope
    lease_seconds: float
    planning: PlanningSnapshot | None = None


def _receipt(effect: Effect) -> EffectReceipt:
    return EffectReceipt(
        effect.session_id,
        effect.effect_key,
        effect.status,
        effect.reserved_usd,
        effect.charged_usd,
        effect.result,
    )


def _effect_result_json(result: dict[str, Any], intent: str) -> str:
    """Bound replay storage, including JSON expansion of one reference snapshot.

    The default remains 128 KiB. A successful installed-reference read has a
    strict path/text envelope and at most 64 KiB of UTF-8 before escaping.
    JSON needs up to six bytes per input byte (C0 escapes), plus bounded path
    and envelope overhead. Keep the original text for exact durable replay.
    """
    try:
        if not isinstance(result, dict):
            raise ValueError("result must be an object")
        limit = 131_072
        if intent == ToolIntent.skill_reference_read and result.get("outcome") == "success":
            data = result.get("data")
            if (
                set(result) != {"data", "outcome"}
                or not isinstance(data, dict)
                or set(data) != {"path", "content"}
                or not isinstance(data["content"], str)
            ):
                raise ValueError("invalid reference result")
            ReferenceRead.model_validate({"path": data["path"]})
            raw = data["content"].encode("utf-8")
            if len(raw) > MAX_FILE_BYTES or b"\x00" in raw:
                raise ValueError("reference outside bounded text profile")
            limit = 6 * MAX_FILE_BYTES + 1024
        content = json.dumps(result, allow_nan=False, ensure_ascii=False)
        if len(content.encode("utf-8")) > limit:
            raise ValueError("oversized result")
        return content
    except (ValueError, TypeError):
        raise ValidationError(message="Effect result must be bounded JSON") from None


def _money(value: Decimal) -> Decimal:
    try:
        return _MONEY.validate_python(value)
    except SchemaError:
        raise ValidationError(
            message="Amount must be finite, nonnegative and exact to four decimal places"
        ) from None


async def _now(db: AsyncSession) -> datetime:
    return (await db.execute(select(func.clock_timestamp()))).scalar_one()


def _project_scope(
    project: Project, plan: PreparedPlan | PlanningSnapshot, borrowed: MatterTerms
) -> None:
    """Hold a run in a matter to that matter's floor and privilege flag.

    And to ``borrowed``, the terms of the other matters it reads a
    knowledge-base file of: the stricter of the two applies.
    """
    # Gateway tier semantics: lower numbers provide stronger protection.
    # An unset project floor adds no restriction beyond the explicit plan.
    floor = min(project.minimum_inference_tier or 5, borrowed.minimum_inference_tier)
    if plan.root.minimum_inference_tier > floor or (
        (project.privileged or borrowed.privileged) and not plan.root.privileged
    ):
        raise Forbidden(message="Project data policy has changed")


async def _data_terms(
    db: AsyncSession, project: Project | None, plan: PreparedPlan | PlanningSnapshot
) -> None:
    """Hold a run to the data terms it runs under, as they are now.

    In a matter those are the matter's, and those of every other matter that
    holds one of the run's selected documents through a knowledge base (ruled
    2026-10-13): the run's floor may not be weaker than any of theirs, and it
    is privileged when any of them is. Outside any matter they are the
    strictest of the matters that hold the run's selected documents (ADR
    0038, ruling 4): the run's floor may not be weaker than theirs, and it is
    privileged exactly when one of them is. The privilege flag turns
    pseudonymization off at the gateway, so a run outside any matter must not
    carry it with no privileged matter behind it, and must carry it when there
    is one. A run in a matter is held only the second way, as it was before
    this rule: it must be privileged when its matter or a lending matter is,
    and it is not stopped when the matter that made it privileged stops being
    so. That it then keeps pseudonymization off is an open point (ADR 0038 D5).

    Called at every admission. A matter whose terms tighten, or a selected
    file that is filed in a stricter matter, stops the run before its next
    call.
    """
    if project is not None:
        borrowed = await borrowed_terms(db, project.id, plan.root.resources.document_ids, lock=True)
        _project_scope(project, plan, borrowed)
        return
    terms = await selection_terms(db, plan.root.resources.document_ids, lock=True)
    if (
        plan.root.minimum_inference_tier > terms.minimum_inference_tier
        or plan.root.privileged is not terms.privileged
    ):
        raise Forbidden(message="Project data policy has changed")


async def _audit(db: AsyncSession, root: Root, event: str, **details: Any) -> None:
    assert event in _EVENTS
    # A run in a privileged matter is marked from the matter. Any other is
    # marked from the terms it took on when it was accepted (``run_privilege``),
    # so the privileged-activity query finds a run that read a privileged
    # matter's file, from outside any matter or from another matter.
    await audit_action(
        db,
        user_id=root.owner_id,
        **await run_privilege(db, root.project_id, recorded_privilege(root.planning_snapshot)),
        action=f"orchestration.{event}",
        resource_type="autonomous_session",
        resource_id=str(root.session_id),
        details=details,
        # Multiple phase/effect events may commit together. Timestamp their
        # writes individually without changing ordinary audit semantics.
        timestamp=func.clock_timestamp(),
    )


class OrchestrationStore:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        check_policy: CurrentPolicyCheck,
        deployment_children: int | None = None,
        on_delivered: DeliveryHook | None = None,
    ) -> None:
        if deployment_children is not None and (
            type(deployment_children) is not int or not 1 <= deployment_children <= 32
        ):
            raise ValidationError(message="Deployment child capacity must be 1-32")
        self.sessions = sessions
        self.check_policy = check_policy
        self.deployment_children = deployment_children
        self.on_delivered = on_delivered

    async def _owner_project(
        self, db: AsyncSession, owner_id: UUID, project_id: UUID | None, *, creating: bool = False
    ) -> Project | None:
        owner = await db.scalar(
            select(User).where(User.id == owner_id).with_for_update(read=not creating)
        )
        if owner is None or not owner.autonomous_enabled:
            raise Forbidden(message="Autonomous execution is not enabled for this owner")
        if creating and owner.role not in MUTATING_ROLES:
            # Held here as well as at the route: starting a run is an act, and
            # a read-only role may not (ADR 0038, ruling 10).
            raise Forbidden(message="A read-only role cannot start a run")
        if project_id is None:
            return None
        project = await db.scalar(
            select(Project).where(Project.id == project_id).with_for_update(read=True)
        )
        if project is None or project.owner_id != owner_id or project.archived_at is not None:
            raise Forbidden(message="Orchestration requires an owned active project")
        from app.authz.matters import require_matter

        await require_matter(db, project_id, owner, need="write")
        return project

    async def _may_act(self, db: AsyncSession, actor_id: UUID) -> None:
        """Approving and rejecting change what runs; a read-only role may not.

        The route refuses first. This is the same rule where no route can
        skip it (ADR 0038, ruling 10). Halting and closing are not acts in
        this sense: they only narrow authority.
        """
        role = await db.scalar(select(User.role).where(User.id == actor_id))
        if role not in MUTATING_ROLES:
            raise Forbidden(message="A read-only role cannot approve or reject a plan")

    async def _root(
        self, db: AsyncSession, root_id: UUID
    ) -> tuple[Root, PreparedPlan | PlanningSnapshot, datetime]:
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
        await _data_terms(db, project, plan)
        return root, plan, await _now(db)

    async def _stored_plan(self, db: AsyncSession, root: Root) -> PreparedPlan | PlanningSnapshot:
        if root.current_revision is None:
            try:
                snapshot = PlanningSnapshot.model_validate_json(json.dumps(root.planning_snapshot))
            except SchemaError:
                raise Conflict(message="Stored planning scope is invalid") from None
            if (snapshot.root_id, snapshot.owner_id, snapshot.project_id, snapshot.plan_id) != (
                root.session_id,
                root.owner_id,
                root.project_id,
                root.plan_id,
            ):
                raise Conflict(message="Planning identity differs from root")
            return snapshot
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

    async def _live(
        self, db: AsyncSession, root: Root, plan: PreparedPlan | PlanningSnapshot, now: datetime
    ) -> None:
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
        self, db: AsyncSession, root: Root, plan: PreparedPlan | PlanningSnapshot, now: datetime
    ) -> None:
        if not isinstance(plan, PreparedPlan) or root.status not in _ACTIVE:
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

    async def save_plan(
        self, plan: PreparedPlan, *, actor_id: UUID, create_session: bool = False
    ) -> None:
        plan = PreparedPlan.model_validate(plan)
        if actor_id != plan.owner_id:
            raise Forbidden(message="Only the owner may prepare this plan")
        try:
            async with self.sessions.begin() as db:
                project = await self._owner_project(
                    db, plan.owner_id, plan.project_id, creating=True
                )
                await _data_terms(db, project, plan)
                root = await db.scalar(
                    select(Root).where(Root.session_id == plan.root_id).with_for_update()
                )
                if root is None:
                    if plan.revision != 1:
                        raise Conflict(message="A new plan starts at revision one")
                    if create_session:
                        db.add(
                            AutonomousSession(
                                id=plan.root_id,
                                user_id=plan.owner_id,
                                project_id=plan.project_id,
                                trigger_kind="manual",
                                max_cost_usd=plan.root_allowance_usd,
                                params={
                                    "orchestration_profile": "demonstration",
                                    "query": plan.goal,
                                    "skill_ref": plan.root.skill.name,
                                },
                            )
                        )
                        await db.flush()
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
                    if root.current_revision is None:
                        raise Conflict(message="Planning must finish before revising a plan")
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
                    db,
                    root,
                    "plan_saved",
                    revision=plan.revision,
                    child_count=len(plan.children),
                )
        except IntegrityError:
            raise Conflict(message="Plan conflicts with an existing root or admission") from None

    async def _execution_authority(
        self,
        db: AsyncSession,
        root: Root,
        plan: PreparedPlan | PlanningSnapshot,
        now: datetime,
        session_id: UUID,
    ) -> None:
        """Planning authorizes only the root; all subsequent work needs approval."""
        if isinstance(plan, PlanningSnapshot):
            if root.status != "planning" or session_id != root.session_id:
                raise Forbidden(message="Planning authority is unavailable")
            await self._live(db, root, plan, now)
        else:
            await self._approved(db, root, plan, now)

    async def start_planning(
        self,
        snapshot: PlanningSnapshot,
        *,
        actor_id: UUID,
        profile: str = "model_demo_v1",
        chat_id: UUID | None = None,
        attach_file_ids: tuple[UUID, ...] = (),
    ) -> UUID:
        """Persist a bounded root before queue dispatch; request UUID is idempotent.

        With ``chat_id`` the run is hosted in that chat (ADR 0038 D1): the
        request becomes an ordinary user message and the reply is one assistant
        message of kind ``run`` linked to the new root session. Both are written
        in this transaction, so a run never exists without its turn or a turn
        without its run. ``attach_file_ids`` are the owner's own files selected
        for the run that were not yet attached to the project (D5); they are
        attached here, each with an audit row, before policy checks the selection.
        """
        snapshot = PlanningSnapshot.model_validate(snapshot)
        if actor_id != snapshot.owner_id:
            raise Forbidden(message="Only the owner may request planning")
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", profile) is None or snapshot.profile not in (
            None,
            profile,
        ):
            raise ValidationError(message="Planning profile is invalid")
        # The database and the check above hold only a profile's shape (migration 0074);
        # the closed set is the registry's, so a well-formed name that nothing registered
        # never becomes a root, whoever the caller is.
        require_profile(profile)
        selected = {document.file_id for document in snapshot.documents}
        if not set(attach_file_ids) <= selected:
            raise ValidationError(message="Only selected documents can be attached for a run")
        try:
            async with self.sessions.begin() as db:
                project = await self._owner_project(
                    db, actor_id, snapshot.project_id, creating=True
                )
                await _data_terms(db, project, snapshot)
                chat: Chat | None = None
                if chat_id is not None:
                    chat = await db.scalar(select(Chat).where(Chat.id == chat_id).with_for_update())
                    if (
                        chat is None
                        or chat.owner_id != actor_id
                        or chat.archived_at is not None
                        or chat.autonomous_session_id is not None
                        or chat.project_id != snapshot.project_id
                    ):
                        raise Forbidden(
                            message="A run needs an active chat in the run's own matter"
                        )
                if attach_file_ids and project is None:
                    raise ValidationError(message="A run outside a matter attaches no files")
                existing = await db.get(Root, snapshot.root_id)
                if existing is not None:
                    if existing.owner_id != actor_id or existing.profile != profile:
                        raise Conflict(message="Request identity is unavailable")
                    old = PlanningSnapshot.model_validate_json(
                        json.dumps(existing.planning_snapshot)
                    )
                    bound = await db.scalar(
                        select(Message.chat_id).where(
                            Message.autonomous_session_id == existing.session_id
                        )
                    )
                    if (
                        (old.project_id, old.goal) != (snapshot.project_id, snapshot.goal)
                        or [d.file_id for d in old.documents]
                        != [d.file_id for d in snapshot.documents]
                        or bound != chat_id
                    ):
                        raise Conflict(message="Request identity was reused with different input")
                    return existing.session_id
                for file_id in attach_file_ids:
                    # Attaching to the project keeps one rule at the read
                    # boundary. Ownership is rechecked here under the owner lock.
                    owned = await db.scalar(
                        select(File.id).where(
                            File.id == file_id,
                            File.owner_id == actor_id,
                            File.deleted_at.is_(None),
                        )
                    )
                    if owned is None:
                        raise Forbidden(message="Selected file is unavailable")
                    if await db.get(ProjectFile, (snapshot.project_id, file_id)) is None:
                        db.add(ProjectFile(project_id=snapshot.project_id, file_id=file_id))
                        await db.flush()
                        await audit_action(
                            db,
                            user_id=actor_id,
                            # Marked as the run's own rows are: attaching a
                            # privileged matter's knowledge-base file to a
                            # matter that is not privileged is privileged
                            # activity too.
                            **await run_privilege(
                                db, snapshot.project_id, snapshot.root.privileged
                            ),
                            action="project.file_attached",
                            resource_type="project",
                            resource_id=str(snapshot.project_id),
                            details={
                                "file_id": str(file_id),
                                "source": "run_selection",
                                "root_id": str(snapshot.root_id),
                            },
                            timestamp=func.clock_timestamp(),
                        )
                db.add(
                    AutonomousSession(
                        id=snapshot.root_id,
                        user_id=actor_id,
                        project_id=snapshot.project_id,
                        trigger_kind="manual",
                        current_phase="analysis",
                        max_cost_usd=snapshot.root_allowance_usd,
                        params={
                            "orchestration_profile": profile,
                            "query": snapshot.goal,
                            # ``skill_ref`` names an installed skill and is read
                            # by the skill tools; a prompt file is not one.
                            (
                                "skill_ref" if snapshot.root.skill.kind == "skill" else "prompt_ref"
                            ): snapshot.root.skill.name,
                        },
                    )
                )
                await db.flush()
                root = Root(
                    session_id=snapshot.root_id,
                    owner_id=actor_id,
                    project_id=snapshot.project_id,
                    plan_id=snapshot.plan_id,
                    current_revision=None,
                    status="planning",
                    profile=profile,
                    planning_snapshot=snapshot.model_dump(mode="json"),
                )
                await self._live(db, root, snapshot, await _now(db))
                db.add(root)
                await db.flush()
                db.add(
                    Account(
                        session_id=root.session_id,
                        root_id=root.session_id,
                        allocation_usd=snapshot.root_allowance_usd,
                    )
                )
                details: dict[str, Any] = {}
                if chat is not None:
                    now = await _now(db)
                    request = Message(
                        chat_id=chat.id,
                        role="user",
                        kind="user",
                        content=snapshot.goal,
                        created_at=now,
                    )
                    reply = Message(
                        chat_id=chat.id,
                        role="assistant",
                        kind="run",
                        content="",
                        autonomous_session_id=root.session_id,
                        # Listed oldest first by time, then by a random id.
                        created_at=now + timedelta(microseconds=1),
                    )
                    db.add_all([request, reply])
                    if chat.title == "New chat":
                        chat.title = derive_chat_title(snapshot.goal)
                    chat.updated_at = now
                    await db.flush()
                    details = {"chat_id": str(chat.id), "message_id": str(reply.id)}
                await _audit(db, root, "planning_started", profile=profile, **details)
        except IntegrityError:
            raise Conflict(message="An active run or conflicting request already exists") from None
        return snapshot.root_id

    async def finish_planning(
        self,
        claim: WorkerClaim,
        plan: PreparedPlan | None,
        *,
        failure: str = "invalid_proposal",
        answer: str | None = None,
    ) -> None:
        """Promote a paid planning result atomically, without resetting its ledger.

        One of three things happens. A plan is stored for the owner to approve.
        The planning call failed, and the run ends. Or the orchestrator answered
        by itself (``answer``): that reply is delivered and the run ends
        completed, with no plan row, no children and no approval (ADR 0038 D1).
        """
        if plan is not None and answer is not None:
            raise ValidationError(message="A planning result is a plan or an answer, not both")
        async with self.sessions.begin() as db:
            root, snapshot, now = await self._root(db, claim.root_id)
            if not isinstance(snapshot, PlanningSnapshot):
                raise Conflict(message="Planning has already finished")
            await self._execution_authority(db, root, snapshot, now, claim.session_id)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            receipt = await db.get(Effect, (claim.session_id, "chat:plan:v1"))
            if account.reserved_usd or receipt is None or receipt.status != "completed":
                raise Conflict(message="Planning effect must be settled before promotion")
            if answer is not None:
                # Nothing further is funded from this run, so the rule below,
                # which keeps room for the tasks and the combining call, does
                # not apply. A charge past the root's whole allocation has
                # already halted the run when the call settled.
                await self._deliver_direct(db, root, snapshot, answer, now, receipt.result)
                root.updated_at = now
                return
            if account.spent_usd > snapshot.planning_allowance_usd:
                plan, failure = None, "unfunded_plan"
            if plan is None:
                if failure not in {
                    "invalid_proposal",
                    "unfunded_plan",
                    "plan_not_handed_over",
                    "plan_has_placeholders",
                }:
                    raise ValidationError(message="Invalid planning failure code")
                root.status, root.stop_reason = "failed", failure
                session = await db.get(AutonomousSession, root.session_id)
                assert session is not None
                session.status, session.completed_at = "failed", now
                await _audit(db, root, "planning_failed", reason=failure)
            else:
                plan = PreparedPlan.model_validate(plan)
                if plan.planning_digest != snapshot.approval_hash():
                    raise Forbidden(message="Plan must bind its original planning scope")
                for key in (
                    "root_id",
                    "plan_id",
                    "owner_id",
                    "project_id",
                    "goal",
                    "policy_version",
                    "budget_usd",
                    "root_allowance_usd",
                    "deadline",
                    "max_active_children",
                    "attempt_timeout_seconds",
                    "delegation_grants",
                    "profile",
                    "documents",
                    "knowledge_bases",
                ):
                    if getattr(plan, key) != getattr(snapshot, key):
                        raise Forbidden(message="Prepared plan differs from planning authority")
                if len(plan.children) > snapshot.max_children:
                    raise Forbidden(message="Prepared plan exceeds the funded task count")
                if (
                    plan.revision != 1
                    or plan.root.model_copy(update={"grants": snapshot.root.grants})
                    != snapshot.root
                ):
                    raise Forbidden(message="Prepared root exceeds planning scope")
                await self._live(db, root, plan, await _now(db))
                root.current_revision, root.status = 1, "awaiting_approval"
                db.add(
                    PlanRow(
                        root_id=root.session_id,
                        revision=1,
                        plan_hash=plan.approval_hash(),
                        snapshot=plan.model_dump(mode="json"),
                        status="proposed",
                    )
                )
                await _audit(db, root, "plan_saved", revision=1, child_count=len(plan.children))
            root.updated_at = now

    async def _deliver_direct(
        self,
        db: AsyncSession,
        root: Root,
        snapshot: PlanningSnapshot,
        answer: str,
        now: datetime,
        planned: dict[str, Any] | None,
    ) -> None:
        """Deliver the orchestrator's own answer: no plan, no tasks, no approval.

        Sending the request authorized the one planning call, and that call is
        all that ran. The answer is written into the bound chat message in this
        transaction, with its audit row, as a combined answer is. It is
        unverified. If the run has selected documents the quotation checks
        still run on it: the orchestrator read none of them, so a quotation it
        marks with a source is reported as it is found.
        """
        if snapshot.terms is None or snapshot.terms.planning != "tool":
            raise Forbidden(message="This run cannot answer without a plan")
        # The answer is the planning call's own stored reply and nothing else:
        # a caller cannot have another text delivered under this run.
        reply = (planned or {}).get("data")
        reply = reply if isinstance(reply, dict) else {}
        try:
            own = (
                None
                if reply.get("tool_calls")
                else direct_answer(
                    reply.get("content"),
                    reply.get("finish_reason"),
                    limit=snapshot.terms.answer_chars,
                )
            )
        except ValueError:
            own = None
        if own is None or own != answer:
            raise Conflict(message="Direct answer differs from the planning call's reply")
        try:
            result = DirectAnswer(summary=answer)
        except SchemaError:
            raise ValidationError(message="Direct answer is outside its bounds") from None
        session = await db.get(AutonomousSession, root.session_id)
        assert session is not None
        session.result = result.model_dump(mode="json")
        session.current_phase = Phase.delivery.value
        root.status = session.status = "completed"
        session.completed_at = session.last_activity_at = now
        details: dict[str, Any] = {"verification": "unverified"}
        message = await db.scalar(
            select(Message)
            .where(Message.autonomous_session_id == root.session_id)
            .with_for_update()
        )
        if message is not None:
            await self._write_answer(db, root, snapshot, message, result.summary)
            details.update(chat_id=str(message.chat_id), message_id=str(message.id))
            if self.on_delivered is not None and snapshot.documents:
                try:
                    async with db.begin_nested():
                        details.update(await self.on_delivered(db, root, snapshot, message))
                except Exception:
                    # No exception text: it can carry quoted document content.
                    log.warning("Run answer checks failed; delivered unverified")
                    details.update(verification="unverified", checks="failed")
        await _audit(db, root, "answered_directly", **details)

    async def approve(
        self, root_id: UUID, *, actor_id: UUID, revision: int, plan_hash: str
    ) -> ApprovalBinding:
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, root_id)
            if actor_id != root.owner_id:
                raise Forbidden(message="Only the owner may approve this plan")
            await self._may_act(db, actor_id)
            if not isinstance(plan, PreparedPlan):
                raise Conflict(message="Planning has not produced an approvable plan")
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
            await self._may_act(db, actor_id)
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
            session = await db.get(AutonomousSession, root_id)
            assert session is not None
            session.status, session.halt_state, session.completed_at = "halted", "halted", now
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
            await self._execution_authority(db, root, plan, now, session_id)
            if session_id != root_id:
                # Serialize capacity admissions across roots/processes. Count
                # expired ownership and uncertain calls until recovery proves
                # they can be released; a lost saver connection frees no budget
                # or execution authority in these durable records.
                await db.execute(select(func.pg_advisory_xact_lock(563, 1)))
                occupied = select(Account.session_id, Account.root_id).where(
                    Account.session_id != Account.root_id,
                    Account.session_id != session_id,
                    or_(
                        Account.worker_id.is_not(None),
                        select(Effect.session_id)
                        .where(
                            Effect.session_id == Account.session_id,
                            Effect.status.in_(["admitted", "uncertain"]),
                        )
                        .exists(),
                    ),
                )
                active = list(await db.execute(occupied))
                if sum(row.root_id == root_id for row in active) >= plan.max_active_children or (
                    self.deployment_children is not None and len(active) >= self.deployment_children
                ):
                    raise Conflict(message="Child execution capacity is occupied")
            account = await self._account(db, root_id, session_id)
            session = await db.get(AutonomousSession, session_id)
            if session is None or session.status != "running":
                raise Conflict(message="Run is already terminal")
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
                root.status = "planning" if isinstance(plan, PlanningSnapshot) else "running"
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
            await self._execution_authority(db, root, plan, now, claim.session_id)
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
            await self._execution_authority(db, root, plan, now, claim.session_id)
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
            return ExecutionView(
                plan,
                scope,
                (account.lease_until - now).total_seconds(),
                PlanningSnapshot.model_validate_json(json.dumps(root.planning_snapshot))
                if root.planning_snapshot
                else None,
            )

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

    async def phase(self, claim: WorkerClaim, phase: Phase) -> None:
        """Publish progress; LangGraph alone owns the continuation position."""
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            session = await db.get(AutonomousSession, claim.session_id)
            assert session is not None
            phases = list(Phase)
            # Replayed nodes must not move visible progress backwards.
            if phases.index(phase) <= phases.index(Phase(session.current_phase)):
                return
            if session.status != "running":
                raise Conflict(message="Terminal run cannot advance phase")
            session.current_phase = phase.value
            session.last_activity_at = root.updated_at = await _now(db)
            await _audit(db, root, "phase_changed", session_id=str(session.id), phase=phase.value)

    async def stage_topic(self, claim: WorkerClaim, outcome: TopicOutcome) -> None:
        """Store bounded internal content outside framework checkpoints/traces."""
        outcome = TopicOutcome.model_validate(outcome)
        if claim.session_id == claim.root_id:
            raise Conflict(message="Only a child may stage a topic outcome")
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            session = await db.get(AutonomousSession, claim.session_id)
            assert session is not None
            value = outcome.model_dump(mode="json")
            if session.result is not None and session.result != value:
                raise Conflict(message="An existing topic outcome cannot change")
            session.result = value

    async def deliver_topic(self, claim: WorkerClaim, *, failed: bool = False) -> None:
        if claim.session_id == claim.root_id:
            raise Conflict(message="Only a child may deliver a topic outcome")
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            if account.reserved_usd or await db.scalar(
                select(Effect.session_id)
                .where(
                    Effect.session_id == claim.session_id,
                    Effect.status.in_(["admitted", "uncertain"]),
                )
                .limit(1)
            ):
                raise Conflict(message="Unresolved work prevents topic delivery")
            session = await db.get(AutonomousSession, claim.session_id)
            assert session is not None
            outcome = TopicOutcome.model_validate_json(json.dumps(session.result))
            if failed != (outcome.status == "failed"):
                raise Conflict(message="Topic delivery status does not match its outcome")
            if session.status != "running":
                return
            if not failed and session.current_phase != Phase.delivery.value:
                raise Conflict(message="Topic must complete its phases before delivery")
            session.status = "failed" if failed else "completed"
            session.completed_at = session.last_activity_at = root.updated_at = await _now(db)
            await _audit(
                db, root, "topic_delivered", session_id=str(session.id), outcome=outcome.status
            )

    async def _topics(
        self, db: AsyncSession, plan: PreparedPlan | PlanningSnapshot
    ) -> tuple[CollectedTopic, ...]:
        topics = []
        for child in plan.children:
            session = await db.get(AutonomousSession, child.dispatch_id)
            if session is None or session.status not in {"completed", "failed"}:
                raise Conflict(message="Approved topics are still pending")
            try:
                outcome = TopicOutcome.model_validate_json(json.dumps(session.result))
            except SchemaError:
                raise Conflict(message="Stored topic outcome is invalid") from None
            topics.append(
                CollectedTopic(session_id=session.id, topic=child.task.topic, outcome=outcome)
            )
        return tuple(topics)

    async def collect_topics(self, claim: WorkerClaim) -> tuple[CollectedTopic, ...]:
        if claim.session_id != claim.root_id:
            raise Forbidden(message="Only the root may collect sibling outcomes")
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            return await self._topics(db, plan)

    async def wait_for_children(self, claim: WorkerClaim) -> bool:
        """Report join readiness without retaining an invocation while waiting."""
        if claim.session_id != claim.root_id:
            raise Forbidden(message="Only the root may wait for children")
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            ready = await db.scalar(
                select(func.count())
                .select_from(AutonomousSession)
                .where(
                    AutonomousSession.parent_session_id == claim.root_id,
                    AutonomousSession.status.in_(["completed", "failed"]),
                )
            ) == len(plan.children)
            if not ready:
                root.status = "waiting_children"
            return ready

    async def fail_synthesis(self, claim: WorkerClaim) -> None:
        """Retain delivered children and a settled but invalid model synthesis."""
        if claim.session_id != claim.root_id:
            raise Forbidden(message="Only the root may finish synthesis")
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            receipt = await db.get(Effect, (claim.session_id, "demo:synthesis:v1"))
            if account.reserved_usd or receipt is None or receipt.status != "completed":
                raise Conflict(message="Synthesis must be settled before failure")
            await self._topics(db, plan)
            session = await db.get(AutonomousSession, claim.root_id)
            assert session is not None
            root.status = session.status = "failed"
            root.stop_reason = "invalid_synthesis"
            root.updated_at = session.completed_at = now
            await _audit(db, root, "synthesis_failed", reason="invalid_output")

    async def stage_synthesis(self, claim: WorkerClaim, summary: str) -> None:
        if claim.session_id != claim.root_id:
            raise Forbidden(message="Only the root may synthesize")
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            topics = await self._topics(db, plan)
            result = DemonstrationResult(
                coverage=topic_coverage(topics), summary=summary, topics=topics
            )
            session = await db.get(AutonomousSession, claim.root_id)
            assert session is not None
            value = result.model_dump(mode="json")
            if session.result is not None and session.result != value:
                raise Conflict(message="An existing root synthesis cannot change")
            session.result = value

    async def deliver_root(self, claim: WorkerClaim) -> None:
        if claim.session_id != claim.root_id:
            raise Forbidden(message="Only the root may deliver a synthesis")
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            if await db.scalar(
                select(Account.session_id)
                .where(Account.root_id == claim.root_id, Account.reserved_usd != 0)
                .limit(1)
            ) or await db.scalar(
                select(Effect.session_id)
                .join(Account)
                .where(
                    Account.root_id == claim.root_id, Effect.status.in_(["admitted", "uncertain"])
                )
                .limit(1)
            ):
                raise Conflict(message="Unresolved work prevents root delivery")
            session = await db.get(AutonomousSession, claim.root_id)
            assert session is not None
            result = DemonstrationResult.model_validate_json(json.dumps(session.result))
            if session.current_phase != Phase.delivery.value or result.topics != await self._topics(
                db, plan
            ):
                raise Conflict(message="Root delivery is not ready")
            root.status = session.status = "failed" if result.coverage == "failed" else "completed"
            session.completed_at = session.last_activity_at = root.updated_at = await _now(db)
            details: dict[str, Any] = {"verification": "unverified"}
            # ADR 0038 D1: the answer is written into the bound chat message in
            # this transaction, with its audit row. A run that produced no
            # answer leaves the message empty, so later turns do not replay it.
            message = await db.scalar(
                select(Message)
                .where(Message.autonomous_session_id == claim.root_id)
                .with_for_update()
            )
            if message is not None and root.status == "completed":
                assert isinstance(plan, PreparedPlan)
                await self._write_answer(db, root, plan, message, result.summary)
                details.update(chat_id=str(message.chat_id), message_id=str(message.id))
                if self.on_delivered is not None and (plan.documents or plan.knowledge_bases):
                    # Nothing to check an answer against when the run selected
                    # no document and could search no knowledge base; it stays
                    # labelled unverified.
                    # The answer is delivered whether or not it could be
                    # checked. A check that fails is rolled back to its
                    # savepoint and the answer stays labelled unverified.
                    try:
                        async with db.begin_nested():
                            details.update(await self.on_delivered(db, root, plan, message))
                    except Exception:
                        # No exception text: it can carry quoted document content.
                        log.warning("Run answer checks failed; delivered unverified")
                        details.update(verification="unverified", checks="failed")
            await _audit(db, root, "root_delivered", coverage=result.coverage, **details)

    async def _write_answer(
        self,
        db: AsyncSession,
        root: Root,
        plan: PreparedPlan | PlanningSnapshot,
        message: Message,
        answer: str,
    ) -> None:
        """Fill the message fields an ordinary assistant turn carries (D2).

        Skills are the plan's pinned skills. Provider, model and tier come from
        the run's settled inference receipts. Tokens are summed across the
        tree, and cost is the tree's accounted spend. ``plan`` is the intake
        when the orchestrator answered by itself: one session, one receipt.
        """
        receipts = (
            await db.scalars(
                select(Effect)
                .join(Account, Account.session_id == Effect.session_id)
                .where(Account.root_id == root.session_id, Effect.status == "completed")
                .order_by(Effect.completed_at)
            )
        ).all()
        prompt = completion = 0
        provider = model = tier = None
        for receipt in receipts:
            data = (receipt.result or {}).get("data")
            counts = data.get("token_counts") if isinstance(data, dict) else None
            accounting = data.get("accounting") if isinstance(data, dict) else None
            if not isinstance(counts, dict) or not isinstance(accounting, dict):
                continue
            prompt += int(counts.get("prompt_tokens") or 0)
            completion += int(counts.get("completion_tokens") or 0)
            provider, model = accounting.get("provider"), accounting.get("model")
            tier = accounting.get("tier", tier)
        spent = await db.scalar(
            select(func.coalesce(func.sum(Account.spent_usd), 0)).where(
                Account.root_id == root.session_id
            )
        )
        # Installed skills only. A session instructed by an engine prompt file
        # applied no skill (ADR 0038 D3); the run's own record names the prompt.
        skills: list[str] = []
        for pin in (plan.root.skill, *(c.execution.skill for c in plan.children)):
            if pin.kind == "skill" and pin.name not in skills:
                skills.append(pin.name)
        message.content = answer
        message.applied_skills = skills
        message.routed_provider = provider if isinstance(provider, str) else None
        message.routed_model = model if isinstance(model, str) else None
        message.routed_inference_tier = tier if type(tier) is int and 1 <= tier <= 5 else None
        requested = (root.planning_snapshot or {}).get("model")
        message.requested_model = requested if isinstance(requested, str) else None
        message.prompt_tokens, message.completion_tokens = prompt, completion
        message.cost_estimate_micros = int((spent or Decimal("0")) * 1_000_000)
        # The chain-of-custody row every answered turn gets (PRD §3.3), so a
        # run's answer is attested to, and exported, like any other.
        db.add(
            WorkProductAttribution(
                message_id=message.id,
                user_id=root.owner_id,
                chat_id=message.chat_id,
                project_id=root.project_id,
                routed_inference_tier=message.routed_inference_tier,
                provider=message.routed_provider,
                model=message.routed_model,
                model_version=message.routed_model,
                skill_ids=skills,
                playbook_id=None,
                content_hash=hashlib.sha256(answer.encode("utf-8")).hexdigest(),
            )
        )
        await db.flush()

    async def close_uncertain(self, root_id: UUID, *, actor_id: UUID) -> None:
        """End an uncertain run without a retry (ADR 0038 D6).

        ADR 0035 D5 stands: nothing is repeated. Each unresolved effect is
        closed without an outcome and its reservation becomes a charge, as does
        any reservation left without an effect. Retained work stays readable.
        Leaving the ``uncertain`` state releases the owner's active-run
        allowance. Reachable after opt-out, archival or revocation, like halt:
        it only narrows authority. Takes the same lock order.
        """
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
            if root.status == "closed":
                return
            if root.status != "uncertain":
                raise Conflict(message="Only an uncertain run can be closed")
            now = await _now(db)
            accounts = (
                await db.scalars(
                    select(Account)
                    .where(Account.root_id == root_id)
                    .order_by(Account.session_id)
                    .with_for_update()
                )
            ).all()
            charged, closed = Decimal("0"), 0
            for account in accounts:
                pending = (
                    await db.scalars(
                        select(Effect)
                        .where(
                            Effect.session_id == account.session_id,
                            Effect.status.in_(["admitted", "uncertain"]),
                        )
                        .with_for_update()
                    )
                ).all()
                amount = Decimal("0")
                for effect in pending:
                    effect.status, effect.charged_usd = "closed", effect.reserved_usd
                    effect.completed_at = now
                    amount += effect.reserved_usd
                    closed += 1
                # A reservation with no effect left to explain it is charged too.
                amount = max(amount, account.reserved_usd)
                account.spent_usd += amount
                account.reserved_usd = Decimal("0")
                # Fence any worker that still believes it owns this account.
                account.generation += 1
                account.worker_id = account.lease_until = account.attempt_deadline = None
                if amount:
                    session = await db.get(AutonomousSession, account.session_id)
                    assert session is not None
                    session.cost_total_usd += amount
                charged += amount
            root.status, root.stop_reason, root.updated_at = "closed", "owner_closed", now
            await db.execute(
                update(AutonomousSession)
                .where(
                    AutonomousSession.root_session_id == root_id,
                    AutonomousSession.status == "running",
                )
                .values(status="halted", halt_state="halted", completed_at=now)
            )
            await _audit(
                db, root, "run_closed", effects_closed=closed, charged_usd=format(charged, ".4f")
            )

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
            if root.status in _TERMINAL:
                return
            if root.status != "uncertain":
                root.status = "halted"
            root.stop_reason, root.updated_at = "owner_halt", await _now(db)
            await db.execute(
                update(AutonomousSession)
                .where(
                    AutonomousSession.root_session_id == root_id,
                    AutonomousSession.status == "running",
                )
                .values(status="halted", halt_state="halt_requested", completed_at=root.updated_at)
            )
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
            if root.status not in _ACTIVE | {"planning", "awaiting_approval"}:
                return False
            root.status = "expired"
            root.stop_reason = root.stop_reason or "root_deadline"
            root.updated_at = await _now(db)
            await _audit(db, root, "root_expired", revision=plan.revision)
            session = await db.get(AutonomousSession, root_id)
            if session and isinstance(session.params.get("orchestration_profile"), str):
                await db.execute(
                    update(AutonomousSession)
                    .where(
                        AutonomousSession.root_session_id == root_id,
                        AutonomousSession.status == "running",
                    )
                    .values(status="halted", halt_state="halted", completed_at=root.updated_at)
                )
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
            await self._execution_authority(db, root, plan, now, claim.session_id)
            if isinstance(plan, PlanningSnapshot) and (
                intent != ToolIntent.plan or phase != Phase.analysis or effect_key != "chat:plan:v1"
            ):
                raise Forbidden(message="Planning permits only its single root inference")
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
            limit = (
                plan.planning_allowance_usd
                if isinstance(plan, PlanningSnapshot)
                else account.allocation_usd
            )
            if account.spent_usd + account.reserved_usd + reservation > limit:
                raise BudgetExhausted(message="Effect exceeds the run's allocated budget")
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

    async def record_refusal(
        self,
        claim: WorkerClaim,
        *,
        effect_key: str,
        request_hash: str,
        phase: Phase,
        tool: str | None,
        code: str,
        step: dict[str, Any],
    ) -> EffectReceipt:
        """Record a tool call the application refused (ADR 0038 D4).

        A refusal is a completed, zero-cost observation. It admits nothing: no
        grant is consulted because nothing runs. The same identity is returned
        unchanged on replay, so a restart neither repeats nor loses it.
        ``tool`` is a registry name or None; the audit row never carries the
        model's own text. ``step`` is the bounded record shown to the owner.
        """
        if (
            re.fullmatch(r"[a-z][a-z0-9_.:-]{0,127}", effect_key) is None
            or re.fullmatch(r"[0-9a-f]{64}", request_hash) is None
            or re.fullmatch(r"[a-z][a-z0-9_]{0,47}", code) is None
            or (tool is not None and re.fullmatch(r"[a-z][a-z0-9_]{0,47}", tool) is None)
        ):
            raise ValidationError(message="Refusal identity is invalid")
        async with self.sessions.begin() as db:
            root, plan, now = await self._root(db, claim.root_id)
            await self._approved(db, root, plan, now)
            account = await self._account(db, claim.root_id, claim.session_id)
            self._fence(account, claim, await _now(db))
            existing = await db.get(Effect, (claim.session_id, effect_key))
            if existing is not None:
                if existing.request_hash != request_hash or existing.intent != "refused":
                    raise Conflict(message="Effect identity was reused with different input")
                return _receipt(existing)
            session = await db.get(AutonomousSession, claim.session_id)
            if (
                claim.session_id == claim.root_id
                or session is None
                or session.status != "running"
                or session.halt_state != "running"
                or session.current_phase != phase.value
            ):
                raise Forbidden(message="Refusal is outside the current run's phase")
            completed = await _now(db)
            effect = Effect(
                session_id=claim.session_id,
                effect_key=effect_key,
                request_hash=request_hash,
                phase=phase.value,
                intent="refused",
                generation=claim.generation,
                status="completed",
                reserved_usd=Decimal("0"),
                charged_usd=Decimal("0"),
                result={"data": {"error": code}, "outcome": "tool_refused", "step": step},
                completed_at=completed,
            )
            db.add(effect)
            await db.flush()
            await _audit(
                db,
                root,
                "tool_refused",
                session_id=str(claim.session_id),
                generation=claim.generation,
                tool=tool or "unregistered",
                code=code,
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
        # The admitted server-side intent selects the storage bound; result
        # fields cannot opt another tool into a larger receipt.
        content = _effect_result_json(result, effect.intent)
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
