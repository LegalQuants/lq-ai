"""Cluster extracted clauses by issue across the corpus — M3-A6 Phase 4.

Input: a flat list of :class:`ClauseInput` items (the union of every
extracted clause from every document in the upload corpus). The
:mod:`.extractor` step (Phase 3) ran once per document and produced
:class:`.ExtractedClause` instances; the wizard's worker (Phase 5)
flattens those into ``ClauseInput`` by attaching the source
``document_id``.

Output: one :class:`Cluster` per recurring issue. Each cluster carries:

* ``issue_label`` — the canonical (normalized) form of the issue.
* ``member_clauses`` — every clause across the corpus tagged with
  that label.
* ``modal_clause`` — the medoid of the cluster's embeddings (the
  clause whose vector minimizes total cosine distance to the rest).
  Becomes the playbook position's ``standard_language`` downstream.
* ``neighbor_clauses`` — the top-``max_fallback_neighbors`` clauses
  (by cosine distance from the modal, descending — most-different
  first) excluding the modal. Become candidate fallback tiers.

Design notes
------------

* **Label-first, embedding-second.** The extractor (Phase 3) is
  prompted to reuse common issue-vocabulary labels ("Limitation of
  Liability", "Governing Law", etc.). Clauses with the same
  normalized label join the same cluster. Embedding distance is used
  only for ranking within a cluster — for picking the modal and the
  variant neighbors.
* **No sub-clustering.** A single label like "Indemnification" may
  carry materially different positions (mutual vs. one-way), but the
  user-attorney edits the assembled playbook downstream (Phase 6's
  inline editor). Sub-clustering would multiply the position count
  without operator-friendly disambiguation. The simpler
  "one cluster per label" rule keeps the wizard's output tractable.
* **Graceful degradation.** If the embeddings call fails (gateway
  outage, dimensional mismatch), we degrade to a non-embedding modal-
  selection rule (the longest clause; ties broken by document_id) so
  the wizard run completes. The downstream user-attorney edit step
  is the safety net for any non-ideal modal choice.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections import defaultdict
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.clients.gateway import GatewayClient
from app.knowledge.embed import DEFAULT_EMBEDDING_MODEL, request_embedding_vectors
from app.playbooks.easy.extractor import ExtractedClauseSourceOffsets

logger = logging.getLogger(__name__)


DEFAULT_MAX_FALLBACK_NEIGHBORS: Final[int] = 2
"""Default count of neighbor clauses per cluster — becomes candidate
fallback tiers. Two matches the M3-A6 prep doc's design (the modal
clause becomes ``standard_language``; the two farthest neighbors
become Tier 1 + Tier 2 fallback candidates the user can edit). More
than 2 would let single-source noise dominate; fewer would leave
some legitimately-variant positions without a fallback tier."""


# ---------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------


class ClauseInput(BaseModel):
    """One extracted clause carrying source attribution.

    Flat shape — the clustering step doesn't care which document a
    clause came from, but the downstream assembly step + the wizard
    UI may want to surface document attribution for the citation-
    drilldown future enhancement.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: uuid.UUID
    issue: str
    clause_text: str
    source_offsets: ExtractedClauseSourceOffsets | None = None


class Cluster(BaseModel):
    """One position-cluster — every clause tagged with one issue label."""

    model_config = ConfigDict(extra="forbid")

    issue_label: str = Field(
        description=(
            "Canonical, human-readable issue label. The label is normalized "
            "from the per-clause ``issue`` strings — leading/trailing whitespace "
            "stripped, internal whitespace collapsed, casing preserved from the "
            "most-common variant in the cluster."
        ),
    )
    member_clauses: list[ClauseInput]
    modal_clause: ClauseInput
    neighbor_clauses: list[ClauseInput]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def cluster_clauses_by_issue(
    *,
    clauses: list[ClauseInput],
    gateway: GatewayClient,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    max_fallback_neighbors: int = DEFAULT_MAX_FALLBACK_NEIGHBORS,
) -> list[Cluster]:
    """Group ``clauses`` by issue label; return one :class:`Cluster` per label.

    Algorithm:

    1. Group by ``_normalize_issue_label(clause.issue)``. Pick the
       most-common original-case spelling within the group as the
       cluster's display label.
    2. Embed every clause text in one batched call.
    3. Within each group, compute the medoid (clause whose embedding
       minimizes total cosine distance to the others) — that's the
       modal_clause.
    4. Rank the non-modal members by cosine distance from the modal
       (largest first) and take the top ``max_fallback_neighbors``
       distinct-text clauses as neighbor_clauses.

    Edge cases:

    * Empty corpus → empty list.
    * Singleton cluster (only one document had the label) → the
      single clause is the modal; no neighbors.
    * Duplicate clause text within a cluster → the duplicates count
      once for modal selection but only one representative is
      retained (the first occurrence by ``document_id`` then position).
    * Embedding service failure → fall back to longest-clause modal
      selection; neighbor selection becomes "longest non-modal members".

    Args:
        clauses: every extracted clause across the upload corpus.
        gateway: inference gateway client used for the embeddings call.
        embedding_model: gateway model alias for the embed call;
            defaults to the project-wide embedding alias.
        max_fallback_neighbors: how many neighbor clauses per
            cluster. Two matches the M3-A6 design.
    """

    if not clauses:
        return []

    groups = _group_by_normalized_label(clauses)
    logger.info(
        "easy_cluster: %d label groups across %d clauses",
        len(groups),
        len(clauses),
        extra={
            "event": "easy_cluster_grouping",
            "group_count": len(groups),
            "clause_count": len(clauses),
        },
    )

    # Single batched embedding call across all clauses — keeps the
    # gateway round-trip count to 1 regardless of corpus size.
    embeddings = await _embed_all_or_none(
        gateway=gateway,
        model=embedding_model,
        texts=[c.clause_text for c in clauses],
    )

    clause_index_by_id = {id(c): i for i, c in enumerate(clauses)}
    clusters: list[Cluster] = []

    for canonical_label, group_clauses in groups.items():
        display_label = _pick_display_label(group_clauses, canonical=canonical_label)

        # Single-member cluster: nothing to compute.
        if len(group_clauses) == 1:
            clusters.append(
                Cluster(
                    issue_label=display_label,
                    member_clauses=group_clauses,
                    modal_clause=group_clauses[0],
                    neighbor_clauses=[],
                )
            )
            continue

        group_indices = [clause_index_by_id[id(c)] for c in group_clauses]

        if embeddings is not None:
            group_vectors = [embeddings[i] for i in group_indices]
            modal_pos = _medoid_index(group_vectors)
            distances_from_modal = [
                _cosine_distance(group_vectors[modal_pos], v) if i != modal_pos else float("-inf")
                for i, v in enumerate(group_vectors)
            ]
        else:
            # No embeddings available — modal = longest clause; tiebreak
            # by document_id stringification + position in the corpus.
            modal_pos = max(
                range(len(group_clauses)),
                key=lambda i: (
                    len(group_clauses[i].clause_text),
                    -group_indices[i],  # earlier-encountered wins ties
                ),
            )
            distances_from_modal = [
                float("-inf") if i == modal_pos else float(len(group_clauses[i].clause_text))
                for i in range(len(group_clauses))
            ]

        modal_clause = group_clauses[modal_pos]
        neighbor_clauses = _pick_neighbors(
            group_clauses=group_clauses,
            modal_pos=modal_pos,
            distances_from_modal=distances_from_modal,
            max_neighbors=max_fallback_neighbors,
        )

        clusters.append(
            Cluster(
                issue_label=display_label,
                member_clauses=group_clauses,
                modal_clause=modal_clause,
                neighbor_clauses=neighbor_clauses,
            )
        )

    # Stable ordering: largest cluster first (corpus-prevalent issues
    # surface at the top of the assembled playbook).
    clusters.sort(key=lambda c: (-len(c.member_clauses), c.issue_label))
    return clusters


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_LABEL_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_issue_label(label: str) -> str:
    """Canonicalize an issue label for grouping.

    Lowercases + strips + collapses internal whitespace. Conservative:
    we don't lemmatize or rewrite the wording (LLM-induced label drift
    is bounded by the SKILL.md's reuse-common-labels instruction). If
    cross-corpus drift becomes problematic, label-embedding similarity
    can be added in a follow-on without changing this module's surface.
    """

    return _LABEL_WHITESPACE_RE.sub(" ", label.strip().lower())


def _group_by_normalized_label(clauses: list[ClauseInput]) -> dict[str, list[ClauseInput]]:
    """Group clauses by the normalized form of their issue label."""

    groups: dict[str, list[ClauseInput]] = defaultdict(list)
    for clause in clauses:
        groups[_normalize_issue_label(clause.issue)].append(clause)
    return dict(groups)


def _pick_display_label(group_clauses: list[ClauseInput], *, canonical: str) -> str:
    """Pick the most-common original-case spelling within the group as the display label.

    Ties broken by first appearance. Falls back to title-casing the
    canonical form if every clause's label was empty after normalization
    (shouldn't happen but be defensive).
    """

    counts: dict[str, int] = defaultdict(int)
    first_seen_index: dict[str, int] = {}
    for index, clause in enumerate(group_clauses):
        original = clause.issue.strip()
        if not original:
            continue
        counts[original] += 1
        first_seen_index.setdefault(original, index)

    if not counts:
        return canonical.title()

    best = max(counts.items(), key=lambda kv: (kv[1], -first_seen_index[kv[0]]))
    return best[0]


def _pick_neighbors(
    *,
    group_clauses: list[ClauseInput],
    modal_pos: int,
    distances_from_modal: list[float],
    max_neighbors: int,
) -> list[ClauseInput]:
    """Select up to ``max_neighbors`` distinct-text neighbor clauses.

    Sorted by distance (largest first). Deduplicates on
    ``clause_text`` so a corpus where two documents share verbatim
    boilerplate doesn't end up with redundant fallback tiers — one
    representative survives.
    """

    candidates = sorted(
        ((i, distances_from_modal[i]) for i in range(len(group_clauses)) if i != modal_pos),
        key=lambda item: -item[1],
    )

    seen_texts: set[str] = {group_clauses[modal_pos].clause_text.strip()}
    out: list[ClauseInput] = []
    for index, _distance in candidates:
        text = group_clauses[index].clause_text.strip()
        if text in seen_texts:
            continue
        seen_texts.add(text)
        out.append(group_clauses[index])
        if len(out) >= max_neighbors:
            break
    return out


def _medoid_index(vectors: list[list[float]]) -> int:
    """Index of the vector that minimizes sum-of-cosine-distances to the others.

    O(n^2) — acceptable for a corpus of 5-20 documents at 5-20 clauses
    each (worst case ~400 clauses, ~160K pairwise computations on
    1536-dim vectors). A single document's worth of clauses (a few
    dozen) computes in milliseconds.

    Ties on total distance broken by index (earliest wins) — stable.
    """

    n = len(vectors)
    if n == 0:  # pragma: no cover - cluster_clauses filters singletons
        raise ValueError("medoid of empty group is undefined")
    if n == 1:
        return 0

    best_index = 0
    best_total = math.inf
    for i in range(n):
        total = 0.0
        for j in range(n):
            if i == j:
                continue
            total += _cosine_distance(vectors[i], vectors[j])
        if total < best_total:
            best_total = total
            best_index = i
    return best_index


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine distance ``1 - (a · b) / (||a|| · ||b||)``.

    Returns 0 for zero-magnitude inputs (rare in practice; vectors
    from the embedding service are non-zero). Defensive so a
    pathological all-zero embedding doesn't NaN-poison the medoid
    computation.
    """

    if len(a) != len(b):
        raise ValueError(f"cosine_distance got mismatched dimensions: {len(a)} vs {len(b)}")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return 1.0 - dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


async def _embed_all_or_none(
    *,
    gateway: GatewayClient,
    model: str,
    texts: list[str],
) -> list[list[float]] | None:
    """Batched embedding call. Returns vectors or ``None`` on any failure.

    The all-or-nothing posture is intentional: partial embeddings
    would create a confusing mix of "ranked by cosine" + "ranked by
    length" clusters within a single corpus run. A clean fallback
    (everything by length) is more interpretable for the user-
    attorney reviewing the assembled playbook.
    """

    if not texts:
        return []
    try:
        vectors = await request_embedding_vectors(texts, model=model, gateway=gateway)
    except Exception as exc:
        logger.warning(
            "easy_cluster: embedding call failed; falling back to length-based modal selection",
            extra={
                "event": "easy_cluster_embed_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return None
    if len(vectors) != len(texts):
        logger.warning(
            "easy_cluster: embedding count mismatch (%d expected, %d received); falling back",
            len(texts),
            len(vectors),
            extra={"event": "easy_cluster_embed_count_mismatch"},
        )
        return None
    return vectors
