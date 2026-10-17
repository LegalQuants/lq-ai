"""Small logical UTF-8 files, isolated by session and shared only with the root.

No host filesystem, code execution or cross-run skill memory. The guarded effect
adapter supplies authority. Content changes and receipts use one transaction;
private working files can evolve, shared findings are immutable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from pydantic import Field, StringConstraints, ValidationError as SchemaError, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.orchestration.contracts import Digest, Snapshot
from app.errors import ToolNotGranted
from app.models.orchestration import OrchestrationFile

if TYPE_CHECKING:
    from app.autonomous.guard import ToolResult
    from app.autonomous.orchestration.store import OrchestrationStore, WorkerClaim

WORKSPACE_INTENTS = frozenset(
    {ToolIntent.workspace_read, ToolIntent.workspace_write, ToolIntent.workspace_share}
)
MAX_FILES = 8
MAX_FILE_BYTES = 65536
MAX_SESSION_BYTES = 262144
MAX_REVISIONS = 32
type FileName = Annotated[
    str, StringConstraints(min_length=1, max_length=96, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
]


class WorkspaceRequest(Snapshot):
    name: FileName
    revision: Annotated[int, Field(ge=0, le=MAX_REVISIONS)]
    session_id: UUID | None = None
    content: Annotated[str, Field(max_length=MAX_FILE_BYTES)] | None = None

    @field_validator("content")
    @classmethod
    def bounded_text(cls, value: str | None) -> str | None:
        if value is not None and ("\x00" in value or len(value.encode("utf-8")) > MAX_FILE_BYTES):
            raise ValueError("File content must be bounded UTF-8 text")
        return value


def parse_request(intent: ToolIntent, params: dict[str, Any]) -> WorkspaceRequest:
    try:
        request = WorkspaceRequest.model_validate_json(json.dumps(params))
        if intent not in WORKSPACE_INTENTS:
            raise ValueError("unsupported operation")
        if intent == ToolIntent.workspace_write:
            if request.content is None or request.session_id is not None:
                raise ValueError("writes require content and own session")
        elif request.content is not None or request.revision == 0:
            raise ValueError("reads/sharing require a stored revision")
        if intent == ToolIntent.workspace_share and request.session_id is not None:
            raise ValueError("only own files can be shared")
        return request
    except (SchemaError, ValueError, TypeError):
        raise ToolNotGranted("Invalid bounded workspace operation") from None


class WorkspaceRef(Snapshot):
    session_id: UUID
    name: FileName
    revision: Annotated[int, Field(ge=1, le=MAX_REVISIONS)]
    digest: Digest


class WorkspaceFileRead(WorkspaceRef):
    size_bytes: int
    shared: bool
    updated_at: datetime


class WorkspaceContent(WorkspaceFileRead):
    content: str


def file_metadata(row: OrchestrationFile) -> WorkspaceFileRead:
    return WorkspaceFileRead(
        session_id=row.session_id,
        name=row.name,
        revision=row.revision,
        digest=row.digest,
        size_bytes=row.size_bytes,
        shared=row.shared,
        updated_at=row.updated_at,
    )


class WorkspaceAccess:
    def __init__(self, store: OrchestrationStore, claim: WorkerClaim) -> None:
        self.store, self.claim = store, claim

    async def execute(
        self, db: AsyncSession, intent: ToolIntent, params: dict[str, Any]
    ) -> ToolResult:
        from app.autonomous.guard import ToolResult

        request = parse_request(intent, params)
        claim = self.claim
        root, plan, now = await self.store._root(db, claim.root_id)
        await self.store._approved(db, root, plan, now)
        account = await self.store._account(db, claim.root_id, claim.session_id)
        fresh_now = await db.scalar(select(func.clock_timestamp()))
        assert fresh_now is not None
        now = fresh_now
        self.store._fence(account, claim, now)
        target = request.session_id or claim.session_id

        def refused(code: str) -> ToolResult:
            # Local refusals are completed observations, not uncertain effects.
            return ToolResult(
                cost_usd=Decimal("0"), outcome="workspace_refused", data={"error": code}
            )

        own = target == claim.session_id
        if not own and (
            claim.session_id != claim.root_id
            or target not in {child.dispatch_id for child in plan.children}
            or intent != ToolIntent.workspace_read
        ):
            return refused("file_unavailable")
        # Root/account locks above serialize capacity and writes in the existing
        # lock order. No file lock precedes a root lock; no remote I/O occurs here.
        row = await db.get(OrchestrationFile, (target, request.name))
        if not own and (row is None or not row.shared):
            return refused("file_unavailable")
        if intent == ToolIntent.workspace_write:
            assert request.content is not None
            if row is not None and row.shared:
                return refused("file_is_shared")
            if request.revision != (row.revision if row else 0):
                return refused("revision_conflict")
            if request.revision >= MAX_REVISIONS:
                return refused("revision_limit")
            count, total = (
                await db.execute(
                    select(func.count(), func.coalesce(func.sum(OrchestrationFile.size_bytes), 0))
                    .select_from(OrchestrationFile)
                    .where(OrchestrationFile.session_id == claim.session_id)
                )
            ).one()
            size = len(request.content.encode("utf-8"))
            if (row is None and count >= MAX_FILES) or total - (
                row.size_bytes if row else 0
            ) + size > MAX_SESSION_BYTES:
                return refused("storage_limit")
            if row is None:
                row = OrchestrationFile(
                    session_id=claim.session_id, name=request.name, shared=False
                )
                db.add(row)
            row.content, row.size_bytes = request.content, size
            row.digest = hashlib.sha256(request.content.encode("utf-8")).hexdigest()
            row.revision = request.revision + 1
            row.updated_at = now
            await db.flush()
        else:
            if row is None:
                return refused("file_unavailable")
            if row.revision != request.revision:
                return refused("revision_conflict")
            if intent == ToolIntent.workspace_share:
                row.shared = True
                row.updated_at = now
                await db.flush()
        data = file_metadata(row).model_dump(mode="json")
        if intent == ToolIntent.workspace_read:
            data["content"] = row.content
        return ToolResult(cost_usd=Decimal("0"), data=data)
