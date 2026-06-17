"""/api/v1/research — case-law research surface (WS3b)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.db.session import get_db
from app.research import service
from app.schemas.research import (
    ClusterView,
    FindInCaseRequest,
    FindInCaseResponse,
    FindMatch,
    OpinionText,
    ResearchCapabilities,
    SearchRequest,
    SearchResponse,
    VerifyCitationsRequest,
    VerifyCitationsResponse,
)

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/capabilities", response_model=ResearchCapabilities)
async def capabilities(user: ActiveUser) -> ResearchCapabilities:
    return ResearchCapabilities(**await service.get_capabilities())


@router.post("/verify-citations", response_model=VerifyCitationsResponse)
async def verify_citations(
    payload: VerifyCitationsRequest, user: ActiveUser
) -> VerifyCitationsResponse:
    result = await service.verify_citations(payload.text)
    return VerifyCitationsResponse(citations=result.get("citations", []))


@router.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, user: ActiveUser) -> SearchResponse:
    result = await service.search_case_law(payload.model_dump(exclude_none=True))
    return SearchResponse(**result)


@router.get("/clusters/{cluster_id}", response_model=ClusterView)
async def get_cluster(
    cluster_id: int, user: ActiveUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> ClusterView:
    result = await service.get_cluster(db, cluster_id=cluster_id)
    await db.commit()
    return ClusterView(**result)


@router.get("/opinions/{opinion_id}", response_model=OpinionText)
async def read_opinion(
    opinion_id: int, user: ActiveUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> OpinionText:
    return OpinionText(**await service.read_opinion(db, opinion_id=opinion_id))


@router.post("/find-in-case", response_model=FindInCaseResponse)
async def find_in_case(
    payload: FindInCaseRequest,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FindInCaseResponse:
    raw_matches = await service.find_in_case(
        db,
        opinion_id=payload.opinion_id,
        query=payload.query,
        max_matches=payload.max_matches,
    )
    matches = [FindMatch(**m) for m in raw_matches]
    return FindInCaseResponse(opinion_id=payload.opinion_id, matches=matches)
