"""Server-built intake for a registry profile: allowance, selection and plan.

Model output supplies questions only. The profile, pinned skills, tools,
readable documents, budgets and limits are all chosen here from operator policy
and the owner's own records (ADR 0035 D2, ADR 0038 D3-D5).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import audit_action
from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import (
    ChildAssignment,
    DocumentRef,
    ExecutionScope,
    PhaseGrants,
    PhaseTools,
    PreparedPlan,
    ResourceScope,
    _unique_object,
    parse_research_proposal,
)
from app.autonomous.orchestration.inference import MAX_TOOL_CALLS, InferenceRoutes
from app.autonomous.orchestration.planning import PlanningSnapshot
from app.autonomous.orchestration.policy import OperatorPolicy
from app.autonomous.orchestration.profiles import RunProfile, dedicated_project
from app.autonomous.orchestration.tools import get_tool
from app.config import Settings
from app.errors import Forbidden, ValidationError
from app.models.document import Document, DocumentChunk
from app.models.file import File
from app.models.project import ProjectFile
from app.skills.registry import MutableSkillRegistry
from app.storage import upload_bytes

MAX_SELECTED_DOCUMENTS = 8
# ADR 0038 D5: only formats the ingestion pipeline produces text for.
READABLE_MIME_TYPES = frozenset({"application/pdf", "text/plain", "text/markdown"})
PACKET_FILENAME = "fictional-vendor-agreement.md"


class UnfundedPlan(ValueError):
    """The proposal has more tasks than the total cap can fund."""


def model_json(content: str) -> str:
    """Remove one complete JSON presentation fence; never extract or repair data.

    All text must still pass the strict JSON/schema parser. Prose outside the
    fence, extra objects, duplicate keys and extra authority fields are refused.
    """
    if len(content.encode()) > 131072:
        raise ValueError("Model JSON exceeds the input limit")
    value = content.strip()
    if value.startswith("```json\n") and value.endswith("\n```"):
        value = value[8:-4]
    try:
        json.loads(value, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, RecursionError):
        raise ValueError("Invalid bounded model JSON") from None
    return value


def packet(skills: MutableSkillRegistry, profile: RunProfile) -> str:
    """Load a bounded installed fixture; its bytes are included in the root pin."""
    record = skills.current().get(profile.root_skill)
    if record is None or record.source != "built-in":
        raise Forbidden(message="Installed demonstration skill is unavailable")
    try:
        content = (record.folder / "reference" / "fictional-agreement.md").read_text("utf-8")
    except (OSError, UnicodeError):
        raise Forbidden(message="Fictional source packet is unavailable") from None
    if not 1 <= len(content.encode()) <= 8192:
        raise Forbidden(message="Fictional source packet exceeds limits")
    return content


def _framing(profile: RunProfile) -> int:
    """Accounting bytes beyond message content for one call at the profile's limits."""
    if not profile.child_tools.names():
        return 96
    return 48 * (3 + (1 + MAX_TOOL_CALLS) * profile.limits.child_turn_limit)


async def prepare_intake(
    profile: RunProfile,
    *,
    settings: Settings,
    skills: MutableSkillRegistry,
    policy: OperatorPolicy,
    routes: InferenceRoutes,
    root_id: UUID,
    owner_id: UUID,
    project_id: UUID,
    goal: str,
    privileged: bool,
    minimum_inference_tier: int,
    documents: tuple[DocumentRef, ...] = (),
) -> PlanningSnapshot:
    """Quote a maximum call allowance before accepting any paid planning.

    One unit is one model call at the profile's input and output limits. The
    root is allowed two (planning and synthesis). Each task is allowed one per
    model call it may make. The total cap decides how many tasks can be funded.
    """
    route = profile.route(settings)
    dedicated = dedicated_project(profile, settings)
    if dedicated is not None and project_id != dedicated:
        raise Forbidden(message="Only the configured demo project is enabled")
    root_skill = next(s for s in policy.skills if s.profile == "orchestrator")
    scope = ExecutionScope(
        resources=ResourceScope(
            document_ids=tuple(d.document_id for d in documents), source_names=()
        ),
        grants=PhaseGrants(
            intake=(), analysis=(ToolIntent.plan,), drafting=(), ethics_review=(), delivery=()
        ),
        skill=root_skill.pin,
        minimum_inference_tier=min(minimum_inference_tier, policy.minimum_inference_tier),
        maximum_egress_tier=0,
        privileged=privileged,
        anonymize=True,
    )
    assert policy.inference is not None
    root_record = skills.current().get(profile.root_skill)
    child_record = skills.current().get(profile.child_skill)
    assert root_record and child_record
    if not root_record.frontmatter.lq_ai.version or not child_record.frontmatter.lq_ai.version:
        raise Forbidden(message="Run skills require declared versions")
    snapshot = PlanningSnapshot(
        contract_version=2,
        profile=profile.id,
        documents=documents,
        plan_id=uuid4(),
        root_id=root_id,
        owner_id=owner_id,
        project_id=project_id,
        goal=goal,
        policy_version=policy.version(),
        root=scope,
        delegation_grants=policy.grants,
        budget_usd=route.budget_usd,
        root_allowance_usd=Decimal("0"),
        planning_allowance_usd=Decimal("0"),
        max_active_children=profile.limits.max_active_children,
        deadline=datetime.now(UTC) + timedelta(seconds=profile.limits.deadline_seconds),
        attempt_timeout_seconds=route.timeout_seconds,
        packet_digest=hashlib.sha256(packet(skills, profile).encode()).hexdigest()
        if profile.documents == "packet"
        else None,
        gateway_revision="0" * 64,
        model=policy.inference.model_key,
        root_skill_version=root_record.frontmatter.lq_ai.version,
        child_skill_version=child_record.frontmatter.lq_ai.version,
    )
    binding = await routes.bind(
        snapshot,
        scope,
        [
            {"role": "system", "content": "Quote bounded run inference."},
            {"role": "user", "content": "No inference is dispatched by this readiness check."},
        ],
    )
    unit = binding.rates.cost(
        policy.inference.max_input_bytes + _framing(profile), policy.inference.max_output_tokens
    )
    per_child = unit * profile.calls_per_child + _tool_allowance(profile)
    funded = (
        4
        if per_child == 0
        else int(
            ((snapshot.budget_usd - unit * 2) / per_child).to_integral_value(rounding=ROUND_FLOOR)
        )
    )
    if funded < 1:
        raise Forbidden(message="Run budget cannot fund planning, one task and synthesis")
    return snapshot.model_copy(
        update={
            "root_allowance_usd": unit * 2,
            "planning_allowance_usd": unit,
            "gateway_revision": binding.gateway_revision,
            "max_children": min(4, funded),
        }
    )


def _tool_allowance(profile: RunProfile) -> Decimal:
    """The most a task's granted tools could cost: every call of every tool turn."""
    quotes = [tool.cost_usd for name in profile.child_tools.names() if (tool := get_tool(name))]
    return max(quotes, default=Decimal("0")) * MAX_TOOL_CALLS * profile.limits.child_turn_limit


def child_allowance(profile: RunProfile, snapshot: PlanningSnapshot) -> Decimal:
    """What one task may spend: a unit per model call, plus its tools' quotes."""
    return snapshot.planning_allowance_usd * profile.calls_per_child + _tool_allowance(profile)


def prepare_model_plan(
    profile: RunProfile, snapshot: PlanningSnapshot, content: str, policy: OperatorPolicy
) -> PreparedPlan:
    """Model output supplies questions only; all executable choices are server-owned."""
    proposal = parse_research_proposal(model_json(content))
    if len(proposal.tasks) > snapshot.max_children:
        raise UnfundedPlan("proposal exceeds the funded task count")
    child = next(s for s in policy.skills if s.profile == "research")
    scope = snapshot.root.model_copy(update={"grants": policy.grants})
    registry = snapshot.contract_version == 2
    tooled = registry and bool(profile.child_tools.names())
    return PreparedPlan(
        contract_version=3 if registry else 2,
        planning_digest=snapshot.approval_hash(),
        profile=snapshot.profile,
        documents=snapshot.documents,
        plan_id=snapshot.plan_id,
        root_id=snapshot.root_id,
        owner_id=snapshot.owner_id,
        project_id=snapshot.project_id,
        revision=1,
        goal=snapshot.goal,
        policy_version=snapshot.policy_version,
        root=scope,
        delegation_grants=policy.grants,
        children=tuple(
            ChildAssignment(
                dispatch_id=uuid4(),
                profile="research",
                task=task,
                execution=scope.model_copy(update={"skill": child.pin}),
                budget_usd=child_allowance(profile, snapshot)
                if registry
                else snapshot.planning_allowance_usd,
                tools=profile.child_tools if tooled else PhaseTools(),
                turn_limit=profile.limits.child_turn_limit if tooled else 0,
            )
            for task in proposal.tasks
        ),
        budget_usd=snapshot.budget_usd,
        root_allowance_usd=snapshot.root_allowance_usd,
        max_active_children=snapshot.max_active_children,
        deadline=snapshot.deadline,
        attempt_timeout_seconds=snapshot.attempt_timeout_seconds,
    )


# --- Documents ---------------------------------------------------------------


@dataclass(frozen=True)
class SelectableDocument:
    """One of the owner's files, with whether a run may read it and why not."""

    file_id: UUID
    filename: str
    mime_type: str
    size_bytes: int
    characters: int
    attached_to_project: bool
    selectable: bool
    reason: str | None
    document_id: UUID | None = None


def _readability(file: File, document: Document | None) -> str | None:
    if file.mime_type not in READABLE_MIME_TYPES:
        return "unsupported_type"
    if file.ingestion_status == "failed":
        return "ingestion_failed"
    if file.ingestion_status != "ready" or document is None:
        return "not_ingested"
    if not (document.normalized_content or "").strip():
        return "no_text"
    return None


async def list_documents(
    db: AsyncSession,
    *,
    owner_id: UUID,
    project_id: UUID,
    candidate_file_ids: tuple[UUID, ...] = (),
) -> list[SelectableDocument]:
    """The files a run could read here: the project's, plus named candidates.

    A candidate is one of the owner's own files that is not attached to the
    project, typically a chat attachment. It is listed so it can be picked;
    picking it attaches it to the project. A file that cannot be read is listed
    with the reason, never silently left out.
    """
    attached = set(
        (
            await db.scalars(
                select(ProjectFile.file_id).where(ProjectFile.project_id == project_id)
            )
        ).all()
    )
    wanted = attached | set(candidate_file_ids)
    if not wanted:
        return []
    rows = (
        await db.execute(
            select(File, Document)
            .outerjoin(Document, Document.file_id == File.id)
            .where(File.id.in_(wanted), File.owner_id == owner_id, File.deleted_at.is_(None))
            .order_by(File.created_at, File.id)
        )
    ).all()
    result = []
    for file, document in rows:
        reason = _readability(file, document)
        result.append(
            SelectableDocument(
                file_id=file.id,
                filename=file.filename,
                mime_type=file.mime_type,
                size_bytes=file.size_bytes,
                characters=len(document.normalized_content or "") if document else 0,
                attached_to_project=file.id in attached,
                selectable=reason is None,
                reason=reason,
                document_id=document.id if document else None,
            )
        )
    return result


async def select_documents(
    db: AsyncSession, *, owner_id: UUID, project_id: UUID, file_ids: tuple[UUID, ...]
) -> tuple[tuple[DocumentRef, ...], tuple[UUID, ...]]:
    """Resolve the owner's selection, in order, to numbered documents.

    Returns the selection and the subset not yet attached to the project. The
    whole selection is refused if any file is missing, another owner's, or
    unreadable: nothing is dropped from what the owner chose.
    """
    if not 1 <= len(file_ids) <= MAX_SELECTED_DOCUMENTS or len(set(file_ids)) != len(file_ids):
        raise ValidationError(
            message=f"Select between 1 and {MAX_SELECTED_DOCUMENTS} different documents"
        )
    listed = {
        d.file_id: d
        for d in await list_documents(
            db, owner_id=owner_id, project_id=project_id, candidate_file_ids=file_ids
        )
    }
    refs: list[DocumentRef] = []
    attach: list[UUID] = []
    for number, file_id in enumerate(file_ids, 1):
        found = listed.get(file_id)
        if found is None or not found.selectable or found.document_id is None:
            raise ValidationError(
                message="A selected document cannot be read",
                details={
                    "file_id": str(file_id),
                    "reason": found.reason if found else "not_found",
                },
            )
        if not found.attached_to_project:
            attach.append(file_id)
        refs.append(
            DocumentRef(
                number=number,
                document_id=found.document_id,
                file_id=file_id,
                filename=found.filename[:256] or "document",
                attached_for_run=not found.attached_to_project,
            )
        )
    return tuple(refs), tuple(attach)


async def ensure_packet_document(
    sessions: async_sessionmaker[AsyncSession],
    *,
    owner_id: UUID,
    project_id: UUID,
    text: str,
) -> DocumentRef:
    """File the installed fictional agreement in the demo project, once.

    ADR 0038 D4's proving case: the agreement is read through the document
    tool, so selection and the read boundary are exercised before any real
    document is involved. The bytes are stored first; a file the owner could
    not open is never left behind as a row.
    """
    digest = hashlib.sha256(text.encode()).hexdigest()

    async def existing(db: AsyncSession) -> DocumentRef | None:
        row = (
            await db.execute(
                select(File.id, Document.id)
                .join(Document, Document.file_id == File.id)
                .join(ProjectFile, ProjectFile.file_id == File.id)
                .where(
                    File.owner_id == owner_id,
                    File.deleted_at.is_(None),
                    File.filename == PACKET_FILENAME,
                    File.hash_sha256 == digest,
                    ProjectFile.project_id == project_id,
                    Document.normalized_content == text,
                )
                .order_by(File.created_at, File.id)
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        return DocumentRef(number=1, document_id=row[1], file_id=row[0], filename=PACKET_FILENAME)

    async with sessions() as db:
        found = await existing(db)
    if found is not None:
        return found
    from app.pipeline.chunker import chunk_document
    from app.pipeline.parsers import PageSpan, ParsedDocument

    file_id = uuid4()
    body = text.encode()
    try:
        await upload_bytes(storage_path=str(file_id), body=body, content_type="text/markdown")
    except Exception:
        raise Forbidden(message="The fictional agreement could not be stored") from None
    async with sessions.begin() as db:
        # One filing per owner at a time; a concurrent request reuses it.
        await db.execute(select(func.pg_advisory_xact_lock(563, func.hashtext(str(owner_id)))))
        found = await existing(db)
        if found is not None:
            return found
        db.add(
            File(
                id=file_id,
                owner_id=owner_id,
                project_id=project_id,
                filename=PACKET_FILENAME,
                mime_type="text/markdown",
                size_bytes=len(body),
                hash_sha256=digest,
                storage_path=str(file_id),
                ingestion_status="ready",
            )
        )
        await db.flush()
        parsed = ParsedDocument(
            canonical_text=text,
            pages=[PageSpan(page_number=1, char_start=0, char_end=len(text))],
            page_count=1,
            parser="orchestration-packet",
            parser_version="1",
            structured_content=None,
        )
        document = Document(
            file_id=file_id,
            parser=parsed.parser,
            parser_version=parsed.parser_version,
            page_count=1,
            character_count=len(text),
            structured_content=None,
            normalized_content=text,
            was_ocrd=False,
        )
        db.add(document)
        await db.flush()
        for chunk in chunk_document(parsed):
            db.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    char_offset_start=chunk.char_offset_start,
                    char_offset_end=chunk.char_offset_end,
                    tokens=None,
                    metadata_json=chunk.metadata,
                )
            )
        db.add(ProjectFile(project_id=project_id, file_id=file_id))
        await audit_action(
            db,
            user_id=owner_id,
            project_id=project_id,
            action="project.file_attached",
            resource_type="project",
            resource_id=str(project_id),
            details={"file_id": str(file_id), "source": "fictional_packet"},
        )
        return DocumentRef(
            number=1, document_id=document.id, file_id=file_id, filename=PACKET_FILENAME
        )
