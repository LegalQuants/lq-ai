import pytest

from app.providers.tool.base import (
    ToolProviderAdapter,
    ToolProviderError,
    ToolResult,
    ToolSpec,
)


@pytest.mark.unit
def test_tool_provider_adapter_is_abstract() -> None:
    with pytest.raises(TypeError):
        ToolProviderAdapter()  # type: ignore[abstract]


@pytest.mark.unit
def test_tool_result_holds_provenance_and_counts() -> None:
    result = ToolResult(
        provider="echo-test",
        tool="echo",
        payload={"echoed": "hi"},
        bytes_in=2,
        bytes_out=2,
    )
    assert result.provider == "echo-test"
    assert result.payload == {"echoed": "hi"}
    assert result.bytes_in == 2


@pytest.mark.unit
def test_tool_spec_carries_metadata_flags() -> None:
    spec = ToolSpec(
        name="echo",
        description="echoes its input",
        parameters={"type": "object"},
        read_only=True,
        destructive=False,
        requires_confirmation=False,
    )
    assert spec.read_only is True
    assert spec.destructive is False


@pytest.mark.unit
def test_tool_provider_error_envelope() -> None:
    err = ToolProviderError("boom", details={"k": "v"})
    assert err.to_envelope()["error"]["code"] == "tool_provider_error"


@pytest.mark.unit
def test_invalid_request_error_code() -> None:
    from app.providers.tool.base import ToolProviderInvalidRequestError

    err = ToolProviderInvalidRequestError("bad reporter", upstream_status=400)
    assert err.code == "invalid_request"
    assert err.to_envelope()["error"]["details"]["upstream_status"] == 400
