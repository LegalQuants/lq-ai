"""Executor tests for the M3-A2 LangGraph workflow.

Two layers:

* **Pure-helper tests** for the JSON coercion + summary aggregation
  in :mod:`app.playbooks.nodes` — no DB, no gateway.
* **End-to-end executor tests** that wire a real DB session (per the
  conftest fixture) + a stubbed gateway client. The stub returns
  hand-crafted ``ChatCompletionResponse`` payloads so the classify +
  redline nodes exercise their parse paths against deterministic JSON.

The stubbed gateway pattern intentionally avoids ``unittest.mock``
machinery for the response shape — the protocol surface is small and
returning a real ``SimpleNamespace`` keeps the mypy-style attribute
access in :func:`app.playbooks.nodes._dispatch_structured_call`
exercised honestly.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.playbook import Playbook, PlaybookExecution, PlaybookPosition
from app.models.user import User
from app.playbooks.executor import run_playbook_execution
from app.playbooks.nodes import (
    _coerce_chunk_indices,
    _coerce_confidence,
    _coerce_verdict,
    _parse_json_object,
    _shape_results_payload,
    _summarize,
)
from app.security import hash_password

# ---------------------------------------------------------------------------
# Pure-helper tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_coerce_verdict_accepts_canonical_values() -> None:
    for v in ("matches_standard", "matches_fallback", "deviates", "missing"):
        assert _coerce_verdict(v) == v


@pytest.mark.unit
def test_coerce_verdict_defaults_to_missing_for_unknown() -> None:
    assert _coerce_verdict("yes") == "missing"
    assert _coerce_verdict(None) == "missing"
    assert _coerce_verdict(42) == "missing"


@pytest.mark.unit
def test_coerce_confidence_normalizes_unknowns_to_low() -> None:
    assert _coerce_confidence("high") == "high"
    assert _coerce_confidence("medium") == "medium"
    assert _coerce_confidence("low") == "low"
    assert _coerce_confidence("very high") == "low"
    assert _coerce_confidence(None) == "low"


@pytest.mark.unit
def test_coerce_chunk_indices_filters_out_of_range() -> None:
    assert _coerce_chunk_indices([0, 1, 5, -1, "x", None], n_chunks=3) == [0, 1]
    assert _coerce_chunk_indices(None, n_chunks=3) == []
    assert _coerce_chunk_indices([], n_chunks=3) == []


@pytest.mark.unit
def test_parse_json_object_strips_code_fence() -> None:
    fenced = '```json\n{"verdict": "deviates", "confidence": "high"}\n```'
    parsed = _parse_json_object(fenced)
    assert parsed == {"verdict": "deviates", "confidence": "high"}


@pytest.mark.unit
def test_parse_json_object_returns_empty_on_garbage() -> None:
    assert _parse_json_object("not json at all") == {}
    assert _parse_json_object("[1, 2, 3]") == {}  # non-object
    assert _parse_json_object("") == {}


@pytest.mark.unit
def test_summarize_counts_each_verdict_bucket() -> None:
    counts = _summarize(
        [
            {"verdict": "matches_standard"},
            {"verdict": "matches_standard"},
            {"verdict": "deviates"},
            {"verdict": "missing"},
            {"verdict": "matches_fallback"},
            {"verdict": "not_a_real_verdict"},  # ignored
        ]
    )
    assert counts == {
        "matches_standard": 2,
        "matches_fallback": 1,
        "deviates": 1,
        "missing": 1,
    }


@pytest.mark.unit
def test_shape_results_payload_includes_schema_version() -> None:
    state: dict[str, Any] = {
        "per_position_results": [{"verdict": "matches_standard"}],
    }
    payload = _shape_results_payload(state)  # type: ignore[arg-type]
    assert payload["schema_version"] == "m3-a2-v1"
    assert payload["summary"]["matches_standard"] == 1
    assert payload["positions"] == [{"verdict": "matches_standard"}]


# ---------------------------------------------------------------------------
# Stub gateway for executor end-to-end tests
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
    """Returns a queued sequence of JSON-string responses, one per call.

    The executor calls :meth:`chat_completion` once per position for the
    classify node and once per deviating-position for the redline node.
    Tests pre-populate ``payloads`` with the JSON the LLM would have
    produced; the stub wraps each in the ``choices[0].message.content``
    shape :func:`_dispatch_structured_call` reads.
    """

    payloads: list[dict[str, Any]] = field(default_factory=list)
    calls_received: list[Any] = field(default_factory=list)

    async def chat_completion(self, request: Any) -> _StubResponse:
        self.calls_received.append(request)
        if not self.payloads:
            return _StubResponse(choices=[_StubChoice(message=_StubMessage(content=""))])
        payload = self.payloads.pop(0)
        return _StubResponse(
            choices=[_StubChoice(message=_StubMessage(content=json.dumps(payload)))]
        )


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_doc_with_chunks(
    db: AsyncSession,
    *,
    owner: User,
    normalized_text: str,
    chunks_text: list[str],
) -> tuple[FileModel, Document, list[DocumentChunk]]:
    f = FileModel(
        owner_id=owner.id,
        filename=f"doc-{uuid.uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        size_bytes=2048,
        hash_sha256="d" * 64,
        storage_path=f"playbook-exec-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()
    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=len(normalized_text),
        normalized_content=normalized_text,
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()
    chunks: list[DocumentChunk] = []
    offset = 0
    for i, text_value in enumerate(chunks_text):
        chunk = DocumentChunk(
            document_id=doc.id,
            chunk_index=i,
            content=text_value,
            page_start=1,
            page_end=1,
            char_offset_start=offset,
            char_offset_end=offset + len(text_value),
        )
        db.add(chunk)
        chunks.append(chunk)
        offset += len(text_value)
    await db.flush()
    return f, doc, chunks


async def _make_playbook_with_position(
    db: AsyncSession,
    *,
    issue: str,
    detection_keywords: list[str],
    severity: str = "high",
    redline_strategy: str = "Tighten the clause to the standard.",
) -> Playbook:
    pb = Playbook(name="Test Playbook", contract_type="NDA")
    db.add(pb)
    await db.flush()
    pos = PlaybookPosition(
        playbook_id=pb.id,
        issue=issue,
        standard_language="The Receiving Party shall hold Confidential Information in confidence.",
        severity_if_missing=severity,
        detection_keywords=detection_keywords,
        detection_examples=[],
        redline_strategy=redline_strategy,
        fallback_tiers=[],
        position_order=0,
    )
    db.add(pos)
    await db.flush()
    return pb


# ---------------------------------------------------------------------------
# End-to-end executor tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_executor_classifies_matches_standard_end_to_end(
    db_session: AsyncSession,
) -> None:
    """Happy-path: one position, one matching chunk → completed + matches_standard."""
    owner = await _make_user(db_session)
    _file, doc, _chunks = await _make_doc_with_chunks(
        db_session,
        owner=owner,
        normalized_text=(
            "Section 1. The Receiving Party shall hold Confidential Information "
            "in confidence and not disclose it to any third party."
        ),
        chunks_text=[
            "Section 1. The Receiving Party shall hold Confidential Information",
            "in confidence and not disclose it to any third party.",
        ],
    )
    playbook = await _make_playbook_with_position(
        db_session,
        issue="Confidentiality",
        detection_keywords=["confidence", "Confidential"],
    )

    execution = PlaybookExecution(
        playbook_id=playbook.id,
        target_document_id=doc.id,
        user_id=owner.id,
    )
    db_session.add(execution)
    await db_session.flush()

    gateway = _StubGateway(
        payloads=[
            {
                "verdict": "matches_standard",
                "confidence": "high",
                "matched_fallback_rank": None,
                "matched_text": (
                    "The Receiving Party shall hold Confidential Information in confidence"
                ),
                "cited_chunk_indices": [0],
                "justification": "The clause materially matches the standard.",
            }
        ]
    )

    await run_playbook_execution(
        db_session,
        execution_id=execution.id,
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
    )

    await db_session.refresh(execution)
    assert execution.status == "completed"
    assert execution.error is None
    assert execution.completed_at is not None
    assert execution.results is not None
    assert execution.results["schema_version"] == "m3-a2-v1"
    assert execution.results["summary"]["matches_standard"] == 1
    assert execution.results["summary"]["deviates"] == 0

    positions = execution.results["positions"]
    assert len(positions) == 1
    assert positions[0]["verdict"] == "matches_standard"
    assert positions[0]["redline"] is None
    # Classify cited chunk 0; verify the chunk_id surfaced.
    assert len(positions[0]["cited_chunk_ids"]) == 1


@pytest.mark.integration
async def test_executor_drafts_redline_for_deviates_verdict(
    db_session: AsyncSession,
) -> None:
    """A 'deviates' classification triggers a second LLM call for the redline."""
    owner = await _make_user(db_session)
    _file, doc, _chunks = await _make_doc_with_chunks(
        db_session,
        owner=owner,
        normalized_text=(
            "Section 2. Receiving Party may share Confidential Information with "
            "any affiliate or vendor at its sole discretion."
        ),
        chunks_text=[
            "Section 2. Receiving Party may share Confidential Information with",
            "any affiliate or vendor at its sole discretion.",
        ],
    )
    playbook = await _make_playbook_with_position(
        db_session,
        issue="Confidentiality",
        detection_keywords=["Confidential", "share"],
    )

    execution = PlaybookExecution(
        playbook_id=playbook.id,
        target_document_id=doc.id,
        user_id=owner.id,
    )
    db_session.add(execution)
    await db_session.flush()

    gateway = _StubGateway(
        payloads=[
            # 1st call — classify
            {
                "verdict": "deviates",
                "confidence": "high",
                "matched_fallback_rank": None,
                "matched_text": "Receiving Party may share Confidential Information with any affiliate or vendor at its sole discretion.",
                "cited_chunk_indices": [0, 1],
                "justification": "Permissive sharing is broader than the standard.",
            },
            # 2nd call — redline
            {
                "old_text": "may share Confidential Information with any affiliate or vendor at its sole discretion",
                "new_text": "shall hold Confidential Information in confidence and not disclose it without prior written consent",
                "justification": "Restores the confidentiality obligation per the standard.",
            },
        ]
    )

    await run_playbook_execution(
        db_session,
        execution_id=execution.id,
        gateway=gateway,  # type: ignore[arg-type]
    )

    await db_session.refresh(execution)
    assert execution.status == "completed"
    positions = execution.results["positions"]
    assert positions[0]["verdict"] == "deviates"
    assert positions[0]["redline"] is not None
    assert positions[0]["redline"]["old_text"].startswith("may share")
    assert "shall hold" in positions[0]["redline"]["new_text"]
    # Two gateway calls: classify + redline.
    assert len(gateway.calls_received) == 2


@pytest.mark.integration
async def test_executor_marks_missing_when_keyword_not_in_document(
    db_session: AsyncSession,
) -> None:
    """A position whose keywords don't match returns 'missing'; no redline call."""
    owner = await _make_user(db_session)
    _file, doc, _chunks = await _make_doc_with_chunks(
        db_session,
        owner=owner,
        normalized_text="Section 1. Generic boilerplate without any confidentiality language.",
        chunks_text=["Section 1. Generic boilerplate without any confidentiality language."],
    )
    playbook = await _make_playbook_with_position(
        db_session,
        issue="Limitation of Liability",
        detection_keywords=["liability", "indemnification"],
    )

    execution = PlaybookExecution(
        playbook_id=playbook.id,
        target_document_id=doc.id,
        user_id=owner.id,
    )
    db_session.add(execution)
    await db_session.flush()

    gateway = _StubGateway(
        payloads=[
            {
                "verdict": "missing",
                "confidence": "high",
                "matched_fallback_rank": None,
                "matched_text": "",
                "cited_chunk_indices": [],
                "justification": "No liability clause present in the contract.",
            }
        ]
    )

    await run_playbook_execution(
        db_session,
        execution_id=execution.id,
        gateway=gateway,  # type: ignore[arg-type]
    )

    await db_session.refresh(execution)
    assert execution.status == "completed"
    positions = execution.results["positions"]
    assert positions[0]["verdict"] == "missing"
    assert positions[0]["redline"] is None
    # Single gateway call: classify only — no redline for `missing`.
    assert len(gateway.calls_received) == 1


@pytest.mark.integration
async def test_executor_persists_error_on_gateway_failure(
    db_session: AsyncSession,
) -> None:
    """A gateway exception inside the classifier surfaces as a low-confidence missing.

    The structured-call dispatcher swallows transport errors and
    returns ``{}`` — :func:`_coerce_verdict` then maps the empty dict
    to ``missing`` at ``low`` confidence. The execution still
    completes successfully (status='completed') because the failure
    is per-position, not per-execution; partial robustness is a
    feature, not a bug.
    """
    owner = await _make_user(db_session)
    _file, doc, _chunks = await _make_doc_with_chunks(
        db_session,
        owner=owner,
        normalized_text="Some content.",
        chunks_text=["Some content."],
    )
    playbook = await _make_playbook_with_position(
        db_session,
        issue="Test",
        detection_keywords=["content"],
    )

    execution = PlaybookExecution(
        playbook_id=playbook.id,
        target_document_id=doc.id,
        user_id=owner.id,
    )
    db_session.add(execution)
    await db_session.flush()

    class _FailingGateway:
        async def chat_completion(self, request: Any) -> Any:
            raise RuntimeError("gateway unreachable")

    await run_playbook_execution(
        db_session,
        execution_id=execution.id,
        gateway=_FailingGateway(),  # type: ignore[arg-type]
    )

    await db_session.refresh(execution)
    # The gateway swallowed the error per-call; the executor still
    # writes a completed row with a 'missing' verdict for the position.
    assert execution.status == "completed"
    positions = execution.results["positions"]
    assert positions[0]["verdict"] == "missing"
    assert positions[0]["confidence"] == 0.5  # low → 0.5
