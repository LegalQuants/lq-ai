"""Tests for MCPServerConfig and the mcp.yaml loader merge (PR4a Task 2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

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
        oauth_client_id="lqai-acme",
        egress_tier=2,
        allowlist={"hosts": ["o.example"]},
    )
    assert s.to_tool_provider_config().auth == "oauth"


# --- PR4c: oauth_client_id field (Task 2) ------------------------------------


@pytest.mark.unit
def test_mcp_server_config_oauth_with_client_id_accepted() -> None:
    """auth='oauth' + oauth_client_id is accepted; client_id passes through."""
    s = MCPServerConfig(
        name="acme-oauth",
        server_url="https://mcp.acme.example/sse",
        auth="oauth",
        oauth_client_id="lqai-acme",
        egress_tier=2,
        allowlist={"hosts": ["mcp.acme.example", "auth.acme.example"]},
    )
    tp = s.to_tool_provider_config()
    assert tp.auth == "oauth"
    assert tp.oauth_client_id == "lqai-acme"


@pytest.mark.unit
def test_mcp_server_config_oauth_without_client_id_rejected() -> None:
    """auth='oauth' without oauth_client_id must be rejected at validation time."""
    with pytest.raises(ValidationError, match="oauth_client_id"):
        MCPServerConfig(
            name="oauth-no-client-id",
            server_url="https://mcp.example/sse",
            auth="oauth",
            egress_tier=2,
            allowlist={"hosts": ["mcp.example"]},
        )


@pytest.mark.unit
def test_mcp_server_config_non_oauth_does_not_require_client_id() -> None:
    """auth='none' and auth='bearer' do not require oauth_client_id."""
    # none auth
    s_none = MCPServerConfig(
        name="none-mcp",
        server_url="https://mcp.example/sse",
        auth="none",
        egress_tier=2,
        allowlist={"hosts": ["mcp.example"]},
    )
    assert s_none.oauth_client_id is None

    # bearer auth
    s_bearer = MCPServerConfig(
        name="bearer-mcp",
        server_url="https://mcp.example/sse",
        auth="bearer",
        api_key_env="MCP_TOKEN",
        egress_tier=2,
        allowlist={"hosts": ["mcp.example"]},
    )
    assert s_bearer.oauth_client_id is None


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


# --- Negative-path validator tests (F1) ---------------------------------------


@pytest.mark.unit
def test_mcp_server_bearer_without_key_raises() -> None:
    """auth='bearer' with no api_key_env or api_key_encrypted must raise."""
    with pytest.raises(ValidationError, match="api_key_env or api_key_encrypted"):
        MCPServerConfig(
            name="bearer-no-key",
            server_url="https://mcp.example/sse",
            auth="bearer",
            egress_tier=2,
            allowlist={"hosts": ["mcp.example"]},
        )


@pytest.mark.unit
def test_mcp_server_none_auth_with_key_raises() -> None:
    """auth='none' + api_key_env is a misconfiguration and must raise."""
    with pytest.raises(ValidationError, match="only valid with auth 'bearer'"):
        MCPServerConfig(
            name="none-with-key",
            server_url="https://mcp.example/sse",
            auth="none",
            api_key_env="SOME_TOKEN",
            egress_tier=2,
            allowlist={"hosts": ["mcp.example"]},
        )


@pytest.mark.unit
def test_mcp_server_oauth_with_key_raises() -> None:
    """auth='oauth' + api_key_env is a misconfiguration and must raise."""
    with pytest.raises(ValidationError, match="only valid with auth 'bearer'"):
        MCPServerConfig(
            name="oauth-with-key",
            server_url="https://mcp.example/sse",
            auth="oauth",
            api_key_env="SOME_TOKEN",
            egress_tier=2,
            allowlist={"hosts": ["mcp.example"]},
        )


# --- Duplicate tool_provider name detection (F2) ------------------------------


@pytest.mark.unit
def test_load_config_duplicate_mcp_server_name_raises(tmp_path: Path, example_env: None) -> None:
    """Two mcp_servers with the same name must raise at config load time.

    Uses two mcp_servers with identical names — the simplest way to trigger
    the duplicate-name guard in GatewayConfig._tool_provider_names_unique
    without needing a pre-existing tool_provider in gateway.yaml.example
    (the example's tool_providers block is commented out).
    """
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
        "  - name: acme-mcp\n"
        "    server_url: https://mcp2.acme.example/sse\n"
        "    auth: none\n"
        "    egress_tier: 2\n"
        "    allowlist: {hosts: [mcp2.acme.example]}\n"
    )
    from app.config_loader import ConfigLoadError

    with pytest.raises(ConfigLoadError, match="acme-mcp"):
        load_config(gw, mcp_path=mcp)
