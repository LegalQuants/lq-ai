"""Tabular executor node-level helpers — M3-C2.

Unit tests targeting the pure functions that drive the cell-extraction
node and the aggregation node in :mod:`app.tabular.nodes`. Full
end-to-end executor tests (real DB + Document with chunks +
``run_tabular_execution``) live in :mod:`tests.tabular.test_executor`.

The cell-extraction LLM call is exercised with the
:class:`_StubGateway` pattern from :mod:`tests.test_easy_playbook_extractor`
— no live gateway, no live LLM, deterministic payloads queued per call.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.clients.gateway import EnsembleConfig
from app.schemas.tabular import ColumnSpec
from app.tabular.nodes import (
    _assemble_rows,
    _coerce_chunk_indices,
    _coerce_confidence,
    _parse_cell_response,
    _shape_results_payload,
    extract_cell,
)

# ---------------------------------------------------------------------------
# Stub gateway (mirrors tests.test_easy_playbook_extractor._StubGateway)
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
class _StubGateway:
    """Returns a queued list of LLM responses, one per call.

    Each entry is either:
      * ``dict`` — JSON-serialized as the LLM response content;
      * ``str`` — returned verbatim (malformed-JSON tests);
      * ``Exception`` — raised on the call (transport-failure tests).
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


def _chunk(idx: int, content: str = "chunk text") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "chunk_index": idx,
        "content": content,
        "char_offset_start": idx * 100,
        "char_offset_end": idx * 100 + 50,
        "page_start": 1,
    }


# ---------------------------------------------------------------------------
# _parse_cell_response — leniently parse the LLM's structured JSON
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_cell_response_valid_json() -> None:
    """A well-formed JSON object round-trips into a dict."""

    content = '{"value": "5 years", "cited_chunk_indices": [0], "confidence": "high"}'
    parsed = _parse_cell_response(content)
    assert parsed["value"] == "5 years"
    assert parsed["cited_chunk_indices"] == [0]
    assert parsed["confidence"] == "high"


@pytest.mark.unit
def test_parse_cell_response_strips_code_fence() -> None:
    """A ```json …``` code-fenced response is unwrapped."""

    content = '```json\n{"value": "5 years", "confidence": "high"}\n```'
    parsed = _parse_cell_response(content)
    assert parsed["value"] == "5 years"


@pytest.mark.unit
def test_parse_cell_response_malformed_returns_empty_dict() -> None:
    """Malformed JSON returns ``{}`` — the caller treats that as failed."""

    parsed = _parse_cell_response("not even close to JSON")
    assert parsed == {}


@pytest.mark.unit
def test_parse_cell_response_non_object_returns_empty_dict() -> None:
    """A JSON value that isn't an object (list, scalar) returns ``{}``."""

    assert _parse_cell_response("[1, 2, 3]") == {}
    assert _parse_cell_response("42") == {}
    assert _parse_cell_response('"hello"') == {}


# ---------------------------------------------------------------------------
# _coerce_confidence — normalize to high/medium/low/failed
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_coerce_confidence_passes_valid_values() -> None:
    for v in ("high", "medium", "low", "failed"):
        assert _coerce_confidence(v) == v


@pytest.mark.unit
def test_coerce_confidence_defaults_to_low_for_garbage() -> None:
    """Unknown / non-string / wrong-case values default to ``low``.

    The conservative posture mirrors the playbook executor's
    :func:`app.playbooks.nodes._coerce_confidence` — bias toward
    low confidence on uncertainty so the operator sees the
    weakest-signal state rather than the model's stylistic
    self-assessment."""

    assert _coerce_confidence(None) == "low"
    assert _coerce_confidence("HIGH") == "low"
    assert _coerce_confidence(42) == "low"
    assert _coerce_confidence("certain") == "low"


# ---------------------------------------------------------------------------
# _coerce_chunk_indices — filter to valid 0-based ints inside the chunk count
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_coerce_chunk_indices_keeps_valid_ints() -> None:
    assert _coerce_chunk_indices([0, 2, 4], n_chunks=5) == [0, 2, 4]


@pytest.mark.unit
def test_coerce_chunk_indices_filters_out_of_range() -> None:
    """Indices >= n_chunks or < 0 are dropped silently."""

    assert _coerce_chunk_indices([0, 5, -1, 7], n_chunks=3) == [0]


@pytest.mark.unit
def test_coerce_chunk_indices_skips_non_ints() -> None:
    assert _coerce_chunk_indices([0, "1", None, 2.5, 3], n_chunks=5) == [0, 3]


@pytest.mark.unit
def test_coerce_chunk_indices_non_list_returns_empty() -> None:
    assert _coerce_chunk_indices(None, n_chunks=5) == []
    assert _coerce_chunk_indices("not a list", n_chunks=5) == []
    assert _coerce_chunk_indices(42, n_chunks=5) == []


# ---------------------------------------------------------------------------
# extract_cell — single-cell extraction against a stub gateway
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_extract_cell_returns_value_and_chunk_ids_on_happy_path() -> None:
    """A well-formed LLM response populates value + cited chunk IDs."""

    chunks = [_chunk(0, "Term: 5 years"), _chunk(1, "Other text")]
    gateway = _StubGateway(
        payloads=[
            {
                "value": "5 years",
                "cited_chunk_indices": [0],
                "confidence": "high",
                "justification": "stated explicitly",
            }
        ]
    )

    cell = await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="Sample NDA",
        chunks=chunks,
        column=ColumnSpec(name="Term", query="What is the term?"),
    )

    assert cell["value"] == "5 years"
    assert cell["confidence"] == "high"
    assert cell["cited_chunk_ids"] == [chunks[0]["id"]]


@pytest.mark.unit
async def test_extract_cell_tags_request_with_tabular_extraction_purpose() -> None:
    """The cell node sets ``lq_ai_purpose='tabular_extraction'`` on every
    gateway call so M2-E2's per-purpose cost calibration sees the new
    traffic and the cost estimator's rolling average can converge."""

    gateway = _StubGateway(payloads=[{"value": "x", "confidence": "high"}])
    await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="doc",
        chunks=[_chunk(0)],
        column=ColumnSpec(name="A", query="?"),
    )
    assert len(gateway.calls_received) == 1
    request = gateway.calls_received[0]
    assert request.lq_ai_purpose == "tabular_extraction"


@pytest.mark.unit
async def test_extract_cell_forwards_minimum_inference_tier_override() -> None:
    """Per-column ``minimum_inference_tier`` override is forwarded to
    the gateway's tier-floor enforcement (Decision C-1)."""

    gateway = _StubGateway(payloads=[{"value": "x", "confidence": "high"}])
    await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="doc",
        chunks=[_chunk(0)],
        column=ColumnSpec(name="HighStakes", query="?", minimum_inference_tier=4),
    )
    request = gateway.calls_received[0]
    assert request.minimum_inference_tier == 4


@pytest.mark.unit
async def test_extract_cell_marks_failed_on_gateway_error() -> None:
    """Any gateway exception lands as ``confidence='failed'`` + ``error``
    populated (Decision C-10)."""

    gateway = _StubGateway(payloads=[RuntimeError("provider down")])
    cell = await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="doc",
        chunks=[_chunk(0)],
        column=ColumnSpec(name="A", query="?"),
    )
    assert cell["confidence"] == "failed"
    assert cell["value"] is None
    assert cell["error"] is not None and "provider down" in cell["error"]


@pytest.mark.unit
async def test_extract_cell_marks_failed_on_empty_value() -> None:
    """An LLM response with no ``value`` field marks the cell as failed.

    Per Decision C-10, "could not extract" is a distinct UI state from
    "extracted but unverified" — the cell node treats missing value as
    the former."""

    gateway = _StubGateway(payloads=[{"confidence": "high", "cited_chunk_indices": []}])
    cell = await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="doc",
        chunks=[_chunk(0)],
        column=ColumnSpec(name="A", query="?"),
    )
    assert cell["confidence"] == "failed"
    assert cell["value"] is None


@pytest.mark.unit
async def test_extract_cell_with_no_chunks_marks_failed() -> None:
    """A cell with no retrieved chunks short-circuits to failed without
    a gateway call — extracting from an empty corpus is undefined."""

    gateway = _StubGateway()
    cell = await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="doc",
        chunks=[],
        column=ColumnSpec(name="A", query="?"),
    )
    assert cell["confidence"] == "failed"
    assert gateway.calls_received == []


# ---------------------------------------------------------------------------
# extract_cell — Stage-4 ensemble verification (Donna #6)
# ---------------------------------------------------------------------------


def _ensemble_config(
    *,
    n: int = 3,
    aggregation_rule: str = "strict",
    default_enabled: bool = True,
) -> EnsembleConfig:
    """Build a real (frozen) :class:`EnsembleConfig` for the cell-verify path."""

    return EnsembleConfig(
        default_enabled=default_enabled,
        judge_models=tuple(f"judge-{i}" for i in range(n)),
        aggregation_rule=aggregation_rule,  # type: ignore[arg-type]
        max_cost_per_message_usd=0.05,
        envelope_tier=3,
    )


def _extraction_payload(value: str = "Delaware") -> dict[str, Any]:
    return {
        "value": value,
        "cited_chunk_indices": [0],
        "confidence": "high",
        "justification": "stated explicitly",
    }


def _judge_payload(verdict: str) -> dict[str, Any]:
    return {"verdict": verdict, "confidence": "high", "justification": "test"}


@pytest.mark.unit
async def test_extract_cell_ensemble_strict_all_yes_sets_method() -> None:
    """Ensemble config + all judges 'yes' under strict → method='ensemble_strict'.

    The gateway is called once for extraction, then once per judge model
    (verify runs Stage 1+2 first — they miss because the short value never
    equals the concatenated chunk text — then dispatches Stage 4).
    """

    cfg = _ensemble_config(n=3, aggregation_rule="strict")
    chunks = [_chunk(0, "Governing law is the State of Delaware."), _chunk(1, "Other")]
    gateway = _StubGateway(
        payloads=[
            _extraction_payload("Delaware"),
            _judge_payload("yes"),
            _judge_payload("yes"),
            _judge_payload("yes"),
        ]
    )

    cell = await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="NDA",
        chunks=chunks,
        column=ColumnSpec(name="Governing Law", query="What is the governing law?"),
        verify_ensemble_config=cfg,
    )

    assert cell["value"] == "Delaware"
    assert cell["cited_chunk_ids"] == [chunks[0]["id"]]
    assert cell["verification_method"] == "ensemble_strict"
    # 1 extraction + 3 judge calls.
    assert len(gateway.calls_received) == 4
    # The ensemble pass must judge ONLY the cited chunk (index 0), never the
    # uncited chunk ("Other") — the verify document is the concatenation of
    # *cited* chunks, not all retrieved chunks. Inspect a judge call's source.
    judge_source = gateway.calls_received[1].messages[1].content
    assert "Delaware" in judge_source
    assert "Other" not in judge_source


@pytest.mark.unit
async def test_extract_cell_no_ensemble_config_leaves_method_none() -> None:
    """No ensemble config → verification_method is None; gateway called once."""

    gateway = _StubGateway(payloads=[_extraction_payload("Delaware")])
    cell = await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="NDA",
        chunks=[_chunk(0, "Delaware text")],
        column=ColumnSpec(name="Governing Law", query="?"),
    )

    assert cell["value"] == "Delaware"
    assert cell["verification_method"] is None
    # Extraction only — no judge calls.
    assert len(gateway.calls_received) == 1


@pytest.mark.unit
async def test_extract_cell_ensemble_strict_dissent_misses() -> None:
    """Strict rule + a judge 'no' → ensemble MISS → verification_method None,
    but the cell still returns its extracted value (verify failure is not
    a cell failure)."""

    cfg = _ensemble_config(n=3, aggregation_rule="strict")
    gateway = _StubGateway(
        payloads=[
            _extraction_payload("Delaware"),
            _judge_payload("yes"),
            _judge_payload("no"),
            _judge_payload("yes"),
        ]
    )

    cell = await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="NDA",
        chunks=[_chunk(0, "Governing law is the State of Delaware.")],
        column=ColumnSpec(name="Governing Law", query="?"),
        verify_ensemble_config=cfg,
    )

    assert cell["value"] == "Delaware"
    assert cell["confidence"] == "high"
    assert cell["verification_method"] is None


@pytest.mark.unit
async def test_extract_cell_ensemble_judge_failure_keeps_value() -> None:
    """A judge raising / malformed JSON degrades to MISS (verify is robust);
    verification_method is None and the cell value is intact (no crash)."""

    cfg = _ensemble_config(n=2, aggregation_rule="strict")
    gateway = _StubGateway(
        payloads=[
            _extraction_payload("Delaware"),
            RuntimeError("judge down"),
            "not valid json",
        ]
    )

    cell = await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="NDA",
        chunks=[_chunk(0, "Governing law is the State of Delaware.")],
        column=ColumnSpec(name="Governing Law", query="?"),
        verify_ensemble_config=cfg,
    )

    assert cell["value"] == "Delaware"
    assert cell["verification_method"] is None


@pytest.mark.unit
async def test_extract_cell_ensemble_on_but_no_cited_chunks_skips_verify() -> None:
    """Ensemble config supplied, but the model cites no (valid) chunk →
    ``verification_method`` stays None and the gateway is called exactly
    once (extraction only). The ``and cited_chunk_ids`` guard in
    ``extract_cell`` skips the verify pass when there is nothing to ground
    the value against, so no judge calls fire."""

    cfg = _ensemble_config(n=3, aggregation_rule="strict")
    # Model returns a value but cites no chunk indices — nothing to verify.
    gateway = _StubGateway(
        payloads=[
            {
                "value": "Delaware",
                "cited_chunk_indices": [],
                "confidence": "high",
                "justification": "no grounding",
            }
        ]
    )

    cell = await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="NDA",
        chunks=[_chunk(0, "Governing law is the State of Delaware.")],
        column=ColumnSpec(name="Governing Law", query="?"),
        verify_ensemble_config=cfg,
    )

    assert cell["value"] == "Delaware"
    assert cell["cited_chunk_ids"] == []
    assert cell["verification_method"] is None
    # Extraction only — the empty-citation guard skips all judge calls.
    assert len(gateway.calls_received) == 1


@pytest.mark.unit
async def test_extract_cell_ensemble_majority_sets_method() -> None:
    """Majority rule + a verified majority of judges → method='ensemble_majority'.

    Exercises the majority aggregation branch through the tabular path
    (the strict branch is covered above). With n=3 and two 'yes' verdicts,
    the strict-majority rule (> n/2) is satisfied and the result verifies
    even though one judge dissented."""

    cfg = _ensemble_config(n=3, aggregation_rule="majority")
    chunks = [_chunk(0, "Governing law is the State of Delaware."), _chunk(1, "Other")]
    gateway = _StubGateway(
        payloads=[
            _extraction_payload("Delaware"),
            _judge_payload("yes"),
            _judge_payload("no"),
            _judge_payload("yes"),
        ]
    )

    cell = await extract_cell(
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
        document_name="NDA",
        chunks=chunks,
        column=ColumnSpec(name="Governing Law", query="What is the governing law?"),
        verify_ensemble_config=cfg,
    )

    assert cell["value"] == "Delaware"
    assert cell["verification_method"] == "ensemble_majority"
    # 1 extraction + 3 judge calls.
    assert len(gateway.calls_received) == 4


# ---------------------------------------------------------------------------
# _assemble_rows + _shape_results_payload — aggregation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_assemble_rows_groups_cells_by_document_in_order() -> None:
    """Rows are emitted in ``document_ids`` order (matches operator
    selection); cells keyed by column name within each row."""

    doc_a = uuid.uuid4()
    doc_b = uuid.uuid4()
    per_cell_results = [
        {
            "document_id": str(doc_a),
            "column_name": "Term",
            "value": "5y",
            "cited_chunk_ids": [],
            "confidence": "high",
            "tier_used": 2,
            "cost_usd": "0.0030",
            "error": None,
        },
        {
            "document_id": str(doc_b),
            "column_name": "Term",
            "value": "3y",
            "cited_chunk_ids": [],
            "confidence": "high",
            "tier_used": 2,
            "cost_usd": "0.0040",
            "error": None,
        },
        {
            "document_id": str(doc_a),
            "column_name": "Survival",
            "value": "perpetual",
            "cited_chunk_ids": [],
            "confidence": "medium",
            "tier_used": 2,
            "cost_usd": "0.0030",
            "error": None,
        },
    ]
    documents = [
        {"id": str(doc_a), "name": "NDA A"},
        {"id": str(doc_b), "name": "NDA B"},
    ]

    rows = _assemble_rows(per_cell_results, documents)

    # Two rows, in documents order.
    assert len(rows) == 2
    assert rows[0]["document_id"] == str(doc_a)
    assert rows[0]["document_name"] == "NDA A"
    assert rows[1]["document_id"] == str(doc_b)

    # Doc A has both columns; Doc B has just Term.
    assert set(rows[0]["cells"].keys()) == {"Term", "Survival"}
    assert rows[0]["cells"]["Term"]["value"] == "5y"
    assert rows[0]["cells"]["Survival"]["value"] == "perpetual"
    assert rows[1]["cells"]["Term"]["value"] == "3y"


@pytest.mark.unit
def test_shape_results_payload_includes_schema_version_and_rows() -> None:
    """The persisted JSONB shape carries a schema-version stamp + rows +
    a summary so the result view can decode it without re-deriving."""

    doc = uuid.uuid4()
    per_cell_results = [
        {
            "document_id": str(doc),
            "column_name": "Term",
            "value": "5y",
            "cited_chunk_ids": [],
            "confidence": "high",
            "tier_used": 2,
            "cost_usd": "0.0030",
            "error": None,
        }
    ]
    documents = [{"id": str(doc), "name": "NDA A"}]

    payload = _shape_results_payload(per_cell_results, documents)

    assert "schema_version" in payload
    assert payload["schema_version"].startswith("m3-c2")
    assert "rows" in payload
    assert len(payload["rows"]) == 1
    assert "summary" in payload
    assert payload["summary"]["total_cells"] == 1
    assert payload["summary"]["failed_cells"] == 0


@pytest.mark.unit
def test_shape_results_payload_counts_failed_cells() -> None:
    """Summary surfaces failed-cell count so the result-view banner can
    flag partial-success runs."""

    doc = uuid.uuid4()
    per_cell_results = [
        {
            "document_id": str(doc),
            "column_name": "A",
            "value": "ok",
            "cited_chunk_ids": [],
            "confidence": "high",
            "tier_used": 2,
            "cost_usd": "0.0030",
            "error": None,
        },
        {
            "document_id": str(doc),
            "column_name": "B",
            "value": None,
            "cited_chunk_ids": [],
            "confidence": "failed",
            "tier_used": None,
            "cost_usd": "0",
            "error": "no chunks retrieved",
        },
    ]
    documents = [{"id": str(doc), "name": "NDA A"}]

    payload = _shape_results_payload(per_cell_results, documents)
    assert payload["summary"]["total_cells"] == 2
    assert payload["summary"]["failed_cells"] == 1
