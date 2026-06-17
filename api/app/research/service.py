"""Research orchestration: gateway tool calls + read-through opinion cache.

Stateless pass-throughs (verify_citations, search_case_law) just call the
gateway. get_cluster (get_cases) is read-through cached: opinion plaintext ->
object storage, metadata -> DB. find_in_case/read_opinion read the cache and
404 if the cluster was never fetched (MikeOSS "fetched-cluster" semantics).
The backend never calls CourtListener directly (ADR 0014)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import get_gateway_client
from app.errors import NotFound, ResearchNotConfigured
from app.models.research import ResearchClusterMetadata, ResearchOpinionMetadata
from app.research.html import html_to_text
from app.storage import stream_download, upload_bytes

# The type string that identifies a CourtListener tool-provider in gateway.yaml.
_COURTLISTENER_TYPE = "courtlistener"

# Process-level cache for the resolved provider name.  A config change requires
# an api restart, which is already true for how gateway config is loaded — the
# gateway itself must restart to pick up a yaml change, so the api restarting
# too is no extra burden.  Use reset_provider_cache() in tests to ensure
# isolation.
_resolved_provider: str | None = None


async def _courtlistener_providers(*, request_id: str | None = None) -> list[dict[str, str]]:
    providers = await get_gateway_client().list_tool_providers(request_id=request_id)
    return [p for p in providers if p.get("type") == _COURTLISTENER_TYPE]


async def get_capabilities(*, request_id: str | None = None) -> dict[str, Any]:
    """Return {enabled, providers} — always reads fresh from the gateway.

    This is the live signal for the UI; it does not use the cached provider
    name so it reflects the current gateway config without an api restart.
    """
    cl = await _courtlistener_providers(request_id=request_id)
    return {"enabled": bool(cl), "providers": cl}


async def _resolve_provider(*, request_id: str | None = None) -> str:
    """Return the configured CourtListener provider name, caching after first call.

    The resolved name is cached at process level after the first successful
    call; a config change (e.g. renaming the provider in gateway.yaml) takes
    effect only after an api restart or an explicit reset_provider_cache() call.

    Raises ResearchNotConfigured (503) when no courtlistener provider is wired
    in gateway.yaml.  In the rare window between get_capabilities returning
    enabled=True and this call executing, a provider that just disappeared
    would also raise here — a transient 503 is correct in that case.
    """
    global _resolved_provider
    if _resolved_provider is not None:
        return _resolved_provider
    cl = await _courtlistener_providers(request_id=request_id)
    if not cl:
        raise ResearchNotConfigured("Case-law research is not enabled on this server.")
    _resolved_provider = cl[0]["name"]
    return _resolved_provider


def reset_provider_cache() -> None:
    """Test/admin hook: clear the cached resolved provider name."""
    global _resolved_provider
    _resolved_provider = None


async def verify_citations(text: str, *, request_id: str | None = None) -> dict[str, Any]:
    provider = await _resolve_provider(request_id=request_id)
    result = await get_gateway_client().call_tool(
        provider, "verify_citations", {"text": text}, request_id=request_id
    )
    return result["payload"]


async def search_case_law(args: dict[str, Any], *, request_id: str | None = None) -> dict[str, Any]:
    provider = await _resolve_provider(request_id=request_id)
    result = await get_gateway_client().call_tool(
        provider, "search_case_law", args, request_id=request_id
    )
    return result["payload"]


def _opinion_storage_path(cluster_id: int, opinion_id: int) -> str:
    return f"courtlistener/opinions/by-cluster/{cluster_id}/{opinion_id}"


def _cluster_view(
    cluster: ResearchClusterMetadata, opinions: list[ResearchOpinionMetadata]
) -> dict[str, Any]:
    return {
        "cluster": {
            "cluster_id": cluster.cluster_id,
            "case_name": cluster.case_name,
            "court": cluster.court,
            "date_filed": cluster.date_filed,
            "absolute_url": cluster.absolute_url,
        },
        "opinions": [
            {
                "opinion_id": o.opinion_id,
                "text_field_used": o.text_field_used,
                "char_length": o.char_length,
            }
            for o in opinions
        ],
    }


async def get_cluster(
    db: AsyncSession, *, cluster_id: int, request_id: str | None = None
) -> dict[str, Any]:
    cached = (
        await db.execute(
            select(ResearchClusterMetadata).where(ResearchClusterMetadata.cluster_id == cluster_id)
        )
    ).scalar_one_or_none()
    if cached is not None:
        ops = list(
            (
                await db.execute(
                    select(ResearchOpinionMetadata).where(
                        ResearchOpinionMetadata.cluster_id == cluster_id
                    )
                )
            )
            .scalars()
            .all()
        )
        return _cluster_view(cached, ops)

    provider = await _resolve_provider(request_id=request_id)
    result = await get_gateway_client().call_tool(
        provider, "get_cases", {"cluster_id": cluster_id}, request_id=request_id
    )
    payload = result["payload"]
    cluster = payload["cluster"]
    cluster_row = ResearchClusterMetadata(
        cluster_id=cluster_id,
        case_name=cluster.get("case_name"),
        court=cluster.get("court"),
        date_filed=cluster.get("date_filed"),
        absolute_url=cluster.get("absolute_url"),
    )
    merged_cluster = await db.merge(cluster_row)
    op_rows: list[ResearchOpinionMetadata] = []
    for op in payload.get("opinions", []):
        opinion_id = op.get("id")
        if opinion_id is None:
            continue
        text = html_to_text(op.get("text") or "")
        path = _opinion_storage_path(cluster_id, opinion_id)
        await upload_bytes(
            storage_path=path,
            body=text.encode("utf-8"),
            content_type="text/plain; charset=utf-8",
        )
        op_row = await db.merge(
            ResearchOpinionMetadata(
                opinion_id=opinion_id,
                cluster_id=cluster_id,
                text_field_used=op.get("text_field_used"),
                storage_path=path,
                char_length=len(text),
            )
        )
        op_rows.append(op_row)
    await db.flush()
    return _cluster_view(merged_cluster, op_rows)


async def _load_opinion(db: AsyncSession, opinion_id: int) -> ResearchOpinionMetadata:
    row = (
        await db.execute(
            select(ResearchOpinionMetadata).where(ResearchOpinionMetadata.opinion_id == opinion_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(
            "opinion not fetched; GET /api/v1/research/clusters/{cluster_id} first",
            details={"opinion_id": opinion_id},
        )
    return row


async def _read_body(storage_path: str) -> str:
    chunks: list[bytes] = []
    async with stream_download(storage_path=storage_path) as stream:
        async for chunk in stream:
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


async def read_opinion(db: AsyncSession, *, opinion_id: int) -> dict[str, Any]:
    row = await _load_opinion(db, opinion_id)
    text = await _read_body(row.storage_path)
    return {
        "opinion_id": row.opinion_id,
        "cluster_id": row.cluster_id,
        "text_field_used": row.text_field_used,
        "text": text,
    }


async def find_in_case(
    db: AsyncSession, *, opinion_id: int, query: str, max_matches: int = 3
) -> list[dict[str, Any]]:
    row = await _load_opinion(db, opinion_id)
    text = await _read_body(row.storage_path)
    lowered = text.lower()
    needle = query.lower()
    matches: list[dict[str, Any]] = []
    start = 0
    while len(matches) < max_matches:
        idx = lowered.find(needle, start)
        if idx == -1:
            break
        lo = max(0, idx - 80)
        hi = min(len(text), idx + len(query) + 80)
        matches.append({"position": idx, "snippet": text[lo:hi]})
        start = idx + len(query)
    return matches
