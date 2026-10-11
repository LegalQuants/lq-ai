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

A matter holds a file when it uploaded it, when it attached it, or when the
file is in a knowledge base the matter has attached (:func:`held_through_a_knowledge_base`).
A file that a matter holds carries that matter's inference-tier floor and
privilege flag, and they go with the file. A run with no matter has no terms
of its own, so it runs under the strictest of its documents' matters: the
lowest floor any of them sets, and privileged if any of them is
(:func:`selection_terms`). Those terms are worked out when the request is
accepted and again at every admission, so a matter whose terms tighten, or a
file that is filed in a stricter matter, stops the run before its next call.

A run in one matter is different: it has that matter's terms and no others.
It does not accept, as a candidate to attach, a file that only another matter
holds (:func:`filed_in_another_matter`). The owner can attach a file to a
second matter themselves; that is their recorded action, and the file is then
attached to the run's matter like any other.

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

from app.models.document import Document
from app.models.file import File
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.project import Project, ProjectFile
from app.models.project_knowledge_base import ProjectKnowledgeBase


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
        .join(
            Project,
            or_(
                Project.id == File.project_id,
                exists().where(
                    ProjectFile.project_id == Project.id, ProjectFile.file_id == File.id
                ),
                held_through_a_knowledge_base(Project.id),
            ),
        )
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
            ProjectKnowledgeBase.project_id == project_id,
        )
        .order_by(ProjectKnowledgeBase.attached_at, KnowledgeBase.id)
    )
