"""End-to-end integration test for the PR1 tool-egress path (ADR 0014).

Exercises the full chain without a network call:
    config → build_tool_adapter → Router.route_tool_call → audit row
"""

import pytest

from app.config import GatewayConfig
from app.main import build_tool_adapter
from app.router import Router
from app.tool_egress_log import RecordingToolEgressLogWriter


@pytest.mark.unit
async def test_end_to_end_echo_through_router(monkeypatch) -> None:
    """Config -> build_tool_adapter -> Router.route_tool_call -> audit row.
    Exercises every PR1 component together without a network call."""
    # build_tool_adapter validates base_url via DNS; example.test isn't real.
    monkeypatch.setattr(
        "app.providers.tool.egress._resolve_ips",
        lambda host: ["93.184.216.34"],
    )
    cfg = GatewayConfig.model_validate(
        {
            "tool_providers": [
                {
                    "name": "echo-test",
                    "type": "echo",
                    "base_url": "https://example.test",
                    "egress_tier": 4,
                    "allowlist": {"hosts": ["example.test"]},
                    "rate_limit": {"requests_per_minute": 10},
                }
            ]
        }
    )
    adapter = build_tool_adapter(cfg.tool_providers[0])
    assert adapter is not None
    writer = RecordingToolEgressLogWriter()
    router = Router(
        config=cfg,
        adapters={},
        tool_adapters={"echo-test": adapter},
        tool_egress_log=writer,
    )
    try:
        result = await router.route_tool_call(
            "echo-test", "echo", {"q": "hello"}, request_id="req_e2e", max_allowed_tier=5
        )
    finally:
        await adapter.aclose()
    assert result.payload == {"echoed": {"q": "hello"}}
    assert result.tier == 4
    assert len(writer.rows) == 1
    row = writer.rows[0]
    assert row.refused is False
    assert row.bytes_out and row.bytes_out > 0
    assert row.anonymization_applied is False  # honest: no transform in PR1
