"""Server-built intake for a registry profile: allowance, selection and plan.

Model output supplies questions only. The profile, pinned skills, tools,
readable documents, budgets and limits are all chosen here from operator policy
and the owner's own records (ADR 0035 D2, ADR 0038 D3-D5).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import audit_action
from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import (
    MAX_KNOWLEDGE_BASES,
    ChildAssignment,
    DocumentRef,
    ExecutionScope,
    KnowledgeBaseRef,
    PhaseGrants,
    PhaseTools,
    PreparedPlan,
    ResourceScope,
    _unique_object,
    parse_research_proposal,
)
from app.autonomous.orchestration.inference import (
    MAX_TOOL_CALLS,
    InferenceBinding,
    InferenceRoutes,
)
from app.autonomous.orchestration.planning import (
    MAX_THREAD_BYTES,
    MAX_THREAD_MESSAGE_CHARS,
    MAX_THREAD_MESSAGES,
    PlanningSnapshot,
    ThreadMessage,
)
from app.autonomous.orchestration.policy import OperatorPolicy, load_instructions
from app.autonomous.orchestration.profiles import RunProfile, dedicated_project, run_terms
from app.autonomous.orchestration.reading import (
    attached_knowledge_bases,
    filed_in_a_matter,
    filed_in_another_matter,
)
from app.autonomous.orchestration.sourcing import run_sources
from app.autonomous.orchestration.tools import get_tool
from app.config import Settings
from app.errors import Forbidden, ValidationError
from app.models.chat import Message
from app.models.document import Document, DocumentChunk
from app.models.file import File
from app.models.orchestration import OrchestrationRoot
from app.models.project import ProjectFile
from app.schemas.autonomous import Phase
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
    project_id: UUID | None,
    goal: str,
    privileged: bool,
    minimum_inference_tier: int,
    documents: tuple[DocumentRef, ...] = (),
    thread: tuple[ThreadMessage, ...] = (),
    today: str | None = None,
    knowledge_bases: tuple[KnowledgeBaseRef, ...] = (),
) -> PlanningSnapshot:
    """Quote a maximum call allowance before accepting any paid planning."""
    snapshot, _ = await quote_intake(
        profile,
        settings=settings,
        skills=skills,
        policy=policy,
        routes=routes,
        root_id=root_id,
        owner_id=owner_id,
        project_id=project_id,
        goal=goal,
        privileged=privileged,
        minimum_inference_tier=minimum_inference_tier,
        documents=documents,
        thread=thread,
        today=today,
        knowledge_bases=knowledge_bases,
    )
    return snapshot


async def quote_intake(
    profile: RunProfile,
    *,
    settings: Settings,
    skills: MutableSkillRegistry,
    policy: OperatorPolicy,
    routes: InferenceRoutes,
    root_id: UUID,
    owner_id: UUID,
    project_id: UUID | None,
    goal: str,
    privileged: bool,
    minimum_inference_tier: int,
    documents: tuple[DocumentRef, ...] = (),
    thread: tuple[ThreadMessage, ...] = (),
    today: str | None = None,
    knowledge_bases: tuple[KnowledgeBaseRef, ...] = (),
) -> tuple[PlanningSnapshot, InferenceBinding]:
    """The intake a run would start from, and the route binding it was priced on.

    One unit is one model call at the profile's input and output limits. The
    root is allowed two (planning and synthesis). Each task is allowed one per
    model call it may make. The total cap decides how many tasks can be funded.

    The binding says what the route does for this scope before anything is
    sent: its tier, and whether calls will be pseudonymized.
    """
    route = profile.route(settings)
    dedicated = dedicated_project(profile, settings)
    if dedicated is not None and project_id != dedicated:
        raise Forbidden(message="Only the configured demo project is enabled")
    if project_id is None and profile.project_scope != "any":
        raise Forbidden(message="This run profile starts from a chat inside a matter")
    if knowledge_bases and (project_id is None or not searches_knowledge(profile)):
        raise Forbidden(message="This run searches no knowledge base")
    root_skill = next(s for s in policy.skills if s.profile == "orchestrator")
    scope = ExecutionScope(
        resources=ResourceScope(
            document_ids=tuple(d.document_id for d in documents),
            source_names=(),
            knowledge_base_ids=tuple(k.knowledge_base_id for k in knowledge_bases),
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
    registry = skills.current()
    root_text = load_instructions(registry, *profile.instructions("orchestrator"))
    child_text = load_instructions(registry, *profile.instructions("research"))
    if not root_text.version or not child_text.version:
        raise Forbidden(message="Run skills require declared versions")
    snapshot = PlanningSnapshot(
        # Version 3 carries the thread, the date and a run outside a matter.
        contract_version=3 if profile.reads_thread else 2,
        thread=thread if profile.reads_thread else (),
        today=(today or datetime.now(UTC).date().isoformat()) if profile.reads_thread else None,
        # Frozen with the request, so the run states and is held to these
        # numbers whatever the profile says later.
        terms=profile.terms() if profile.reads_thread else None,
        knowledge_bases=knowledge_bases,
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
        root_skill_version=root_text.version,
        child_skill_version=child_text.version,
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
    return (
        snapshot.model_copy(
            update={
                "root_allowance_usd": unit * 2,
                "planning_allowance_usd": unit,
                "gateway_revision": binding.gateway_revision,
                "max_children": min(4, funded),
            }
        ),
        binding,
    )


def _tool_allowance(profile: RunProfile) -> Decimal:
    """The most a task's granted tools could cost: every call of every tool turn."""
    quotes = [tool.cost_usd for name in profile.child_tools.names() if (tool := get_tool(name))]
    return max(quotes, default=Decimal("0")) * MAX_TOOL_CALLS * profile.limits.child_turn_limit


def child_allowance(profile: RunProfile, snapshot: PlanningSnapshot) -> Decimal:
    """What one task may spend: a unit per model call, plus its tools' quotes."""
    return snapshot.planning_allowance_usd * profile.calls_per_child + _tool_allowance(profile)


READ_TOOL, SEARCH_TOOL = "read_document", "search_knowledge_base"


def searches_knowledge(profile: RunProfile) -> bool:
    """Whether a task of this profile may be offered the knowledge-base search."""
    return SEARCH_TOOL in profile.child_tools.names()


def granted_tools(
    profile: RunProfile,
    documents: tuple[DocumentRef, ...],
    knowledge_bases: tuple[KnowledgeBaseRef, ...] = (),
) -> PhaseTools:
    """The tools a task of this run is offered: the profile's, less what cannot apply.

    A run with no documents has nothing to read, and a run with no knowledge
    base nothing to search, so its tasks are not offered a tool that could only
    refuse. A plan may grant a subset of what the operator allows; the
    working-note tools stay.
    """
    dropped = set()
    if profile.documents == "optional" and not documents:
        dropped.add(READ_TOOL)
    if not knowledge_bases:
        dropped.add(SEARCH_TOOL)
    if not dropped & profile.child_tools.names():
        return profile.child_tools
    return PhaseTools(
        **{
            phase.value: tuple(
                name for name in profile.child_tools.for_phase(phase) if name not in dropped
            )
            for phase in Phase
        }
    )


def prepare_model_plan(
    profile: RunProfile,
    snapshot: PlanningSnapshot,
    content: str,
    policy: OperatorPolicy,
    *,
    arguments: bool = False,
) -> PreparedPlan:
    """Model output supplies questions only; all executable choices are server-owned.

    ``content`` is the reply's text, or with ``arguments`` the arguments of the
    model's one ``propose_plan`` call. Arguments are JSON as they stand: no
    presentation fence is removed from them.
    """
    proposal = parse_research_proposal(content if arguments else model_json(content))
    if len(proposal.tasks) > snapshot.max_children:
        raise UnfundedPlan("proposal exceeds the funded task count")
    child = next(s for s in policy.skills if s.profile == "research")
    scope = snapshot.root.model_copy(update={"grants": policy.grants})
    registry = snapshot.contract_version >= 2
    granted = granted_tools(profile, snapshot.documents, snapshot.knowledge_bases)
    tooled = registry and bool(granted.names())
    turns = run_terms(profile, snapshot).task_turns
    return PreparedPlan(
        contract_version=3 if registry else 2,
        planning_digest=snapshot.approval_hash(),
        profile=snapshot.profile,
        documents=snapshot.documents,
        knowledge_bases=snapshot.knowledge_bases,
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
                tools=granted if tooled else PhaseTools(),
                turn_limit=turns if tooled else 0,
            )
            for task in proposal.tasks
        ),
        budget_usd=snapshot.budget_usd,
        root_allowance_usd=snapshot.root_allowance_usd,
        max_active_children=snapshot.max_active_children,
        deadline=snapshot.deadline,
        attempt_timeout_seconds=snapshot.attempt_timeout_seconds,
    )


# --- The thread ---------------------------------------------------------------

_SOURCE_MARKER = re.compile(r"\(Source:\s*\[(\d{1,3})\]\)")


async def _name_sources(db: AsyncSession, root_id: UUID, text: str) -> str:
    """Rewrite an earlier run's ``(Source: [N])`` markers to the file they named.

    Documents are numbered per run. In a later run the same number may be a
    different file, so a marker carried forward unchanged would point the
    planner at the wrong one.
    """
    snapshot = await db.scalar(
        select(OrchestrationRoot.planning_snapshot).where(OrchestrationRoot.session_id == root_id)
    )
    names: dict[int, str] = {}
    for entry in (snapshot or {}).get("documents") or ():
        if isinstance(entry, dict) and type(entry.get("number")) is int:
            names[entry["number"]] = str(entry.get("filename") or "")
    # Numbers above the selection are files that run's searches found.
    for source in await run_sources(db, root_id):
        names.setdefault(source.number, source.filename)

    def named(match: re.Match[str]) -> str:
        return f"(Source: {names.get(int(match[1])) or 'a document of that earlier run'})"

    return _SOURCE_MARKER.sub(named, text)


async def thread_excerpt(db: AsyncSession, *, chat_id: UUID) -> tuple[ThreadMessage, ...]:
    """The chat before this request, as the planning call will be shown it.

    The same rows an ordinary turn's history uses: user and assistant messages
    that have content and no error. The newest are kept, each cut to a bound and
    marked when cut, and the oldest are dropped until the whole fits. Read once
    at intake and frozen in the run's planning snapshot, so a replayed planning
    call sees exactly what the first attempt saw, and the owner can read it.
    """
    rows = (
        await db.execute(
            select(Message.role, Message.content, Message.autonomous_session_id)
            .where(
                Message.chat_id == chat_id,
                Message.role.in_(("user", "assistant")),
                Message.error_code.is_(None),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(MAX_THREAD_MESSAGES * 4)
        )
    ).all()
    newest_first: list[ThreadMessage] = []
    for role, content, session_id in rows:
        text = (content or "").strip()
        if not text:
            # A run that produced no answer leaves its message empty.
            continue
        if session_id is not None:
            text = await _name_sources(db, session_id, text)
        cut = len(text) > MAX_THREAD_MESSAGE_CHARS
        if cut:
            text = text[:MAX_THREAD_MESSAGE_CHARS].rstrip()
        newest_first.append(ThreadMessage(role=role, content=text, cut=cut))
        if len(newest_first) == MAX_THREAD_MESSAGES:
            break
    while newest_first and sum(len(m.content.encode()) for m in newest_first) > MAX_THREAD_BYTES:
        newest_first.pop()
    return tuple(reversed(newest_first))


# --- Knowledge bases ----------------------------------------------------------


async def list_knowledge_bases(
    db: AsyncSession, *, owner_id: UUID, project_id: UUID | None
) -> tuple[tuple[KnowledgeBaseRef, ...], int]:
    """The knowledge bases a run in this matter would search, and how many are left out.

    The owner's own, not archived, and attached to the matter, oldest
    attachment first. A run lists at most ``MAX_KNOWLEDGE_BASES``; the count of
    any beyond that is returned so the owner is told, never silently dropped.
    A chat outside any matter has none.
    """
    if project_id is None:
        return (), 0
    rows = (
        await db.execute(attached_knowledge_bases(owner_id=owner_id, project_id=project_id))
    ).all()
    listed = tuple(
        KnowledgeBaseRef(
            knowledge_base_id=row.id, name=(row.name or "").strip()[:256] or "Untitled"
        )
        for row in rows[:MAX_KNOWLEDGE_BASES]
    )
    return listed, max(0, len(rows) - MAX_KNOWLEDGE_BASES)


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
    project_id: UUID | None,
    candidate_file_ids: tuple[UUID, ...] = (),
) -> list[SelectableDocument]:
    """The files a run could read here: the matter's, plus named candidates.

    A candidate is one of the owner's own files that is not attached to the
    matter, typically a chat attachment. It is listed so it can be picked;
    picking it attaches it to the matter. A file that cannot be read is listed
    with the reason, never silently left out.

    A candidate that another matter holds is listed as unreadable here: a run
    does not take a file out of its matter. Outside a matter (``project_id``
    is None) only candidates are listed, and one that any matter holds is
    unreadable. See :mod:`app.autonomous.orchestration.reading` for the rule
    and its reason; the predicates are the ones the read checks use.
    """
    attached = (
        set(
            (
                await db.scalars(
                    select(ProjectFile.file_id).where(ProjectFile.project_id == project_id)
                )
            ).all()
        )
        if project_id is not None
        else set()
    )
    wanted = attached | set(candidate_file_ids)
    if not wanted:
        return []
    rows = (
        await db.execute(
            select(
                File,
                Document,
                filed_in_a_matter() if project_id is None else filed_in_another_matter(project_id),
            )
            .outerjoin(Document, Document.file_id == File.id)
            .where(File.id.in_(wanted), File.owner_id == owner_id, File.deleted_at.is_(None))
            .order_by(File.created_at, File.id)
        )
    ).all()
    result = []
    for file, document, held_elsewhere in rows:
        reason = _readability(file, document)
        if project_id is None:
            if held_elsewhere:
                reason = "in_a_matter"
        elif held_elsewhere and file.id not in attached:
            # Attached here as well is the owner's own earlier action, and readable.
            reason = "in_another_matter"
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
    db: AsyncSession, *, owner_id: UUID, project_id: UUID | None, file_ids: tuple[UUID, ...]
) -> tuple[tuple[DocumentRef, ...], tuple[UUID, ...]]:
    """Resolve the owner's selection, in order, to numbered documents.

    Returns the selection and the subset not yet attached to the matter. The
    whole selection is refused if any file is missing, another owner's, or
    unreadable: nothing is dropped from what the owner chose. An empty
    selection is a run with no documents. Outside a matter nothing is attached.
    """
    if len(file_ids) > MAX_SELECTED_DOCUMENTS or len(set(file_ids)) != len(file_ids):
        raise ValidationError(
            message=f"Select at most {MAX_SELECTED_DOCUMENTS} different documents"
        )
    if not file_ids:
        return (), ()
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
        attaching = project_id is not None and not found.attached_to_project
        if attaching:
            attach.append(file_id)
        refs.append(
            DocumentRef(
                number=number,
                document_id=found.document_id,
                file_id=file_id,
                filename=found.filename[:256] or "document",
                attached_for_run=attaching,
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
