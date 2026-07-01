from unittest.mock import AsyncMock, patch

import pytest

from app.chat.tool_schemas import (
    AUTHORITY_OPS,
    AUTHORITY_TOOL_SCHEMAS,
    RESEARCH_OPS,
    assemble_allowlist,
    mcp_function_name,
    parse_mcp_function_name,
)


class _FakeGateway:  # only what resolve_available_sources needs
    pass


@pytest.mark.asyncio
async def test_research_only_allowlist(db):
    with (
        patch(
            "app.chat.tool_schemas.get_capabilities",
            new=AsyncMock(
                return_value={
                    "enabled": True,
                    "providers": [{"name": "cl-prod", "type": "courtlistener"}],
                }
            ),
        ),
        patch(
            "app.chat.tool_schemas.research_resolve_provider", new=AsyncMock(return_value="cl-prod")
        ),
        patch("app.chat.tool_schemas.list_servers", new=AsyncMock(return_value=[])),
    ):
        al = await assemble_allowlist(db, gateway=_FakeGateway())
    assert set(al.specs) >= RESEARCH_OPS
    spec = al.resolve("search_case_law")
    assert spec.kind == "research" and spec.provider == "cl-prod" and spec.read_only


@pytest.mark.asyncio
async def test_mcp_only_allowlist(db):
    tools = [
        {
            "name": "get_doc",
            "description": "",
            "parameters": {"type": "object"},
            "read_only": True,
            "destructive": False,
            "requires_confirmation": False,
            "enabled": True,
        },
        {
            "name": "delete_doc",
            "description": "",
            "parameters": {"type": "object"},
            "read_only": False,
            "destructive": True,
            "requires_confirmation": True,
            "enabled": True,
        },
        {
            "name": "disabled_tool",
            "description": "",
            "parameters": {},
            "read_only": True,
            "destructive": False,
            "requires_confirmation": False,
            "enabled": False,
        },
    ]
    with (
        patch(
            "app.chat.tool_schemas.get_capabilities",
            new=AsyncMock(return_value={"enabled": False, "providers": []}),
        ),
        patch(
            "app.chat.tool_schemas.list_servers",
            new=AsyncMock(return_value=[{"name": "files", "type": "mcp"}]),
        ),
        patch("app.chat.tool_schemas.list_cached_tools", new=AsyncMock(return_value=tools)),
    ):
        al = await assemble_allowlist(db, gateway=_FakeGateway())
    assert mcp_function_name("files", "get_doc") in al.specs
    assert al.resolve(mcp_function_name("files", "delete_doc")).destructive is True
    # disabled tools are NOT in the allowlist
    assert mcp_function_name("files", "disabled_tool") not in al.specs


@pytest.mark.asyncio
async def test_empty_allowlist_when_nothing_enabled(db):
    with (
        patch(
            "app.chat.tool_schemas.get_capabilities",
            new=AsyncMock(return_value={"enabled": False, "providers": []}),
        ),
        patch("app.chat.tool_schemas.list_servers", new=AsyncMock(return_value=[])),
    ):
        al = await assemble_allowlist(db, gateway=_FakeGateway())
    assert al.specs == {}
    assert al.function_schemas() == []


def test_mcp_name_roundtrip():
    n = mcp_function_name("files", "get_doc")
    assert parse_mcp_function_name(n) == ("files", "get_doc")
    assert parse_mcp_function_name("verify_citations") is None


def test_authority_schemas_declare_search_and_get():
    assert set(AUTHORITY_OPS) == {"search_authority", "get_authority"}
    for op in AUTHORITY_OPS:
        schema = AUTHORITY_TOOL_SCHEMAS[op]
        assert schema.get("description")
        assert schema["parameters"]["type"] == "object"


class _FakeGovInfoSource:
    type = "govinfo"
    enabled = True
    ops = ("search_authority", "get_authority")


@pytest.mark.asyncio
async def test_assemble_allowlist_adds_authority_when_govinfo_available(db, monkeypatch):
    async def _fake_resolve(gateway):
        return [_FakeGovInfoSource()]

    monkeypatch.setattr("app.chat.tool_schemas.resolve_available_sources", _fake_resolve)
    with (
        patch(
            "app.chat.tool_schemas.get_capabilities",
            new=AsyncMock(return_value={"enabled": False, "providers": []}),
        ),
        patch("app.chat.tool_schemas.list_servers", new=AsyncMock(return_value=[])),
    ):
        allowlist = await assemble_allowlist(db, gateway=_FakeGateway(), request_id="r1")
    authority_specs = [s for s in allowlist.specs.values() if s.kind == "authority"]
    assert {s.tool for s in authority_specs} == {"search_authority", "get_authority"}
    assert all(s.provider == "govinfo" and s.read_only for s in authority_specs)


@pytest.mark.asyncio
async def test_assemble_allowlist_no_authority_when_absent(db, monkeypatch):
    async def _fake_resolve(gateway):
        return []

    monkeypatch.setattr("app.chat.tool_schemas.resolve_available_sources", _fake_resolve)
    with (
        patch(
            "app.chat.tool_schemas.get_capabilities",
            new=AsyncMock(return_value={"enabled": False, "providers": []}),
        ),
        patch("app.chat.tool_schemas.list_servers", new=AsyncMock(return_value=[])),
    ):
        allowlist = await assemble_allowlist(db, gateway=_FakeGateway(), request_id="r1")
    assert not any(s.kind == "authority" for s in allowlist.specs.values())


@pytest.mark.asyncio
async def test_assemble_allowlist_authority_failure_does_not_kill_other_ops(db, monkeypatch):
    async def _boom(gateway):
        raise RuntimeError("registry down")

    monkeypatch.setattr("app.chat.tool_schemas.resolve_available_sources", _boom)
    with (
        patch(
            "app.chat.tool_schemas.get_capabilities",
            new=AsyncMock(return_value={"enabled": False, "providers": []}),
        ),
        patch("app.chat.tool_schemas.list_servers", new=AsyncMock(return_value=[])),
    ):
        # Should not raise, and should still return a (possibly empty) allowlist.
        allowlist = await assemble_allowlist(db, gateway=_FakeGateway(), request_id="r1")
    assert not any(s.kind == "authority" for s in allowlist.specs.values())
