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
from app.research.registry import SOURCE_REGISTRY, resolve_available_sources
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

# Authority function-schema TEMPLATES (WS-E; generalized WS-E PR2a Task 3).
# Gated on the content-source registry (app.research.registry.resolve_
# available_sources), NOT on get_capabilities (which is CourtListener-only).
# All are read_only.
#
# One pair of tools (search_authority/get_authority) serves EVERY enabled
# authority source via a `source` argument — NOT one schema per source.
# Property names are the union across the registered adapters' real gateway
# contracts (GovInfo: collection/query, package_id; EDGAR: query/forms,
# external_ref); each provider's gateway tool ignores properties it doesn't
# recognise, so the model picks the properties relevant to the `source` it
# chose. These templates carry the *shared* description/parameters shape;
# `build_authority_tool_schemas` injects the per-turn `source` enum (the
# enabled sources) — a turn with zero enabled sources gets no authority
# tools at all.
AUTHORITY_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "search_authority": {
        "description": (
            "Full-text search an authoritative source: govinfo (U.S. Code / "
            "CFR — set 'collection' to 'USCODE' or 'CFR') or edgar (SEC "
            "company filings — optional 'forms' filter, e.g. '10-K,8-K'). "
            "Returns matching items with an external_ref; call get_authority "
            "to fetch an item's full text before quoting it."
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
                    "description": "GovInfo only: collection filter, 'USCODE' or 'CFR'.",
                },
                "forms": {
                    "type": "string",
                    "description": (
                        "EDGAR only: optional comma-separated form types, e.g. '10-K,8-K'."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    "get_authority": {
        "description": (
            "Fetch the full text of a specific authority item (from "
            "search_authority results) so its language can be quoted verbatim."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "package_id": {
                    "type": "string",
                    "description": "GovInfo only: package id, e.g. 'USCODE-2022-title17'.",
                },
                "external_ref": {
                    "type": "string",
                    "description": "EDGAR only: external_ref returned by search_authority.",
                },
            },
            "required": [],
        },
    },
}
AUTHORITY_OPS = frozenset(AUTHORITY_TOOL_SCHEMAS)


def build_authority_tool_schemas(enabled_sources: list[str]) -> list[dict[str, Any]]:
    """Build the per-turn authority function schemas for the enabled sources.

    Injects a `source` enum (the enabled authority source types, in registry
    order) into each op's shared parameter template. An empty
    ``enabled_sources`` yields ``[]`` — no authority tools offered this turn.

    Returns a list of ``{"name", "description", "parameters"}`` dicts (the
    same shape :func:`assemble_allowlist` already expects from
    ``AUTHORITY_TOOL_SCHEMAS.items()``).
    """
    if not enabled_sources:
        return []
    source_enum = {"type": "string", "enum": list(enabled_sources)}
    schemas: list[dict[str, Any]] = []
    for op, template in AUTHORITY_TOOL_SCHEMAS.items():
        properties = {"source": source_enum, **template["parameters"]["properties"]}
        required = ["source", *template["parameters"]["required"]]
        schemas.append(
            {
                "name": op,
                "description": template["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
        )
    return schemas


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

    # Authority ops (WS-E; registry-driven WS-E PR2a Task 3) gate on the
    # content-source registry, NOT on get_capabilities (which is
    # CourtListener-only).  Guarded independently: a registry/gateway hiccup
    # must not strip research/MCP tools (PR1a lesson).
    #
    # "Authority sources" = registry entries whose ops include the authority
    # ops (search_authority/get_authority) AND that are enabled in the
    # gateway. A single search_authority/get_authority ToolSpec pair covers
    # ALL of them; the model selects among them via the `source` argument
    # (see build_authority_tool_schemas). `provider` on the shared ToolSpec
    # is a best-effort default (the first enabled authority source, in
    # registry order) — it is NOT used to dispatch the call; the real source
    # is resolved per-call from the `source` argument in tool_loop.py.
    try:
        sources = await resolve_available_sources(gateway)
        enabled_authority: list[str] = []
        for s in sources:
            if not getattr(s, "enabled", False):
                continue
            reg_spec = SOURCE_REGISTRY.get(getattr(s, "type", None) or "")
            if reg_spec is None:
                continue
            if set(AUTHORITY_OPS) & set(reg_spec.ops):
                enabled_authority.append(s.type)

        authority_schemas = build_authority_tool_schemas(enabled_authority)
        for schema in authority_schemas:
            specs[schema["name"]] = ToolSpec(
                function_name=schema["name"],
                kind="authority",
                provider=enabled_authority[0],
                tool=schema["name"],
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
