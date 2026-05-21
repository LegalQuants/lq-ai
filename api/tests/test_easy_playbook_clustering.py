"""Tests for ``app.playbooks.easy.clustering`` — M3-A6 Phase 4.

Verifies the structural shape of the clustering output: label
grouping, modal/medoid selection, neighbor ranking, and the
embeddings-failure fallback. The downstream user-attorney evaluates
final cluster correctness during the wizard's Step 3 inline editor;
these tests are the "structurally correct" gate per the M3-A6
quality bar.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.playbooks.easy.clustering import (
    ClauseInput,
    _cosine_distance,
    _medoid_index,
    _normalize_issue_label,
    cluster_clauses_by_issue,
)

# ---------------------------------------------------------------------------
# Stub gateway for embeddings — separate from the chat-completion stub used by
# the extractor / assembly tests; the embedding wire shape is OpenAI-compatible
# {data: [{embedding: [...], index: int}]}
# ---------------------------------------------------------------------------


@dataclass
class _StubEmbeddingGateway:
    """Returns one canned vector per input, in declaration order.

    Tests pre-populate ``vectors`` with the per-clause embeddings.
    The stub mirrors the gateway's OpenAI-shaped response.
    """

    vectors: list[list[float]] = field(default_factory=list)
    calls_received: list[dict[str, Any]] = field(default_factory=list)
    raise_on_call: BaseException | None = None
    return_wrong_count: bool = False
    """If True, returns one fewer vector than requested — triggers
    the count-mismatch fallback path in :func:`_embed_all_or_none`."""

    async def embeddings(
        self,
        *,
        model: str,
        input_: str | list[str],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        inputs = [input_] if isinstance(input_, str) else input_
        self.calls_received.append({"model": model, "input_": inputs})
        if self.raise_on_call is not None:
            raise self.raise_on_call
        if self.return_wrong_count:
            data = [
                {"index": i, "embedding": self.vectors[i]} for i in range(max(len(inputs) - 1, 0))
            ]
        else:
            data = [{"index": i, "embedding": self.vectors[i]} for i in range(len(inputs))]
        return {"data": data}


def _mk(issue: str, text: str) -> ClauseInput:
    return ClauseInput(document_id=uuid.uuid4(), issue=issue, clause_text=text)


# ---------------------------------------------------------------------------
# Pure-Python helpers — exercised first (no async; no stubs needed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_normalize_issue_label_lowercases_and_collapses_whitespace() -> None:
    assert _normalize_issue_label("Limitation of Liability") == "limitation of liability"
    assert _normalize_issue_label("  Governing   Law  ") == "governing law"
    assert _normalize_issue_label("MUTUAL\tINDEMNIFICATION") == "mutual indemnification"


@pytest.mark.unit
def test_cosine_distance_orthogonal_vectors_is_one() -> None:
    assert _cosine_distance([1.0, 0.0], [0.0, 1.0]) == 1.0


@pytest.mark.unit
def test_cosine_distance_identical_vectors_is_zero() -> None:
    assert _cosine_distance([3.0, 4.0], [3.0, 4.0]) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.unit
def test_cosine_distance_zero_magnitude_defaults_to_zero() -> None:
    """Defensive: pathological all-zero embedding doesn't NaN-poison the medoid."""

    assert _cosine_distance([0.0, 0.0], [1.0, 1.0]) == 0.0


@pytest.mark.unit
def test_cosine_distance_dimension_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        _cosine_distance([1.0, 0.0], [1.0, 0.0, 0.0])


@pytest.mark.unit
def test_medoid_index_picks_central_vector() -> None:
    # Three points: (0,0), (1,0), (0,1). The medoid by cosine distance
    # is (1,0) — equally distant from (0,1) as (0,1) is from it, but
    # the (0,0) zero-magnitude defaults all distances to 0 so the
    # algorithm pricks the first encountered tied minimum.
    # Use clearer non-zero vectors so the test pins a specific medoid.
    vectors = [
        [1.0, 0.0, 0.0],  # close to v1
        [0.9, 0.1, 0.0],  # the medoid: small angle to v0 and v2
        [0.0, 1.0, 0.0],  # orthogonal to v0
    ]
    assert _medoid_index(vectors) == 1


# ---------------------------------------------------------------------------
# Clustering — empty + singleton
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_empty_corpus_returns_empty_list() -> None:
    gateway = _StubEmbeddingGateway()
    result = await cluster_clauses_by_issue(
        clauses=[],
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert result == []
    # No embedding call when there's nothing to cluster.
    assert gateway.calls_received == []


@pytest.mark.unit
async def test_singleton_cluster_has_no_neighbors() -> None:
    """A cluster with only one clause: that clause is the modal; neighbors=[]."""

    gateway = _StubEmbeddingGateway(vectors=[[1.0, 0.0, 0.0]])
    clauses = [_mk("Governing Law", "Delaware law applies.")]
    clusters = await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clusters) == 1
    assert clusters[0].issue_label == "Governing Law"
    assert clusters[0].modal_clause is clauses[0]
    assert clusters[0].neighbor_clauses == []


# ---------------------------------------------------------------------------
# Label grouping — fuzzy on whitespace and casing
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_label_drift_via_whitespace_and_casing_still_clusters() -> None:
    """Label variants like "Governing Law" / "governing law" / " Governing  Law " co-cluster."""

    gateway = _StubEmbeddingGateway(
        vectors=[[1.0, 0.0], [0.9, 0.1], [0.8, 0.2]],
    )
    clauses = [
        _mk("Governing Law", "Delaware law."),
        _mk("governing law", "New York law."),
        _mk("  Governing   Law  ", "California law."),
    ]
    clusters = await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clusters) == 1
    # Display label is the most-common original-case spelling
    # ("Governing Law" appears once, "governing law" once,
    # "  Governing   Law  " once — first-encountered tiebreak wins).
    assert clusters[0].issue_label == "Governing Law"
    assert len(clusters[0].member_clauses) == 3


# ---------------------------------------------------------------------------
# Modal + neighbor selection
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_modal_is_medoid_and_neighbors_are_farthest() -> None:
    """Three clauses in one cluster: middle one is medoid; outer two are neighbors."""

    # Vectors chosen so v1 is centrally placed between v0 and v2.
    # v0 + v2 are orthogonal; v1 sits at a 45deg angle between them.
    gateway = _StubEmbeddingGateway(
        vectors=[
            [1.0, 0.0, 0.0],
            [0.707, 0.707, 0.0],
            [0.0, 1.0, 0.0],
        ],
    )
    c0 = _mk("Indemnification", "Vendor indemnifies for IP claims only.")
    c1 = _mk("Indemnification", "Mutual indemnification for IP and breach.")
    c2 = _mk("Indemnification", "Customer indemnifies for misuse only.")
    clusters = await cluster_clauses_by_issue(
        clauses=[c0, c1, c2],
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clusters) == 1
    assert clusters[0].modal_clause is c1
    # Both c0 and c2 are equidistant from c1 by cosine; ordering is
    # by distance then index. The set is what matters.
    neighbor_ids = {id(n) for n in clusters[0].neighbor_clauses}
    assert neighbor_ids == {id(c0), id(c2)}
    assert len(clusters[0].neighbor_clauses) == 2


@pytest.mark.unit
async def test_max_fallback_neighbors_caps_neighbor_count() -> None:
    """``max_fallback_neighbors=1`` returns only the single farthest neighbor."""

    gateway = _StubEmbeddingGateway(
        vectors=[
            [1.0, 0.0, 0.0],  # v0 — modal candidate
            [0.95, 0.31, 0.0],  # closer to v0
            [0.0, 1.0, 0.0],  # farther from v0
        ],
    )
    clauses = [
        _mk("Term", "Three years."),
        _mk("Term", "Five years."),
        _mk("Term", "Perpetual obligation."),
    ]
    clusters = await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
        max_fallback_neighbors=1,
    )
    assert len(clusters[0].neighbor_clauses) == 1


@pytest.mark.unit
async def test_duplicate_clause_text_dedupes_in_neighbors() -> None:
    """Verbatim-duplicate clauses do not produce redundant fallback tiers."""

    # c0 is unique; c1 and c2 share verbatim text. Medoid lands on one
    # of the duplicate-text clauses (smallest sum-of-distances). The
    # dedup pass skips the other copy of the modal's text, so only the
    # unique-text c0 appears as a neighbor.
    gateway = _StubEmbeddingGateway(
        vectors=[
            [1.0, 0.0],
            [0.0, 1.0],
            [0.0, 1.0],
        ],
    )
    duplicate_text = "Liability is capped at the fees paid in the prior 12 months."
    c0 = _mk("Limitation of Liability", "Liability uncapped.")
    c1 = _mk("Limitation of Liability", duplicate_text)
    c2 = _mk("Limitation of Liability", duplicate_text)
    clusters = await cluster_clauses_by_issue(
        clauses=[c0, c1, c2],
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clusters) == 1
    # Modal is one of the duplicate-text clauses (lower sum-of-distances).
    assert clusters[0].modal_clause.clause_text == duplicate_text
    # Only the unique-text clause survives as a neighbor; the second
    # duplicate-text copy is dedup'd out.
    assert len(clusters[0].neighbor_clauses) == 1
    assert clusters[0].neighbor_clauses[0].clause_text == "Liability uncapped."


# ---------------------------------------------------------------------------
# Label merging via embedding similarity (M3-A6 Phase 4 post-smoke iteration)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_similar_clause_centroids_merge_into_one_cluster() -> None:
    """Label groups whose clause-text centroids exceed the threshold merge.

    Three different labels, each with one clause; the three clauses
    embed to near-identical vectors (centroid pairs ~0.99 cosine
    similarity, well above the 0.85 default threshold). Result: one
    merged cluster, regardless of how different the label strings are.
    The label-only similarity probe on the synthetic NDA corpus showed
    that surface tokens are NOT the right signal — clause-text
    centroids are.
    """

    gateway = _StubEmbeddingGateway(
        vectors=[
            # Three clauses — all embed close together
            [1.0, 0.0, 0.0],
            [0.99, 0.14, 0.0],
            [0.98, 0.20, 0.0],
        ],
    )
    clauses = [
        _mk("Term", "Three years."),
        _mk("Term of Agreement", "Five years."),
        _mk("Term of Confidentiality Obligation", "Two years."),
    ]
    clusters = await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clusters) == 1, (
        f"Expected 1 merged cluster, got {len(clusters)}: {[c.issue_label for c in clusters]}"
    )
    assert len(clusters[0].member_clauses) == 3


@pytest.mark.unit
async def test_dissimilar_clause_centroids_stay_separate() -> None:
    """Label groups whose clause-text centroids are below threshold do NOT merge.

    Even when label strings might share words, distinct clause-text
    centroids keep the groups separate. (E.g., "Definition of
    Confidential Info" vs "Exclusions from Confidential Info" share
    surface tokens but cover distinct legal concepts.)
    """

    gateway = _StubEmbeddingGateway(
        vectors=[
            [1.0, 0.0],
            [0.0, 1.0],  # orthogonal — centroid cosine 0.0
        ],
    )
    clauses = [
        _mk("Confidential Information — Definition", "Confidential Information includes [...]"),
        _mk("Confidential Information — Exclusions", "The obligations do not apply to [...]"),
    ]
    clusters = await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clusters) == 2


@pytest.mark.unit
async def test_merge_threshold_controls_aggressiveness() -> None:
    """A stricter threshold (0.99) keeps near-similar centroids separate."""

    gateway = _StubEmbeddingGateway(
        vectors=[
            [1.0, 0.0],
            [0.95, 0.31],  # centroid cosine ~0.95 — merges at 0.85, not at 0.99
        ],
    )
    clauses = [
        _mk("Term", "Three years."),
        _mk("Term of Agreement", "Five years."),
    ]
    clusters_strict = await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
        label_merge_threshold=0.99,
    )
    assert len(clusters_strict) == 2


@pytest.mark.unit
async def test_merge_threshold_none_disables_merging() -> None:
    """When label_merge_threshold is None, no merge runs even with identical centroids."""

    gateway = _StubEmbeddingGateway(
        vectors=[
            [1.0, 0.0],
            [1.0, 0.0],  # identical centroids — would merge at default threshold
        ],
    )
    clauses = [
        _mk("Term", "Three years."),
        _mk("Term of Agreement", "Five years."),
    ]
    clusters = await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
        label_merge_threshold=None,
    )
    # No merging — two distinct exact-match labels survive as separate clusters.
    assert len(clusters) == 2


@pytest.mark.unit
async def test_merged_cluster_canonical_label_is_most_populated() -> None:
    """When merging, the canonical label = the source group with the most clauses."""

    # 3 source label groups with similar clause centroids: "Term" (2
    # clauses), "Term of Agreement" (1 clause), "Term of
    # Confidentiality" (1 clause). All merge. Expected canonical:
    # "Term" (most-populated source group).
    gateway = _StubEmbeddingGateway(
        vectors=[
            [1.0, 0.0, 0.0],
            [0.99, 0.14, 0.0],
            [0.98, 0.20, 0.0],
            [0.99, 0.14, 0.0],
        ],
    )
    clauses = [
        _mk("Term", "Three years."),
        _mk("Term", "Five years."),
        _mk("Term of Agreement", "Two years."),
        _mk("Term of Confidentiality", "One year."),
    ]
    clusters = await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clusters) == 1
    assert clusters[0].issue_label == "Term"
    assert len(clusters[0].member_clauses) == 4


# ---------------------------------------------------------------------------
# Ordering — largest cluster first
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_clusters_ordered_by_member_count_descending() -> None:
    gateway = _StubEmbeddingGateway(
        vectors=[
            [1.0, 0.0],  # group A
            [0.9, 0.1],  # group A
            [0.8, 0.2],  # group A
            [0.0, 1.0],  # group B (singleton)
        ],
    )
    clauses = [
        _mk("Confidentiality", "Standard non-disclosure obligations."),
        _mk("Confidentiality", "Five-year confidentiality obligation."),
        _mk("Confidentiality", "Indefinite obligation on trade secrets."),
        _mk("Audit Rights", "Annual audit at customer expense."),
    ]
    clusters = await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert [c.issue_label for c in clusters] == ["Confidentiality", "Audit Rights"]
    assert len(clusters[0].member_clauses) == 3
    assert len(clusters[1].member_clauses) == 1


# ---------------------------------------------------------------------------
# Embeddings failure — length-based fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_embedding_failure_falls_back_to_length_based_modal() -> None:
    """Gateway raises → modal = longest clause; neighbors by length."""

    gateway = _StubEmbeddingGateway(raise_on_call=ConnectionError("embeddings 503"))
    short = _mk("Payment Terms", "Net 30.")
    medium = _mk("Payment Terms", "Invoices due net 60 days.")
    longest = _mk(
        "Payment Terms",
        "Customer shall pay invoices within 90 days; late payments accrue 1.5%/mo interest.",
    )
    clusters = await cluster_clauses_by_issue(
        clauses=[short, medium, longest],
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clusters) == 1
    # Longest clause is the modal under fallback.
    assert clusters[0].modal_clause is longest
    # Both other clauses appear as neighbors (ordered by length DESC).
    assert clusters[0].neighbor_clauses[0] is medium
    assert clusters[0].neighbor_clauses[1] is short


@pytest.mark.unit
async def test_embedding_count_mismatch_falls_back() -> None:
    """If the gateway returns N-1 vectors for N inputs, fall back gracefully."""

    gateway = _StubEmbeddingGateway(
        vectors=[[1.0, 0.0], [0.0, 1.0]],
        return_wrong_count=True,
    )
    clauses = [
        _mk("Audit", "Quarterly audits."),
        _mk("Audit", "Annual audits at customer expense."),
    ]
    clusters = await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
    )
    # Cluster forms; modal is the longer clause (fallback rule).
    assert len(clusters) == 1
    assert clusters[0].modal_clause.clause_text == "Annual audits at customer expense."


# ---------------------------------------------------------------------------
# Embeddings call — batched, one request per run
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_embeddings_called_once_with_labels_and_clauses_batched() -> None:
    """One batched call carrying clause texts only.

    The centroid-based label-merge pass reuses the clause embeddings
    from the modal-selection step — labels are NOT embedded separately.
    Keeps round-trip count to 1 regardless of corpus size, matching
    the M3-A6 prep doc's "one gateway call" target.
    """

    gateway = _StubEmbeddingGateway(
        vectors=[
            [1.0, 0.0],
            [0.9, 0.1],
            [0.0, 1.0],
        ],
    )
    clauses = [
        _mk("Foo", "A."),
        _mk("Foo", "B."),
        _mk("Bar", "C."),
    ]
    await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(gateway.calls_received) == 1
    assert gateway.calls_received[0]["input_"] == ["A.", "B.", "C."]


@pytest.mark.unit
async def test_embeddings_call_is_clauses_only_when_merge_disabled() -> None:
    """When ``label_merge_threshold=None`` is passed, the batched call also carries clauses only.

    Same shape as the default case — the label-merge mechanism never
    embedded labels separately under the centroid algorithm, so this
    is asserting the more-permissive contract that the batched call
    has not gained label inputs even when merging is off.
    """

    gateway = _StubEmbeddingGateway(
        vectors=[[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]],
    )
    clauses = [
        _mk("Foo", "A."),
        _mk("Foo", "B."),
        _mk("Bar", "C."),
    ]
    await cluster_clauses_by_issue(
        clauses=clauses,
        gateway=gateway,  # type: ignore[arg-type]
        label_merge_threshold=None,
    )
    assert gateway.calls_received[0]["input_"] == ["A.", "B.", "C."]
