"""Mid-run ensemble cost ceiling for Tabular Review — DE-331.

Two layers:

* Unit tests for the ceiling math: :func:`_would_exceed_ceiling` (the
  pre-pass projection compared against the confirmed ceiling),
  :func:`_parse_ceiling` (defensive state parsing), the shared per-pass
  estimator :func:`app.tabular.cost.estimate_ensemble_pass_cost_usd`,
  and the additive results-payload / schema fields.
* Integration tests through ``run_tabular_execution`` proving the
  acceptance behavior: a low ceiling lets early ensemble cells verify,
  halts later ones (``verification_method=None``), sets
  ``ensemble_halted_at_ceiling`` + ``ensemble_halted_cells``, and the
  run still COMPLETES (degrade-only); an ample ceiling, a no-ensemble
  run, and a no-ceiling run are all behaviorally unchanged.

Cost determinism: the stub gateway's responses carry no ``cost_estimate``
annotation, so actual extraction spend accumulates as 0 and the halt
point is driven purely by the estimated per-pass cost — cold-start
``DEFAULT_PER_JUDGE_USD`` ($0.005) x 3 judges = $0.015/pass (the judge
cost-estimator cache is invalidated per test so no calibration data
leaks in).

Harness: integration tests are ``@pytest.mark.integration`` — require
Postgres (session-scoped ``db_session`` from conftest auto-migrates the
throwaway pgvector DB). Seeding mirrors
:mod:`tests.tabular.test_ensemble_verification_integration`.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.cost import (
    DEFAULT_PER_JUDGE_USD,
    invalidate_cache as invalidate_judge_cache,
)
from app.clients.gateway import EnsembleConfig
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.tabular import TabularExecution
from app.models.user import User
from app.schemas.tabular import TabularResults
from app.security import hash_password
from app.tabular.cost import estimate_ensemble_pass_cost_usd
from app.tabular.executor import run_tabular_execution
from app.tabular.nodes import (
    _parse_ceiling,
    _shape_results_payload,
    _would_exceed_ceiling,
)

# ---------------------------------------------------------------------------
# Unit tests — ceiling math
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_would_exceed_ceiling_accumulates_estimates() -> None:
    """Projected spend = extraction actual + granted-pass estimates + one
    more pass; halts exactly when the projection crosses the ceiling."""

    per_pass = Decimal("0.015")
    ceiling = Decimal("0.02")

    # First pass: 0 + 0 + 0.015 <= 0.02 → runs.
    assert not _would_exceed_ceiling(
        ceiling=ceiling,
        extraction_spend=Decimal("0"),
        ensemble_spend_estimate=Decimal("0"),
        per_pass_estimate=per_pass,
    )
    # Second pass: 0 + 0.015 + 0.015 = 0.03 > 0.02 → halts.
    assert _would_exceed_ceiling(
        ceiling=ceiling,
        extraction_spend=Decimal("0"),
        ensemble_spend_estimate=per_pass,
        per_pass_estimate=per_pass,
    )


@pytest.mark.unit
def test_would_exceed_ceiling_counts_actual_extraction_spend() -> None:
    """DE-310 actual extraction spend eats into the ensemble headroom."""

    assert _would_exceed_ceiling(
        ceiling=Decimal("0.02"),
        extraction_spend=Decimal("0.01"),
        ensemble_spend_estimate=Decimal("0"),
        per_pass_estimate=Decimal("0.015"),
    )


@pytest.mark.unit
def test_would_exceed_ceiling_exact_boundary_still_runs() -> None:
    """A projection exactly equal to the ceiling does not halt (spend up
    TO the confirmed number is what the operator confirmed)."""

    assert not _would_exceed_ceiling(
        ceiling=Decimal("0.03"),
        extraction_spend=Decimal("0"),
        ensemble_spend_estimate=Decimal("0.015"),
        per_pass_estimate=Decimal("0.015"),
    )


@pytest.mark.unit
def test_parse_ceiling_valid_none_and_garbage() -> None:
    assert _parse_ceiling("0.5000") == Decimal("0.5")
    assert _parse_ceiling(None) is None
    assert _parse_ceiling("not-a-decimal") is None


@pytest.mark.unit
async def test_estimate_ensemble_pass_cost_cold_start_is_judges_times_default() -> None:
    """``db=None`` → per-pass estimate is judge-count x the cold-start
    per-judge default (the same math as the preview's premium)."""

    config = EnsembleConfig(
        default_enabled=False,
        judge_models=("j1", "j2", "j3"),
        aggregation_rule="strict",
        max_cost_per_message_usd=10.0,
        envelope_tier=3,
    )
    assert await estimate_ensemble_pass_cost_usd(None, config) == DEFAULT_PER_JUDGE_USD * 3


# ---------------------------------------------------------------------------
# Unit tests — additive payload / schema fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_shape_results_payload_carries_halt_fields() -> None:
    payload = _shape_results_payload(
        [],
        [],
        ensemble_halted_at_ceiling=True,
        ensemble_halted_cells=7,
    )
    assert payload["ensemble_halted_at_ceiling"] is True
    assert payload["ensemble_halted_cells"] == 7


@pytest.mark.unit
def test_shape_results_payload_defaults_to_no_halt() -> None:
    payload = _shape_results_payload([], [])
    assert payload["ensemble_halted_at_ceiling"] is False
    assert payload["ensemble_halted_cells"] == 0


@pytest.mark.unit
def test_tabular_results_validates_pre_de331_payload_with_defaults() -> None:
    """A persisted payload from before DE-331 (no halt keys) validates
    unchanged, defaulting to the no-halt state."""

    legacy_payload = {
        "schema_version": "m3-c2-v1",
        "rows": [],
        "summary": {"total_cells": 0, "failed_cells": 0},
    }
    results = TabularResults.model_validate(legacy_payload)
    assert results.ensemble_halted_at_ceiling is False
    assert results.ensemble_halted_cells == 0


# ---------------------------------------------------------------------------
# Stub gateway (content-sniffing — mirrors
# tests.tabular.test_ensemble_verification_integration)
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
    """Judge calls (``lq_ai_purpose == 'judge_paraphrase'``) return a
    "yes" verdict; every other call returns the extraction JSON. The
    responses deliberately carry NO ``cost_estimate`` annotation so the
    executor's actual-extraction-spend accumulator stays at 0 and the
    ceiling arithmetic is driven purely by pass estimates."""

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
# DB helpers (mirror tests.tabular.test_ensemble_verification_integration)
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
        filename=f"tab-ceil-{uuid.uuid4().hex[:6]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="f" * 64,
        storage_path=f"tab-ceil/{uuid.uuid4()}",
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


_DOC_TEXT = (
    "The initial term of this Agreement shall be three (3) years commencing on the Effective Date."
)


def _ensemble_columns(n: int, *, ensemble: bool = True) -> list[dict[str, Any]]:
    return [
        {
            "name": f"C{i}",
            "query": "contract term duration",
            "minimum_inference_tier": None,
            "ensemble_verification": ensemble,
        }
        for i in range(n)
    ]


async def _run_execution(
    db: AsyncSession,
    *,
    columns: list[dict[str, Any]],
    confirmed_cost_usd: Decimal | None,
) -> tuple[TabularExecution, _StubGateway]:
    """Seed one doc + one execution, run it, return the refreshed row."""

    invalidate_judge_cache()
    owner = await _make_user(db)
    doc = await _make_doc(db, owner=owner, text=_DOC_TEXT)

    execution = TabularExecution(
        document_ids=[doc.id],
        columns=columns,
        status="pending",
        cost_estimate_usd=confirmed_cost_usd,
    )
    db.add(execution)
    await db.flush()
    execution_id = execution.id

    gateway = _StubGateway()
    await run_tabular_execution(
        db,
        execution_id=execution_id,
        gateway=gateway,  # type: ignore[arg-type]
    )

    refreshed = (
        await db.execute(select(TabularExecution).where(TabularExecution.id == execution_id))
    ).scalar_one()
    return refreshed, gateway


# ---------------------------------------------------------------------------
# Integration tests — acceptance
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_low_ceiling_halts_ensemble_midrun_and_run_completes(
    db_session: AsyncSession,
) -> None:
    """Acceptance (DE-331): with a $0.02 ceiling and a $0.015/pass
    estimate, cell 1 verifies via ensemble; cells 2-3 skip (projection
    $0.03 > $0.02), carrying ``verification_method=None``; the halt flag
    + count are recorded; the run COMPLETES with every cell extracted."""

    refreshed, gateway = await _run_execution(
        db_session,
        columns=_ensemble_columns(3),
        confirmed_cost_usd=Decimal("0.02"),
    )

    assert refreshed.status == "completed", f"unexpected status: {refreshed.status!r}"
    results = refreshed.results
    assert results is not None
    assert results["ensemble_halted_at_ceiling"] is True
    assert results["ensemble_halted_cells"] == 2

    cells = results["rows"][0]["cells"]
    # First ensemble-eligible cell got its pass; later cells were halted
    # but still extracted (degrade-only, never fail the run).
    assert cells["C0"]["verification_method"] == "ensemble_strict"
    for name in ("C1", "C2"):
        assert cells[name]["verification_method"] is None, (
            f"halted cell {name} still carries a verification signal: "
            f"{cells[name]['verification_method']!r}"
        )
    for name in ("C0", "C1", "C2"):
        assert cells[name]["value"] == "3 years"
        assert cells[name]["confidence"] == "high"

    # Exactly one ensemble pass dispatched = 3 judge calls (1 cell x 3 judges).
    assert gateway.judge_calls == 3, f"expected 3 judge calls; got {gateway.judge_calls}"

    # Read path surfaces the halt honestly.
    from app.api.tabular import _to_response

    response = await _to_response(db_session, refreshed)
    assert response.results is not None
    assert response.results.ensemble_halted_at_ceiling is True
    assert response.results.ensemble_halted_cells == 2


@pytest.mark.integration
async def test_ample_ceiling_runs_all_ensemble_passes(db_session: AsyncSession) -> None:
    """A ceiling with headroom for every pass changes nothing: all cells
    verify, no halt is recorded."""

    refreshed, gateway = await _run_execution(
        db_session,
        columns=_ensemble_columns(3),
        confirmed_cost_usd=Decimal("10.00"),
    )

    assert refreshed.status == "completed"
    results = refreshed.results
    assert results is not None
    assert results["ensemble_halted_at_ceiling"] is False
    assert results["ensemble_halted_cells"] == 0
    cells = results["rows"][0]["cells"]
    for name in ("C0", "C1", "C2"):
        assert cells[name]["verification_method"] == "ensemble_strict"
    assert gateway.judge_calls == 9, f"expected 9 judge calls; got {gateway.judge_calls}"


@pytest.mark.integration
async def test_no_ensemble_run_untouched_by_tiny_ceiling(db_session: AsyncSession) -> None:
    """A run with no ensemble columns never trips the ceiling regardless
    of how tiny the confirmed cost is — no judge calls, no halt flag."""

    refreshed, gateway = await _run_execution(
        db_session,
        columns=_ensemble_columns(2, ensemble=False),
        confirmed_cost_usd=Decimal("0.0001"),
    )

    assert refreshed.status == "completed"
    results = refreshed.results
    assert results is not None
    assert results["ensemble_halted_at_ceiling"] is False
    assert results["ensemble_halted_cells"] == 0
    cells = results["rows"][0]["cells"]
    for name in ("C0", "C1"):
        assert cells[name]["verification_method"] is None
        assert cells[name]["value"] == "3 years"
    assert gateway.judge_calls == 0


@pytest.mark.integration
async def test_no_confirmed_cost_means_no_ceiling(db_session: AsyncSession) -> None:
    """``cost_estimate_usd=None`` (operator confirmed nothing — e.g. a
    pre-confirmation-gate row) applies no ceiling: ensemble runs for
    every eligible cell."""

    refreshed, gateway = await _run_execution(
        db_session,
        columns=_ensemble_columns(2),
        confirmed_cost_usd=None,
    )

    assert refreshed.status == "completed"
    results = refreshed.results
    assert results is not None
    assert results["ensemble_halted_at_ceiling"] is False
    assert results["ensemble_halted_cells"] == 0
    cells = results["rows"][0]["cells"]
    for name in ("C0", "C1"):
        assert cells[name]["verification_method"] == "ensemble_strict"
    assert gateway.judge_calls == 6
