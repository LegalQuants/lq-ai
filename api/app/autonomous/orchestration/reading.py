"""Which stored documents a run may read: one rule, wherever it is checked.

The rule is applied on every policy check while the run is live and again at
each read (:func:`readable_documents`). Selection never grants a read by
itself (ADR 0038 D5). Intake lists and refuses with the same predicates, so
what the owner is offered and what a run may read cannot drift apart.

* A run in a matter reads the owner's own, undeleted files that are attached
  to that matter.
* A run outside any matter reads the owner's own, undeleted files that are
  filed in no matter at all.

A file that a matter holds carries that matter's inference-tier floor and
privilege flag. So a run never takes one out of its matter: a run with no
matter does not read it, and a run in another matter does not accept it as a
candidate to attach (:func:`filed_in_another_matter`). The owner can attach a
file to a second matter themselves; that is their recorded action, and the
file is then attached to the run's matter like any other.

Knowledge bases follow the same thinking (:func:`searchable_knowledge_bases`).
A run in a matter may search the knowledge bases attached to that matter that
its plan lists. A run outside any matter searches none. A passage is shown
unless its file is held by another matter and not by this one, so a search
cannot take a file out of its matter either. A file that this matter holds as
well is the owner's own earlier action, as it is for a selected document.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any
from uuid import UUID

from sqlalchemy import Select, exists, select

from app.models.document import Document
from app.models.file import File
from app.models.knowledge import KnowledgeBase
from app.models.project import ProjectFile
from app.models.project_knowledge_base import ProjectKnowledgeBase


def filed_in_a_matter() -> Any:
    """True for a file that any matter holds, by upload or by attachment."""
    return File.project_id.is_not(None) | exists().where(ProjectFile.file_id == File.id)


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
        return query.where(~filed_in_a_matter())
    return query.join(ProjectFile, ProjectFile.file_id == File.id).where(
        ProjectFile.project_id == project_id
    )


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
