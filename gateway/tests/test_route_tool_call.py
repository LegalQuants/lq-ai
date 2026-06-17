"""Tests for Router.route_tool_call — governed egress path (ADR 0014 D2/D3/D4)."""

import pytest

from app.config import GatewayConfig
from app.providers.tool.echo import EchoToolAdapter
from app.providers.tool.ratelimit import FixedWindowRateLimiter
from app.router import Router, ToolEgressRefused
from app.tool_egress_log import RecordingToolEgressLogWriter


def _config() -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "echo-test",
                    "type": "echo",
                    "base_url": "https://example.test",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                    "rate_limit": {"requests_per_minute": 2},
                }
            ]
        }
    )


def _router(writer, clock=None):
    cfg = _config()
    adapter = EchoToolAdapter.from_config(cfg.tool_providers[0])
    limiter = FixedWindowRateLimiter(requests_per_minute=2, now=(clock or (lambda: 1000.0)))
    return Router(
        config=cfg,
        adapters={},
        tool_adapters={"echo-test": adapter},
        tool_egress_log=writer,
        tool_rate_limiter=limiter,
    )


@pytest.mark.unit
async def test_route_tool_call_happy_path_writes_audit_row() -> None:
    writer = RecordingToolEgressLogWriter()
    router = _router(writer)
    result = await router.route_tool_call(
        "echo-test", "echo", {"msg": "hi"}, request_id="req_1", max_allowed_tier=4
    )
    assert result.payload == {"echoed": {"msg": "hi"}}
    assert len(writer.rows) == 1
    assert writer.rows[0].refused is False
    assert writer.rows[0].tier == 4


@pytest.mark.unit
async def test_route_tool_call_refuses_when_egress_tier_exceeds_ceiling() -> None:
    writer = RecordingToolEgressLogWriter()
    router = _router(writer)
    with pytest.raises(ToolEgressRefused, match="egress_tier"):
        await router.route_tool_call(
            "echo-test", "echo", {"msg": "x"}, request_id="req_2", max_allowed_tier=3
        )
    assert writer.rows[-1].refused is True
    assert writer.rows[-1].refusal_reason is not None


@pytest.mark.unit
async def test_route_tool_call_refuses_unknown_provider() -> None:
    writer = RecordingToolEgressLogWriter()
    router = _router(writer)
    with pytest.raises(ToolEgressRefused, match="unknown"):
        await router.route_tool_call("missing", "echo", {}, request_id="req_3", max_allowed_tier=5)


@pytest.mark.unit
async def test_route_tool_call_enforces_rate_limit() -> None:
    writer = RecordingToolEgressLogWriter()
    router = _router(writer)
    for i in range(2):
        await router.route_tool_call(
            "echo-test", "echo", {}, request_id=f"r{i}", max_allowed_tier=4
        )
    with pytest.raises(ToolEgressRefused, match="rate"):
        await router.route_tool_call("echo-test", "echo", {}, request_id="r3", max_allowed_tier=4)
    assert writer.rows[-1].refused is True
