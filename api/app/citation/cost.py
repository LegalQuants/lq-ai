"""Per-judge-model cost calibration from the inference routing log (M2-E2).

Replaces the M2-D1 flat constant ``FLAT_PER_JUDGE_USD = 0.005`` with a
per-model rolling average computed from production routing-log data.
The constant remains as a conservative cold-start fallback.

Why per-model
-------------

Judge models span order-of-magnitude cost differences:

* ``claude-haiku-4-5`` — ~$0.001 per judge call (1 K input + 200 output).
* ``claude-sonnet-4-6`` — ~$0.008 per judge call.
* ``claude-opus-4-7`` — ~$0.040 per judge call.
* ``gpt-4o-mini`` — ~$0.0008 per judge call.
* ``gpt-4o`` — ~$0.013 per judge call.

A single flat constant of 0.005 is 5x too conservative for haiku
(causing unnecessary single-judge fallbacks even when the operator
configured a cheap ensemble) and 8x too permissive for opus (letting
ensembles silently overrun the per-message cap when the operator
configured an expensive ensemble). Per-model calibration sourced from
the actual routing log fixes both extremes without manual price
maintenance.

How the estimate works
----------------------

The gateway records actual ``cost_estimate`` on every inference call.
M2-E2 added a ``purpose`` column (``'chat' | 'judge_paraphrase' |
'embedding'``) so this estimator can filter to judge traffic only.
The rolling average runs over the last 100 judge calls for the model
(or the last 30 days, whichever cuts smaller) — fresh enough to track
provider price changes, deep enough to smooth single-call noise.

Cold-start posture
------------------

When a model has fewer than :data:`_MIN_SAMPLES` recent judge calls,
the estimator returns :data:`DEFAULT_PER_JUDGE_USD` — the same
conservative flat constant M2-D1 shipped. Operators with brand-new
deployments see the conservative budget posture until enough judge
traffic accumulates to calibrate; that matches the safety story of
"err toward fallback rather than runaway spend".

Caching
-------

Pre-flight cost-budget checks call this once per configured judge
model on every ensemble-activated chat-send. Without caching, a
3-model ensemble would hit the DB three times per message. The
estimator caches per-model for ~5 minutes in-process — short enough
that new judge calls feed back into the average reasonably quickly
but long enough to amortize the DB hits. Per-process; multi-worker
deployments accept the per-worker drift as benign noise.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inference import InferenceRoutingLog

logger = logging.getLogger(__name__)


DEFAULT_PER_JUDGE_USD: Decimal = Decimal("0.005")
"""Cold-start fallback. Matches the M2-D1 ``FLAT_PER_JUDGE_USD``
constant in :mod:`app.citation.verification`; intentionally
conservative so the pre-flight errs toward fallback rather than
overrun when no calibration data exists yet."""


_MIN_SAMPLES = 5
"""Minimum judge calls required before the rolling average is trusted
over the cold-start fallback. Below this, a single outlier (e.g., a
2000-token-input judge call against a long chunk) would distort the
estimate."""

_WINDOW_SAMPLES = 100
"""Most recent N judge calls per model included in the rolling
average. Large enough to smooth noise; small enough that the average
tracks recent provider price changes within hours of typical traffic."""

_WINDOW_DAYS = 30
"""Maximum lookback window. Anything older than this is excluded even
if the model hasn't seen :data:`_WINDOW_SAMPLES` recent calls.
Protects against price-stale data on low-traffic deployments."""

_CACHE_TTL_SECONDS = 300.0
"""In-process cache TTL. Tradeoff: shorter = newer calibration data
feeds in faster but more DB hits; longer = fewer DB hits but stale
calibration. 5 minutes is the same TTL as the Anthropic prompt cache
window — keeps the calibration consistent with the cache horizon."""


_cache: dict[str, tuple[float, Decimal]] = {}


async def estimate_judge_call_cost_usd(
    db: AsyncSession | None,
    *,
    judge_model: str,
) -> Decimal:
    """Return the estimated USD cost of one judge call to ``judge_model``.

    Computes the rolling average ``cost_estimate`` across the last
    :data:`_WINDOW_SAMPLES` ``inference_routing_log`` rows where
    ``routed_model = judge_model`` AND ``purpose = 'judge_paraphrase'``.
    Returns :data:`DEFAULT_PER_JUDGE_USD` if fewer than
    :data:`_MIN_SAMPLES` such rows exist.

    ``db=None`` skips the query and returns :data:`DEFAULT_PER_JUDGE_USD`.
    Honored by tests that exercise the activation-resolver logic without
    caring about cost calibration; production callers always pass a real
    session.

    Cached in-process per :data:`_CACHE_TTL_SECONDS`. Tests can use
    :func:`invalidate_cache` to reset between assertions.
    """

    if db is None:
        return DEFAULT_PER_JUDGE_USD

    now = time.monotonic()
    cached = _cache.get(judge_model)
    if cached is not None:
        cached_at, cached_value = cached
        if now - cached_at < _CACHE_TTL_SECONDS:
            return cached_value

    cutoff = datetime.now(UTC) - timedelta(days=_WINDOW_DAYS)
    recent = (
        select(InferenceRoutingLog.cost_estimate)
        .where(
            InferenceRoutingLog.routed_model == judge_model,
            InferenceRoutingLog.purpose == "judge_paraphrase",
            InferenceRoutingLog.cost_estimate.is_not(None),
            InferenceRoutingLog.timestamp >= cutoff,
        )
        .order_by(InferenceRoutingLog.timestamp.desc())
        .limit(_WINDOW_SAMPLES)
        .subquery()
    )
    stmt = select(
        func.avg(recent.c.cost_estimate),
        func.count(recent.c.cost_estimate),
    )

    try:
        result = await db.execute(stmt)
        avg_raw, count = result.one()
    except Exception as exc:
        # Defensive: a DB hiccup on the cost pre-flight should never
        # break chat-send. Fall back to the conservative default and
        # log loud — operators care about audit-trail visibility on
        # this failure mode.
        logger.warning(
            "judge cost calibration query failed: %s",
            exc,
            extra={
                "event": "citation_cost_query_error",
                "judge_model": judge_model,
                "error_type": type(exc).__name__,
            },
        )
        return DEFAULT_PER_JUDGE_USD

    if count is None or count < _MIN_SAMPLES or avg_raw is None:
        # Cold start — cache the fallback at a short TTL so cold-start
        # deployments don't query repeatedly. Caching the fallback
        # also limits DB load if a misconfigured model name is asked
        # about hundreds of times per minute.
        _cache[judge_model] = (now, DEFAULT_PER_JUDGE_USD)
        return DEFAULT_PER_JUDGE_USD

    estimate = Decimal(str(avg_raw))
    _cache[judge_model] = (now, estimate)
    return estimate


def invalidate_cache(judge_model: str | None = None) -> None:
    """Reset the in-process cache.

    Tests call this between assertions. Operators can call it via an
    admin endpoint (not currently exposed) when they know prices have
    shifted out of band. ``judge_model=None`` clears all entries.
    """

    if judge_model is None:
        _cache.clear()
    else:
        _cache.pop(judge_model, None)
