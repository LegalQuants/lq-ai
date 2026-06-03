"""Per-cell cost calibration for Tabular Review — M3-C2.

Targets :mod:`app.tabular.cost`:

* ``db=None`` cold-start fast-path returns the conservative default.
* Cold-start with empty DB returns the conservative default.
* Rolling-average computation against real routing-log rows.
* ``purpose='tabular_extraction'`` filter excludes chat / judge / NULL rows.
* NULL ``cost_estimate`` rows excluded.
* Stale rows (older than ``_WINDOW_DAYS``) excluded.
* Cache hits return cached value without re-querying.
* ``invalidate_cache()`` resets the cache.
* Public entry point :func:`estimate_tabular_execution_cost` derives
  ``cells_count``, ``estimated_tokens``, ``estimated_cost_usd``, and the
  ``per_tier_breakdown`` from the column spec + document list.

Mirrors the M2-E2 cost-test surface in ``tests/citation/test_cost.py``;
the Tabular variant is single-primitive (not per-model) because cells
fan out across whatever tier their column demands. The rolling average
is over all tabular-extraction calls regardless of routed model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.cost import DEFAULT_PER_JUDGE_USD, invalidate_cache as invalidate_judge_cache
from app.clients.gateway import EnsembleConfig
from app.models.inference import InferenceRoutingLog
from app.schemas.tabular import ColumnSpec
from app.tabular.cost import (
    DEFAULT_PER_CELL_USD,
    DEFAULT_TOKENS_PER_CELL,
    TABULAR_EXTRACTION_PURPOSE,
    estimate_per_cell_cost_usd,
    estimate_tabular_execution_cost,
    invalidate_cache,
)


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    """Reset both in-process caches between tests so cached values from
    one test don't leak into the next: the tabular per-cell cache and
    the judge-cost cache (the ensemble premium reuses the latter)."""

    invalidate_cache()
    invalidate_judge_cache()


def _ensemble_config(
    *,
    default_enabled: bool = False,
    judge_models: tuple[str, ...] = ("a", "b", "c"),
) -> EnsembleConfig:
    """Build an :class:`EnsembleConfig` for premium-cost assertions.

    The aggregation_rule / max_cost / envelope_tier fields don't affect
    the cost preview (the preview always counts one ensemble pass per
    ensemble cell); only ``default_enabled`` and ``judge_models`` matter
    here, so they get sensible fixed values.
    """

    return EnsembleConfig(
        default_enabled=default_enabled,
        judge_models=judge_models,
        aggregation_rule="strict",
        max_cost_per_message_usd=1.0,
        envelope_tier=3,
    )


def _tabular_row(
    *,
    cost_estimate: Decimal | None = Decimal("0.0030"),
    tokens_in: int | None = 1800,
    tokens_out: int | None = 200,
    purpose: str | None = TABULAR_EXTRACTION_PURPOSE,
    timestamp: datetime | None = None,
    routed_model: str = "claude-sonnet-4-6",
    routed_inference_tier: int = 2,
) -> InferenceRoutingLog:
    return InferenceRoutingLog(
        id=uuid.uuid4(),
        timestamp=timestamp or datetime.now(UTC),
        routed_provider="anthropic-prod",
        routed_model=routed_model,
        routed_inference_tier=routed_inference_tier,
        cost_estimate=cost_estimate,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        purpose=purpose,
    )


# --- estimate_per_cell_cost_usd: db=None ------------------------------------


@pytest.mark.unit
async def test_per_cell_db_none_returns_default_without_query() -> None:
    """``db=None`` is the cold-start fast-path; no DB hit needed."""

    estimate = await estimate_per_cell_cost_usd(None)
    assert estimate == DEFAULT_PER_CELL_USD


# --- estimate_per_cell_cost_usd: cold start ---------------------------------


@pytest.mark.integration
async def test_per_cell_cold_start_no_rows_returns_default(db_session: AsyncSession) -> None:
    """An empty routing log falls back to the conservative default."""

    estimate = await estimate_per_cell_cost_usd(db_session)
    assert estimate == DEFAULT_PER_CELL_USD


@pytest.mark.integration
async def test_per_cell_below_min_samples_returns_default(db_session: AsyncSession) -> None:
    """Fewer than _MIN_SAMPLES tabular rows → fall back to default."""

    for _ in range(3):
        db_session.add(_tabular_row(cost_estimate=Decimal("0.0010")))
    await db_session.flush()

    estimate = await estimate_per_cell_cost_usd(db_session)
    assert estimate == DEFAULT_PER_CELL_USD


# --- estimate_per_cell_cost_usd: rolling average ----------------------------


@pytest.mark.integration
async def test_per_cell_rolling_average_computes_correctly(db_session: AsyncSession) -> None:
    """5+ tabular rows → returns the average of cost_estimate."""

    prices = [
        Decimal("0.0010"),
        Decimal("0.0020"),
        Decimal("0.0030"),
        Decimal("0.0040"),
        Decimal("0.0050"),
    ]
    for price in prices:
        db_session.add(_tabular_row(cost_estimate=price))
    await db_session.flush()

    estimate = await estimate_per_cell_cost_usd(db_session)
    # average = 0.0030
    assert estimate == Decimal("0.00300000000000000000") or estimate == Decimal("0.0030")


# --- Filter correctness -----------------------------------------------------


@pytest.mark.integration
async def test_per_cell_purpose_filter_excludes_chat_rows(db_session: AsyncSession) -> None:
    """Chat-purpose rows for the same model are ignored.

    Chat traffic has very different token distribution from tabular
    extraction (chat ≈ free-form generation, tabular ≈ structured
    extraction over retrieved chunks). Averaging across both would
    pollute the per-cell estimate.
    """

    for _ in range(5):
        db_session.add(
            _tabular_row(cost_estimate=Decimal("0.0200"), purpose="chat"),
        )
    await db_session.flush()

    estimate = await estimate_per_cell_cost_usd(db_session)
    assert estimate == DEFAULT_PER_CELL_USD


@pytest.mark.integration
async def test_per_cell_purpose_filter_excludes_null_purpose_rows(
    db_session: AsyncSession,
) -> None:
    """Rows with NULL purpose are excluded (matches the citation/cost.py posture)."""

    for _ in range(5):
        db_session.add(_tabular_row(cost_estimate=Decimal("0.0050"), purpose=None))
    await db_session.flush()

    estimate = await estimate_per_cell_cost_usd(db_session)
    assert estimate == DEFAULT_PER_CELL_USD


@pytest.mark.integration
async def test_per_cell_purpose_filter_excludes_judge_paraphrase_rows(
    db_session: AsyncSession,
) -> None:
    """``judge_paraphrase`` rows are excluded from the tabular average.

    A model can serve all three workloads; only the tabular-extraction
    rows reflect cell-shaped traffic.
    """

    for _ in range(5):
        db_session.add(
            _tabular_row(cost_estimate=Decimal("0.0080"), purpose="judge_paraphrase"),
        )
    await db_session.flush()

    estimate = await estimate_per_cell_cost_usd(db_session)
    assert estimate == DEFAULT_PER_CELL_USD


@pytest.mark.integration
async def test_per_cell_null_cost_estimate_rows_excluded(db_session: AsyncSession) -> None:
    """Tabular rows missing ``cost_estimate`` don't poison the average."""

    for _ in range(5):
        db_session.add(_tabular_row(cost_estimate=Decimal("0.0010")))
    for _ in range(10):
        db_session.add(_tabular_row(cost_estimate=None))
    await db_session.flush()

    estimate = await estimate_per_cell_cost_usd(db_session)
    assert estimate == Decimal("0.00100000000000000000") or estimate == Decimal("0.0010")


@pytest.mark.integration
async def test_per_cell_stale_rows_excluded(db_session: AsyncSession) -> None:
    """Rows older than _WINDOW_DAYS are excluded.

    Protects against price-stale data on low-traffic deployments.
    """

    now = datetime.now(UTC)
    stale = now - timedelta(days=60)

    for _ in range(5):
        db_session.add(_tabular_row(cost_estimate=Decimal("0.0010"), timestamp=now))
    for _ in range(10):
        db_session.add(_tabular_row(cost_estimate=Decimal("0.1000"), timestamp=stale))
    await db_session.flush()

    estimate = await estimate_per_cell_cost_usd(db_session)
    # If stale rows weren't excluded, average ≈ 0.067.
    assert estimate < Decimal("0.005")


# --- Cache ------------------------------------------------------------------


@pytest.mark.integration
async def test_per_cell_cache_returns_same_value_without_db_hit(
    db_session: AsyncSession,
) -> None:
    """Second call within TTL returns cached value even if rows change."""

    for _ in range(5):
        db_session.add(_tabular_row(cost_estimate=Decimal("0.0010")))
    await db_session.flush()

    first = await estimate_per_cell_cost_usd(db_session)

    for _ in range(10):
        db_session.add(_tabular_row(cost_estimate=Decimal("0.1000")))
    await db_session.flush()

    second = await estimate_per_cell_cost_usd(db_session)
    assert second == first


@pytest.mark.unit
async def test_invalidate_cache_all_clears_everything() -> None:
    """``invalidate_cache()`` clears state without raising."""

    await estimate_per_cell_cost_usd(None)
    invalidate_cache()  # should not raise


# --- estimate_tabular_execution_cost: public entry point --------------------


@pytest.mark.unit
async def test_execution_cost_cells_count_is_docs_times_columns() -> None:
    """``cells_count = len(document_ids) * len(columns)``."""

    doc_ids = [uuid.uuid4() for _ in range(5)]
    cols = [
        ColumnSpec(name="Term", query="What is the term?"),
        ColumnSpec(name="Survival", query="What is the survival period?"),
        ColumnSpec(name="Carveouts", query="What are the carveouts?"),
        ColumnSpec(name="Governing Law", query="What is the governing law?"),
    ]

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
    )
    assert preview.cells_count == 20


@pytest.mark.unit
async def test_execution_cost_uses_default_per_cell_when_db_none() -> None:
    """``db=None`` uses the cold-start per-cell default x cells_count."""

    doc_ids = [uuid.uuid4() for _ in range(3)]
    cols = [
        ColumnSpec(name="A", query="?"),
        ColumnSpec(name="B", query="?"),
    ]

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
    )
    # 3 docs * 2 cols * 0.005 = 0.030
    assert preview.estimated_cost_usd == DEFAULT_PER_CELL_USD * Decimal(6)


@pytest.mark.unit
async def test_execution_cost_estimated_tokens_uses_default_when_db_none() -> None:
    """``db=None`` uses the cold-start tokens-per-cell default x cells_count."""

    doc_ids = [uuid.uuid4() for _ in range(2)]
    cols = [ColumnSpec(name="A", query="?")]

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
    )
    assert preview.estimated_tokens == DEFAULT_TOKENS_PER_CELL * 2


@pytest.mark.unit
async def test_execution_cost_per_tier_breakdown_counts_default_tier() -> None:
    """Columns without an explicit ``minimum_inference_tier`` count toward
    the default tier bucket."""

    doc_ids = [uuid.uuid4() for _ in range(4)]
    cols = [
        ColumnSpec(name="A", query="?"),  # default tier
        ColumnSpec(name="B", query="?"),  # default tier
    ]

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
    )
    # 4 docs * 2 default-tier cols = 8 cells, all in one bucket
    assert sum(preview.per_tier_breakdown.values()) == 8
    assert len(preview.per_tier_breakdown) == 1


@pytest.mark.unit
async def test_execution_cost_per_tier_breakdown_separates_explicit_tier() -> None:
    """Columns with explicit ``minimum_inference_tier`` get their own bucket."""

    doc_ids = [uuid.uuid4() for _ in range(5)]
    cols = [
        ColumnSpec(name="Routine", query="?"),  # default tier
        ColumnSpec(name="HighStakes", query="?", minimum_inference_tier=4),
    ]

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
    )
    # 5 cells default + 5 cells tier_4 = two buckets, each holding 5.
    assert "tier_4" in preview.per_tier_breakdown
    assert preview.per_tier_breakdown["tier_4"] == 5
    # Other bucket carries the remaining 5 default cells.
    assert sum(preview.per_tier_breakdown.values()) == 10


@pytest.mark.unit
async def test_execution_cost_empty_columns_yields_zero_cells() -> None:
    """An empty column list yields zero cells / zero cost / zero tokens.

    Defensive: the public entry point shouldn't crash on edge inputs;
    the endpoint layer's request validation rejects empty inputs before
    this layer ever sees them, but a zero-cell run should still produce
    a well-formed response.
    """

    doc_ids = [uuid.uuid4()]

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=[],
    )
    assert preview.cells_count == 0
    assert preview.estimated_cost_usd == Decimal("0")
    assert preview.estimated_tokens == 0
    assert preview.per_tier_breakdown == {}
    # New ensemble fields default to zero on the empty edge case.
    assert preview.ensemble_cells_count == 0
    assert preview.ensemble_premium_usd == Decimal("0")


# --- estimate_tabular_execution_cost: ensemble premium (Donna #6) -----------


@pytest.mark.unit
async def test_execution_cost_ensemble_column_previews_higher() -> None:
    """An ensemble column previews HIGHER than the same shape without
    ensemble config — the premium is one ensemble pass (N judge calls)
    per ensemble cell, on top of the extraction rate."""

    doc_ids = [uuid.uuid4() for _ in range(4)]
    cols = [ColumnSpec(name="A", query="?", ensemble_verification=True)]
    config = _ensemble_config(judge_models=("a", "b", "c"))

    # Baseline: same columns, no ensemble config wired → no premium.
    base = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
    )

    invalidate_cache()
    invalidate_judge_cache()

    premium_preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
        ensemble_config=config,
    )

    assert premium_preview.estimated_cost_usd > base.estimated_cost_usd
    # 4 docs * 1 ensemble column = 4 ensemble cells.
    assert premium_preview.ensemble_cells_count == 4
    assert premium_preview.ensemble_premium_usd > Decimal("0")
    # db=None → each judge call costs the cold-start default; one pass is
    # 3 judges, applied per ensemble cell.
    expected_premium = DEFAULT_PER_JUDGE_USD * Decimal(3) * Decimal(4)
    assert premium_preview.ensemble_premium_usd == expected_premium
    # estimated_cost_usd is the TOTAL: base extraction + premium.
    assert premium_preview.estimated_cost_usd == base.estimated_cost_usd + expected_premium


@pytest.mark.unit
async def test_execution_cost_no_ensemble_config_adds_no_premium() -> None:
    """``ensemble_config=None`` → no premium even if a column has
    ``ensemble_verification=True`` (can't run an ensemble the gateway
    hasn't configured)."""

    doc_ids = [uuid.uuid4() for _ in range(3)]
    cols = [ColumnSpec(name="A", query="?", ensemble_verification=True)]

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
        ensemble_config=None,
    )

    assert preview.ensemble_cells_count == 0
    assert preview.ensemble_premium_usd == Decimal("0")
    # estimated_cost equals the pure extraction base (3 * 1 * default).
    assert preview.estimated_cost_usd == DEFAULT_PER_CELL_USD * Decimal(3)


@pytest.mark.unit
async def test_execution_cost_mixed_columns_counts_only_ensemble_cells() -> None:
    """A mix of one ensemble + one non-ensemble column charges the
    premium only against the ensemble cells (n_docs * 1, not * 2)."""

    doc_ids = [uuid.uuid4() for _ in range(5)]
    cols = [
        ColumnSpec(name="Ensemble", query="?", ensemble_verification=True),
        ColumnSpec(name="Plain", query="?", ensemble_verification=False),
    ]
    config = _ensemble_config(judge_models=("a", "b"))

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
        ensemble_config=config,
    )

    # 5 docs * 1 ensemble column = 5 ensemble cells (the plain column
    # contributes 0 to the ensemble count).
    assert preview.ensemble_cells_count == 5
    expected_premium = DEFAULT_PER_JUDGE_USD * Decimal(2) * Decimal(5)
    assert preview.ensemble_premium_usd == expected_premium


@pytest.mark.unit
async def test_execution_cost_deployment_default_activates_null_column() -> None:
    """A column with ``ensemble_verification=None`` inherits the
    deployment default: ``default_enabled=True`` → counts as ensemble."""

    doc_ids = [uuid.uuid4() for _ in range(3)]
    cols = [ColumnSpec(name="A", query="?")]  # ensemble_verification defaults to None
    config = _ensemble_config(default_enabled=True, judge_models=("a", "b"))

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
        ensemble_config=config,
    )

    assert preview.ensemble_cells_count == 3
    assert preview.ensemble_premium_usd == DEFAULT_PER_JUDGE_USD * Decimal(2) * Decimal(3)


@pytest.mark.unit
async def test_execution_cost_deployment_default_off_null_column_no_premium() -> None:
    """A column with ``ensemble_verification=None`` and
    ``default_enabled=False`` → no premium."""

    doc_ids = [uuid.uuid4() for _ in range(3)]
    cols = [ColumnSpec(name="A", query="?")]
    config = _ensemble_config(default_enabled=False, judge_models=("a", "b"))

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
        ensemble_config=config,
    )

    assert preview.ensemble_cells_count == 0
    assert preview.ensemble_premium_usd == Decimal("0")


@pytest.mark.unit
async def test_execution_cost_empty_judge_models_yields_zero_premium() -> None:
    """An ``EnsembleConfig`` with ``judge_models=()`` (empty tuple) and an
    ensemble column → ``ensemble_premium_usd == Decimal("0")`` cleanly.

    The premium is a sum over the judge models; an empty tuple sums to
    zero rather than crashing. This path can't arise via the gateway
    (it rejects empty judge_models), but ``estimate_tabular_execution_cost``
    is a public function, so this pins the empty-judges behavior: zero
    premium, no error.
    """

    doc_ids = [uuid.uuid4() for _ in range(3)]
    cols = [ColumnSpec(name="A", query="?", ensemble_verification=True)]
    config = _ensemble_config(judge_models=())

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
        ensemble_config=config,
    )

    # Empty judge_models → zero premium (sum over zero judges = 0).
    assert preview.ensemble_premium_usd == Decimal("0")


@pytest.mark.unit
async def test_execution_cost_explicit_false_overrides_deployment_default() -> None:
    """An explicit ``ensemble_verification=False`` wins over
    ``default_enabled=True`` — no premium for that column."""

    doc_ids = [uuid.uuid4() for _ in range(3)]
    cols = [ColumnSpec(name="A", query="?", ensemble_verification=False)]
    config = _ensemble_config(default_enabled=True, judge_models=("a", "b"))

    preview = await estimate_tabular_execution_cost(
        None,
        document_ids=doc_ids,
        columns=cols,
        ensemble_config=config,
    )

    assert preview.ensemble_cells_count == 0
    assert preview.ensemble_premium_usd == Decimal("0")
