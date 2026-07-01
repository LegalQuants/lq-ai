"""Tool / data-source provider egress class (ADR 0014).

A tool provider is a sibling of the inference :class:`ProviderAdapter`,
invoked via ``invoke_tool`` rather than ``chat_completion``. All outbound
HTTP from a tool adapter MUST route through ``guarded_egress`` (ADR 0014 D2).
"""

from app.providers.tool.base import (
    ToolProviderAdapter,
    ToolProviderAuthError,
    ToolProviderError,
    ToolProviderHTTPError,
    ToolProviderInvalidRequestError,
    ToolProviderNetworkError,
    ToolResult,
    ToolSpec,
)
from app.providers.tool.courtlistener import CourtListenerToolAdapter
from app.providers.tool.echo import EchoToolAdapter
from app.providers.tool.edgar import EdgarToolAdapter
from app.providers.tool.govinfo import GovInfoToolAdapter

__all__ = [
    "CourtListenerToolAdapter",
    "EchoToolAdapter",
    "EdgarToolAdapter",
    "GovInfoToolAdapter",
    "ToolProviderAdapter",
    "ToolProviderAuthError",
    "ToolProviderError",
    "ToolProviderHTTPError",
    "ToolProviderInvalidRequestError",
    "ToolProviderNetworkError",
    "ToolResult",
    "ToolSpec",
]
