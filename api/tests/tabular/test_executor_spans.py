"""OTel span tests for the tabular executor (M3-F2 Task 8).

Tests that ``run_tabular_execution`` emits:
* exactly one ``tabular.execute`` top-level span with
  ``tabular.document_count`` + ``tabular.column_count``.
* at least one ``tabular.cell`` child span with
  ``tabular.document.id`` + ``tabular.column.name``.
* the cell spans are DIRECT CHILDREN of the ``tabular.execute`` span:
  ``cell_span.parent.span_id == exec_span.context.span_id`` — proves
  LangGraph async context propagation works without explicit threading
  of span context through state.

Harness: marked ``@pytest.mark.integration`` — requires Postgres
(DATABASE_URL env var + the session-scoped test_engine / db_session
fixtures from conftest.py). Mirrors the pattern from
:mod:`tests.playbooks.test_executor_spans`.
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
from app.models.tabular import TabularExecution
from app.models.user import User
from app.security import hash_password
from app.tabular.executor import run_tabular_execution

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
# Stub gateway
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
# DB helpers
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
        filename=f"tab-span-{uuid.uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="f" * 64,
        storage_path=f"tab-span/{uuid.uuid4()}",
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


# ---------------------------------------------------------------------------
# Span assertion test
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_executor_emits_tabular_execute_and_cell_spans(
    db_session: AsyncSession,
    span_exporter: InMemorySpanExporter,
) -> None:
    """tabular.execute span + at least one tabular.cell child span are emitted.

    Verifies:
    - exactly one ``tabular.execute`` span with ``tabular.document_count``
      and ``tabular.column_count``.
    - at least one ``tabular.cell`` child span with
      ``tabular.document.id`` and ``tabular.column.name``.
    - each cell span is a DIRECT child of the ``tabular.execute`` span:
      ``cell_span.parent.span_id == exec_span.context.span_id``
      (proves LangGraph async context propagation, not just co-location).
    """
    span_exporter.clear()

    owner = await _make_user(db_session)
    doc_text = (
        "The initial term of this Agreement shall be three (3) years "
        "commencing on the Effective Date."
    )
    doc = await _make_doc(db_session, owner=owner, text=doc_text)

    column_spec = {
        "name": "Contract Term",
        "query": "contract term duration",
        "minimum_inference_tier": None,
        "ensemble_verification": None,
    }

    execution = TabularExecution(
        document_ids=[doc.id],
        columns=[column_spec],
        status="pending",
    )
    db_session.add(execution)
    await db_session.flush()

    cell_payload = {
        "value": "3 years",
        "cited_chunk_indices": [0],
        "confidence": "high",
        "justification": "The clause states 'three (3) years'.",
    }
    gateway = _StubGateway(payloads=[cell_payload])

    await run_tabular_execution(
        db_session,
        execution_id=execution.id,
        gateway=gateway,  # type: ignore[arg-type]
        judge_model="smart",
    )

    spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    # --- top-level span ---
    execute_spans = [s for s in spans if s.name == "tabular.execute"]
    assert len(execute_spans) == 1, (
        f"expected exactly 1 'tabular.execute' span; got {len(execute_spans)}. "
        f"All span names: {span_names}"
    )
    exec_span = execute_spans[0]

    assert exec_span.attributes.get("tabular.document_count") == 1, (
        f"tabular.document_count mismatch: {exec_span.attributes.get('tabular.document_count')!r}"
    )
    assert exec_span.attributes.get("tabular.column_count") == 1, (
        f"tabular.column_count mismatch: {exec_span.attributes.get('tabular.column_count')!r}"
    )

    # --- child cell spans ---
    cell_spans = [s for s in spans if s.name == "tabular.cell"]
    assert len(cell_spans) >= 1, (
        f"expected at least 1 'tabular.cell' span; got {len(cell_spans)}. "
        f"All span names: {span_names}"
    )
    for cell_span in cell_spans:
        assert cell_span.attributes.get("tabular.document.id") is not None, (
            "tabular.document.id attribute missing from cell span"
        )
        assert cell_span.attributes.get("tabular.column.name") is not None, (
            "tabular.column.name attribute missing from cell span"
        )

    # --- strong nesting assertion: cell spans are DIRECT children of exec span ---
    assert exec_span.context is not None
    for cell_span in cell_spans:
        assert cell_span.parent is not None, "tabular.cell span is a root span — nesting broke"
        assert cell_span.parent.span_id == exec_span.context.span_id, (
            f"tabular.cell span.parent.span_id {cell_span.parent.span_id!r} != "
            f"tabular.execute span_id {exec_span.context.span_id!r} — "
            "LangGraph context propagation may be broken"
        )
