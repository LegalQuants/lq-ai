from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
async def test_research_only_allowlist(db: AsyncSession) -> None:
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
    assert spec is not None
    assert spec.kind == "research" and spec.provider == "cl-prod" and spec.read_only


@pytest.mark.asyncio
async def test_mcp_only_allowlist(db: AsyncSession) -> None:
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
    delete_spec = al.resolve(mcp_function_name("files", "delete_doc"))
    assert delete_spec is not None
    assert delete_spec.destructive is True
    # disabled tools are NOT in the allowlist
    assert mcp_function_name("files", "disabled_tool") not in al.specs


@pytest.mark.asyncio
async def test_empty_allowlist_when_nothing_enabled(db: AsyncSession) -> None:
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


def test_mcp_name_roundtrip() -> None:
    n = mcp_function_name("files", "get_doc")
    assert parse_mcp_function_name(n) == ("files", "get_doc")
    assert parse_mcp_function_name("verify_citations") is None


def test_authority_schemas_declare_search_and_get() -> None:
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
async def test_assemble_allowlist_adds_authority_when_govinfo_available(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_resolve(gateway: object) -> list[object]:
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
async def test_assemble_allowlist_no_authority_when_absent(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_resolve(gateway: object) -> list[object]:
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
async def test_assemble_allowlist_authority_failure_does_not_kill_other_ops(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(gateway: object) -> list[object]:
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


# ---------------------------------------------------------------------------
# Registry-driven authority wiring (WS-E PR2a Task 3)
# ---------------------------------------------------------------------------

from app.chat.tool_schemas import build_authority_tool_schemas  # noqa: E402


def test_authority_source_enum_lists_enabled_sources() -> None:
    # both govinfo + edgar enabled → source enum has both
    schemas = build_authority_tool_schemas(enabled_sources=["govinfo", "edgar"])
    search = next(s for s in schemas if s["name"] == "search_authority")
    source_prop = search["parameters"]["properties"]["source"]
    assert set(source_prop["enum"]) == {"govinfo", "edgar"}


def test_authority_schemas_empty_when_no_sources() -> None:
    assert build_authority_tool_schemas(enabled_sources=[]) == []


def test_govinfo_only_still_works() -> None:
    schemas = build_authority_tool_schemas(enabled_sources=["govinfo"])
    search = next(s for s in schemas if s["name"] == "search_authority")
    assert search["parameters"]["properties"]["source"]["enum"] == ["govinfo"]


def test_authority_schemas_require_source_and_op_specific_fields() -> None:
    schemas = build_authority_tool_schemas(enabled_sources=["govinfo", "edgar"])
    search = next(s for s in schemas if s["name"] == "search_authority")
    get_ = next(s for s in schemas if s["name"] == "get_authority")
    assert search["parameters"]["required"] == ["source", "query"]
    # get_authority has no single universal required id field (govinfo:
    # package_id, edgar: external_ref) — only `source` is universally required.
    assert get_["parameters"]["required"] == ["source"]
    assert "package_id" in get_["parameters"]["properties"]
    assert "external_ref" in get_["parameters"]["properties"]


class _FakeEdgarSource:
    type = "edgar"
    enabled = True


@pytest.mark.asyncio
async def test_assemble_allowlist_adds_both_sources_when_both_available(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_resolve(gateway: object) -> list[object]:
        return [_FakeGovInfoSource(), _FakeEdgarSource()]

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
    # ONE search_authority + ONE get_authority spec — not one pair per source.
    assert {s.tool for s in authority_specs} == {"search_authority", "get_authority"}
    assert len(authority_specs) == 2
    search_spec = allowlist.resolve("search_authority")
    assert search_spec is not None
    assert set(search_spec.parameters["properties"]["source"]["enum"]) == {"govinfo", "edgar"}


def test_authority_source_enum_is_per_op() -> None:
    # govinfo+edgar support both ops; eurlex supports only get_authority.
    schemas = build_authority_tool_schemas(enabled_sources=["govinfo", "edgar", "eurlex"])
    by_name = {s["name"]: s for s in schemas}
    assert set(by_name["get_authority"]["parameters"]["properties"]["source"]["enum"]) == {
        "govinfo",
        "edgar",
        "eurlex",
    }
    assert set(by_name["search_authority"]["parameters"]["properties"]["source"]["enum"]) == {
        "govinfo",
        "edgar",
    }


def test_authority_search_omitted_when_no_search_source() -> None:
    # only a get-only source enabled → no search_authority tool at all
    schemas = build_authority_tool_schemas(enabled_sources=["eurlex"])
    assert [s["name"] for s in schemas] == ["get_authority"]
