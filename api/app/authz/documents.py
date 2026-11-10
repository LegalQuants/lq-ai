"""Recheck document-matter authority immediately before workflow inference."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.matters import require_document_matter_access, require_matter
from app.clients.gateway import EnsembleConfig, GatewayClient
from app.errors import NotFound
from app.models.user import User
from app.schemas.gateway import ChatCompletionRequest, ChatCompletionResponse


class DocumentWorkflowGateway(GatewayClient):
    """Borrow a gateway for non-streaming document workflows; own no HTTP client.

    The caller closes the original client. Configuration reads delegate to it;
    every content-bearing completion rechecks the current actor and all source
    matters, including ensemble/retry calls after the worker has been admitted.
    """

    def __init__(
        self,
        gateway: GatewayClient,
        db: AsyncSession,
        user_id: uuid.UUID | None,
        document_ids: Sequence[uuid.UUID],
        project_ids: Sequence[uuid.UUID] = (),
    ) -> None:
        self._gateway = gateway
        self._db = db
        self._actor_id = user_id
        self._document_ids = tuple(document_ids)
        self._project_ids = tuple(project_ids)

    async def authorize(self) -> None:
        actor = (
            await self._db.scalar(
                select(User)
                .where(User.id == self._actor_id)
                .execution_options(populate_existing=True)
            )
            if self._actor_id is not None
            else None
        )
        if actor is None or actor.deleted_at is not None:
            raise NotFound("Workflow actor no longer exists.")
        await require_document_matter_access(self._db, self._document_ids, actor, need="write")
        for project_id in self._project_ids:
            await require_matter(self._db, project_id, actor, need="write", include_archived=True)

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str | None = None,
        configuration_revision: str | None = None,
    ) -> ChatCompletionResponse:
        await self.authorize()
        kwargs: dict[str, str] = {}
        if request_id is not None:
            kwargs["request_id"] = request_id
        if configuration_revision is not None:
            kwargs["configuration_revision"] = configuration_revision
        return await self._gateway.chat_completion(request, **kwargs)

    async def get_citation_engine_ensemble_config(self) -> EnsembleConfig | None:
        return await self._gateway.get_citation_engine_ensemble_config()

    async def get_citation_engine_judge_model(self, *, fallback: str = "fast") -> str:
        return await self._gateway.get_citation_engine_judge_model(fallback=fallback)
