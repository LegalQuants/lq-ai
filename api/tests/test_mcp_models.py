import pytest

from app.models.mcp import MCPToolCache


@pytest.mark.unit
def test_mcp_tool_cache_columns() -> None:
    cols = MCPToolCache.__table__.columns.keys()
    assert set(cols) >= {
        "provider_name",
        "tool_name",
        "description",
        "parameters",
        "read_only",
        "destructive",
        "requires_confirmation",
        "enabled",
        "discovered_at",
    }
    pk = {c.name for c in MCPToolCache.__table__.primary_key.columns}
    assert pk == {"provider_name", "tool_name"}
