"""OTel span tests for the playbook executor (M3-F2 Task 7).

Tests that ``run_playbook_execution`` emits:
* exactly one ``playbook.execute`` top-level span with the four
  required attributes (playbook.id, playbook.contract_type,
  position.count, document.id).
* at least one ``playbook.position`` child span carrying
  ``playbook.position.id``.
* all position spans share the same trace_id as the top span —
  proving that LangGraph async context propagation works without
  explicit threading of span context through state.

Harness: the end-to-end executor tests are marked ``@pytest.mark.integration``
and require Postgres (DATABASE_URL env var + the session-scoped test_engine /
db_session fixtures from conftest.py). This file mirrors that approach —
same marker, same fixture chain.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.playbook import Playbook, PlaybookExecution, PlaybookPosition
from app.models.user import User
from app.playbooks.executor import run_playbook_execution
from app.security import hash_password

# ---------------------------------------------------------------------------
# Module-scoped span exporter — same pattern as test_observability_helpers.py
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


# ---------------------------------------------------------------------------
# Stub gateway (minimal copy of the one in test_executor.py)
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
    payloads: list[dict[str, Any]] = field(default_factory=list)

    async def chat_completion(self, request: Any) -> _StubResponse:
        if not self.payloads:
            return _StubResponse(choices=[_StubChoice(message=_StubMessage(content=""))])
        payload = self.payloads.pop(0)
        return _StubResponse(
            choices=[_StubChoice(message=_StubMessage(content=json.dumps(payload)))]
        )


# ---------------------------------------------------------------------------
# DB helpers (mirrors test_executor.py helpers exactly)
# ---------------------------------------------------------------------------


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


async def _make_doc(db: AsyncSession, *, owner: User, text: str) -> Document:
    f = FileModel(
        owner_id=owner.id,
        filename=f"span-test-{uuid.uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="e" * 64,
        storage_path=f"span-test/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()
    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=len(text),
        normalized_content=text,
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()
    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=text,
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=len(text),
    )
    db.add(chunk)
    await db.flush()
    return doc


async def _make_playbook(db: AsyncSession) -> Playbook:
    pb = Playbook(name="Span Test Playbook", contract_type="NDA")
    db.add(pb)
    await db.flush()
    pos = PlaybookPosition(
        playbook_id=pb.id,
        issue="Confidentiality",
        standard_language="The Receiving Party shall hold Confidential Information in confidence.",
        severity_if_missing="high",
        detection_keywords=["confidence", "Confidential"],
        detection_examples=[],
        redline_strategy="Tighten the clause.",
        fallback_tiers=[],
        position_order=0,
    )
    db.add(pos)
    await db.flush()
    return pb


# ---------------------------------------------------------------------------
# Span assertion test
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_executor_emits_playbook_execute_and_position_spans(
    db_session: AsyncSession,
    span_exporter: InMemorySpanExporter,
) -> None:
    """playbook.execute span + at least one playbook.position child span are emitted.

    Verifies:
    - exactly one ``playbook.execute`` span with the four required attributes.
    - at least one ``playbook.position`` child span with ``playbook.position.id``.
    - all spans share the same trace_id (LangGraph async context propagation works).
    """
    span_exporter.clear()

    owner = await _make_user(db_session)
    doc_text = (
        "Section 1. The Receiving Party shall hold Confidential Information "
        "in confidence and not disclose it to any third party."
    )
    doc = await _make_doc(db_session, owner=owner, text=doc_text)
    playbook = await _make_playbook(db_session)

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
                "matched_text": "The Receiving Party shall hold Confidential Information in confidence",
                "cited_chunk_indices": [0],
                "justification": "The clause matches the standard.",
            }
        ]
    )

    await run_playbook_execution(
        db_session,
        execution_id=execution.id,
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
    )

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    # --- top-level span ---
    execute_spans = [s for s in spans if s.name == "playbook.execute"]
    assert len(execute_spans) == 1, (
        f"expected exactly 1 'playbook.execute' span; got {len(execute_spans)}. "
        f"All span names: {span_names}"
    )
    exec_span = execute_spans[0]

    assert str(exec_span.attributes.get("playbook.id")) == str(playbook.id), (
        f"playbook.id mismatch: {exec_span.attributes.get('playbook.id')!r}"
    )
    assert exec_span.attributes.get("playbook.contract_type") == "NDA", (
        f"playbook.contract_type mismatch: {exec_span.attributes.get('playbook.contract_type')!r}"
    )
    assert exec_span.attributes.get("position.count") == 1, (
        f"position.count mismatch: {exec_span.attributes.get('position.count')!r}"
    )
    assert str(exec_span.attributes.get("document.id")) == str(doc.id), (
        f"document.id mismatch: {exec_span.attributes.get('document.id')!r}"
    )

    # --- child position spans ---
    position_spans = [s for s in spans if s.name == "playbook.position"]
    assert len(position_spans) >= 1, (
        f"expected at least 1 'playbook.position' span; got {len(position_spans)}. "
        f"All span names: {span_names}"
    )
    for pos_span in position_spans:
        assert pos_span.attributes.get("playbook.position.id") is not None, (
            "playbook.position.id attribute missing from position span"
        )

    # --- trace nesting: all spans share the same trace_id ---
    all_trace_ids = {s.context.trace_id for s in spans if s.context is not None}
    assert len(all_trace_ids) == 1, (
        f"spans have {len(all_trace_ids)} distinct trace_ids — LangGraph context "
        f"propagation may be broken: {all_trace_ids}"
    )
    assert exec_span.context is not None
    assert exec_span.context.trace_id in all_trace_ids

    # Stronger than shared-trace: each position span must be an actual child
    # of the playbook.execute span (proves nesting, not just co-location in
    # the same trace). Catches a regression where positions become siblings
    # under a detached root.
    for pos_span in position_spans:
        assert pos_span.parent is not None, "playbook.position span is a root — nesting broke"
        assert pos_span.parent.span_id == exec_span.context.span_id
