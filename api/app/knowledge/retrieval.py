"""Hybrid (vector + FTS) retrieval over KB chunks (Task C6 / ADR 0008).

Per ADR 0008 §"Hybrid score combination":

1. Run pgvector cosine search: ``ORDER BY embedding <=> :q`` with a
   per-query limit of ``top_k * 4`` to give the rerank room to work.
2. Run Postgres FTS: ``ORDER BY ts_rank_cd(content_tsv, plainto_tsquery
   (:q)) DESC`` with the same overshoot.
3. Min-max normalize each side's scores across the union.
4. ``score = (1 - alpha) * vector + alpha * fts``.
5. Return top-``k`` by combined score.

The candidate set is filtered to chunks whose owning file is attached
to the KB AND whose ``ingestion_status='ready'`` AND whose file isn't
soft-deleted. Per-user isolation is enforced upstream by the handler
(the KB owner is the only caller; the handler verified ownership).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


CANDIDATE_OVERSHOOT: int = 4
"""Multiplier on top_k for the pre-merge candidate window.

Per ADR 0008 we overshoot 4x on each side to give the score
combination room to rerank. Smaller multipliers risk losing the
right chunk to a single-side artifact; larger multipliers cost more
DB work without measurable recall improvement at M1 scale.
"""


@dataclass(slots=True)
class HybridSearchResult:
    """One ranked chunk in a hybrid-search result.

    Field shapes mirror :class:`app.schemas.knowledge.SearchResult` so
    the handler can convert verbatim. ``vector_score`` and ``fts_score``
    are the *normalized* (post min-max) values; the raw scores are not
    surfaced to clients (they're not interpretable across queries).
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    file_id: uuid.UUID
    file_name: str
    content: str
    page_start: int | None
    page_end: int | None
    char_offset_start: int
    char_offset_end: int
    vector_score: float
    fts_score: float
    hybrid_score: float


# ---------------------------------------------------------------------------
# Hybrid search entry point
# ---------------------------------------------------------------------------


async def hybrid_search(
    db: AsyncSession,
    *,
    kb_id: uuid.UUID,
    query: str,
    query_embedding: list[float] | None,
    top_k: int,
    alpha: float,
) -> list[HybridSearchResult]:
    """Run hybrid search against KB ``kb_id`` for ``query``.

    Args:
        db: Active :class:`AsyncSession`.
        kb_id: The :class:`KnowledgeBase` id to query.
        query: User's plain-text query — passed verbatim to FTS via
            :func:`plainto_tsquery`. The embedding for this same string
            is computed by the handler before calling here.
        query_embedding: 1536-dim vector or ``None``. When ``None``,
            we skip the vector side entirely and run FTS-only — used
            when embed-on-read fails or ``alpha=1``.
        top_k: Final result count after combining.
        alpha: Mixing weight in [0, 1]. 0 => vector-only; 1 => FTS-
            only. Out-of-bound values are clamped (the API layer
            already validates).

    Returns:
        List of up to ``top_k`` :class:`HybridSearchResult`, ordered by
        descending ``hybrid_score``.
    """

    alpha = max(0.0, min(1.0, alpha))
    candidate_limit = top_k * CANDIDATE_OVERSHOOT

    # --- Vector side ------------------------------------------------------
    vector_rows: list[tuple[uuid.UUID, float]] = []
    if query_embedding is not None and alpha < 1.0:
        vector_rows = await _vector_candidates(
            db,
            kb_id=kb_id,
            query_embedding=query_embedding,
            limit=candidate_limit,
        )

    # --- FTS side ---------------------------------------------------------
    fts_rows: list[tuple[uuid.UUID, float]] = []
    if alpha > 0.0:
        fts_rows = await _fts_candidates(
            db,
            kb_id=kb_id,
            query=query,
            limit=candidate_limit,
        )

    return await _combine_and_hydrate(
        db, vector_rows=vector_rows, fts_rows=fts_rows, top_k=top_k, alpha=alpha
    )


async def _combine_and_hydrate(
    db: AsyncSession,
    *,
    vector_rows: list[tuple[uuid.UUID, float]],
    fts_rows: list[tuple[uuid.UUID, float]],
    top_k: int,
    alpha: float,
) -> list[HybridSearchResult]:
    """Min-max normalize, linearly combine, take top_k, hydrate.

    Shared by :func:`hybrid_search` (KB-scoped) and
    :func:`hybrid_search_files` (file-scoped) — the only difference
    between the two is which candidate SQL produced ``vector_rows`` /
    ``fts_rows``.
    """

    if not vector_rows and not fts_rows:
        return []

    # --- Combine ----------------------------------------------------------
    candidate_ids: set[uuid.UUID] = set()
    candidate_ids.update(cid for cid, _ in vector_rows)
    candidate_ids.update(cid for cid, _ in fts_rows)

    vector_lookup = dict(vector_rows)
    fts_lookup = dict(fts_rows)

    vector_norm = _min_max_normalize(vector_lookup)
    fts_norm = _min_max_normalize(fts_lookup)

    combined: list[tuple[uuid.UUID, float, float, float]] = []
    for cid in candidate_ids:
        v_score = vector_norm.get(cid, 0.0)
        f_score = fts_norm.get(cid, 0.0)
        hybrid = (1.0 - alpha) * v_score + alpha * f_score
        combined.append((cid, v_score, f_score, hybrid))

    combined.sort(key=lambda row: row[3], reverse=True)
    top = combined[:top_k]

    if not top:
        return []

    # --- Hydrate ----------------------------------------------------------
    score_map = {cid: (v, f, h) for cid, v, f, h in top}
    rows = await _hydrate_chunks(db, [cid for cid, _, _, _ in top])

    results: list[HybridSearchResult] = []
    for row in rows:
        cid = row["chunk_id"]
        scores = score_map.get(cid)
        if scores is None:
            continue
        v_score, f_score, hybrid_score = scores
        results.append(
            HybridSearchResult(
                chunk_id=cid,
                document_id=row["document_id"],
                file_id=row["file_id"],
                file_name=row["file_name"],
                content=row["content"],
                page_start=row["page_start"],
                page_end=row["page_end"],
                char_offset_start=row["char_offset_start"],
                char_offset_end=row["char_offset_end"],
                vector_score=v_score,
                fts_score=f_score,
                hybrid_score=hybrid_score,
            )
        )
    # Re-sort because _hydrate_chunks doesn't preserve order.
    results.sort(key=lambda r: r.hybrid_score, reverse=True)
    return results


# ---------------------------------------------------------------------------
# File-scoped hybrid search entry point
# ---------------------------------------------------------------------------


async def hybrid_search_files(
    db: AsyncSession,
    *,
    file_ids: list[uuid.UUID],
    query: str,
    query_embedding: list[float] | None,
    top_k: int,
    alpha: float,
) -> list[HybridSearchResult]:
    """Hybrid search scoped to an explicit set of file ids.

    Same score model as :func:`hybrid_search` (pgvector cosine + FTS,
    min-max normalized, ``(1-alpha)*vec + alpha*fts``) but the candidate
    set is ``document_chunks`` whose owning file is in ``file_ids`` (not
    a KB join). Callers MUST have already authorized ``file_ids`` — this
    primitive does no ownership check, matching :func:`hybrid_search`'s
    contract (the handler enforces scope).
    """
    if not file_ids:
        return []
    alpha = max(0.0, min(1.0, alpha))
    candidate_limit = top_k * CANDIDATE_OVERSHOOT
    ids = [str(fid) for fid in file_ids]

    vector_rows: list[tuple[uuid.UUID, float]] = []
    if query_embedding is not None and alpha < 1.0:
        result = await db.execute(
            _VECTOR_SQL_FILES,
            {"file_ids": ids, "q_emb": _format_vector(query_embedding), "limit": candidate_limit},
        )
        vector_rows = [
            (uuid.UUID(str(r["chunk_id"])), float(r["vec_score"])) for r in result.mappings().all()
        ]

    fts_rows: list[tuple[uuid.UUID, float]] = []
    if alpha > 0.0:
        result = await db.execute(
            _FTS_SQL_FILES, {"file_ids": ids, "q": query, "limit": candidate_limit}
        )
        fts_rows = [
            (uuid.UUID(str(r["chunk_id"])), float(r["fts_rank"])) for r in result.mappings().all()
        ]

    return await _combine_and_hydrate(
        db, vector_rows=vector_rows, fts_rows=fts_rows, top_k=top_k, alpha=alpha
    )


# ---------------------------------------------------------------------------
# Side queries
# ---------------------------------------------------------------------------


_VECTOR_SQL = text(
    """
    SELECT dc.id AS chunk_id,
           1.0 - (dc.embedding <=> CAST(:q_emb AS vector)) AS vec_score
      FROM document_chunks dc
      JOIN documents d ON d.id = dc.document_id
      JOIN files f ON f.id = d.file_id
      JOIN knowledge_base_files kbf ON kbf.file_id = f.id
     WHERE kbf.kb_id = :kb_id
       AND f.deleted_at IS NULL
       AND f.ingestion_status = 'ready'
       AND dc.embedding IS NOT NULL
     ORDER BY dc.embedding <=> CAST(:q_emb AS vector)
     LIMIT :limit
    """
)


async def _vector_candidates(
    db: AsyncSession,
    *,
    kb_id: uuid.UUID,
    query_embedding: list[float],
    limit: int,
) -> list[tuple[uuid.UUID, float]]:
    """Run the pgvector cosine query.

    Returns ``(chunk_id, vector_score)`` pairs; ``vector_score`` is
    ``1 - cosine_distance``, in roughly ``[0, 1]`` for normalized
    embeddings (OpenAI's text-embedding-3-* are unit-normalized at
    output, so cosine distance is in [0, 2] and ``1 - dist`` is in
    [-1, 1]; we clamp at the normalize step).
    """

    vector_text = _format_vector(query_embedding)
    result = await db.execute(
        _VECTOR_SQL,
        {"kb_id": str(kb_id), "q_emb": vector_text, "limit": limit},
    )
    rows = result.mappings().all()
    return [(uuid.UUID(str(row["chunk_id"])), float(row["vec_score"])) for row in rows]


_FTS_SQL = text(
    """
    SELECT dc.id AS chunk_id,
           ts_rank_cd(dc.content_tsv, plainto_tsquery('english', :q)) AS fts_rank
      FROM document_chunks dc
      JOIN documents d ON d.id = dc.document_id
      JOIN files f ON f.id = d.file_id
      JOIN knowledge_base_files kbf ON kbf.file_id = f.id
     WHERE kbf.kb_id = :kb_id
       AND f.deleted_at IS NULL
       AND f.ingestion_status = 'ready'
       AND dc.content_tsv @@ plainto_tsquery('english', :q)
     ORDER BY fts_rank DESC
     LIMIT :limit
    """
)


async def _fts_candidates(
    db: AsyncSession,
    *,
    kb_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[tuple[uuid.UUID, float]]:
    """Run the FTS query (``plainto_tsquery`` + ``ts_rank_cd``).

    ``plainto_tsquery`` is the safest tsquery constructor for user
    input — it lexes and stems each whitespace-separated token without
    interpreting any operators. Operators (``&``, ``|``, ``!``) are
    treated as literal characters.
    """

    result = await db.execute(_FTS_SQL, {"kb_id": str(kb_id), "q": query, "limit": limit})
    rows = result.mappings().all()
    return [(uuid.UUID(str(row["chunk_id"])), float(row["fts_rank"])) for row in rows]


# ---------------------------------------------------------------------------
# File-scoped side queries
# ---------------------------------------------------------------------------


_VECTOR_SQL_FILES = text(
    """
    SELECT dc.id AS chunk_id,
           1.0 - (dc.embedding <=> CAST(:q_emb AS vector)) AS vec_score
      FROM document_chunks dc
      JOIN documents d ON d.id = dc.document_id
      JOIN files f ON f.id = d.file_id
     WHERE f.id = ANY(:file_ids)
       AND f.deleted_at IS NULL
       AND f.ingestion_status = 'ready'
       AND dc.embedding IS NOT NULL
     ORDER BY dc.embedding <=> CAST(:q_emb AS vector)
     LIMIT :limit
    """
)


_FTS_SQL_FILES = text(
    """
    SELECT dc.id AS chunk_id,
           ts_rank_cd(dc.content_tsv, plainto_tsquery('english', :q)) AS fts_rank
      FROM document_chunks dc
      JOIN documents d ON d.id = dc.document_id
      JOIN files f ON f.id = d.file_id
     WHERE f.id = ANY(:file_ids)
       AND f.deleted_at IS NULL
       AND f.ingestion_status = 'ready'
       AND dc.content_tsv @@ plainto_tsquery('english', :q)
     ORDER BY fts_rank DESC
     LIMIT :limit
    """
)


_HYDRATE_SQL = text(
    """
    SELECT dc.id AS chunk_id,
           dc.document_id AS document_id,
           f.id AS file_id,
           f.filename AS file_name,
           dc.content AS content,
           dc.page_start AS page_start,
           dc.page_end AS page_end,
           dc.char_offset_start AS char_offset_start,
           dc.char_offset_end AS char_offset_end
      FROM document_chunks dc
      JOIN documents d ON d.id = dc.document_id
      JOIN files f ON f.id = d.file_id
     WHERE dc.id = ANY(:ids)
    """
)


async def _hydrate_chunks(
    db: AsyncSession,
    chunk_ids: list[uuid.UUID],
) -> list[dict[str, Any]]:
    """Fetch the chunk rows + file metadata for ``chunk_ids``."""

    if not chunk_ids:
        return []
    result = await db.execute(_HYDRATE_SQL, {"ids": [str(cid) for cid in chunk_ids]})
    rows = result.mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "chunk_id": uuid.UUID(str(row["chunk_id"])),
                "document_id": uuid.UUID(str(row["document_id"])),
                "file_id": uuid.UUID(str(row["file_id"])),
                "file_name": str(row["file_name"]),
                "content": str(row["content"]),
                "page_start": (int(row["page_start"]) if row["page_start"] is not None else None),
                "page_end": int(row["page_end"]) if row["page_end"] is not None else None,
                "char_offset_start": int(row["char_offset_start"]),
                "char_offset_end": int(row["char_offset_end"]),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Score combination helpers
# ---------------------------------------------------------------------------


def _min_max_normalize(scores: dict[uuid.UUID, float]) -> dict[uuid.UUID, float]:
    """Min-max normalize a score map to [0, 1].

    Per ADR 0008 we use min-max not z-score — z-score requires non-trivial
    standard deviation which fails on small candidate sets common at M1
    scale. With min-max:

    * If every score is identical, every normalized score is 1.0 (the
      candidate set is uniformly relevant according to that side).
    * If the set is empty, returns an empty dict (caller handles the
      missing-entry case as 0 contribution).
    * Otherwise, ``norm = (score - min) / (max - min)`` clamped to
      [0, 1].
    """

    if not scores:
        return {}
    values = list(scores.values())
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return dict.fromkeys(scores, 1.0)
    out: dict[uuid.UUID, float] = {}
    spread = hi - lo
    for cid, score in scores.items():
        normalized = (score - lo) / spread
        # Clamp to [0, 1] — vector_score = 1 - cosine_distance can be
        # slightly outside [0, 1] for non-normalized embeddings.
        out[cid] = max(0.0, min(1.0, normalized))
    return out


def _format_vector(vector: list[float]) -> str:
    """Format a float list as pgvector's textual ``[v1,v2,...]`` form."""

    return "[" + ",".join(repr(float(v)) for v in vector) + "]"
