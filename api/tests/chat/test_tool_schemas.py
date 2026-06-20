from unittest.mock import AsyncMock, patch

import pytest

from app.chat.tool_schemas import (
    RESEARCH_OPS,
    assemble_allowlist,
    mcp_function_name,
    parse_mcp_function_name,
)


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
        al = await assemble_allowlist(db)
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
        al = await assemble_allowlist(db)
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
        al = await assemble_allowlist(db)
    assert al.specs == {}
    assert al.function_schemas() == []


def test_mcp_name_roundtrip():
    n = mcp_function_name("files", "get_doc")
    assert parse_mcp_function_name(n) == ("files", "get_doc")
    assert parse_mcp_function_name("verify_citations") is None
