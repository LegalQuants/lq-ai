"""Smoke test: the mcp SDK is installed and the client surface imports.

PR4a depends on the official MCP SDK (client-only: the gateway speaks MCP as
the sole egress, ADR 0014 + WS2 spec D1). This guards the dependency pin so a
botched resolution (e.g. sse-starlette pulling starlette 1.x and breaking
fastapi) fails loudly here rather than deep in adapter tests."""

import pytest


@pytest.mark.unit
def test_mcp_client_surface_importable() -> None:
    from mcp import ClientSession  # noqa: F401
    from mcp.client.streamable_http import streamablehttp_client  # noqa: F401
    from mcp.types import ToolAnnotations  # noqa: F401
