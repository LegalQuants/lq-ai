from unittest.mock import AsyncMock, patch

import pytest

from app.skills.connectors import resolve_available_connectors, unavailable_tool_usage
from app.skills.schema import LQAIFrontmatter, SkillFrontmatter, derive_summary


def test_frontmatter_parses_tool_usage():
    fm = LQAIFrontmatter.model_validate({"tool_usage": ["courtlistener"]})
    assert fm.tool_usage == ["courtlistener"]


def test_frontmatter_tool_usage_absent_is_none():
    assert LQAIFrontmatter.model_validate({}).tool_usage is None


def test_derive_summary_carries_tool_usage():
    front = SkillFrontmatter.model_validate(
        {"name": "x", "description": "d", "lq_ai": {"tool_usage": ["courtlistener"]}}
    )
    summary = derive_summary("x", front)
    assert summary.tool_usage == ["courtlistener"]


def test_unavailable_pure_function():
    assert unavailable_tool_usage(None, {"courtlistener"}) == []
    assert unavailable_tool_usage([], {"courtlistener"}) == []
    assert unavailable_tool_usage(["courtlistener"], None) is None  # undeterminable
    assert unavailable_tool_usage(["courtlistener"], {"courtlistener"}) == []
    assert unavailable_tool_usage(["courtlistener"], set()) == ["courtlistener"]
    assert unavailable_tool_usage(["CourtListener"], {"courtlistener"}) == []  # case-insensitive


@pytest.mark.asyncio
async def test_resolve_available_unions_caselaw_and_mcp():
    with (
        patch(
            "app.skills.connectors.get_capabilities",
            new=AsyncMock(return_value={"enabled": True, "providers": [{}]}),
        ),
        patch(
            "app.skills.connectors.list_servers",
            new=AsyncMock(return_value=[{"name": "files", "type": "mcp", "auth": "none"}]),
        ),
    ):
        got = await resolve_available_connectors()
    assert got == {"courtlistener", "files"}


@pytest.mark.asyncio
async def test_resolve_available_none_on_error():
    with (
        patch(
            "app.skills.connectors.get_capabilities",
            new=AsyncMock(side_effect=RuntimeError("gw down")),
        ),
        patch("app.skills.connectors.list_servers", new=AsyncMock(return_value=[])),
    ):
        assert await resolve_available_connectors() is None


@pytest.mark.asyncio
async def test_resolve_available_caselaw_disabled_excludes_courtlistener():
    with (
        patch(
            "app.skills.connectors.get_capabilities",
            new=AsyncMock(return_value={"enabled": False, "providers": []}),
        ),
        patch("app.skills.connectors.list_servers", new=AsyncMock(return_value=[])),
    ):
        assert await resolve_available_connectors() == set()
