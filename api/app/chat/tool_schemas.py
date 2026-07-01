"""Per-turn chat tool allowlist (PR5b).

Assembles the closed set of function schemas the chat model may call this
turn — fixed CourtListener research ops (when enabled) + operator-enabled
MCP tools — and resolves a model-emitted function name back to a typed
:class:`ToolSpec`. The allowlist IS the closed set (ADR 0015, alt A): the
model picks among allowed tools and cannot reach beyond them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.service import list_cached_tools, list_servers
from app.research.registry import resolve_available_sources
from app.research.service import _resolve_provider as research_resolve_provider, get_capabilities

log = logging.getLogger(__name__)

MCP_NAME_PREFIX = "mcp__"
_MCP_SEP = "__"

# Fixed CourtListener research function schemas (OpenAI `parameters` shape).
# All are read_only. `op` is the research-service op name AND the
# tool_call_log `tool` column value.
RESEARCH_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "verify_citations": {
        "description": "Verify legal citations in text against CourtListener; "
        "returns each citation's match status.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text containing citations."}},
            "required": ["text"],
        },
    },
    "search_case_law": {
        "description": "Search CourtListener case law. Returns matching clusters.",
        "parameters": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query."},
                "cursor": {"type": "string", "description": "Pagination cursor (optional)."},
            },
            "required": ["q"],
        },
    },
    "get_cluster": {
        "description": "Fetch a CourtListener opinion cluster's metadata and opinions by cluster id.",
        "parameters": {
            "type": "object",
            "properties": {"cluster_id": {"type": "integer"}},
            "required": ["cluster_id"],
        },
    },
    "read_opinion": {
        "description": "Read the full plaintext of a fetched opinion by opinion id "
        "(the cluster must have been fetched via get_cluster first).",
        "parameters": {
            "type": "object",
            "properties": {"opinion_id": {"type": "integer"}},
            "required": ["opinion_id"],
        },
    },
    "find_in_case": {
        "description": "Find snippets matching a query within a fetched opinion.",
        "parameters": {
            "type": "object",
            "properties": {
                "opinion_id": {"type": "integer"},
                "query": {"type": "string"},
                "max_matches": {"type": "integer", "default": 3},
            },
            "required": ["opinion_id", "query"],
        },
    },
}
RESEARCH_OPS: frozenset[str] = frozenset(RESEARCH_TOOL_SCHEMAS)

# Fixed GovInfo authority function schemas (WS-E). Gated on the content-source
# registry (app.research.registry.resolve_available_sources), NOT on
# get_capabilities (which is CourtListener-only). All are read_only.
AUTHORITY_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "search_authority": {
        "description": (
            "Search free U.S. legal authority (U.S. Code, Code of Federal "
            "Regulations) on GovInfo for a statute or regulation. Returns "
            "matching packages with titles and identifiers; call get_authority "
            "to fetch a package's full text before quoting it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms, e.g. '17 USC 107 fair use'.",
                },
                "collection": {
                    "type": "string",
                    "description": "Optional collection filter: 'USCODE' or 'CFR'.",
                },
            },
            "required": ["query"],
        },
    },
    "get_authority": {
        "description": (
            "Fetch the full text of a specific GovInfo authority package (from "
            "search_authority results) so its language can be quoted verbatim."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "package_id": {
                    "type": "string",
                    "description": "GovInfo package id, e.g. 'USCODE-2022-title17'.",
                },
            },
            "required": ["package_id"],
        },
    },
}
AUTHORITY_OPS = frozenset(AUTHORITY_TOOL_SCHEMAS)


def mcp_function_name(server: str, tool: str) -> str:
    """Model-visible function name for an MCP tool: ``mcp__{server}__{tool}``."""
    return f"{MCP_NAME_PREFIX}{server}{_MCP_SEP}{tool}"


def parse_mcp_function_name(name: str) -> tuple[str, str] | None:
    """Inverse of :func:`mcp_function_name`; returns ``(server, tool)`` or None."""
    if not name.startswith(MCP_NAME_PREFIX):
        return None
    rest = name[len(MCP_NAME_PREFIX) :]
    server, sep, tool = rest.partition(_MCP_SEP)
    if not sep or not server or not tool:
        return None
    return server, tool


@dataclass(frozen=True)
class ToolSpec:
    function_name: str
    kind: Literal["research", "mcp", "authority"]
    provider: str
    tool: str
    read_only: bool
    destructive: bool
    requires_confirmation: bool
    parameters: dict[str, Any]
    description: str = ""


@dataclass
class ChatToolAllowlist:
    specs: dict[str, ToolSpec]

    def resolve(self, function_name: str) -> ToolSpec | None:
        return self.specs.get(function_name)

    def function_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": s.function_name,
                    "description": s.description,
                    "parameters": s.parameters,
                },
            }
            for s in self.specs.values()
        ]


async def assemble_allowlist(
    db: AsyncSession, *, gateway: Any, request_id: str | None = None
) -> ChatToolAllowlist:
    """Build the per-turn allowlist. Empty when no research/MCP/authority is configured."""
    specs: dict[str, ToolSpec] = {}

    caps = await get_capabilities(request_id=request_id)
    if caps.get("enabled"):
        provider = await research_resolve_provider(request_id=request_id)
        for op, schema in RESEARCH_TOOL_SCHEMAS.items():
            specs[op] = ToolSpec(
                function_name=op,
                kind="research",
                provider=provider,
                tool=op,
                read_only=True,
                destructive=False,
                requires_confirmation=False,
                parameters=schema["parameters"],
                description=schema["description"],
            )

    # Authority ops (WS-E) gate on the content-source registry, NOT on
    # get_capabilities (which is CourtListener-only).  Guarded independently:
    # a registry/gateway hiccup must not strip research/MCP tools (PR1a lesson).
    try:
        sources = await resolve_available_sources(gateway)
        govinfo = next(
            (
                s
                for s in sources
                if getattr(s, "type", None) == "govinfo" and getattr(s, "enabled", False)
            ),
            None,
        )
        if govinfo is not None:
            for op, schema in AUTHORITY_TOOL_SCHEMAS.items():
                specs[op] = ToolSpec(
                    function_name=op,
                    kind="authority",
                    provider="govinfo",
                    tool=op,
                    read_only=True,
                    destructive=False,
                    requires_confirmation=False,
                    parameters=schema["parameters"],
                    description=schema["description"],
                )
    except Exception:
        log.warning(
            "assemble_allowlist: authority source resolution failed — "
            "authority tools unavailable this turn",
            exc_info=True,
        )

    for server in await list_servers(request_id=request_id):
        name = server.get("name")
        if not name:
            continue
        for t in await list_cached_tools(db, provider=name):
            if not t.get("enabled"):
                continue
            fn = mcp_function_name(name, t["name"])
            specs[fn] = ToolSpec(
                function_name=fn,
                kind="mcp",
                provider=name,
                tool=t["name"],
                read_only=bool(t.get("read_only")),
                destructive=bool(t.get("destructive")),
                requires_confirmation=bool(t.get("requires_confirmation")),
                parameters=t.get("parameters") or {"type": "object", "properties": {}},
                description=t.get("description") or "",
            )

    return ChatToolAllowlist(specs=specs)
