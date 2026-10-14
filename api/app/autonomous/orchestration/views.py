"""Owner-scoped plan, progress and receipts, readable after opt-out or halt."""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.autonomous.orchestration.contracts import PreparedPlan
from app.autonomous.orchestration.evidence import quotation_counts
from app.autonomous.orchestration.outcomes import DemonstrationResult, DirectAnswer, TopicOutcome
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.profiles import get_profile
from app.autonomous.orchestration.sourcing import run_sources
from app.autonomous.orchestration.tools import get_tool
from app.autonomous.orchestration.workspace import (
    WorkspaceContent,
    WorkspaceFileRead,
    file_metadata,
)
from app.errors import Conflict, NotFound
from app.models.autonomous import AutonomousSession
from app.models.chat import Message
from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationEffect as Effect,
    OrchestrationFile,
    OrchestrationPlan as PlanRow,
    OrchestrationRoot as Root,
)
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate
from app.schemas.autonomous import Phase


class StepRead(BaseModel):
    """What one step did, in registry terms (ADR 0038 D3).

    ``kind`` selects a renderer in the client; an unknown kind falls back to a
    generic presentation of ``label`` and ``summary``. ``label`` comes from the
    tool registry, so a tool the client has never seen is still described.
    ``reason`` is the model's own stated reason: text to display, never markup
    and never an instruction. ``summary`` holds counts, numbers and the owner's
    own file names; it carries no document text.
    """

    kind: str
    tool: str | None = None
    label: str | None = None
    reason: str | None = None
    summary: dict[str, Any] | None = None


class EffectRead(BaseModel):
    effect_key: str
    status: str
    reserved_usd: Decimal
    charged_usd: Decimal | None
    intent: str = ""
    created_at: datetime | None = None
    completed_at: datetime | None = None
    skill: dict[str, str] | None = None
    accounting: dict[str, Any] | None = None
    outcome: str | None = None
    step: StepRead | None = None


class ToolRead(BaseModel):
    """A tool a child's approved plan grants, as the plan card lists it."""

    name: str
    label: str
    phase: str
    registered: bool = True


class RunRead(BaseModel):
    session_id: UUID
    status: str
    phase: Phase
    allocation_usd: Decimal
    spent_usd: Decimal
    reserved_usd: Decimal
    updated_at: datetime | None
    outcome: TopicOutcome | None = None
    effects: list[EffectRead]
    files: list[WorkspaceFileRead] = []
    tools: list[ToolRead] = []
    turn_limit: int = 0


class TreeRead(BaseModel):
    root_id: UUID
    status: str
    stop_reason: str | None
    plan: PreparedPlan
    plan_hash: str
    approved: bool
    # The registry profile this run was started under (ADR 0038 D3).
    mode: str = "model_demo_v1"
    verification: Literal["unverified"] = "unverified"
    root: RunRead
    children: list[RunRead]
    spent_usd: Decimal
    reserved_usd: Decimal
    result: DemonstrationResult | None
    partial_summary: str | None


async def read_tree(
    sessions: async_sessionmaker[AsyncSession], root_id: UUID, actor_id: UUID
) -> TreeRead:
    async with sessions() as db:
        root = await db.scalar(
            select(Root).where(Root.session_id == root_id, Root.owner_id == actor_id)
        )
        if root is None or root.profile == "demonstration":
            raise NotFound(message="Orchestration root not found")
        if root.current_revision is None:
            # Still planning, ended before a plan, or answered without one.
            raise Conflict(message="This run has no plan; use the chat run view")
        row = await db.get(PlanRow, (root_id, root.current_revision))
        assert row is not None
        plan = PreparedPlan.model_validate_json(json.dumps(row.snapshot))
        runs = []
        granted = {
            child.dispatch_id: (
                [
                    ToolRead(
                        name=name,
                        label=tool.label if (tool := get_tool(name)) else name,
                        phase=phase.value,
                        registered=tool is not None,
                    )
                    for phase in Phase
                    for name in child.tools.for_phase(phase)
                ],
                child.turn_limit,
            )
            for child in plan.children
        }
        # Approved plan order includes children that have not yet been admitted.
        for session_id, allocation in (
            (root_id, plan.root_allowance_usd),
            *((child.dispatch_id, child.budget_usd) for child in plan.children),
        ):
            session = await db.get(AutonomousSession, session_id)
            account = await db.get(Account, session_id)
            receipts = list(
                await db.scalars(
                    select(Effect)
                    .where(Effect.session_id == session_id)
                    .order_by(Effect.created_at, Effect.effect_key)
                )
            )
            runs.append(
                RunRead(
                    session_id=session_id,
                    status=(
                        session.status
                        if session.status != "running"
                        else "stopped"
                        if root.status in {"uncertain", "halted", "expired", "rejected", "closed"}
                        else "running"
                        if account and account.worker_id
                        else "queued"
                    )
                    if session
                    else "pending",
                    phase=Phase(session.current_phase) if session else Phase.intake,
                    allocation_usd=allocation,
                    spent_usd=account.spent_usd if account else Decimal("0"),
                    reserved_usd=account.reserved_usd if account else Decimal("0"),
                    updated_at=session.last_activity_at if session else None,
                    outcome=TopicOutcome.model_validate_json(json.dumps(session.result))
                    if session and session.result and session_id != root_id
                    else None,
                    effects=[effect_read(e) for e in receipts],
                    files=[
                        file_metadata(file)
                        for file in await db.scalars(
                            select(OrchestrationFile)
                            .where(OrchestrationFile.session_id == session_id)
                            .order_by(OrchestrationFile.name)
                            .limit(8)
                        )
                    ],
                    tools=granted.get(session_id, ([], 0))[0],
                    turn_limit=granted.get(session_id, ([], 0))[1],
                )
            )
        root_session = await db.get(AutonomousSession, root_id)
        assert root_session is not None
        result = (
            DemonstrationResult.model_validate_json(json.dumps(root_session.result))
            if root_session.result
            else None
        )
        partial = None
        if (
            root.status in {"halted", "expired", "uncertain", "rejected", "failed", "closed"}
            and not result
        ):
            partial = (
                "The run stopped before a combined answer. Findings are unverified.\n\n"
                + "\n".join(
                    f"{child.task.topic}: {run.outcome.summary if run.outcome else 'No delivered outcome.'}"
                    for child, run in zip(plan.children, runs[1:], strict=True)
                )
            )
        return TreeRead(
            root_id=root_id,
            mode=root.profile,
            status=root.status,
            stop_reason=root.stop_reason,
            plan=plan,
            plan_hash=row.plan_hash,
            approved=row.status == "approved",
            root=runs[0],
            children=runs[1:],
            spent_usd=sum((run.spent_usd for run in runs), Decimal("0")),
            reserved_usd=sum((run.reserved_usd for run in runs), Decimal("0")),
            result=result,
            partial_summary=partial,
        )


async def read_workspace_file(
    sessions: async_sessionmaker[AsyncSession],
    root_id: UUID,
    actor_id: UUID,
    session_id: UUID,
    name: str,
) -> WorkspaceContent:
    """Owner receipt access includes private WIP after execution stops."""
    async with sessions() as db:
        row = await db.scalar(
            select(OrchestrationFile)
            .join(Account)
            .join(Root)
            .where(
                Root.session_id == root_id,
                Root.owner_id == actor_id,
                Account.session_id == session_id,
                OrchestrationFile.name == name,
            )
        )
        if row is None:
            raise NotFound(message="Workspace file not found")
        return WorkspaceContent(**file_metadata(row).model_dump(), content=row.content)


def _step(result: dict[str, Any]) -> StepRead | None:
    note = result.get("step")
    if not isinstance(note, dict) or not isinstance(note.get("kind"), str):
        return None
    name = note.get("tool") if isinstance(note.get("tool"), str) else None
    tool = get_tool(name) if name else None
    summary = note.get("summary")
    reason = note.get("reason")
    return StepRead(
        kind=note["kind"],
        tool=name,
        label=tool.label if tool else None,
        reason=reason if isinstance(reason, str) else None,
        summary=summary if isinstance(summary, dict) else None,
    )


def effect_read(effect: Effect) -> EffectRead:
    """Expose only safe provenance, never raw provider responses or prompts.

    A step's stored note is bounded at write time. Tool arguments, tool results
    and document text stay in the run's records and are not part of this view.
    """
    result = effect.result or {}
    data = result.get("data")
    data = data if isinstance(data, dict) else {}
    outcome = result.get("outcome")
    return EffectRead(
        effect_key=effect.effect_key,
        status=effect.status,
        intent=effect.intent,
        reserved_usd=effect.reserved_usd,
        charged_usd=effect.charged_usd,
        created_at=effect.created_at,
        completed_at=effect.completed_at,
        skill=data.get("skill"),
        accounting=data.get("accounting"),
        outcome=outcome if isinstance(outcome, str) else None,
        step=_step(result),
    )


class EvidenceRead(BaseModel):
    """The result of the citation checks on a delivered answer (ADR 0038 D5).

    Counts from the answer's fiduciary gate. ``flagged`` means at least one
    quotation could not be matched to the file it cites. Absent when the
    answer carried no quotation that named a source of the run (a selected
    document, or a file one of its searches found): nothing was checked, and
    the answer is unverified.
    """

    gate_status: str
    checked: int
    matched: int
    unmatched: int
    # Quotations whose marker names no source of the run, or that fall past the
    # checking cap. Nothing was checked for them.
    unresolved: int = 0
    # Quoted passages with no source marker. The checks never saw them.
    unmarked: int = 0


class SourceRead(BaseModel):
    """A knowledge-base file one of the run's searches found, with its source number.

    The number is what a quotation's ``(Source: [N])`` marker carries. Numbers
    above the selected documents belong to these files. ``session_id`` is the
    task whose search found it.
    """

    number: int
    file_id: UUID
    filename: str
    session_id: UUID


class ChatRunRead(BaseModel):
    root_id: UUID
    status: str
    stop_reason: str | None
    # True when the orchestrator answered by itself (ADR 0038 D1): the run is
    # completed with no plan, no tasks and no approval, and ``tree`` is null.
    # Nothing was read or searched for that answer.
    answered_directly: bool = False
    # That answer, as delivered. Null for every other run: a plan's combined
    # answer is ``tree.result.summary``.
    direct_answer: str | None = None
    # Knowledge-base files the run's searches found, by source number.
    sources: list[SourceRead] = []
    # The registry profile, and its display facts while it is still registered.
    profile: str = "model_demo_v1"
    profile_title: str | None = None
    reads: str | None = None
    evidence: Literal["unverified", "citations"] = "unverified"
    evidence_result: EvidenceRead | None = None
    # The chat turn this run is bound to (ADR 0038 D1); null for a run that
    # was started from the stand-alone page before chat hosting.
    chat_id: UUID | None = None
    message_id: UUID | None = None
    planning: PlanningSnapshot
    packet: str | None = None
    effects: list[EffectRead]
    spent_usd: Decimal
    reserved_usd: Decimal
    tree: TreeRead | None


async def read_chat_run(
    sessions: async_sessionmaker[AsyncSession], root_id: UUID, actor_id: UUID
) -> ChatRunRead:
    """Owner-only durable conversation, including pre-plan terminal outcomes."""
    async with sessions() as db:
        root = await db.scalar(
            select(Root).where(
                Root.session_id == root_id,
                Root.owner_id == actor_id,
                Root.profile != "demonstration",
            )
        )
        if root is None:
            raise NotFound(message="Orchestration chat not found")
        bound = (
            await db.execute(
                select(Message.chat_id, Message.id, Message.content).where(
                    Message.autonomous_session_id == root_id
                )
            )
        ).one_or_none()
        profile_id = root.profile
        gate = (
            await db.scalar(
                select(WorkProductFiduciaryGate).where(
                    WorkProductFiduciaryGate.message_id == bound.id
                )
            )
            if bound is not None
            else None
        )
        snapshot = PlanningSnapshot.model_validate_json(json.dumps(root.planning_snapshot))
        found = await run_sources(db, root_id)
        # What the checks could not see in the delivered answer, counted from the
        # answer itself against the run's source numbers: the selected documents
        # and the files its searches found.
        quoted = quotation_counts(
            (bound.content or "") if bound is not None else "",
            {document.number for document in snapshot.documents}
            | {source.number for source in found},
        )
        account = await db.get(Account, root_id)
        assert account is not None
        effects = [
            effect_read(e)
            for e in await db.scalars(
                select(Effect).where(Effect.session_id == root_id).order_by(Effect.created_at)
            )
        ]
        revision, status, reason = root.current_revision, root.status, root.stop_reason
        spent, reserved = account.spent_usd, account.reserved_usd
        answer: str | None = None
        if revision is None and status == "completed":
            session = await db.get(AutonomousSession, root_id)
            try:
                answer = DirectAnswer.model_validate_json(
                    json.dumps(session.result if session else None)
                ).summary
            except SchemaError:
                answer = None
    tree = await read_tree(sessions, root_id, actor_id) if revision else None
    profile = get_profile(profile_id)
    # Completed with no plan: the orchestrator's own answer.
    direct = revision is None and status == "completed"
    return ChatRunRead(
        root_id=root_id,
        status=tree.status if tree else status,
        stop_reason=tree.stop_reason if tree else reason,
        answered_directly=direct,
        direct_answer=answer,
        sources=[
            SourceRead(
                number=source.number,
                file_id=source.file_id,
                filename=source.filename,
                session_id=source.session_id,
            )
            for source in found
        ],
        profile=profile_id,
        profile_title=profile.title if profile else None,
        reads=profile.reads if profile else None,
        # Per run, not per profile: quotations can be checked only against
        # sources the run had, which are documents it selected and files its
        # searches found. A run with neither is unverified, and says so, and so
        # is an answer the orchestrator gave by itself, having read nothing.
        # A recorded gate means the checks ran, whatever became of the profile.
        evidence="citations"
        if gate is not None
        or (
            profile is not None
            and profile.evidence == "citations"
            and not direct
            and (snapshot.documents or found)
        )
        else "unverified",
        evidence_result=EvidenceRead(
            gate_status=gate.gate_status,
            checked=gate.total_assertions,
            matched=gate.pass_count + gate.supported_count,
            unmatched=gate.fail_count,
            unresolved=quoted["unresolved"],
            unmarked=quoted["unmarked"],
        )
        if gate is not None
        else None,
        chat_id=bound.chat_id if bound else None,
        message_id=bound.id if bound else None,
        planning=snapshot,
        effects=effects,
        spent_usd=tree.spent_usd if tree else spent,
        reserved_usd=tree.reserved_usd if tree else reserved,
        tree=tree,
    )
