"""Unit tests for MCPToolProviderAdapter (Task 3 — injected fake session, no network)."""

from contextlib import asynccontextmanager

import pytest

from app.config import ToolProviderConfig
from app.providers.tool.mcp import MCPToolProviderAdapter


class _FakeTool:
    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict,
        annotations: object = None,
    ) -> None:
        self.name = name
        self.description = description
        self.inputSchema = input_schema
        self.annotations = annotations


class _Ann:
    def __init__(self, read_only: bool | None = None, destructive: bool | None = None) -> None:
        self.readOnlyHint = read_only
        self.destructiveHint = destructive


class _FakeResult:
    def __init__(
        self,
        tools: list | None = None,
        content: object = None,
        is_error: bool = False,
    ) -> None:
        self.tools = tools or []
        self.content = content
        self.isError = is_error

    def model_dump(self, mode: str = "json") -> dict:
        return {"content": self.content}


class _FakeSession:
    def __init__(
        self,
        tools: list | None = None,
        call_result: _FakeResult | None = None,
    ) -> None:
        self._tools = tools or []
        self._call_result = call_result

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> _FakeResult:
        return _FakeResult(tools=self._tools)

    async def call_tool(self, name: str, args: dict) -> _FakeResult | None:
        return self._call_result


def _cfg() -> ToolProviderConfig:
    return ToolProviderConfig(
        name="acme-mcp",
        type="mcp",
        base_url="https://mcp.acme.example/sse",
        egress_tier=2,
        allowlist={"hosts": ["mcp.acme.example"]},
        auth="none",
    )


def _adapter(session: _FakeSession, monkeypatch: pytest.MonkeyPatch) -> MCPToolProviderAdapter:
    from app.providers.tool import egress

    monkeypatch.setattr(egress, "_resolve_ips", lambda host: ["93.184.216.34"])

    @asynccontextmanager
    async def factory(url: str, headers: object):  # type: ignore[misc]
        yield session

    return MCPToolProviderAdapter.from_config(_cfg(), session_factory=factory)


@pytest.mark.unit
async def test_list_tools_maps_annotations(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = [
        _FakeTool("read_doc", "reads", {"type": "object"}, _Ann(read_only=True)),
        _FakeTool("delete_doc", "deletes", {"type": "object"}, _Ann(destructive=True)),
        _FakeTool("mystery", "no hints", {"type": "object"}, None),
    ]
    specs = await _adapter(_FakeSession(tools=tools), monkeypatch).list_tools()
    by = {s.name: s for s in specs}
    assert by["read_doc"].read_only and not by["read_doc"].requires_confirmation
    assert by["delete_doc"].destructive and by["delete_doc"].requires_confirmation
    # un-annotated -> safe default: not auto-runnable
    assert by["mystery"].requires_confirmation and not by["mystery"].read_only


@pytest.mark.unit
async def test_invoke_tool_returns_tool_result(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _FakeResult(content=[{"type": "text", "text": "hi"}], is_error=False)
    out = await _adapter(_FakeSession(call_result=res), monkeypatch).invoke_tool(
        "read_doc", {"q": "x"}, request_id="r1"
    )
    assert out.provider == "acme-mcp"
    assert out.tool == "read_doc"
    assert out.payload == [{"type": "text", "text": "hi"}]


@pytest.mark.unit
async def test_invoke_tool_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.tool.base import ToolProviderError

    res = _FakeResult(content=[{"type": "text", "text": "boom"}], is_error=True)
    with pytest.raises(ToolProviderError):
        await _adapter(_FakeSession(call_result=res), monkeypatch).invoke_tool(
            "x", {}, request_id="r1"
        )


@pytest.mark.unit
async def test_validate_base_url_rejects_non_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.tool import egress
    from app.providers.tool.egress import EgressRefused

    monkeypatch.setattr(egress, "_resolve_ips", lambda host: ["93.184.216.34"])
    bad = ToolProviderConfig(
        name="x",
        type="mcp",
        base_url="https://evil.example/sse",
        egress_tier=2,
        allowlist={"hosts": ["mcp.acme.example"]},
        auth="none",
    )
    a = MCPToolProviderAdapter.from_config(bad)
    with pytest.raises(EgressRefused):
        a.validate_base_url()


# ---------------------------------------------------------------------------
# Auth header tests (cover MCPToolProviderAdapter._headers branches)
# ---------------------------------------------------------------------------


def _capturing_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth: str,
    api_key: str | None = None,
) -> tuple[MCPToolProviderAdapter, dict]:
    """Build an adapter whose session factory captures the headers it receives."""
    from app.providers.tool import egress

    monkeypatch.setattr(egress, "_resolve_ips", lambda host: ["93.184.216.34"])
    captured: dict = {}

    @asynccontextmanager
    async def factory(url: str, headers: object):  # type: ignore[misc]
        captured["headers"] = headers
        yield _FakeSession(tools=[])

    a = MCPToolProviderAdapter(
        name="acme-mcp",
        server_url="https://mcp.acme.example/sse",
        auth=auth,
        api_key=api_key,
        allowlist=["mcp.acme.example"],
        session_factory=factory,
    )
    return a, captured


@pytest.mark.unit
async def test_oauth_without_user_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """oauth auth with no user_token must raise ToolProviderError with the right code."""
    from app.providers.tool.base import ToolProviderError

    adapter, _ = _capturing_adapter(monkeypatch, auth="oauth")
    with pytest.raises(ToolProviderError) as exc_info:
        await adapter.list_tools()
    assert exc_info.value.details["code"] == "mcp_authorization_required"


@pytest.mark.unit
async def test_oauth_with_user_token_sets_bearer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """oauth auth with a user_token must forward it as a Bearer Authorization header."""
    adapter, captured = _capturing_adapter(monkeypatch, auth="oauth")
    await adapter.list_tools(user_token="user-tok")
    assert captured["headers"] == {"Authorization": "Bearer user-tok"}


@pytest.mark.unit
async def test_bearer_auth_sets_operator_key_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """bearer auth must inject the operator api_key as a Bearer Authorization header."""
    adapter, captured = _capturing_adapter(monkeypatch, auth="bearer", api_key="op-secret")
    await adapter.list_tools()
    assert captured["headers"] == {"Authorization": "Bearer op-secret"}


@pytest.mark.unit
async def test_none_auth_sends_no_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """auth=none must pass None as headers (no Authorization header sent)."""
    adapter, captured = _capturing_adapter(monkeypatch, auth="none")
    await adapter.list_tools()
    assert captured["headers"] is None
