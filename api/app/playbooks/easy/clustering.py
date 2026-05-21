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


DEFAULT_LABEL_MERGE_THRESHOLD: Final[float] = 0.85
"""Default cosine-similarity threshold for merging semantically-similar
issue label groups into a single cluster (post-smoke iteration,
2026-05-21).

The original M3-A6 design grouped by normalized-label exact match
(whitespace + case insensitive), which left semantically-identical
positions split across multiple clusters when the extractor produced
label drift — e.g., "Term" vs "Term of Agreement" vs "Term of
Confidentiality Obligation" on the synthetic NDA corpus produced
three orphan clusters instead of one merged cluster with three
fallback variants. The first fix attempt embedded the labels and
unioned label-embedding pairs above threshold — but the synthetic-
NDA smoke showed that **label-only similarity is the wrong signal**:

* "term of agreement" / "term of confidentiality obligation" → 0.584
* "governing law" / "forum and jurisdiction" → 0.492 (same concept!)
* "definition of confidential info" / "exclusions from confidential info" → 0.731 (distinct concepts, shared words)

No single label-similarity threshold separates "want merge" from
"want keep". The signal that actually works is **the centroid of
each group's clause-text embeddings**: groups whose member clauses
talk about the same legal concept have centroid pairs in the
0.85-0.95 range, while distinct concepts sit in 0.65-0.78. The
clause text is already being embedded for medoid selection so this
piggybacks on the existing batched call with no extra round-trip.

0.85 was selected against the synthetic NDA corpus as the threshold
that merges "Term"-variant groups and "Governing Law"/"Forum and
Jurisdiction" while keeping "Definition" vs "Exclusions"-from-
Confidential-Information separate. Operators can override per-call
by passing a different ``label_merge_threshold`` (stricter = fewer
merges).

Pass ``label_merge_threshold=None`` to disable label-merging entirely
(reverts to exact-match grouping). Useful when the wizard caller
already knows the labels are clean or for unit tests that pin only
the exact-match path."""


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
    label_merge_threshold: float | None = DEFAULT_LABEL_MERGE_THRESHOLD,
) -> list[Cluster]:
    """Group ``clauses`` by issue label; return one :class:`Cluster` per label.

    Algorithm:

    1. Group by ``_normalize_issue_label(clause.issue)``. Pick the
       most-common original-case spelling within the group as the
       cluster's display label.
    2. Embed every clause text in a single batched call.
    3. **Label-merge pass (centroid-based)**: if ``label_merge_threshold``
       is set and there are 2+ unique groups, compute each group's
       centroid (element-wise mean of its member-clause embeddings)
       and union-find merge groups whose centroid pairs exceed the
       cosine-similarity threshold. The canonical label for a merged
       group is the source label whose group had the most clauses.
       Catches semantic drift ("Term" / "Term of Agreement" / "Term
       of Confidentiality Obligation"; "Governing Law" / "Forum and
       Jurisdiction") that the exact-match step misses. The label
       string itself is NOT the signal — clause-text centroids are.
    4. Within each (possibly merged) group, compute the medoid
       (clause whose embedding minimizes total cosine distance to the
       others) — that's the modal_clause.
    5. Rank the non-modal members by cosine distance from the modal
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
      Label-merging is skipped when embeddings fail (the original
      exact-match groups stand).

    Args:
        clauses: every extracted clause across the upload corpus.
        gateway: inference gateway client used for the embeddings call.
        embedding_model: gateway model alias for the embed call;
            defaults to the project-wide embedding alias.
        max_fallback_neighbors: how many neighbor clauses per
            cluster. Two matches the M3-A6 design.
        label_merge_threshold: cosine-similarity threshold for the
            label-merge pass. ``None`` disables the pass entirely
            (exact-match grouping only — the original M3-A6 behavior).
            Default ``0.85`` was tuned against the synthetic NDA corpus.
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

    # Single batched embedding call across all clause texts. Used for
    # both the label-merge pass (centroid-based) and the per-cluster
    # medoid-selection step. Keeps gateway round-trips at 1 regardless
    # of corpus size — matches the M3-A6 prep doc's design target.
    embeddings = await _embed_all_or_none(
        gateway=gateway,
        model=embedding_model,
        texts=[c.clause_text for c in clauses],
    )

    clause_index_by_id = {id(c): i for i, c in enumerate(clauses)}

    # Run the label-merge pass using clause-text centroids. Two
    # label-groups are merged when the cosine similarity of their
    # member-clause centroids exceeds the threshold — the embedding
    # of the clause TEXT is the right signal, not the label string
    # itself (proven by the post-smoke similarity probe). Skipped if
    # threshold is None, only one group exists, or embeddings failed.
    do_label_merge = (
        label_merge_threshold is not None and len(groups) >= 2 and embeddings is not None
    )
    if do_label_merge:
        groups = _merge_groups_by_clause_centroid(
            groups=groups,
            clauses=clauses,
            embeddings=embeddings,  # type: ignore[arg-type]  # guarded by do_label_merge
            clause_index_by_id=clause_index_by_id,
            similarity_threshold=label_merge_threshold,  # type: ignore[arg-type]
        )
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


def _merge_groups_by_clause_centroid(
    *,
    groups: dict[str, list[ClauseInput]],
    clauses: list[ClauseInput],
    embeddings: list[list[float]],
    clause_index_by_id: dict[int, int],
    similarity_threshold: float,
) -> dict[str, list[ClauseInput]]:
    """Union-find merge of label groups whose clause-text centroids exceed the threshold.

    For each label group, the centroid is the element-wise mean of its
    member-clause embeddings. Two groups merge when the cosine similarity
    of their centroids exceeds the threshold. The clause-text signal is
    much stronger than the label-string signal for this task: e.g.,
    "Governing Law" and "Forum and Jurisdiction" share no surface tokens
    (label cosine ~0.49) but their member clauses describe the same
    legal concept (centroid cosine in the 0.85+ range against the
    synthetic NDA corpus).

    Each connected component becomes one merged group; the canonical
    label for a merged group is the source group's label with the most
    clauses (ties → the lexicographically-first label, for stability).

    Returns a new ``groups`` dict. Singleton components pass through
    unchanged.
    """

    label_list = list(groups.keys())
    n = len(label_list)
    if n < 2:
        return groups

    centroids: list[list[float]] = []
    for label in label_list:
        group_clauses = groups[label]
        vectors = [embeddings[clause_index_by_id[id(c)]] for c in group_clauses]
        centroids.append(_centroid(vectors))

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i in range(n):
        for j in range(i + 1, n):
            similarity = 1.0 - _cosine_distance(centroids[i], centroids[j])
            if similarity > similarity_threshold:
                union(i, j)

    components: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        components[find(i)].append(i)

    merged: dict[str, list[ClauseInput]] = {}
    for root in sorted(components.keys()):
        member_label_indices = components[root]
        if len(member_label_indices) == 1:
            label = label_list[member_label_indices[0]]
            merged[label] = groups[label]
            continue

        member_labels = [label_list[idx] for idx in member_label_indices]
        canonical = max(member_labels, key=lambda lab: (len(groups[lab]), lab))

        combined_clauses: list[ClauseInput] = []
        for lab in member_labels:
            combined_clauses.extend(groups[lab])
        merged[canonical] = combined_clauses

    return merged


def _centroid(vectors: list[list[float]]) -> list[float]:
    """Element-wise mean of the input vectors. Defensive on empty input."""

    if not vectors:
        return []
    dim = len(vectors[0])
    sums = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            sums[i] += x
    n = len(vectors)
    return [s / n for s in sums]


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
