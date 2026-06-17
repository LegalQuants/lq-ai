import pytest

from app.config import ToolProviderConfig
from app.providers.tool.base import ToolResult
from app.providers.tool.echo import EchoToolAdapter
from app.providers.tool.egress import EgressRefused


def _cfg(**over) -> ToolProviderConfig:
    base = {
        "name": "echo-test",
        "type": "echo",
        "base_url": "https://example.test",
        "egress_tier": 4,
        "allowlist": {"hosts": ["example.test"]},
    }
    base.update(over)
    return ToolProviderConfig.model_validate(base)


@pytest.mark.unit
async def test_echo_invoke_returns_input() -> None:
    adapter = EchoToolAdapter.from_config(_cfg())
    try:
        result = await adapter.invoke_tool("echo", {"msg": "hi"}, request_id="req_1")
    finally:
        await adapter.aclose()
    assert isinstance(result, ToolResult)
    assert result.provider == "echo-test"
    assert result.payload == {"echoed": {"msg": "hi"}}
    assert result.bytes_out > 0


@pytest.mark.unit
async def test_echo_lists_one_tool() -> None:
    adapter = EchoToolAdapter.from_config(_cfg())
    try:
        tools = await adapter.list_tools()
    finally:
        await adapter.aclose()
    assert [t.name for t in tools] == ["echo"]
    assert tools[0].read_only is True


@pytest.mark.unit
async def test_echo_rejects_unknown_tool() -> None:
    from app.providers.tool.base import ToolProviderError

    adapter = EchoToolAdapter.from_config(_cfg())
    try:
        with pytest.raises(ToolProviderError):
            await adapter.invoke_tool("nope", {}, request_id="req_1")
    finally:
        await adapter.aclose()


@pytest.mark.unit
async def test_echo_base_url_must_pass_egress_policy() -> None:
    # base_url host not in its own allowlist -> egress refusal at validation.
    with pytest.raises(EgressRefused):
        EchoToolAdapter.from_config(
            _cfg(base_url="https://evil.test", allowlist={"hosts": ["example.test"]})
        ).validate_base_url()
