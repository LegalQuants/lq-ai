"""Tabular wire-schema read-side transforms — M3-C2 / M3-E1.

Regression coverage for the citation read-side projection (F6, found in
the M3-E1 fresh-install verification): the executor persists each cell's
grounding chunks as raw ``cited_chunk_ids: list[str]``, but the API/UI
surface models structured ``Citation`` objects under ``citations``.
Without the :class:`TabularRow` ``model_validator`` that bridges the two,
``CellResult.citations`` deserialized empty on every cell even though the
grounding chunks were recorded — the citation drawer showed nothing.
"""

from __future__ import annotations

import uuid

from app.schemas.tabular import (
    _TABULAR_CITATION_NAMESPACE,
    CellResult,
    TabularResults,
    TabularRow,
)


def _persisted_cell(
    *,
    value: str | None,
    cited_chunk_ids: list[str],
    confidence: str,
    error: str | None = None,
) -> dict[str, object]:
    """Mirror the exact JSONB shape the executor persists per cell."""
    return {
        "value": value,
        "cited_chunk_ids": cited_chunk_ids,
        "confidence": confidence,
        "tier_used": None,
        "cost_usd": "0",
        "error": error,
    }


def test_tabular_row_synthesizes_citations_from_cited_chunk_ids() -> None:
    document_id = uuid.uuid4()
    chunk_a = uuid.uuid4()
    chunk_b = uuid.uuid4()
    row = TabularRow.model_validate(
        {
            "document_id": str(document_id),
            "document_name": "nda-1-acme-beta.pdf",
            "cells": {
                "Term": _persisted_cell(
                    value="3 years",
                    cited_chunk_ids=[str(chunk_a), str(chunk_b)],
                    confidence="high",
                ),
            },
        }
    )

    cell = row.cells["Term"]
    assert len(cell.citations) == 2
    cite_a, cite_b = cell.citations
    assert cite_a.document_id == document_id
    assert cite_a.chunk_id == chunk_a
    assert cite_a.confidence == "high"
    # citation_id is deterministic: uuid5(NS, chunk_id) so the same chunk
    # always maps to the same display id.
    assert cite_a.citation_id == uuid.uuid5(_TABULAR_CITATION_NAMESPACE, str(chunk_a))
    assert cite_b.chunk_id == chunk_b


def test_synthesized_citation_id_is_deterministic() -> None:
    document_id = uuid.uuid4()
    chunk = uuid.uuid4()
    payload = {
        "document_id": str(document_id),
        "document_name": "x.pdf",
        "cells": {
            "Col": _persisted_cell(value="v", cited_chunk_ids=[str(chunk)], confidence="medium")
        },
    }
    first = TabularRow.model_validate(payload).cells["Col"].citations[0].citation_id
    second = TabularRow.model_validate(payload).cells["Col"].citations[0].citation_id
    assert first == second


def test_failed_cell_with_no_chunks_yields_no_citations() -> None:
    row = TabularRow.model_validate(
        {
            "document_id": str(uuid.uuid4()),
            "document_name": "x.pdf",
            "cells": {
                "Col": _persisted_cell(
                    value=None,
                    cited_chunk_ids=[],
                    confidence="failed",
                    error="no chunks retrieved",
                ),
            },
        }
    )
    assert row.cells["Col"].citations == []


def test_cell_already_carrying_citations_passes_through_untouched() -> None:
    """A future executor that emits real Citation objects must not be
    double-projected away by the chunk-id bridge."""
    document_id = uuid.uuid4()
    citation_id = uuid.uuid4()
    chunk = uuid.uuid4()
    row = TabularRow.model_validate(
        {
            "document_id": str(document_id),
            "document_name": "x.pdf",
            "cells": {
                "Col": {
                    "value": "v",
                    "cited_chunk_ids": [str(uuid.uuid4())],  # should be ignored
                    "citations": [
                        {
                            "citation_id": str(citation_id),
                            "document_id": str(document_id),
                            "chunk_id": str(chunk),
                            "confidence": "high",
                        }
                    ],
                    "confidence": "high",
                    "tier_used": 4,
                    "cost_usd": "0.01",
                    "error": None,
                },
            },
        }
    )
    cell = row.cells["Col"]
    assert len(cell.citations) == 1
    assert cell.citations[0].citation_id == citation_id
    assert cell.citations[0].chunk_id == chunk


def test_full_results_payload_round_trip_surfaces_citations() -> None:
    """The API read path: TabularResults.model_validate over the persisted
    JSONB must surface citations on every grounded cell."""
    document_id = uuid.uuid4()
    chunk = uuid.uuid4()
    results = TabularResults.model_validate(
        {
            "schema_version": 1,
            "rows": [
                {
                    "document_id": str(document_id),
                    "document_name": "nda-1.pdf",
                    "cells": {
                        "Governing Law": _persisted_cell(
                            value="Delaware",
                            cited_chunk_ids=[str(chunk)],
                            confidence="high",
                        ),
                    },
                }
            ],
            "summary": {"total_cells": 1, "failed_cells": 0},
        }
    )
    cell: CellResult = results.rows[0].cells["Governing Law"]
    assert len(cell.citations) == 1
    assert cell.citations[0].chunk_id == chunk
