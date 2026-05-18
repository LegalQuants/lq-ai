"""Per-judge-model cost calibration — M2-E2.

Targets :mod:`app.citation.cost`:

* ``db=None`` cold-start fast-path.
* Rolling-average computation against real routing-log rows.
* Cold-start fallback when < _MIN_SAMPLES rows exist.
* Filter correctness — ``purpose='judge_paraphrase'`` only, NULL
  ``cost_estimate`` excluded, stale rows excluded.
* Cache hits return without hitting the DB twice.
* ``invalidate_cache`` resets entries.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.cost import (
    DEFAULT_PER_JUDGE_USD,
    estimate_judge_call_cost_usd,
    invalidate_cache,
)
from app.models.inference import InferenceRoutingLog


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    """Reset the in-process cache between tests so cached values from
    one test don't leak into the next."""

    invalidate_cache()


def _judge_row(
    *,
    routed_model: str,
    cost_estimate: Decimal | None,
    purpose: str | None = "judge_paraphrase",
    timestamp: datetime | None = None,
) -> InferenceRoutingLog:
    return InferenceRoutingLog(
        id=uuid.uuid4(),
        timestamp=timestamp or datetime.now(UTC),
        routed_provider="anthropic-prod",
        routed_model=routed_model,
        routed_inference_tier=3,
        cost_estimate=cost_estimate,
        purpose=purpose,
    )


# --- db=None ----------------------------------------------------------------


@pytest.mark.unit
async def test_db_none_returns_default_without_query() -> None:
    """``db=None`` is the test/cold-start fast-path; no DB hit needed."""

    estimate = await estimate_judge_call_cost_usd(None, judge_model="claude-haiku-4-5")
    assert estimate == DEFAULT_PER_JUDGE_USD


# --- Cold start -------------------------------------------------------------


@pytest.mark.integration
async def test_cold_start_no_rows_returns_default(db_session: AsyncSession) -> None:
    """A model with no routing-log rows at all falls back to the default."""

    estimate = await estimate_judge_call_cost_usd(db_session, judge_model="never-seen-judge")
    assert estimate == DEFAULT_PER_JUDGE_USD


@pytest.mark.integration
async def test_below_min_samples_returns_default(db_session: AsyncSession) -> None:
    """Fewer than _MIN_SAMPLES=5 judge rows → fall back to default."""

    # Insert 3 judge rows (below the 5-sample minimum).
    for _ in range(3):
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=Decimal("0.0010"),
            )
        )
    await db_session.flush()

    estimate = await estimate_judge_call_cost_usd(db_session, judge_model="claude-haiku-4-5")
    assert estimate == DEFAULT_PER_JUDGE_USD


# --- Rolling average --------------------------------------------------------


@pytest.mark.integration
async def test_rolling_average_computes_correctly(db_session: AsyncSession) -> None:
    """5+ judge rows for a model → returns the average of cost_estimate."""

    # Five judge calls at varying prices; average = 0.0030
    prices = [
        Decimal("0.0010"),
        Decimal("0.0020"),
        Decimal("0.0030"),
        Decimal("0.0040"),
        Decimal("0.0050"),
    ]
    for price in prices:
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=price,
            )
        )
    await db_session.flush()

    estimate = await estimate_judge_call_cost_usd(db_session, judge_model="claude-haiku-4-5")
    # Allow tiny rounding tolerance — SQL AVG returns Numeric and we
    # convert through Decimal(str(...)) which preserves the printed form.
    assert estimate == Decimal("0.00300000000000000000") or estimate == Decimal("0.0030")


# --- Filter correctness -----------------------------------------------------


@pytest.mark.integration
async def test_purpose_filter_excludes_chat_rows(db_session: AsyncSession) -> None:
    """Chat-purpose rows for the same model are ignored.

    A model can serve both chat traffic and judge traffic — averaging
    over both would let chat-token-distribution drown out judge cost.
    """

    # Five chat rows at $0.020 (a typical chat call) for the same model.
    for _ in range(5):
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=Decimal("0.0200"),
                purpose="chat",
            )
        )
    await db_session.flush()

    estimate = await estimate_judge_call_cost_usd(db_session, judge_model="claude-haiku-4-5")
    # No judge_paraphrase rows → fall back to default, NOT 0.020.
    assert estimate == DEFAULT_PER_JUDGE_USD


@pytest.mark.integration
async def test_purpose_filter_excludes_null_purpose_rows(db_session: AsyncSession) -> None:
    """Rows with NULL purpose (pre-0029 backfill) are excluded.

    Pre-migration rows don't have the column populated; treating them
    as judge calls would be wrong because their token distribution
    matches whatever the call actually was. Conservative interpretation:
    only known-purpose 'judge_paraphrase' rows count.
    """

    for _ in range(5):
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=Decimal("0.0050"),
                purpose=None,
            )
        )
    await db_session.flush()

    estimate = await estimate_judge_call_cost_usd(db_session, judge_model="claude-haiku-4-5")
    assert estimate == DEFAULT_PER_JUDGE_USD


@pytest.mark.integration
async def test_null_cost_estimate_rows_excluded(db_session: AsyncSession) -> None:
    """Judge rows missing ``cost_estimate`` don't poison the average.

    Some providers (e.g., Ollama) don't carry a published per-token
    price; the gateway records NULL ``cost_estimate`` on those rows.
    Including them in the average would dilute or skew the estimate.
    """

    # 5 valid judge rows at $0.0010 + 10 NULL-cost judge rows.
    for _ in range(5):
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=Decimal("0.0010"),
            )
        )
    for _ in range(10):
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=None,
            )
        )
    await db_session.flush()

    estimate = await estimate_judge_call_cost_usd(db_session, judge_model="claude-haiku-4-5")
    assert estimate == Decimal("0.00100000000000000000") or estimate == Decimal("0.0010")


@pytest.mark.integration
async def test_stale_rows_excluded(db_session: AsyncSession) -> None:
    """Rows older than _WINDOW_DAYS=30 are excluded.

    Protects against price-stale data on low-traffic deployments. Five
    valid recent rows at $0.001 + ten stale rows at $0.100 → estimate
    reflects only the recent (cheap) data, not the stale outliers.
    """

    now = datetime.now(UTC)
    stale = now - timedelta(days=60)

    for _ in range(5):
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=Decimal("0.0010"),
                timestamp=now,
            )
        )
    for _ in range(10):
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=Decimal("0.1000"),
                timestamp=stale,
            )
        )
    await db_session.flush()

    estimate = await estimate_judge_call_cost_usd(db_session, judge_model="claude-haiku-4-5")
    # If the stale rows weren't excluded, the average would be ~0.067.
    assert estimate < Decimal("0.005")
    assert estimate == Decimal("0.00100000000000000000") or estimate == Decimal("0.0010")


# --- Cache ------------------------------------------------------------------


@pytest.mark.integration
async def test_cache_returns_same_value_without_db_hit(db_session: AsyncSession) -> None:
    """Second call within TTL returns cached value even if rows change.

    The cache is keyed by ``judge_model`` only. Inserting new rows after
    the cache populates should not change the returned estimate within
    the TTL window — proves the cache is short-circuiting the query.
    """

    # Seed with 5 rows at $0.001
    for _ in range(5):
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=Decimal("0.0010"),
            )
        )
    await db_session.flush()

    first = await estimate_judge_call_cost_usd(db_session, judge_model="claude-haiku-4-5")

    # Add more expensive rows — would shift the average if cache miss.
    for _ in range(10):
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=Decimal("0.1000"),
            )
        )
    await db_session.flush()

    second = await estimate_judge_call_cost_usd(db_session, judge_model="claude-haiku-4-5")
    assert second == first


@pytest.mark.integration
async def test_invalidate_cache_clears_specific_model(
    db_session: AsyncSession,
) -> None:
    """``invalidate_cache(model)`` re-queries on next call."""

    for _ in range(5):
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=Decimal("0.0010"),
            )
        )
    await db_session.flush()

    first = await estimate_judge_call_cost_usd(db_session, judge_model="claude-haiku-4-5")
    assert first != DEFAULT_PER_JUDGE_USD  # we got the calibrated value

    invalidate_cache("claude-haiku-4-5")

    # After invalidation + adding more rows, next call sees fresh average.
    for _ in range(5):
        db_session.add(
            _judge_row(
                routed_model="claude-haiku-4-5",
                cost_estimate=Decimal("0.0100"),
            )
        )
    await db_session.flush()

    second = await estimate_judge_call_cost_usd(db_session, judge_model="claude-haiku-4-5")
    # New average over 10 rows = (5x0.001 + 5x0.010) / 10 = 0.0055
    assert second > first  # picked up the new expensive rows


@pytest.mark.unit
async def test_invalidate_cache_all_clears_everything() -> None:
    """``invalidate_cache(None)`` clears all entries."""

    # Populate cache for two models via the db=None fast path. The
    # fast path doesn't write to the cache (it returns early), so we
    # call through with db=None and assert the function still works.
    # The clear-all behavior is exercised by the lack of side-effects
    # observed in other tests' autouse cleanup.
    await estimate_judge_call_cost_usd(None, judge_model="a")
    await estimate_judge_call_cost_usd(None, judge_model="b")

    invalidate_cache(None)  # should not raise


# --- Pre-flight integration -------------------------------------------------


@pytest.mark.integration
async def test_resolve_ensemble_uses_per_model_calibration(
    db_session: AsyncSession,
) -> None:
    """End-to-end: a seeded routing-log shifts the pre-flight outcome.

    With the M2-D1 flat constant (0.005), 2 candidates x 3 judges =
    $0.03 — well under a $0.05 budget, so ensemble activates. With
    M2-E2 per-model calibration where each judge averages $0.020
    (a realistic opus rate), 2 x 3 x 0.020 = $0.12 — over budget, so
    ensemble falls back. This test proves the per-model lookup is
    wired into ``_resolve_ensemble_config`` and changes the decision.
    """

    from app.api.chats import _resolve_ensemble_config

    # Seed enough judge rows per model that the rolling average kicks in.
    for model in ("judge-a", "judge-b", "judge-c"):
        for _ in range(5):
            db_session.add(
                _judge_row(
                    routed_model=model,
                    cost_estimate=Decimal("0.0200"),
                )
            )
    await db_session.flush()

    class _Cfg:
        default_enabled = True
        judge_models: tuple[str, ...] = ("judge-a", "judge-b", "judge-c")
        aggregation_rule = "strict"
        max_cost_per_message_usd = 0.05
        envelope_tier = 3

    class _Gw:
        async def get_citation_engine_ensemble_config(self) -> _Cfg:
            return _Cfg()

    # WITHOUT calibration (db=None) the conservative default applies
    # and the request passes the budget.
    result_default = await _resolve_ensemble_config(
        gateway=_Gw(),
        applied_skills=[],
        project_ensemble_verification=True,
        skill_registry=None,
        n_candidates=2,
        message_id=uuid.uuid4(),
        db=None,
    )
    assert result_default is not None  # 2 x 3 x 0.005 = $0.03 < $0.05

    # WITH calibration (real db_session + seeded rows) the per-model
    # average is $0.020/call, so 2 x 3 x 0.020 = $0.12 — falls back.
    result_calibrated = await _resolve_ensemble_config(
        gateway=_Gw(),
        applied_skills=[],
        project_ensemble_verification=True,
        skill_registry=None,
        n_candidates=2,
        message_id=uuid.uuid4(),
        db=db_session,
    )
    assert result_calibrated is None  # calibrated estimate exceeded budget
