"""Tests for ``app.playbooks.easy.assembly`` — M3-A6 Phase 4.

Verifies the assembled :class:`PlaybookCreate` is structurally valid
(every field present, severity within the enum, fallback tiers
ranked correctly) and that deterministic transforms (keyword
derivation, example list construction) behave per spec. LLM content
itself is not asserted — the user-attorney evaluates downstream.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.playbooks.easy.assembly import (
    MAX_KEYWORD_COUNT,
    _derive_examples,
    _derive_keywords,
    assemble_playbook,
)
from app.playbooks.easy.clustering import ClauseInput, Cluster
from app.schemas.playbooks import PlaybookCreate

# ---------------------------------------------------------------------------
# Stub gateway — same shape as the extractor tests' stub
# ---------------------------------------------------------------------------


@dataclass
class _StubMessage:
    content: str


@dataclass
class _StubChoice:
    message: _StubMessage


@dataclass
class _StubResponse:
    choices: list[_StubChoice]


@dataclass
class _StubChatGateway:
    """Queued ``chat_completion`` responses, one per call.

    Entries may be:
      * dict — JSON-serialized as the response content
      * str — returned verbatim
      * Exception — raised on the call
    """

    payloads: list[Any] = field(default_factory=list)
    calls_received: list[Any] = field(default_factory=list)

    async def chat_completion(self, request: Any) -> _StubResponse:
        self.calls_received.append(request)
        if not self.payloads:
            return _StubResponse(choices=[_StubChoice(message=_StubMessage(content=""))])
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            return _StubResponse(choices=[_StubChoice(message=_StubMessage(content=payload))])
        return _StubResponse(
            choices=[_StubChoice(message=_StubMessage(content=json.dumps(payload)))]
        )


def _ci(issue: str, text: str) -> ClauseInput:
    return ClauseInput(document_id=uuid.uuid4(), issue=issue, clause_text=text)


def _cluster(
    *,
    label: str,
    modal_text: str,
    neighbor_texts: list[str],
    members: list[ClauseInput] | None = None,
) -> Cluster:
    modal = _ci(label, modal_text)
    neighbors = [_ci(label, t) for t in neighbor_texts]
    member_list = members if members is not None else [modal, *neighbors]
    return Cluster(
        issue_label=label,
        member_clauses=member_list,
        modal_clause=modal,
        neighbor_clauses=neighbors,
    )


# ---------------------------------------------------------------------------
# Pure-Python helpers (keyword + example derivation)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_derive_keywords_includes_issue_label_tokens_first() -> None:
    keywords = _derive_keywords(
        issue_label="Limitation of Liability",
        clause_texts=[
            "Total liability is capped at fees paid in the prior twelve months.",
        ],
    )
    # Label tokens come first; stop words ("of") dropped; lowercased.
    assert keywords[0] == "limitation"
    assert keywords[1] == "liability"


@pytest.mark.unit
def test_derive_keywords_drops_stopwords_and_short_tokens() -> None:
    keywords = _derive_keywords(
        issue_label="Term",
        clause_texts=["The term is to be three years."],
    )
    # 1-2 char tokens (e.g., "is") and stop words ("the", "to", "be")
    # all dropped; numbers/digits not tokenized.
    assert "the" not in keywords
    assert "is" not in keywords
    assert "be" not in keywords
    assert "to" not in keywords
    assert "term" in keywords
    assert "years" in keywords


@pytest.mark.unit
def test_derive_keywords_dedupes_across_label_and_content() -> None:
    """A token appearing in both label and content appears only once."""

    keywords = _derive_keywords(
        issue_label="Indemnification",
        clause_texts=["Indemnification is mutual for IP claims."],
    )
    assert keywords.count("indemnification") == 1


@pytest.mark.unit
def test_derive_keywords_capped_at_max_count() -> None:
    keywords = _derive_keywords(
        issue_label="A B C",
        clause_texts=["aaa bbb ccc ddd eee fff ggg hhh iii jjj kkk lll mmm nnn"],
    )
    assert len(keywords) <= MAX_KEYWORD_COUNT


@pytest.mark.unit
def test_derive_examples_modal_first_then_neighbors() -> None:
    cluster = _cluster(
        label="Term",
        modal_text="Three years.",
        neighbor_texts=["Five years.", "Perpetual."],
    )
    examples = _derive_examples(cluster=cluster)
    assert examples == ["Three years.", "Five years.", "Perpetual."]


# ---------------------------------------------------------------------------
# Assembly — empty cluster list
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_empty_clusters_returns_valid_playbook_no_positions() -> None:
    gateway = _StubChatGateway()
    playbook = await assemble_playbook(
        clusters=[],
        name="Empty playbook",
        contract_type="NDA",
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert isinstance(playbook, PlaybookCreate)
    assert playbook.name == "Empty playbook"
    assert playbook.positions == []
    # No LLM calls when there are no clusters.
    assert gateway.calls_received == []


# ---------------------------------------------------------------------------
# Assembly — happy path with one cluster, two neighbors
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_one_cluster_with_two_neighbors_produces_one_position_with_two_tiers() -> None:
    cluster = _cluster(
        label="Limitation of Liability",
        modal_text="Total liability is capped at fees paid in the prior twelve months.",
        neighbor_texts=[
            "Liability uncapped; consequential damages excluded.",
            "Two-year cap on total liability.",
        ],
    )
    gateway = _StubChatGateway(
        payloads=[
            # Describe-position call.
            {
                "description": "Caps the vendor's total liability at recent fees paid.",
                "redline_strategy": "Negotiate toward a 12-month fees-paid cap; reject uncapped clauses.",
                "severity_if_missing": "high",
            },
            # Tier 1 describe call.
            {"description": "No cap — full uncapped liability."},
            # Tier 2 describe call.
            {"description": "Two-year cap instead of twelve months."},
        ]
    )
    playbook = await assemble_playbook(
        clusters=[cluster],
        name="My MSA Playbook",
        contract_type="MSA-SaaS",
        gateway=gateway,  # type: ignore[arg-type]
    )

    # PlaybookCreate validates structurally.
    assert playbook.name == "My MSA Playbook"
    assert playbook.contract_type == "MSA-SaaS"
    assert len(playbook.positions) == 1

    position = playbook.positions[0]
    assert position.issue == "Limitation of Liability"
    assert (
        position.standard_language
        == "Total liability is capped at fees paid in the prior twelve months."
    )
    assert position.severity_if_missing == "high"
    assert position.description == "Caps the vendor's total liability at recent fees paid."
    assert "12-month" in position.redline_strategy
    assert position.position_order == 0

    # Both fallback tiers landed, ranked 1 and 2.
    assert len(position.fallback_tiers) == 2
    assert position.fallback_tiers[0].rank == 1
    assert position.fallback_tiers[0].description == "No cap — full uncapped liability."
    assert (
        position.fallback_tiers[0].language == "Liability uncapped; consequential damages excluded."
    )
    assert position.fallback_tiers[1].rank == 2
    assert position.fallback_tiers[1].description == "Two-year cap instead of twelve months."

    # detection_examples: modal first, then both neighbors.
    assert position.detection_examples[0] == cluster.modal_clause.clause_text
    assert len(position.detection_examples) == 3

    # detection_keywords: label tokens first.
    assert position.detection_keywords[0] == "limitation"
    assert position.detection_keywords[1] == "liability"

    # LLM was called 3 times (1 describe + 2 tier).
    assert len(gateway.calls_received) == 3


# ---------------------------------------------------------------------------
# Assembly — multi-cluster ordering preserved
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_multi_cluster_position_order_assigned_in_input_order() -> None:
    c1 = _cluster(label="Term", modal_text="3 years.", neighbor_texts=[])
    c2 = _cluster(label="Governing Law", modal_text="Delaware.", neighbor_texts=[])
    c3 = _cluster(label="Audit Rights", modal_text="Quarterly.", neighbor_texts=[])
    gateway = _StubChatGateway(
        payloads=[
            # One describe-position call per cluster; no tier calls (no neighbors).
            {
                "description": "Term description",
                "redline_strategy": "rs",
                "severity_if_missing": "medium",
            },
            {
                "description": "Gov law description",
                "redline_strategy": "rs",
                "severity_if_missing": "low",
            },
            {
                "description": "Audit description",
                "redline_strategy": "rs",
                "severity_if_missing": "medium",
            },
        ]
    )
    playbook = await assemble_playbook(
        clusters=[c1, c2, c3],
        name="My Playbook",
        contract_type="NDA",
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert [p.issue for p in playbook.positions] == ["Term", "Governing Law", "Audit Rights"]
    assert [p.position_order for p in playbook.positions] == [0, 1, 2]


# ---------------------------------------------------------------------------
# Assembly — defensive defaults on LLM failures
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_describe_position_llm_failure_uses_defensive_defaults() -> None:
    """Gateway transport failure → empty description, empty redline, severity=medium."""

    cluster = _cluster(label="Term", modal_text="One year.", neighbor_texts=[])
    gateway = _StubChatGateway(payloads=[ConnectionError("boom")])
    playbook = await assemble_playbook(
        clusters=[cluster],
        name="Defaults playbook",
        contract_type="NDA",
        gateway=gateway,  # type: ignore[arg-type]
    )
    position = playbook.positions[0]
    assert position.description == ""
    assert position.redline_strategy == ""
    # Severity defaults to "medium" per the prompt's "bias toward medium" guidance.
    assert position.severity_if_missing == "medium"


@pytest.mark.unit
async def test_describe_position_invalid_severity_normalized_to_medium() -> None:
    cluster = _cluster(label="Term", modal_text="One year.", neighbor_texts=[])
    gateway = _StubChatGateway(
        payloads=[
            {
                "description": "An over-eager LLM emitted 'extreme' as severity.",
                "redline_strategy": "rs",
                "severity_if_missing": "extreme",
            }
        ]
    )
    playbook = await assemble_playbook(
        clusters=[cluster],
        name="Coerced playbook",
        contract_type="NDA",
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert playbook.positions[0].severity_if_missing == "medium"


@pytest.mark.unit
async def test_describe_position_malformed_json_uses_defaults() -> None:
    cluster = _cluster(label="Term", modal_text="One year.", neighbor_texts=[])
    gateway = _StubChatGateway(payloads=["not valid json {["])
    playbook = await assemble_playbook(
        clusters=[cluster],
        name="Malformed playbook",
        contract_type="NDA",
        gateway=gateway,  # type: ignore[arg-type]
    )
    position = playbook.positions[0]
    assert position.description == ""
    assert position.severity_if_missing == "medium"


@pytest.mark.unit
async def test_describe_tier_failure_uses_default_description() -> None:
    cluster = _cluster(
        label="Term",
        modal_text="One year.",
        neighbor_texts=["Five years."],
    )
    gateway = _StubChatGateway(
        payloads=[
            # Describe-position call succeeds.
            {
                "description": "Term description",
                "redline_strategy": "rs",
                "severity_if_missing": "low",
            },
            # Tier description call fails.
            ConnectionError("tier describe failed"),
        ]
    )
    playbook = await assemble_playbook(
        clusters=[cluster],
        name="Tier-default playbook",
        contract_type="NDA",
        gateway=gateway,  # type: ignore[arg-type]
    )
    position = playbook.positions[0]
    assert len(position.fallback_tiers) == 1
    # Defensive default kicks in.
    assert position.fallback_tiers[0].description == "Variant clause; review during playbook edit."
    # Language still set to the neighbor's verbatim text.
    assert position.fallback_tiers[0].language == "Five years."


# ---------------------------------------------------------------------------
# Assembly — request shape carries audit attribution
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_describe_position_request_carries_audit_purpose() -> None:
    cluster = _cluster(label="Term", modal_text="One year.", neighbor_texts=[])
    gateway = _StubChatGateway(
        payloads=[
            {
                "description": "ok",
                "redline_strategy": "ok",
                "severity_if_missing": "low",
            }
        ]
    )
    await assemble_playbook(
        clusters=[cluster],
        name="Audit playbook",
        contract_type="NDA",
        gateway=gateway,  # type: ignore[arg-type]
    )
    request = gateway.calls_received[0]
    assert request.lq_ai_purpose == "playbook_easy_assemble_describe_position"
    assert request.anonymize is False
    # `temperature` is intentionally omitted — Opus 4.x reasoning models
    # rejected it as of 2026-05; the gateway only forwards non-None.
    assert request.temperature is None


@pytest.mark.unit
async def test_describe_tier_request_carries_distinct_audit_purpose() -> None:
    cluster = _cluster(
        label="Term",
        modal_text="One year.",
        neighbor_texts=["Five years."],
    )
    gateway = _StubChatGateway(
        payloads=[
            {
                "description": "Term description",
                "redline_strategy": "rs",
                "severity_if_missing": "low",
            },
            {"description": "Longer-term variant."},
        ]
    )
    await assemble_playbook(
        clusters=[cluster],
        name="Audit playbook",
        contract_type="NDA",
        gateway=gateway,  # type: ignore[arg-type]
    )
    # Two requests: describe-position then describe-tier; distinct purposes.
    assert gateway.calls_received[0].lq_ai_purpose == "playbook_easy_assemble_describe_position"
    assert gateway.calls_received[1].lq_ai_purpose == "playbook_easy_assemble_describe_tier"


# ---------------------------------------------------------------------------
# Assembly — output validates against PlaybookCreate's schema
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_assembled_playbook_validates_as_playbook_create() -> None:
    """End-to-end: the returned object passes a fresh ``PlaybookCreate.model_validate``.

    This is the structural-correctness gate per the M3-A6 quality bar:
    whatever clusters + LLM emit, the result must always be a valid
    ``PlaybookCreate``.
    """

    cluster = _cluster(
        label="Indemnification",
        modal_text="Mutual indemnification scoped to IP and breach.",
        neighbor_texts=["One-way indemnification toward customer only."],
    )
    gateway = _StubChatGateway(
        payloads=[
            {
                "description": "Both parties indemnify for IP infringement and breach.",
                "redline_strategy": "Push for mutuality; accept one-way only with offsetting concessions.",
                "severity_if_missing": "critical",
            },
            {"description": "Asymmetric — one-way toward customer."},
        ]
    )
    playbook = await assemble_playbook(
        clusters=[cluster],
        name="Validation playbook",
        contract_type="MSA-SaaS",
        gateway=gateway,  # type: ignore[arg-type]
    )
    # Round-trip via .model_dump() + .model_validate to ensure the
    # object is fully serializable (mirrors what the POST endpoint does
    # at body parse time).
    dumped = playbook.model_dump()
    PlaybookCreate.model_validate(dumped)
