"""Throwaway MCP peer for the real-peer adapter tests (issue #525).

Run by file path as ``python mcp_peer_server.py <port>``. It serves the MCP
SDK's own ``FastMCP`` over streamable HTTP on ``127.0.0.1:<port>``, with one
tool per behaviour the gateway adapter has to map: read-only, destructive,
un-annotated and failing.

Run by path, this script puts ``gateway/tests`` first on ``sys.path``, so
nothing in that directory may shadow ``mcp``. It imports only ``mcp`` and the
standard library: no ``app`` code, and no dependence on the working directory.
"""

import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

SERVER_NAME = "lq-ai-test-peer"
CLAUSE_TEXT = "Clause {clause_id}: governed by the laws of Ontario."
ERROR_TEXT = "peer tool failed on purpose: {reason}"


def build_server(port: int) -> FastMCP:
    server = FastMCP(SERVER_NAME, host="127.0.0.1", port=port)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def lookup_clause(clause_id: str) -> str:
        """Return the text of one clause."""
        return CLAUSE_TEXT.format(clause_id=clause_id)

    @server.tool(annotations=ToolAnnotations(destructiveHint=True))
    def delete_clause(clause_id: str) -> str:
        """Delete one clause."""
        return f"deleted {clause_id}"

    @server.tool()
    def annotate_clause(clause_id: str, note: str) -> str:
        """Attach a note to one clause (no annotations declared)."""
        return f"noted {clause_id}: {note}"

    @server.tool()
    def explode(reason: str) -> str:
        """Always fail."""
        raise RuntimeError(ERROR_TEXT.format(reason=reason))

    return server


def main() -> None:
    port = int(sys.argv[1])
    build_server(port).run(transport="streamable-http")


if __name__ == "__main__":
    main()
