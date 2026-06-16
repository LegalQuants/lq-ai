"""Abstract :class:`ProviderAdapter` contract and shared error types.

Every concrete adapter (Anthropic in B3; OpenAI / Vertex / Bedrock /
Ollama / vLLM in B6) implements this contract. The router (B4) holds a
mapping ``provider_name -> ProviderAdapter`` and dispatches each request
to the adapter selected by alias resolution.

Why not raise generic exceptions
--------------------------------

The gateway is the security boundary. Adapter errors must:

1. Map cleanly to an HTTP status the caller can act on.
2. Never leak provider keys, full request bodies, or upstream stack
   traces in their stringified form (CONTRIBUTING.md security rules).

The :class:`ProviderAdapterError` hierarchy below gives every adapter a
small, structured vocabulary; the route handler in
:mod:`app.api.inference` catches these and serializes them with the
``GatewayError`` envelope from ``docs/api/gateway-openapi.yaml``.

The ``lq_ai.errors`` namespace mentioned in CLAUDE.md does not exist
yet — that's a future cross-cutting package. Until it lands, B3 keeps
its exception types co-located with the adapter contract that produces
them. When ``lq_ai.errors`` is created (likely as part of B5 / B6 when
the backend gains a parallel client), these types will move there.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.providers.openai_schema import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingsRequest,
    EmbeddingsResponse,
)

# --- Errors -------------------------------------------------------------------


class ProviderAdapterError(Exception):
    """Base class for all adapter errors.

    Carries a stable ``code`` (used by the route handler to pick an HTTP
    status and a ``GatewayError.code`` value) and a public-safe
    ``message``. ``details`` is an optional ``dict`` shown to operators
    in the response envelope; adapters MUST NOT include API keys, full
    request bodies, or PII in ``details``.
    """

    code: str = "provider_error"
    """Stable identifier for this error class. Subclasses override."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_envelope(self) -> dict[str, object]:
        """Render as the ``GatewayError`` envelope shape."""

        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": dict(self.details),
            }
        }


class ProviderAuthError(ProviderAdapterError):
    """Provider rejected our credentials (401 / 403 from upstream).

    Maps to ``GatewayError.code = "unauthorized"`` per the OpenAPI surface.
    The adapter MUST scrub any echoed key material before raising.
    """

    code = "unauthorized"


class ProviderHTTPError(ProviderAdapterError):
    """Upstream returned a non-success HTTP status that is not auth.

    The adapter populates ``details["upstream_status"]`` with the integer
    status code so the route handler can map sensibly (e.g., upstream
    4xx -> gateway 400 ``invalid_request``, upstream 429 -> gateway 429,
    upstream 5xx -> gateway 502 ``provider_unavailable``).
    """

    code = "provider_unavailable"

    def __init__(
        self,
        message: str,
        *,
        upstream_status: int,
        details: dict[str, object] | None = None,
    ) -> None:
        merged: dict[str, object] = dict(details or {})
        merged["upstream_status"] = upstream_status
        super().__init__(message, details=merged)
        self.upstream_status = upstream_status


class ProviderNetworkError(ProviderAdapterError):
    """We failed to reach the provider (DNS, TCP, TLS, timeout)."""

    code = "provider_unavailable"


class ProviderUnsupportedError(ProviderAdapterError):
    """The adapter does not support this operation.

    Used by Anthropic's :meth:`AnthropicAdapter.embeddings` (Anthropic
    has no first-party embeddings endpoint as of this writing).
    """

    code = "not_implemented"


# --- Health -------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderHealth:
    """Result of a provider health probe.

    The admin endpoint ``GET /admin/v1/providers/health`` (PRD §4.5)
    returns a list of these per configured provider. ``latency_ms`` is
    set to ``None`` when ``reachable`` is ``False``.
    """

    name: str
    reachable: bool
    latency_ms: int | None = None
    error: str | None = None


# --- Adapter contract ---------------------------------------------------------


class ProviderAdapter(ABC):
    """Abstract contract for a provider adapter.

    Concrete adapters own a long-lived ``httpx.AsyncClient`` and translate
    between the gateway's OpenAI-compatible surface and the provider's
    native wire format. They are constructed once at gateway startup
    (typically in the lifespan) and reused across requests.

    Lifecycle::

        adapter = AnthropicAdapter.from_config(provider_cfg)  # startup
        ...  # serve traffic
        await adapter.aclose()  # shutdown

    Adapters MUST be safe to use concurrently from multiple coroutines —
    they share the underlying HTTP client.
    """

    name: str
    """The operator-chosen provider name (matches ``ProviderConfig.name``)."""

    @abstractmethod
    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        *,
        model: str,
        stream: bool,
    ) -> ChatCompletionResponse | AsyncIterator[ChatCompletionChunk]:
        """Run a chat completion against the upstream provider.

        ``model`` is the **provider-native** model string (already
        resolved from any LQ.AI alias). ``stream`` overrides
        ``request.stream`` — the router decides streaming based on the
        incoming HTTP request, not the body. Returning a value vs. an
        async iterator is determined by ``stream``.
        """

    @abstractmethod
    async def embeddings(
        self,
        request: EmbeddingsRequest,
        *,
        model: str,
    ) -> EmbeddingsResponse:
        """Compute embeddings against the upstream provider.

        Adapters whose provider has no embeddings endpoint raise
        :class:`ProviderUnsupportedError`.
        """

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Cheap probe of upstream reachability and credential validity.

        Implementations should pick the lightest-weight upstream endpoint
        available (typically a model-list call). The probe should respect
        a short timeout — admin/health calls aren't allowed to hang the
        admin surface.
        """

    @abstractmethod
    async def aclose(self) -> None:
        """Release any owned resources (HTTP clients, etc.)."""
