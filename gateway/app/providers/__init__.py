"""Provider adapters for the LQ.AI Inference Gateway.

Each adapter translates between the gateway's OpenAI-compatible surface
(:mod:`app.providers.openai_schema`) and a specific provider's native
wire format. The :class:`~app.providers.base.ProviderAdapter` abstract
base defines the contract; B3 ships :class:`~app.providers.anthropic.
AnthropicAdapter`; C6 added :class:`~app.providers.openai.OpenAIAdapter`
(embeddings only); B6 partial adds
:class:`~app.providers.ollama.OllamaAdapter` (chat completions for
Mode-2 air-gapped local inference).

Adapters are constructed once at startup and reused across requests
(they own a long-lived ``httpx.AsyncClient``). Lifespan teardown calls
:meth:`ProviderAdapter.aclose` on each so connection pools shut down
cleanly.
"""

from app.providers.anthropic import AnthropicAdapter
from app.providers.azure_openai import AzureOpenAIAdapter
from app.providers.base import (
    ProviderAdapter,
    ProviderAdapterError,
    ProviderAuthError,
    ProviderHealth,
    ProviderHTTPError,
    ProviderNetworkError,
    ProviderUnsupportedError,
)
from app.providers.ollama import OllamaAdapter, ProviderModelNotFound
from app.providers.openai import OpenAIAdapter
from app.providers.openai_schema import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    EmbeddingObject,
    EmbeddingsRequest,
    EmbeddingsResponse,
    EmbeddingsUsage,
    InlineSkillRef,
)

__all__ = [
    "AnthropicAdapter",
    "AzureOpenAIAdapter",
    "ChatCompletionChoice",
    "ChatCompletionChunk",
    "ChatCompletionChunkChoice",
    "ChatCompletionDelta",
    "ChatCompletionMessage",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatCompletionUsage",
    "EmbeddingObject",
    "EmbeddingsRequest",
    "EmbeddingsResponse",
    "EmbeddingsUsage",
    "InlineSkillRef",
    "OllamaAdapter",
    "OpenAIAdapter",
    "ProviderAdapter",
    "ProviderAdapterError",
    "ProviderAuthError",
    "ProviderHTTPError",
    "ProviderHealth",
    "ProviderModelNotFound",
    "ProviderNetworkError",
    "ProviderUnsupportedError",
]
