"""``echo`` tool provider — the PR1 proof-of-path adapter (ADR 0014).

Implements the full :class:`ToolProviderAdapter` contract and exercises the
egress-validation wiring, but returns its input instead of making a network
call, so unit tests need no live endpoint. Replaced by real providers
(CourtListener PR2, MCP PR4)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import ToolProviderConfig
from app.providers.base import ProviderHealth
from app.providers.tool.base import (
    ToolProviderAdapter,
    ToolProviderError,
    ToolResult,
    ToolSpec,
)
from app.providers.tool.egress import validate_egress_target

DEFAULT_TIMEOUT_SECONDS = 30.0


class EchoToolAdapter(ToolProviderAdapter):
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        allowlist: list[str],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._allowlist = allowlist
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url, timeout=DEFAULT_TIMEOUT_SECONDS
        )

    @classmethod
    def from_config(cls, provider: ToolProviderConfig) -> EchoToolAdapter:
        if provider.type != "echo":
            raise ValueError(f"EchoToolAdapter built from non-echo provider {provider.type!r}")
        return cls(
            name=provider.name,
            base_url=provider.base_url,
            allowlist=provider.allowlist.hosts,
        )

    def validate_base_url(self) -> None:
        """Confirm the configured base_url satisfies this provider's own
        egress policy (called at build time so a misconfig fails at startup)."""
        validate_egress_target(self._base_url + "/", allowlist=self._allowlist)

    async def list_tools(self, *, user_token: str | None = None) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="echo",
                description="Echoes its input arguments back. Test provider only.",
                parameters={"type": "object", "additionalProperties": True},
                read_only=True,
            )
        ]

    async def invoke_tool(
        self, tool: str, args: dict[str, Any], *, request_id: str, user_token: str | None = None
    ) -> ToolResult:
        if tool != "echo":
            raise ToolProviderError(f"unknown tool {tool!r} for echo provider")
        encoded = json.dumps(args).encode("utf-8")
        return ToolResult(
            provider=self.name,
            tool=tool,
            payload={"echoed": args},
            bytes_out=len(encoded),
            bytes_in=len(encoded),
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, reachable=True, latency_ms=0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
