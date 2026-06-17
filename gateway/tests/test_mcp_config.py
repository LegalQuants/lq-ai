"""Tests for MCPServerConfig and the mcp.yaml loader merge (PR4a Task 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import MCPServerConfig
from app.config_loader import load_config

# gateway/tests/ -> gateway/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"


@pytest.mark.unit
def test_mcp_server_config_synthesizes_tool_provider() -> None:
    s = MCPServerConfig(
        name="acme-mcp",
        server_url="https://mcp.acme.example/sse",
        auth="bearer",
        api_key_env="ACME_MCP_TOKEN",
        egress_tier=2,
        allowlist={"hosts": ["mcp.acme.example"]},
    )
    tp = s.to_tool_provider_config()
    assert tp.type == "mcp"
    assert tp.name == "acme-mcp"
    assert tp.base_url == "https://mcp.acme.example/sse"
    assert tp.egress_tier == 2
    assert tp.allowlist.hosts == ["mcp.acme.example"]
    assert tp.auth == "bearer"


@pytest.mark.unit
def test_mcp_server_config_oauth_needs_no_static_key() -> None:
    s = MCPServerConfig(
        name="oauth-mcp",
        server_url="https://o.example/sse",
        auth="oauth",
        egress_tier=2,
        allowlist={"hosts": ["o.example"]},
    )
    assert s.to_tool_provider_config().auth == "oauth"


@pytest.mark.unit
def test_load_config_merges_mcp_yaml(tmp_path: Path, example_env: None) -> None:
    gw = tmp_path / "gateway.yaml"
    gw.write_text(EXAMPLE_CONFIG.read_text())
    mcp = tmp_path / "mcp.yaml"
    mcp.write_text(
        "mcp_servers:\n"
        "  - name: acme-mcp\n"
        "    server_url: https://mcp.acme.example/sse\n"
        "    auth: none\n"
        "    egress_tier: 2\n"
        "    allowlist: {hosts: [mcp.acme.example]}\n"
    )
    cfg = load_config(gw, mcp_path=mcp)
    names = {tp.name: tp for tp in cfg.tool_providers}
    assert "acme-mcp" in names
    assert names["acme-mcp"].type == "mcp"


@pytest.mark.unit
def test_load_config_without_mcp_yaml_is_fine(tmp_path: Path, example_env: None) -> None:
    gw = tmp_path / "gateway.yaml"
    gw.write_text(EXAMPLE_CONFIG.read_text())
    cfg = load_config(gw, mcp_path=tmp_path / "does-not-exist.yaml")
    assert all(tp.type != "mcp" for tp in cfg.tool_providers)
