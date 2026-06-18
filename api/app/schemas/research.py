"""Pydantic schemas for the /api/v1/research surface (WS3b)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Closed set of opinion text fields, in the adapter's preference order.
# MUST stay in sync with _OPINION_TEXT_FIELDS in
# gateway/app/providers/tool/courtlistener.py.
OpinionTextField = Literal[
    "html_with_citations",
    "html_columbia",
    "html_lawbox",
    "xml_harvard",
    "html_anon_2020",
    "html",
    "plain_text",
]


class VerifyCitationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=64000)


class CitationCluster(BaseModel):
    id: int | None = None
    case_name: str | None = None
    absolute_url: str | None = None


class VerifiedCitation(BaseModel):
    citation: str | None = None
    normalized_citations: list[str] = Field(default_factory=list)
    status: int | None = None
    error_message: str | None = None
    clusters: list[CitationCluster] = Field(default_factory=list)


class VerifyCitationsResponse(BaseModel):
    citations: list[VerifiedCitation] = Field(default_factory=list)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(min_length=1)
    court: str | None = None
    order_by: str | None = None
    cursor: str | None = None


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
    text_field_used: OpinionTextField | None = None
    char_length: int


class ClusterView(BaseModel):
    cluster: ClusterMeta
    opinions: list[OpinionMeta] = Field(default_factory=list)


class OpinionText(BaseModel):
    opinion_id: int
    cluster_id: int
    text_field_used: OpinionTextField | None = None
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


class ResearchProvider(BaseModel):
    name: str
    type: str


class ResearchCapabilities(BaseModel):
    enabled: bool
    providers: list[ResearchProvider] = Field(default_factory=list)
