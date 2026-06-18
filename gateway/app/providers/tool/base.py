"""Abstract :class:`ToolProviderAdapter` contract + shared types.

Mirrors the design of :mod:`app.providers.base` (the inference adapter
contract) but for non-inference egress: list the tools a provider offers,
invoke one, return structured provenance. Errors follow the same
public-safe, key-scrubbing discipline (CONTRIBUTING.md security rules).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import ProviderHealth

# --- Errors -------------------------------------------------------------------


class ToolProviderError(Exception):
    """Base class for tool-provider errors. Public-safe; never leak keys."""

    code: str = "tool_provider_error"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_envelope(self) -> dict[str, object]:
        return {
            "error": {"code": self.code, "message": self.message, "details": dict(self.details)}
        }


class ToolProviderAuthError(ToolProviderError):
    code = "unauthorized"


class ToolProviderHTTPError(ToolProviderError):
    code = "tool_provider_unavailable"

    def __init__(
        self, message: str, *, upstream_status: int, details: dict[str, object] | None = None
    ) -> None:
        merged: dict[str, object] = dict(details or {})
        merged["upstream_status"] = upstream_status
        super().__init__(message, details=merged)
        self.upstream_status = upstream_status


class ToolProviderInvalidRequestError(ToolProviderError):
    """Upstream rejected the request as malformed (non-auth 4xx).

    Aligns with the inference path's #155 posture: upstream 4xx is the
    caller's problem (bad citation/query), not a provider outage."""

    code = "invalid_request"

    def __init__(
        self, message: str, *, upstream_status: int, details: dict[str, object] | None = None
    ) -> None:
        merged: dict[str, object] = dict(details or {})
        merged["upstream_status"] = upstream_status
        super().__init__(message, details=merged)
        self.upstream_status = upstream_status


class ToolProviderNetworkError(ToolProviderError):
    code = "tool_provider_unavailable"


# --- Tool spec + result -------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """One model-callable tool a provider offers.

    ``parameters`` is a JSON-schema object. The metadata flags map to
    MikeOSS's ``readOnly``/``destructive``/``requiresConfirmation`` and are
    carried through to WS4's confirmation gates (ADR 0015 D2/D4)."""

    name: str
    description: str
    parameters: dict[str, Any]
    read_only: bool = True
    destructive: bool = False
    requires_confirmation: bool = False


@dataclass
class ToolResult:
    """Result of one tool invocation, with provenance + byte counts.

    ``payload`` is the structured tool output. ``skip_anonymization`` marks
    inbound public text (e.g. opinion bodies) that must reach the citation
    engine verbatim (ADR 0014 D5); the echo provider leaves it False."""

    provider: str
    tool: str
    payload: Any
    bytes_in: int = 0
    bytes_out: int = 0
    skip_anonymization: bool = False
    details: dict[str, object] = field(default_factory=dict)


# --- Adapter contract ---------------------------------------------------------


class ToolProviderAdapter(ABC):
    """Abstract contract for a tool/data-source provider adapter.

    Constructed once at startup, held in ``app.state.tool_adapters``, reused
    across requests. All outbound HTTP MUST go through ``guarded_egress``."""

    name: str

    @abstractmethod
    async def list_tools(self, *, user_token: str | None = None) -> list[ToolSpec]:
        """Return the model-callable tools this provider offers."""

    @abstractmethod
    async def invoke_tool(
        self, tool: str, args: dict[str, Any], *, request_id: str, user_token: str | None = None
    ) -> ToolResult:
        """Invoke ``tool`` with ``args``; return structured provenance."""

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Cheap reachability/credential probe."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release owned resources (HTTP clients, etc.)."""
