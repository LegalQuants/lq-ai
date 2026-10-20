"""Which stored documents a run may read: one rule, wherever it is checked.

The rule is applied on every policy check while the run is live and again at
each read (:func:`readable_documents`). Selection never grants a read by
itself (ADR 0038 D5). Intake lists and refuses with the same predicates, so
what the owner is offered and what a run may read cannot drift apart.

* A run in a matter reads the owner's own, undeleted files that are attached
  to that matter.
* A run outside any matter reads the owner's own, undeleted files, wherever
  they are filed, and takes on the terms of every matter that holds one of
  them (ADR 0038, ruling 4).

For the terms a run takes on, a matter holds a file when it uploaded it, when it attached it, or when the file is in a knowledge base the matter has attached (:func:`held_through_a_knowledge_base`). The candidate check for a run in a matter (:func:`filed_in_another_matter`) and the knowledge-base search's own passage check deliberately count upload and attachment only, so a file that another matter holds only through a knowledge base is still offered to a run in a matter. A file that a matter holds carries that matter's inference-tier floor and
privilege flag, and they go with the file. A run with no matter has no terms
of its own, so it runs under the strictest of its documents' matters: the
lowest floor any of them sets, and privileged if any of them is
(:func:`selection_terms`). Those terms are worked out when the request is
accepted and again at every admission, so a matter whose terms tighten, or a
file that is filed in a stricter matter, stops the run before its next call.

A run in one matter has that matter's terms. It does not accept, as a
candidate to attach, a file that only another matter holds by upload or
attachment (:func:`filed_in_another_matter`). The owner can attach a file to a
second matter themselves; that is their recorded action, and the file is then
attached to the run's matter like any other and read on this matter's terms.

A selected file that another matter holds through a knowledge base is the
exception (ruled 2026-10-13). The run may read it, and then runs under the
stricter of the two matters' terms: the lower floor, and privileged if either
is (:func:`borrowed_terms`). That holds whether this run's pick attached the
file to its matter or it was attached already, so a second run does not escape
the terms. They are set when the request is accepted and held at every
admission, like the terms of a run outside any matter. A file that a
knowledge-base search finds during the run does not change the run's terms.

Knowledge bases are narrower (:func:`searchable_knowledge_bases`).
A run in a matter may search the knowledge bases attached to that matter that
its plan lists. A run outside any matter searches none. A passage is shown
unless its file is held by another matter and not by this one, so a search
cannot take a file out of its matter either. A file that this matter holds as
well is the owner's own earlier action, as it is for a selected document.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.matters import denied_file_ids, denied_kb_ids, matter_scope_filter
from app.models.document import Document
from app.models.file import File
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.project import Project, ProjectFile
from app.models.project_knowledge_base import ProjectKnowledgeBase
from app.models.user import User


def held_through_a_knowledge_base(project: Any = None) -> Any:
    """True for a file in a knowledge base that a matter has attached.

    With ``project`` (a column or an id), only that matter. A matter's files
    include the ones in its knowledge bases, which its runs may search, so a
    file that lives only there still brings that matter's terms with it. An
    archived knowledge base counts: archiving does not release a file.
    """
    conditions = [
        KnowledgeBaseFile.file_id == File.id,
        KnowledgeBaseFile.kb_id == ProjectKnowledgeBase.knowledge_base_id,
    ]
    if project is not None:
        conditions.append(ProjectKnowledgeBase.project_id == project)
    return exists().where(*conditions)


def filed_in_a_matter() -> Any:
    """True for a file that any matter holds: by upload, attachment or a knowledge base.

    This decides which candidates of a run outside any matter bring a matter's
    terms. It is not the test of whether a matter's own search may show a
    passage (:func:`filed_in_another_matter` and :func:`filed_in_matter`), which
    stays as it was: a knowledge base's files are what that search is for.
    """
    return (
        File.project_id.is_not(None)
        | exists().where(ProjectFile.file_id == File.id)
        | held_through_a_knowledge_base()
    )


def filed_in_another_matter(project_id: UUID) -> Any:
    """True for a file that a matter other than ``project_id`` holds."""
    return (File.project_id.is_not(None) & (File.project_id != project_id)) | exists().where(
        ProjectFile.file_id == File.id, ProjectFile.project_id != project_id
    )


def filed_in_matter(project_id: UUID) -> Any:
    """True for a file that the matter ``project_id`` holds, by upload or by attachment.

    Never NULL, so that it can be negated: a file uploaded to no matter has a
    null ``project_id``, and ``NOT (NULL = :id OR false)`` would be NULL, which
    a WHERE clause treats as false.
    """
    return (File.project_id.is_not(None) & (File.project_id == project_id)) | exists().where(
        ProjectFile.file_id == File.id, ProjectFile.project_id == project_id
    )


def file_access_filter(owner_id: UUID) -> Any:
    """Keep the live matter read grant and transitive screens on owned sources."""
    return File.id.not_in(denied_file_ids(owner_id)) & (
        File.project_id.is_(None)
        | File.project_id.in_(select(Project.id).where(matter_scope_filter(User(id=owner_id))))
    )


def readable_documents(
    *, owner_id: UUID, project_id: UUID | None, document_ids: Collection[UUID]
) -> Select[tuple[UUID]]:
    """The subset of ``document_ids`` this owner's run may read in this scope.

    Callers add their own row locks. In a matter the query joins the attachment
    row, so it can be share-locked with the document and the file.
    """
    query = (
        select(Document.id)
        .join(File, File.id == Document.file_id)
        .where(
            Document.id.in_(document_ids),
            File.owner_id == owner_id,
            File.deleted_at.is_(None),
            file_access_filter(owner_id),
        )
    )
    if project_id is None:
        # Wherever the file is filed. What it costs the run to read a matter's
        # file is in ``selection_terms``, which the store holds the run to.
        return query
    return query.join(ProjectFile, ProjectFile.file_id == File.id).where(
        ProjectFile.project_id == project_id
    )


# Gateway tier semantics: a lower number is a stronger protection. A matter
# that sets no floor allows any route, which is 5.
NO_FLOOR = 5


@dataclass(frozen=True)
class MatterTerms:
    """The data terms a set of files brings with it from the matters that hold them."""

    minimum_inference_tier: int = NO_FLOOR
    privileged: bool = False


# Shown in place of an earlier run's answer that was written under stricter data
# terms than the request now being sent: to a later run's planning call, to an
# ordinary chat turn that replays the thread, and to the owner who reads what
# was sent.
WITHHELD_ANSWER = (
    "[An earlier answer is not shown here. It was written under stricter data terms "
    "(a matter's inference tier floor or privilege flag) than this request has.]"
)


def written_under_stricter_terms(snapshot: object, terms: MatterTerms) -> bool:
    """Whether the run this intake belongs to ran under stricter terms than ``terms``.

    Its floor was lower, or it was privileged and ``terms`` is not. An intake
    whose terms cannot be read counts as stricter: the answer is then
    withheld, never shown on a guess.
    """
    scope = snapshot.get("root") if isinstance(snapshot, dict) else None
    if not isinstance(scope, dict):
        return True
    floor, privileged = scope.get("minimum_inference_tier"), scope.get("privileged")
    if type(floor) is not int or type(privileged) is not bool:
        return True
    return floor < terms.minimum_inference_tier or (privileged and not terms.privileged)


def holding_matters(
    document_ids: Collection[UUID],
) -> Select[tuple[UUID, UUID, str, UUID, int | None, bool]]:
    """Each matter that holds the file of one of these documents.

    A matter holds a file by upload, by attachment, or through a knowledge base
    it has attached.

    One row for each file and matter: the file, then the matter's id, name,
    owner, floor and privilege flag. An archived matter is included: archiving
    a matter does not release its files from its terms. So is a matter of
    another owner, should one ever hold the file.
    """
    return _matters(
        document_ids,
        or_(
            Project.id == File.project_id,
            exists().where(ProjectFile.project_id == Project.id, ProjectFile.file_id == File.id),
            held_through_a_knowledge_base(Project.id),
        ),
    )


def lending_matters(
    project_id: UUID, document_ids: Collection[UUID]
) -> Select[tuple[UUID, UUID, str, UUID, int | None, bool]]:
    """Each other matter that holds the file of one of these documents through a knowledge base.

    What a run in the matter ``project_id`` borrows from. The rows are those of
    :func:`holding_matters`, and as there an archived matter and a matter of
    another owner count. A matter that holds the file by upload or attachment
    as well still counts. One that holds it by upload or attachment only does
    not: such a file is refused as a candidate, or the owner attached it to
    this matter themselves.
    """
    return _matters(document_ids, held_through_a_knowledge_base(Project.id)).where(
        Project.id != project_id
    )


def _matters(
    document_ids: Collection[UUID], holds: Any
) -> Select[tuple[UUID, UUID, str, UUID, int | None, bool]]:
    return (
        select(
            File.id,
            Project.id,
            Project.name,
            Project.owner_id,
            Project.minimum_inference_tier,
            Project.privileged,
        )
        .select_from(Document)
        .join(File, File.id == Document.file_id)
        .join(Project, holds)
        .where(Document.id.in_(document_ids))
        .order_by(File.id, Project.id)
    )


def strictest(rows: Collection[Any]) -> MatterTerms:
    """The strictest terms among ``holding_matters`` rows: lowest floor, privileged if any."""
    return MatterTerms(
        minimum_inference_tier=min((row[4] or NO_FLOOR for row in rows), default=NO_FLOOR),
        privileged=any(row[5] for row in rows),
    )


async def selection_terms(
    db: AsyncSession, document_ids: Collection[UUID], *, lock: bool = False
) -> MatterTerms:
    """The terms a run outside any matter takes on from the documents it selected.

    The strictest of every matter that holds one of them. No matter, or no
    document, means no floor and not privileged. With ``lock`` the matters are
    share-locked for the transaction, as a run's own matter is.
    """
    if not document_ids:
        return MatterTerms()
    query = holding_matters(document_ids)
    if lock:
        query = query.with_for_update(read=True, of=Project)
    return strictest((await db.execute(query)).all())


async def borrowed_terms(
    db: AsyncSession, project_id: UUID, document_ids: Collection[UUID], *, lock: bool = False
) -> MatterTerms:
    """The terms a run in a matter takes on from other matters' knowledge bases.

    The strictest of every other matter that holds one of the run's selected
    documents through a knowledge base (:func:`lending_matters`). The run's own
    matter's terms are not in this; the caller applies the stricter of the two.
    With ``lock`` those matters are share-locked, as the run's own is.
    """
    if not document_ids:
        return MatterTerms()
    query = lending_matters(project_id, document_ids)
    if lock:
        query = query.with_for_update(read=True, of=Project)
    return strictest((await db.execute(query)).all())


async def answer_terms(
    db: AsyncSession, *, project_id: UUID | None, snapshot: object
) -> MatterTerms | None:
    """The matters' terms behind an earlier run's answer, for a turn that is not a run.

    A later run is compared with what the earlier run's intake recorded
    (:func:`written_under_stricter_terms`): both floors then include the
    profile's own, which the operator sets, so they compare like with like. An
    ordinary chat turn has no profile floor. Compared with the recorded floor,
    it would be refused every answer wherever the operator's floor is stricter
    than the matter's, which is the default. So the floor here is the matters'
    alone, as they are now: for a run in a matter, that matter's and those of
    the matters it borrowed from (:func:`borrowed_terms`); for a run outside
    any matter, those of the matters that hold its selected documents
    (:func:`selection_terms`). The privilege flag is the recorded one or the
    present one, whichever is set.

    ``project_id`` is the run's matter and ``snapshot`` its intake. None when
    the intake cannot be read: the answer is then withheld, never shown on a
    guess.
    """
    scope = snapshot.get("root") if isinstance(snapshot, dict) else None
    resources = scope.get("resources") if isinstance(scope, dict) else None
    listed = resources.get("document_ids") if isinstance(resources, dict) else None
    if not isinstance(scope, dict) or not isinstance(listed, list):
        return None
    recorded = scope.get("privileged")
    if type(recorded) is not bool:
        return None
    try:
        document_ids = [UUID(str(value)) for value in listed]
    except ValueError:
        return None
    if project_id is None:
        now = await selection_terms(db, document_ids)
    else:
        own = (
            await db.execute(
                select(Project.minimum_inference_tier, Project.privileged).where(
                    Project.id == project_id
                )
            )
        ).one_or_none()
        if own is None:
            return None
        borrowed = await borrowed_terms(db, project_id, document_ids)
        now = MatterTerms(
            minimum_inference_tier=min(own[0] or NO_FLOOR, borrowed.minimum_inference_tier),
            privileged=bool(own[1]) or borrowed.privileged,
        )
    return MatterTerms(
        minimum_inference_tier=now.minimum_inference_tier,
        privileged=recorded or now.privileged,
    )


def withheld_from(answer: MatterTerms | None, turn: MatterTerms) -> bool:
    """Whether an answer written under ``answer`` is kept from a turn sent on ``turn``.

    Its floor was lower, or it was privileged and the turn is not. Terms that
    could not be read (None) count as stricter.
    """
    if answer is None:
        return True
    return answer.minimum_inference_tier < turn.minimum_inference_tier or (
        answer.privileged and not turn.privileged
    )


async def thread_for_turn(
    db: AsyncSession,
    rows: Collection[tuple[str, str, UUID | None, UUID | None, object]],
    turn: MatterTerms | None,
) -> list[tuple[str, str]]:
    """Earlier messages as an ordinary turn may send them: a stricter run's answer withheld.

    ``rows`` are ``(role, content, autonomous_session_id, run's project_id,
    run's intake)`` in the order wanted; the last two come from the run's root
    and are None for a message that is not a run's. A run's answer written
    under stricter terms than ``turn`` is replaced by :data:`WITHHELD_ANSWER`
    (ADR 0038 D5). With no ``turn`` nothing is withheld. Used by every path of
    ordinary chat that sends the thread to a model, so they share one rule.
    """
    thread: list[tuple[str, str]] = []
    for role, content, session_id, project_id, snapshot in rows:
        if (
            turn is not None
            and session_id is not None
            and withheld_from(
                await answer_terms(db, project_id=project_id, snapshot=snapshot), turn
            )
        ):
            content = WITHHELD_ANSWER
        thread.append((role, content))
    return thread


def read_locks(project_id: UUID | None) -> tuple[Any, ...]:
    """The tables :func:`readable_documents` rows are share-locked on."""
    return (Document, File) if project_id is None else (Document, File, ProjectFile)


def searchable_knowledge_bases(
    *, owner_id: UUID, project_id: UUID, knowledge_base_ids: Collection[UUID]
) -> Select[tuple[UUID, str]]:
    """The subset of ``knowledge_base_ids`` this owner's run may search now.

    The owner's own, not archived, and attached to the run's matter. Used when
    a request is accepted, to list what a run would search, and again at every
    search, where the rows are share-locked for the read.
    """
    return (
        select(KnowledgeBase.id, KnowledgeBase.name)
        .join(ProjectKnowledgeBase, ProjectKnowledgeBase.knowledge_base_id == KnowledgeBase.id)
        .where(
            KnowledgeBase.id.in_(knowledge_base_ids),
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.archived_at.is_(None),
            KnowledgeBase.id.not_in(denied_kb_ids(owner_id)),
            KnowledgeBase.project_id.is_(None)
            | KnowledgeBase.project_id.in_(
                select(Project.id).where(matter_scope_filter(User(id=owner_id)))
            ),
            ProjectKnowledgeBase.project_id == project_id,
        )
    )


def attached_knowledge_bases(*, owner_id: UUID, project_id: UUID) -> Select[tuple[UUID, str]]:
    """Every knowledge base a run in this matter could search, oldest attachment first."""
    return (
        select(KnowledgeBase.id, KnowledgeBase.name)
        .join(ProjectKnowledgeBase, ProjectKnowledgeBase.knowledge_base_id == KnowledgeBase.id)
        .where(
            KnowledgeBase.owner_id == owner_id,
            KnowledgeBase.archived_at.is_(None),
            KnowledgeBase.id.not_in(denied_kb_ids(owner_id)),
            KnowledgeBase.project_id.is_(None)
            | KnowledgeBase.project_id.in_(
                select(Project.id).where(matter_scope_filter(User(id=owner_id)))
            ),
            ProjectKnowledgeBase.project_id == project_id,
        )
        .order_by(ProjectKnowledgeBase.attached_at, KnowledgeBase.id)
    )
