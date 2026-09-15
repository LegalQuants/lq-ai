"""Corpus-replay test for Easy Playbook clustering — DE-308.

Replays the five-document sample NDA corpus
(``docs/quickstart/sample-ndas/``) through
:func:`cluster_clauses_by_issue` and scores the result against the
corpus README's target: **5-10 positions covering all five variant
axes** (Term, Definition of Confidential Information, Standard of
Care, Survival of Trade Secrets, Permitted Disclosures).

Honesty note on fixtures
------------------------

This is a *deterministic fixture replay*, not a live pipeline run:

* The per-document extractor outputs are hand-recorded emulations of
  what the (DE-308-fixed) extraction prompt produces on the corpus —
  including realistic label drift ("Term" / "Term of Agreement" /
  "Term and Termination") and the per-README axis variants. No live
  LLM is called.
* Embeddings come from a deterministic synthetic-vector stub: each
  clause carries a ground-truth axis, and its vector lies in that
  axis's 2-D plane at a small per-clause angle. Same-axis centroids
  land above the 0.85 merge threshold; cross-axis similarity is 0;
  one drift singleton is deliberately placed in the 0.80-0.85 gap
  (folds) and one genuine outlier in its own plane (stays). No live
  embedding provider is called.

The final end-to-end numbers against real ``smart``-alias extraction
and real embeddings come from the maintainer's attorney walk-through
of the wizard (flagged in the DE-308 PR), not from this suite.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Final

import pytest

from app.playbooks.easy.clustering import ClauseInput, Cluster, cluster_clauses_by_issue

# ---------------------------------------------------------------------------
# Deterministic synthetic embeddings
# ---------------------------------------------------------------------------

# One 2-D plane per semantic axis; vectors on different axes are
# orthogonal (cosine 0), vectors on the same axis differ only by a
# small angle. 9 axes → 18-dim vectors.
_AXIS_TERM: Final[int] = 0
_AXIS_DEFINITION: Final[int] = 1
_AXIS_CARE: Final[int] = 2
_AXIS_SURVIVAL: Final[int] = 3
_AXIS_PERMITTED: Final[int] = 4
_AXIS_GOVLAW: Final[int] = 5
_AXIS_RETURN: Final[int] = 6
_AXIS_REMEDIES: Final[int] = 7
_AXIS_REVERSE_ENG: Final[int] = 8

_DIM: Final[int] = 18


def _axis_vector(axis: int, angle: float) -> list[float]:
    """Unit vector in ``axis``'s plane at ``angle`` radians from the plane's base."""

    vec = [0.0] * _DIM
    vec[2 * axis] = math.cos(angle)
    vec[2 * axis + 1] = math.sin(angle)
    return vec


# ---------------------------------------------------------------------------
# Recorded corpus fixture — (document #, issue label, clause snippet, axis, angle)
#
# Labels and clause variants mirror docs/quickstart/sample-ndas/README.md's
# variant-axis table; label drift is included on purpose (it is exactly
# what over-segmented the pre-DE-308 output).
# ---------------------------------------------------------------------------

_CORPUS: Final[list[tuple[int, str, str, int, float]]] = [
    # NDA 1 — Acme <-> Beta
    (
        1,
        "Term of Agreement",
        "This Agreement terminates three (3) years from the Effective Date.",
        _AXIS_TERM,
        0.00,
    ),
    (
        1,
        "Definition of Confidential Information",
        "Confidential Information means all information disclosed orally or in writing, whether or not marked.",
        _AXIS_DEFINITION,
        0.00,
    ),
    (
        1,
        "Standard of Care",
        "The Receiving Party shall use reasonable care to protect the Confidential Information.",
        _AXIS_CARE,
        0.00,
    ),
    (
        1,
        "Survival of Trade Secrets",
        "Obligations as to trade secrets survive for five (5) years after termination.",
        _AXIS_SURVIVAL,
        0.00,
    ),
    (
        1,
        "Permitted Disclosures",
        "Disclosure is permitted to employees and professional advisors with a need to know.",
        _AXIS_PERMITTED,
        0.00,
    ),
    (
        1,
        "Governing Law",
        "This Agreement is governed by the laws of the State of Delaware.",
        _AXIS_GOVLAW,
        0.00,
    ),
    (
        1,
        "Return or Destruction of Materials",
        "Upon request, the Receiving Party shall return or destroy all Confidential Information.",
        _AXIS_RETURN,
        0.00,
    ),
    (
        1,
        "Remedies",
        "Breach entitles the Disclosing Party to seek equitable relief in addition to damages.",
        _AXIS_REMEDIES,
        0.00,
    ),
    # NDA 2 — Cypress <-> Delta (no separate survival clause, per README)
    (2, "Term of Agreement", "The term of this Agreement is two (2) years.", _AXIS_TERM, 0.10),
    (
        2,
        "Confidential Information — Definition",
        "Confidential Information means written information marked confidential; oral disclosures must be confirmed in writing within thirty (30) days.",
        _AXIS_DEFINITION,
        0.12,
    ),
    (
        2,
        "Standard of Care",
        "The Receiving Party shall maintain the Confidential Information using a standard of care consistent with industry practice.",
        _AXIS_CARE,
        0.10,
    ),
    (
        2,
        "Permitted Disclosures",
        "Disclosure is permitted to employees only.",
        _AXIS_PERMITTED,
        0.10,
    ),
    (
        2,
        "Governing Law",
        "This Agreement is governed by the laws of the State of New York.",
        _AXIS_GOVLAW,
        0.10,
    ),
    (
        2,
        "Return or Destruction of Materials",
        "All materials shall be returned within ten (10) days of written request.",
        _AXIS_RETURN,
        0.10,
    ),
    (
        2,
        "Remedies",
        "The parties agree that money damages may be inadequate for breach of confidentiality.",
        _AXIS_REMEDIES,
        0.10,
    ),
    # NDA 3 — Echo <-> Foxtrot
    (
        3,
        "Term",
        "This Agreement continues for five (5) years from the Effective Date.",
        _AXIS_TERM,
        -0.10,
    ),
    (
        3,
        "Definition of Confidential Information",
        "Confidential Information means information in the enumerated categories, including technical, financial, and business information.",
        _AXIS_DEFINITION,
        -0.10,
    ),
    (
        3,
        "Degree of Care",
        "The Receiving Party shall protect the Confidential Information using at least the same degree of care as its own information.",
        _AXIS_CARE,
        -0.12,
    ),
    (
        3,
        "Trade Secret Survival",
        "Trade secret obligations survive for as long as trade-secret status is maintained.",
        _AXIS_SURVIVAL,
        0.15,
    ),
    (
        3,
        "Permitted Disclosures",
        "Disclosure is permitted to employees, advisors, and affiliates bound by confidentiality.",
        _AXIS_PERMITTED,
        -0.10,
    ),
    (
        3,
        "Governing Law",
        "This Agreement is governed by the laws of the State of California.",
        _AXIS_GOVLAW,
        -0.10,
    ),
    (
        3,
        "Return or Destruction of Materials",
        "Upon termination, all copies shall be destroyed and destruction certified.",
        _AXIS_RETURN,
        -0.10,
    ),
    (
        3,
        "Remedies",
        "Each party consents to injunctive relief for breach, without posting bond.",
        _AXIS_REMEDIES,
        -0.10,
    ),
    (
        3,
        "Reverse Engineering Prohibition",
        "The Receiving Party shall not reverse-engineer, decompile, or disassemble any Confidential Information.",
        _AXIS_REVERSE_ENG,
        0.00,
    ),
    # NDA 4 — Gamma <-> Helix
    (
        4,
        "Term of Agreement",
        "This Agreement expires one (1) year after the Effective Date.",
        _AXIS_TERM,
        0.15,
    ),
    (
        4,
        "Definition of Confidential Information",
        "Confidential Information includes oral and written disclosures with no marking requirement.",
        _AXIS_DEFINITION,
        0.15,
    ),
    (
        4,
        "Standard of Care",
        "The Receiving Party shall protect the Confidential Information with the highest degree of commercial care reasonable under the circumstances.",
        _AXIS_CARE,
        0.15,
    ),
    (
        4,
        "Survival of Trade Secrets",
        "Trade secret obligations survive for three (3) years post-termination.",
        _AXIS_SURVIVAL,
        -0.10,
    ),
    (
        4,
        "Permitted Disclosures",
        "Disclosure is limited to employees with a need to know.",
        _AXIS_PERMITTED,
        0.15,
    ),
    (
        4,
        "Governing Law",
        "This Agreement is governed by the laws of the Commonwealth of Massachusetts.",
        _AXIS_GOVLAW,
        0.15,
    ),
    (
        4,
        "Return or Destruction of Materials",
        "The Receiving Party shall promptly return all Confidential Information upon expiration.",
        _AXIS_RETURN,
        0.15,
    ),
    # Drift singleton: semantically a Remedies clause, but labeled and
    # phrased differently. Its vector sits at cosine ~0.82 to the
    # Remedies centroid — under the 0.85 merge bar, at/above the 0.80
    # fold floor. Pre-DE-308 this became an 11th standalone position.
    (
        4,
        "Injunctive Relief",
        "The parties stipulate that breach causes irreparable harm warranting injunctive relief.",
        _AXIS_REMEDIES,
        0.62,
    ),
    # NDA 5 — Indigo <-> Juniper
    (
        5,
        "Term and Termination",
        "This Agreement remains in force for four (4) years.",
        _AXIS_TERM,
        0.05,
    ),
    (
        5,
        "Definition of Confidential Information",
        "Confidential Information includes oral disclosures confirmed in writing within thirty (30) days.",
        _AXIS_DEFINITION,
        0.05,
    ),
    (
        5,
        "Standard of Care",
        "The Receiving Party agrees to use reasonable care to prevent unauthorized use or disclosure.",
        _AXIS_CARE,
        0.05,
    ),
    (
        5,
        "Trade Secret Survival",
        "Obligations with respect to trade secrets survive indefinitely.",
        _AXIS_SURVIVAL,
        0.05,
    ),
    (
        5,
        "Permitted Disclosures",
        "Disclosure is permitted to employees, advisors, and contractors under written confidentiality obligations.",
        _AXIS_PERMITTED,
        0.05,
    ),
    (
        5,
        "Governing Law",
        "This Agreement is governed by the laws of the State of Washington.",
        _AXIS_GOVLAW,
        0.05,
    ),
    (
        5,
        "Return or Destruction of Materials",
        "All Confidential Information shall be returned or destroyed at the Disclosing Party's election.",
        _AXIS_RETURN,
        0.05,
    ),
    (
        5,
        "Remedies",
        "The Disclosing Party may seek specific performance and injunctive relief for any breach.",
        _AXIS_REMEDIES,
        0.05,
    ),
]

# The five README variant axes, as predicates over lowercased cluster labels.
_AXIS_LABEL_PREDICATES: Final[dict[str, Any]] = {
    "Term": lambda label: "term" in label and "survival" not in label,
    "Definition of Confidential Information": lambda label: "definition" in label,
    "Standard of Care": lambda label: "care" in label,
    "Survival of Trade Secrets": lambda label: "survival" in label or "trade secret" in label,
    "Permitted Disclosures": lambda label: "disclosur" in label,
}


def _corpus_clauses() -> list[ClauseInput]:
    return [
        ClauseInput(
            document_id=uuid.UUID(int=doc),
            issue=issue,
            clause_text=text,
        )
        for doc, issue, text, _axis, _angle in _CORPUS
    ]


def _corpus_vectors() -> list[list[float]]:
    return [_axis_vector(axis, angle) for _doc, _issue, _text, axis, angle in _CORPUS]


@dataclass
class _StubEmbeddingGateway:
    """Deterministic embedding stub — one fixture vector per clause, in order."""

    vectors: list[list[float]] = field(default_factory=list)

    async def embeddings(
        self,
        *,
        model: str,
        input_: str | list[str],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        inputs = [input_] if isinstance(input_, str) else input_
        assert len(inputs) == len(self.vectors), "fixture drift: vector count != clause count"
        return {"data": [{"index": i, "embedding": v} for i, v in enumerate(self.vectors)]}


def _cluster_containing(clusters: list[Cluster], clause_text: str) -> Cluster:
    for cluster in clusters:
        if any(member.clause_text == clause_text for member in cluster.member_clauses):
            return cluster
    raise AssertionError(f"no cluster contains clause: {clause_text!r}")


# ---------------------------------------------------------------------------
# The replay
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_corpus_replay_hits_position_target_and_covers_all_five_axes() -> None:
    """Default pipeline settings → 5-10 positions, all five README axes present."""

    gateway = _StubEmbeddingGateway(vectors=_corpus_vectors())
    clusters = await cluster_clauses_by_issue(
        clauses=_corpus_clauses(),
        gateway=gateway,  # type: ignore[arg-type]
    )

    labels = [c.issue_label for c in clusters]
    assert 5 <= len(clusters) <= 10, f"position count {len(clusters)} outside 5-10: {labels}"
    # Pin the exact deterministic outcome so tuning regressions surface loudly:
    # Term, Definition, Standard of Care, Survival, Permitted Disclosures,
    # Governing Law, Return/Destruction, Remedies (incl. folded Injunctive
    # Relief), and the standalone Reverse Engineering outlier.
    assert len(clusters) == 9, f"expected 9 deterministic clusters, got {labels}"

    lowered = [label.lower() for label in labels]
    for axis_name, predicate in _AXIS_LABEL_PREDICATES.items():
        assert any(predicate(label) for label in lowered), (
            f"axis {axis_name!r} missing from cluster labels: {labels}"
        )


@pytest.mark.unit
async def test_corpus_replay_folds_drift_singleton_into_remedies() -> None:
    """The near-miss "Injunctive Relief" singleton lands inside the Remedies cluster."""

    gateway = _StubEmbeddingGateway(vectors=_corpus_vectors())
    clusters = await cluster_clauses_by_issue(
        clauses=_corpus_clauses(),
        gateway=gateway,  # type: ignore[arg-type]
    )
    injunctive_text = (
        "The parties stipulate that breach causes irreparable harm warranting injunctive relief."
    )
    home = _cluster_containing(clusters, injunctive_text)
    assert home.issue_label == "Remedies"
    assert len(home.member_clauses) == 5  # 4 Remedies + 1 folded Injunctive Relief


@pytest.mark.unit
async def test_corpus_replay_keeps_genuine_outlier_standalone() -> None:
    """Fail-closed: the reverse-engineering one-off stays its own position."""

    gateway = _StubEmbeddingGateway(vectors=_corpus_vectors())
    clusters = await cluster_clauses_by_issue(
        clauses=_corpus_clauses(),
        gateway=gateway,  # type: ignore[arg-type]
    )
    outlier_text = (
        "The Receiving Party shall not reverse-engineer, decompile, or disassemble any "
        "Confidential Information."
    )
    home = _cluster_containing(clusters, outlier_text)
    assert home.issue_label == "Reverse Engineering Prohibition"
    assert len(home.member_clauses) == 1


@pytest.mark.unit
async def test_corpus_replay_regression_without_de308_passes_oversegments() -> None:
    """Documents the pre-fix failure mode the DE-308 passes eliminate.

    * Exact-label grouping alone (no centroid merge, no fold): every
      drift label becomes its own position — 15 clusters, blowing the
      10-position ceiling.
    * Centroid merge without the fold pass: drift labels collapse but
      the near-miss "Injunctive Relief" singleton (0.80-0.85 gap)
      still stands — 10 clusters, at the very edge of the target.
    """

    gateway = _StubEmbeddingGateway(vectors=_corpus_vectors())
    exact_match_only = await cluster_clauses_by_issue(
        clauses=_corpus_clauses(),
        gateway=gateway,  # type: ignore[arg-type]
        label_merge_threshold=None,
        min_document_support=1,
    )
    assert len(exact_match_only) == 15

    merge_without_fold = await cluster_clauses_by_issue(
        clauses=_corpus_clauses(),
        gateway=gateway,  # type: ignore[arg-type]
        min_document_support=1,
    )
    assert len(merge_without_fold) == 10
    assert any(c.issue_label == "Injunctive Relief" for c in merge_without_fold)
