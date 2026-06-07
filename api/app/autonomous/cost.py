"""R4 cost wrapper for the autonomous executor (M4-A3.1).

Projects the USD cost of a tool call before the chokepoint
(:func:`~app.autonomous.nodes.guarded_tool_call`, M4-A3.3) decides
whether to permit it. Inference-bearing intents reuse the M2-E2
rolling-average estimator; local-only intents have zero marginal cost.

Cost model (per M4 implementation plan)
----------------------------------------
* ``run_skill`` / ``run_playbook`` — inference-bearing; delegate to
  :func:`~app.citation.cost.estimate_judge_call_cost_usd` which uses a
  per-model rolling average over the last 100 judge calls.
* ``retrieve_chunks`` / ``propose_memory`` / ``propose_precedent`` /
  ``emit_finding`` / ``emit_artifact`` / ``notify`` — local operations
  with no provider inference; marginal cost is zero for R4 pre-flight
  purposes (``emit_artifact`` writes storage + DB rows but burns no
  provider tokens, exactly like ``emit_finding``).

Usage::

    from app.autonomous.cost import estimate_tool_cost
    from app.autonomous.enums import ToolIntent

    projected = await estimate_tool_cost(ToolIntent.run_skill, params, db)
    if session.cost_total_usd + projected > session.max_cost_usd:
        raise CostCapReached("cost cap would be exceeded", projected_usd=float(projected))
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.citation.cost import estimate_judge_call_cost_usd

_INFERENCE_INTENTS: frozenset[ToolIntent] = frozenset(
    {ToolIntent.run_skill, ToolIntent.run_playbook}
)


async def estimate_tool_cost(
    intent: ToolIntent,
    params: dict[str, Any],
    db: AsyncSession | None,
) -> Decimal:
    """Project the USD cost of a tool call for the R4 pre-flight check.

    Inference-bearing intents (:attr:`~ToolIntent.run_skill`,
    :attr:`~ToolIntent.run_playbook`) reuse the M2-E2 rolling-average
    estimator keyed by model name. The ``params`` dict is expected to carry
    ``"judge_model"`` (preferred) or ``"model"`` for these intents.

    All other intents (``retrieve_chunks``, ``propose_memory``,
    ``propose_precedent``, ``emit_finding``, ``emit_artifact``,
    ``notify``) are local-only operations with no provider inference;
    this function returns :data:`decimal.Decimal` ``"0"`` for them
    without querying the DB.

    Args:
        intent: The :class:`~app.autonomous.enums.ToolIntent` being considered.
        params: The keyword-argument dict the tool call would receive. Used
            to extract the model name for inference-bearing intents.
        db: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`. ``None``
            is accepted (and passed through to the underlying estimator,
            which returns the conservative default in that case).

    Returns:
        A :class:`~decimal.Decimal` representing the projected USD cost.
    """

    if intent in _INFERENCE_INTENTS:
        model = params.get("judge_model") or params["model"]
        return await estimate_judge_call_cost_usd(db, judge_model=model)
    return Decimal("0")
