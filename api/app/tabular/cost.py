"""Per-cell cost calibration for Tabular Review — M3-C2.

Mirrors :mod:`app.citation.cost` (M2-E2 rolling-average estimator).
The Tabular variant differs in scope: cells fan out across whatever
inference tier their column demands, so the primitive is a single
rolling average over all tabular-extraction calls (not per-model).
Per-column tier overrides surface in the
:class:`~app.schemas.tabular.TabularPreviewCostResponse`
``per_tier_breakdown`` as informational cell counts; the per-cell
cost itself is one average across all tiers in v0.3.0.

Why single-primitive (not per-tier)
-----------------------------------

Splitting the rolling average per-tier would let the cost preview
report Tier 4 cells at 3x the price of Tier 2 cells (which they are,
roughly). The trade-off is each per-tier bucket needs its own cold-
start path; tiers that have never been routed return the conservative
default x bucket-count and the operator sees a misleadingly wide cost
band. Single-average gives a tighter, more honest pre-flight number
at the cost of less per-tier resolution. If operators start asking
"why is my Tier 4-heavy run priced the same as my Tier 1-heavy run?"
that's a follow-on DE.

How the estimate works
----------------------

* The gateway records actual ``cost_estimate`` on every inference call.
* M2-E2 added a ``purpose`` column. The Tabular executor's cell node
  tags every gateway call with ``lq_ai_purpose='tabular_extraction'``
  (the value defined here as :data:`TABULAR_EXTRACTION_PURPOSE`).
* The rolling average runs over the last 100 tabular-extraction calls
  (or last 30 days, whichever cuts smaller).

Cold-start posture
------------------

When fewer than :data:`_MIN_SAMPLES` recent tabular-extraction rows
exist, the estimator returns :data:`DEFAULT_PER_CELL_USD` —
intentionally permissive so the pre-flight errs toward fallback
rather than over-promising a tiny cost on a brand-new deployment.

Caching
-------

The cost-preview endpoint runs synchronously per
``POST /api/v1/tabular/preview-cost``. Without caching, every
keystroke that triggers a re-preview (column-spec edits in the
wizard) would re-query. The estimator caches per ~5 minutes in-process
(matches the M2-E2 + Anthropic prompt-cache horizon).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inference import InferenceRoutingLog
from app.schemas.tabular import ColumnSpec, TabularPreviewCostResponse

logger = logging.getLogger(__name__)


TABULAR_EXTRACTION_PURPOSE = "tabular_extraction"
"""Value the cell node tags every gateway call with via
``lq_ai_purpose``. The gateway writes this through to
``inference_routing_log.purpose`` (M2-E2). The cost estimator filters
on it so chat / judge / embedding traffic does not pollute the
per-cell average."""


DEFAULT_PER_CELL_USD: Decimal = Decimal("0.005")
"""Cold-start per-cell cost fallback.

Matches the M2-D1 ``FLAT_PER_JUDGE_USD`` constant —
intentionally conservative. A 200-doc x 10-col run at the default
estimates to $10.00 in the cost-preview before any calibration data
exists, which gates the operator behind the $1.00 confirmation
checkbox (Decision C-5). Real per-cell cost typically lands between
$0.002 (Haiku) and $0.020 (Opus on a long context); the default
trends toward the cheaper side so operators don't see scary numbers
on cold-start, but stays conservative enough to gate large runs."""


DEFAULT_TOKENS_PER_CELL: int = 2000
"""Cold-start tokens-per-cell fallback. Rough heuristic:
~1.8K input (system prompt + 4 retrieved chunks averaging ~400
chars each) + ~200 output (extraction value + brief justification).
Surfaced in the preview's ``estimated_tokens`` so operators see the
inference-budget shape even before calibration kicks in."""


DEFAULT_TIER_LABEL = "default"
"""Bucket key for cells whose column has no explicit
``minimum_inference_tier``. Distinct from ``tier_N`` keys so the UI
can render the bucket as "Default tier (gateway routing)" instead
of pinning to a specific number that the gateway's router may not
actually pick."""


_MIN_SAMPLES = 5
"""Minimum tabular-extraction rows required before the rolling
average is trusted over the cold-start fallback."""

_WINDOW_SAMPLES = 100
"""Most recent N tabular-extraction calls included in the rolling
average. Large enough to smooth noise; small enough to track recent
provider price changes within hours of typical traffic."""

_WINDOW_DAYS = 30
"""Maximum lookback window. Protects against price-stale data on
low-traffic deployments."""

_CACHE_TTL_SECONDS = 300.0
"""In-process cache TTL — matches the M2-E2 + Anthropic prompt-cache
window so cost calibration stays consistent with the cache horizon."""


# Single-entry cache: the per-cell average is global (not keyed by
# model or tier), so one slot is enough. Tuple is ``(cached_at,
# (cost_per_cell, tokens_per_cell))``.
_cache: dict[str, tuple[float, tuple[Decimal, int]]] = {}
_CACHE_KEY = "per_cell_metrics"


async def estimate_per_cell_cost_usd(db: AsyncSession | None) -> Decimal:
    """Return the rolling-average per-cell cost in USD.

    Computes the average ``cost_estimate`` across the last
    :data:`_WINDOW_SAMPLES` ``inference_routing_log`` rows where
    ``purpose = 'tabular_extraction'``. Returns
    :data:`DEFAULT_PER_CELL_USD` if fewer than :data:`_MIN_SAMPLES`
    such rows exist.

    ``db=None`` skips the query and returns the default. Honored by
    unit tests that exercise wiring without caring about calibration;
    production callers always pass a real session.

    Cached in-process per :data:`_CACHE_TTL_SECONDS`.
    """

    cost, _ = await _estimate_per_cell_metrics(db)
    return cost


async def estimate_per_cell_tokens(db: AsyncSession | None) -> int:
    """Return the rolling-average tokens-per-cell.

    Mirrors :func:`estimate_per_cell_cost_usd` but for the
    ``tokens_in + tokens_out`` sum on tabular-extraction rows. The
    preview UX surfaces this as ``estimated_tokens`` so operators see
    inference-budget shape independent of the dollar cost.
    """

    _, tokens = await _estimate_per_cell_metrics(db)
    return tokens


async def estimate_tabular_execution_cost(
    db: AsyncSession | None,
    *,
    document_ids: list[UUID],
    columns: list[ColumnSpec],
) -> TabularPreviewCostResponse:
    """Compute the full cost-preview payload for one tabular execution.

    Multiplies ``len(document_ids) * len(columns)`` to derive
    ``cells_count``; multiplies the per-cell cost / tokens by the
    cell count; bucketizes cells by ``minimum_inference_tier`` for
    the ``per_tier_breakdown`` informational field.

    Edge case: an empty column list yields a zero-cell preview with
    zero cost / zero tokens / empty breakdown. The endpoint layer's
    request validation rejects this before it reaches the estimator
    (``min_length=1`` on ``columns`` in the request schema), but the
    estimator is defensive about edge inputs so callers building
    previews internally don't crash on empty drafts.
    """

    cells_count = len(document_ids) * len(columns)

    if cells_count == 0:
        return TabularPreviewCostResponse(
            cells_count=0,
            estimated_tokens=0,
            estimated_cost_usd=Decimal("0"),
            per_tier_breakdown={},
        )

    per_cell_cost, per_cell_tokens = await _estimate_per_cell_metrics(db)

    estimated_cost = per_cell_cost * Decimal(cells_count)
    estimated_tokens = per_cell_tokens * cells_count

    per_tier_breakdown = _bucketize_cells_by_tier(
        n_docs=len(document_ids),
        columns=columns,
    )

    return TabularPreviewCostResponse(
        cells_count=cells_count,
        estimated_tokens=estimated_tokens,
        estimated_cost_usd=estimated_cost,
        per_tier_breakdown=per_tier_breakdown,
    )


def invalidate_cache() -> None:
    """Reset the in-process cache. Tests call this between assertions."""

    _cache.clear()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _estimate_per_cell_metrics(
    db: AsyncSession | None,
) -> tuple[Decimal, int]:
    """Shared primitive — returns (per-cell cost USD, per-cell tokens).

    One DB hit fetches both the average cost AND the average token
    total in the same query, then both estimators share the cache so
    a preview that needs both metrics only pays one round-trip.
    """

    if db is None:
        return DEFAULT_PER_CELL_USD, DEFAULT_TOKENS_PER_CELL

    now = time.monotonic()
    cached = _cache.get(_CACHE_KEY)
    if cached is not None:
        cached_at, cached_value = cached
        if now - cached_at < _CACHE_TTL_SECONDS:
            return cached_value

    cutoff = datetime.now(UTC) - timedelta(days=_WINDOW_DAYS)
    recent = (
        select(
            InferenceRoutingLog.cost_estimate,
            InferenceRoutingLog.tokens_in,
            InferenceRoutingLog.tokens_out,
        )
        .where(
            InferenceRoutingLog.purpose == TABULAR_EXTRACTION_PURPOSE,
            InferenceRoutingLog.cost_estimate.is_not(None),
            InferenceRoutingLog.timestamp >= cutoff,
        )
        .order_by(InferenceRoutingLog.timestamp.desc())
        .limit(_WINDOW_SAMPLES)
        .subquery()
    )
    # AVG over the sub-select. ``func.coalesce(tokens_in, 0) +
    # coalesce(tokens_out, 0)`` so rows where the gateway recorded
    # cost but not token counts (e.g., provider didn't return usage)
    # still contribute their cost without poisoning the token average.
    stmt = select(
        func.avg(recent.c.cost_estimate),
        func.avg(
            func.coalesce(recent.c.tokens_in, 0) + func.coalesce(recent.c.tokens_out, 0),
        ),
        func.count(recent.c.cost_estimate),
    )

    try:
        result = await db.execute(stmt)
        avg_cost_raw, avg_tokens_raw, count = result.one()
    except Exception as exc:
        # Defensive: a DB hiccup on the cost pre-flight should never
        # break execute-tabular. Fall back to the conservative
        # defaults and log loud.
        logger.warning(
            "tabular cost calibration query failed: %s",
            exc,
            extra={
                "event": "tabular_cost_query_error",
                "error_type": type(exc).__name__,
            },
        )
        return DEFAULT_PER_CELL_USD, DEFAULT_TOKENS_PER_CELL

    if count is None or count < _MIN_SAMPLES or avg_cost_raw is None:
        _cache[_CACHE_KEY] = (now, (DEFAULT_PER_CELL_USD, DEFAULT_TOKENS_PER_CELL))
        return DEFAULT_PER_CELL_USD, DEFAULT_TOKENS_PER_CELL

    cost_estimate = Decimal(str(avg_cost_raw))
    tokens_estimate = int(avg_tokens_raw) if avg_tokens_raw is not None else DEFAULT_TOKENS_PER_CELL

    metrics: tuple[Decimal, int] = (cost_estimate, tokens_estimate)
    _cache[_CACHE_KEY] = (now, metrics)
    return metrics


def _bucketize_cells_by_tier(
    *,
    n_docs: int,
    columns: list[ColumnSpec],
) -> dict[str, int]:
    """Count cells per tier bucket for the informational breakdown.

    Columns with ``minimum_inference_tier`` set get a ``tier_N`` key;
    columns without get the :data:`DEFAULT_TIER_LABEL` bucket. The UI
    renders the breakdown so operators see the tier-mix of their
    proposed execution before confirming.
    """

    buckets: dict[str, int] = {}
    for col in columns:
        key = (
            f"tier_{col.minimum_inference_tier}"
            if col.minimum_inference_tier
            else DEFAULT_TIER_LABEL
        )
        buckets[key] = buckets.get(key, 0) + n_docs
    return buckets


__all__ = [
    "DEFAULT_PER_CELL_USD",
    "DEFAULT_TIER_LABEL",
    "DEFAULT_TOKENS_PER_CELL",
    "TABULAR_EXTRACTION_PURPOSE",
    "estimate_per_cell_cost_usd",
    "estimate_per_cell_tokens",
    "estimate_tabular_execution_cost",
    "invalidate_cache",
]
