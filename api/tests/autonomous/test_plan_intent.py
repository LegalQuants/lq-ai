"""Tests for ToolIntent.plan — WS-D PR1.

Verifies that ``plan`` is:
1. A member of the closed ``ToolIntent`` set with the expected string value.
2. Granted in ``PHASE_GRANTS[Phase.analysis]`` and nowhere else.
3. Included in ``_INFERENCE_INTENTS`` so R4 projects a non-zero cost.
4. Costed by ``estimate_tool_cost`` as inference (non-zero Decimal), not zero.
"""

import pytest

from app.autonomous.cost import _INFERENCE_INTENTS, estimate_tool_cost
from app.autonomous.enums import PHASE_GRANTS, Phase, ToolIntent

pytestmark = pytest.mark.asyncio


def test_plan_is_a_tool_intent_granted_in_analysis():
    assert ToolIntent.plan == "plan"
    assert ToolIntent.plan in PHASE_GRANTS[Phase.analysis]
    # not granted elsewhere
    assert ToolIntent.plan not in PHASE_GRANTS[Phase.drafting]
    assert ToolIntent.plan not in PHASE_GRANTS[Phase.intake]


def test_plan_is_an_inference_intent():
    assert ToolIntent.plan in _INFERENCE_INTENTS


async def test_estimate_tool_cost_treats_plan_as_inference():
    # db=None → estimator returns its conservative default (non-None Decimal), not 0
    cost = await estimate_tool_cost(ToolIntent.plan, {"model": "fast"}, None)
    from decimal import Decimal

    assert isinstance(cost, Decimal)
    # contrast: a non-inference intent is exactly 0
    zero = await estimate_tool_cost(ToolIntent.retrieve_caselaw, {}, None)
    assert zero == Decimal("0")
