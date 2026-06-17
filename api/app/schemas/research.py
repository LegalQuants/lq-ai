"""Pydantic schemas for the /api/v1/research surface (WS3b)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VerifyCitationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=64000)


class VerifyCitationsResponse(BaseModel):
    citations: list[dict[str, Any]] = Field(default_factory=list)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(min_length=1)
    court: str | None = None
    order_by: str | None = None


class SearchResultItem(BaseModel):
    cluster_id: int | None = None
    case_name: str | None = None
    court: str | None = None
    date_filed: str | None = None
    citation: Any | None = None
    absolute_url: str | None = None
    snippet: str | None = None


class SearchResponse(BaseModel):
    count: int | None = None
    results: list[SearchResultItem] = Field(default_factory=list)
    next_cursor: str | None = None


class ClusterMeta(BaseModel):
    cluster_id: int
    case_name: str | None = None
    court: str | None = None
    date_filed: str | None = None
    absolute_url: str | None = None


class OpinionMeta(BaseModel):
    opinion_id: int
    text_field_used: str | None = None
    char_length: int


class ClusterView(BaseModel):
    cluster: ClusterMeta
    opinions: list[OpinionMeta] = Field(default_factory=list)


class OpinionText(BaseModel):
    opinion_id: int
    cluster_id: int
    text_field_used: str | None = None
    text: str


class FindInCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opinion_id: int
    query: str = Field(min_length=1)
    max_matches: int = Field(default=3, ge=1, le=10)


class FindMatch(BaseModel):
    position: int
    snippet: str


class FindInCaseResponse(BaseModel):
    opinion_id: int
    matches: list[FindMatch] = Field(default_factory=list)
