"""End-to-end acceptance test for per-column tabular ensemble verification
(Donna #6, part 3).

Acceptance: in a completed execution, an ensemble column's cells carry an
``ensemble_*`` verification signal while a non-ensemble column on the same run
does not.

Where the Task-1 unit tests drove ``extract_cell`` directly with an explicit
``verify_ensemble_config``, this exercises the FULL wiring:
``run_tabular_execution`` → ``make_extract_cells_node`` resolving each column's
*effective* ``ensemble_verification`` flag AND fetching the ensemble config from
the (stub) gateway → the Stage-4 ensemble verify pass → the persisted
``results`` JSON → the read-path projection that surfaces
``verification_method`` on each cell's citations.

The stub gateway is content-sniffing (branches on the request rather than
relying on call ordering): a judge call (``lq_ai_purpose == 'judge_paraphrase'``)
returns a "yes" verdict; any other call returns the extraction JSON. That keeps
the stub robust to the executor's ``for document: for column:`` walk regardless
of how many extraction / judge calls each cell makes.

Harness: ``@pytest.mark.integration`` — requires Postgres (the session-scoped
``db_session`` fixture from conftest auto-migrates the throwaway pgvector DB).
Mirrors the seeding pattern from :mod:`tests.tabular.test_executor_spans`.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import EnsembleConfig
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.tabular import TabularExecution
from app.models.user import User
from app.security import hash_password
from app.tabular.executor import run_tabular_execution

# ---------------------------------------------------------------------------
# Stub gateway response shapes
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


_EXTRACTION_PAYLOAD = {
    "value": "3 years",
    "cited_chunk_indices": [0],
    "confidence": "high",
    "justification": "The clause states 'three (3) years'.",
}

_JUDGE_PAYLOAD = {
    "verdict": "yes",
    "confidence": "high",
    "justification": "The source supports the claim.",
}


@dataclass
class _StubGateway:
    """Content-sniffing stub.

    A judge call (``lq_ai_purpose == 'judge_paraphrase'``) returns a "yes"
    verdict; every other call returns the extraction JSON. Records how many
    judge calls were issued so the test can assert the non-ensemble column
    made none of them.
    """

    judge_calls: int = 0
    extraction_calls: int = 0

    async def chat_completion(
        self, request: Any, *, request_id: str | None = None
    ) -> _StubResponse:
        if getattr(request, "lq_ai_purpose", None) == "judge_paraphrase":
            self.judge_calls += 1
            payload = _JUDGE_PAYLOAD
        else:
            self.extraction_calls += 1
            payload = _EXTRACTION_PAYLOAD
        return _StubResponse(
            choices=[_StubChoice(message=_StubMessage(content=json.dumps(payload)))]
        )

    async def get_citation_engine_ensemble_config(self) -> EnsembleConfig:
        return EnsembleConfig(
            default_enabled=False,
            judge_models=("j1", "j2", "j3"),
            aggregation_rule="strict",
            max_cost_per_message_usd=10.0,
            envelope_tier=3,
        )


# ---------------------------------------------------------------------------
# DB helpers (mirror tests.tabular.test_executor_spans)
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
        filename=f"tab-ens-{uuid.uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="f" * 64,
        storage_path=f"tab-ens/{uuid.uuid4()}",
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
# Acceptance test
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_per_column_ensemble_gating_end_to_end(db_session: AsyncSession) -> None:
    """One ensemble + one non-ensemble column on the same run.

    Proves (through the executor/node wiring, not a direct ``extract_cell``
    call):

    * persisted ``results``: the ensemble column's cell carries
      ``verification_method == 'ensemble_strict'``; the non-ensemble column's
      cell carries no verification signal (``None``). Both cells still have
      their ``value`` + ``cited_chunk_ids``.
    * read path: each ensemble cell citation carries
      ``verification_method == 'ensemble_strict'`` while the non-ensemble
      cell's citations carry ``None``.
    * the non-ensemble column issued NO judge calls.
    """

    owner = await _make_user(db_session)
    doc_text = (
        "The initial term of this Agreement shall be three (3) years "
        "commencing on the Effective Date."
    )
    doc = await _make_doc(db_session, owner=owner, text=doc_text)

    # Column order matters: the executor walks for document: for column:.
    # A = ensemble (1 extraction + 3 judge calls), B = non-ensemble
    # (1 extraction, 0 judge calls).
    columns = [
        {
            "name": "A",
            "query": "contract term duration",
            "minimum_inference_tier": None,
            "ensemble_verification": True,
        },
        {
            "name": "B",
            "query": "contract term duration",
            "minimum_inference_tier": None,
            "ensemble_verification": False,
        },
    ]

    execution = TabularExecution(
        document_ids=[doc.id],
        columns=columns,
        status="pending",
    )
    db_session.add(execution)
    await db_session.flush()

    execution_id = execution.id

    gateway = _StubGateway()
    await run_tabular_execution(
        db_session,
        execution_id=execution_id,
        gateway=gateway,  # type: ignore[arg-type]
    )

    # --- persisted-results assertion ---------------------------------------
    # The aggregate node commits (expiring ``execution``); reload a fresh row.
    refreshed = (
        await db_session.execute(
            select(TabularExecution).where(TabularExecution.id == execution_id)
        )
    ).scalar_one()

    assert refreshed.status == "completed", f"unexpected status: {refreshed.status!r}"
    results = refreshed.results
    assert results is not None
    rows = results["rows"]
    assert len(rows) == 1
    cells = rows[0]["cells"]

    ensemble_cell = cells["A"]
    plain_cell = cells["B"]

    # Ensemble column → ensemble_strict; both cells still extracted a value
    # with grounding chunks.
    assert ensemble_cell["verification_method"] == "ensemble_strict", (
        f"ensemble cell verification_method: {ensemble_cell['verification_method']!r}"
    )
    assert ensemble_cell["value"] == "3 years"
    assert ensemble_cell["cited_chunk_ids"], "ensemble cell lost its cited_chunk_ids"

    # Non-ensemble column → no verification signal.
    assert plain_cell.get("verification_method") is None, (
        f"non-ensemble cell carried a verification signal: "
        f"{plain_cell.get('verification_method')!r}"
    )
    assert plain_cell["value"] == "3 years"
    assert plain_cell["cited_chunk_ids"], "non-ensemble cell lost its cited_chunk_ids"

    # The non-ensemble column must not have issued judge calls. One ensemble
    # cell x 3 judge models = exactly 3 judge calls total.
    assert gateway.judge_calls == 3, (
        f"expected exactly 3 judge calls (1 ensemble cell x 3 judges); got {gateway.judge_calls}"
    )

    # --- read-path assertion -----------------------------------------------
    # Build the response through the SAME projection the GET endpoint uses
    # (_to_response synthesizes citations + mirrors verification_method;
    # _enrich_cell_citations resolves navigation fields without disturbing it).
    from app.api.tabular import _enrich_cell_citations, _to_response

    response = await _to_response(db_session, refreshed)
    await _enrich_cell_citations(db_session, response)

    assert response.results is not None
    resp_row = response.results.rows[0]
    resp_ensemble = resp_row.cells["A"]
    resp_plain = resp_row.cells["B"]

    assert resp_ensemble.citations, "ensemble cell produced no citations on read path"
    for citation in resp_ensemble.citations:
        assert citation.verification_method == "ensemble_strict", (
            f"ensemble citation verification_method: {citation.verification_method!r}"
        )

    assert resp_plain.citations, "non-ensemble cell produced no citations on read path"
    for citation in resp_plain.citations:
        assert citation.verification_method is None, (
            f"non-ensemble citation carried a verification signal: {citation.verification_method!r}"
        )
