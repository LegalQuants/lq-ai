"""DE-309 — offset-bearing cell provenance: locate + mint unit tests.

Covers the executor-side half of DE-309:

* ``extract_cell`` locates the extracted value verbatim inside each
  cited chunk's canonical text and emits in-flight ``cell_citations``
  entries with chunk-local char offsets + the cascade's method /
  confidence (``exact_match`` / 1.0 for a verbatim hit).
* Fail-closed: an unlocatable value emits NO entry — the cell renders
  unverified read-side; a fake offset row is never minted.
* ``_mint_cell_citation_rows`` projects the in-flight entries into
  :class:`TabularCellCitation` ORM rows keyed by
  ``(execution_id, document_id, column_name)`` and skips malformed
  entries without sinking the aggregate write.
* The persisted results JSONB shape is unchanged — ``cell_citations``
  is stripped before persistence (export stays byte-identical).

The HTTP read-side half (real ids + offsets served, uuid5-bridge
fallback for pre-migration executions) lives in
:mod:`tests.test_tabular_endpoints`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tabular import TabularCellCitation, TabularExecution
from app.schemas.tabular import ColumnSpec
from app.tabular.nodes import (
    _mint_cell_citation_rows,
    _shape_results_payload,
    extract_cell,
    make_aggregate_node,
)

from .test_nodes import _chunk, _StubGateway


async def _run_extract(
    chunks: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    gateway = _StubGateway(payloads=[payload])
    return await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="Sample NDA",
        chunks=chunks,
        column=ColumnSpec(name="Term", query="What is the term?"),
    )


# ---------------------------------------------------------------------------
# extract_cell — cell_citations minting (locate)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_extract_cell_mints_offset_citation_for_verbatim_value() -> None:
    """A value that appears verbatim in the cited chunk yields one
    ``cell_citations`` entry whose offsets re-derive the value from the
    chunk content and whose method comes from the cascade."""

    content = "The term of this Agreement is five (5) years from the Effective Date."
    chunks = [_chunk(0, content)]
    cell = await _run_extract(
        chunks,
        {"value": "five (5) years", "cited_chunk_indices": [0], "confidence": "high"},
    )

    assert cell["value"] == "five (5) years"
    citations = cell["cell_citations"]
    assert len(citations) == 1
    cit = citations[0]
    assert cit["chunk_id"] == chunks[0]["id"]
    start, end = cit["source_offset_start"], cit["source_offset_end"]
    assert content[start:end] == "five (5) years"
    assert cit["verification_method"] == "exact_match"
    assert cit["verification_confidence"] == 1.0


@pytest.mark.unit
async def test_extract_cell_unlocatable_value_mints_no_citation() -> None:
    """Fail-closed: a paraphrased value absent from the cited chunk's
    text yields NO cell_citations entry (never a fake offset row).
    The cell itself is untouched — value / chunk ids / confidence stand."""

    chunks = [_chunk(0, "The term of this Agreement is five (5) years.")]
    cell = await _run_extract(
        chunks,
        {"value": "5 years", "cited_chunk_indices": [0], "confidence": "medium"},
    )

    assert cell["value"] == "5 years"
    assert cell["cited_chunk_ids"] == [chunks[0]["id"]]
    assert cell["cell_citations"] == []


@pytest.mark.unit
async def test_extract_cell_locates_only_in_chunks_containing_value() -> None:
    """A cell citing two chunks mints a row only for the chunk(s) the
    value actually locates in."""

    hit = "Governing law: the State of Delaware shall govern."
    miss = "This section covers notices and assignment."
    chunks = [_chunk(0, hit), _chunk(1, miss)]
    cell = await _run_extract(
        chunks,
        {"value": "Delaware", "cited_chunk_indices": [0, 1], "confidence": "high"},
    )

    citations = cell["cell_citations"]
    assert [c["chunk_id"] for c in citations] == [chunks[0]["id"]]
    start, end = citations[0]["source_offset_start"], citations[0]["source_offset_end"]
    assert hit[start:end] == "Delaware"


@pytest.mark.unit
async def test_extract_cell_duplicate_cited_indices_mint_once() -> None:
    """Duplicate cited chunk indices dedupe to one provenance entry."""

    chunks = [_chunk(0, "Payment is due within thirty (30) days.")]
    cell = await _run_extract(
        chunks,
        {
            "value": "thirty (30) days",
            "cited_chunk_indices": [0, 0],
            "confidence": "high",
        },
    )
    assert len(cell["cell_citations"]) == 1


@pytest.mark.unit
async def test_failed_cell_carries_empty_cell_citations() -> None:
    """The failed-cell shape carries ``cell_citations: []`` so the
    aggregate node's minting loop needs no special-casing."""

    gateway = _StubGateway(payloads=["not json at all"])
    cell = await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="Sample NDA",
        chunks=[_chunk(0, "text")],
        column=ColumnSpec(name="Term", query="?"),
    )
    assert cell["confidence"] == "failed"
    assert cell["cell_citations"] == []


# ---------------------------------------------------------------------------
# _mint_cell_citation_rows — in-flight → ORM projection
# ---------------------------------------------------------------------------


def _in_flight_cell(
    doc_id: uuid.UUID,
    column: str,
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "document_id": str(doc_id),
        "column_name": column,
        "value": "x",
        "cited_chunk_ids": [c.get("chunk_id") for c in citations],
        "confidence": "high",
        "tier_used": 2,
        "cost_usd": "0",
        "error": None,
        "verification_method": None,
        "cell_citations": citations,
    }


@pytest.mark.unit
def test_mint_cell_citation_rows_keys_rows_to_cells() -> None:
    execution_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    per_cell_results = [
        _in_flight_cell(
            doc_id,
            "Term",
            [
                {
                    "chunk_id": str(chunk_id),
                    "source_offset_start": 4,
                    "source_offset_end": 18,
                    "verification_method": "exact_match",
                    "verification_confidence": 1.0,
                }
            ],
        ),
        _in_flight_cell(doc_id, "Survival", []),  # ungrounded cell → no rows
    ]

    rows = _mint_cell_citation_rows(execution_id, per_cell_results)

    assert len(rows) == 1
    row = rows[0]
    assert row.execution_id == execution_id
    assert row.document_id == doc_id
    assert row.column_name == "Term"
    assert row.chunk_id == chunk_id
    assert row.source_offset_start == 4
    assert row.source_offset_end == 18
    assert row.verification_method == "exact_match"
    assert row.verification_confidence == Decimal("1.0")


@pytest.mark.unit
def test_mint_cell_citation_rows_skips_malformed_entries() -> None:
    """A malformed in-flight entry is skipped; well-formed siblings
    still mint (one bad citation must not sink the aggregate write)."""

    execution_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    per_cell_results = [
        _in_flight_cell(
            doc_id,
            "Term",
            [
                {"chunk_id": "not-a-uuid", "source_offset_start": 0},  # malformed
                {
                    "chunk_id": str(uuid.uuid4()),
                    "source_offset_start": 0,
                    "source_offset_end": 5,
                    "verification_method": "exact_match",
                    "verification_confidence": None,
                },
            ],
        ),
        # Cell missing document_id/column_name keys entirely → skipped.
        {"cell_citations": [{"chunk_id": str(uuid.uuid4())}]},
    ]

    rows = _mint_cell_citation_rows(execution_id, per_cell_results)
    assert len(rows) == 1
    assert rows[0].verification_confidence is None


@pytest.mark.unit
def test_results_payload_does_not_persist_cell_citations() -> None:
    """``cell_citations`` is in-flight only: the persisted results JSONB
    (and therefore the export surface) is byte-identical to the
    pre-DE-309 shape."""

    doc_id = uuid.uuid4()
    per_cell_results = [
        _in_flight_cell(
            doc_id,
            "Term",
            [
                {
                    "chunk_id": str(uuid.uuid4()),
                    "source_offset_start": 0,
                    "source_offset_end": 5,
                    "verification_method": "exact_match",
                    "verification_confidence": 1.0,
                }
            ],
        )
    ]
    payload = _shape_results_payload(per_cell_results, [{"id": str(doc_id), "name": "NDA"}])
    cell = payload["rows"][0]["cells"]["Term"]
    assert "cell_citations" not in cell
    assert set(cell.keys()) == {
        "value",
        "cited_chunk_ids",
        "confidence",
        "tier_used",
        "cost_usd",
        "error",
        "verification_method",
    }


# ---------------------------------------------------------------------------
# make_aggregate_node — extract → aggregate minting wiring (real DB)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_aggregate_node_persists_located_cell_citations_end_to_end(
    db_session: AsyncSession,
) -> None:
    """The aggregate node's ``db.add_all(_mint_cell_citation_rows(...))``
    wiring persists real :class:`TabularCellCitation` rows.

    Drives ``make_aggregate_node`` exactly as the executor builds it
    (``make_aggregate_node(db)``) against the real session — no DB
    mocks — with in-flight cells produced by the real ``extract_cell``
    (keyed with ``document_id`` / ``column_name`` the way the
    extract-cells map node keys them). One cell locates its value
    (carries ``cell_citations``); one does not. Exactly one row must
    land, bound to the located cell's ``(document_id, column_name)``,
    with the cited chunk's real id, offsets that re-derive the value,
    and a CHECK-allowed ``verification_method``. The results JSONB
    must land stamped with the post-F1 minting-vintage
    ``schema_version`` — guarding the read side's fail-closed
    discriminator end to end.
    """

    doc_id = uuid.uuid4()
    execution = TabularExecution(
        user_id=None,
        skill_name=None,
        status="running",
        document_ids=[doc_id],
        columns=[
            {"name": "Term", "query": "What is the term?"},
            {"name": "Survival", "query": "What survives termination?"},
        ],
    )
    db_session.add(execution)
    await db_session.flush()

    content = "The term of this Agreement is five (5) years from the Effective Date."
    located_chunks = [_chunk(0, content)]
    located = await _run_extract(
        located_chunks,
        {"value": "five (5) years", "cited_chunk_indices": [0], "confidence": "high"},
    )
    # Paraphrased value absent from the cited chunk → no cell_citations.
    unlocated = await _run_extract(
        [_chunk(0, "The term of this Agreement is five (5) years.")],
        {"value": "5 years", "cited_chunk_indices": [0], "confidence": "medium"},
    )
    assert located["cell_citations"] and unlocated["cell_citations"] == []
    # The extract-cells map node keys each cell for the aggregate node.
    located["document_id"] = str(doc_id)
    located["column_name"] = "Term"
    unlocated["document_id"] = str(doc_id)
    unlocated["column_name"] = "Survival"

    aggregate_node = make_aggregate_node(db_session)
    await aggregate_node(
        {
            "execution_id": str(execution.id),
            "columns": list(execution.columns),
            "judge_model": "smart",
            "documents": [{"id": str(doc_id), "name": "Sample NDA"}],
            "per_cell_results": [located, unlocated],
            "error": None,
        }
    )

    persisted = (
        (
            await db_session.execute(
                select(TabularCellCitation).where(TabularCellCitation.execution_id == execution.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(persisted) == 1
    row = persisted[0]
    assert row.document_id == doc_id
    assert row.column_name == "Term"
    assert row.chunk_id == uuid.UUID(located_chunks[0]["id"])
    assert content[row.source_offset_start : row.source_offset_end] == "five (5) years"
    assert row.verification_method in {
        "exact_match",
        "tolerant_match",
        "paraphrase_judge",
        "ensemble_strict",
        "ensemble_majority",
    }

    await db_session.refresh(execution)
    assert execution.status == "completed"
    assert execution.results is not None
    assert execution.results["schema_version"] == "m3-c2-v2"
