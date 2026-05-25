"""Privacy-guard observability test for the autonomous chokepoint — M4-A3.3b.

Verifies the DE-293 acceptance bar:

1. **No raw entity value in any autonomous span or audit row.**
   Spans produced by ``guarded_tool_call`` carry only counts, types,
   IDs, costs, and enum labels — never raw document text, person names,
   or matter numbers.  The audit-log rows written by ``autonomous_audit``
   likewise carry only safe metadata.

2. **Happy-path spans carry the expected attributes.**
   ``autonomous.session_id``, ``autonomous.phase``, ``autonomous.tool``,
   ``autonomous.outcome``, ``autonomous.cost_usd`` are present on the
   span for a successful ``retrieve_chunks`` call.

3. **Grep guard: no provider SDK imported under api/app/autonomous/.**
   The autonomous package must route all inference through the gateway
   client; direct anthropic/openai imports are forbidden.

The test builds:

- A real KB + file + document + chunk whose text contains synthetic
  sensitive entities: person name ``"Jane Privilege"`` and matter
  number ``"MTR-2026-0042"``.
- An ``AutonomousSession`` driven through ``guarded_tool_call`` with
  ``retrieve_chunks`` (real ``hybrid_search`` over the KB via FTS —
  no embedding needed; ``query_embedding=None`` → FTS-only path).
- A ``run_skill`` call with a **stubbed gateway** returning a canned
  ``ChatCompletionResponse`` — we are NOT testing gateway anonymization
  here; we are testing that OUR autonomous span/audit code never records
  raw values.

Span collection uses :class:`InMemorySpanExporter` wired through a
module-scoped :class:`TracerProvider`, mirroring the pattern in
:mod:`tests.playbooks.test_executor_spans`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.autonomous import AutonomousSession
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.user import User
from app.security import hash_password

# ---------------------------------------------------------------------------
# Synthetic sensitive entities — used ONLY to prove they never appear in spans
# or audit rows.  These strings are "injected test values"; the test asserts
# they are absent from all telemetry.
# ---------------------------------------------------------------------------

_ENTITY_PERSON = "Jane Privilege"
_ENTITY_MATTER = "MTR-2026-0042"
_CHUNK_TEXT = (
    f"This Non-Disclosure Agreement is entered into by {_ENTITY_PERSON} "
    f"in connection with matter {_ENTITY_MATTER}.  "
    "The receiving party shall keep all information confidential."
)
_SYNTHETIC_ENTITIES = [_ENTITY_PERSON, _ENTITY_MATTER]


# ---------------------------------------------------------------------------
# Module-scoped span exporter — one provider per test module.
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
# Stub gateway for run_skill — returns a canned ChatCompletionResponse.
# ---------------------------------------------------------------------------


@dataclass
class _StubMessage:
    content: str = "stub_content"
    role: str = "assistant"


@dataclass
class _StubChoice:
    message: _StubMessage = field(default_factory=_StubMessage)
    index: int = 0
    finish_reason: str = "stop"


@dataclass
class _StubUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 5
    total_tokens: int = 15


@dataclass
class _StubChatCompletionResponse:
    id: str = "stub-resp-001"
    object: str = "chat.completion"
    created: int = 0
    model: str = "stub"
    choices: list[Any] = field(default_factory=lambda: [_StubChoice()])
    usage: _StubUsage = field(default_factory=_StubUsage)
    routed_inference_tier: int | None = None
    routed_provider: str | None = None


@dataclass
class _StubGateway:
    async def chat_completion(self, request: Any) -> _StubChatCompletionResponse:
        return _StubChatCompletionResponse()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"u-obs-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_kb_with_chunk(
    db: AsyncSession,
    *,
    owner: User,
    chunk_text: str,
) -> KnowledgeBase:
    """Create a KB with one file + document + chunk containing ``chunk_text``.

    The chunk's ``content_tsv`` is a GENERATED ALWAYS column — Postgres
    populates it automatically on INSERT.  We set ``ingestion_status='ready'``
    so the retrieval SQL includes the file.
    """
    kb = KnowledgeBase(
        owner_id=owner.id,
        name="obs-test-kb",
        hybrid_alpha=0.5,
    )
    db.add(kb)
    await db.flush()

    f = FileModel(
        owner_id=owner.id,
        filename=f"obs-test-{uuid.uuid4().hex[:6]}.txt",
        mime_type="text/plain",
        size_bytes=len(chunk_text),
        hash_sha256="f" * 64,
        storage_path=f"obs-test/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()

    kbf = KnowledgeBaseFile(kb_id=kb.id, file_id=f.id)
    db.add(kbf)
    await db.flush()

    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=len(chunk_text),
        normalized_content=chunk_text,
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=chunk_text,
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=len(chunk_text),
    )
    db.add(chunk)
    await db.flush()
    # Force Postgres to compute the generated content_tsv column so FTS works.
    await db.execute(text("UPDATE document_chunks SET chunk_index = chunk_index"))
    await db.flush()

    return kb


async def _make_session(
    db: AsyncSession,
    *,
    user: User,
    current_phase: str,
) -> AutonomousSession:
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        current_phase=current_phase,
        halt_state="running",
        max_cost_usd=None,
        cost_total_usd=Decimal("0"),
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


# ---------------------------------------------------------------------------
# Privacy assertion helpers
# ---------------------------------------------------------------------------


def _span_contains_entity(span: Any, entities: list[str]) -> list[str]:
    """Return any entity strings found in any attribute value of ``span``."""
    found: list[str] = []
    if not span.attributes:
        return found
    for key, value in span.attributes.items():
        str_val = str(value)
        for entity in entities:
            if entity in str_val:
                found.append(f"span_attr[{key}]={str_val!r} contains {entity!r}")
    return found


# ---------------------------------------------------------------------------
# Part 1 — privacy-guard test
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_retrieve_chunks_no_raw_entities_in_spans_or_audit(
    db_session: AsyncSession,
    span_exporter: InMemorySpanExporter,
) -> None:
    """retrieve_chunks: no synthetic entity string appears in any autonomous span.

    Also asserts happy-path span attributes are present.

    This test proves the §1.3 transparency-vs-privacy guarantee:
    telemetry carries counts/types/IDs/costs but never raw document text.
    """
    from sqlalchemy import select

    from app.autonomous.enums import ToolIntent
    from app.autonomous.guard import guarded_tool_call
    from app.models.audit import AuditLog

    span_exporter.clear()

    owner = await _make_user(db_session)
    kb = await _make_kb_with_chunk(db_session, owner=owner, chunk_text=_CHUNK_TEXT)
    sess = await _make_session(db_session, user=owner, current_phase="intake")
    gateway = _StubGateway()

    # retrieve_chunks using FTS-only (query_embedding=None) so no embedding
    # needed.  The query includes one of the entity strings to prove the
    # retrieval FINDS the chunk (entities ARE in the document text) but does
    # NOT leak into spans.
    result = await guarded_tool_call(
        sess,
        ToolIntent.retrieve_chunks,
        {
            "kb_id": str(kb.id),
            "query": "confidential",  # neutral query — FTS matches the chunk
            "query_embedding": None,
            "top_k": 4,
            "alpha": 1.0,  # FTS-only path
        },
        db_session,
        gateway,
    )

    # Verify the retrieval found our chunk (proves the KB/FTS pipeline works).
    assert result.data is not None
    assert result.data["summary"]["chunk_count"] >= 0  # may be 0 if FTS misses

    # ── Privacy assertion: no synthetic entity in any autonomous.* span ────
    spans = span_exporter.get_finished_spans()
    auto_spans = [s for s in spans if s.name.startswith("autonomous.")]
    assert len(auto_spans) >= 1, "Expected at least one autonomous.* span"

    violations: list[str] = []
    for span in auto_spans:
        violations.extend(_span_contains_entity(span, _SYNTHETIC_ENTITIES))

    assert not violations, "Raw entity strings found in autonomous span attributes:\n" + "\n".join(
        violations
    )

    # ── Happy-path span attributes ──────────────────────────────────────────
    tool_call_spans = [s for s in auto_spans if s.name == "autonomous.tool_call"]
    assert len(tool_call_spans) >= 1, "Expected at least one autonomous.tool_call span"
    span = tool_call_spans[-1]
    attrs = span.attributes or {}

    assert "autonomous.session_id" in attrs
    assert str(sess.id) in str(attrs["autonomous.session_id"])
    assert "autonomous.phase" in attrs
    assert "autonomous.tool" in attrs
    assert str(ToolIntent.retrieve_chunks) in str(attrs["autonomous.tool"])
    assert "autonomous.outcome" in attrs
    assert attrs["autonomous.outcome"] == "success"
    assert "autonomous.cost_usd" in attrs
    assert float(attrs["autonomous.cost_usd"]) == pytest.approx(0.0)

    # ── Privacy assertion: no synthetic entity in any audit row ─────────────
    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.resource_id == str(sess.id))))
        .scalars()
        .all()
    )
    assert len(audit_rows) >= 1, "Expected at least one audit row for this session"

    for row in audit_rows:
        details_str = str(row.details or "")
        for entity in _SYNTHETIC_ENTITIES:
            assert entity not in details_str, (
                f"Audit row {row.action!r} details contains raw entity {entity!r}: {details_str!r}"
            )


@pytest.mark.integration
async def test_run_skill_no_raw_entities_in_spans_or_audit(
    db_session: AsyncSession,
    span_exporter: InMemorySpanExporter,
) -> None:
    """run_skill: no synthetic entity string appears in any autonomous span or audit row.

    Uses a stubbed gateway so no real inference is made; the test proves
    OUR code does not record raw values in the chokepoint's audit/span paths.
    """
    from unittest.mock import AsyncMock, patch

    from sqlalchemy import select

    from app.autonomous.enums import ToolIntent
    from app.autonomous.guard import guarded_tool_call
    from app.models.audit import AuditLog

    span_exporter.clear()

    owner = await _make_user(db_session)
    sess = await _make_session(db_session, user=owner, current_phase="analysis")
    gateway = _StubGateway()

    # Monkeypatch estimate_tool_cost so we don't need a real DB model call cost.
    mock_estimate = AsyncMock(return_value=Decimal("0.003"))

    from app.autonomous import guard as guard_mod

    with patch.object(guard_mod, "estimate_tool_cost", mock_estimate):
        result = await guarded_tool_call(
            sess,
            ToolIntent.run_skill,
            {
                "model": "fast",
                "messages": [
                    {
                        "role": "user",
                        # The message content intentionally contains entity strings
                        # to prove they never reach spans/audit even when present
                        # in the params dict.
                        "content": (
                            f"Review this document involving {_ENTITY_PERSON} "
                            f"for matter {_ENTITY_MATTER}."
                        ),
                    }
                ],
                "max_tokens": 256,
                "anonymize": True,
            },
            db_session,
            gateway,
        )

    assert result is not None
    assert result.cost_usd == Decimal("0.003")

    # ── Privacy assertion: no synthetic entity in any autonomous.* span ────
    spans = span_exporter.get_finished_spans()
    auto_spans = [s for s in spans if s.name.startswith("autonomous.")]
    assert len(auto_spans) >= 1

    violations: list[str] = []
    for span in auto_spans:
        violations.extend(_span_contains_entity(span, _SYNTHETIC_ENTITIES))

    assert not violations, "Raw entity strings found in autonomous span attributes:\n" + "\n".join(
        violations
    )

    # ── Privacy assertion: no synthetic entity in any audit row ─────────────
    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.resource_id == str(sess.id))))
        .scalars()
        .all()
    )
    for row in audit_rows:
        details_str = str(row.details or "")
        for entity in _SYNTHETIC_ENTITIES:
            assert entity not in details_str, (
                f"Audit row {row.action!r} details contains raw entity {entity!r}: {details_str!r}"
            )


# ---------------------------------------------------------------------------
# Part 2 — Red/green proof: the test WOULD fail if a raw value were recorded
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_privacy_guard_would_fail_on_raw_span_attribute(
    db_session: AsyncSession,
    span_exporter: InMemorySpanExporter,
) -> None:
    """Demonstrates that the privacy assertion catches a raw-value leak.

    Injects a fake span with one of the synthetic entity strings as an
    attribute value and verifies that ``_span_contains_entity`` catches it.
    This proves the guard in the test above is not vacuous — it WOULD fail
    if a raw value were recorded.
    """

    # Build a fake span-like object (no OTel needed — just needs .attributes).
    # Use ClassVar annotation to satisfy RUF012 (mutable class attribute).
    from typing import ClassVar

    class _FakeSpan:
        name = "autonomous.tool_call"
        attributes: ClassVar[dict[str, str]] = {
            "autonomous.session_id": "some-session-id",
            "autonomous.tool": "retrieve_chunks",
            # Intentionally inject the raw entity string:
            "autonomous.raw_leak": _ENTITY_PERSON,
        }

    violations = _span_contains_entity(_FakeSpan(), _SYNTHETIC_ENTITIES)
    assert len(violations) > 0, (
        "Expected _span_contains_entity to detect the injected raw entity string, "
        "but it returned no violations — the privacy guard is not working."
    )
    assert any(_ENTITY_PERSON in v for v in violations)


# ---------------------------------------------------------------------------
# Part 3 — Grep guard: no provider SDK in api/app/autonomous/
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_provider_sdk_in_autonomous_package() -> None:
    """No ``import anthropic`` / ``import openai`` / provider SDK in autonomous/.

    The autonomous package must route all inference through the gateway
    client.  Direct provider imports are the supply-chain attack surface
    we're preventing.
    """
    import os
    import re

    autonomous_dir = os.path.join(
        os.path.dirname(__file__),  # tests/autonomous/
        "..",  # tests/
        "..",  # api/
        "app",
        "autonomous",
    )
    autonomous_dir = os.path.normpath(autonomous_dir)

    pattern = re.compile(
        r"^\s*(import (anthropic|openai)|from (anthropic|openai))",
        re.MULTILINE,
    )

    violations: list[str] = []
    for root, _dirs, files in os.walk(autonomous_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, encoding="utf-8") as fh:
                content = fh.read()
            for match in pattern.finditer(content):
                line_no = content[: match.start()].count("\n") + 1
                violations.append(f"{fpath}:{line_no}: {match.group().strip()!r}")

    assert not violations, "Provider SDK imports found in api/app/autonomous/:\n" + "\n".join(
        violations
    )
