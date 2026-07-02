"""``mcp`` tool provider — Model Context Protocol egress (ADR 0014, WS2/PR4a).

The gateway is the sole egress AND the only MCP-protocol speaker (spec D1):
streamable_http sessions are stateful, so the holder of the connection must
speak MCP. Ports the proven client logic from
``web/backend/open_webui/utils/mcp/client.py`` behind an injectable session
factory so unit tests never touch the network. Every connect passes
``validate_egress_target`` (SSRF/allowlist)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from app.config import ToolProviderConfig
from app.providers.base import ProviderHealth
from app.providers.tool.base import (
    ToolProviderAdapter,
    ToolProviderError,
    ToolProviderNetworkError,
    ToolResult,
    ToolSpec,
)
from app.providers.tool.egress import validate_egress_target
from app.secrets import ProviderKeyResolver

SessionFactory = Callable[..., Any]  # (url, headers) -> async ctx mgr yielding a ClientSession


def _default_session_factory() -> SessionFactory:
    @asynccontextmanager
    async def factory(url: str, headers: dict[str, str] | None) -> AsyncIterator[Any]:
        # Port of web/backend/open_webui/utils/mcp/client.py connect/disconnect.
        from contextlib import AsyncExitStack

        import anyio
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with AsyncExitStack() as stack:
            transport = await stack.enter_async_context(streamablehttp_client(url, headers=headers))
            read_stream, write_stream, _ = transport
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            with anyio.fail_after(10):
                await session.initialize()
            yield session

    return factory


def _map_flags(annotations: Any) -> tuple[bool, bool, bool]:
    """(read_only, destructive, requires_confirmation) from MCP tool annotations.

    Safe default for un-annotated tools: not read-only, not destructive, but
    requires_confirmation=True (treat unknown as needing the PR5 gate)."""
    read_only = bool(getattr(annotations, "readOnlyHint", False)) if annotations else False
    destructive = bool(getattr(annotations, "destructiveHint", False)) if annotations else False
    if read_only and not destructive:
        return True, False, False
    if destructive:
        return False, True, True
    return False, False, True  # un-annotated / ambiguous -> confirm


class MCPToolProviderAdapter(ToolProviderAdapter):
    def __init__(
        self,
        *,
        name: str,
        server_url: str,
        auth: str,
        api_key: str | None,
        allowlist: list[str],
        session_factory: SessionFactory | None = None,
    ) -> None:
        self.name = name
        self._server_url = server_url
        self._auth = auth
        self._api_key = api_key
        self._allowlist = allowlist
        self._session_factory = session_factory or _default_session_factory()

    @classmethod
    def from_config(
        cls,
        provider: ToolProviderConfig,
        *,
        key_resolver: ProviderKeyResolver | None = None,
        session_factory: SessionFactory | None = None,
    ) -> MCPToolProviderAdapter:
        if provider.type != "mcp":
            raise ValueError(f"MCPToolProviderAdapter from non-mcp {provider.type!r}")
        auth = getattr(provider, "auth", "none")
        api_key: str | None = None
        if auth == "bearer":
            resolver = key_resolver or ProviderKeyResolver.from_environ()
            api_key = resolver.resolve(
                provider_name=provider.name,
                api_key_env=provider.api_key_env,
                api_key_encrypted=provider.api_key_encrypted,
            )
            if not api_key:
                raise ValueError(
                    f"MCP provider {provider.name!r}: bearer auth but no token resolved."
                )
        return cls(
            name=provider.name,
            server_url=provider.base_url,
            auth=auth,
            api_key=api_key,
            allowlist=provider.allowlist.hosts,
            session_factory=session_factory,
        )

    def validate_base_url(self) -> None:
        validate_egress_target(self._server_url, allowlist=self._allowlist)

    def _headers(self, user_token: str | None) -> dict[str, str] | None:
        if self._auth == "bearer" and self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        if self._auth == "oauth":
            if not user_token:
                raise ToolProviderError(
                    f"MCP server {self.name!r} requires per-user authorization",
                    details={"code": "mcp_authorization_required"},
                )
            return {"Authorization": f"Bearer {user_token}"}
        return None

    @asynccontextmanager
    async def _session(self, user_token: str | None) -> AsyncIterator[Any]:
        validate_egress_target(self._server_url, allowlist=self._allowlist)
        try:
            async with self._session_factory(self._server_url, self._headers(user_token)) as s:
                yield s
        except ToolProviderError:
            raise
        except Exception as exc:  # transport/protocol failure
            raise ToolProviderNetworkError(f"mcp session error: {exc}") from exc

    async def list_tools(self, *, user_token: str | None = None) -> list[ToolSpec]:
        # user_token extends the ABC signature; base ABC updated in PR4a Task 4
        async with self._session(user_token) as session:
            result = await session.list_tools()
        specs: list[ToolSpec] = []
        for tool in result.tools:
            read_only, destructive, requires_confirmation = _map_flags(
                getattr(tool, "annotations", None)
            )
            specs.append(
                ToolSpec(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=tool.inputSchema or {"type": "object"},
                    read_only=read_only,
                    destructive=destructive,
                    requires_confirmation=requires_confirmation,
                )
            )
        return specs

    async def invoke_tool(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        request_id: str,
        user_token: str | None = None,
    ) -> ToolResult:
        # user_token extends the ABC signature; base ABC updated in PR4a Task 4
        async with self._session(user_token) as session:
            result = await session.call_tool(tool, args)
        dumped = result.model_dump(mode="json")
        content = dumped.get("content")
        if getattr(result, "isError", False):
            raise ToolProviderError("mcp tool returned an error", details={"content": content})
        return ToolResult(
            provider=self.name,
            tool=tool,
            payload=content,
            bytes_out=len(json.dumps(args).encode("utf-8")),
            bytes_in=len(json.dumps(content).encode("utf-8")),
            skip_anonymization=False,
        )

    async def health_check(self) -> ProviderHealth:
        try:
            async with self._session(None):
                pass
        except ToolProviderError as exc:
            return ProviderHealth(name=self.name, reachable=False, error=str(exc))
        return ProviderHealth(name=self.name, reachable=True, latency_ms=0)

    async def aclose(self) -> None:
        return None
